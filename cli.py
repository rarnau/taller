#!/usr/bin/env python3
"""Modo headless: simulación y gestión de configuración desde la línea de comandos.

No importa PySide6/Qt ni nada de ``gui_qt/``, por lo que corre en entornos sin
display (servidores, CI, lotes de estadística). La función ``ejecutar_simulacion``
y el helper ``construir_taller`` son reutilizables de forma programática (p. ej.
por un futuro generador de cambios o un runner de miles de simulaciones en
paralelo) sin disparar el parser de argumentos.

Subcomandos::

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
from config import generator_model as modmod
from config.persistencia import (cargar_config, guardar_config, obtener_maquinas,
                                  obtener_max_iteraciones, obtener_rangos,
                                  obtener_tiempo_enfriado)
from modelos.enums import TipoRectificado
from modelos.kpis import calcular_kpis
from modelos.estrategias import ESTRATEGIAS_SELECCION, FAMILIAS_ESTRATEGIA
from modelos import generador_cambios as gencambios
from modelos.taller import TallerCilindros
from modelos import turnos as turnos_mod

_TIPOS_RECT = [t.value for t in TipoRectificado]


def _resolver_turnos(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
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
# La simulación es CPU-bound en Python puro, así que se corre en procesos aparte
# (no hilos: el GIL los serializa). Para barridos de muchas corridas que comparten
# el MISMO stock + config + estrategia y solo varían el ``Programa_Cambios`` (p. ej.
# distintas seeds del generador), el stock/config/estrategia se cargan **una sola
# vez por worker** vía un *initializer* del pool y cada tarea envía únicamente su
# ``cambios_df`` — lo más liviano de serializar. Lo usan tanto la GUI (una corrida)
# como ``batch_simular`` (N corridas en paralelo).

# Estado por-worker: lo siembra el initializer en cada proceso del pool (no es
# estado global compartido entre procesos — cada worker tiene su propia copia).
_WORKER_STATE: Dict[str, Any] = {}


def ctx_paralelo() -> "multiprocessing.context.BaseContext":
    """Contexto de multiprocessing preferido: ``fork`` si está disponible.

    Con ``fork`` el worker hereda los módulos ya importados (sin re-importar ni
    re-ejecutar nada — clave cuando el padre es la GUI). Si la plataforma no
    soporta fork (p. ej. Windows) se cae a ``spawn``; como el initializer y la
    tarea viven en este módulo (sin GUI), spawn solo re-importa ``cli``.
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


