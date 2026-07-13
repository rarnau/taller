"""Tests de ``nucleo/stock.py``: validación de filas, CRUD sobre el DataFrame
del stock inicial y roundtrip guardar→cargar→construir taller.

La GUI (pestaña Inventario) es una cáscara fina sobre estas funciones puras:
toda la regla editable del stock vive acá y queda cubierta sin display.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from config.persistencia import cargar_config
from nucleo.runner import construir_taller_desde_dataframes
from nucleo.stock import (
    COL_DIAMETRO,
    COL_ESTADO,
    COL_ID,
    COL_JAULA,
    COL_MM,
    COL_PERFIL,
    COL_POSICION,
    COL_TIPO,
    COLUMNAS_CAMBIOS,
    COLUMNAS_STOCK,
    actualizar_fila_stock,
    agregar_fila_stock,
    eliminar_fila_stock,
    guardar_stock_excel,
    validar_fila_stock,
)


@pytest.fixture()
def cfg():
    return cargar_config()  # conftest aísla CONFIG_PATH -> defaults prístinos


def _fila(**kwargs):
    """Fila válida por defecto (Disponible, dentro del rango global 520-575)."""
    base = {
        COL_ID: "CIL-X01",
        COL_DIAMETRO: 560.0,
        COL_ESTADO: "Disponible",
        COL_JAULA: None,
        COL_POSICION: None,
        COL_PERFIL: None,
        COL_MM: None,
        COL_TIPO: None,
    }
    base.update(kwargs)
    return base


def _stock_df():
    return pd.DataFrame(
        [
            {COL_ID: "CIL-001", COL_DIAMETRO: 570.0, COL_ESTADO: "Trabajando",
             COL_JAULA: 1, COL_POSICION: 1},
            {COL_ID: "CIL-002", COL_DIAMETRO: 569.0, COL_ESTADO: "Trabajando",
             COL_JAULA: 1, COL_POSICION: 2},
            {COL_ID: "CIL-003", COL_DIAMETRO: 555.0, COL_ESTADO: "Disponible",
             COL_JAULA: None, COL_POSICION: None},
        ]
    )


# ── validar_fila_stock ───────────────────────────────────────────────────────

def test_fila_valida_sin_errores_ni_avisos(cfg):
    errores, avisos = validar_fila_stock(_fila(), cfg, {"CIL-001"})
    assert errores == []
    assert avisos == []


def test_id_vacio_y_duplicado(cfg):
    errores, _ = validar_fila_stock(_fila(**{COL_ID: "  "}), cfg, set())
    assert any("vacío" in e for e in errores)
    errores, _ = validar_fila_stock(_fila(**{COL_ID: "CIL-001"}), cfg, {"CIL-001"})
    assert any("Ya existe" in e for e in errores)


def test_id_propio_permitido_al_editar(cfg):
    errores, _ = validar_fila_stock(
        _fila(**{COL_ID: "CIL-001"}), cfg, {"CIL-001", "CIL-002"}, id_original="CIL-001"
    )
    assert errores == []


def test_diametro_invalido(cfg):
    for malo in (None, "abc", float("nan"), 0, -3.0):
        errores, _ = validar_fila_stock(_fila(**{COL_DIAMETRO: malo}), cfg, set())
        assert errores, f"esperaba error para diámetro {malo!r}"


def test_estado_invalido(cfg):
    errores, _ = validar_fila_stock(_fila(**{COL_ESTADO: "Volando"}), cfg, set())
    assert any("Estado inválido" in e for e in errores)


def test_jaula_fuera_de_rango(cfg):
    errores, _ = validar_fila_stock(_fila(**{COL_JAULA: 99}), cfg, set())
    assert any("fuera de rango" in e for e in errores)
    errores, _ = validar_fila_stock(_fila(**{COL_JAULA: 0}), cfg, set())
    assert any("fuera de rango" in e for e in errores)


def test_posicion_tipo_y_mm_invalidos(cfg):
    errores, _ = validar_fila_stock(_fila(**{COL_POSICION: 3}), cfg, set())
    assert any("posición" in e.lower() for e in errores)
    errores, _ = validar_fila_stock(
        _fila(**{COL_ESTADO: "A rectificar", COL_TIPO: "pulido"}), cfg, set()
    )
    assert any("Tipo de rectificado inválido" in e for e in errores)
    errores, _ = validar_fila_stock(
        _fila(**{COL_ESTADO: "A rectificar", COL_MM: -1.0}), cfg, set()
    )
    assert any("mm" in e for e in errores)


def test_avisos_espejan_al_motor(cfg):
    # Diámetro bajo el mínimo (520) => el motor lo marcará BAJA.
    _, avisos = validar_fila_stock(_fila(**{COL_DIAMETRO: 500.0}), cfg, set())
    assert any("BAJA" in a for a in avisos)
    # Trabajando sin jaula.
    _, avisos = validar_fila_stock(_fila(**{COL_ESTADO: "Trabajando"}), cfg, set())
    assert any("sin jaula" in a for a in avisos)
    # BAJA sobre el mínimo.
    _, avisos = validar_fila_stock(_fila(**{COL_ESTADO: "Baja"}), cfg, set())
    assert any("sobre el mínimo" in a for a in avisos)
    # Rectificando se degrada al cargar.
    _, avisos = validar_fila_stock(_fila(**{COL_ESTADO: "Rectificando"}), cfg, set())
    assert any("degrada" in a for a in avisos)
    # Ninguno bloquea.
    for fila in (_fila(**{COL_DIAMETRO: 500.0}), _fila(**{COL_ESTADO: "Baja"})):
        errores, _ = validar_fila_stock(fila, cfg, set())
        assert errores == []


# ── CRUD sobre el DataFrame ──────────────────────────────────────────────────

def test_agregar_no_muta_y_agrega_al_final():
    df = _stock_df()
    filas_antes = len(df)
    nuevo = agregar_fila_stock(df, _fila())
    assert len(df) == filas_antes  # el original no se muta
    assert len(nuevo) == filas_antes + 1
    assert str(nuevo.iloc[-1][COL_ID]) == "CIL-X01"
    assert nuevo.iloc[-1][COL_DIAMETRO] == 560.0


def test_agregar_sobre_stock_vacio_crea_contrato():
    nuevo = agregar_fila_stock(None, _fila())
    assert list(nuevo.columns) == COLUMNAS_STOCK
    assert len(nuevo) == 1


def test_agregar_preserva_columnas_extra():
    df = _stock_df()
    df["Observaciones_Planta"] = ["a", "b", "c"]
    nuevo = agregar_fila_stock(df, _fila())
    assert "Observaciones_Planta" in nuevo.columns
    assert list(nuevo["Observaciones_Planta"][:3]) == ["a", "b", "c"]
    assert pd.isna(nuevo.iloc[-1]["Observaciones_Planta"])


def test_actualizar_cambia_solo_esa_fila():
    df = _stock_df()
    df["Extra"] = ["x", "y", "z"]
    nuevo = actualizar_fila_stock(df, "CIL-003", _fila(**{COL_ID: "CIL-003", COL_DIAMETRO: 540.0}))
    fila = nuevo[nuevo[COL_ID].astype(str) == "CIL-003"].iloc[0]
    assert fila[COL_DIAMETRO] == 540.0
    assert fila["Extra"] == "z"  # columna extra intacta
    intactas = nuevo[nuevo[COL_ID].astype(str) != "CIL-003"]
    assert list(intactas[COL_DIAMETRO]) == [570.0, 569.0]


def test_actualizar_id_inexistente_lanza():
    with pytest.raises(KeyError):
        actualizar_fila_stock(_stock_df(), "NO-EXISTE", _fila())


def test_eliminar():
    nuevo = eliminar_fila_stock(_stock_df(), "CIL-002")
    assert len(nuevo) == 2
    assert "CIL-002" not in set(nuevo[COL_ID].astype(str))
    with pytest.raises(KeyError):
        eliminar_fila_stock(nuevo, "CIL-002")


def test_mm_y_tipo_nan_segun_estado():
    # Estado sin pase: mm/Tipo se descartan aunque vengan cargados.
    nuevo = agregar_fila_stock(None, _fila(**{COL_MM: 0.5, COL_TIPO: "produccion"}))
    assert pd.isna(nuevo.iloc[0][COL_MM])
    assert pd.isna(nuevo.iloc[0][COL_TIPO])
    # Estado con pase: se conservan.
    nuevo = agregar_fila_stock(
        None, _fila(**{COL_ESTADO: "A rectificar", COL_MM: 0.5, COL_TIPO: "desbaste"})
    )
    assert nuevo.iloc[0][COL_MM] == 0.5
    assert nuevo.iloc[0][COL_TIPO] == "desbaste"


def test_jaula_none_queda_nan():
    nuevo = agregar_fila_stock(None, _fila())
    assert pd.isna(nuevo.iloc[0][COL_JAULA])
    assert pd.isna(nuevo.iloc[0][COL_POSICION])
    nuevo = agregar_fila_stock(None, _fila(**{COL_JAULA: 2, COL_POSICION: 1,
                                              COL_ESTADO: "Trabajando"}))
    assert nuevo.iloc[0][COL_JAULA] == 2
    assert nuevo.iloc[0][COL_POSICION] == 1


# ── Roundtrip guardar → cargar → construir taller ────────────────────────────

def _cambios_df():
    return pd.DataFrame(
        [
            {"ID_Cambio": "CAM-001", "Fecha_Hora": datetime(2026, 6, 1, 8, 0),
             "Jaula": 1, "Tipo_Rectificado": "produccion",
             "mm_a_Rectificar": 0.5, "Observación": "test"},
        ]
    )


def test_roundtrip_con_programa(cfg, tmp_path):
    df = _stock_df()
    df = agregar_fila_stock(df, _fila(**{COL_ID: "CIL-100", COL_DIAMETRO: 566.0}))
    ruta = tmp_path / "stock_editado.xlsx"
    guardar_stock_excel(str(ruta), df, _cambios_df())

    stock = pd.read_excel(ruta, sheet_name="Stock_Inicial")
    cambios = pd.read_excel(ruta, sheet_name="Programa_Cambios")
    assert len(stock) == 4 and len(cambios) == 1

    taller = construir_taller_desde_dataframes(cfg, stock, cambios)
    assert set(taller.cilindros) == {"CIL-001", "CIL-002", "CIL-003", "CIL-100"}
    assert len(taller.eventos_programados) == 1


def test_roundtrip_sin_programa_hoja_vacia_recargable(cfg, tmp_path):
    ruta = tmp_path / "solo_stock.xlsx"
    guardar_stock_excel(str(ruta), _stock_df(), None)

    # La carga de la GUI lee ambas hojas incondicionalmente: deben existir.
    stock = pd.read_excel(ruta, sheet_name="Stock_Inicial")
    cambios = pd.read_excel(ruta, sheet_name="Programa_Cambios")
    assert list(cambios.columns) == COLUMNAS_CAMBIOS
    assert cambios.empty

    taller = construir_taller_desde_dataframes(cfg, stock, cambios)
    assert len(taller.cilindros) == 3
    assert taller.eventos_programados == []


def test_roundtrip_jaula_nan_sobrevive(cfg, tmp_path):
    """Un Disponible sin jaula (NaN) guardado y recargado no rompe la carga."""
    ruta = tmp_path / "nan.xlsx"
    guardar_stock_excel(str(ruta), agregar_fila_stock(None, _fila()), None)
    stock = pd.read_excel(ruta, sheet_name="Stock_Inicial")
    assert np.isnan(stock.iloc[0][COL_JAULA])
    taller = construir_taller_desde_dataframes(
        cfg, stock, pd.read_excel(ruta, sheet_name="Programa_Cambios")
    )
    cil = taller.cilindros["CIL-X01"]
    assert cil.jaula is None
