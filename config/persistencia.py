"""Persistencia de configuración de usuario en JSON.

A partir de v4.1 el JSON es la fuente de verdad de la configuración estructural
del taller (parámetros globales + máquinas + rangos por jaula + parámetros de
simulación). El Excel cargado pasa a contener únicamente los datos variables
(stock inicial y programa de cambios).

Esquema actual::

    {
      "config_global": {"diametro_maximo", "diametro_minimo",
                        "tiempo_traslado_crc_min", "cantidad_jaulas"},
      "maquinas": [{"nombre", "prioridad",
                    "tasas": {"produccion": {"mm", "tiempo_min"},
                              "desbaste":   {"mm", "tiempo_min"}}}],
      "rangos": [{"jaula", "desde", "hasta"}],
      "tiempo_enfriado_h": float,
      "max_iteraciones": int
    }

Esquemas viejos (sin ``config_global``/``maquinas`` y con el dict suelto
``prioridades_maquinas``) se migran al cargar.
"""
import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_DIR, "user_config.json")

# Tasa de rectificado por máquina, una entrada por tipo. Sembrado desde la hoja
# "Máquinas" del Excel de referencia (datos/simulacion_140cils_1semana.xlsx).
_TASAS_DEFECTO = {
    "produccion": {"mm": 0.8, "tiempo_min": 60},
    "desbaste": {"mm": 5.0, "tiempo_min": 480},
}

DEFAULTS: Dict[str, Any] = {
    "config_global": {
        "diametro_maximo": 575.0,
        "diametro_minimo": 520.0,
        "tiempo_traslado_crc_min": 10.0,
        "cantidad_jaulas": 4,
    },
    "maquinas": [
        {"nombre": "G36", "prioridad": "produccion",
         "tasas": {k: dict(v) for k, v in _TASAS_DEFECTO.items()}},
        {"nombre": "F36", "prioridad": "produccion",
         "tasas": {k: dict(v) for k, v in _TASAS_DEFECTO.items()}},
        {"nombre": "F60", "prioridad": "desbaste",
         "tasas": {k: dict(v) for k, v in _TASAS_DEFECTO.items()}},
    ],
    "rangos": [
        {"jaula": 1, "desde": 533.0, "hasta": 520.0, "perfil": "4"},
        {"jaula": 2, "desde": 547.0, "hasta": 533.0, "perfil": "2"},
        {"jaula": 3, "desde": 561.0, "hasta": 547.0, "perfil": "2"},
        {"jaula": 4, "desde": 575.0, "hasta": 561.0, "perfil": "3"},
    ],
    "tiempo_enfriado_h": 0.0,
    "max_iteraciones": 10000,
    "estrategia_seleccion": "mayor_diametro",
    "estrategia_asignacion": "jaula_mas_necesitada",
    # Generador sintético del Programa_Cambios a partir de la historia real.
    # ``turnos_cambios`` (régimen propio del laminador) se omite ⇒ 24/7; sólo se
    # persiste el dict compacto cuando no es 24/7 (igual que los turnos de máquina).
    "generador_cambios": {
        "generador": "empirico",
        "umbral_desbaste_mm": 1.0,
        # Ventana de generación (ISO YYYY-MM-DD). None ⇒ se usa una ventana por
        # defecto (o el legacy ``horizonte_dias``) al generar.
        "fecha_inicio": None,
        "fecha_fin": None,
        "horizonte_dias": 7,  # legacy: fallback si no hay fecha_inicio/fecha_fin
    },
}


# ── Carga / guardado ─────────────────────────────────────────────────────────

