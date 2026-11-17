"""Pestaña de tablas distribuidas con fragmentación horizontal."""
import tkinter as tk
from tkinter import messagebox, ttk

from ..catalog import (STRATEGY_LABELS, STRATEGY_LIST, STRATEGY_NODE, STRATEGY_RANGE, Column)
from ..dp import FILTER_OPS
from .widgets import Dialog, NodeCombo, make_tree, set_tree_columns

TYPE_SUGGESTIONS = ["VARCHAR(50)", "VARCHAR(100)", "CHAR(5)", "INT", "BIGINT", "DECIMAL(10,2)",
                    "DATE", "DATETIME", "BOOLEAN", "TEXT"]


def predicate_text(strategy, pred):
    if not pred:
        return "— (no recibe filas)" if strategy != STRATEGY_NODE else "Filas asignadas a esta sucursal"
    if strategy == STRATEGY_LIST:
        return "IN (" + ", ".join(pred.get("values", [])) + ")"
    lo, hi = pred.get("min") or "-∞", pred.get("max") or "+∞"
    return f"{lo} ≤ valor ≤ {hi}"


class PredicateEditor(ttk.Frame):
    """Captura el predicado de fragmentación de cada nodo."""

    def __init__(self, parent, nodes):
        super().__init__(parent)
        self.nodes = nodes
        self.strategy = STRATEGY_NODE
        self.vars = {}

    def set_strategy(self, strategy, current=None):
        self.strategy = strategy
        current = current or {}
        for w in self.winfo_children():
            w.destroy()
        self.vars = {}
        if strategy == STRATEGY_NODE:
            ttk.Label(self, text="Cada fila se guarda en la sucursal que se elige al insertarla.\n"
                                 "No se requiere columna de fragmentación.", foreground="#555").grid(sticky="w")
            return
        if strategy == STRATEGY_LIST:
            ttk.Label(self, text="Nodo").grid(row=0, column=0, sticky="w")
            ttk.Label(self, text="Valores separados por coma (vacío = no recibe filas)").grid(row=0, column=1, sticky="w")
        else:
            ttk.Label(self, text="Nodo").grid(row=0, column=0, sticky="w")
            ttk.Label(self, text="Mínimo (incl.)").grid(row=0, column=1, sticky="w")
            ttk.Label(self, text="Máximo (incl.)").grid(row=0, column=2, sticky="w")
        for i, n in enumerate(self.nodes, start=1):
            ttk.Label(self, text=n.name).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            pred = current.get(n.id) or {}
            if strategy == STRATEGY_LIST:
                v = tk.StringVar(value=", ".join(pred.get("values", [])))
                ttk.Entry(self, textvariable=v, width=44).grid(row=i, column=1, columnspan=2, sticky="ew", pady=2)
                self.vars[n.id] = (v,)
            else:
                lo = tk.StringVar(value=pred.get("min") or "")
                hi = tk.StringVar(value=pred.get("max") or "")
                ttk.Entry(self, textvariable=lo, width=20).grid(row=i, column=1, sticky="w", pady=2, padx=(0, 6))
                ttk.Entry(self, textvariable=hi, width=20).grid(row=i, column=2, sticky="w", pady=2)
                self.vars[n.id] = (lo, hi)
        if strategy == STRATEGY_RANGE:
            ttk.Label(self, text="Deja un extremo vacío para un rango abierto (−∞ / +∞). Ambos vacíos = no recibe filas.",
                      foreground="#555").grid(row=len(self.nodes) + 1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    @staticmethod
    def parse(strategy, vars_):
        if strategy == STRATEGY_LIST:
            values = [x.strip() for x in vars_[0].get().split(",") if x.strip()]
            return {"values": values} if values else None
        lo, hi = vars_[0].get().strip(), vars_[1].get().strip()
        return {"min": lo, "max": hi} if (lo or hi) else None

    def predicates(self):
        if self.strategy == STRATEGY_NODE:
            return {n.id: None for n in self.nodes}
        return {nid: self.parse(self.strategy, v) for nid, v in self.vars.items()}


class CreateTableDialog(Dialog):
    def __init__(self, tab):
        super().__init__(tab, "Nueva tabla distribuida", ok_text="Crear tabla")
        self.tab, self.app = tab, tab.app
        self.resizable(True, True)
        b = self.body
        ttk.Label(b, text="Nombre de la tabla *").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar()
        e = ttk.Entry(b, textvariable=self.name, width=30)
        e.grid(row=0, column=1, sticky="w", pady=3)
        e.focus_set()

        cols = ttk.LabelFrame(b, text="Columnas (el sistema agrega «Id» como llave primaria global)", padding=8)
        cols.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)
        hdr = ttk.Frame(cols)
        hdr.pack(fill="x")
        for text, w in (("Nombre", 22), ("Tipo", 18), ("Nulo", 6)):
            ttk.Label(hdr, text=text, width=w).pack(side="left", padx=2)
        self.cols_frame = ttk.Frame(cols)
        self.cols_frame.pack(fill="x")
        self.col_rows = []
        ttk.Button(cols, text="+ Agregar columna", command=self.add_column).pack(anchor="w", pady=(6, 0))

        frag = ttk.LabelFrame(b, text="Fragmentación horizontal", padding=8)
        frag.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(frag, text="Estrategia").grid(row=0, column=0, sticky="w")
        self.strategy = ttk.Combobox(frag, values=list(STRATEGY_LABELS.values()), state="readonly", width=24)
        self.strategy.current(0)
        self.strategy.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        self.strategy.bind("<<ComboboxSelected>>", lambda e: self._on_strategy())
        ttk.Label(frag, text="Columna").grid(row=1, column=0, sticky="w")
        self.frag_col = ttk.Combobox(frag, values=[], state="readonly", width=24, postcommand=self._refresh_cols)
        self.frag_col.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        self.pred = PredicateEditor(frag, self.app.nodes)
        self.pred.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self.add_column()
        self._on_strategy()
        self.show()

    def add_column(self):
        row = ttk.Frame(self.cols_frame)
        row.pack(fill="x", pady=1)
        name = tk.StringVar()
        typ = tk.StringVar(value="VARCHAR(50)")
        nullable = tk.BooleanVar(value=True)
        ttk.Entry(row, textvariable=name, width=24).pack(side="left", padx=2)
        ttk.Combobox(row, textvariable=typ, values=TYPE_SUGGESTIONS, width=18).pack(side="left", padx=2)
        ttk.Checkbutton(row, variable=nullable).pack(side="left", padx=10)
        entry = (row, name, typ, nullable)
        ttk.Button(row, text="✕", width=3, command=lambda: self._remove(entry)).pack(side="left")
        self.col_rows.append(entry)

    def _remove(self, entry):
        if len(self.col_rows) > 1:
            entry[0].destroy()
            self.col_rows.remove(entry)

    def _refresh_cols(self):
        self.frag_col["values"] = [n.get().strip() for _, n, _, _ in self.col_rows if n.get().strip()]

    def _strategy_code(self):
        label = self.strategy.get()
        return next(k for k, v in STRATEGY_LABELS.items() if v == label)

    def _on_strategy(self):
        code = self._strategy_code()
        self.frag_col.configure(state="disabled" if code == STRATEGY_NODE else "readonly")
        self.pred.set_strategy(code)

    def on_ok(self):
        columns = [Column(n.get().strip(), t.get().strip(), nl.get())
                   for _, n, t, nl in self.col_rows if n.get().strip()]
        strategy = self._strategy_code()
        frag_col = self.frag_col.get() if strategy != STRATEGY_NODE else None
        preds = self.pred.predicates()
        name = self.name.get().strip()
        self.set_busy(True)

        def ok(_):
            self.destroy()
            self.tab.refresh_tables(select=name)

        self.app.run_task(lambda: self.app.dp.create_distributed_table(name, columns, strategy, frag_col, preds),
                          ok, "Creando fragmentos en todos los nodos…", parent=self,
                          on_error=lambda e: self.set_busy(False))


