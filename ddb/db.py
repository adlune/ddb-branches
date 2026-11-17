"""Utilidades de conexión a MySQL/MariaDB."""
import re
from dataclasses import dataclass

import pymysql
import pymysql.cursors

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


@dataclass
class ConnInfo:
    host: str
    port: int
    user: str
    password: str
    database: str | None = None


def connect(info: ConnInfo, database: str | None = None, autocommit: bool = True):
    return pymysql.connect(
        host=info.host,
        port=int(info.port),
        user=info.user,
        password=info.password or "",
        database=database if database is not None else info.database,
        charset="utf8mb4",
        autocommit=autocommit,
        connect_timeout=4,
        read_timeout=30,
        write_timeout=30,
        cursorclass=pymysql.cursors.DictCursor,
    )


def is_identifier(name: str) -> bool:
    return bool(IDENT_RE.match(name or ""))


def q(name: str) -> str:
    """Entrecomilla un identificador (tabla/columna/BD) tras validarlo."""
    if not is_identifier(name):
        raise ValueError(f"Identificador inválido: {name!r}")
    return f"`{name}`"
