"""Validación PURA (sin Tk) de los campos de la pestaña Configuración.

Vive en su propio módulo **sin dependencias de customtkinter/tkinter** para que
la lógica de validación en vivo sea testeable sin entorno gráfico (los tests
importan ``_estado_validacion`` desde aquí). ``gui/tab_config.py`` la reexporta.
"""
from typing import List, Tuple

# Etiquetas legibles de los campos globales requeridos (orden de evaluación).
_ETIQUETAS_GLOBALES = {
    "diam_max": "Diámetro máximo",
    "diam_min": "Diámetro mínimo",
    "crc": "Traslado Disponible→CRC",
    "jaulas": "Cantidad de jaulas",
    "enfriado": "Tiempo de enfriado",
    "max_iter": "Máximo de iteraciones",
}


def _a_numero(txt: str):
    """Convierte ``txt`` a float; lanza ValueError si no es numérico."""
    return float(str(txt).strip())


def _estado_validacion(globales: dict, rangos: list,
                       maquinas: list | None = None) -> Tuple[str, bool]:
    """Valida en vivo los campos de Configuración (valores crudos, sin Tk).

    ``globales`` = {"diam_max","diam_min","crc","jaulas","enfriado","max_iter"}
    (strings). ``rangos`` = lista de dicts {"jaula":int, "min":str, "max":str,
    "perfil":str}. ``maquinas`` = lista de dicts {"nombre":str, "prod_mm":str,
    "prod_min":str, "desb_mm":str, "desb_min":str} (opcional, retrocompat).
    Devuelve ``(mensaje, es_error)``. El primer problema detectado manda; si
    todo OK, devuelve un ✓ con un resumen. Mensajes verbosos con ⚠ (requerido),
    ❌ (inválido).
    """
    # 1) Campos globales requeridos vacíos (en orden).
    for clave, etiqueta in _ETIQUETAS_GLOBALES.items():
        if str(globales.get(clave, "")).strip() == "":
            return (f"⚠ Campo requerido: {etiqueta}", True)

    # 2) Campos globales no numéricos (en orden).
    valores = {}
    for clave, etiqueta in _ETIQUETAS_GLOBALES.items():
        try:
            valores[clave] = _a_numero(globales[clave])
        except ValueError:
            return (f"❌ Valor inválido en {etiqueta} (debe ser número)", True)

    # 3) Reglas de coherencia de los globales.
    if valores["diam_max"] <= valores["diam_min"]:
        return ("❌ El diámetro máximo debe ser mayor que el mínimo", True)
    jaulas = int(valores["jaulas"])
    if jaulas <= 0:
        return ("❌ La cantidad de jaulas debe ser mayor que 0", True)
    if valores["crc"] < 0:
        return ("❌ El traslado Disponible→CRC no puede ser negativo", True)
    if valores["enfriado"] < 0:
        return ("❌ El tiempo de enfriado no puede ser negativo", True)
    if valores["max_iter"] <= 0:
        return ("❌ El máximo de iteraciones debe ser mayor que 0", True)

    # 4) Rangos de SubStock fila por fila.
    for r in rangos:
        jaula = r.get("jaula")
        min_txt = str(r.get("min", "")).strip()
        max_txt = str(r.get("max", "")).strip()
        if min_txt == "" or max_txt == "":
            return (f"⚠ Campo requerido: límites de la jaula {jaula}", True)
        try:
            hasta = _a_numero(min_txt)   # 'Desde (mín)' UI = hasta interno
            desde = _a_numero(max_txt)   # 'Hasta (máx)' UI = desde interno
        except ValueError:
            return (f"❌ Valor inválido en los límites de la jaula {jaula} (debe ser número)", True)
        if desde <= hasta:
            return (f"❌ Rango inválido en jaula {jaula}: 'Hasta' debe ser mayor que 'Desde'", True)

    # 5) Cantidad de filas de rango vs cantidad de jaulas.
    r_n = len(rangos)
    if r_n != jaulas:
        return (f"⚠ Falta(n) rango(s): hay {r_n} de {jaulas} jaulas", True)

    # 6) Máquinas rectificadoras (si se proporcionan).
    if maquinas is not None:
        if not maquinas:
            return ("⚠ Debe definir al menos una máquina", True)
        nombres_vistos: set = set()
        _CAMPOS_TASA = ("prod_mm", "prod_min", "desb_mm", "desb_min")
        _ETIQUETAS_TASA = {
            "prod_mm": "Prod mm", "prod_min": "Prod min",
            "desb_mm": "Desb mm", "desb_min": "Desb min",
        }
        for idx, m in enumerate(maquinas, 1):
            nombre = str(m.get("nombre", "")).strip()
            valores_tasa = [str(m.get(c, "")).strip() for c in _CAMPOS_TASA]
            tiene_datos = nombre or any(valores_tasa)
            if not tiene_datos:
                continue
            if not nombre:
                return (f"❌ Máquina {idx}: falta el nombre", True)
            if nombre in nombres_vistos:
                return (f"❌ Nombre de máquina repetido: '{nombre}'", True)
            nombres_vistos.add(nombre)
            for campo, txt in zip(_CAMPOS_TASA, valores_tasa):
                if txt == "":
                    return (f"⚠ Máquina '{nombre}': campo {_ETIQUETAS_TASA[campo]} requerido", True)
                try:
                    val = _a_numero(txt)
                except ValueError:
                    return (f"❌ Máquina '{nombre}': {_ETIQUETAS_TASA[campo]} no es un número válido", True)
                if val <= 0:
                    return (f"❌ Máquina '{nombre}': {_ETIQUETAS_TASA[campo]} debe ser mayor que 0", True)

    return ("✓ Configuración válida — recuerde Guardar", False)
