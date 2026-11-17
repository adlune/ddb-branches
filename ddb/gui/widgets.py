"""Componentes reutilizables de la interfaz (Tkinter/ttk)."""
import tkinter as tk
from tkinter import ttk


def make_tree(parent, columns, headings=None, widths=None, height=10):
    """Treeview con barras de desplazamiento. Devuelve (frame, tree)."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode="browse")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    set_tree_columns(tree, columns, headings, widths)
    return frame, tree


def set_tree_columns(tree, columns, headings=None, widths=None):
    tree.delete(*tree.get_children())
    tree["columns"] = columns
    for i, col in enumerate(columns):
        tree.heading(col, text=(headings[i] if headings else col),
                     command=lambda c=col: sort_tree(tree, c, False))
        tree.column(col, width=(widths[i] if widths else 120), anchor="w", stretch=True)


def sort_tree(tree, col, reverse):
    items = [(tree.set(k, col), k) for k in tree.get_children("")]

    def key(item):
        v = item[0]
        try:
            return (0, float(v))
        except ValueError:
            return (1, v.casefold())

    items.sort(key=key, reverse=reverse)
    for idx, (_, k) in enumerate(items):
        tree.move(k, "", idx)
    tree.heading(col, command=lambda: sort_tree(tree, col, not reverse))


class Dialog(tk.Toplevel):
    """Ventana modal con botones Aceptar/Cancelar."""

    def __init__(self, parent, title, ok_text="Guardar"):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        self.ok_button = ttk.Button(buttons, text=ok_text, command=self.on_ok, style="Accent.TButton")
        self.ok_button.pack(side="right")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def show(self):
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()
        self.focus_set()

    def set_busy(self, busy: bool):
        self.ok_button.configure(state="disabled" if busy else "normal")

    def on_ok(self):
        raise NotImplementedError


class Form:
    """Rejilla de etiquetas + campos de texto."""

    def __init__(self, parent, fields, values=None, start_row=0, width=34):
        """fields: lista de (clave, etiqueta, obligatorio)."""
        self.vars = {}
        values = values or {}
        for i, (key, label, required) in enumerate(fields):
            ttk.Label(parent, text=label + (" *" if required else "")).grid(
                row=start_row + i, column=0, sticky="w", pady=3, padx=(0, 8))
            var = tk.StringVar(value="" if values.get(key) is None else str(values.get(key)))
            entry = ttk.Entry(parent, textvariable=var, width=width)
            entry.grid(row=start_row + i, column=1, sticky="ew", pady=3)
            self.vars[key] = var
            if i == 0:
                entry.focus_set()
        self.next_row = start_row + len(fields)

    def values(self):
        return {k: v.get() for k, v in self.vars.items()}


class NodeCombo(ttk.Combobox):
    """Combobox para seleccionar un nodo (sucursal)."""

    def __init__(self, parent, nodes, selected_id=None, extra_first=None, **kw):
        self.nodes = list(nodes)
        self.extra_first = extra_first
        labels = ([extra_first] if extra_first else []) + [n.name for n in self.nodes]
        super().__init__(parent, values=labels, state="readonly", **kw)
        idx = 0
        for i, n in enumerate(self.nodes):
            if n.id == selected_id:
                idx = i + (1 if extra_first else 0)
        if labels:
            self.current(idx)

    def selected_node(self):
        idx = self.current()
        if self.extra_first:
            idx -= 1
        if idx < 0 or idx >= len(self.nodes):
            return None
        return self.nodes[idx]
