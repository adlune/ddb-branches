"""Reads the connection settings from config.ini.

Every node uses the same MariaDB user, so the password lives here and not in the catalog.
If config.ini doesn't exist, the defaults of a fresh XAMPP install are used.
"""
import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, "config.ini")

DEFAULTS = {
    "host": "localhost",
    "port": "3306",
    "user": "root",
    "password": "",
    "catalog": "ddb_catalog",
}


def load():
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")
    section = parser["mariadb"] if parser.has_section("mariadb") else {}
    settings = {key: section.get(key, default) for key, default in DEFAULTS.items()}
    settings["port"] = int(settings["port"])
    return settings
