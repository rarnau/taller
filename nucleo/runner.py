"""Entry-points reutilizables del motor, sin GUI ni argparse.

Núcleo programático compartido por el CLI (``cli.py``), la GUI
(``gui_qt/services.py``) y los tests: construir un taller, simularlo y correr
barridos en paralelo. No importa PySide6/Qt ni ``gui_qt/``, así que corre en
entornos sin display y es seguro de re-importar bajo ``multiprocessing`` (spawn
re-importa este módulo liviano, nunca la GUI).

La simulación es CPU-bound en Python puro, por lo que se ejecuta en procesos
aparte (no hilos: el GIL los serializa). El patrón de barrido comparte el mismo
stock + config + estrategia entre corridas (cargados una vez por worker vía el
*initializer* del pool) y varía solo el ``Programa_Cambios``.
"""
import json
import multiprocessing
import multiprocessing.context
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from config import persistencia as cfgmod
from config.persistencia import cargar_config
from modelos import generador_cambios as gencambios
from modelos.taller import TallerCilindros

if TYPE_CHECKING:  # solo para anotaciones (sin import duro de pandas)
    import pandas as pd


# ── Núcleo reutilizable ──────────────────────────────────────────────────────

def construir_taller(cfg: Dict[str, Any], ruta_excel: str) -> TallerCilindros:
    """Construye un taller configurado y con los datos del Excel cargados.

    Aplica primero la configuración estructural (``configurar``) y luego los
    datos (``cargar_datos``), en ese orden obligatorio. Pensado como base de un
    futuro runner de lotes: cada simulación crea su propia instancia
    independiente a partir de un mismo ``cfg``.
    """
    cfgmod.verificar_coherencia(cfg)  # jaulas ⇄ rangos: aborta antes de simular
    taller = TallerCilindros()
    taller.configurar(cfg)
    taller.cargar_datos(ruta_excel)
    return taller


def construir_taller_desde_dataframes(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                                      cambios_df: "pd.DataFrame") -> TallerCilindros:
    """Como ``construir_taller`` pero con DataFrames en memoria (sin I/O de disco).

    Base del runner batch: el stock se carga una vez y el ``cambios_df`` lo
    produce el generador para cada seed, sin escribir Excel intermedios.
    """
    cfgmod.verificar_coherencia(cfg)
    taller = TallerCilindros()
    taller.configurar(cfg)
    taller.cargar_datos_desde_dataframes(stock_df, cambios_df)
    return taller


def simular_desde_dataframes(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                             cambios_df: "pd.DataFrame",
                             estrategia: str = "mayor_diametro",
                             seed: Optional[int] = None) -> TallerCilindros:
    """Construye el taller desde DataFrames, simula y devuelve el taller resultante.

    Función **a nivel de módulo** y sin GUI: es picklable, así que la GUI la corre
    en un proceso aparte (``ProcessPoolExecutor``) para no congelar el event loop
    de Qt (el GIL no alcanza con un hilo para una simulación CPU-bound). El
    taller devuelto (snapshots, cilindros, máquinas, alertas) viaja por pickle.
    ``seed`` determina la realización de fallas de máquina (ver
    ``TallerCilindros.simular``); en Monte Carlo suele ser la misma seed que generó
    el ``cambios_df``.
    """
    taller = construir_taller_desde_dataframes(cfg, stock_df, cambios_df)
    taller.simular(estrategia=estrategia, callback_log=None, seed=seed)
    return taller


# ── Ejecución en procesos (worker reutilizable + barridos en paralelo) ────────
#
# Para barridos de muchas corridas que comparten el MISMO stock + config +
# estrategia y solo varían el ``Programa_Cambios`` (p. ej. distintas seeds del
# generador), el stock/config/estrategia se cargan **una sola vez por worker**
# vía un *initializer* del pool y cada tarea envía únicamente su ``cambios_df``
# — lo más liviano de serializar. Lo usan tanto la GUI (una corrida) como
# ``batch_simular`` (N corridas en paralelo).

# Estado por-worker: lo siembra el initializer en cada proceso del pool (no es
# estado global compartido entre procesos — cada worker tiene su propia copia).
_WORKER_STATE: Dict[str, Any] = {}


def ctx_paralelo() -> multiprocessing.context.BaseContext:
    """Contexto de multiprocessing preferido: ``fork`` si está disponible.

    Con ``fork`` el worker hereda los módulos ya importados (sin re-importar ni
    re-ejecutar nada — clave cuando el padre es la GUI). Si la plataforma no
    soporta fork (p. ej. Windows) se cae a ``spawn``; como el initializer y la
    tarea viven en este módulo (sin GUI), spawn solo re-importa ``runner``.
    """
    metodos = multiprocessing.get_all_start_methods()
    return multiprocessing.get_context("fork" if "fork" in metodos else "spawn")


