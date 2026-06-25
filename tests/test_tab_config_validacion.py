"""Tests de la lógica de validación en vivo de la pestaña Configuración.

Importa SOLO la función pura ``_estado_validacion`` desde ``gui.validacion_config``
(ese módulo no importa customtkinter, así que el test corre sin tkinter).
"""
from gui.validacion_config import _estado_validacion


def _globales_validos():
    return {
        "diam_max": "575", "diam_min": "520", "crc": "10",
        "jaulas": "2", "enfriado": "0", "max_iter": "10000",
    }


def _rangos_validos():
    return [
        {"jaula": 1, "min": "520", "max": "547", "perfil": ""},
        {"jaula": 2, "min": "547", "max": "575", "perfil": ""},
    ]


def test_caso_valido():
    msg, es_error = _estado_validacion(_globales_validos(), _rangos_validos())
    assert es_error is False
    assert msg.startswith("✓")


def test_campo_requerido_vacio():
    g = _globales_validos()
    g["diam_max"] = ""
    msg, es_error = _estado_validacion(g, _rangos_validos())
    assert es_error is True
    assert msg.startswith("⚠")
    assert "requerido" in msg.lower()


def test_diam_max_menor_o_igual_min():
    g = _globales_validos()
    g["diam_max"] = "520"
    g["diam_min"] = "520"
    msg, es_error = _estado_validacion(g, _rangos_validos())
    assert es_error is True
    assert msg.startswith("❌")


def test_rango_invalido_desde_mayor_o_igual_hasta():
    rangos = _rangos_validos()
    # 'Hasta' (max) <= 'Desde' (min) en jaula 1.
    rangos[0]["min"] = "550"
    rangos[0]["max"] = "540"
    msg, es_error = _estado_validacion(_globales_validos(), rangos)
    assert es_error is True
    assert msg.startswith("❌")
    assert "jaula 1" in msg.lower()


def test_cantidad_rangos_distinta_de_jaulas():
    g = _globales_validos()
    g["jaulas"] = "3"  # hay 2 filas de rango, faltan
    msg, es_error = _estado_validacion(g, _rangos_validos())
    assert es_error is True
    assert msg.startswith("⚠")


# ── Validación de máquinas ───────────────────────────────────────────────

def _maquinas_validas():
    return [
        {"nombre": "G36", "prod_mm": "0.3", "prod_min": "45",
         "desb_mm": "1.0", "desb_min": "60"},
    ]


def test_maquinas_caso_valido():
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), _maquinas_validas())
    assert es_error is False
    assert msg.startswith("✓")


def test_maquinas_sin_maquinas():
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), [])
    assert es_error is True
    assert "máquina" in msg.lower()


def test_maquinas_sin_nombre():
    maq = _maquinas_validas()
    maq[0]["nombre"] = ""
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is True
    assert "nombre" in msg.lower()


def test_maquinas_nombre_repetido():
    maq = _maquinas_validas() + _maquinas_validas()
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is True
    assert "repetido" in msg.lower()


def test_maquinas_tasa_vacia():
    maq = _maquinas_validas()
    maq[0]["prod_mm"] = ""
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is True
    assert "prod mm" in msg.lower()


def test_maquinas_tasa_no_numerica():
    maq = _maquinas_validas()
    maq[0]["desb_min"] = "abc"
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is True
    assert "desb min" in msg.lower()


def test_maquinas_tasa_negativa():
    maq = _maquinas_validas()
    maq[0]["prod_min"] = "-5"
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is True
    assert "mayor que 0" in msg.lower()


def test_maquinas_tasa_cero():
    maq = _maquinas_validas()
    maq[0]["desb_mm"] = "0"
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is True
    assert "mayor que 0" in msg.lower()


def test_maquinas_none_retrocompat():
    """Sin pasar maquinas (None) se mantiene la validación original."""
    msg, es_error = _estado_validacion(_globales_validos(), _rangos_validos())
    assert es_error is False
    assert msg.startswith("✓")


def test_maquinas_fila_vacia_se_ignora():
    maq = _maquinas_validas() + [
        {"nombre": "", "prod_mm": "", "prod_min": "", "desb_mm": "", "desb_min": ""}
    ]
    msg, es_error = _estado_validacion(
        _globales_validos(), _rangos_validos(), maq)
    assert es_error is False
