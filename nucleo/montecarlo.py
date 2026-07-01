"""Estudio de Monte Carlo: miles de simulaciones con parámetros sorteados.

Núcleo GUI-free del runner de miles de corridas. A diferencia de
``runner.batch_kpis`` (mismo ``cfg``, varía solo el ``Programa_Cambios``), acá
**cada corrida sortea** valores numéricos del taller dentro de rangos
``[min,max]`` (rates de producción/desbaste y tasa de falla por máquina, tiempo
de enfriado y de traslado al CRC), con selectores fijos (estrategias, generador,
ventana, turnos). Devuelve KPIs por corrida + un resumen estadístico, escribe un
CSV de una fila por corrida y puede volcar el taller completo a disco.

Reproducibilidad y reanudabilidad por **seed derivada**::

    seed_i = SeedSequence([master_seed, i]).generate_state(1)[0]

La corrida ``i`` sortea sus parámetros, genera sus cambios y realiza sus fallas
con ``seed_i``, así re-ejecutarla da el **mismo** resultado ⇒ reanudar = correr
solo los índices ausentes del CSV. La tarea del worker es **solo el índice** (lo
más liviano de picklear); el worker reconstruye todo desde el estado compartido
del *initializer* del pool. Reutiliza los primitivos de ``runner.py``.
"""
from __future__ import annotations

import copy
import csv
import logging
import os
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from config import persistencia as cfgmod
from modelos import generador_cambios as gencambios
from modelos import turnos as turnos_mod
from modelos.kpis import metricas_montecarlo
from nucleo.runner import construir_taller_desde_dataframes, ctx_paralelo

if TYPE_CHECKING:  # solo anotaciones (sin import duro de pandas)
    import pandas as pd

_IDENT = {"run", "seed", "master_seed"}


# ── Spec de parámetros ───────────────────────────────────────────────────────

@dataclass
class EspecMonteCarlo:
    """Configuración de un barrido: rangos numéricos + selectores fijos + N.

    ``rangos`` = ``{"tiempo_enfriado": [min,max], "tiempo_traslado_crc": [min,max],
    "maquinas": {nombre: {"rate_prod":[..], "rate_desb":[..], "tasa_falla":[..]}}}``.
    ``fijos`` = estrategias, generador, ``duracion_dias`` y presets de turnos.
    """

    runs: int = 500
    master_seed: Optional[int] = None
    chunk: int = 100
    fijos: Dict[str, Any] = field(default_factory=dict)
    rangos: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def desde_cfg(cls, cfg: Dict[str, Any]) -> "EspecMonteCarlo":
        """Construye la spec desde el bloque ``montecarlo`` del cfg (merge incluido)."""
        mc = cfgmod.obtener_montecarlo(cfg)
        return cls(runs=int(mc["runs"]), master_seed=mc.get("master_seed"),
                   chunk=int(mc["chunk"]), fijos=mc["fijos"], rangos=mc["rangos"])


# ── Muestreo y aplicación al cfg ─────────────────────────────────────────────

def _u(rng: "np.random.Generator", par: Any) -> float:
    """Sorteo uniforme en ``[min,max]`` (devuelve el extremo si el rango es nulo)."""
    lo, hi = float(par[0]), float(par[1])
    return lo if hi <= lo else float(rng.uniform(lo, hi))


def muestrear_overrides(spec: EspecMonteCarlo, rng: "np.random.Generator") -> Dict[str, Any]:
    """Sortea un conjunto de parámetros numéricos según los rangos de la spec."""
    r = spec.rangos
    ov: Dict[str, Any] = {
        "tiempo_enfriado": _u(rng, r["tiempo_enfriado"]),
        "tiempo_traslado_crc": _u(rng, r["tiempo_traslado_crc"]),
        "maquinas": {},
    }
    for nombre, rr in r.get("maquinas", {}).items():
        ov["maquinas"][nombre] = {
            "rate_prod": _u(rng, rr["rate_prod"]),
            "rate_desb": _u(rng, rr["rate_desb"]),
            "tasa_falla": _u(rng, rr["tasa_falla"]),
        }
    return ov


