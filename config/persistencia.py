"""User configuration persistence in JSON.

From v4.1 on, the JSON is the source of truth for the workshop's structural
configuration (global params + machines + per-stand ranges + simulation params).
The loaded Excel only holds the variable data (initial stock and change schedule).

Current schema::

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

Old schemas (without ``config_global``/``maquinas`` and with the loose
``prioridades_maquinas`` dict) are migrated on load.

Note: the JSON keys are kept in Spanish on purpose — they are the persisted
config contract (existing user_config.json files depend on them).
"""
import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_DIR, "user_config.json")

# Grinding rate per machine, one entry per type. Seeded from the "Máquinas" sheet
# of the reference Excel (data/simulacion_140cils_1semana.xlsx).
_DEFAULT_RATES = {
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
         "tasas": {k: dict(v) for k, v in _DEFAULT_RATES.items()}},
        {"nombre": "F36", "prioridad": "produccion",
         "tasas": {k: dict(v) for k, v in _DEFAULT_RATES.items()}},
        {"nombre": "F60", "prioridad": "desbaste",
         "tasas": {k: dict(v) for k, v in _DEFAULT_RATES.items()}},
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
    # Synthetic Programa_Cambios generator learned from the real history.
    # ``turnos_cambios`` (the mill's own regime) is omitted ⇒ 24/7; only the
    # compact dict is persisted when it is not 24/7 (like the machine shifts).
    "generador_cambios": {
        "generador": "empirico",
        "umbral_desbaste_mm": 1.0,
        # Generation window (ISO YYYY-MM-DD). None ⇒ a default window (or the
        # legacy ``horizonte_dias``) is used when generating.
        "fecha_inicio": None,
        "fecha_fin": None,
        "horizonte_dias": 7,  # legacy: fallback if no fecha_inicio/fecha_fin
    },
}


# ── Load / save ──────────────────────────────────────────────────────────────

