"""Console interface of the distributed system. Run it with: python main.py

This file only asks for data and prints results. Every operation is done by the Data Processor
(ddb/dp.py), so the user never chooses a database, only a branch.
"""
import sys
import unicodedata

import pymysql

from ddb import dp, validation
from ddb.validation import ValidationError

CANCEL_WORD = "cancel"

TITLE = """
  ██████╗ ██████╗ ██████╗     ██████╗ ██████╗  █████╗ ███╗   ██╗ ██████╗██╗  ██╗███████╗███████╗
  ██╔══██╗██╔══██╗██╔══██╗    ██╔══██╗██╔══██╗██╔══██╗████╗  ██║██╔════╝██║  ██║██╔════╝██╔════╝
  ██║  ██║██║  ██║██████╔╝    ██████╔╝██████╔╝███████║██╔██╗ ██║██║     ███████║█████╗  ███████╗
  ██║  ██║██║  ██║██╔══██╗    ██╔══██╗██╔══██╗██╔══██║██║╚██╗██║██║     ██╔══██║██╔══╝  ╚════██║
  ██████╔╝██████╔╝██████╔╝    ██████╔╝██║  ██║██║  ██║██║ ╚████║╚██████╗██║  ██║███████╗███████║
  ╚═════╝ ╚═════╝ ╚═════╝     ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝"""

RULE = "  " + "─" * 94

# (column, label, example of the expected format)
CLIENT_FIELDS = [
    ("Name", "Name", "Juan"),
    ("PaternalSurname", "Paternal surname", "López"),
    ("MaternalSurname", "Maternal surname, optional", "García"),
    ("RFC", "RFC", "LOGJ850312AB1"),
]

ADDRESS_FIELDS = [
    ("Street", "Street", "Av. Madero Poniente"),
    ("Number", "Number", "450 or 12-B"),
    ("Neighborhood", "Neighborhood, optional", "Centro"),
    ("State", "State", "Michoacán"),
    ("ZIPCode", "ZIP code, 5 digits", "58000"),
]

# format hints for the columns of distributed tables, by type (VARCHAR(50) -> VARCHAR)
TYPE_HINTS = {
    "INT": "whole number, e.g. 10",
    "BIGINT": "whole number, e.g. 10",
    "DECIMAL": "number with a dot, e.g. 12.50",
    "DATE": "YYYY-MM-DD, e.g. 2026-11-17",
    "DATETIME": "YYYY-MM-DD HH:MM:SS, e.g. 2026-11-17 14:30:00",
    "TEXT": "text",
    "VARCHAR": "text",
    "CHAR": "text",
}

CLIENT_COLUMNS = ["Branch", "Id", "Name", "PaternalSurname", "MaternalSurname", "RFC", "AddressId", "Address"]


# input and output helpers

class Cancelled(Exception):
    """The user typed the cancel word: stop the current option and go back to the menu."""


def ask(label, default=None):
    """Reads a value. If there is a default, pressing Enter keeps it."""
    if default is None or default == "":
        text = input(f"  {label}: ").strip()
    else:
        text = input(f"  {label} [{default}]: ").strip() or str(default)
    if text.lower() == CANCEL_WORD:
        raise Cancelled()
    return text


def ask_int(label):
    while True:
        text = ask(label)
        if text.isdigit():
            return int(text)
        print(f"  {label} must be a number.")


def ask_yes_no(label):
    while True:
        answer = ask(f"{label} (y/n)").lower()
        if answer in ("y", "n"):
            return answer == "y"
        print("  Type y or n.")


def ask_fields(fields, current=None):
    """Asks every field of a form. When updating, current has the values to keep with Enter.
    A field without a current value shows an example of the format."""
    current = current or {}
    values = {}
    for key, label, example in fields:
        if current.get(key):
            values[key] = ask(label, current[key])
        else:
            values[key] = ask(f"{label} (e.g. {example})")
    return values


def ask_form(fields, check, current=None):
    """Asks a form and checks it right away. If something is wrong, it says what and asks again,
    keeping what was already typed, so nothing is lost because of one wrong field."""
    values = current
    while True:
        values = ask_fields(fields, values)
        try:
            return check(values)
        except ValidationError as error:
            print(f"\n  {error} Fix it (Enter keeps what you typed):")


def choose(label, options, describe):
    """Prints a numbered list and returns the option chosen."""
    if not options:
        raise ValidationError(f"There are no {label.lower()}s to choose from.")
    print(f"  {label}:")
    for number, option in enumerate(options, start=1):
        print(f"    {number}. {describe(option)}")
    while True:
        number = ask_int("Number")
        if 1 <= number <= len(options):
            return options[number - 1]
        print("  That number isn't in the list.")


def choose_branch():
    return choose("Branch", dp.nodes(), lambda node: node["Name"])


def choose_table():
    return choose("Table", sorted(dp.distributed_tables()), lambda table: table)


def report_ok(message):
    """Tells the user that the operation went through."""
    print(f"\n  [OK] {message}")


def report_failed(message):
    """Tells the user that the operation didn't go through."""
    print(f"\n  [FAILED] {message}")
    print("  Nothing was changed in the database.")


def print_rows(rows, columns):
    if not rows:
        print("\n  No results.")
        return
    texts = [["" if row.get(column) is None else str(row[column]) for column in columns] for row in rows]
    widths = [max([len(column)] + [len(text[i]) for text in texts]) for i, column in enumerate(columns)]
    print()
    print("  " + "  ".join(column.ljust(width) for column, width in zip(columns, widths)))
    print("  " + "  ".join("-" * width for width in widths))
    for text in texts:
        print("  " + "  ".join(value.ljust(width) for value, width in zip(text, widths)))
    print(f"\n  {len(rows)} row(s)")


