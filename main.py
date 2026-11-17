"""Console interface of the distributed system. Run it with: python main.py

This file only asks for data and prints results. Every operation is done by the Data Processor
(ddb/dp.py), so the user never chooses a database, only a branch.
"""
import unicodedata

import pymysql

from ddb import dp
from ddb.validation import ValidationError

CLIENT_FIELDS = [
    ("Name", "Name"),
    ("PaternalSurname", "Paternal surname"),
    ("MaternalSurname", "Maternal surname (optional)"),
    ("RFC", "RFC"),
]

ADDRESS_FIELDS = [
    ("Street", "Street"),
    ("Number", "Number"),
    ("Neighborhood", "Neighborhood (optional)"),
    ("State", "State"),
    ("ZIPCode", "ZIP code"),
]

CLIENT_COLUMNS = ["Branch", "Id", "Name", "PaternalSurname", "MaternalSurname", "RFC", "AddressId", "Address"]


# input and output helpers

def ask(label, default=None):
    """Reads a value. If there is a default, pressing Enter keeps it."""
    if default is None:
        return input(f"  {label}: ").strip()
    text = input(f"  {label} [{default}]: ").strip()
    return text or str(default)


def ask_int(label):
    text = ask(label)
    if not text.isdigit():
        raise ValidationError(f"{label} must be a number.")
    return int(text)


def ask_fields(fields, current=None):
    """Asks every field of a form. When updating, current has the values to keep with Enter."""
    current = current or {}
    return {key: ask(label, current.get(key)) for key, label in fields}


def choose(label, options, describe):
    """Prints a numbered list and returns the option chosen."""
    if not options:
        raise ValidationError(f"There are no {label.lower()}s to choose from.")
    print(f"  {label}:")
    for number, option in enumerate(options, start=1):
        print(f"    {number}. {describe(option)}")
    number = ask_int("Number")
    if not 1 <= number <= len(options):
        raise ValidationError("That number isn't in the list.")
    return options[number - 1]


def choose_branch():
    return choose("Branch", dp.nodes(), lambda node: node["Name"])


def choose_table():
    return choose("Table", sorted(dp.distributed_tables()), lambda table: table)


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
    client = ask_fields(CLIENT_FIELDS)
    address = None
    if ask("Add an address now? (y/n)", "y").lower() == "y":
        address = ask_fields(ADDRESS_FIELDS)
    client_id = dp.insert_client(node, client, address)
    print(f"\n  Client {client_id} saved in {node['Name']}.")


def insert_address():
    client_id = ask_int("Client Id")
    address_id = dp.insert_address(client_id, ask_fields(ADDRESS_FIELDS))
    print(f"\n  Address {address_id} saved.")


def update_client():
    client_id = ask_int("Client Id")
    current = dp.get_record("Clients", client_id)
    print("  Press Enter to keep the current value.")
    dp.update_client(client_id, ask_fields(CLIENT_FIELDS, current))
    print(f"\n  Client {client_id} updated.")


def update_address():
    address_id = ask_int("Address Id")
    current = dp.get_record("Addresses", address_id)
    print("  Press Enter to keep the current value.")
    dp.update_address(address_id, ask_fields(ADDRESS_FIELDS, current))
    print(f"\n  Address {address_id} updated.")


def search_clients():
    search_by = choose("Search by", ["name", "rfc", "address"], lambda option: option)
    text = ask("Text to search")
    print_rows(dp.search_clients(search_by, text), CLIENT_COLUMNS)


def list_clients():
    print_rows(dp.search_clients(), CLIENT_COLUMNS)


def create_table():
    name = ask("Table name")
    print("  The Id column is added automatically.")
    print("  Types: INT, BIGINT, DATE, DATETIME, TEXT, DECIMAL(10,2), VARCHAR(50), CHAR(5)...")
    columns = []
    while True:
        column = ask(f"Column {len(columns) + 1} name (Enter to finish)")
        if not column:
            break
        columns.append((column, ask(f"Type of {column}")))
    dp.create_distributed_table(name, columns)
    print(f"\n  Table {name} created on every branch.")


def insert_row():
    table = choose_table()
    node = choose_branch()
    print("  Leave a value empty to save it as NULL.")
    values = {column: ask(f"{column} ({column_type})") for column, column_type in dp.distributed_tables()[table]}
    row_id = dp.insert_row(table, node, values)
    print(f"\n  Row {row_id} saved in {node['Name']}.")


def show_table():
    table = choose_table()
    columns = ["Branch", "Id"] + [column for column, _ in dp.distributed_tables()[table]]
    print_rows(dp.show_table(table), columns)


def add_node():
    name = ask("Branch name")
    suggested = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace(" ", "_")
    host = ask("Host", "localhost")
    port = ask("Port", 3306)
    db_name = ask("Database name", f"ddb_{suggested}")
    node = dp.add_node(name, host, port, db_name)
    print(f"\n  Branch {node['Name']} added as node {node['Id']}.")


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
    print(f"Connected to the catalog. Branches: {branches}")

    while True:
        print("\n=== Distributed database: branches ===")
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
        print(f"\n--- {label} ---")
        try:
            action()
        except ValidationError as error:
            print(f"\n  Invalid data: {error}")
        except pymysql.MySQLError as error:
            print(f"\n  Database error: {error}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
