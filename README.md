# Data Processor (DP) and Transaction Processor (TP)

Console program for a distributed database with one MariaDB database per branch.
It starts with two branches, Morelia and Pátzcuaro, and new branches can be added from the
program. The databases are created by [sql/create_databases.sql](sql/create_databases.sql).

## Setup

- XAMPP (tested with MariaDB 10.4, user `root` without password).
- Python 3.10 or newer.

1. Create the databases:

   ```bash
   C:\xampp\mysql\bin\mysql.exe -u root --default-character-set=utf8mb4 -e "source sql/create_databases.sql"
   ```

2. Install the dependency:

   ```bash
   pip install -r requirements.txt
   ```

3. If your MariaDB user, password or port are different, copy **config.example.ini**
   as **config.ini** and change the values.

4. Run:

   ```bash
   python main.py
   ```

## Structure

```
Console menu (main.py)       asks for data and prints results
        │
        ▼
DP: Data Processor (ddb/dp.py)
   • reads the global catalog to know which nodes exist
   • sends each insert or update to the node where the record belongs
   • runs each search on every node and joins the results
        │  writes
        ▼
TP: Transaction Processor (ddb/tp.py)
   • runs each write as a transaction on its node: COMMIT, or ROLLBACK if something fails
        │
        ▼
Nodes: ddb_morelia, ddb_patzcuaro, ...       Global catalog: ddb_catalog
```

| File | Function |
|---|---|
| **main.py** | Console menu |
| **ddb/dp.py** | Data Processor |
| **ddb/tp.py** | Transaction Processor |
| **ddb/catalog.py** | Reads and writes the global catalog |
| **ddb/db.py** | Opens connections to the catalog and to the nodes |
| **ddb/config.py** | Reads **config.ini** |
| **ddb/validation.py** | Checks RFC, ZIP code and field lengths |

### Globally unique records

Each node has its own range of ids. Node **N** starts at **N × 1,000,000 + 1** (e. g. **Node 1 has 1000001**, **Node 2 has 2000001**, etc.). The id also says where the record is stored
(**2000005 ÷ 1,000,000 = node 2**). The DP uses that to send updates to the right node.

The RFC must also be unique in the whole system. **UNIQUE** only works inside one database, so the
DP checks every node before inserting or updating a client.

### Horizontal fragmentation by branch

**Clients**, **Addresses** and every table created from the menu have one fragment on each node.
A row is stored only in the fragment of its branch. To show a table, the DP runs the same query
on every node and joins the rows (the union of the fragments), adding a **Branch** column.

## Notes and limitations

- **CREATE TABLE** and **CREATE DATABASE** can't be rolled back. If creating a distributed table or
  a node fails halfway, the program drops what it already created.
- The RFC check and the insert are two separate steps. Two users inserting the same RFC at the
  same moment in different branches could both pass the check.
- If a node is offline, searches show the rows of the other nodes and print a warning. Inserting
  or updating a client needs every node online, because the RFC check asks all of them.
- The SQL script only drops the original three databases.
