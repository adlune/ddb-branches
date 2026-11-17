"""Ventana principal de la aplicación."""
import queue
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, scrolledtext, ttk

from .. import config
from ..catalog import Catalog
from ..db import ConnInfo
from ..dp import DataProcessor, DistributedError
from ..eventlog import EventLog
from ..tp import TransactionError
from ..validation import ValidationError
from .clients_tab import ClientsTab
from .nodes_tab import NodesTab
from .tables_tab import TablesTab
from .widgets import NodeCombo

TAG_COLORS = {"DP": "#1f5fa8", "TP": "#a8541f", "CAT": "#2e7d32", "ERR": "#c62828", "APP": "#555555"}


class LoginDialog(tk.Toplevel):
    """Conexión al catálogo global."""

    def __init__(self, root):
        super().__init__(root)
        self.title("Conectar al catálogo global")
        self.resizable(False, False)
        self.result = None
        cfg = config.load()
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Sistema distribuido de sucursales", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.vars = {}
        fields = [("host", "Servidor"), ("port", "Puerto"), ("user", "Usuario"),
                  ("password", "Contraseña"), ("database", "BD del catálogo")]
        for i, (k, label) in enumerate(fields, start=1):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            var = tk.StringVar(value=cfg[k])
            ttk.Entry(frm, textvariable=var, width=30, show="•" if k == "password" else "").grid(
                row=i, column=1, sticky="ew", pady=3)
            self.vars[k] = var
        self.save_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Recordar (sin contraseña)", variable=self.save_var).grid(
            row=6, column=1, sticky="w", pady=(6, 0))
        self.msg = ttk.Label(frm, text="", foreground="#c62828", wraplength=320)
        self.msg.grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Salir", command=self.cancel).pack(side="right")
        self.ok = ttk.Button(btns, text="Conectar", command=self.connect)
        self.ok.pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self.connect())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 3
        self.geometry(f"+{x}+{y}")

    def cancel(self):
        self.result = None
        self.destroy()

    def connect(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        try:
            info = ConnInfo(v["host"], int(v["port"]), v["user"], self.vars["password"].get(), v["database"])
        except ValueError:
            self.msg.configure(text="El puerto debe ser numérico.")
            return
        self.ok.configure(state="disabled")
        self.msg.configure(text="Conectando…", foreground="#555555")
        self.update()
        try:
            catalog = Catalog(info)
            catalog.ensure_schema()
        except Exception as exc:
            self.msg.configure(text=f"No se pudo conectar: {exc}", foreground="#c62828")
            self.ok.configure(state="normal")
            return
        if self.save_var.get():
            config.save(v)
        self.result = catalog
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("DDB Sucursales — Procesador de Datos y Transacciones")
        self.geometry("1180x720")
        self.minsize(960, 600)
        self._setup_style()

        self.events = EventLog()
        self._queue = queue.Queue()
        self.events.subscribe(lambda entry: self._queue.put(("log", entry, None)))
        self._busy = 0

        login = LoginDialog(self)
        self.wait_window(login)
        if login.result is None:
            self.destroy()
            return
        self.catalog = login.result
        self.dp = DataProcessor(self.catalog, self.events)
        self.nodes = []

        self._build()
        self.deiconify()
        self.after(50, self._poll)
        self.events("APP", f"Conectado al catálogo {self.catalog.info.host}:{self.catalog.info.port}/"
                           f"{self.catalog.info.database}")
        self.refresh_nodes()

    # ------------------------------------------------------------------ estilo
    def _setup_style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=24)
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))

    # ------------------------------------------------------------- estructura
    def _build(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Sucursal actual (origen de las peticiones):").pack(side="left")
        self.origin_combo = NodeCombo(top, [], width=22)
        self.origin_combo.pack(side="left", padx=6)
        self.origin_combo.bind("<<ComboboxSelected>>", lambda e: self.events(
            "APP", f"Sucursal actual: {self.origin_node().name if self.origin_node() else '-'}"))
        ttk.Button(top, text="Actualizar nodos", command=self.refresh_nodes).pack(side="left", padx=6)
        info = self.catalog.info
        ttk.Label(top, text=f"Catálogo: {info.user}@{info.host}:{info.port}/{info.database}",
                  foreground="#555").pack(side="right")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.clients_tab = ClientsTab(self.notebook, self)
        self.tables_tab = TablesTab(self.notebook, self)
        self.nodes_tab = NodesTab(self.notebook, self)
        log_frame = ttk.Frame(self.notebook, padding=8)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, font=("Consolas", 9), state="disabled")
        self.log_text.pack(fill="both", expand=True)
        for tag, color in TAG_COLORS.items():
            self.log_text.tag_configure(tag, foreground=color)
        ttk.Button(log_frame, text="Limpiar bitácora", command=self._clear_log).pack(anchor="e", pady=(6, 0))
        self.notebook.add(self.clients_tab, text="  Clientes  ")
        self.notebook.add(self.tables_tab, text="  Tablas distribuidas  ")
        self.notebook.add(self.nodes_tab, text="  Nodos  ")
        self.notebook.add(log_frame, text="  Bitácora DP / TP  ")

        self.status = tk.StringVar(value="Listo")
        bar = ttk.Frame(self, padding=(10, 2))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.progress.pack(side="right")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ----------------------------------------------------------------- nodos
    def origin_node(self):
        return self.origin_combo.selected_node()

    def refresh_nodes(self, then=None):
        def done(nodes):
            current = self.origin_node()
            self.nodes = nodes
            self.origin_combo.nodes = nodes
            self.origin_combo["values"] = [n.name for n in nodes]
            if nodes:
                ids = [n.id for n in nodes]
                self.origin_combo.current(ids.index(current.id) if current and current.id in ids else 0)
            for tab in (self.clients_tab, self.tables_tab, self.nodes_tab):
                tab.on_nodes_changed()
            if then:
                then()
        self.run_task(self.dp.nodes, done, "Leyendo catálogo de nodos…")

    # --------------------------------------------------------- tareas en hilo
    def run_task(self, fn, on_ok=None, busy_text="Procesando…", parent=None, on_error=None):
        """Ejecuta fn() en un hilo y llama on_ok(resultado) en el hilo de la interfaz."""
        self._busy += 1
        self.status.set(busy_text)
        self.progress.start(12)
        self.configure(cursor="watch")

        def worker():
            try:
                result = fn()
                self._queue.put(("ok", on_ok, result))
            except Exception as exc:
                self._queue.put(("err", (exc, traceback.format_exc(), parent, on_error), None))

        threading.Thread(target=worker, daemon=True).start()

    def _task_finished(self):
        self._busy = max(0, self._busy - 1)
        if not self._busy:
            self.progress.stop()
            self.configure(cursor="")
            self.status.set("Listo")

    def _poll(self):
        try:
            while True:
                kind, a, b = self._queue.get_nowait()
                if kind == "log":
                    self._append_log(a)
                elif kind == "ok":
                    self._task_finished()
                    if a:
                        try:
                            a(b)
                        except Exception as exc:
                            self._show_error(exc, traceback.format_exc(), None)
                elif kind == "err":
                    self._task_finished()
                    exc, tb, parent, on_error = a
                    self._show_error(exc, tb, parent)
                    if on_error:
                        on_error(exc)
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _append_log(self, entry):
        ts, tag, msg = entry
        self.log_text.configure(state="normal")
        self.log_text.insert("end", ts.strftime("%H:%M:%S "), "APP")
        self.log_text.insert("end", f"[{tag:<3}] ", tag)
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _show_error(self, exc, tb, parent):
        parent = parent or self
        if isinstance(exc, ValidationError):
            messagebox.showwarning("Datos no válidos", str(exc), parent=parent)
            return
        self.events("ERR", str(exc))
        if isinstance(exc, (DistributedError, TransactionError)):
            messagebox.showerror("Error del sistema distribuido", str(exc), parent=parent)
        else:
            print(tb)
            messagebox.showerror("Error", f"{type(exc).__name__}: {exc}", parent=parent)

    def report_partial(self, errors, parent=None):
        """Avisa cuando algunos nodos no respondieron (resultados parciales)."""
        if errors:
            self.status.set("Resultados parciales: sin respuesta de " + ", ".join(errors))
            messagebox.showwarning(
                "Nodos no disponibles",
                "Los resultados son parciales. No respondieron:\n\n"
                + "\n".join(f"• {k}: {v}" for k, v in errors.items()),
                parent=parent or self,
            )


def main():
    app = App()
    try:
        if app.winfo_exists():
            app.mainloop()
    except tk.TclError:
        pass
