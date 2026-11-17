"""Pestaña de nodos (sucursales) del sistema distribuido."""
import tkinter as tk
from tkinter import messagebox, ttk

from ..catalog import STRATEGY_NODE, id_base
from .tables_tab import PredicateEditor, predicate_text
from .widgets import Dialog, make_tree


class AddNodeDialog(Dialog):
    def __init__(self, tab, tables):
        super().__init__(tab, "Agregar nodo al sistema distribuido", ok_text="Agregar nodo")
        self.tab, self.app = tab, tab.app
        self.tables = [t for t in tables if not t.is_system and t.strategy != STRATEGY_NODE]
        b = self.body
        cat = self.app.catalog.info
        next_id = max((n.id for n in self.app.nodes), default=0) + 1
        ttk.Label(b, text=f"Nuevo nodo #{next_id} — sus Ids comenzarán en {id_base(next_id)}",
                  style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.vars = {}
        fields = [("name", "Nombre de la sucursal *", ""), ("host", "Servidor (host) *", cat.host),
                  ("port", "Puerto *", str(cat.port)), ("db", "Base de datos *", "ddb_"),
                  ("user", "Usuario", ""), ("password", "Contraseña", "")]
        for i, (k, label, default) in enumerate(fields, start=1):
            ttk.Label(b, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            v = tk.StringVar(value=default)
            ent = ttk.Entry(b, textvariable=v, width=32, show="•" if k == "password" else "")
            ent.grid(row=i, column=1, sticky="ew", pady=3)
            if k == "name":
                ent.focus_set()
            self.vars[k] = v
        self.vars["name"].trace_add("write", self._suggest_db)
        ttk.Label(b, text="Usuario vacío = usar las mismas credenciales del catálogo.",
                  foreground="#555").grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Button(b, text="Probar conexión", command=self.test).grid(row=8, column=0, sticky="w", pady=6)
        self.test_msg = ttk.Label(b, text="", wraplength=300)
        self.test_msg.grid(row=8, column=1, sticky="w")

        self.editors = {}
        if self.tables:
            box = ttk.LabelFrame(b, text="Fragmentos del nuevo nodo en las tablas distribuidas", padding=8)
            box.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            for t in self.tables:
                ttk.Label(box, text=f"{t.name} — {t.strategy_label} sobre «{t.frag_column}»",
                          style="Title.TLabel").pack(anchor="w", pady=(4, 0))
                existing = "; ".join(f"{n.name}: {predicate_text(t.strategy, t.fragments.get(n.id))}"
                                     for n in self.app.nodes)
                ttk.Label(box, text="Actual: " + existing, foreground="#555", wraplength=460).pack(anchor="w")
                fake = type("N", (), {"id": -1, "name": "Nuevo nodo"})()
                ed = PredicateEditor(box, [fake])
                ed.set_strategy(t.strategy)
                ed.pack(fill="x")
                self.editors[t.name] = (t, ed)
        ttk.Label(b, text="Se creará la base de datos con Clients, Addresses y los fragmentos de cada tabla "
                          "distribuida, y el nodo quedará registrado en el catálogo global.",
                  foreground="#555", wraplength=460).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.show()

    def _suggest_db(self, *_):
        import unicodedata
        name = self.vars["name"].get()
        slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        slug = "".join(ch if ch.isalnum() else "_" for ch in slug).strip("_")
        self.vars["db"].set("ddb_" + slug)

    def _conn_args(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        cat = self.app.catalog.info
        user = v["user"] or cat.user
        password = self.vars["password"].get() if v["user"] else cat.password
        return v, user, password

    def test(self):
        v, user, password = self._conn_args()
        self.test_msg.configure(text="Probando…", foreground="#555")

        def ok(version):
            self.test_msg.configure(text=f"Conexión correcta (servidor {version})", foreground="#2e7d32")

        def err(exc):
            self.test_msg.configure(text="Sin conexión", foreground="#c62828")

        self.app.run_task(lambda: self.app.dp.test_server(v["host"], v["port"] or 3306, user, password),
                          ok, "Probando conexión…", parent=self, on_error=err)

    def on_ok(self):
        v, _, _ = self._conn_args()
        preds = {name: PredicateEditor.parse(t.strategy, ed.vars[-1]) for name, (t, ed) in self.editors.items()}
        self.set_busy(True)

        def ok(node):
            self.destroy()
            messagebox.showinfo("Nodo agregado", f"El nodo «{node.name}» se agregó al sistema distribuido.",
                                parent=self.app)
            self.app.refresh_nodes()

        self.app.run_task(
            lambda: self.app.dp.add_node(v["name"], v["host"], v["port"], v["db"], v["user"],
                                         self.vars["password"].get(), preds),
            ok, "Creando nodo…", parent=self, on_error=lambda e: self.set_busy(False))


class NodesTab(ttk.Frame):
    COLS = ("Id", "Name", "Host", "Port", "DbName", "Ids", "Status")
    HEAD = ("Id", "Sucursal", "Servidor", "Puerto", "Base de datos", "Rango de Ids", "Estado")
    WIDTHS = (50, 140, 160, 70, 160, 140, 380)

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Nodos registrados en el catálogo global", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Agregar nodo", command=self.add_node, style="Accent.TButton").pack(side="right")
        ttk.Button(top, text="Verificar estado", command=self.check_status).pack(side="right", padx=4)
        frame, self.tree = make_tree(self, self.COLS, self.HEAD, self.WIDTHS, height=12)
        frame.pack(fill="both", expand=True, pady=6)
        self.tree.tag_configure("up", foreground="#2e7d32")
        self.tree.tag_configure("down", foreground="#c62828")

    def on_nodes_changed(self):
        self.tree.delete(*self.tree.get_children())
        for n in self.app.nodes:
            self.tree.insert("", "end", iid=str(n.id), values=(
                n.id, n.name, n.host, n.port, n.db_name, f"{id_base(n.id)} …", "sin verificar"))
        self.check_status()

    def check_status(self):
        nodes = list(self.app.nodes)

        def work():
            return {n.id: self.app.dp.ping(n) for n in nodes}

        def done(status):
            for nid, err in status.items():
                if self.tree.exists(str(nid)):
                    self.tree.set(str(nid), "Status", "● En línea" if err is None else f"● Sin conexión: {err}")
                    self.tree.item(str(nid), tags=("up" if err is None else "down",))

        self.app.run_task(work, done, "Verificando nodos…")

    def add_node(self):
        self.app.run_task(self.app.dp.tables, lambda tables: AddNodeDialog(self, tables), "Leyendo catálogo…")
