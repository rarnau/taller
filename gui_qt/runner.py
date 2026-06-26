"""Runner de simulación: corre el motor en un proceso aparte sin congelar Qt.

Reutiliza **exactamente** el mismo patrón que ``gui/app.py`` (CustomTkinter):
``ProcessPoolExecutor`` con el *initializer* de ``cli`` y un sondeo del ``future``.
Aquí el sondeo se hace con un ``QTimer`` (análogo Qt de ``self.after``). La
simulación es CPU-bound en Python puro: un hilo no basta (el GIL congela la UI),
por eso va en un proceso separado y el taller resultante vuelve por pickle.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any, Optional

import pandas as pd
from PySide6.QtCore import QObject, QTimer, Signal

import cli
from modelos import generador_cambios as gencambios


class SimRunner(QObject):
    """Lanza una simulación y emite ``finished(taller)`` o ``error(str)``."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._executor: Optional[ProcessPoolExecutor] = None
        self._future = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self.corriendo = False

    def lanzar(self, cfg: dict, stock_df: pd.DataFrame,
               cambios_df: Optional[pd.DataFrame], estrategia: str) -> None:
        if self.corriendo:
            return
        if cambios_df is None:
            cambios_df = pd.DataFrame(columns=gencambios.COLUMNAS_SALIDA)
        self.corriendo = True
        # Mismo camino que el runner paralelo del CLI: stock+config+estrategia se
        # cargan una vez por worker (initializer) y la tarea solo manda cambios_df.
        self._executor = ProcessPoolExecutor(
            max_workers=1, mp_context=cli.ctx_paralelo(),
            initializer=cli.init_worker_simulacion,
            initargs=(cfg, stock_df, estrategia))
        self._future = self._executor.submit(cli.simular_cambios_worker, cambios_df)
        self._timer.start()

    def _poll(self) -> None:
        fut = self._future
        if fut is None or not fut.done():
            return
        self._timer.stop()
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        self._future = None
        self.corriendo = False
        try:
            taller = fut.result()
        except Exception as e:  # noqa: BLE001 - se reporta a la UI
            self.error.emit(str(e))
            return
        self.finished.emit(taller)
