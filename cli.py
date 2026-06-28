#!/usr/bin/env python3
"""Headless mode: simulation and configuration management from the command line.

It does not import Tkinter or anything from ``gui/``, so it runs in display-less
environments (servers, CI, statistics batches). The ``run_simulation`` function
and the ``build_workshop`` helper are reusable programmatically (e.g. by a future
change generator or a runner of thousands of parallel simulations) without firing
the argument parser.

Subcommands::

    cli.py simular <excel> [opciones]
    cli.py config show | export <json> | import <json> | import-excel <excel>
    cli.py config global [--diametro-max --diametro-min --crc-min --jaulas]
    cli.py config maquina list|add|remove|set [flags]
    cli.py config jaula   list|set|remove     [flags, set acepta --perfil]
    cli.py config sim [--tiempo-enfriado --max-iteraciones --estrategia-asignacion]
"""
import argparse
import json
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from config import persistencia as cfgmod
from config import modelo_generador as modmod
from config.persistencia import (cargar_config, guardar_config, obtener_maquinas,
                                  obtener_max_iteraciones, obtener_rangos,
                                  obtener_tiempo_enfriado, obtener_estrategia_asignacion)
from models.enums import GrindingType
from models.kpis import compute_kpis
from models.strategies import SELECTION_STRATEGIES, ASSIGNMENT_STRATEGIES
from models import change_generator as gencambios
from models.workshop import CylinderWorkshop
from models import shifts as shifts_mod

_TIPOS_RECT = [t.value for t in GrindingType]


def _resolve_shifts(args) -> Optional[Dict[str, Any]]:
    """Get the shift schedule from --turnos-preset or --turnos (or None)."""
    if getattr(args, "turnos_preset", None):
        return {k: list(v) for k, v in shifts_mod.PRESETS[args.turnos_preset].items()}
    if getattr(args, "turnos", None):
        return shifts_mod.parse_compact(args.turnos)
    return None


# ── Reusable core (no argparse) ──────────────────────────────────────────────

def build_workshop(cfg: Dict[str, Any], excel_path: str) -> CylinderWorkshop:
    """Build a configured workshop with the Excel data loaded.

    Applies the structural configuration first (``configure``) and then the data
    (``load_data``), in that mandatory order. Designed as the base of a future
    batch runner: each simulation creates its own independent instance from the
    same ``cfg``.
    """
    cfgmod.verificar_coherencia(cfg)  # stands ⇄ ranges: abort before simulating
    workshop = CylinderWorkshop()
    workshop.configure(cfg)
    workshop.load_data(excel_path)
    return workshop


def build_workshop_from_dataframes(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                                   cambios_df: "pd.DataFrame") -> CylinderWorkshop:
    """Like ``build_workshop`` but with in-memory DataFrames (no disk I/O).

    Base of the batch runner: the stock is loaded once and the ``cambios_df`` is
    produced by the generator for each seed, without writing intermediate Excels.
    """
    cfgmod.verificar_coherencia(cfg)
    workshop = CylinderWorkshop()
    workshop.configure(cfg)
    workshop.load_data_from_dataframes(stock_df, cambios_df)
    return workshop


def simulate_from_dataframes(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                             cambios_df: "pd.DataFrame",
                             estrategia: str = "mayor_diametro") -> CylinderWorkshop:
    """Build the workshop from DataFrames, simulate and return the resulting workshop.

    A **module-level**, GUI-free function: it is picklable, so the GUI runs it in
    a separate process (``ProcessPoolExecutor``) to avoid freezing the Tkinter
    event loop (a single thread is not enough for a CPU-bound simulation under the
    GIL). The returned workshop (snapshots, cylinders, machines, alerts) travels
    back by pickle.
    """
    workshop = build_workshop_from_dataframes(cfg, stock_df, cambios_df)
    workshop.simulate(strategy=estrategia, callback_log=None)
    return workshop


