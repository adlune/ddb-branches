"""Bitácora de eventos del DP/TP, observable desde la interfaz."""
import threading
from datetime import datetime


class EventLog:
    def __init__(self):
        self._listeners = []
        self._lock = threading.Lock()

    def subscribe(self, fn):
        with self._lock:
            self._listeners.append(fn)

    def __call__(self, tag: str, message: str) -> None:
        entry = (datetime.now(), tag, message)
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(entry)
            except Exception:
                pass
