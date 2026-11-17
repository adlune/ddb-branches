"""Data Processor (DP).

The user interface only talks to the DP. The DP reads the global catalog to know which nodes
exist, sends each insert or update to the node where the record belongs, and runs each search
on every node, joining the results. This way the user never needs to know in which branch
(database) a record is stored.
"""
import re

import pymysql

from . import catalog, db, tp, validation
from .validation import ValidationError

# column types allowed when the user creates a distributed table
TYPE_PATTERN = re.compile(
    r"^(INT|BIGINT|DATE|DATETIME|TEXT|DECIMAL\(\d{1,2},\d{1,2}\)|VARCHAR\(\d{1,4}\)|CHAR\(\d{1,3}\))$",
    re.IGNORECASE,
)

# tables that every node has from the start; a new node gets them with its own Id range
CLIENTS_DDL = """
CREATE TABLE Clients (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(50) NOT NULL,
    PaternalSurname VARCHAR(50) NOT NULL,
    MaternalSurname VARCHAR(50),
    RFC VARCHAR(13) NOT NULL UNIQUE
) AUTO_INCREMENT = {first_id}
"""

ADDRESSES_DDL = """
CREATE TABLE Addresses (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Street VARCHAR(100) NOT NULL,
    Number VARCHAR(10) NOT NULL,
    Neighborhood VARCHAR(100),
    State VARCHAR(50) NOT NULL,
    ZIPCode CHAR(5) NOT NULL,
    ClientId INT NOT NULL,
    FOREIGN KEY (ClientId) REFERENCES Clients(Id)
) AUTO_INCREMENT = {first_id}
"""


def log(message):
    print(f"  [DP] {message}")


def nodes():
    return catalog.nodes()


def distributed_tables():
    return catalog.distributed_tables()


# locating data

def node_of_record(record_id):
    """Finds the node that stores a record. The Id is enough: node N's Ids start at N * 1000000 + 1."""
    node = catalog.find_node(catalog.node_id_of(record_id))
    if node is None:
        raise ValidationError(f"No node owns the Id {record_id}.")
    log(f"Id {record_id} belongs to {node['Name']}")
    return node


def query_all_nodes(sql, params=(), allow_partial=True):
    """Runs the same SELECT on every node and joins the results (the union of the fragments).

    Each row gets a Branch column with the name of the node it came from. If a node doesn't
    answer, its rows are missing and a warning is printed, unless allow_partial is False.
    """
    all_nodes = nodes()
    log("querying " + ", ".join(node["Name"] for node in all_nodes))
    rows = []
    for node in all_nodes:
        try:
            with db.connect_node(node) as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                for row in cur.fetchall():
                    rows.append({"Branch": node["Name"], **row})
        except pymysql.MySQLError as error:
            if not allow_partial:
                raise
            log(f"warning: {node['Name']} didn't answer, results are partial ({error})")
    return rows


def get_record(table, record_id):
    """Reads one row of Clients or Addresses from the node that stores it."""
    node = node_of_record(record_id)
    with db.connect_node(node) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE Id = %s", (record_id,))
        row = cur.fetchone()
    if row is None:
        raise ValidationError(f"There is no record {record_id} in {table}.")
    return row


# clients and addresses

def check_rfc_is_unique(rfc, client_id=None):
    """The RFC must be unique in the whole system, not only in one node, so every node is asked."""
    rows = query_all_nodes("SELECT Id FROM Clients WHERE RFC = %s", (rfc,), allow_partial=False)
    for row in rows:
        if row["Id"] != client_id:
            raise ValidationError(f"The RFC {rfc} already belongs to client {row['Id']} ({row['Branch']}).")