# ── Process execution (reusable worker + parallel sweeps) ─────────────────────
#
# The simulation is CPU-bound pure Python, so it runs in separate processes (not
# threads: the GIL serializes them). For sweeps of many runs sharing the SAME
# stock + config + strategy and only varying the ``Programa_Cambios`` (e.g.
# different generator seeds), the stock/config/strategy are loaded **once per
# worker** via a pool *initializer* and each task sends only its ``cambios_df`` —
# the lightest thing to serialize. Used both by the GUI (one run) and by
# ``batch_simular`` (N runs in parallel).

# Per-worker state: seeded by the initializer in each pool process (not global
# state shared across processes — each worker has its own copy).
_WORKER_STATE: Dict[str, Any] = {}


def ctx_paralelo() -> "multiprocessing.context.BaseContext":
    """Preferred multiprocessing context: ``fork`` if available.

    With ``fork`` the worker inherits the already-imported modules (without
    re-importing or re-running anything — key when the parent is the GUI). If the
    platform does not support fork (e.g. Windows) it falls back to ``spawn``; as
    the initializer and the task live in this module (no GUI), spawn only
    re-imports ``cli``.
    """
    metodos = multiprocessing.get_all_start_methods()
    return multiprocessing.get_context("fork" if "fork" in metodos else "spawn")


def init_worker_simulacion(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                           estrategia: str = "mayor_diametro") -> None:
    """Pool *initializer*: sets the worker's shared stock+config+strategy.

    Runs once per pool process; then each task (``simular_cambios_worker``) reuses
    these values without serializing them again.
    """
    _WORKER_STATE["cfg"] = cfg
    _WORKER_STATE["stock_df"] = stock_df
    _WORKER_STATE["estrategia"] = estrategia


def simular_cambios_worker(cambios_df: "pd.DataFrame") -> CylinderWorkshop:
    """Pool task: simulate with the worker's stock/config/strategy + ``cambios_df``.

    Requires ``init_worker_simulacion`` to have run in this process (the
    ``ProcessPoolExecutor`` initializer does it). Returns the resulting workshop.
    """
    return simulate_from_dataframes(
        _WORKER_STATE["cfg"], _WORKER_STATE["stock_df"], cambios_df,
        _WORKER_STATE["estrategia"])


def batch_simular(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                  lista_cambios: List["pd.DataFrame"],
                  estrategia: str = "mayor_diametro",
                  max_workers: Optional[int] = None) -> List[CylinderWorkshop]:
    """Run N simulations in parallel: same stock+config+strategy, different changes.

    The stock/config/strategy are loaded **once per worker** (initializer) and
    each task only sends its ``cambios_df``. Returns the workshops in the **same
    order** as ``lista_cambios``. Designed for generator seed sweeps (combine with
    ``gencambios.generate_changes`` to produce each ``cambios_df``).
    """
    if not lista_cambios:
        return []
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx_paralelo(),
                             initializer=init_worker_simulacion,
                             initargs=(cfg, stock_df, estrategia)) as ex:
        return list(ex.map(simular_cambios_worker, lista_cambios))


def generar_y_construir(cfg: Dict[str, Any], stock_df: "pd.DataFrame",
                        modelo: Dict[str, Any], *, seed: Optional[int] = None,
                        horizonte_dias: Optional[int] = None) -> CylinderWorkshop:
    """Generate the Programa_Cambios from ``modelo`` and build the workshop ready to simulate.

    Designed so a parallel runner can iterate over seeds reusing the same
    ``stock_df`` and already-fitted ``modelo``.
    """
    cambios_df = gencambios.generate_changes(modelo, cfg, seed=seed,
                                             horizon_days=horizonte_dias)
    return build_workshop_from_dataframes(cfg, stock_df, cambios_df)