def aplicar_a_cfg(base_cfg: Dict[str, Any], overrides: Dict[str, Any],
                  spec: EspecMonteCarlo) -> Dict[str, Any]:
    """Devuelve una copia del cfg con los selectores fijos y los overrides aplicados.

    Los *rates* (mm/min) se convierten a ``mm`` manteniendo el ``tiempo_min`` de
    cada máquina (``mm = rate × tiempo_min``). Usa los mutadores de
    ``config/persistencia.py`` (no reinventa la escritura del cfg).
    """
    cfg = copy.deepcopy(base_cfg)
    fijos = spec.fijos

    cfgmod.set_sim(cfg, tiempo_enfriado=overrides.get("tiempo_enfriado"),
                   estrategia_seleccion=fijos.get("estrategia_seleccion"),
                   estrategia_asignacion=fijos.get("estrategia_asignacion"))
    if overrides.get("tiempo_traslado_crc") is not None:
        cfgmod.set_config_global(cfg, tiempo_traslado_crc_min=overrides["tiempo_traslado_crc"])
    if fijos.get("generador"):
        cfgmod.set_generador_cambios(cfg, generador=fijos["generador"])

    preset_maq = fijos.get("turnos_maquinas_preset")
    turnos_por_maquina = fijos.get("turnos_por_maquina") or {}
    for m in cfgmod.obtener_maquinas(cfg):
        nombre_m = m["nombre"]
        # Turno per-máquina tiene prioridad; luego el preset global (legacy).
        preset_this = turnos_por_maquina.get(nombre_m, preset_maq)
        if preset_this and preset_this in turnos_mod.PRESETS:
            grid = {k: list(v) for k, v in turnos_mod.PRESETS[preset_this].items()}
            cfgmod.set_maquina(cfg, nombre_m, turnos=grid)
        elif preset_this and preset_this not in turnos_mod.PRESETS:
            # Puede ser un string compacto personalizado
            try:
                grid_custom = {k: list(v) for k, v in
                               turnos_mod.expandir(turnos_mod.parse_compacto(preset_this)).items()}
                cfgmod.set_maquina(cfg, nombre_m, turnos=grid_custom)
            except Exception:
                pass  # String inválido: se deja el turno original de la máquina
    preset_lam = fijos.get("turnos_laminador_preset")
    if preset_lam and preset_lam in turnos_mod.PRESETS:
        cfgmod.set_turnos_cambios(
            cfg, {k: list(v) for k, v in turnos_mod.PRESETS[preset_lam].items()})

    maq_over = overrides.get("maquinas", {})
    for m in cfgmod.obtener_maquinas(cfg):
        o = maq_over.get(m["nombre"])
        if not o:
            continue
        tasas = m.get("tasas", {})
        prod_min = float(tasas.get("produccion", {}).get("tiempo_min", 60) or 60)
        desb_min = float(tasas.get("desbaste", {}).get("tiempo_min", 480) or 480)
        cfgmod.set_maquina(
            cfg, m["nombre"],
            prod_mm=o["rate_prod"] * prod_min if "rate_prod" in o else None,
            desb_mm=o["rate_desb"] * desb_min if "rate_desb" in o else None,
            tasa_falla=o.get("tasa_falla"))
    return cfg


def _seed_corrida(master: int, i: int) -> int:
    """Seed independiente y reproducible de la corrida ``i`` (stream propio)."""
    return int(np.random.SeedSequence([int(master), int(i)]).generate_state(1)[0])


# ── Worker del pool (initializer + tarea por índice) ─────────────────────────

_WORKER_STATE_MC: Dict[str, Any] = {}


