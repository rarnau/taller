"""Persistencia de configuración de usuario en JSON."""
import json
import os
from typing import Any, Dict, List

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_DIR, "user_config.json")

DEFAULTS: Dict[str, Any] = {
    "rangos": [
        {"jaula": 1, "desde": 533.0, "hasta": 520.0},
        {"jaula": 2, "desde": 547.0, "hasta": 533.0},
        {"jaula": 3, "desde": 561.0, "hasta": 547.0},
        {"jaula": 4, "desde": 575.0, "hasta": 561.0},
    ],
    "prioridades_maquinas": {},
}


def cargar_config() -> Dict[str, Any]:
    """Carga la configuración de usuario; devuelve los valores por defecto si no existe o es inválida."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULTS.copy()


def guardar_config(cfg: Dict[str, Any]) -> None:
    """Guarda la configuración de usuario en disco."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def obtener_rangos(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Devuelve los rangos de diámetros por jaula desde la configuración."""
    return cfg.get("rangos", DEFAULTS["rangos"])


def obtener_prioridades(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Devuelve las prioridades de rectificado por máquina desde la configuración."""
    return cfg.get("prioridades_maquinas", {})
