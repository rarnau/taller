"""Servicios de integracion entre la nueva GUI Qt y el motor de simulacion.

Esta capa encapsula llamadas a ``cli.py`` y mantiene la GUI desacoplada del
modelo para facilitar pruebas y evolucion incremental.
"""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from cli import (
    ctx_paralelo,
    init_worker_simulacion,
    simular_cambios_worker,
)


@dataclass
class SimulationRequest:
    """Payload minimo para ejecutar una simulacion desde la GUI."""

    cfg: Dict[str, Any]
    stock_df: "pd.DataFrame"
    cambios_df: "pd.DataFrame"
    estrategia: str = "mayor_diametro"


class SimulationService:
    """Adaptador de ejecucion para la simulacion en proceso separado.

    Replica el patron de la GUI actual: un ``ProcessPoolExecutor`` con
    ``initializer`` para fijar config/stock/estrategia por worker.
    """

    def __init__(self) -> None:
        self._executor: Optional[ProcessPoolExecutor] = None

    def submit(self, request: SimulationRequest) -> Future:
        """Lanza una simulacion y devuelve el future asociado."""
        # Se recrea por corrida para asegurar que el initializer reciba siempre
        # el cfg/stock/estrategia vigentes.
        self.shutdown()
        self._ensure_executor(request)
        assert self._executor is not None
        return self._executor.submit(simular_cambios_worker, request.cambios_df)

    def shutdown(self) -> None:
        """Libera el pool de procesos si existe."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _ensure_executor(self, request: SimulationRequest) -> None:
        """Crea el executor la primera vez.

        Para esta fase inicial se mantiene un solo worker, igual que la GUI
        legacy, priorizando paridad de comportamiento.
        """
        if self._executor is not None:
            return
        self._executor = ProcessPoolExecutor(
            max_workers=1,
            mp_context=ctx_paralelo(),
            initializer=init_worker_simulacion,
            initargs=(request.cfg, request.stock_df, request.estrategia),
        )