def ejecutar_simulacion(ruta_excel: str, estrategia: str = "mayor_diametro",
                        config_path: Optional[str] = None,
                        callback_log: Optional[Callable[[str], None]] = print,
                        tiempo_enfriado: Optional[float] = None,
                        max_iteraciones: Optional[int] = None) -> CylinderWorkshop:
    """Load data + configuration, run the simulation and return the workshop.

    Mirrors the orchestration of ``App._simular()`` but without GUI.
    ``tiempo_enfriado`` and ``max_iteraciones``, if given, take precedence over the
    JSON value.
    """
    cfg = _cargar_config(config_path)
    if tiempo_enfriado is not None:
        cfg["tiempo_enfriado_h"] = tiempo_enfriado
    if max_iteraciones is not None:
        cfg["max_iteraciones"] = max_iteraciones

    workshop = build_workshop(cfg, ruta_excel)

    if callback_log:
        for aviso in workshop.load_warnings:
            callback_log(aviso)

    workshop.simulate(strategy=estrategia, callback_log=callback_log)
    return workshop


def _cargar_config(config_path: Optional[str]) -> Dict[str, Any]:
    """Load the config from the given JSON, or the default user config."""
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            return cfgmod.migrar(json.load(f))
    return cargar_config()


def _escribir_json(obj: Any, ruta: str) -> None:
    """Dump ``obj`` to ``ruta`` as indented UTF-8 JSON."""
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ── Output formatting ────────────────────────────────────────────────────────

def _formatear_resumen(kpis: Dict[str, Any]) -> str:
    """Readable KPI block to print to the console."""
    lineas = [
        "",
        "═" * 48,
        "  RESUMEN DE LA SIMULACIÓN",
        "═" * 48,
        f"  Cilindros totales      : {kpis['cilindros_totales']}",
        f"  Activos                : {kpis['activos']}",
        f"  Bajas                  : {kpis['bajas']}",
        f"  Alertas críticas       : {kpis['alertas_criticas']}",
        f"  Cambios programados    : {kpis['cambios_programados']}",
        f"  Rectificados realizados: {kpis['rectificados_realizados']}",
        f"  Horizonte simulación   : {kpis['horizonte_simulacion_h']:.1f} h",
        f"  Diámetro promedio      : {kpis['diametro_promedio_mm']:.1f} mm",
        f"  Desgaste medio         : {kpis['desgaste_medio_mm']:.2f} mm",
        "  Utilización de máquinas (disponible / neta):",
    ]
    for nombre, pct in kpis["utilizacion_maquinas_pct"].items():
        neta = kpis["utilizacion_neta_pct"].get(nombre, 0.0)
        lineas.append(f"    - {nombre:<18}: {pct:.0f}% / {neta:.0f}%")
    lineas.append("═" * 48)
    return "\n".join(lineas)


# ── Command: simular ───────────────────────────────────────────────────────────

def _cmd_simular(args) -> int:
    if not os.path.isfile(args.excel):
        print(f"Error: no se encontró el archivo de datos: {args.excel}", file=sys.stderr)
        return 2

    callback = None if args.quiet else print
    try:
        workshop = ejecutar_simulacion(args.excel, estrategia=args.estrategia,
                                       config_path=args.config, callback_log=callback,
                                       tiempo_enfriado=args.tiempo_enfriado,
                                       max_iteraciones=args.max_iteraciones)
    except Exception as e:
        print(f"Error al ejecutar la simulación: {e}", file=sys.stderr)
        return 1

    kpis = compute_kpis(workshop)
    print(_formatear_resumen(kpis))

    if args.json:
        print(json.dumps(kpis, ensure_ascii=False, indent=2))
    if args.json_out:
        _escribir_json(kpis, args.json_out)
        print(f"KPIs escritos en: {args.json_out}")
    if args.export:
        workshop.export_results(args.export)
        print(f"Resultados exportados en: {args.export}")
    return 0


# ── Command: config ────────────────────────────────────────────────────────────

def _print_config(cfg: Dict[str, Any]) -> None:
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


