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
