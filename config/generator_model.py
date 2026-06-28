"""Persistencia del modelo aprendido del generador de cambios.

Espejo de :mod:`config.persistencia` para el **artefacto de adaptación**: el
modelo que ``modelos.generador_cambios`` ajusta a partir de la historia real se
guarda en ``config/generator_model.json`` para poder:

- **refinarlo incrementalmente** al subir más historia (``ajustar`` con
  ``modelo_previo`` = lo guardado), y
- **reiniciarlo a cero** para una adaptación limpia (``reset_models``).

El modelo es un dict JSON-serializable cuya clave ``clave`` registra qué
generador lo produjo; al cambiar de generador no se mezclan modelos de claves
distintas (el ``ajustar`` arranca de cero si la clave no coincide). En disco se
guardan **todos** los modelos bajo ``{"modelos": {clave: modelo}, "activo": ...}``;
``activo`` apunta al último ajustado.
"""
import json
import os
from typing import Any, Dict, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_STORE_PATH = os.path.join(_DIR, "generator_model.json")


def _read_store_file() -> Optional[Dict[str, Any]]:
    """Lee el JSON crudo del disco, o ``None`` si no existe / es inválido."""
    if os.path.exists(MODEL_STORE_PATH):
        try:
            with open(MODEL_STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _normalize_store(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normaliza el payload persistido al formato multi-modelo.

    Acepta tanto el formato nuevo ``{"modelos": {...}, "activo": ...}`` como el
    legado (un único modelo dict con ``clave``) y devuelve siempre el nuevo.
    """
    if not data:
        return {"modelos": {}, "activo": None}

    # Formato nuevo: {"modelos": {clave: modelo}, "activo": "..."}
    if isinstance(data.get("modelos"), dict):
        models = {str(k): v for k, v in data["modelos"].items() if isinstance(v, dict)}
        active = data.get("activo")
        if active not in models:
            active = next(iter(models), None)
        return {"modelos": models, "activo": active}

    # Formato legado: un único modelo dict con clave.
    key = str(data.get("clave") or "")
    if key:
        return {"modelos": {key: data}, "activo": key}
    return {"modelos": {}, "activo": None}


def _write_store_file(store: Dict[str, Any]) -> None:
    """Escribe el store normalizado al JSON en disco."""
    with open(MODEL_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def load_models() -> Dict[str, Dict[str, Any]]:
    """Carga todos los modelos persistidos indexados por clave de generador."""
    store = _normalize_store(_read_store_file())
    return dict(store["modelos"])


def load_model_for_key(key: str) -> Optional[Dict[str, Any]]:
    """Carga el modelo de una clave concreta, si existe."""
    if not key:
        return None
    return load_models().get(str(key))


def load_active_model() -> Optional[Dict[str, Any]]:
    """Carga el modelo activo (el último ajustado), o ``None`` si no hay."""
    store = _normalize_store(_read_store_file())
    models = store["modelos"]
    if not models:
        return None
    active = store.get("activo")
    if isinstance(active, str) and active in models:
        return models[active]
    return next(iter(models.values()))


def save_model_for_key(key: str, model: Dict[str, Any], *, set_active: bool = True) -> None:
    """Guarda/actualiza un modelo para una clave sin perder los demás."""
    if not key:
        raise ValueError("La clave del modelo no puede ser vacía.")
    store = _normalize_store(_read_store_file())
    store["modelos"][str(key)] = model
    if set_active:
        store["activo"] = str(key)
    _write_store_file(store)


def save_model(model: Dict[str, Any]) -> None:
    """Guarda el modelo ajustado en disco y lo marca como activo."""
    key = str(model.get("clave") or "")
    if not key:
        raise ValueError("El modelo debe incluir una 'clave' válida.")
    save_model_for_key(key, model, set_active=True)


def reset_models(key: Optional[str] = None) -> None:
    """Reinicia modelos persistidos.

    - ``key is None``: borra todo (comportamiento legado).
    - ``key``: borra solo ese modelo y conserva los demás.
    """
    if key is None:
        if os.path.exists(MODEL_STORE_PATH):
            os.remove(MODEL_STORE_PATH)
        return

    store = _normalize_store(_read_store_file())
    models = store["modelos"]
    models.pop(str(key), None)
    if not models:
        if os.path.exists(MODEL_STORE_PATH):
            os.remove(MODEL_STORE_PATH)
        return

    if store.get("activo") == str(key):
        store["activo"] = next(iter(models), None)
    _write_store_file(store)