# menu options

def insert_client():
    node = choose_branch()
    client = ask_form(CLIENT_FIELDS, validation.client)
    address = None
    if ask_yes_no("Add an address now?"):
        address = ask_form(ADDRESS_FIELDS, validation.address)
    client_id = dp.insert_client(node, client, address)
    report_ok(f"Client {client_id} saved in {node['Name']}.")


def insert_address():
    client_id = ask_int("Client Id (e.g. 1000001, see List all clients)")
    address_id = dp.insert_address(client_id, ask_form(ADDRESS_FIELDS, validation.address))
    report_ok(f"Address {address_id} saved for client {client_id}.")


def update_client():
    client_id = ask_int("Client Id (e.g. 1000001, see List all clients)")
    current = dp.get_record("Clients", client_id)
    print("  Press Enter to keep the current value.")
    dp.update_client(client_id, ask_form(CLIENT_FIELDS, validation.client, current))
    report_ok(f"Client {client_id} updated.")


def update_address():
    address_id = ask_int("Address Id (e.g. 1000001, see AddressId in List all clients)")
    current = dp.get_record("Addresses", address_id)
    print("  Press Enter to keep the current value.")
    dp.update_address(address_id, ask_form(ADDRESS_FIELDS, validation.address, current))
    report_ok(f"Address {address_id} updated.")


def search_clients():
    search_by = choose("Search by", ["name", "rfc", "address"], lambda option: option)
    text = ask("Text to search (e.g. López, LOGJ or Madero)")
    print_rows(dp.search_clients(search_by, text), CLIENT_COLUMNS)


def list_clients():
    print_rows(dp.search_clients(), CLIENT_COLUMNS)


def create_table():
    name = ask("Table name (e.g. Products)")
    print("  The Id column is added automatically.")
    print("  Types: INT, BIGINT, DATE, DATETIME, TEXT, DECIMAL(10,2), VARCHAR(50), CHAR(5)...")
    columns = []
    while True:
        column = ask(f"Column {len(columns) + 1} name (e.g. Price, Enter to finish)")
        if not column:
            break
        columns.append((column, ask(f"Type of {column} (e.g. VARCHAR(50), INT or DECIMAL(10,2))")))
    dp.create_distributed_table(name, columns)
    report_ok(f"Table {name} created on every branch.")


def insert_row():
    table = choose_table()
    node = choose_branch()
    print("  Leave a value empty to save it as NULL.")
    values = {}
    for column, column_type in dp.distributed_tables()[table]:
        hint = TYPE_HINTS[column_type.split("(")[0]]
        values[column] = ask(f"{column} ({column_type}, {hint})")
    row_id = dp.insert_row(table, node, values)
    report_ok(f"Row {row_id} saved in {node['Name']}.")


def show_table():
    table = choose_table()
    columns = ["Branch", "Id"] + [column for column, _ in dp.distributed_tables()[table]]
    print_rows(dp.show_table(table), columns)


def add_node():
    name = ask("Branch name (e.g. Uruapan)")
    suggested = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace(" ", "_")
    host = ask("Host", "localhost")
    port = ask("Port", 3306)
    db_name = ask("Database name", f"ddb_{suggested}")
    node = dp.add_node(name, host, port, db_name)
    report_ok(f"Branch {node['Name']} added as node {node['Id']}.")


def list_nodes():
    rows = []
    for node in dp.nodes():
        status = "online" if dp.node_is_online(node) else "offline"
        rows.append({**node, "Status": status})
    print_rows(rows, ["Id", "Name", "Host", "Port", "DbName", "Status"])


MENU = [
    ("Insert client", insert_client),
    ("Add address to a client", insert_address),
    ("Update client", update_client),
    ("Update address", update_address),
    ("Search clients", search_clients),
    ("List all clients", list_clients),
    ("Create distributed table", create_table),
    ("Insert row in a distributed table", insert_row),
    ("Show a distributed table", show_table),
    ("Add node (branch)", add_node),
    ("List nodes", list_nodes),
]


def main():
    try:
        branches = ", ".join(node["Name"] for node in dp.nodes())
    except pymysql.MySQLError as error:
        print(f"Can't connect to the catalog: {error}")
        print("Check that MariaDB is running and that sql/create_databases.sql was run.")
        return
    print(TITLE)
    print()
    print("  Distributed database system for branches  ·  MariaDB")
    print("  Data Processor (DP) and Transaction Processor (TP)")
    print(RULE)
    print(f"  Connected to the global catalog. Branches: {branches}")

    while True:
        print(f"\n{RULE}\n  MAIN MENU\n{RULE}")
        for number, (label, _) in enumerate(MENU, start=1):
            print(f"  {number:>2}. {label}")
        print("   0. Exit")
        option = input("Option: ").strip()
        if option == "0":
            break
        if not option.isdigit() or not 1 <= int(option) <= len(MENU):
            print("  Invalid option.")
            continue
        label, action = MENU[int(option) - 1]
        print(f"\n--- {label} ---  (type '{CANCEL_WORD}' or press Ctrl+C to go back to the menu)")
        try:
            action()
        except (Cancelled, KeyboardInterrupt):
            print("\n  [CANCELLED] Nothing was changed in the database.")
        except ValidationError as error:
            report_failed(error)
        except pymysql.MySQLError as error:
            # pymysql errors look like (1366, "Incorrect integer value..."): keep only the text
            report_failed(f"The database rejected it: {error.args[-1]}")
        input("\n  Press Enter to go back to the menu...")  # so the result doesn't scroll away


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # the title uses block characters
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
