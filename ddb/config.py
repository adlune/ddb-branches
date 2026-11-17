"""Lectura y escritura de config.ini (conexión al catálogo global)."""
import configparser
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, "config.ini")

DEFAULTS = {
    "host": "localhost",
    "port": "3306",
    "user": "root",
    "password": "",
    "database": "ddb_catalog",
}


def load() -> dict:
    cp = configparser.ConfigParser()
    cp.read(CONFIG_FILE, encoding="utf-8")
    section = cp["catalog"] if cp.has_section("catalog") else {}
    return {k: section.get(k, v) for k, v in DEFAULTS.items()}


def save(values: dict, include_password: bool = False) -> None:
    cp = configparser.ConfigParser()
    data = {k: str(values.get(k, DEFAULTS[k])) for k in DEFAULTS}
    if not include_password:
        data["password"] = ""
    cp["catalog"] = data
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        cp.write(fh)
