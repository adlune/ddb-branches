"""Connections to MariaDB: one to the catalog, and one to each node when it's needed."""
import re

import pymysql
import pymysql.cursors

from . import config

SETTINGS = config.load()

# table, column and database names typed by the user must match this before going into SQL
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def connect(host, port, database=None, autocommit=True):
    return pymysql.connect(
        host=host,
        port=int(port),
        user=SETTINGS["user"],
        password=SETTINGS["password"],
        database=database,
        charset="utf8mb4",
        autocommit=autocommit,
        connect_timeout=4,
        cursorclass=pymysql.cursors.DictCursor,  # rows come back as {column: value}
    )


def connect_catalog():
    return connect(SETTINGS["host"], SETTINGS["port"], SETTINGS["catalog"])


def connect_node(node, autocommit=True):
    """node is a row of the Nodes table: {"Id", "Name", "Host", "Port", "DbName"}."""
    return connect(node["Host"], node["Port"], node["DbName"], autocommit)


def is_identifier(name):
    return bool(IDENTIFIER.match(name))