def init_worker_simulacion(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                           estrategia: str = "mayor_diametro",
                           seed: Optional[int] = None) -> None:
    """*Initializer* del pool: fija el stock+config+estrategia(+seed) compartidos del worker.

    Se ejecuta una vez por proceso del pool; luego cada tarea
    (``simular_cambios_worker``) reusa estos valores sin volver a serializarlos.
    ``seed`` es la seed de fallas **compartida** por defecto; ``simular_cambios_worker``
    con una tarea ``(cambios_df, seed)`` la sobreescribe por corrida (Monte Carlo).
    """
    _WORKER_STATE["cfg"] = cfg
    _WORKER_STATE["stock_df"] = stock_df
    _WORKER_STATE["estrategia"] = estrategia
    _WORKER_STATE["seed"] = seed


def simular_cambios_worker(tarea: Any) -> TallerCilindros:
    """Tarea del pool: simula con el stock/config/estrategia del worker + la tarea.

    ``tarea`` puede ser el ``cambios_df`` solo (usa la seed compartida del
    initializer, p. ej. la GUI con seed=None) o una tupla ``(cambios_df, seed)``
    para barridos de Monte Carlo donde cada corrida lleva su propia seed de fallas
    (típicamente la misma que generó ese ``cambios_df``). Requiere que
    ``init_worker_simulacion`` haya corrido en este proceso. Devuelve el taller.
    """
    if isinstance(tarea, tuple):
        cambios_df, seed = tarea
    else:
        cambios_df, seed = tarea, _WORKER_STATE.get("seed")
    return simular_desde_dataframes(
        _WORKER_STATE["cfg"], _WORKER_STATE["stock_df"], cambios_df,
        _WORKER_STATE["estrategia"], seed=seed)


def batch_simular(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                  lista_cambios: List["pd.DataFrame"],
                  estrategia: str = "mayor_diametro",
                  max_workers: Optional[int] = None,
                  seeds: Optional[List[Optional[int]]] = None) -> List[TallerCilindros]:
    """Corre N simulaciones en paralelo: mismo stock+config+estrategia, distintos cambios.

    El stock/config/estrategia se cargan **una vez por worker** (initializer) y cada
    tarea solo manda su ``cambios_df``. Devuelve la lista de tallers en el **mismo
    orden** que ``lista_cambios``. Pensado para barridos de seeds del generador
    (combinar con ``gencambios.generar_cambios`` para producir cada ``cambios_df``).

    ``seeds`` (opcional, alineada con ``lista_cambios``) fija la seed de **fallas**
    por corrida — la base de Monte Carlo: cada simulación realiza sus fallas con la
    misma seed que generó su ``cambios_df``. Si se omite, todas comparten ``None``
    (sin fallas reproducibles).
    """
    if not lista_cambios:
        return []
    if seeds is not None and len(seeds) != len(lista_cambios):
        raise ValueError("seeds debe tener el mismo largo que lista_cambios.")
    tareas: List[Any] = (list(zip(lista_cambios, seeds)) if seeds is not None
                         else list(lista_cambios))
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx_paralelo(),
                             initializer=init_worker_simulacion,
                             initargs=(cfg, stock_df, estrategia)) as ex:
        return list(ex.map(simular_cambios_worker, tareas))


def generar_y_construir(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                        modelo: Dict[str, Any], *, seed: Optional[int] = None,
                        horizonte_dias: Optional[int] = None) -> TallerCilindros:
    """Genera el Programa_Cambios desde ``modelo`` y arma el taller listo a simular.

    Pensado para que un runner paralelo itere sobre seeds reusando el mismo
    ``stock_df`` y ``modelo`` ya ajustado.
    """
    cambios_df = gencambios.generar_cambios(modelo, cfg, seed=seed,
                                            horizonte_dias=horizonte_dias)
    return construir_taller_desde_dataframes(cfg, stock_df, cambios_df)


def cargar_config_path(config_path: Optional[str]) -> Dict[str, Any]:
    """Carga la configuración del JSON indicado, o la de usuario por defecto."""
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            return cfgmod.migrar(json.load(f))
    return cargar_config()


def ejecutar_simulacion(ruta_excel: str, estrategia: str = "mayor_diametro",
                        config_path: Optional[str] = None,
                        callback_log: Optional[Callable[[str], None]] = print,
                        tiempo_enfriado: Optional[float] = None,
                        max_iteraciones: Optional[int] = None,
                        seed: Optional[int] = None) -> TallerCilindros:
    """Carga datos + configuración, ejecuta la simulación y devuelve el taller.

    Replica la orquestación de la GUI pero sin GUI. ``tiempo_enfriado`` y
    ``max_iteraciones``, si se indican, tienen prioridad sobre el valor del JSON.
    ``seed`` determina la realización de las fallas de máquina (ver
    ``TallerCilindros.simular``); ``None`` ⇒ sin fallas reproducibles.
    """
    cfg = cargar_config_path(config_path)
    if tiempo_enfriado is not None:
        cfg["tiempo_enfriado_h"] = tiempo_enfriado
    if max_iteraciones is not None:
        cfg["max_iteraciones"] = max_iteraciones

    taller = construir_taller(cfg, ruta_excel)

    if callback_log:
        for aviso in taller.avisos_carga:
            callback_log(aviso)

    taller.simular(estrategia=estrategia, callback_log=callback_log, seed=seed)
    return taller