def _cmd_config(args) -> int:
    sub = args.subcomando

    if sub == "show":
        _print_config(_cargar_config(args.config))
        return 0

    if sub == "export":
        _escribir_json(cargar_config(), args.ruta)
        print(f"Configuración exportada en: {args.ruta}")
        return 0

    if sub == "import":
        with open(args.ruta, "r", encoding="utf-8") as f:
            cfg = cfgmod.migrar(json.load(f))
        guardar_config(cfg)
        print(f"Configuración importada desde: {args.ruta}")
        return 0

    if sub == "import-excel":
        if not os.path.isfile(args.excel):
            print(f"Error: no se encontró el Excel: {args.excel}", file=sys.stderr)
            return 2
        cfg = cfgmod.cfg_desde_excel(args.excel)
        guardar_config(cfg)
        print(f"Configuración volcada desde las hojas del Excel: {args.excel}")
        _print_config(cfg)
        return 0

    # Commands that mutate the user configuration
    cfg = cargar_config()
    try:
        if sub == "global":
            cfgmod.set_config_global(
                cfg, diametro_maximo=args.diametro_max, diametro_minimo=args.diametro_min,
                tiempo_traslado_crc_min=args.crc_min, cantidad_jaulas=args.jaulas)
            guardar_config(cfg)
            print("Parámetros globales actualizados.")
            print(json.dumps(cfg["config_global"], ensure_ascii=False, indent=2))
            _avisar_incoherencias(cfg)
            return 0

        if sub == "sim":
            cfgmod.set_sim(cfg, tiempo_enfriado=args.tiempo_enfriado,
                           max_iteraciones=args.max_iteraciones,
                           estrategia_asignacion=args.estrategia_asignacion)
            guardar_config(cfg)
            print(f"Parámetros de simulación: tiempo_enfriado_h="
                  f"{obtener_tiempo_enfriado(cfg)}, max_iteraciones={obtener_max_iteraciones(cfg)}, "
                  f"estrategia_asignacion={obtener_estrategia_asignacion(cfg)}")
            return 0

        if sub == "maquina":
            return _cmd_config_maquina(args, cfg)

        if sub == "jaula":
            return _cmd_config_jaula(args, cfg)

        if sub == "generador":
            return _cmd_config_generador(args, cfg)

        if sub == "turnos-cambios":
            return _cmd_config_turnos_cambios(args, cfg)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("Subcomando de config no reconocido.", file=sys.stderr)
    return 2


def _cmd_config_maquina(args, cfg) -> int:
    accion = args.accion
    if accion == "list":
        for m in obtener_maquinas(cfg):
            t = m.get("tasas", {})
            prod, desb = t.get("produccion", {}), t.get("desbaste", {})
            print(f"  {m['nombre']:<10} prioridad={m.get('prioridad','-'):<11} "
                  f"prod={prod.get('mm','?')}mm/{prod.get('tiempo_min','?')}min  "
                  f"desb={desb.get('mm','?')}mm/{desb.get('tiempo_min','?')}min  "
                  f"turnos={shifts_mod.summary(m.get('turnos'))}")
        return 0
    if accion == "add":
        cfgmod.add_maquina(cfg, args.nombre, prod_mm=args.prod_mm, prod_min=args.prod_min,
                           desb_mm=args.desb_mm, desb_min=args.desb_min,
                           prioridad=args.prioridad or "produccion",
                           turnos=_resolve_shifts(args))
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' agregada.")
        return 0
    if accion == "set":
        cfgmod.set_maquina(cfg, args.nombre, prod_mm=args.prod_mm, prod_min=args.prod_min,
                           desb_mm=args.desb_mm, desb_min=args.desb_min, prioridad=args.prioridad,
                           turnos=_resolve_shifts(args))
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' actualizada.")
        return 0
    if accion == "remove":
        cfgmod.remove_maquina(cfg, args.nombre)
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' eliminada.")
        return 0
    return 2


