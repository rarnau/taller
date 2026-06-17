#!/usr/bin/env python3
"""Modo headless: simulación y gestión de configuración desde la línea de comandos.

No importa Tkinter ni nada de ``gui/``, por lo que corre en entornos sin
display (servidores, CI, lotes de estadística). La función ``ejecutar_simulacion``
y el helper ``construir_taller`` son reutilizables de forma programática (p. ej.
por un futuro generador de cambios o un runner de miles de simulaciones en
paralelo) sin disparar el parser de argumentos.

Subcomandos::

    cli.py simular <excel> [opciones]
    cli.py config show | export <json> | import <json> | import-excel <excel>
    cli.py config global [--diametro-max --diametro-min --crc-min --jaulas]
    cli.py config maquina list|add|remove|set [flags]
    cli.py config jaula   list|set|remove     [flags]
    cli.py config sim [--tiempo-enfriado --max-iteraciones]
"""
import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import persistencia as cfgmod
from config.persistencia import (cargar_config, guardar_config, obtener_maquinas,
                                  obtener_max_iteraciones, obtener_rangos,
                                  obtener_tiempo_enfriado)
from modelos.enums import TipoRectificado
from modelos.kpis import calcular_kpis
from modelos.estrategias import ESTRATEGIAS_SELECCION
from modelos.taller import TallerCilindros
from modelos import turnos as turnos_mod

_TIPOS_RECT = [t.value for t in TipoRectificado]


def _resolver_turnos(args) -> Optional[Dict[str, Any]]:
    """Obtiene el esquema de turnos desde --turnos-preset o --turnos (o None)."""
    if getattr(args, "turnos_preset", None):
        return {k: list(v) for k, v in turnos_mod.PRESETS[args.turnos_preset].items()}
    if getattr(args, "turnos", None):
        return turnos_mod.parse_compacto(args.turnos)
    return None


# ── Núcleo reutilizable (sin argparse) ───────────────────────────────────────

def construir_taller(cfg: Dict[str, Any], ruta_excel: str) -> TallerCilindros:
    """Construye un taller configurado y con los datos del Excel cargados.

    Aplica primero la configuración estructural (``configurar``) y luego los
    datos (``cargar_datos``), en ese orden obligatorio. Pensado como base de un
    futuro runner de lotes: cada simulación crea su propia instancia
    independiente a partir de un mismo ``cfg``.
    """
    taller = TallerCilindros()
    taller.configurar(cfg)
    taller.cargar_datos(ruta_excel)
    return taller


def ejecutar_simulacion(ruta_excel: str, estrategia: str = "mayor_diametro",
                        config_path: Optional[str] = None,
                        callback_log: Optional[Callable[[str], None]] = print,
                        tiempo_enfriado: Optional[float] = None,
                        max_iteraciones: Optional[int] = None) -> TallerCilindros:
    """Carga datos + configuración, ejecuta la simulación y devuelve el taller.

    Replica la orquestación de ``App._simular()`` pero sin GUI. ``tiempo_enfriado``
    y ``max_iteraciones``, si se indican, tienen prioridad sobre el valor del JSON.
    """
    cfg = _cargar_config(config_path)
    if tiempo_enfriado is not None:
        cfg["tiempo_enfriado_h"] = tiempo_enfriado
    if max_iteraciones is not None:
        cfg["max_iteraciones"] = max_iteraciones

    taller = construir_taller(cfg, ruta_excel)

    if callback_log:
        for aviso in taller.avisos_carga:
            callback_log(aviso)

    taller.simular(estrategia=estrategia, callback_log=callback_log)
    return taller


def _cargar_config(config_path: Optional[str]) -> Dict[str, Any]:
    """Carga la configuración del JSON indicado, o la de usuario por defecto."""
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            return cfgmod.migrar(json.load(f))
    return cargar_config()


def _escribir_json(obj: Any, ruta: str) -> None:
    """Vuelca ``obj`` a ``ruta`` como JSON UTF-8 indentado."""
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ── Formato de salida ────────────────────────────────────────────────────────

def _formatear_resumen(kpis: Dict[str, Any]) -> str:
    """Bloque legible de KPIs para imprimir en consola."""
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
        "  Utilización de máquinas:",
    ]
    for nombre, pct in kpis["utilizacion_maquinas_pct"].items():
        lineas.append(f"    - {nombre:<18}: {pct:.0f}%")
    lineas.append("═" * 48)
    return "\n".join(lineas)


# ── Comando: simular ──────────────────────────────────────────────────────────