def insert_client(node, client, address=None):
    """Inserts a client (and optionally its first address) in the node of its branch."""
    client = validation.client(client)
    if address is not None:
        address = validation.address(address)
    check_rfc_is_unique(client["RFC"])
    log(f"insert routed to {node['Name']} ({node['DbName']})")

    def work(cur):
        cur.execute(
            "INSERT INTO Clients (Name, PaternalSurname, MaternalSurname, RFC) VALUES (%s, %s, %s, %s)",
            (client["Name"], client["PaternalSurname"], client["MaternalSurname"], client["RFC"]),
        )
        client_id = cur.lastrowid
        if address is not None:
            insert_address_sql(cur, address, client_id)
        return client_id

    return tp.run(node, work)


def insert_address(client_id, address):
    """Adds an address to an existing client. It goes to the same node as the client."""
    address = validation.address(address)
    node = node_of_record(client_id)

    def work(cur):
        cur.execute("SELECT Id FROM Clients WHERE Id = %s", (client_id,))
        if cur.fetchone() is None:
            raise ValidationError(f"Client {client_id} doesn't exist.")
        return insert_address_sql(cur, address, client_id)

    return tp.run(node, work)


def insert_address_sql(cur, address, client_id):
    cur.execute(
        "INSERT INTO Addresses (Street, Number, Neighborhood, State, ZIPCode, ClientId) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (address["Street"], address["Number"], address["Neighborhood"], address["State"],
         address["ZIPCode"], client_id),
    )
    return cur.lastrowid


def update_client(client_id, client):
    client = validation.client(client)
    check_rfc_is_unique(client["RFC"], client_id)
    node = node_of_record(client_id)

    def work(cur):
        cur.execute(
            "UPDATE Clients SET Name = %s, PaternalSurname = %s, MaternalSurname = %s, RFC = %s WHERE Id = %s",
            (client["Name"], client["PaternalSurname"], client["MaternalSurname"], client["RFC"], client_id),
        )

    tp.run(node, work)


def update_address(address_id, address):
    address = validation.address(address)
    node = node_of_record(address_id)

    def work(cur):
        cur.execute(
            "UPDATE Addresses SET Street = %s, Number = %s, Neighborhood = %s, State = %s, ZIPCode = %s "
            "WHERE Id = %s",
            (address["Street"], address["Number"], address["Neighborhood"], address["State"],
             address["ZIPCode"], address_id),
        )

    tp.run(node, work)


# searches: one row per client and address (a client without addresses still shows up)

CLIENTS_WITH_ADDRESSES = """
    SELECT c.Id, c.Name, c.PaternalSurname, c.MaternalSurname, c.RFC, a.Id AS AddressId,
           CONCAT_WS(', ', CONCAT(a.Street, ' ', a.Number), a.Neighborhood, a.State, a.ZIPCode) AS Address
    FROM Clients c
    LEFT JOIN Addresses a ON a.ClientId = c.Id
"""

SEARCH_COLUMNS = {
    "name": "CONCAT_WS(' ', c.Name, c.PaternalSurname, c.MaternalSurname)",
    "rfc": "c.RFC",
    "address": "CONCAT_WS(' ', a.Street, a.Number, a.Neighborhood, a.State, a.ZIPCode)",
}


def search_clients(search_by=None, text=""):
    """Searches by "name", "rfc" or "address" on every node. Without search_by, lists all clients."""
    sql = CLIENTS_WITH_ADDRESSES
    params = ()
    if search_by is not None:
        text = text.strip()
        if not text:
            raise ValidationError("Type the text to search.")
        sql += f" WHERE {SEARCH_COLUMNS[search_by]} LIKE %s"
        params = (f"%{text}%",)
    sql += " ORDER BY c.Id, a.Id"
    return query_all_nodes(sql, params)


# distributed tables (horizontal fragmentation by branch)

def table_ddl(name, columns, node_id):
    """CREATE TABLE for one fragment. Every fragment gets an Id with the node's own range."""
    lines = ["Id INT AUTO_INCREMENT PRIMARY KEY"]
    lines += [f"`{column}` {column_type}" for column, column_type in columns]
    return f"CREATE TABLE `{name}` ({', '.join(lines)}) AUTO_INCREMENT = {catalog.first_id(node_id)}"