def _avisar_incoherencias(cfg) -> None:
    """Print (non-fatal) warnings if stands and ranges got misaligned.

    CLI editing is incremental (e.g. bump the stands and then add the new range in
    another command), so an incoherent intermediate state must not abort the save;
    it is only warned. ``build_workshop`` does treat it as a hard error before
    simulating."""
    for p in cfgmod.problemas_coherencia(cfg):
        print(f"Aviso: {p}", file=sys.stderr)


def _cmd_config_jaula(args, cfg) -> int:
    accion = args.accion
    if accion == "list":
        for r in obtener_rangos(cfg):
            perfil = r.get("perfil")
            extra = f" | perfil {perfil}" if perfil not in (None, "") else ""
            print(f"  Jaula {r['jaula']}: {r['hasta']} < d ≤ {r['desde']} mm{extra}")
        return 0
    if accion == "set":
        cfgmod.set_rango(cfg, args.jaula, args.desde, args.hasta, perfil=args.perfil)
        guardar_config(cfg)
        print(f"Rango de la jaula {args.jaula} actualizado.")
        _avisar_incoherencias(cfg)
        return 0
    if accion == "remove":
        cfgmod.remove_rango(cfg, args.jaula)
        guardar_config(cfg)
        print(f"Rango de la jaula {args.jaula} eliminado.")
        _avisar_incoherencias(cfg)
        return 0
    return 2


# ── Commands: modelo / generar-cambios ────────────────────────────────────────

def _leer_historia(ruta: str) -> "pd.DataFrame":
    """Read the history from CSV or Excel (first sheet, or 'Historia' if present)."""
    if ruta.lower().endswith(".csv"):
        return pd.read_csv(ruta)
    xl = pd.ExcelFile(ruta, engine="openpyxl")
    hoja = "Historia" if "Historia" in xl.sheet_names else xl.sheet_names[0]
    return xl.parse(hoja)


def _resumen_modelo(modelo: Dict[str, Any]) -> str:
    jaulas = sorted(modelo.get("jaulas", {}).keys(), key=int)
    return (f"  generador : {modelo.get('clave')}\n"
            f"  filas     : {modelo.get('n_filas', 0)}\n"
            f"  jaulas    : {', '.join(jaulas) or '(ninguna)'}\n"
            f"  fechas    : {modelo.get('fecha_min')} → {modelo.get('fecha_max')}")


def _cmd_modelo(args) -> int:
    accion = args.accion

    if accion == "show":
        modelo = modmod.cargar_modelo()
        if not modelo:
            print("No hay modelo persistido. Ajuste uno con 'modelo ajustar <historia>'.")
            return 0
        print(_resumen_modelo(modelo))
        return 0

    if accion == "reset":
        modmod.reiniciar_modelo()
        print("Modelo de generador reiniciado (adaptación limpia).")
        return 0

    if accion == "ajustar":
        if not os.path.isfile(args.historia):
            print(f"Error: no se encontró la historia: {args.historia}", file=sys.stderr)
            return 2
        cfg = cargar_config()
        if args.umbral_desbaste is not None:
            cfgmod.set_generador_cambios(cfg, umbral_desbaste=args.umbral_desbaste)
        previo = None if args.reiniciar else modmod.cargar_modelo()
        try:
            historia = _leer_historia(args.historia)
            modelo = gencambios.fit_model(historia, cfg, key=args.generador,
                                          prior_model=previo)
        except Exception as e:
            print(f"Error al ajustar el modelo: {e}", file=sys.stderr)
            return 1
        modmod.guardar_modelo(modelo)
        modo = "desde cero" if (args.reiniciar or previo is None) else "incremental"
        print(f"Modelo ajustado ({modo}):")
        print(_resumen_modelo(modelo))
        return 0

    return 2


