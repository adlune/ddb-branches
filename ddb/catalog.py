"""Catálogo global del sistema distribuido (base de datos ddb_catalog).

Además de la tabla ``Nodes`` definida en sql/create_databases.sql, el sistema
crea (si no existen) estas tablas de metadatos:

* ``NodeAuth``          credenciales opcionales por nodo (si un nodo usa un
                        usuario distinto al del catálogo).
* ``DistributedTables`` esquema global de cada tabla distribuida.
* ``Fragments``         fragmento horizontal de cada tabla en cada nodo y su
                        predicado de selección (lista de valores o rango).
"""
import json
from dataclasses import dataclass, field

from . import db
from .db import ConnInfo

# Cada nodo recibe un rango propio de identificadores para que las llaves
# primarias sean únicas globalmente: nodo 1 -> 1000001.., nodo 2 -> 2000001..
NODE_ID_RANGE = 1_000_000


def id_base(node_id: int) -> int:
    return node_id * NODE_ID_RANGE + 1


STRATEGY_NODE = "NODE"    # el usuario indica la sucursal de cada registro
STRATEGY_LIST = "LIST"    # por lista de valores de una columna
STRATEGY_RANGE = "RANGE"  # por rango de valores de una columna

STRATEGY_LABELS = {
    STRATEGY_NODE: "Por sucursal",
    STRATEGY_LIST: "Por lista de valores",
    STRATEGY_RANGE: "Por rango de valores",
}

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS NodeAuth (
        NodeId INT PRIMARY KEY,
        User VARCHAR(64) NOT NULL,
        Password VARCHAR(128) NOT NULL DEFAULT '',
        FOREIGN KEY (NodeId) REFERENCES Nodes(Id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS DistributedTables (
        Name VARCHAR(64) PRIMARY KEY,
        Columns TEXT NOT NULL,
        Strategy VARCHAR(10) NOT NULL,
        FragmentColumn VARCHAR(64) NULL,
        IsSystem TINYINT NOT NULL DEFAULT 0,
        CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS Fragments (
        TableName VARCHAR(64) NOT NULL,
        NodeId INT NOT NULL,
        Predicate TEXT NULL,
        PRIMARY KEY (TableName, NodeId),
        FOREIGN KEY (TableName) REFERENCES DistributedTables(Name) ON DELETE CASCADE,
        FOREIGN KEY (NodeId) REFERENCES Nodes(Id) ON DELETE CASCADE
    )
    """,
]

# Esquema de las tablas base de cada sucursal (igual al script SQL).
CLIENTS_DDL = """
CREATE TABLE Clients (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(50) NOT NULL,
    PaternalSurname VARCHAR(50) NOT NULL,
    MaternalSurname VARCHAR(50),
    RFC VARCHAR(13) NOT NULL UNIQUE
) AUTO_INCREMENT = {base}
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
) AUTO_INCREMENT = {base}
"""

SYSTEM_TABLES = {
    "Clients": [
        ("Name", "VARCHAR(50)", False),
        ("PaternalSurname", "VARCHAR(50)", False),
        ("MaternalSurname", "VARCHAR(50)", True),
        ("RFC", "VARCHAR(13)", False),
    ],
    "Addresses": [
        ("Street", "VARCHAR(100)", False),
        ("Number", "VARCHAR(10)", False),
        ("Neighborhood", "VARCHAR(100)", True),
        ("State", "VARCHAR(50)", False),
        ("ZIPCode", "CHAR(5)", False),
        ("ClientId", "INT", False),
    ],
}


@dataclass
class Node:
    id: int
    name: str
    host: str
    port: int
    db_name: str
    user: str | None = None
    password: str | None = None

    def __str__(self):
        return self.name


@dataclass
class Column:
    name: str
    type: str
    nullable: bool = True

    def to_dict(self):
        return {"name": self.name, "type": self.type, "nullable": self.nullable}


@dataclass
class DistTable:
    name: str
    columns: list[Column]
    strategy: str
    frag_column: str | None
    is_system: bool
    fragments: dict[int, dict | None] = field(default_factory=dict)

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name.lower() == (name or "").lower():
                return c
        return None

    @property
    def strategy_label(self):
        return STRATEGY_LABELS.get(self.strategy, self.strategy)


class Catalog:
    """Acceso al catálogo global: nodos, tablas distribuidas y fragmentos."""

    def __init__(self, info: ConnInfo):
        self.info = info

    # ---------------------------------------------------------------- conexión
    def conn(self, autocommit=True):
        return db.connect(self.info, self.info.database, autocommit)

    def node_conn_info(self, node: Node) -> ConnInfo:
        return ConnInfo(
            host=node.host,
            port=node.port,
            user=node.user or self.info.user,
            password=node.password if node.user else self.info.password,
            database=node.db_name,
        )

    def connect_node(self, node: Node, autocommit=True):
        return db.connect(self.node_conn_info(node), node.db_name, autocommit)

    # ------------------------------------------------------------------ schema
    def ensure_schema(self):
        """Crea las tablas de metadatos que falten y registra Clients/Addresses."""
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'Nodes'")
            if not cur.fetchone():
                raise RuntimeError(
                    f"La base de datos «{self.info.database}» no contiene la tabla Nodes. "
                    "Ejecuta primero sql/create_databases.sql."
                )
            for stmt in SCHEMA:
                cur.execute(stmt)
            for name, cols in SYSTEM_TABLES.items():
                columns = [Column(n, t, nl).to_dict() for n, t, nl in cols]
                cur.execute(
                    "INSERT IGNORE INTO DistributedTables (Name, Columns, Strategy, FragmentColumn, IsSystem) "
                    "VALUES (%s, %s, %s, NULL, 1)",
                    (name, json.dumps(columns), STRATEGY_NODE),
                )
                cur.execute(
                    "INSERT IGNORE INTO Fragments (TableName, NodeId, Predicate) "
                    "SELECT %s, Id, NULL FROM Nodes",
                    (name,),
                )

    # ------------------------------------------------------------------- nodos
    def nodes(self) -> list[Node]:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT n.Id, n.Name, n.Host, n.Port, n.DbName, a.User, a.Password "
                "FROM Nodes n LEFT JOIN NodeAuth a ON a.NodeId = n.Id ORDER BY n.Id"
            )
            return [
                Node(r["Id"], r["Name"], r["Host"], int(r["Port"]), r["DbName"], r["User"], r["Password"])
                for r in cur.fetchall()
            ]

    def node(self, node_id: int) -> Node:
        for n in self.nodes():
            if n.id == node_id:
                return n
        raise KeyError(f"No existe el nodo {node_id}")

    # --------------------------------------------------------- tablas/fragmentos
    def tables(self) -> list[DistTable]:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT * FROM DistributedTables ORDER BY IsSystem DESC, Name")
            rows = cur.fetchall()
            cur.execute("SELECT * FROM Fragments")
            frags = cur.fetchall()
        result = []
        for r in rows:
            cols = [Column(c["name"], c["type"], bool(c["nullable"])) for c in json.loads(r["Columns"])]
            t = DistTable(r["Name"], cols, r["Strategy"], r["FragmentColumn"], bool(r["IsSystem"]))
            for f in frags:
                if f["TableName"] == r["Name"]:
                    t.fragments[int(f["NodeId"])] = json.loads(f["Predicate"]) if f["Predicate"] else None
            result.append(t)
        return result

    def table(self, name: str) -> DistTable:
        for t in self.tables():
            if t.name.lower() == name.lower():
                return t
        raise KeyError(f"La tabla distribuida «{name}» no existe")
