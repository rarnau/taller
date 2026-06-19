"""Persistencia del modelo aprendido del generador de cambios.

Espejo de :mod:`config.persistencia` para el **artefacto de adaptación**: el
modelo que ``modelos.generador_cambios`` ajusta a partir de la historia real se
guarda en ``config/modelo_generador.json`` para poder:

- **refinarlo incrementalmente** al subir más historia (``ajustar`` con
  ``modelo_previo`` = lo guardado), y
- **reiniciarlo a cero** para una adaptación limpia (``reiniciar_modelo``).

El modelo es un dict JSON-serializable cuya clave ``clave`` registra qué
generador lo produjo; al cambiar de generador no se mezclan modelos de claves
distintas (el ``ajustar`` arranca de cero si la clave no coincide).
"""
import json
import os
from typing import Any, Dict, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
MODELO_PATH = os.path.join(_DIR, "modelo_generador.json")


def cargar_modelo() -> Optional[Dict[str, Any]]:
    """Carga el modelo persistido, o ``None`` si no existe / es inválido."""
    if os.path.exists(MODELO_PATH):
        try:
            with open(MODELO_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def guardar_modelo(modelo: Dict[str, Any]) -> None:
    """Guarda el modelo ajustado en disco."""
    with open(MODELO_PATH, "w", encoding="utf-8") as f:
        json.dump(modelo, f, ensure_ascii=False, indent=2)


def reiniciar_modelo() -> None:
    """Borra el modelo persistido (adaptación limpia desde cero)."""
    if os.path.exists(MODELO_PATH):
        os.remove(MODELO_PATH)