def _cmd_generar_cambios(args) -> int:
    cfg = cargar_config()
    if args.umbral_desbaste is not None:
        cfgmod.set_generador_cambios(cfg, umbral_desbaste=args.umbral_desbaste)

    # Fit on the fly if requested or if a history was given; otherwise use the persisted one.
    if args.historia or args.ajustar:
        if not args.historia or not os.path.isfile(args.historia):
            print("Error: --ajustar requiere una historia válida.", file=sys.stderr)
            return 2
        previo = modmod.cargar_modelo()
        try:
            historia = _leer_historia(args.historia)
            modelo = gencambios.fit_model(historia, cfg, key=args.generador,
                                          prior_model=previo)
        except Exception as e:
            print(f"Error al ajustar el modelo: {e}", file=sys.stderr)
            return 1
        modmod.guardar_modelo(modelo)
    else:
        modelo = modmod.cargar_modelo()
        if not modelo:
            print("Error: no hay modelo persistido. Use 'modelo ajustar' o pase una historia.",
                  file=sys.stderr)
            return 2

    inicio = fin = None
    try:
        if args.inicio:
            inicio = pd.to_datetime(args.inicio).to_pydatetime()
        if args.fin:
            fin = pd.to_datetime(args.fin).to_pydatetime()
    except Exception:
        print(f"Error: fecha inválida (--inicio/--fin).", file=sys.stderr)
        return 2

    seed = gencambios.resolve_seed(args.seed)
    gen = gencambios.get_generator(args.generador or modelo.get("clave"))
    cambios_df = gen.generate(modelo, cfg, seed=seed, start=inicio, end=fin,
                              horizon_days=args.horizonte_dias,
                              change_grid=gencambios.change_grid_from_cfg(cfg))

    print(f"Generados {len(cambios_df)} cambios (generador={gen.key}, seed={seed}).")
    if args.salida:
        with pd.ExcelWriter(args.salida, engine="openpyxl") as xl:
            cambios_df.to_excel(xl, sheet_name="Programa_Cambios", index=False)
        print(f"Programa_Cambios escrito en: {args.salida}")
    else:
        print(cambios_df.to_string(index=False))
    return 0


def _cmd_config_generador(args, cfg) -> int:
    cfgmod.set_generador_cambios(cfg, generador=args.generador,
                                 umbral_desbaste=args.umbral_desbaste,
                                 horizonte_dias=args.horizonte_dias,
                                 fecha_inicio=args.fecha_inicio,
                                 fecha_fin=args.fecha_fin)
    guardar_config(cfg)
    gc = cfgmod.obtener_generador_cambios(cfg)
    print(f"Generador de cambios: generador={gc['generador']}, "
          f"umbral_desbaste_mm={gc['umbral_desbaste_mm']}, "
          f"fecha_inicio={gc.get('fecha_inicio')}, fecha_fin={gc.get('fecha_fin')}")
    return 0


def _cmd_config_turnos_cambios(args, cfg) -> int:
    turnos = _resolve_shifts(args)
    cfgmod.set_turnos_cambios(cfg, turnos)
    guardar_config(cfg)
    print(f"Régimen de turnos de cambios: {shifts_mod.summary(cfgmod.obtener_turnos_cambios(cfg))}")
    return 0


# ── Argument parser ────────────────────────────────────────────────────────────

