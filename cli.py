#!/usr/bin/env python3
"""Modo headless: ejecuta la simulación desde la línea de comandos, sin GUI.

No importa Tkinter ni nada de ``gui/``, por lo que corre en entornos sin
display (servidores, CI, lotes de estadística). La función ``ejecutar_simulacion``
es reutilizable de forma programática (p. ej. por un futuro generador de cambios
o un módulo de estadística) sin disparar el parser de argumentos.
"""
import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.persistencia import cargar_config, obtener_prioridades, obtener_rangos
from modelos.kpis import calcular_kpis
from modelos.taller import ESTRATEGIAS_SELECCION, TallerCilindros


def ejecutar_simulacion(ruta_excel: str, estrategia: str = "mayor_diametro",
                        config_path: Optional[str] = None,
                        callback_log: Optional[Callable[[str], None]] = print) -> TallerCilindros:
    """Carga datos + configuración, ejecuta la simulación y devuelve el taller.

    Replica la orquestación de ``App._simular()`` pero sin GUI.
    """
    cfg = _cargar_config(config_path)

    taller = TallerCilindros()
    taller.cargar_datos(ruta_excel)
    taller.configurar_substocks(obtener_rangos(cfg))
    prioridades = obtener_prioridades(cfg)
    if prioridades:
        taller.aplicar_prioridades_maquinas(prioridades)

    if callback_log:
        for aviso in taller.avisos_carga:
            callback_log(aviso)

    taller.simular(estrategia=estrategia, callback_log=callback_log)
    return taller


def _cargar_config(config_path: Optional[str]) -> Dict[str, Any]:
    """Carga la configuración del JSON indicado, o la de usuario por defecto."""
    if config_path:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return cargar_config()


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


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Ejecuta la simulación del taller de cilindros en modo headless.",
    )
    parser.add_argument("excel", help="Ruta al archivo .xlsx con los datos de la simulación.")
    parser.add_argument("--estrategia", default="mayor_diametro",
                        choices=list(ESTRATEGIAS_SELECCION.keys()),
                        help="Estrategia de selección de la cola de rectificado (default: mayor_diametro).")
    parser.add_argument("--config", metavar="RUTA",
                        help="JSON de configuración (default: config/user_config.json).")
    parser.add_argument("--export", metavar="RUTA.xlsx",
                        help="Exporta el Excel de resultados (Stock_Final + Alertas).")
    parser.add_argument("--json", action="store_true",
                        help="Imprime los KPIs como JSON en stdout.")
    parser.add_argument("--json-out", metavar="RUTA.json",
                        help="Escribe los KPIs como JSON en el archivo indicado.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suprime los logs por-evento; deja solo el resumen.")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.excel):
        print(f"Error: no se encontró el archivo de datos: {args.excel}", file=sys.stderr)
        return 2

    callback = None if args.quiet else print
    try:
        taller = ejecutar_simulacion(args.excel, estrategia=args.estrategia,
                                     config_path=args.config, callback_log=callback)
    except Exception as e:
        print(f"Error al ejecutar la simulación: {e}", file=sys.stderr)
        return 1

    kpis = calcular_kpis(taller)
    print(_formatear_resumen(kpis))

    if args.json:
        print(json.dumps(kpis, ensure_ascii=False, indent=2))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(kpis, f, ensure_ascii=False, indent=2)
        print(f"KPIs escritos en: {args.json_out}")

    if args.export:
        taller.exportar_resultados(args.export)
        print(f"Resultados exportados en: {args.export}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
