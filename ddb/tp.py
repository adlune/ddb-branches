"""Procesador de Transacciones (TP).

Coordina transacciones que pueden involucrar a uno o varios nodos usando el
protocolo de compromiso en dos fases (2PC) mediante transacciones XA de
MySQL/MariaDB:

    Fase 1 (votación):  XA END + XA PREPARE en cada nodo participante.
    Fase 2 (decisión):  XA COMMIT en todos si todos votaron "sí";
                        XA ROLLBACK en todos si alguno falló.

Si sólo participa un nodo se usa la optimización de una fase
(XA COMMIT ... ONE PHASE).

Uso::

    with tp.begin("Insertar cliente") as tx:
        cur = tx.cursor(nodo)
        cur.execute("INSERT ...")
"""
import itertools
import os
import time

from .catalog import Catalog, Node


class TransactionError(Exception):
    """La transacción distribuida no pudo confirmarse."""


_counter = itertools.count(1)


class DistributedTransaction:
    def __init__(self, catalog: Catalog, log, label: str):
        self.catalog = catalog
        self.log = log
        self.label = label
        self.gtrid = f"ddb-{os.getpid()}-{int(time.time())}-{next(_counter)}"
        self._branches: dict[int, dict] = {}
        self._done = False

    # ------------------------------------------------------------------ util
    def _xid(self, node: Node) -> str:
        return f"'{self.gtrid}','n{node.id}'"

    def _exec(self, branch: dict, sql: str):
        with branch["conn"].cursor() as cur:
            cur.execute(sql)

    @property
    def nodes(self) -> list[Node]:
        return [b["node"] for b in self._branches.values()]

    # ---------------------------------------------------------- participación
    def cursor(self, node: Node):
        """Devuelve un cursor dentro de la rama XA del nodo (la abre si hace falta)."""
        branch = self._branches.get(node.id)
        if branch is None:
            conn = self.catalog.connect_node(node, autocommit=False)
            branch = {"node": node, "conn": conn, "state": "NEW"}
            try:
                self._exec(branch, f"XA START {self._xid(node)}")
            except Exception:
                conn.close()
                raise
            branch["state"] = "ACTIVE"
            self._branches[node.id] = branch
            self.log("TP", f"[{self.gtrid}] {node.name}: XA START (se une a «{self.label}»)")
        return branch["conn"].cursor()

    # ------------------------------------------------------------ terminación
    def commit(self):
        branches = list(self._branches.values())
        self._done = True
        if not branches:
            return
        try:
            for b in branches:
                self._exec(b, f"XA END {self._xid(b['node'])}")
                b["state"] = "IDLE"
            if len(branches) == 1:
                b = branches[0]
                self._exec(b, f"XA COMMIT {self._xid(b['node'])} ONE PHASE")
                b["state"] = "COMMITTED"
                self.log("TP", f"[{self.gtrid}] {b['node'].name}: COMMIT en una fase (único participante)")
                return
            # Fase 1: votación
            self.log("TP", f"[{self.gtrid}] Fase 1 (PREPARE) con {len(branches)} participantes")
            for b in branches:
                self._exec(b, f"XA PREPARE {self._xid(b['node'])}")
                b["state"] = "PREPARED"
                self.log("TP", f"[{self.gtrid}] {b['node'].name}: PREPARED — voto SÍ")
        except Exception as exc:
            self.log("TP", f"[{self.gtrid}] Fallo antes de la decisión: {exc}. Se aborta en todos los nodos.")
            self.rollback()
            raise TransactionError(f"La transacción «{self.label}» se abortó: {exc}") from exc

        # Fase 2: decisión global = COMMIT
        self.log("TP", f"[{self.gtrid}] Fase 2: decisión global COMMIT")
        failures = []
        for b in branches:
            try:
                self._exec(b, f"XA COMMIT {self._xid(b['node'])}")
                b["state"] = "COMMITTED"
                self.log("TP", f"[{self.gtrid}] {b['node'].name}: COMMIT")
            except Exception as exc:  # el nodo queda "in doubt" hasta recuperarse
                failures.append(f"{b['node'].name}: {exc}")
                self.log("TP", f"[{self.gtrid}] {b['node'].name}: COMMIT pendiente (en duda): {exc}")
        if failures:
            raise TransactionError(
                "La decisión fue COMMIT pero algunos nodos no confirmaron (quedan preparados "
                "y pueden recuperarse con XA RECOVER): " + "; ".join(failures)
            )

    def rollback(self):
        self._done = True
        for b in self._branches.values():
            node = b["node"]
            try:
                if b["state"] == "ACTIVE":
                    self._exec(b, f"XA END {self._xid(node)}")
                    b["state"] = "IDLE"
                if b["state"] in ("IDLE", "PREPARED"):
                    self._exec(b, f"XA ROLLBACK {self._xid(node)}")
                    b["state"] = "ROLLED_BACK"
                    self.log("TP", f"[{self.gtrid}] {node.name}: ROLLBACK")
            except Exception as exc:
                self.log("TP", f"[{self.gtrid}] {node.name}: error durante ROLLBACK: {exc}")

    def close(self):
        for b in self._branches.values():
            try:
                b["conn"].close()
            except Exception:
                pass
        self._branches.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None and not self._done:
                self.commit()
            elif not self._done:
                self.log("TP", f"[{self.gtrid}] Error en «{self.label}»: {exc}. Abortando.")
                self.rollback()
        finally:
            self.close()
        return False


class TransactionProcessor:
    def __init__(self, catalog: Catalog, log):
        self.catalog = catalog
        self.log = log

    def begin(self, label: str) -> DistributedTransaction:
        return DistributedTransaction(self.catalog, self.log, label)