def ejecutar_simulacion(ruta_excel: str, estrategia: str = "mayor_diametro",
                        config_path: Optional[str] = None,
                        callback_log: Optional[Callable[[str], None]] = print,
                        tiempo_enfriado: Optional[float] = None,
                        max_iteraciones: Optional[int] = None,
                        seed: Optional[int] = None) -> TallerCilindros:
    """Carga datos + configuración, ejecuta la simulación y devuelve el taller.

    Replica la orquestación de ``App._simular()`` pero sin GUI. ``tiempo_enfriado``
    y ``max_iteraciones``, si se indican, tienen prioridad sobre el valor del JSON.
    ``seed`` determina la realización de las fallas de máquina (ver
    ``TallerCilindros.simular``); ``None`` ⇒ sin fallas reproducibles.
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

    taller.simular(estrategia=estrategia, callback_log=callback_log, seed=seed)
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
    ]
    if kpis.get("reposicion_entregados") or kpis.get("reposicion_pendientes"):
        lineas.append(f"  Repuestos (entregados) : {kpis['reposicion_entregados']}")
        lineas.append(f"  Reposición pendiente   : {kpis['reposicion_pendientes']}")
    lineas.append("  Utilización de máquinas (disponible / neta):")
    for nombre, pct in kpis["utilizacion_maquinas_pct"].items():
        neta = kpis["utilizacion_neta_pct"].get(nombre, 0.0)
        lineas.append(f"    - {nombre:<18}: {pct:.0f}% / {neta:.0f}%")
    lineas.append("═" * 48)
    return "\n".join(lineas)


# ── Comando: simular ──────────────────────────────────────────────────────────

def _cmd_simular(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.excel):
        print(f"Error: no se encontró el archivo de datos: {args.excel}", file=sys.stderr)
        return 2

    callback = None if args.quiet else print
    try:
        taller = ejecutar_simulacion(args.excel, estrategia=args.estrategia,
                                     config_path=args.config, callback_log=callback,
                                     tiempo_enfriado=args.tiempo_enfriado,
                                     max_iteraciones=args.max_iteraciones,
                                     seed=args.seed_fallas)
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


def _cmd_config(args: argparse.Namespace) -> int:
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
            _avisar_incoherencias(cfg)
            return 0

        if sub == "sim":
            estr_kwargs = {fam.clave_cfg: getattr(args, fam.dest_cli)
                           for fam in FAMILIAS_ESTRATEGIA}
            cfgmod.set_sim(cfg, tiempo_enfriado=args.tiempo_enfriado,
                           max_iteraciones=args.max_iteraciones, **estr_kwargs)
            guardar_config(cfg)
            estr_txt = ", ".join(f"{fam.clave_cfg}={cfg.get(fam.clave_cfg, fam.defecto)}"
                                 for fam in FAMILIAS_ESTRATEGIA)
            print(f"Parámetros de simulación: tiempo_enfriado_h="
                  f"{obtener_tiempo_enfriado(cfg)}, max_iteraciones={obtener_max_iteraciones(cfg)}, "
                  f"{estr_txt}")
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


def _cmd_config_maquina(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    accion = args.accion
    if accion == "list":
        for m in obtener_maquinas(cfg):
            t = m.get("tasas", {})
            prod, desb = t.get("produccion", {}), t.get("desbaste", {})
            falla = float(m.get("tasa_falla", 0.0) or 0.0)
            falla_txt = f"  falla={falla*100:.0f}%" if falla > 0 else ""
            print(f"  {m['nombre']:<10} prioridad={m.get('prioridad','-'):<11} "
                  f"prod={prod.get('mm','?')}mm/{prod.get('tiempo_min','?')}min  "
                  f"desb={desb.get('mm','?')}mm/{desb.get('tiempo_min','?')}min  "
                  f"turnos={turnos_mod.resumen(m.get('turnos'))}{falla_txt}")
        return 0
    if accion == "add":
        cfgmod.add_maquina(cfg, args.nombre, prod_mm=args.prod_mm, prod_min=args.prod_min,
                           desb_mm=args.desb_mm, desb_min=args.desb_min,
                           prioridad=args.prioridad or "produccion",
                           turnos=_resolver_turnos(args), tasa_falla=args.tasa_falla)
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' agregada.")
        return 0
    if accion == "set":
        cfgmod.set_maquina(cfg, args.nombre, prod_mm=args.prod_mm, prod_min=args.prod_min,
                           desb_mm=args.desb_mm, desb_min=args.desb_min, prioridad=args.prioridad,
                           turnos=_resolver_turnos(args), tasa_falla=args.tasa_falla)
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' actualizada.")
        return 0
    if accion == "remove":
        cfgmod.remove_maquina(cfg, args.nombre)
        guardar_config(cfg)
        print(f"Máquina '{args.nombre}' eliminada.")
        return 0
    return 2


def _avisar_incoherencias(cfg: Dict[str, Any]) -> None:
    """Imprime avisos (no fatales) si jaulas y rangos quedaron desalineados.

    La edición por CLI es incremental (p. ej. subir jaulas y luego agregar el
    rango nuevo en otro comando), así que un estado intermedio incoherente no
    debe abortar el guardado; solo se avisa. ``construir_taller`` sí lo trata
    como error duro antes de simular."""
    for p in cfgmod.problemas_coherencia(cfg):
        print(f"Aviso: {p}", file=sys.stderr)


def _cmd_config_jaula(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
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


# ── Comandos: modelo / generar-cambios ────────────────────────────────────────

def _leer_historia(ruta: str) -> "pd.DataFrame":
    """Lee la historia desde CSV o Excel (primera hoja, o 'Historia' si existe)."""
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


def _cmd_modelo(args: argparse.Namespace) -> int:
    accion = args.accion

    if accion == "show":
        modelo = modmod.load_active_model()
        if not modelo:
            print("No hay modelo persistido. Ajuste uno con 'modelo ajustar <historia>'.")
            return 0
        print(_resumen_modelo(modelo))
        return 0

    if accion == "reset":
        modmod.reset_models()
        print("Modelo de generador reiniciado (adaptación limpia).")
        return 0

    if accion == "ajustar":
        if not os.path.isfile(args.historia):
            print(f"Error: no se encontró la historia: {args.historia}", file=sys.stderr)
            return 2
        cfg = cargar_config()
        if args.umbral_desbaste is not None:
            cfgmod.set_generador_cambios(cfg, umbral_desbaste=args.umbral_desbaste)
        previo = None if args.reiniciar else modmod.load_active_model()
        try:
            historia = _leer_historia(args.historia)
            modelo = gencambios.ajustar_modelo(historia, cfg, clave=args.generador,
                                               modelo_previo=previo)
        except Exception as e:
            print(f"Error al ajustar el modelo: {e}", file=sys.stderr)
            return 1
        modmod.save_model(modelo)
        modo = "desde cero" if (args.reiniciar or previo is None) else "incremental"
        print(f"Modelo ajustado ({modo}):")
        print(_resumen_modelo(modelo))
        return 0

    return 2


def _cmd_generar_cambios(args: argparse.Namespace) -> int:
    cfg = cargar_config()
    if args.umbral_desbaste is not None:
        cfgmod.set_generador_cambios(cfg, umbral_desbaste=args.umbral_desbaste)

    # Ajustar al vuelo si se pidió o si se pasó historia; si no, usar el persistido.
    if args.historia or args.ajustar:
        if not args.historia or not os.path.isfile(args.historia):
            print("Error: --ajustar requiere una historia válida.", file=sys.stderr)
            return 2
        previo = modmod.load_active_model()
        try:
            historia = _leer_historia(args.historia)
            modelo = gencambios.ajustar_modelo(historia, cfg, clave=args.generador,
                                               modelo_previo=previo)
        except Exception as e:
            print(f"Error al ajustar el modelo: {e}", file=sys.stderr)
            return 1
        modmod.save_model(modelo)
    else:
        modelo = modmod.load_active_model()
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

    seed = gencambios.resolver_seed(args.seed)
    gen = gencambios.obtener_generador(args.generador or modelo.get("clave"))
    cambios_df = gen.generar(modelo, cfg, seed=seed, inicio=inicio, fin=fin,
                             horizonte_dias=args.horizonte_dias,
                             grilla_cambios=gencambios.grilla_cambios_desde_cfg(cfg))

    print(f"Generados {len(cambios_df)} cambios (generador={gen.clave}, seed={seed}).")
    if args.salida:
        with pd.ExcelWriter(args.salida, engine="openpyxl") as xl:
            cambios_df.to_excel(xl, sheet_name="Programa_Cambios", index=False)
        print(f"Programa_Cambios escrito en: {args.salida}")
    else:
        print(cambios_df.to_string(index=False))
    return 0


def _cmd_config_generador(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
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


def _cmd_config_turnos_cambios(args: argparse.Namespace, cfg: Dict[str, Any]) -> int:
    turnos = _resolver_turnos(args)
    cfgmod.set_turnos_cambios(cfg, turnos)
    guardar_config(cfg)
    print(f"Régimen de turnos de cambios: {turnos_mod.resumen(cfgmod.obtener_turnos_cambios(cfg))}")
    return 0


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
    p_sim.add_argument("--seed-fallas", type=int, metavar="SEED",
                       help="Seed que realiza las fallas de máquina (tasa_falla). "
                            "Reproducible; sin esto no hay fallas. Base de Monte Carlo.")
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
    # Un flag por familia de estrategia, derivado de la tabla (agregar una
    # familia nueva no requiere tocar el CLI).
    for fam in FAMILIAS_ESTRATEGIA:
        p_simcfg.add_argument(fam.flag_cli, dest=fam.dest_cli,
                              choices=list(fam.registro.keys()),
                              help=f"{fam.etiqueta_ui} (clave en user_config.json).")

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
    p_maq.add_argument("--tasa-falla", type=float, metavar="FRAC",
                       help="Tasa de falla: fracción [0,1] del tiempo disponible perdido "
                            "por fallas (0 la quita). Se realiza con la --seed-fallas de simular.")

    p_jau = csub.add_parser("jaula", help="Gestiona rangos por jaula (list/set/remove).")
    p_jau.add_argument("accion", choices=["list", "set", "remove"])
    p_jau.add_argument("--jaula", type=int)
    p_jau.add_argument("--desde", type=float)
    p_jau.add_argument("--hasta", type=float)
    p_jau.add_argument("--perfil", help="Perfil (bombatura) de la jaula; \"\" lo quita.")

    p_gen = csub.add_parser("generador", help="Edita la config del generador de cambios.")
    p_gen.add_argument("--generador", choices=list(gencambios.GENERADORES_CAMBIOS))
    p_gen.add_argument("--umbral-desbaste", type=float,
                       help="mm a partir del cual el cambio se clasifica 'desbaste'.")
    p_gen.add_argument("--horizonte-dias", type=int, help="(legacy) ventana en días.")
    p_gen.add_argument("--fecha-inicio", help="Fecha de inicio de la generación (ISO YYYY-MM-DD).")
    p_gen.add_argument("--fecha-fin", help="Fecha de fin de la generación (ISO YYYY-MM-DD).")

    p_tc = csub.add_parser("turnos-cambios", help="Régimen de turnos del laminador (cambios).")
    p_tc.add_argument("--turnos", metavar="COMPACTO",
                      help="7 grupos lun..dom de 3 bits T1T2T3, p. ej. '111 111 111 111 111 110 000'.")
    p_tc.add_argument("--turnos-preset", choices=list(turnos_mod.PRESETS))

    # modelo (adaptación persistida del generador)
    p_mod = sub.add_parser("modelo", help="Ajusta/inspecciona el modelo aprendido del generador.")
    p_mod.add_argument("accion", choices=["ajustar", "show", "reset"])
    p_mod.add_argument("historia", nargs="?", help="Historia (.xlsx/.csv) para 'ajustar'.")
    p_mod.add_argument("--generador", choices=list(gencambios.GENERADORES_CAMBIOS))
    p_mod.add_argument("--umbral-desbaste", type=float)
    p_mod.add_argument("--reiniciar", action="store_true",
                       help="Ajusta desde cero en vez de refit incremental.")
    p_mod.set_defaults(func=_cmd_modelo)

    # generar-cambios
    p_gc = sub.add_parser("generar-cambios", help="Genera un Programa_Cambios reproducible por seed.")
    p_gc.add_argument("historia", nargs="?",
                      help="Historia opcional: si se pasa (o --ajustar), re-ajusta antes de generar.")
    p_gc.add_argument("--generador", choices=list(gencambios.GENERADORES_CAMBIOS))
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


def main(argv: Optional[List[str]] = None) -> int:
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
    if args.comando == "config" and args.subcomando == "turnos-cambios":
        if args.turnos and args.turnos_preset:
            parser.error("Use --turnos o --turnos-preset, no ambos")
    if args.comando == "modelo" and args.accion == "ajustar" and not args.historia:
        parser.error("'modelo ajustar' requiere la ruta de la historia")

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