def cargar_config() -> Dict[str, Any]:
    """Carga la configuración de usuario, migrando esquemas viejos.

    Devuelve los valores por defecto si el archivo no existe o es inválido.
    """
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return migrar(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return _copia_defaults()


def guardar_config(cfg: Dict[str, Any]) -> None:
    """Guarda la configuración de usuario en disco."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _copia_defaults() -> Dict[str, Any]:
    """Copia profunda de los valores por defecto (para no mutar el módulo)."""
    return json.loads(json.dumps(DEFAULTS))


def migrar(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Completa claves faltantes desde DEFAULTS y migra el esquema viejo.

    - Rellena ``config_global``, ``maquinas`` y ``rangos`` si faltan.
    - Fusiona el dict suelto ``prioridades_maquinas`` (esquema viejo) dentro de
      cada máquina por nombre.
    """
    base = _copia_defaults()
    base.update(cfg)

    # config_global: completar campos sueltos faltantes
    cg = dict(DEFAULTS["config_global"])
    cg.update(cfg.get("config_global", {}))
    base["config_global"] = cg

    # maquinas: si no vienen, usar las de DEFAULTS
    if not cfg.get("maquinas"):
        base["maquinas"] = _copia_defaults()["maquinas"]

    # Migrar prioridades del esquema viejo a las máquinas por nombre
    prio_viejas = cfg.get("prioridades_maquinas") or {}
    if prio_viejas:
        for maq in base["maquinas"]:
            if maq["nombre"] in prio_viejas:
                maq["prioridad"] = prio_viejas[maq["nombre"]]

    base.pop("prioridades_maquinas", None)  # clave del esquema viejo, ya migrada
    return base


# ── Getters ──────────────────────────────────────────────────────────────────

def obtener_config_global(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve los parámetros globales del taller."""
    cg = dict(DEFAULTS["config_global"])
    cg.update(cfg.get("config_global", {}))
    return cg


def obtener_maquinas(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Devuelve la lista de máquinas con sus tasas y prioridad.

    Si la clave falta, devuelve una **copia** de los defaults (nunca la
    referencia compartida del módulo, para no mutar ``DEFAULTS``).
    """
    maquinas = cfg.get("maquinas")
    return maquinas if maquinas is not None else _copia_defaults()["maquinas"]


def obtener_rangos(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Devuelve los rangos de diámetros por jaula desde la configuración.

    Si la clave falta, devuelve una **copia** de los defaults (nunca la
    referencia compartida del módulo, para no mutar ``DEFAULTS``).
    """
    rangos = cfg.get("rangos")
    return rangos if rangos is not None else _copia_defaults()["rangos"]


def obtener_prioridades(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Devuelve las prioridades por máquina (derivadas de la lista de máquinas)."""
    return {m["nombre"]: m.get("prioridad", "produccion") for m in obtener_maquinas(cfg)}


def obtener_tiempo_enfriado(cfg: Dict[str, Any]) -> float:
    """Devuelve el tiempo de enfriado (horas) tras retirar un cilindro de la jaula."""
    return float(cfg.get("tiempo_enfriado_h", DEFAULTS["tiempo_enfriado_h"]))


def obtener_max_iteraciones(cfg: Dict[str, Any]) -> int:
    """Devuelve el máximo de iteraciones del bucle de simulación."""
    return int(cfg.get("max_iteraciones", DEFAULTS["max_iteraciones"]))


def obtener_estrategia_asignacion(cfg: Dict[str, Any]) -> str:
    """Devuelve la clave de la estrategia de asignación de jaula destino."""
    return str(cfg.get("estrategia_asignacion", DEFAULTS["estrategia_asignacion"]))


def obtener_estrategia_seleccion(cfg: Dict[str, Any]) -> str:
    """Devuelve la clave de la estrategia de selección de la cola de rectificado."""
    return str(cfg.get("estrategia_seleccion", DEFAULTS["estrategia_seleccion"]))


def obtener_generador_cambios(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve la config del generador de cambios (merge con los defaults)."""
    gc = dict(DEFAULTS["generador_cambios"])
    gc.update(cfg.get("generador_cambios", {}))
    return gc


def obtener_turnos_cambios(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Devuelve el régimen de turnos de los cambios (None = 24/7)."""
    return cfg.get("turnos_cambios")


# ── Mutadores (capa única de CRUD usada por el CLI y la GUI) ──────────────────

def set_config_global(cfg: Dict[str, Any], *, diametro_maximo=None, diametro_minimo=None,
                      tiempo_traslado_crc_min=None, cantidad_jaulas=None) -> Dict[str, Any]:
    """Actualiza los campos indicados de ``config_global`` (los None se ignoran)."""
    cg = obtener_config_global(cfg)
    if diametro_maximo is not None:
        cg["diametro_maximo"] = float(diametro_maximo)
    if diametro_minimo is not None:
        cg["diametro_minimo"] = float(diametro_minimo)
    if tiempo_traslado_crc_min is not None:
        cg["tiempo_traslado_crc_min"] = float(tiempo_traslado_crc_min)
    if cantidad_jaulas is not None:
        cg["cantidad_jaulas"] = int(cantidad_jaulas)
    cfg["config_global"] = cg
    return cfg


def _buscar_maquina(cfg: Dict[str, Any], nombre: str) -> Optional[Dict[str, Any]]:
    for m in cfg.setdefault("maquinas", []):
        if m["nombre"] == nombre:
            return m
    return None


def add_maquina(cfg: Dict[str, Any], nombre: str, *, prod_mm: float, prod_min: float,
                desb_mm: float, desb_min: float, prioridad: str = "produccion",
                turnos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Agrega una máquina nueva. Lanza ValueError si el nombre ya existe.

    ``turnos`` (esquema de trabajo) es opcional; si se omite, la máquina opera
    24/7 (no se persiste la clave).
    """
    nombre = str(nombre).strip()
    if not nombre:
        raise ValueError("El nombre de la máquina no puede estar vacío.")
    if _buscar_maquina(cfg, nombre):
        raise ValueError(f"Ya existe una máquina llamada '{nombre}'.")
    maq: Dict[str, Any] = {
        "nombre": nombre,
        "prioridad": prioridad,
        "tasas": {
            "produccion": {"mm": float(prod_mm), "tiempo_min": float(prod_min)},
            "desbaste": {"mm": float(desb_mm), "tiempo_min": float(desb_min)},
        },
    }
    if turnos is not None:
        maq["turnos"] = turnos
    cfg.setdefault("maquinas", []).append(maq)
    return cfg


def set_maquina(cfg: Dict[str, Any], nombre: str, *, prod_mm=None, prod_min=None,
                desb_mm=None, desb_min=None, prioridad=None,
                turnos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Modifica los campos indicados de una máquina existente.

    ``turnos`` reemplaza el esquema de trabajo cuando no es None.
    """
    maq = _buscar_maquina(cfg, nombre)
    if not maq:
        raise ValueError(f"No existe una máquina llamada '{nombre}'.")
    tasas = maq.setdefault("tasas", {})
    prod = tasas.setdefault("produccion", {"mm": 0.0, "tiempo_min": 0.0})
    desb = tasas.setdefault("desbaste", {"mm": 0.0, "tiempo_min": 0.0})
    if prod_mm is not None:
        prod["mm"] = float(prod_mm)
    if prod_min is not None:
        prod["tiempo_min"] = float(prod_min)
    if desb_mm is not None:
        desb["mm"] = float(desb_mm)
    if desb_min is not None:
        desb["tiempo_min"] = float(desb_min)
    if prioridad is not None:
        maq["prioridad"] = prioridad
    if turnos is not None:
        maq["turnos"] = turnos
    return cfg


def obtener_turnos(cfg: Dict[str, Any], nombre: str) -> Optional[Dict[str, Any]]:
    """Devuelve el esquema de turnos de una máquina (None = 24/7 o inexistente)."""
    maq = _buscar_maquina(cfg, nombre)
    return maq.get("turnos") if maq else None


def remove_maquina(cfg: Dict[str, Any], nombre: str) -> Dict[str, Any]:
    """Elimina una máquina por nombre. Lanza ValueError si no existe."""
    maqs = cfg.setdefault("maquinas", [])
    nuevas = [m for m in maqs if m["nombre"] != nombre]
    if len(nuevas) == len(maqs):
        raise ValueError(f"No existe una máquina llamada '{nombre}'.")
    cfg["maquinas"] = nuevas
    return cfg


def set_rango(cfg: Dict[str, Any], jaula: int, desde: float, hasta: float,
              perfil: Optional[str] = None) -> Dict[str, Any]:
    """Crea o actualiza el rango de una jaula. Valida ``desde > hasta``.

    ``perfil`` es el perfil (bombatura) exigido por la jaula. Si es ``None`` se
    conserva el perfil ya existente (no se borra al editar sólo el rango); para
    quitarlo pásese cadena vacía ``""``.
    """
    jaula = int(jaula)
    desde, hasta = float(desde), float(hasta)
    if desde <= hasta:
        raise ValueError(f"Jaula {jaula}: 'desde' ({desde}) debe ser mayor que 'hasta' ({hasta}).")
    perfil_norm = None if perfil in (None, "") else str(perfil)
    rangos = cfg.setdefault("rangos", [])
    for r in rangos:
        if int(r["jaula"]) == jaula:
            r["desde"], r["hasta"] = desde, hasta
            if perfil == "":
                r.pop("perfil", None)
            elif perfil is not None:
                r["perfil"] = perfil_norm
            return cfg
    nuevo = {"jaula": jaula, "desde": desde, "hasta": hasta}
    if perfil_norm is not None:
        nuevo["perfil"] = perfil_norm
    rangos.append(nuevo)
    rangos.sort(key=lambda r: int(r["jaula"]))
    return cfg


def remove_rango(cfg: Dict[str, Any], jaula: int) -> Dict[str, Any]:
    """Elimina el rango de una jaula por número."""
    jaula = int(jaula)
    rangos = cfg.setdefault("rangos", [])
    nuevos = [r for r in rangos if int(r["jaula"]) != jaula]
    if len(nuevos) == len(rangos):
        raise ValueError(f"No existe un rango para la jaula {jaula}.")
    cfg["rangos"] = nuevos
    return cfg


# ── Coherencia jaulas ⇄ rangos (fuente única usada por CLI y GUI) ─────────────

def problemas_coherencia(cfg: Dict[str, Any]) -> List[str]:
    """Lista los problemas de coherencia entre ``cantidad_jaulas`` y los rangos.

    Una config coherente tiene **exactamente un rango por jaula**, con números de
    jaula ``1..cantidad_jaulas`` (sin faltantes, sobrantes ni duplicados). Para
    cada tipo de desajuste agrega un mensaje legible. Devuelve ``[]`` si todo
    está en orden. No muta ``cfg``; es la base tanto del aviso no fatal del CLI
    como del error de guardado en CLI/GUI.
    """
    cg = obtener_config_global(cfg)
    try:
        n = int(cg.get("cantidad_jaulas", 0))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return ["La cantidad de jaulas debe ser un entero mayor que 0."]

    jaulas = [int(r["jaula"]) for r in obtener_rangos(cfg)]
    esperadas = set(range(1, n + 1))
    presentes = set(jaulas)

    problemas: List[str] = []
    dups = sorted(j for j, c in Counter(jaulas).items() if c > 1)
    faltan = sorted(esperadas - presentes)
    sobran = sorted(presentes - esperadas)
    if dups:
        problemas.append(f"Rango(s) de SubStock duplicado(s) para la(s) jaula(s): "
                         f"{', '.join(map(str, dups))}.")
    if faltan:
        problemas.append(f"Falta(n) rango(s) de SubStock para la(s) jaula(s): "
                         f"{', '.join(map(str, faltan))}.")
    if sobran:
        problemas.append(f"Hay rango(s) de SubStock para jaula(s) inexistente(s) "
                         f"(cantidad_jaulas={n}): {', '.join(map(str, sobran))}.")
    return problemas


def verificar_coherencia(cfg: Dict[str, Any]) -> None:
    """Lanza ``ValueError`` si ``cfg`` es incoherente (ver ``problemas_coherencia``)."""
    problemas = problemas_coherencia(cfg)
    if problemas:
        raise ValueError(" ".join(problemas))


def set_sim(cfg: Dict[str, Any], *, tiempo_enfriado=None, max_iteraciones=None,
            estrategia_asignacion=None, estrategia_seleccion=None) -> Dict[str, Any]:
    """Actualiza los parámetros de simulación indicados."""
    if tiempo_enfriado is not None:
        t = round(float(tiempo_enfriado), 1)
        if t < 0:
            raise ValueError("El tiempo de enfriado no puede ser negativo.")
        cfg["tiempo_enfriado_h"] = t
    if max_iteraciones is not None:
        n = int(max_iteraciones)
        if n <= 0:
            raise ValueError("El máximo de iteraciones debe ser mayor que 0.")
        cfg["max_iteraciones"] = n
    if estrategia_asignacion is not None:
        cfg["estrategia_asignacion"] = str(estrategia_asignacion)
    if estrategia_seleccion is not None:
        cfg["estrategia_seleccion"] = str(estrategia_seleccion)
    return cfg


def set_generador_cambios(cfg: Dict[str, Any], *, generador=None,
                          umbral_desbaste=None, horizonte_dias=None,
                          fecha_inicio=None, fecha_fin=None) -> Dict[str, Any]:
    """Actualiza los campos indicados de la config del generador de cambios.

    ``fecha_inicio``/``fecha_fin`` son cadenas ISO ``YYYY-MM-DD`` (o ``""`` para
    limpiar). Si ambas vienen no vacías se valida ``fin > inicio``.
    """
    gc = obtener_generador_cambios(cfg)
    if generador is not None:
        gc["generador"] = str(generador)
    if umbral_desbaste is not None:
        u = float(umbral_desbaste)
        if u < 0:
            raise ValueError("El umbral de desbaste no puede ser negativo.")
        gc["umbral_desbaste_mm"] = u
    if horizonte_dias is not None:
        h = int(horizonte_dias)
        if h <= 0:
            raise ValueError("El horizonte en días debe ser mayor que 0.")
        gc["horizonte_dias"] = h
    if fecha_inicio is not None:
        gc["fecha_inicio"] = str(fecha_inicio).strip() or None
    if fecha_fin is not None:
        gc["fecha_fin"] = str(fecha_fin).strip() or None
    fi, ff = gc.get("fecha_inicio"), gc.get("fecha_fin")
    if fi and ff and not (ff > fi):
        raise ValueError("La fecha fin debe ser posterior a la fecha inicio.")
    cfg["generador_cambios"] = gc
    return cfg


def set_turnos_cambios(cfg: Dict[str, Any],
                       turnos: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fija el régimen de turnos de los cambios; ``None``/24-7 quita la clave."""
    from modelos import turnos as turnos_mod  # import local: evita ciclo de carga
    if turnos is None or turnos_mod.es_completo(turnos):
        cfg.pop("turnos_cambios", None)
    else:
        cfg["turnos_cambios"] = turnos
    return cfg


# ── Importación desde Excel de 4 hojas (siembra / migración) ──────────────────

def cfg_desde_excel(ruta_excel: str) -> Dict[str, Any]:
    """Extrae ``config_global`` y ``maquinas`` de un Excel con las hojas viejas.

    Lee las hojas ``Configuración`` y ``Máquinas`` de un archivo en formato
    antiguo (4 hojas) y devuelve un dict de configuración listo para guardar.
    Conserva ``rangos`` y parámetros de simulación por defecto.
    """
    import pandas as pd

    xl = pd.ExcelFile(ruta_excel, engine="openpyxl")
    cfg = _copia_defaults()

    if "Configuración" in xl.sheet_names:
        df = xl.parse("Configuración")
        valores = dict(zip(df["Parámetro"], df["Valor"]))
        cfg["config_global"] = {
            "diametro_maximo": float(valores.get("Diámetro Máximo (mm)", 575.0)),
            "diametro_minimo": float(valores.get("Diámetro Mínimo (mm)", 520.0)),
            "tiempo_traslado_crc_min": float(
                valores.get("Tiempo Disponible→CRC por pareja (min)", 10.0)),
            "cantidad_jaulas": int(valores.get("Cantidad de Jaulas", 4)),
        }

    if "Máquinas" in xl.sheet_names:
        df = xl.parse("Máquinas")
        maquinas: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            nombre = str(row["Máquina"])
            tipo = str(row["Tipo_Rectificado"])
            maq = maquinas.setdefault(nombre, {"nombre": nombre, "prioridad": "produccion", "tasas": {}})
            maq["tasas"][tipo] = {"mm": float(row["mm_removidos"]), "tiempo_min": float(row["Tiempo_min"])}
        cfg["maquinas"] = list(maquinas.values())

    return cfg