def create_distributed_table(name, columns):
    """Creates one fragment of the table on every node and registers the table in the catalog."""
    if not db.is_identifier(name):
        raise ValidationError("Invalid table name: use letters, digits and _, and don't start with a digit.")
    taken = [table.lower() for table in distributed_tables()] + ["clients", "addresses"]
    if name.lower() in taken:
        raise ValidationError(f"There is already a table named {name}.")
    if not columns:
        raise ValidationError("The table needs at least one column.")
    seen = ["id", "branch"]  # Id is added by the system, and searches add a Branch column
    for column, column_type in columns:
        if not db.is_identifier(column):
            raise ValidationError(f"Invalid column name: {column}.")
        if column.lower() in seen:
            raise ValidationError(f"Repeated or reserved column: {column} (Id and Branch are added automatically).")
        if not TYPE_PATTERN.match(column_type):
            raise ValidationError(f"Type not supported for {column}: {column_type}.")
        seen.append(column.lower())
    columns = [(column, column_type.upper()) for column, column_type in columns]

    created = []
    try:
        for node in nodes():
            with db.connect_node(node) as conn, conn.cursor() as cur:
                cur.execute(table_ddl(name, columns, node["Id"]))
            created.append(node)
            log(f"fragment of {name} created on {node['Name']}")
        catalog.register_table(name, columns)
        log(f"{name} registered in the catalog")
    except Exception:
        # CREATE TABLE can't be rolled back, so the fragments already created are dropped by hand
        for node in created:
            with db.connect_node(node) as conn, conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS `{name}`")
            log(f"fragment of {name} dropped on {node['Name']} (undo)")
        raise


def insert_row(table, node, values):
    """Inserts a row in the fragment of the chosen branch. Empty values are saved as NULL."""
    columns = [column for column, _ in distributed_tables()[table]]
    log(f"insert into {table} routed to {node['Name']}")

    def work(cur):
        cur.execute(
            f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            [values.get(column) or None for column in columns],
        )
        return cur.lastrowid

    return tp.run(node, work)


def show_table(table):
    """The whole table as the user sees it: the union of the fragments of every node."""
    return query_all_nodes(f"SELECT * FROM `{table}` ORDER BY Id")


# nodes

def node_is_online(node):
    try:
        with db.connect_node(node):
            return True
    except pymysql.MySQLError:
        return False


def add_node(name, host, port, db_name):
    """Creates the database of a new branch with all its tables, then registers it in the catalog."""
    name, host, db_name = name.strip(), host.strip(), db_name.strip()
    if not name or len(name) > 50:
        raise ValidationError("The branch name is required (50 characters at most).")
    if not host:
        raise ValidationError("The host is required.")
    if not db.is_identifier(db_name):
        raise ValidationError("Invalid database name: use letters, digits and _.")
    if not str(port).isdigit():
        raise ValidationError("The port must be a number.")
    current = nodes()
    if any(node["Name"].lower() == name.lower() for node in current):
        raise ValidationError(f"There is already a branch named {name}.")

    node_id = max(node["Id"] for node in current) + 1
    node = {"Id": node_id, "Name": name, "Host": host, "Port": int(port), "DbName": db_name}
    first_id = catalog.first_id(node_id)
    log(f"new node {name} gets Id {node_id}, its records start at {first_id}")

    conn = db.connect(host, port)  # no database selected: it doesn't exist yet
    created = False
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4")
            created = True
            cur.execute(f"USE `{db_name}`")
            cur.execute(CLIENTS_DDL.format(first_id=first_id))
            cur.execute(ADDRESSES_DDL.format(first_id=first_id))
            log(f"{db_name} created with Clients and Addresses")
            for table, columns in distributed_tables().items():
                cur.execute(table_ddl(table, columns, node_id))
                log(f"fragment of {table} created on {name}")
        catalog.register_node(node)
        log(f"{name} registered in the catalog")
        return node
    except Exception:
        # CREATE DATABASE can't be rolled back either, so the new database is dropped by hand
        if created:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE `{db_name}`")
            log(f"{db_name} dropped (undo)")
        raise
    finally:
        conn.close()
