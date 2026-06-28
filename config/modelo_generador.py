"""Persistence of the change generator's learned model.

Mirror of :mod:`config.persistencia` for the **adaptation artifact**: the model
that ``models.change_generator`` fits from the real history is saved to
``config/modelo_generador.json`` so it can be:

- **refined incrementally** when more history is uploaded (``fit`` with
  ``prior_model`` = what was saved), and
- **reset to zero** for a clean adaptation (``reiniciar_modelo``).

The model is a JSON-serializable dict whose ``clave`` key records which generator
produced it; switching generators does not mix models of different keys (``fit``
starts from scratch if the key does not match).

Note: the public function names and the persisted dict keys stay in Spanish on
purpose — they are part of the config persistence layer / saved-file contract.
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
    """Normalize the persisted payload to the multi-model format."""
    if not data:
        return {"modelos": {}, "activo": None}

    # New format: {"modelos": {key: model}, "activo": "..."}
    if isinstance(data.get("modelos"), dict):
        modelos = {str(k): v for k, v in data["modelos"].items() if isinstance(v, dict)}
        activo = data.get("activo")
        if activo not in modelos:
            activo = next(iter(modelos), None)
        return {"modelos": modelos, "activo": activo}

    # Legacy format: a single model dict with a key.
    clave = str(data.get("clave") or "")
    if clave:
        return {"modelos": {clave: data}, "activo": clave}
    return {"modelos": {}, "activo": None}


def _save_store(store: Dict[str, Any]) -> None:
    with open(MODELO_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def cargar_modelos() -> Dict[str, Dict[str, Any]]:
    """Load all persisted models indexed by generator key."""
    store = _to_store(_load_raw())
    return dict(store["modelos"])


def cargar_modelo_por_clave(clave: str) -> Optional[Dict[str, Any]]:
    """Load the model for a specific key, if it exists."""
    if not clave:
        return None
    return cargar_modelos().get(str(clave))


def cargar_modelo() -> Optional[Dict[str, Any]]:
    """Load the persisted model, or ``None`` if it does not exist / is invalid."""
    store = _to_store(_load_raw())
    modelos = store["modelos"]
    if not modelos:
        return None
    activo = store.get("activo")
    if isinstance(activo, str) and activo in modelos:
        return modelos[activo]
    return next(iter(modelos.values()))


def guardar_modelo_por_clave(clave: str, modelo: Dict[str, Any], *, set_activo: bool = True) -> None:
    """Save/update a model for a key without losing the others."""
    if not clave:
        raise ValueError("La clave del modelo no puede ser vacía.")
    store = _to_store(_load_raw())
    store["modelos"][str(clave)] = modelo
    if set_activo:
        store["activo"] = str(clave)
    _save_store(store)


def guardar_modelo(modelo: Dict[str, Any]) -> None:
    """Save the fitted model to disk."""
    clave = str(modelo.get("clave") or "")
    if not clave:
        raise ValueError("El modelo debe incluir una 'clave' válida.")
    guardar_modelo_por_clave(clave, modelo, set_activo=True)


def reiniciar_modelo(clave: Optional[str] = None) -> None:
    """Reset persisted models.

    - ``clave is None``: deletes everything (legacy behavior).
    - ``clave``: deletes only that model and keeps the others.
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
