"""Pestaña de clientes y direcciones."""
import tkinter as tk
from tkinter import messagebox, ttk

from ..dp import SEARCH_ADDRESS, SEARCH_ALL, SEARCH_NAME, SEARCH_RFC
from .widgets import Dialog, Form, NodeCombo, make_tree

CLIENT_FIELDS = [
    ("Name", "Nombre", True),
    ("PaternalSurname", "Apellido paterno", True),
    ("MaternalSurname", "Apellido materno", False),
    ("RFC", "RFC", True),
]
ADDRESS_FIELDS = [
    ("Street", "Calle", True),
    ("Number", "Número", True),
    ("Neighborhood", "Colonia", False),
    ("State", "Estado", True),
    ("ZIPCode", "Código postal", True),
]
SEARCH_MODES = [("Nombre", SEARCH_NAME), ("RFC", SEARCH_RFC), ("Domicilio", SEARCH_ADDRESS)]
ALL_BRANCHES = "Todas las sucursales"


class ClientDialog(Dialog):
    def __init__(self, tab, client=None):
        super().__init__(tab, "Editar cliente" if client else "Nuevo cliente")
        self.tab, self.app, self.client = tab, tab.app, client
        b = self.body
        ttk.Label(b, text="Datos del cliente", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.form = Form(b, CLIENT_FIELDS, client, start_row=1)
        r = self.form.next_row
        ttk.Label(b, text="Sucursal *").grid(row=r, column=0, sticky="w", pady=3)
        selected = client["NodeId"] if client else (self.app.origin_node().id if self.app.origin_node() else None)
        self.node_combo = NodeCombo(b, self.app.nodes, selected)
        self.node_combo.grid(row=r, column=1, sticky="ew", pady=3)
        hint = ("Cambiar la sucursal migra al cliente y sus direcciones (transacción distribuida); "
                "el cliente recibirá un nuevo Id." if client else
                "El registro se insertará en la base de datos de esta sucursal.")
        ttk.Label(b, text=hint, foreground="#666", wraplength=330).grid(row=r + 1, column=0, columnspan=2, sticky="w")
        self.addr_form = None
        if not client:
            ttk.Separator(b).grid(row=r + 2, column=0, columnspan=2, sticky="ew", pady=8)
            self.with_addr = tk.BooleanVar(value=True)
            ttk.Checkbutton(b, text="Registrar domicilio", variable=self.with_addr,
                            command=self._toggle_addr).grid(row=r + 3, column=0, columnspan=2, sticky="w")
            self.addr_frame = ttk.Frame(b)
            self.addr_frame.grid(row=r + 4, column=0, columnspan=2, sticky="ew")
            self.addr_form = Form(self.addr_frame, ADDRESS_FIELDS, {"State": "Michoacán"})
        self.show()

    def _toggle_addr(self):
        state = "normal" if self.with_addr.get() else "disabled"
        for child in self.addr_frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def on_ok(self):
        node = self.node_combo.selected_node()
        if node is None:
            messagebox.showwarning("Sucursal", "Selecciona una sucursal.", parent=self)
            return
        data = self.form.values()
        self.set_busy(True)
        if self.client:
            if node.id != self.client["NodeId"] and not messagebox.askyesno(
                    "Cambiar sucursal",
                    f"El cliente se moverá de {self.client['Branch']} a {node.name} junto con sus direcciones.\n"
                    "¿Continuar?", parent=self):
                self.set_busy(False)
                return
            fn = lambda: self.app.dp.update_client(self.client["NodeId"], self.client["Id"], data, node.id)
            msg = "Actualizando cliente…"
        else:
            addr = self.addr_form.values() if self.with_addr.get() else None
            fn = lambda: self.app.dp.insert_client(node.id, data, addr)
            msg = f"Insertando cliente en {node.name}…"

        def ok(new_id):
            self.destroy()
            self.tab.after_change(node.id, new_id)

        self.app.run_task(fn, ok, msg, parent=self, on_error=lambda e: self.set_busy(False))


class AddressDialog(Dialog):
    def __init__(self, tab, client, address=None):
        super().__init__(tab, "Editar dirección" if address else "Nueva dirección")
        self.tab, self.app, self.client, self.address = tab, tab.app, client, address
        ttk.Label(self.body, text=f"Cliente {client['Id']} — {client['Name']} {client['PaternalSurname']} "
                                  f"(sucursal {client['Branch']})", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.form = Form(self.body, ADDRESS_FIELDS, address or {"State": "Michoacán"}, start_row=1)
        self.show()

    def on_ok(self):
        data = self.form.values()
        c = self.client
        if self.address:
            fn = lambda: self.app.dp.update_address(c["NodeId"], self.address["Id"], data)
        else:
            fn = lambda: self.app.dp.insert_address(c["NodeId"], c["Id"], data)
        self.set_busy(True)

        def ok(_):
            self.destroy()
            self.tab.after_change(c["NodeId"], c["Id"])

        self.app.run_task(fn, ok, "Guardando dirección…", parent=self, on_error=lambda e: self.set_busy(False))


class ClientsTab(ttk.Frame):
    COLS = ("Branch", "Id", "Name", "PaternalSurname", "MaternalSurname", "RFC", "MainAddress", "NumAddresses")
    HEAD = ("Sucursal", "Id", "Nombre", "Ap. paterno", "Ap. materno", "RFC", "Domicilio principal", "Dirs.")
    WIDTHS = (100, 80, 110, 110, 110, 120, 360, 50)
    ACOLS = ("Id", "Street", "Number", "Neighborhood", "State", "ZIPCode")
    AHEAD = ("Id", "Calle", "Número", "Colonia", "Estado", "C.P.")
    AWIDTHS = (80, 240, 80, 180, 140, 70)

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.rows = {}
        self.addresses = {}
        self.last_search = (SEARCH_ALL, "", None)

        bar = ttk.LabelFrame(self, text="Búsqueda", padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="Buscar por").pack(side="left")
        self.mode = ttk.Combobox(bar, values=[m[0] for m in SEARCH_MODES], state="readonly", width=11)
        self.mode.current(0)
        self.mode.pack(side="left", padx=6)
        self.text = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.text, width=34)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: self.search())
        ttk.Label(bar, text="en").pack(side="left", padx=(8, 0))
        self.scope = NodeCombo(bar, [], extra_first=ALL_BRANCHES, width=20)
        self.scope.pack(side="left", padx=6)
        ttk.Button(bar, text="Buscar", command=self.search, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(bar, text="Listar todos", command=self.list_all).pack(side="left", padx=4)
        self.count = ttk.Label(bar, text="", foreground="#555")
        self.count.pack(side="right")

        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, pady=(8, 0))

        top = ttk.Frame(paned)
        btns = ttk.Frame(top)
        btns.pack(fill="x", pady=(0, 4))
        ttk.Label(btns, text="Clientes", style="Title.TLabel").pack(side="left")
        ttk.Button(btns, text="Eliminar cliente", command=self.delete_client).pack(side="right")
        ttk.Button(btns, text="Editar cliente", command=self.edit_client).pack(side="right", padx=4)
        ttk.Button(btns, text="Nuevo cliente", command=self.new_client).pack(side="right")
        frame, self.tree = make_tree(top, self.COLS, self.HEAD, self.WIDTHS, height=12)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.load_addresses())
        self.tree.bind("<Double-1>", lambda e: self.edit_client())
        paned.add(top, weight=3)

        bottom = ttk.Frame(paned)
        abtns = ttk.Frame(bottom)
        abtns.pack(fill="x", pady=(6, 4))
        self.addr_title = ttk.Label(abtns, text="Direcciones", style="Title.TLabel")
        self.addr_title.pack(side="left")
        ttk.Button(abtns, text="Eliminar dirección", command=self.delete_address).pack(side="right")
        ttk.Button(abtns, text="Editar dirección", command=self.edit_address).pack(side="right", padx=4)
        ttk.Button(abtns, text="Nueva dirección", command=self.new_address).pack(side="right")
        aframe, self.atree = make_tree(bottom, self.ACOLS, self.AHEAD, self.AWIDTHS, height=5)
        aframe.pack(fill="both", expand=True)
        self.atree.bind("<Double-1>", lambda e: self.edit_address())
        paned.add(bottom, weight=2)

    # ------------------------------------------------------------- eventos
    def on_nodes_changed(self):
        current = self.scope.selected_node()
        self.scope.nodes = self.app.nodes
        self.scope["values"] = [ALL_BRANCHES] + [n.name for n in self.app.nodes]
        ids = [n.id for n in self.app.nodes]
        self.scope.current(ids.index(current.id) + 1 if current and current.id in ids else 0)
        self.list_all()

    def _run_search(self, mode, text, scope_id):
        self.last_search = (mode, text, scope_id)
        origin = self.app.origin_node()

        def done(result):
            rows, errors = result
            self._fill(rows)
            self.app.report_partial(errors)

        self.app.run_task(lambda: self.app.dp.search_clients(mode, text, origin, scope_id), done,
                          "Consultando sucursales…")

    def search(self):
        mode = dict(SEARCH_MODES)[self.mode.get()]
        node = self.scope.selected_node()
        self._run_search(mode, self.text.get(), node.id if node else None)

    def list_all(self):
        node = self.scope.selected_node()
        self._run_search(SEARCH_ALL, "", node.id if node else None)

    def refresh(self, select=None):
        mode, text, scope_id = self.last_search
        origin = self.app.origin_node()

        def done(result):
            rows, errors = result
            self._fill(rows, select)
            self.app.report_partial(errors)

        self.app.run_task(lambda: self.app.dp.search_clients(mode, text, origin, scope_id), done,
                          "Actualizando…")

    def after_change(self, node_id, client_id):
        self.refresh(select=(node_id, client_id))

    def _fill(self, rows, select=None):
        self.tree.delete(*self.tree.get_children())
        self.atree.delete(*self.atree.get_children())
        self.rows.clear()
        target = None
        for r in rows:
            iid = f"{r['NodeId']}:{r['Id']}"
            self.rows[iid] = r
            self.tree.insert("", "end", iid=iid, values=[("" if r.get(c) is None else r.get(c)) for c in self.COLS])
            if select and (r["NodeId"], r["Id"]) == tuple(select):
                target = iid
        nodes = len({r["NodeId"] for r in rows})
        self.count.configure(text=f"{len(rows)} cliente(s) en {nodes} sucursal(es)")
        self.addr_title.configure(text="Direcciones")
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)

    def selected_client(self, warn=True):
        sel = self.tree.selection()
        if not sel:
            if warn:
                messagebox.showinfo("Clientes", "Selecciona un cliente de la lista.", parent=self)
            return None
        return self.rows[sel[0]]

    def selected_address(self):
        sel = self.atree.selection()
        if not sel:
            messagebox.showinfo("Direcciones", "Selecciona una dirección.", parent=self)
            return None
        return self.addresses[sel[0]]

    def load_addresses(self):
        c = self.selected_client(warn=False)
        if not c:
            return
        self.addr_title.configure(text=f"Direcciones de {c['Name']} {c['PaternalSurname']} ({c['Branch']})")

        def done(rows):
            if self.selected_client(warn=False) is not c:
                return
            self.atree.delete(*self.atree.get_children())
            self.addresses.clear()
            for a in rows:
                iid = str(a["Id"])
                self.addresses[iid] = a
                self.atree.insert("", "end", iid=iid, values=[("" if a.get(k) is None else a.get(k)) for k in self.ACOLS])

        self.app.run_task(lambda: self.app.dp.get_addresses(c["NodeId"], c["Id"]), done, "Leyendo direcciones…")

    # ---------------------------------------------------------- acciones
    def new_client(self):
        if not self.app.nodes:
            messagebox.showwarning("Sin nodos", "No hay sucursales registradas.", parent=self)
            return
        ClientDialog(self)

    def edit_client(self):
        c = self.selected_client()
        if c:
            ClientDialog(self, c)

    def delete_client(self):
        c = self.selected_client()
        if not c:
            return
        if messagebox.askyesno("Eliminar cliente",
                               f"¿Eliminar al cliente {c['Id']} ({c['Name']} {c['PaternalSurname']}, {c['RFC']}) "
                               f"y todas sus direcciones de la sucursal {c['Branch']}?\nNo se puede deshacer.",
                               icon="warning", parent=self):
            self.app.run_task(lambda: self.app.dp.delete_client(c["NodeId"], c["Id"]),
                              lambda _: self.refresh(), "Eliminando cliente…")

    def new_address(self):
        c = self.selected_client()
        if c:
            AddressDialog(self, c)

    def edit_address(self):
        c = self.selected_client()
        a = c and self.selected_address()
        if a:
            AddressDialog(self, c, a)

    def delete_address(self):
        c = self.selected_client()
        a = c and self.selected_address()
        if a and messagebox.askyesno("Eliminar dirección", f"¿Eliminar la dirección {a['Street']} {a['Number']}?",
                                     icon="warning", parent=self):
            self.app.run_task(lambda: self.app.dp.delete_address(c["NodeId"], a["Id"]),
                              lambda _: self.after_change(c["NodeId"], c["Id"]), "Eliminando dirección…")
