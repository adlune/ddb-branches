"""Transaction Processor (TP).

Every write in this system touches a single node: a client and its addresses are stored in the
same branch. So a local transaction on that node is enough to keep the data consistent: either
every statement is committed, or if one of them fails, all of them are rolled back.
"""
from . import db


def run(node, work):
    """Runs work(cursor) inside a transaction on the node and returns what work returns."""
    conn = db.connect_node(node, autocommit=False)
    try:
        with conn.cursor() as cur:
            result = work(cur)
        conn.commit()
        print(f"  [TP] COMMIT on {node['Name']}")
        return result
    except Exception:
        conn.rollback()
        print(f"  [TP] ROLLBACK on {node['Name']}")
        raise
    finally:
        conn.close()
