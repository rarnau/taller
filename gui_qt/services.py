"""Servicios de integracion entre la nueva GUI Qt y el motor de simulacion.

Esta capa encapsula los entry-points GUI-free de ``runner.py`` y mantiene la GUI
desacoplada del modelo (y del CLI) para facilitar pruebas y evolucion incremental.
"""

from __future__ import annotations

import queue
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from montecarlo import EspecMonteCarlo, correr_montecarlo
from runner import (
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
    seed: Optional[int] = None  # seed de fallas (de la generación); None ⇒ sin fallas


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
            initargs=(request.cfg, request.stock_df, request.estrategia, request.seed),
        )


@dataclass
class MonteCarloRequest:
    """Payload para lanzar un estudio de Monte Carlo desde la GUI."""

    base_cfg: Dict[str, Any]
    stock_df: "pd.DataFrame"
    modelo: Dict[str, Any]
    spec: EspecMonteCarlo
    csv_path: str
    dump_dir: Optional[str] = None
    resume: bool = False
    max_workers: Optional[int] = None


class MonteCarloService:
    """Ejecuta ``correr_montecarlo`` en un hilo aparte y stream-ea el progreso.

    ``correr_montecarlo`` ya distribuye las corridas en **procesos** (su propio
    pool), por lo que el trabajo CPU-bound no toma el GIL del hilo de Qt. Acá lo
    corremos en un **hilo** de fondo (un ``ThreadPoolExecutor`` de 1) que bloquea
    esperando ese pool sin congelar el event loop, y publicamos el avance en una
    cola que la GUI sondea con su ``QTimer``.
    """

    def __init__(self) -> None:
        self._executor: Optional[ThreadPoolExecutor] = None
        self.progress: "queue.Queue[Tuple[int, int]]" = queue.Queue()

    def submit(self, request: MonteCarloRequest) -> Future:
        """Lanza el barrido y devuelve el future (resultado = lista de filas)."""
        self.shutdown()
        # Cola nueva por corrida para no arrastrar avances viejos.
        self.progress = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=1)
        return self._executor.submit(self._run, request)

    def _run(self, request: MonteCarloRequest) -> List[Dict[str, Any]]:
        return correr_montecarlo(
            request.base_cfg, request.stock_df, request.modelo, request.spec,
            csv_path=request.csv_path, dump_dir=request.dump_dir,
            resume=request.resume, max_workers=request.max_workers,
            on_progress=lambda hechos, total: self.progress.put((hechos, total)))

    def drain_progress(self) -> Optional[Tuple[int, int]]:
        """Devuelve el último avance publicado (o None si no hubo novedades)."""
        ultimo: Optional[Tuple[int, int]] = None
        try:
            while True:
                ultimo = self.progress.get_nowait()
        except queue.Empty:
            pass
        return ultimo

    def shutdown(self) -> None:
        """Libera el hilo de fondo si existe."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