def _cmd_simular(args) -> int:
    if not os.path.isfile(args.excel):
        print(f"Error: no se encontró el archivo de datos: {args.excel}", file=sys.stderr)
        return 2

    callback = None if args.quiet else print
    try:
        taller = ejecutar_simulacion(args.excel, estrategia=args.estrategia,
                                     config_path=args.config, callback_log=callback,
                                     tiempo_enfriado=args.tiempo_enfriado,
                                     max_iteraciones=args.max_iteraciones)
    except Exception as e:
        print(f"Error al ejecutar la simulación: {e}", file=sys.stderr)
        return 1

    kpis = calcular_kpis(taller)
    print(_formatear_resumen(kpis))

    if args.json:
        print(json.dumps(kpis, ensure_ascii=False, indent=2))
    if args.json_out:
        _escribir_json(kpis, args.json_out)
        print(f"KPIs escritos en: {args.json_out}")
    if args.export:
        taller.exportar_resultados(args.export)
        print(f"Resultados exportados en: {args.export}")
    return 0


# ── Comando: config ───────────────────────────────────────────────────────────

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

    # Comandos que mutan la configuración de usuario
    cfg = cargar_config()
    try:
        if sub == "global":
            cfgmod.set_config_global(
                cfg, diametro_maximo=args.diametro_max, diametro_minimo=args.diametro_min,
                tiempo_traslado_crc_min=args.crc_min, cantidad_jaulas=args.jaulas)
            guardar_config(cfg)
            print("Parámetros globales actualizados.")
            print(json.dumps(cfg["config_global"], ensure_ascii=False, indent=2))
            return 0

        if sub == "sim":
            cfgmod.set_sim(cfg, tiempo_enfriado=args.tiempo_enfriado,
                           max_iteraciones=args.max_iteraciones)
            guardar_config(cfg)
            print(f"Parámetros de simulación: tiempo_enfriado_h="
                  f"{obtener_tiempo_enfriado(cfg)}, max_iteraciones={obtener_max_iteraciones(cfg)}")
            return 0

        if sub == "maquina":
            return _cmd_config_maquina(args, cfg)

        if sub == "jaula":
            return _cmd_config_jaula(args, cfg)

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
                  f"turnos={turnos_mod.resumen(m.get('turnos'))}")
        return 0
    if accion == "add":
        cfgmod.add_maquina(cfg, args.nombre, prod_mm=args.prod_mm, prod_min=args.prod_min,
                           desb_mm=args.desb_mm, desb_min=args.desb_min,
                           prioridad=args.prioridad or "produccion",
                           turnos=_resolver_turnos(args))
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' agregada.")
        return 0
    if accion == "set":
        cfgmod.set_maquina(cfg, args.nombre, prod_mm=args.prod_mm, prod_min=args.prod_min,
                           desb_mm=args.desb_mm, desb_min=args.desb_min, prioridad=args.prioridad,
                           turnos=_resolver_turnos(args))
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' actualizada.")
        return 0
    if accion == "remove":
        cfgmod.remove_maquina(cfg, args.nombre)
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' eliminada.")
        return 0
    return 2


def _cmd_config_jaula(args, cfg) -> int:
    accion = args.accion
    if accion == "list":
        for r in obtener_rangos(cfg):
            print(f"  Jaula {r['jaula']}: {r['hasta']} < d ≤ {r['desde']} mm")
        return 0
    if accion == "set":
        cfgmod.set_rango(cfg, args.jaula, args.desde, args.hasta)
        guardar_config(cfg)
        print(f"Rango de la jaula {args.jaula} actualizado.")
        return 0
    if accion == "remove":
        cfgmod.remove_rango(cfg, args.jaula)
        guardar_config(cfg)
        print(f"Rango de la jaula {args.jaula} eliminado.")
        return 0
    return 2


# ── Parser de argumentos ──────────────────────────────────────────────────────

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
                       choices=list(ESTRATEGIAS_SELECCION.keys()),
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
    p_maq.add_argument("--turnos-preset", choices=list(turnos_mod.PRESETS))

    p_jau = csub.add_parser("jaula", help="Gestiona rangos por jaula (list/set/remove).")
    p_jau.add_argument("accion", choices=["list", "set", "remove"])
    p_jau.add_argument("--jaula", type=int)
    p_jau.add_argument("--desde", type=float)
    p_jau.add_argument("--hasta", type=float)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = _construir_parser()
    args = parser.parse_args(argv)

    # Validaciones mínimas para acciones que requieren --nombre / --jaula
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

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
