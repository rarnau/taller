"""Helpers GUI-free para editar el stock inicial (hoja ``Stock_Inicial``).

Única fuente de los nombres de columna del contrato Excel (con acentos) y de
las reglas de validación que la GUI aplica ANTES de mutar el DataFrame. Las
reglas duras del motor siguen viviendo en ``TallerCilindros._cargar_stock``
(que re-valida todo al construir el taller); acá solo se espejan para avisar
al usuario en el momento de la edición, no para reemplazarlas.

Los helpers CRUD devuelven siempre un DataFrame NUEVO (no mutan el argumento):
el owner del ``stock_df`` es quien llama (en la GUI, ``MainWindow``).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from config.persistencia import obtener_config_global
from modelos.enums import EstadoCilindro, TipoRectificado

# ── Contrato de columnas del Excel (ver modelos/taller.py::_cargar_stock /
#    _cargar_cambios). Los acentos son parte del contrato: no re-tipearlos. ──
COL_ID = "ID_Cilindro"
COL_DIAMETRO = "Diámetro_mm"
COL_ESTADO = "Estado"
COL_JAULA = "Jaula_Asignada"
COL_POSICION = "Posición"
COL_PERFIL = "Perfil"
COL_MM = "mm_a_Rectificar"
COL_TIPO = "Tipo_Rectificado"

COLUMNAS_STOCK = [
    COL_ID, COL_DIAMETRO, COL_ESTADO, COL_JAULA,
    COL_POSICION, COL_PERFIL, COL_MM, COL_TIPO,
]

COLUMNAS_CAMBIOS = [
    "ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
    "mm_a_Rectificar", "Observación",
]

# Estados en los que el motor consume mm_a_Rectificar / Tipo_Rectificado.
_ESTADOS_CON_PASE = (EstadoCilindro.A_RECTIFICAR.value, EstadoCilindro.RECTIFICANDO.value)


def _es_vacio(valor: Any) -> bool:
    """True para None, NaN o string en blanco (celda vacía de Excel)."""
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return isinstance(valor, str) and valor.strip() == ""


def validar_fila_stock(
    fila: Dict[str, Any],
    cfg: Dict[str, Any],
    ids_existentes: Set[str],
    id_original: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """Valida una fila candidata del stock. Devuelve ``(errores, avisos)``.

    Los errores bloquean la operación; los avisos espejan lo que el motor
    haría al cargar (BAJA por diámetro, reclasificaciones) para que el usuario
    confirme con conocimiento. ``id_original`` excluye el propio ID del check
    de duplicado al editar.
    """
    errores: List[str] = []
    avisos: List[str] = []
    cg = obtener_config_global(cfg)
    diametro_minimo = float(cg["diametro_minimo"])
    cantidad_jaulas = int(cg["cantidad_jaulas"])

    id_cil = str(fila.get(COL_ID, "") or "").strip()
    if not id_cil:
        errores.append("El ID del cilindro no puede estar vacío.")
    else:
        otros = ids_existentes - ({str(id_original)} if id_original is not None else set())
        if id_cil in otros:
            errores.append(f"Ya existe un cilindro con ID '{id_cil}'.")

    diametro = fila.get(COL_DIAMETRO)
    try:
        diametro = float(diametro)
        if math.isnan(diametro):
            raise ValueError
    except (TypeError, ValueError):
        errores.append("El diámetro debe ser un número.")
        diametro = None
    if diametro is not None and diametro <= 0:
        errores.append("El diámetro debe ser mayor que 0.")

    estado = str(fila.get(COL_ESTADO, "") or "")
    estados_validos = {e.value for e in EstadoCilindro}
    if estado not in estados_validos:
        errores.append(
            f"Estado inválido '{estado}'. Válidos: {', '.join(sorted(estados_validos))}."
        )

    jaula = fila.get(COL_JAULA)
    if not _es_vacio(jaula):
        try:
            jaula = int(jaula)
            if not 1 <= jaula <= cantidad_jaulas:
                errores.append(
                    f"Jaula {jaula} fuera de rango (1-{cantidad_jaulas})."
                )
        except (TypeError, ValueError):
            errores.append("La jaula debe ser un entero.")
    else:
        jaula = None

    posicion = fila.get(COL_POSICION)
    if not _es_vacio(posicion):
        try:
            posicion = int(posicion)
        except (TypeError, ValueError):
            posicion = -1
        if posicion not in (1, 2):
            errores.append("La posición debe ser 1 o 2 (o quedar vacía).")

    tipo = fila.get(COL_TIPO)
    if not _es_vacio(tipo):
        tipos_validos = {t.value for t in TipoRectificado}
        if str(tipo) not in tipos_validos:
            errores.append(
                f"Tipo de rectificado inválido '{tipo}'. Válidos: {', '.join(sorted(tipos_validos))}."
            )

    mm = fila.get(COL_MM)
    if not _es_vacio(mm):
        try:
            if float(mm) < 0:
                errores.append("Los mm a rectificar no pueden ser negativos.")
        except (TypeError, ValueError):
            errores.append("Los mm a rectificar deben ser un número.")

    # ── Avisos: espejo de lo que _cargar_stock hará con la fila ──
    if diametro is not None and estado in estados_validos:
        if estado != EstadoCilindro.BAJA.value and diametro < diametro_minimo:
            avisos.append(
                f"Diámetro {diametro:.1f} < mínimo {diametro_minimo:.1f}: "
                "el motor lo marcará BAJA al cargar."
            )
        if estado == EstadoCilindro.BAJA.value and diametro >= diametro_minimo:
            avisos.append(
                "Estado Baja con diámetro sobre el mínimo: se respetará, "
                "pero el motor emitirá un aviso al cargar."
            )
    if estado in (EstadoCilindro.TRABAJANDO.value, EstadoCilindro.CRC.value) and jaula is None:
        avisos.append(f"Estado {estado} sin jaula asignada.")
    if estado == EstadoCilindro.RECTIFICANDO.value:
        avisos.append("Estado Rectificando se degrada a 'A rectificar' al cargar.")

    return errores, avisos


def _normalizar_fila(fila: Dict[str, Any]) -> Dict[str, Any]:
    """Ajusta la fila al contrato: NaN en opcionales vacíos y en mm/Tipo
    cuando el estado no los consume."""
    limpia: Dict[str, Any] = dict(fila)
    limpia[COL_ID] = str(fila.get(COL_ID, "")).strip()
    limpia[COL_DIAMETRO] = float(fila[COL_DIAMETRO])
    estado = str(fila.get(COL_ESTADO, ""))
    limpia[COL_ESTADO] = estado

    for col in (COL_JAULA, COL_POSICION):
        valor = fila.get(col)
        limpia[col] = float("nan") if _es_vacio(valor) else int(valor)

    perfil = fila.get(COL_PERFIL)
    limpia[COL_PERFIL] = float("nan") if _es_vacio(perfil) else str(perfil).strip()

    if estado in _ESTADOS_CON_PASE:
        mm = fila.get(COL_MM)
        limpia[COL_MM] = float("nan") if _es_vacio(mm) else float(mm)
        tipo = fila.get(COL_TIPO)
        limpia[COL_TIPO] = float("nan") if _es_vacio(tipo) else str(tipo)
    else:
        limpia[COL_MM] = float("nan")
        limpia[COL_TIPO] = float("nan")
    return limpia


def _df_base(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_STOCK)
    return df


def _mascara_id(df: pd.DataFrame, id_cilindro: str) -> pd.Series:
    return df[COL_ID].astype(str) == str(id_cilindro)


def agregar_fila_stock(df: Optional[pd.DataFrame], fila: Dict[str, Any]) -> pd.DataFrame:
    """Devuelve un DataFrame nuevo con la fila agregada al final.

    Preserva las columnas extra que trajera el Excel original (quedan NaN en
    la fila nueva) y agrega al df las columnas del contrato que le faltaran.
    """
    base = _df_base(df)
    fila_df = pd.DataFrame([_normalizar_fila(fila)])
    return pd.concat([base, fila_df], ignore_index=True)


def actualizar_fila_stock(
    df: pd.DataFrame, id_original: str, fila: Dict[str, Any]
) -> pd.DataFrame:
    """Devuelve un DataFrame nuevo con la fila de ``id_original`` reemplazada.

    Solo cambia las columnas del contrato presentes en ``fila``; las columnas
    extra del Excel original conservan su valor en esa fila.
    """
    nuevo = df.copy()
    mask = _mascara_id(nuevo, id_original)
    if not mask.any():
        raise KeyError(f"No existe un cilindro con ID '{id_original}' en el stock.")
    limpia = _normalizar_fila(fila)
    for col, valor in limpia.items():
        if col not in nuevo.columns:
            nuevo[col] = float("nan")
        nuevo.loc[mask, col] = valor
    return nuevo


def eliminar_fila_stock(df: pd.DataFrame, id_cilindro: str) -> pd.DataFrame:
    """Devuelve un DataFrame nuevo sin la fila de ``id_cilindro``."""
    mask = _mascara_id(df, id_cilindro)
    if not mask.any():
        raise KeyError(f"No existe un cilindro con ID '{id_cilindro}' en el stock.")
    return df.loc[~mask].reset_index(drop=True)


def guardar_stock_excel(
    path: str,
    stock_df: pd.DataFrame,
    cambios_df: Optional[pd.DataFrame] = None,
) -> None:
    """Escribe un .xlsx recargable por el flujo de carga normal.

    Hoja ``Stock_Inicial`` con el DataFrame crudo (contrato completo) y hoja
    ``Programa_Cambios`` con el programa cargado — o vacía con los headers del
    contrato si no hay programa, porque la carga lee ambas hojas siempre.
    """
    if cambios_df is None or cambios_df.empty:
        cambios_df = pd.DataFrame(columns=COLUMNAS_CAMBIOS)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        stock_df.to_excel(writer, sheet_name="Stock_Inicial", index=False)
        cambios_df.to_excel(writer, sheet_name="Programa_Cambios", index=False)