class RowDialog(Dialog):
    def __init__(self, tab, table, row=None):
        super().__init__(tab, f"{'Editar' if row else 'Nueva'} fila — {table.name}")
        self.tab, self.app, self.table, self.row = tab, tab.app, table, row
        self.vars = {}
        r = 0
        for c in table.columns:
            label = c.name + ("" if c.nullable else " *") + f"  ({c.type})"
            if c.name == table.frag_column:
                label += "  ⟵ fragmentación"
            ttk.Label(self.body, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            v = tk.StringVar(value="" if not row else str(row.get(c.name, "")))
            ent = ttk.Entry(self.body, textvariable=v, width=34)
            ent.grid(row=r, column=1, sticky="ew", pady=3)
            if r == 0:
                ent.focus_set()
            self.vars[c.name] = v
            r += 1
        self.node_combo = None
        if table.strategy == STRATEGY_NODE:
            ttk.Label(self.body, text="Sucursal *").grid(row=r, column=0, sticky="w", pady=3)
            sel = row["NodeId"] if row else (self.app.origin_node().id if self.app.origin_node() else None)
            self.node_combo = NodeCombo(self.body, self.app.nodes, sel)
            self.node_combo.grid(row=r, column=1, sticky="ew", pady=3)
        else:
            ttk.Label(self.body, text=f"El sistema ubicará la fila en el nodo correspondiente según «{table.frag_column}».",
                      foreground="#555", wraplength=340).grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.show()

    def on_ok(self):
        values = {k: v.get() for k, v in self.vars.items()}
        node = self.node_combo.selected_node() if self.node_combo else None
        t = self.table
        if self.row:
            fn = lambda: self.app.dp.update_row(t.name, self.row["NodeId"], self.row["Id"], values,
                                                node.id if node else None)
        else:
            fn = lambda: self.app.dp.insert_row(t.name, values, node.id if node else None)
        self.set_busy(True)

        def ok(result):
            target, row_id = result
            self.destroy()
            self.app.status.set(f"Fila {row_id} guardada en el nodo {target.name}")
            self.tab.query()

        self.app.run_task(fn, ok, "Guardando fila…", parent=self, on_error=lambda e: self.set_busy(False))


class FragmentsDialog(Dialog):
    """Muestra (y permite modificar) los predicados de fragmentación."""

    def __init__(self, tab, table):
        editable = table.strategy != STRATEGY_NODE and not table.is_system
        super().__init__(tab, f"Fragmentos de {table.name}", ok_text="Guardar predicados" if editable else "Cerrar")
        self.tab, self.app, self.table, self.editable = tab, tab.app, table, editable
        b = self.body
        ttk.Label(b, text=f"Estrategia: {table.strategy_label}"
                          + (f"   ·   Columna: {table.frag_column}" if table.frag_column else ""),
                  style="Title.TLabel").pack(anchor="w")
        frame, tree = make_tree(b, ("node", "pred"), ("Nodo", "Predicado de selección"), (140, 380), height=6)
        frame.pack(fill="both", expand=True, pady=6)
        for n in self.app.nodes:
            tree.insert("", "end", values=(n.name, predicate_text(table.strategy, table.fragments.get(n.id))))
        if editable:
            ttk.Label(b, text="Modificar predicados (se verifica que las filas existentes sigan cumpliéndolos):",
                      foreground="#555").pack(anchor="w", pady=(6, 2))
            self.pred = PredicateEditor(b, self.app.nodes)
            self.pred.set_strategy(table.strategy, table.fragments)
            self.pred.pack(fill="x")
        self.show()

    def on_ok(self):
        if not self.editable:
            self.destroy()
            return
        preds = self.pred.predicates()
        changed = {nid: p for nid, p in preds.items() if p != self.table.fragments.get(nid)}
        if not changed:
            self.destroy()
            return

        def work():
            # Primero los que reducen/eliminan rangos para evitar traslapes temporales.
            for nid, p in sorted(changed.items(), key=lambda kv: kv[1] is not None):
                self.app.dp.update_fragment(self.table.name, nid, p)

        self.set_busy(True)
        self.app.run_task(work, lambda _: (self.destroy(), self.tab.refresh_tables(select=self.table.name)),
                          "Actualizando catálogo…", parent=self, on_error=lambda e: self.set_busy(False))


class TablesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.tables = {}
        self.rows = {}
        self.current = None

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        ttk.Label(left, text="Tablas distribuidas", style="Title.TLabel").pack(anchor="w")
        frame, self.ttree = make_tree(left, ("name", "strategy", "col"), ("Tabla", "Fragmentación", "Columna"),
                                      (120, 140, 90), height=14)
        frame.pack(fill="both", expand=True, pady=4)
        self.ttree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        lb = ttk.Frame(left)
        lb.pack(fill="x")
        ttk.Button(lb, text="Nueva tabla", command=lambda: CreateTableDialog(self), style="Accent.TButton").pack(side="left")
        ttk.Button(lb, text="Fragmentos", command=self.show_fragments).pack(side="left", padx=4)
        ttk.Button(lb, text="Eliminar", command=self.drop_table).pack(side="left")
        paned.add(left, weight=1)

        right = ttk.Frame(paned)
        self.title = ttk.Label(right, text="Selecciona una tabla", style="Title.TLabel")
        self.title.pack(anchor="w")
        fbar = ttk.Frame(right)
        fbar.pack(fill="x", pady=4)
        ttk.Label(fbar, text="Filtro:").pack(side="left")
        self.fcol = ttk.Combobox(fbar, state="readonly", width=16)
        self.fcol.pack(side="left", padx=4)
        self.fop = ttk.Combobox(fbar, values=FILTER_OPS, state="readonly", width=6)
        self.fop.current(0)
        self.fop.pack(side="left", padx=4)
        self.fval = tk.StringVar()
        ent = ttk.Entry(fbar, textvariable=self.fval, width=20)
        ent.pack(side="left", padx=4)
        ent.bind("<Return>", lambda e: self.query())
        ttk.Button(fbar, text="Consultar", command=self.query).pack(side="left", padx=4)
        ttk.Button(fbar, text="Todo", command=lambda: (self.fcol.current(0), self.query())).pack(side="left")
        self.count = ttk.Label(fbar, text="", foreground="#555")
        self.count.pack(side="right")
        frame, self.dtree = make_tree(right, ("x",), height=14)
        frame.pack(fill="both", expand=True)
        self.dtree.bind("<Double-1>", lambda e: self.edit_row())
        rb = ttk.Frame(right)
        rb.pack(fill="x", pady=(4, 0))
        self.row_buttons = [
            ttk.Button(rb, text="Insertar fila", command=self.new_row),
            ttk.Button(rb, text="Editar fila", command=self.edit_row),
            ttk.Button(rb, text="Eliminar fila", command=self.delete_row),
        ]
        for i, btn in enumerate(self.row_buttons):
            btn.pack(side="left", padx=(0 if i == 0 else 4, 0))
        paned.add(right, weight=3)

    # ---------------------------------------------------------------- tablas
    def on_nodes_changed(self):
        self.refresh_tables(select=self.current.name if self.current else None)

    def refresh_tables(self, select=None):
        def done(tables):
            self.ttree.delete(*self.ttree.get_children())
            self.tables = {t.name: t for t in tables}
            for t in tables:
                label = t.strategy_label + (" (sistema)" if t.is_system else "")
                self.ttree.insert("", "end", iid=t.name, values=(t.name, label, t.frag_column or ""))
            if select and select in self.tables:
                self.ttree.selection_set(select)
                self.ttree.see(select)
        self.app.run_task(self.app.dp.tables, done, "Leyendo catálogo de tablas…")

    def _on_select(self):
        sel = self.ttree.selection()
        if not sel:
            return
        self.current = self.tables[sel[0]]
        t = self.current
        self.title.configure(text=f"{t.name} — vista global (unión de {len(t.fragments)} fragmentos)")
        self.fcol["values"] = ["(sin filtro)", "Id"] + [c.name for c in t.columns]
        self.fcol.current(0)
        state = "disabled" if t.is_system else "normal"
        for b in self.row_buttons:
            b.configure(state=state)
        self.query()

    def query(self):
        t = self.current
        if not t:
            return
        col = self.fcol.get()
        col = None if col in ("", "(sin filtro)") else col
        op, val = self.fop.get(), self.fval.get()

        def done(result):
            table, rows, errors = result
            cols = ["Branch", "Id"] + [c.name for c in table.columns]
            set_tree_columns(self.dtree, cols, ["Nodo", "Id"] + cols[2:], [100, 80] + [130] * len(table.columns))
            self.rows.clear()
            for r in rows:
                iid = f"{r['NodeId']}:{r['Id']}"
                self.rows[iid] = r
                self.dtree.insert("", "end", iid=iid, values=[r.get(c, "") for c in cols])
            self.count.configure(text=f"{len(rows)} fila(s)")
            self.app.report_partial(errors)

        self.app.run_task(lambda: self.app.dp.query_table(t.name, col, op, val), done, "Consultando fragmentos…")

    def show_fragments(self):
        if self.current:
            FragmentsDialog(self, self.current)

    def drop_table(self):
        t = self.current
        if not t:
            return
        if t.is_system:
            messagebox.showinfo("Tablas", "Las tablas del sistema no pueden eliminarse.", parent=self)
            return
        if messagebox.askyesno("Eliminar tabla", f"¿Eliminar la tabla distribuida «{t.name}» y TODOS sus "
                                                 f"fragmentos en todos los nodos?\nNo se puede deshacer.",
                               icon="warning", parent=self):
            def done(_):
                self.current = None
                self.title.configure(text="Selecciona una tabla")
                set_tree_columns(self.dtree, ("x",))
                self.refresh_tables()
            self.app.run_task(lambda: self.app.dp.drop_distributed_table(t.name), done, "Eliminando tabla…")

    # ---------------------------------------------------------------- filas
    def _selected_row(self):
        sel = self.dtree.selection()
        if not sel:
            messagebox.showinfo("Filas", "Selecciona una fila.", parent=self)
            return None
        return self.rows.get(sel[0])

    def new_row(self):
        if self.current and not self.current.is_system:
            RowDialog(self, self.current)

    def edit_row(self):
        if self.current and not self.current.is_system:
            r = self._selected_row()
            if r:
                RowDialog(self, self.current, r)

    def delete_row(self):
        t = self.current
        r = t and not t.is_system and self._selected_row()
        if r and messagebox.askyesno("Eliminar fila", f"¿Eliminar la fila {r['Id']} del nodo {r['Branch']}?",
                                     icon="warning", parent=self):
            self.app.run_task(lambda: self.app.dp.delete_row(t.name, r["NodeId"], r["Id"]),
                              lambda _: self.query(), "Eliminando fila…")
