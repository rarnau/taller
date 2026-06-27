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


def _load_raw() -> Optional[Dict[str, Any]]:
    if os.path.exists(MODELO_PATH):
        try:
            with open(MODELO_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _to_store(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normaliza el payload persistido al formato multi-modelo."""
    if not data:
        return {"modelos": {}, "activo": None}

    # Nuevo formato: {"modelos": {clave: modelo}, "activo": "..."}
    if isinstance(data.get("modelos"), dict):
        modelos = {str(k): v for k, v in data["modelos"].items() if isinstance(v, dict)}
        activo = data.get("activo")
        if activo not in modelos:
            activo = next(iter(modelos), None)
        return {"modelos": modelos, "activo": activo}

    # Formato legado: un único modelo dict con clave.
    clave = str(data.get("clave") or "")
    if clave:
        return {"modelos": {clave: data}, "activo": clave}
    return {"modelos": {}, "activo": None}


def _save_store(store: Dict[str, Any]) -> None:
    with open(MODELO_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def cargar_modelos() -> Dict[str, Dict[str, Any]]:
    """Carga todos los modelos persistidos indexados por clave de generador."""
    store = _to_store(_load_raw())
    return dict(store["modelos"])


def cargar_modelo_por_clave(clave: str) -> Optional[Dict[str, Any]]:
    """Carga el modelo de una clave concreta, si existe."""
    if not clave:
        return None
    return cargar_modelos().get(str(clave))


def cargar_modelo() -> Optional[Dict[str, Any]]:
    """Carga el modelo persistido, o ``None`` si no existe / es inválido."""
    store = _to_store(_load_raw())
    modelos = store["modelos"]
    if not modelos:
        return None
    activo = store.get("activo")
    if isinstance(activo, str) and activo in modelos:
        return modelos[activo]
    return next(iter(modelos.values()))


def guardar_modelo_por_clave(clave: str, modelo: Dict[str, Any], *, set_activo: bool = True) -> None:
    """Guarda/actualiza un modelo para una clave sin perder los demás."""
    if not clave:
        raise ValueError("La clave del modelo no puede ser vacía.")
    store = _to_store(_load_raw())
    store["modelos"][str(clave)] = modelo
    if set_activo:
        store["activo"] = str(clave)
    _save_store(store)


def guardar_modelo(modelo: Dict[str, Any]) -> None:
    """Guarda el modelo ajustado en disco."""
    clave = str(modelo.get("clave") or "")
    if not clave:
        raise ValueError("El modelo debe incluir una 'clave' válida.")
    guardar_modelo_por_clave(clave, modelo, set_activo=True)


def reiniciar_modelo(clave: Optional[str] = None) -> None:
    """Reinicia modelos persistidos.

    - ``clave is None``: borra todo (comportamiento legado).
    - ``clave``: borra solo ese modelo y conserva los demás.
    """
    if clave is None:
        if os.path.exists(MODELO_PATH):
            os.remove(MODELO_PATH)
        return

    store = _to_store(_load_raw())
    modelos = store["modelos"]
    modelos.pop(str(clave), None)
    if not modelos:
        if os.path.exists(MODELO_PATH):
            os.remove(MODELO_PATH)
        return

    if store.get("activo") == str(clave):
        store["activo"] = next(iter(modelos), None)
    _save_store(store)