def init_worker_montecarlo(base_cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                           modelo: Dict[str, Any], spec: EspecMonteCarlo,
                           dump_dir: Optional[str] = None) -> None:
    """*Initializer* del pool: fija el estado compartido (base_cfg/stock/modelo/spec)."""
    # Monte Carlo corre miles de simulaciones en procesos hijos: silenciamos el
    # logger del motor para no inundar stderr con avisos de cada corrida.
    logger_taller = logging.getLogger("modelos.taller")
    if not any(isinstance(h, logging.NullHandler) for h in logger_taller.handlers):
        logger_taller.addHandler(logging.NullHandler())
    logger_taller.propagate = False
    _WORKER_STATE_MC.update(base_cfg=base_cfg, stock_df=stock_df, modelo=modelo,
                            spec=spec, dump_dir=dump_dir)


def simular_montecarlo_worker(i: int) -> Dict[str, Any]:
    """Tarea del pool: corrida ``i`` completa, devuelve la fila de métricas.

    Sortea params con ``seed_i``, arma el cfg, genera los cambios, simula y
    devuelve ``metricas_montecarlo`` (KPIs planos) + el índice, la seed y los
    parámetros sorteados (columnas ``in_*``). Descarta el taller (salvo dump).
    """
    ws = _WORKER_STATE_MC
    spec: EspecMonteCarlo = ws["spec"]
    seed_i = _seed_corrida(spec.master_seed, i)
    rng = np.random.default_rng(seed_i)
    overrides = muestrear_overrides(spec, rng)
    cfg = aplicar_a_cfg(ws["base_cfg"], overrides, spec)

    cambios_df = gencambios.generar_cambios(
        ws["modelo"], cfg, seed=seed_i, horizonte_dias=spec.fijos.get("duracion_dias"))
    taller = construir_taller_desde_dataframes(cfg, ws["stock_df"], cambios_df)
    taller.simular(estrategia=spec.fijos.get("estrategia_seleccion", "mayor_diametro"),
                   callback_log=None, seed=seed_i)

    fila: Dict[str, Any] = {"run": int(i), "seed": int(seed_i),
                            "master_seed": int(spec.master_seed)}
    fila["in_tiempo_enfriado"] = overrides["tiempo_enfriado"]
    fila["in_tiempo_traslado_crc"] = overrides["tiempo_traslado_crc"]
    for nombre, o in overrides["maquinas"].items():
        fila[f"in_rate_prod_{nombre}"] = o["rate_prod"]
        fila[f"in_rate_desb_{nombre}"] = o["rate_desb"]
        fila[f"in_tasa_falla_{nombre}"] = o["tasa_falla"]
    fila.update(metricas_montecarlo(taller))

    if ws.get("dump_dir"):
        with open(os.path.join(ws["dump_dir"], f"run_{int(i):06d}.pkl"), "wb") as fp:
            pickle.dump(taller, fp)
    return fila


# ── Orquestador (paralelo, chunked, reanudable) ──────────────────────────────

