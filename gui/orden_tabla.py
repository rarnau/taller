"""Ordenamiento type-aware de filas de la tabla de Inventario (sin Tk)."""
import math

_PLACEHOLDERS = {"", "-"}

def _es_numerico(v: str) -> bool:
    """True si `v` es un placeholder o parsea como float."""
    s = str(v).strip()
    if s in _PLACEHOLDERS:
        return True
    try:
        float(s)
        return True
    except ValueError:
        return False

def _a_float(v: str) -> float:
    """float de `v`; placeholders → +inf (van al final en ascendente)."""
    s = str(v).strip()
    if s in _PLACEHOLDERS:
        return math.inf
    try:
        return float(s)
    except ValueError:
        return math.inf

def ordenar_filas(cols, filas, sort_col, desc):
    """Devuelve `filas` ordenadas por `sort_col` (None ⇒ sin cambios).

    Type-aware: si todos los valores de la columna son numéricos/placeholder,
    ordena por número; si no, alfabético case-insensitive. `desc` invierte."""
    if sort_col is None or sort_col not in cols:
        return list(filas)
    idx = cols.index(sort_col)
    valores = [str(f[idx]) for f in filas]
    if valores and all(_es_numerico(v) for v in valores):
        clave = lambda f: _a_float(str(f[idx]))
    else:
        clave = lambda f: str(f[idx]).lower()
    return sorted(filas, key=clave, reverse=desc)