def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Simulación y gestión de configuración del taller de cilindros (headless).",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    # simular
    p_sim = sub.add_parser("simular", help="Ejecuta una simulación.")
    p_sim.add_argument("excel", help="Ruta al .xlsx con Stock_Inicial y Programa_Cambios.")
    p_sim.add_argument("--estrategia", default="mayor_diametro",
                       choices=list(SELECTION_STRATEGIES.keys()),
                       help="Estrategia de selección de la cola (default: mayor_diametro).")
    p_sim.add_argument("--config", metavar="RUTA", help="JSON de configuración (default: user_config.json).")
    p_sim.add_argument("--export", metavar="RUTA.xlsx", help="Exporta el Excel de resultados.")
    p_sim.add_argument("--json", action="store_true", help="Imprime los KPIs como JSON.")
    p_sim.add_argument("--json-out", metavar="RUTA.json", help="Escribe los KPIs como JSON.")
    p_sim.add_argument("--quiet", action="store_true", help="Suprime los logs por-evento.")
    p_sim.add_argument("--tiempo-enfriado", type=float, metavar="HORAS",
                       help="Horas de enfriado (pisa la config).")
    p_sim.add_argument("--max-iteraciones", type=int, metavar="N",
                       help="Tope de iteraciones del bucle (pisa la config).")
    p_sim.set_defaults(func=_cmd_simular)

    # config
    p_cfg = sub.add_parser("config", help="Gestiona la configuración persistente.")
    csub = p_cfg.add_subparsers(dest="subcomando", required=True)
    p_cfg.set_defaults(func=_cmd_config)

    p_show = csub.add_parser("show", help="Muestra la configuración actual.")
    p_show.add_argument("--config", metavar="RUTA", help="JSON alternativo a mostrar.")

    p_exp = csub.add_parser("export", help="Exporta la configuración a un JSON.")
    p_exp.add_argument("ruta")

    p_imp = csub.add_parser("import", help="Importa (reemplaza) la configuración desde un JSON.")
    p_imp.add_argument("ruta")

    p_impx = csub.add_parser("import-excel", help="Vuelca Configuración/Máquinas de un Excel viejo al JSON.")
    p_impx.add_argument("excel")

    p_glob = csub.add_parser("global", help="Edita los parámetros globales.")
    p_glob.add_argument("--diametro-max", type=float)
    p_glob.add_argument("--diametro-min", type=float)
    p_glob.add_argument("--crc-min", type=float)
    p_glob.add_argument("--jaulas", type=int)

    p_simcfg = csub.add_parser("sim", help="Edita los parámetros de simulación.")
    p_simcfg.add_argument("--tiempo-enfriado", type=float)
    p_simcfg.add_argument("--max-iteraciones", type=int)
    p_simcfg.add_argument("--estrategia-asignacion", choices=list(ASSIGNMENT_STRATEGIES.keys()),
                          help="Estrategia de asignación de jaula destino al rectificar.")

    p_maq = csub.add_parser("maquina", help="Gestiona máquinas (list/add/remove/set).")
    p_maq.add_argument("accion", choices=["list", "add", "remove", "set"])
    p_maq.add_argument("--nombre")
    p_maq.add_argument("--prod-mm", type=float)
    p_maq.add_argument("--prod-min", type=float)
    p_maq.add_argument("--desb-mm", type=float)
    p_maq.add_argument("--desb-min", type=float)
    p_maq.add_argument("--prioridad", choices=_TIPOS_RECT)
    p_maq.add_argument("--turnos", metavar="COMPACTO",
                       help="Esquema de trabajo: 7 grupos lun..dom de 3 bits T1T2T3, "
                            "p. ej. '111 111 111 111 111 110 000'.")
    p_maq.add_argument("--turnos-preset", choices=list(shifts_mod.PRESETS))

    p_jau = csub.add_parser("jaula", help="Gestiona rangos por jaula (list/set/remove).")
    p_jau.add_argument("accion", choices=["list", "set", "remove"])
    p_jau.add_argument("--jaula", type=int)
    p_jau.add_argument("--desde", type=float)
    p_jau.add_argument("--hasta", type=float)
    p_jau.add_argument("--perfil", help="Perfil (bombatura) de la jaula; \"\" lo quita.")

    p_gen = csub.add_parser("generador", help="Edita la config del generador de cambios.")
    p_gen.add_argument("--generador", choices=list(gencambios.CHANGE_GENERATORS))
    p_gen.add_argument("--umbral-desbaste", type=float,
                       help="mm a partir del cual el cambio se clasifica 'desbaste'.")
    p_gen.add_argument("--horizonte-dias", type=int, help="(legacy) ventana en días.")
    p_gen.add_argument("--fecha-inicio", help="Fecha de inicio de la generación (ISO YYYY-MM-DD).")
    p_gen.add_argument("--fecha-fin", help="Fecha de fin de la generación (ISO YYYY-MM-DD).")

    p_tc = csub.add_parser("turnos-cambios", help="Régimen de turnos del laminador (cambios).")
    p_tc.add_argument("--turnos", metavar="COMPACTO",
                      help="7 grupos lun..dom de 3 bits T1T2T3, p. ej. '111 111 111 111 111 110 000'.")
    p_tc.add_argument("--turnos-preset", choices=list(shifts_mod.PRESETS))

    # modelo (persisted generator adaptation)
    p_mod = sub.add_parser("modelo", help="Ajusta/inspecciona el modelo aprendido del generador.")
    p_mod.add_argument("accion", choices=["ajustar", "show", "reset"])
    p_mod.add_argument("historia", nargs="?", help="Historia (.xlsx/.csv) para 'ajustar'.")
    p_mod.add_argument("--generador", choices=list(gencambios.CHANGE_GENERATORS))
    p_mod.add_argument("--umbral-desbaste", type=float)
    p_mod.add_argument("--reiniciar", action="store_true",
                       help="Ajusta desde cero en vez de refit incremental.")
    p_mod.set_defaults(func=_cmd_modelo)

    # generar-cambios
    p_gc = sub.add_parser("generar-cambios", help="Genera un Programa_Cambios reproducible por seed.")
    p_gc.add_argument("historia", nargs="?",
                      help="Historia opcional: si se pasa (o --ajustar), re-ajusta antes de generar.")
    p_gc.add_argument("--generador", choices=list(gencambios.CHANGE_GENERATORS))
    p_gc.add_argument("--seed", type=int, help="Seed (por defecto aleatoria reproducible).")
    p_gc.add_argument("--horizonte-dias", type=int, help="(legacy) ventana en días desde --inicio.")
    p_gc.add_argument("--umbral-desbaste", type=float)
    p_gc.add_argument("--inicio", help="Fecha/hora de inicio de la ventana (ISO).")
    p_gc.add_argument("--fin", help="Fecha/hora de fin de la ventana (ISO).")
    p_gc.add_argument("--ajustar", action="store_true",
                      help="Re-ajusta el modelo con la historia antes de generar.")
    p_gc.add_argument("--salida", metavar="RUTA.xlsx", help="Excel de salida (si se omite, imprime).")
    p_gc.set_defaults(func=_cmd_generar_cambios)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = _construir_parser()
    args = parser.parse_args(argv)

    # Minimal validations for actions that require --nombre / --jaula
    if args.comando == "config" and args.subcomando == "maquina":
        if args.accion in ("add", "set", "remove") and not args.nombre:
            parser.error(f"'config maquina {args.accion}' requiere --nombre")
        if args.accion == "add" and any(v is None for v in (args.prod_mm, args.prod_min, args.desb_mm, args.desb_min)):
            parser.error("'config maquina add' requiere --prod-mm --prod-min --desb-mm --desb-min")
        if args.turnos and args.turnos_preset:
            parser.error("Use --turnos o --turnos-preset, no ambos")
    if args.comando == "config" and args.subcomando == "jaula":
        if args.accion in ("set", "remove") and args.jaula is None:
            parser.error(f"'config jaula {args.accion}' requiere --jaula")
        if args.accion == "set" and (args.desde is None or args.hasta is None):
            parser.error("'config jaula set' requiere --desde y --hasta")
    if args.comando == "config" and args.subcomando == "turnos-cambios":
        if args.turnos and args.turnos_preset:
            parser.error("Use --turnos o --turnos-preset, no ambos")
    if args.comando == "modelo" and args.accion == "ajustar" and not args.historia:
        parser.error("'modelo ajustar' requiere la ruta de la historia")

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