def _num(v: Any) -> Any:
    """Convierte a float si se puede; si no, deja el string (lectura de CSV)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _leer_filas_csv(path: str) -> Tuple[List[Dict[str, Any]], Optional[List[str]], Optional[int]]:
    """Lee filas previas de un CSV (para reanudar): (filas, columnas, master_seed)."""
    filas: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        columnas = rd.fieldnames
        master: Optional[int] = None
        for row in rd:
            filas.append({k: _num(v) for k, v in row.items()})
            if master is None and row.get("master_seed"):
                master = int(float(row["master_seed"]))
    return filas, columnas, master


def _ordenar_columnas(fila: Dict[str, Any]) -> List[str]:
    """Ordena las columnas: identificadores, luego inputs ``in_*``, luego KPIs."""
    ident = [c for c in ("run", "seed", "master_seed") if c in fila]
    ins = sorted(c for c in fila if c.startswith("in_"))
    resto = sorted(c for c in fila if c not in ident and not c.startswith("in_"))
    return ident + ins + resto


def correr_montecarlo(base_cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                      modelo: Dict[str, Any], spec: EspecMonteCarlo, *,
                      csv_path: str, dump_dir: Optional[str] = None,
                      resume: bool = False,
                      on_progress: Optional[Callable[[int, int], None]] = None,
                      max_workers: Optional[int] = None) -> List[Dict[str, Any]]:
    """Corre ``spec.runs`` simulaciones en paralelo y escribe el CSV incremental.

    Devuelve **todas** las filas (las reanudadas + las nuevas) ordenadas por
    ``run``. Con ``resume`` lee el CSV existente, valida el ``master_seed`` y
    saltea los índices ya hechos. ``on_progress(hechos, total)`` se llama cada
    ``spec.chunk`` corridas. ``dump_dir`` (si se indica) recibe un pickle del
    taller por corrida.
    """
    master = gencambios.resolver_seed(spec.master_seed)
    spec = replace(spec, master_seed=master)
    total = int(spec.runs)

    filas_previas: List[Dict[str, Any]] = []
    columnas: Optional[List[str]] = None
    reanudando = bool(resume and os.path.exists(csv_path))
    if reanudando:
        filas_previas, columnas, prev_master = _leer_filas_csv(csv_path)
        if prev_master is not None and prev_master != master:
            raise ValueError(
                f"El CSV {csv_path} fue generado con master_seed={prev_master}, "
                f"distinto del pedido ({master}). Use otra ruta o el mismo seed.")

    hechos = {int(r["run"]) for r in filas_previas if "run" in r}
    pendientes = [i for i in range(total) if i not in hechos]
    if on_progress:
        on_progress(len(hechos), total)
    if not pendientes:
        return sorted(filas_previas, key=lambda r: int(r["run"]))

    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)

    nuevas: List[Dict[str, Any]] = []
    f = writer = None
    completados = 0
    try:
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx_paralelo(),
                                 initializer=init_worker_montecarlo,
                                 initargs=(base_cfg, stock_df, modelo, spec, dump_dir)) as ex:
            futuros = [ex.submit(simular_montecarlo_worker, i) for i in pendientes]
            for fut in as_completed(futuros):
                fila = fut.result()
                nuevas.append(fila)
                if writer is None:
                    if columnas is None:
                        columnas = _ordenar_columnas(fila)
                    f = open(csv_path, "a" if reanudando else "w", newline="", encoding="utf-8")
                    writer = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
                    if not reanudando:
                        writer.writeheader()
                writer.writerow(fila)
                completados += 1
                if on_progress and (completados % spec.chunk == 0 or completados == len(pendientes)):
                    f.flush()
                    on_progress(len(hechos) + completados, total)
    finally:
        if f is not None:
            f.close()

    return sorted(filas_previas + nuevas, key=lambda r: int(r["run"]))


# ── Agregación de resultados ─────────────────────────────────────────────────

def resumir(filas: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Estadísticas por KPI sobre las corridas: mean/std/p10/p50/p90 (+min/max/n).

    Resume las columnas de métricas (excluye identificadores y los inputs
    sorteados ``in_*``). Devuelve ``{kpi: {mean, std, p10, p50, p90, min, max, n}}``.
    """
    if not filas:
        return {}
    columnas = [c for c in filas[0]
                if c not in _IDENT and not c.startswith("in_")]
    resumen: Dict[str, Dict[str, float]] = {}
    for c in columnas:
        vals = np.array([float(r[c]) for r in filas
                         if isinstance(r.get(c), (int, float))], dtype=float)
        if vals.size == 0:
            continue
        resumen[c] = {
            "mean": float(np.mean(vals)), "std": float(np.std(vals)),
            "p10": float(np.percentile(vals, 10)), "p50": float(np.percentile(vals, 50)),
            "p90": float(np.percentile(vals, 90)),
            "min": float(vals.min()), "max": float(vals.max()), "n": int(vals.size),
        }
    return resumen


def exportar_resumen_csv(resumen: Dict[str, Dict[str, float]], ruta: str) -> None:
    """Escribe el resumen estadístico a un CSV (una fila por KPI)."""
    campos = ["variable", "mean", "std", "p10", "p50", "p90", "min", "max", "n"]
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for variable, st in resumen.items():
            w.writerow({"variable": variable, **st})
