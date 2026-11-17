"""Procesador de Datos (DP).

Recibe las peticiones de la interfaz y las traduce a operaciones sobre los
nodos usando el catálogo global, de modo que el usuario no necesita saber en
qué sucursal está físicamente cada registro:

* Localiza el nodo correcto para inserciones (sucursal del cliente o
  predicado de fragmentación de la tabla).
* Descompone las consultas globales en subconsultas a cada fragmento,
  ejecutadas en paralelo, y une los resultados.
* Aplica poda de fragmentos cuando el filtro determina un único nodo.
* Delegará al TP toda escritura para que sea atómica, aunque involucre
  a varios nodos (p. ej. mover un cliente de sucursal).
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import db, validation
from .catalog import (
    ADDRESSES_DDL,
    CLIENTS_DDL,
    STRATEGY_LIST,
    STRATEGY_NODE,
    STRATEGY_RANGE,
    Catalog,
    Column,
    DistTable,
    Node,
    id_base,
)
from .db import ConnInfo, q
from .tp import TransactionProcessor
from .validation import ValidationError

SEARCH_ALL = "all"
SEARCH_NAME = "name"
SEARCH_RFC = "rfc"
SEARCH_ADDRESS = "address"
SEARCH_LABELS = {SEARCH_ALL: "todos", SEARCH_NAME: "por nombre", SEARCH_RFC: "por RFC",
                 SEARCH_ADDRESS: "por domicilio"}

TYPE_RE = re.compile(
    r"^(INT|BIGINT|SMALLINT|TEXT|DATE|DATETIME|BOOLEAN|FLOAT|DOUBLE"
    r"|(VARCHAR|CHAR)\(\d{1,4}\)|DECIMAL\(\d{1,2},\d{1,2}\))$",
    re.IGNORECASE,
)
NUMERIC_PREFIXES = ("INT", "BIGINT", "SMALLINT", "DECIMAL", "FLOAT", "DOUBLE", "BOOLEAN")
FILTER_OPS = ("=", "<>", "<", "<=", ">", ">=", "LIKE")


class DistributedError(Exception):
    """Error de operación del sistema distribuido."""


def _display(value):
    if value is None:
        return ""
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    return value


class DataProcessor:
    def __init__(self, catalog: Catalog, log):
        self.catalog = catalog
        self.log = log
        self.tp = TransactionProcessor(catalog, log)

    # ============================================================ utilidades
    def nodes(self) -> list[Node]:
        return self.catalog.nodes()

    def _node(self, node_id: int) -> Node:
        return self.catalog.node(int(node_id))

    def _scatter(self, nodes: list[Node], fn):
        """Ejecuta fn(nodo, cursor) en paralelo en cada nodo.

        Devuelve (resultados {node_id: valor}, errores {nombre_nodo: mensaje}).
        """
        results, errors = {}, {}

        def task(node):
            with self.catalog.connect_node(node) as conn, conn.cursor() as cur:
                return fn(node, cur)

        if not nodes:
            return results, errors
        with ThreadPoolExecutor(max_workers=min(8, len(nodes))) as pool:
            futures = {pool.submit(task, n): n for n in nodes}
            for fut, node in futures.items():
                try:
                    results[node.id] = fut.result()
                except Exception as exc:
                    errors[node.name] = str(exc)
                    self.log("DP", f"{node.name}: nodo no disponible o error — {exc}")
        return results, errors

    def ping(self, node: Node) -> str | None:
        """None si el nodo responde, o el mensaje de error."""
        try:
            with self.catalog.connect_node(node) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return None
        except Exception as exc:
            return str(exc)

    # ================================================================ clientes
    _CLIENT_SELECT = """
        SELECT c.Id, c.Name, c.PaternalSurname, c.MaternalSurname, c.RFC,
               (SELECT CONCAT_WS(', ', CONCAT(a.Street, ' ', a.Number), a.Neighborhood,
                                  a.State, CONCAT('CP ', a.ZIPCode))
                  FROM Addresses a WHERE a.ClientId = c.Id ORDER BY a.Id LIMIT 1) AS MainAddress,
               (SELECT COUNT(*) FROM Addresses a WHERE a.ClientId = c.Id) AS NumAddresses
          FROM Clients c
    """

    def search_clients(self, mode: str, text: str = "", origin: Node | None = None,
                       scope_node_id: int | None = None):
        """Búsqueda global de clientes. Devuelve (filas, errores)."""
        text = (text or "").strip()
        where, params = [], []
        words = text.split()
        if mode != SEARCH_ALL and not words:
            raise ValidationError("Escribe el texto a buscar o usa «Listar todos».")
        if mode == SEARCH_NAME:
            for w in words:
                where.append("CONCAT_WS(' ', c.Name, c.PaternalSurname, c.MaternalSurname) LIKE %s")
                params.append(f"%{w}%")
        elif mode == SEARCH_RFC:
            where.append("c.RFC LIKE %s")
            params.append(f"%{text.upper()}%")
        elif mode == SEARCH_ADDRESS:
            for w in words:
                where.append(
                    "EXISTS (SELECT 1 FROM Addresses a WHERE a.ClientId = c.Id AND "
                    "CONCAT_WS(' ', a.Street, a.Number, a.Neighborhood, a.State, a.ZIPCode) LIKE %s)"
                )
                params.append(f"%{w}%")
        sql = self._CLIENT_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY c.Id"

        nodes = self.nodes()
        if scope_node_id is not None:
            nodes = [n for n in nodes if n.id == scope_node_id]
        origin_name = origin.name if origin else "?"
        self.log(
            "DP",
            f"Consulta de clientes desde {origin_name} ({SEARCH_LABELS.get(mode, mode)}"
            + (f": «{text}»" if text else "") + ") → "
            + ", ".join(f"{n.name} ({'local' if origin and n.id == origin.id else 'remoto'})" for n in nodes),
        )

        def run(node, cur):
            cur.execute(sql, params)
            return cur.fetchall()

        results, errors = self._scatter(nodes, run)
        rows = []
        for node in nodes:
            for r in results.get(node.id, []):
                r["NodeId"] = node.id
                r["Branch"] = node.name
                rows.append(r)
        self.log("DP", f"Unión de resultados: {len(rows)} cliente(s) de {len(results)} nodo(s)")
        return rows, errors

    def get_addresses(self, node_id: int, client_id: int):
        node = self._node(node_id)
        with self.catalog.connect_node(node) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM Addresses WHERE ClientId = %s ORDER BY Id", (client_id,))
            return cur.fetchall()

    def get_client(self, node_id: int, client_id: int):
        node = self._node(node_id)
        with self.catalog.connect_node(node) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM Clients WHERE Id = %s", (client_id,))
            return cur.fetchone()

    def _check_rfc_unique(self, rfc: str, exclude: tuple[int, int] | None = None):
        """El RFC debe ser único en TODO el sistema, no sólo en un nodo."""
        def run(node, cur):
            cur.execute("SELECT Id FROM Clients WHERE RFC = %s", (rfc,))
            return [r["Id"] for r in cur.fetchall()]

        results, errors = self._scatter(self.nodes(), run)
        if errors:
            raise DistributedError(
                "No se pudo verificar la unicidad global del RFC porque hay nodos sin respuesta: "
                + "; ".join(f"{k}: {v}" for k, v in errors.items())
            )
        for node_id, ids in results.items():
            for cid in ids:
                if exclude and exclude == (node_id, cid):
                    continue
                raise ValidationError(f"Ya existe un cliente con el RFC {rfc} (sucursal {self._node(node_id).name}, Id {cid}).")

    @staticmethod
    def _insert_client_sql(cur, client):
        cur.execute(
            "INSERT INTO Clients (Name, PaternalSurname, MaternalSurname, RFC) VALUES (%s, %s, %s, %s)",
            (client["Name"], client["PaternalSurname"], client["MaternalSurname"], client["RFC"]),
        )
        return cur.lastrowid

    @staticmethod
    def _insert_address_sql(cur, address, client_id):
        cur.execute(
            "INSERT INTO Addresses (Street, Number, Neighborhood, State, ZIPCode, ClientId) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (address["Street"], address["Number"], address["Neighborhood"], address["State"],
             address["ZIPCode"], client_id),
        )
        return cur.lastrowid

    def insert_client(self, node_id: int, client: dict, address: dict | None = None) -> int:
        client = validation.client(client)
        address = validation.address(address) if address else None
        node = self._node(node_id)
        self._check_rfc_unique(client["RFC"])
        self.log("DP", f"Insertar cliente {client['RFC']}: se enruta a la sucursal {node.name}")
        with self.tp.begin(f"Insertar cliente {client['RFC']}") as tx:
            cur = tx.cursor(node)
            client_id = self._insert_client_sql(cur, client)
            if address:
                self._insert_address_sql(cur, address, client_id)
        self.log("DP", f"Cliente {client_id} creado en {node.name}")
        return client_id

    def update_client(self, node_id: int, client_id: int, client: dict, new_node_id: int | None = None):
        """Actualiza un cliente. Si cambia de sucursal, se migra con sus direcciones (2PC)."""
        client = validation.client(client)
        node = self._node(node_id)
        target = self._node(new_node_id) if new_node_id and int(new_node_id) != node.id else None
        self._check_rfc_unique(client["RFC"], exclude=(node.id, int(client_id)))

        if target is None:
            with self.tp.begin(f"Actualizar cliente {client_id}") as tx:
                cur = tx.cursor(node)
                cur.execute(
                    "UPDATE Clients SET Name=%s, PaternalSurname=%s, MaternalSurname=%s, RFC=%s WHERE Id=%s",
                    (client["Name"], client["PaternalSurname"], client["MaternalSurname"], client["RFC"], client_id),
                )
                if cur.rowcount == 0 and not self.get_client(node.id, client_id):
                    raise DistributedError("El cliente ya no existe.")
            self.log("DP", f"Cliente {client_id} actualizado en {node.name}")
            return int(client_id)

        # Migración entre sucursales: transacción distribuida en ambos nodos.
        self.log("DP", f"Cliente {client_id}: cambio de sucursal {node.name} → {target.name} (migración)")
        with self.tp.begin(f"Migrar cliente {client_id} a {target.name}") as tx:
            src = tx.cursor(node)
            src.execute("SELECT * FROM Addresses WHERE ClientId = %s ORDER BY Id FOR UPDATE", (client_id,))
            addresses = src.fetchall()
            src.execute("DELETE FROM Addresses WHERE ClientId = %s", (client_id,))
            src.execute("DELETE FROM Clients WHERE Id = %s", (client_id,))
            if src.rowcount == 0:
                raise DistributedError("El cliente ya no existe en la sucursal de origen.")
            dst = tx.cursor(target)
            new_id = self._insert_client_sql(dst, client)
            for a in addresses:
                self._insert_address_sql(dst, a, new_id)
        self.log("DP", f"Cliente migrado: {node.name}#{client_id} → {target.name}#{new_id}")
        return new_id

    def delete_client(self, node_id: int, client_id: int):
        node = self._node(node_id)
        with self.tp.begin(f"Eliminar cliente {client_id}") as tx:
            cur = tx.cursor(node)
            cur.execute("DELETE FROM Addresses WHERE ClientId = %s", (client_id,))
            cur.execute("DELETE FROM Clients WHERE Id = %s", (client_id,))
        self.log("DP", f"Cliente {client_id} eliminado de {node.name}")

    def insert_address(self, node_id: int, client_id: int, address: dict) -> int:
        address = validation.address(address)
        node = self._node(node_id)
        self.log("DP", f"Nueva dirección para cliente {client_id}: se enruta a {node.name} (sucursal del cliente)")
        with self.tp.begin(f"Insertar dirección cliente {client_id}") as tx:
            cur = tx.cursor(node)
            cur.execute("SELECT Id FROM Clients WHERE Id = %s FOR UPDATE", (client_id,))
            if not cur.fetchone():
                raise DistributedError("El cliente no existe en su sucursal.")
            return self._insert_address_sql(cur, address, client_id)

    def update_address(self, node_id: int, address_id: int, address: dict):
        address = validation.address(address)
        node = self._node(node_id)
        with self.tp.begin(f"Actualizar dirección {address_id}") as tx:
            cur = tx.cursor(node)
            cur.execute(
                "UPDATE Addresses SET Street=%s, Number=%s, Neighborhood=%s, State=%s, ZIPCode=%s WHERE Id=%s",
                (address["Street"], address["Number"], address["Neighborhood"], address["State"],
                 address["ZIPCode"], address_id),
            )
        self.log("DP", f"Dirección {address_id} actualizada en {node.name}")

    def delete_address(self, node_id: int, address_id: int):
        node = self._node(node_id)
        with self.tp.begin(f"Eliminar dirección {address_id}") as tx:
            tx.cursor(node).execute("DELETE FROM Addresses WHERE Id = %s", (address_id,))
        self.log("DP", f"Dirección {address_id} eliminada de {node.name}")

    # ===================================================== tablas distribuidas
    def tables(self) -> list[DistTable]:
        return self.catalog.tables()

    @staticmethod
    def _is_numeric(col: Column) -> bool:
        return col.type.upper().startswith(NUMERIC_PREFIXES)

    def _key(self, col: Column, value):
        """Valor comparable para evaluar predicados de fragmentación."""
        if value is None:
            return None
        if self._is_numeric(col):
            try:
                return Decimal(str(value).strip())
            except InvalidOperation:
                raise ValidationError(f"«{col.name}» debe ser numérico (valor: {value!r}).")
        return str(value).strip().casefold()

    def _matches(self, table: DistTable, col: Column, pred, value) -> bool:
        if pred is None:
            return False
        key = self._key(col, value)
        if key is None:
            return False
        if table.strategy == STRATEGY_LIST:
            return key in {self._key(col, v) for v in pred.get("values", [])}
        if table.strategy == STRATEGY_RANGE:
            lo, hi = pred.get("min"), pred.get("max")
            if lo not in (None, "") and key < self._key(col, lo):
                return False
            if hi not in (None, "") and key > self._key(col, hi):
                return False
            return True
        return False

    def route(self, table: DistTable, values: dict, node_id: int | None = None) -> Node:
        """Determina el nodo (fragmento) donde debe almacenarse una fila."""
        nodes = {n.id: n for n in self.nodes()}
        if table.strategy == STRATEGY_NODE:
            if node_id is None:
                raise ValidationError("Selecciona la sucursal donde se registrará la fila.")
            return nodes[int(node_id)]
        col = table.column(table.frag_column)
        value = values.get(col.name)
        for nid, pred in table.fragments.items():
            if nid in nodes and self._matches(table, col, pred, value):
                return nodes[nid]
        raise ValidationError(
            f"Ningún fragmento de «{table.name}» acepta {col.name} = {value!r}. "
            "Revisa los predicados de fragmentación (pestaña Tablas distribuidas → Fragmentos)."
        )

    def validate_predicates(self, strategy: str, col: Column | None, preds: dict[int, dict | None]):
        """Comprueba que los fragmentos sean disjuntos (cada fila en un solo nodo)."""
        if strategy == STRATEGY_NODE:
            return
        if strategy == STRATEGY_LIST:
            seen = {}
            for nid, p in preds.items():
                for v in (p or {}).get("values", []):
                    k = self._key(col, v)
                    if k in seen and seen[k] != nid:
                        raise ValidationError(f"El valor «{v}» está asignado a más de un nodo.")
                    seen[k] = nid
        elif strategy == STRATEGY_RANGE:
            ranges = []
            for nid, p in preds.items():
                if not p:
                    continue
                lo = self._key(col, p.get("min")) if p.get("min") not in (None, "") else None
                hi = self._key(col, p.get("max")) if p.get("max") not in (None, "") else None
                if lo is not None and hi is not None and lo > hi:
                    raise ValidationError(f"Rango inválido para el nodo {nid}: mínimo mayor que máximo.")
                ranges.append((nid, lo, hi))
            for i, (n1, lo1, hi1) in enumerate(ranges):
                for n2, lo2, hi2 in ranges[i + 1:]:
                    if (lo1 is None or hi2 is None or lo1 <= hi2) and (lo2 is None or hi1 is None or lo2 <= hi1):
                        raise ValidationError("Los rangos de dos nodos se traslapan; deben ser disjuntos.")

    def _fragment_ddl(self, name: str, columns: list[Column], node_id: int) -> str:
        cols = ["`Id` INT AUTO_INCREMENT PRIMARY KEY"]
        for c in columns:
            cols.append(f"{q(c.name)} {c.type.upper()}{'' if c.nullable else ' NOT NULL'}")
        return (
            f"CREATE TABLE {q(name)} (\n    " + ",\n    ".join(cols) +
            f"\n) CHARACTER SET utf8mb4 AUTO_INCREMENT = {id_base(node_id)}"
        )

    def create_distributed_table(self, name: str, columns: list[Column], strategy: str,
                                 frag_column: str | None, predicates: dict[int, dict | None]):
        """Crea la tabla en todos los nodos y la registra en el catálogo."""
        name = (name or "").strip()
        if not db.is_identifier(name):
            raise ValidationError("Nombre de tabla inválido (letras, dígitos y _; no iniciar con dígito).")
        if not columns:
            raise ValidationError("Define al menos una columna.")
        seen = {"id"}
        for c in columns:
            if not db.is_identifier(c.name):
                raise ValidationError(f"Nombre de columna inválido: «{c.name}».")
            if c.name.lower() in seen:
                raise ValidationError(f"Columna repetida o reservada: «{c.name}» (Id lo crea el sistema).")
            seen.add(c.name.lower())
            if not TYPE_RE.match(c.type.strip()):
                raise ValidationError(f"Tipo no soportado para «{c.name}»: {c.type}.")
        existing = {t.name.lower() for t in self.tables()}
        if name.lower() in existing:
            raise ValidationError(f"Ya existe una tabla distribuida llamada «{name}».")

        col = None
        if strategy != STRATEGY_NODE:
            col = next((c for c in columns if c.name.lower() == (frag_column or "").lower()), None)
            if col is None:
                raise ValidationError("Selecciona la columna de fragmentación.")
            col.nullable = False  # una fila sin valor no podría ubicarse en ningún fragmento
            if not any(predicates.values()):
                raise ValidationError("Define el predicado de al menos un fragmento.")
        self.validate_predicates(strategy, col, predicates)

        nodes = self.nodes()
        # Todos los nodos deben estar disponibles: el esquema global debe existir en cada uno.
        down = {n.name: e for n in nodes if (e := self.ping(n))}
        if down:
            raise DistributedError("No se puede crear la tabla; nodos sin respuesta: " + ", ".join(down))
        self.log("DP", f"Crear tabla distribuida «{name}» ({strategy}) en {len(nodes)} nodo(s)")

        created = []
        try:
            for n in nodes:
                with self.catalog.connect_node(n) as conn, conn.cursor() as cur:
                    cur.execute("SHOW TABLES LIKE %s", (name,))
                    if cur.fetchone():
                        raise DistributedError(f"El nodo {n.name} ya tiene una tabla «{name}».")
                    cur.execute(self._fragment_ddl(name, columns, n.id))
                created.append(n)
                self.log("DP", f"{n.name}: fragmento {name} creado")
            with self.catalog.conn(autocommit=False) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO DistributedTables (Name, Columns, Strategy, FragmentColumn, IsSystem) "
                    "VALUES (%s, %s, %s, %s, 0)",
                    (name, json.dumps([c.to_dict() for c in columns]), strategy, col.name if col else None),
                )
                for n in nodes:
                    pred = predicates.get(n.id)
                    cur.execute(
                        "INSERT INTO Fragments (TableName, NodeId, Predicate) VALUES (%s, %s, %s)",
                        (name, n.id, json.dumps(pred) if pred else None),
                    )
                conn.commit()
            self.log("CAT", f"Tabla «{name}» registrada en el catálogo global")
        except Exception:
            # Compensación: el DDL no es transaccional, se deshace manualmente.
            for n in created:
                try:
                    with self.catalog.connect_node(n) as conn, conn.cursor() as cur:
                        cur.execute(f"DROP TABLE IF EXISTS {q(name)}")
                    self.log("DP", f"{n.name}: compensación, fragmento {name} eliminado")
                except Exception as exc:
                    self.log("DP", f"{n.name}: no se pudo compensar: {exc}")
            raise

    def drop_distributed_table(self, name: str):
        table = self.catalog.table(name)
        if table.is_system:
            raise ValidationError("Las tablas del sistema (Clients, Addresses) no pueden eliminarse.")
        nodes = self.nodes()
        down = {n.name: e for n in nodes if (e := self.ping(n))}
        if down:
            raise DistributedError("No se puede eliminar; nodos sin respuesta: " + ", ".join(down))
        for n in nodes:
            with self.catalog.connect_node(n) as conn, conn.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {q(table.name)}")
            self.log("DP", f"{n.name}: fragmento {table.name} eliminado")
        with self.catalog.conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM DistributedTables WHERE Name = %s", (table.name,))
        self.log("CAT", f"Tabla «{table.name}» eliminada del catálogo")

    def query_table(self, name: str, column: str | None = None, op: str = "=", value: str = ""):
        """Consulta global sobre una tabla distribuida (unión de fragmentos)."""
        table = self.catalog.table(name)
        nodes = [n for n in self.nodes() if n.id in table.fragments] or self.nodes()
        sql = f"SELECT * FROM {q(table.name)}"
        params = []
        if column:
            if op not in FILTER_OPS:
                raise ValidationError("Operador no válido.")
            if column != "Id" and not table.column(column):
                raise ValidationError("Columna no válida.")
            sql += f" WHERE {q(column)} {op} %s"
            params.append(f"%{value}%" if op == "LIKE" else value)
            # Poda de fragmentos: igualdad sobre la columna de fragmentación.
            if (op == "=" and table.strategy in (STRATEGY_LIST, STRATEGY_RANGE)
                    and table.frag_column and column.lower() == table.frag_column.lower()):
                col = table.column(table.frag_column)
                pruned = [n for n in nodes if self._matches(table, col, table.fragments.get(n.id), value)]
                self.log("DP", f"Poda de fragmentos ({column} = {value!r}): se consulta solo "
                               f"{', '.join(n.name for n in pruned) or 'ningún nodo'}")
                nodes = pruned
        sql += " ORDER BY Id"
        self.log("DP", f"Consulta global sobre «{table.name}» en: {', '.join(n.name for n in nodes)}")

        def run(node, cur):
            cur.execute(sql, params)
            return cur.fetchall()

        results, errors = self._scatter(nodes, run)
        rows = []
        for n in nodes:
            for r in results.get(n.id, []):
                row = {k: _display(v) for k, v in r.items()}
                row["NodeId"] = n.id
                row["Branch"] = n.name
                rows.append(row)
        return table, rows, errors

    def _clean_values(self, table: DistTable, values: dict) -> dict:
        out = {}
        for c in table.columns:
            v = values.get(c.name)
            v = None if v is None or str(v).strip() == "" else str(v).strip()
            if v is None and not c.nullable:
                raise ValidationError(f"El campo «{c.name}» es obligatorio.")
            if v is not None and c.type.upper() == "BOOLEAN":
                v = 1 if v.lower() in ("1", "si", "sí", "true", "verdadero", "s", "x") else 0
            out[c.name] = v
        return out

    def insert_row(self, name: str, values: dict, node_id: int | None = None) -> tuple[Node, int]:
        table = self.catalog.table(name)
        if table.is_system:
            raise ValidationError("Usa la pestaña Clientes para modificar Clients y Addresses.")
        values = self._clean_values(table, values)
        node = self.route(table, values, node_id)
        self.log("DP", f"Insertar en «{table.name}»: el predicado ubica la fila en {node.name}")
        cols = list(values)
        with self.tp.begin(f"Insertar en {table.name}") as tx:
            cur = tx.cursor(node)
            cur.execute(
                f"INSERT INTO {q(table.name)} ({', '.join(q(c) for c in cols)}) "
                f"VALUES ({', '.join(['%s'] * len(cols))})",
                [values[c] for c in cols],
            )
            new_id = cur.lastrowid
        return node, new_id

    def update_row(self, name: str, node_id: int, row_id: int, values: dict, new_node_id: int | None = None):
        table = self.catalog.table(name)
        if table.is_system:
            raise ValidationError("Usa la pestaña Clientes para modificar Clients y Addresses.")
        values = self._clean_values(table, values)
        node = self._node(node_id)
        target = self.route(table, values, new_node_id if table.strategy == STRATEGY_NODE else None) \
            if table.strategy != STRATEGY_NODE or new_node_id else node
        cols = list(values)
        if target.id == node.id:
            with self.tp.begin(f"Actualizar {table.name} {row_id}") as tx:
                tx.cursor(node).execute(
                    f"UPDATE {q(table.name)} SET {', '.join(f'{q(c)} = %s' for c in cols)} WHERE Id = %s",
                    [values[c] for c in cols] + [row_id],
                )
            self.log("DP", f"{table.name} {row_id} actualizado en {node.name}")
            return node, row_id
        # La fila cambia de fragmento: se mueve atómicamente entre nodos.
        self.log("DP", f"{table.name} {row_id}: el nuevo valor pertenece al fragmento de {target.name}; se migra")
        with self.tp.begin(f"Migrar fila {table.name} {row_id}") as tx:
            src = tx.cursor(node)
            src.execute(f"DELETE FROM {q(table.name)} WHERE Id = %s", (row_id,))
            if src.rowcount == 0:
                raise DistributedError("La fila ya no existe.")
            dst = tx.cursor(target)
            dst.execute(
                f"INSERT INTO {q(table.name)} ({', '.join(q(c) for c in cols)}) "
                f"VALUES ({', '.join(['%s'] * len(cols))})",
                [values[c] for c in cols],
            )
            new_id = dst.lastrowid
        return target, new_id

    def delete_row(self, name: str, node_id: int, row_id: int):
        table = self.catalog.table(name)
        if table.is_system:
            raise ValidationError("Usa la pestaña Clientes para modificar Clients y Addresses.")
        node = self._node(node_id)
        with self.tp.begin(f"Eliminar {table.name} {row_id}") as tx:
            tx.cursor(node).execute(f"DELETE FROM {q(table.name)} WHERE Id = %s", (row_id,))
        self.log("DP", f"{table.name} {row_id} eliminado de {node.name}")

    # ================================================================= nodos
    @staticmethod
    def test_server(host: str, port: int, user: str, password: str):
        info = ConnInfo(host, int(port), user, password)
        with db.connect(info, database="") as conn, conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS v")
            return cur.fetchone()["v"]

    def add_node(self, name: str, host: str, port: int, db_name: str,
                 user: str | None, password: str | None,
                 predicates: dict[str, dict | None]) -> Node:
        """Da de alta un nuevo nodo (sucursal): crea su BD, sus fragmentos y lo registra."""
        name, host, db_name = (name or "").strip(), (host or "").strip(), (db_name or "").strip()
        user = (user or "").strip() or None
        if not name or len(name) > 50:
            raise ValidationError("El nombre del nodo es obligatorio (máx. 50 caracteres).")
        if not host:
            raise ValidationError("El host es obligatorio.")
        if not db.is_identifier(db_name):
            raise ValidationError("Nombre de base de datos inválido.")
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise ValidationError("El puerto debe ser numérico.")
        nodes = self.nodes()
        if any(n.name.lower() == name.lower() for n in nodes):
            raise ValidationError(f"Ya existe un nodo llamado «{name}».")
        if any(n.host == host and n.port == port and n.db_name.lower() == db_name.lower() for n in nodes):
            raise ValidationError("Ese servidor y base de datos ya pertenecen a otro nodo.")

        tables = [t for t in self.tables() if not t.is_system]
        for t in tables:
            if t.strategy == STRATEGY_NODE:
                continue
            col = t.column(t.frag_column)
            merged = dict(t.fragments)
            merged[-1] = predicates.get(t.name)
            self.validate_predicates(t.strategy, col, merged)

        node_id = max((n.id for n in nodes), default=0) + 1
        new = Node(node_id, name, host, port, db_name, user, password if user else None)
        info = self.catalog.node_conn_info(new)
        self.log("DP", f"Alta de nodo {name} (Id {node_id}) en {host}:{port}/{db_name}")

        created_db = False
        try:
            with db.connect(info, database="") as conn, conn.cursor() as cur:
                cur.execute("SHOW DATABASES LIKE %s", (db_name,))
                if cur.fetchone():
                    raise ValidationError(f"La base de datos «{db_name}» ya existe en {host}:{port}.")
                cur.execute(f"CREATE DATABASE {q(db_name)} CHARACTER SET utf8mb4")
                created_db = True
                cur.execute(f"USE {q(db_name)}")
                cur.execute(CLIENTS_DDL.format(base=id_base(node_id)))
                cur.execute(ADDRESSES_DDL.format(base=id_base(node_id)))
                self.log("DP", f"{name}: BD {db_name} creada con Clients y Addresses (Ids desde {id_base(node_id)})")
                for t in tables:
                    cur.execute(self._fragment_ddl(t.name, t.columns, node_id))
                    self.log("DP", f"{name}: fragmento de «{t.name}» creado")

            with self.catalog.conn(autocommit=False) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO Nodes (Id, Name, Host, Port, DbName) VALUES (%s, %s, %s, %s, %s)",
                    (node_id, name, host, port, db_name),
                )
                if user:
                    cur.execute("INSERT INTO NodeAuth (NodeId, User, Password) VALUES (%s, %s, %s)",
                                (node_id, user, password or ""))
                cur.execute("INSERT INTO Fragments (TableName, NodeId, Predicate) "
                            "SELECT Name, %s, NULL FROM DistributedTables WHERE IsSystem = 1", (node_id,))
                for t in tables:
                    pred = predicates.get(t.name) if t.strategy != STRATEGY_NODE else None
                    cur.execute("INSERT INTO Fragments (TableName, NodeId, Predicate) VALUES (%s, %s, %s)",
                                (t.name, node_id, json.dumps(pred) if pred else None))
                conn.commit()
            self.log("CAT", f"Nodo {name} registrado en el catálogo global")
            return new
        except Exception:
            if created_db:
                try:
                    with db.connect(info, database="") as conn, conn.cursor() as cur:
                        cur.execute(f"DROP DATABASE IF EXISTS {q(db_name)}")
                    self.log("DP", f"Compensación: BD {db_name} eliminada")
                except Exception as exc:
                    self.log("DP", f"No se pudo compensar la creación de {db_name}: {exc}")
            raise

    def update_fragment(self, table_name: str, node_id: int, predicate: dict | None):
        """Cambia el predicado de un fragmento (sólo si no deja filas fuera de lugar)."""
        table = self.catalog.table(table_name)
        if table.strategy == STRATEGY_NODE:
            raise ValidationError("Las tablas por sucursal no tienen predicado.")
        col = table.column(table.frag_column)
        merged = dict(table.fragments)
        merged[int(node_id)] = predicate
        self.validate_predicates(table.strategy, col, merged)
        node = self._node(node_id)
        with self.catalog.connect_node(node) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT Id, {q(col.name)} AS v FROM {q(table.name)}")
            for r in cur.fetchall():
                tmp = DistTable(table.name, table.columns, table.strategy, table.frag_column, False)
                if not self._matches(tmp, col, predicate, r["v"]):
                    raise ValidationError(
                        f"La fila {r['Id']} ({col.name} = {r['v']!r}) de {node.name} ya no cumpliría el predicado."
                    )
        with self.catalog.conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE Fragments SET Predicate = %s WHERE TableName = %s AND NodeId = %s",
                        (json.dumps(predicate) if predicate else None, table.name, node_id))
        self.log("CAT", f"Predicado de «{table.name}» en {node.name} actualizado")