def cargar_config() -> Dict[str, Any]:
    """Load the user configuration, migrating old schemas.

    Returns the defaults if the file does not exist or is invalid.
    """
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return migrar(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return _copia_defaults()


def guardar_config(cfg: Dict[str, Any]) -> None:
    """Save the user configuration to disk."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _copia_defaults() -> Dict[str, Any]:
    """Deep copy of the defaults (so the module is not mutated)."""
    return json.loads(json.dumps(DEFAULTS))


def migrar(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in missing keys from DEFAULTS and migrate the old schema.

    - Fills ``config_global``, ``maquinas`` and ``rangos`` if missing.
    - Folds the loose ``prioridades_maquinas`` dict (old schema) into each
      machine by name.
    """
    base = _copia_defaults()
    base.update(cfg)

    # config_global: fill in missing loose fields
    cg = dict(DEFAULTS["config_global"])
    cg.update(cfg.get("config_global", {}))
    base["config_global"] = cg

    # maquinas: if absent, use the DEFAULTS ones
    if not cfg.get("maquinas"):
        base["maquinas"] = _copia_defaults()["maquinas"]

    # Migrate priorities from the old schema into the machines by name
    old_priorities = cfg.get("prioridades_maquinas") or {}
    if old_priorities:
        for maq in base["maquinas"]:
            if maq["nombre"] in old_priorities:
                maq["prioridad"] = old_priorities[maq["nombre"]]

    base.pop("prioridades_maquinas", None)  # old-schema key, already migrated
    return base


# ── Getters ──────────────────────────────────────────────────────────────────

def obtener_config_global(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return the workshop global parameters."""
    cg = dict(DEFAULTS["config_global"])
    cg.update(cfg.get("config_global", {}))
    return cg


def obtener_maquinas(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the machine list with their rates and priority.

    If the key is missing, returns a **copy** of the defaults (never the module's
    shared reference, so ``DEFAULTS`` is not mutated).
    """
    maquinas = cfg.get("maquinas")
    return maquinas if maquinas is not None else _copia_defaults()["maquinas"]


def obtener_rangos(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the per-stand diameter ranges from the configuration.

    If the key is missing, returns a **copy** of the defaults (never the module's
    shared reference, so ``DEFAULTS`` is not mutated).
    """
    rangos = cfg.get("rangos")
    return rangos if rangos is not None else _copia_defaults()["rangos"]


def obtener_prioridades(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Return the per-machine priorities (derived from the machine list)."""
    return {m["nombre"]: m.get("prioridad", "produccion") for m in obtener_maquinas(cfg)}


def obtener_tiempo_enfriado(cfg: Dict[str, Any]) -> float:
    """Return the cooling time (hours) after retiring a cylinder from the stand."""
    return float(cfg.get("tiempo_enfriado_h", DEFAULTS["tiempo_enfriado_h"]))


def obtener_max_iteraciones(cfg: Dict[str, Any]) -> int:
    """Return the maximum number of iterations of the simulation loop."""
    return int(cfg.get("max_iteraciones", DEFAULTS["max_iteraciones"]))


def obtener_estrategia_asignacion(cfg: Dict[str, Any]) -> str:
    """Return the key of the target-stand assignment strategy."""
    return str(cfg.get("estrategia_asignacion", DEFAULTS["estrategia_asignacion"]))


def obtener_estrategia_seleccion(cfg: Dict[str, Any]) -> str:
    """Return the key of the grinding-queue selection strategy."""
    return str(cfg.get("estrategia_seleccion", DEFAULTS["estrategia_seleccion"]))


def obtener_generador_cambios(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return the change-generator config (merged with the defaults)."""
    gc = dict(DEFAULTS["generador_cambios"])
    gc.update(cfg.get("generador_cambios", {}))
    return gc


def obtener_turnos_cambios(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the change shift regime (None = 24/7)."""
    return cfg.get("turnos_cambios")


# ── Mutators (single CRUD layer used by the CLI and the GUI) ──────────────────

def set_config_global(cfg: Dict[str, Any], *, diametro_maximo=None, diametro_minimo=None,
                      tiempo_traslado_crc_min=None, cantidad_jaulas=None) -> Dict[str, Any]:
    """Update the given fields of ``config_global`` (None values are ignored)."""
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
    """Add a new machine. Raises ValueError if the name already exists.

    ``turnos`` (work schedule) is optional; if omitted, the machine operates 24/7
    (the key is not persisted).
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
    """Modify the given fields of an existing machine.

    ``turnos`` replaces the work schedule when not None.
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
    """Return a machine's shift schedule (None = 24/7 or nonexistent)."""
    maq = _buscar_maquina(cfg, nombre)
    return maq.get("turnos") if maq else None


def remove_maquina(cfg: Dict[str, Any], nombre: str) -> Dict[str, Any]:
    """Remove a machine by name. Raises ValueError if it does not exist."""
    maqs = cfg.setdefault("maquinas", [])
    nuevas = [m for m in maqs if m["nombre"] != nombre]
    if len(nuevas) == len(maqs):
        raise ValueError(f"No existe una máquina llamada '{nombre}'.")
    cfg["maquinas"] = nuevas
    return cfg


def set_rango(cfg: Dict[str, Any], jaula: int, desde: float, hasta: float,
              perfil: Optional[str] = None) -> Dict[str, Any]:
    """Create or update a stand's range. Validates ``desde > hasta``.

    ``perfil`` is the profile (convexity) required by the stand. If ``None`` the
    existing profile is kept (not erased when editing only the range); to remove
    it pass the empty string ``""``.
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
    """Remove a stand's range by number."""
    jaula = int(jaula)
    rangos = cfg.setdefault("rangos", [])
    nuevos = [r for r in rangos if int(r["jaula"]) != jaula]
    if len(nuevos) == len(rangos):
        raise ValueError(f"No existe un rango para la jaula {jaula}.")
    cfg["rangos"] = nuevos
    return cfg


# ── Stands ⇄ ranges coherence (single source used by CLI and GUI) ─────────────

def problemas_coherencia(cfg: Dict[str, Any]) -> List[str]:
    """List the coherence problems between ``cantidad_jaulas`` and the ranges.

    A coherent config has **exactly one range per stand**, numbered
    ``1..cantidad_jaulas`` (no missing, extra or duplicate). For each kind of
    mismatch it adds a readable message. Returns ``[]`` if everything is fine.
    Does not mutate ``cfg``; it is the basis of both the CLI's non-fatal warning
    and the save error in CLI/GUI.
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
    """Raise ``ValueError`` if ``cfg`` is incoherent (see ``problemas_coherencia``)."""
    problemas = problemas_coherencia(cfg)
    if problemas:
        raise ValueError(" ".join(problemas))


def set_sim(cfg: Dict[str, Any], *, tiempo_enfriado=None, max_iteraciones=None,
            estrategia_asignacion=None, estrategia_seleccion=None) -> Dict[str, Any]:
    """Update the given simulation parameters."""
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
    """Update the given fields of the change-generator config.

    ``fecha_inicio``/``fecha_fin`` are ISO strings ``YYYY-MM-DD`` (or ``""`` to
    clear). If both come non-empty, ``fin > inicio`` is validated.
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
    """Set the change shift regime; ``None``/24-7 removes the key."""
    from models import shifts as shifts_mod  # local import: avoids a load cycle
    if turnos is None or shifts_mod.is_full(turnos):
        cfg.pop("turnos_cambios", None)
    else:
        cfg["turnos_cambios"] = turnos
    return cfg


# ── Import from a 4-sheet Excel (seed / migration) ────────────────────────────

def cfg_desde_excel(ruta_excel: str) -> Dict[str, Any]:
    """Extract ``config_global`` and ``maquinas`` from an Excel with the old sheets.

    Reads the ``Configuración`` and ``Máquinas`` sheets of a file in the old
    format (4 sheets) and returns a config dict ready to save. Keeps the default
    ``rangos`` and simulation params.
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
