"""Global catalog (ddb_catalog): which nodes exist and which distributed tables exist."""
from . import db

# each node has its own range of Ids so records are unique in the whole system:
# node 1 -> 1000001, 1000002...   node 2 -> 2000001, 2000002...
ID_RANGE = 1_000_000


def first_id(node_id):
    return node_id * ID_RANGE + 1


def node_id_of(record_id):
    """The node that created a record, read from its Id (2000005 -> node 2)."""
    return record_id // ID_RANGE


# nodes

def nodes():
    with db.connect_catalog() as conn, conn.cursor() as cur:
        cur.execute("SELECT Id, Name, Host, Port, DbName FROM Nodes ORDER BY Id")
        return cur.fetchall()


def find_node(node_id):
    for node in nodes():
        if node["Id"] == node_id:
            return node
    return None


def register_node(node):
    with db.connect_catalog() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO Nodes (Id, Name, Host, Port, DbName) VALUES (%s, %s, %s, %s, %s)",
            (node["Id"], node["Name"], node["Host"], node["Port"], node["DbName"]),
        )


# distributed tables

def distributed_tables():
    """Returns {table name: [(column name, column type), ...]}."""
    with db.connect_catalog() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT TableName, Name, Type FROM DistributedColumns ORDER BY TableName, Id"
        )
        rows = cur.fetchall()
    tables = {}
    for row in rows:
        tables.setdefault(row["TableName"], []).append((row["Name"], row["Type"]))
    return tables


def register_table(name, columns):
    """Saves the table and its columns in one transaction: both rows or none."""
    with db.connect_catalog() as conn, conn.cursor() as cur:
        conn.begin()
        cur.execute("INSERT INTO DistributedTables (Name) VALUES (%s)", (name,))
        for column, column_type in columns:
            cur.execute(
                "INSERT INTO DistributedColumns (TableName, Name, Type) VALUES (%s, %s, %s)",
                (name, column, column_type),
            )
        conn.commit()
