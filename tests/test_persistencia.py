"""Pruebas de la coherencia jaulas ⇄ rangos de SubStock.

Cubre ``problemas_coherencia`` / ``verificar_coherencia`` de
``config/persistencia.py``: la verificación compartida que usan el CLI (aviso al
editar, error duro antes de simular) y la GUI (error al guardar).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import persistencia as p


def _cfg(n, jaulas):
    """Config mínima con ``n`` jaulas y un rango por cada número en ``jaulas``."""
    return {
        "config_global": {"cantidad_jaulas": n},
        "rangos": [{"jaula": j, "desde": 100 + j, "hasta": 100} for j in jaulas],
    }


def test_coherente_no_tiene_problemas():
    assert p.problemas_coherencia(_cfg(3, [1, 2, 3])) == []
    p.verificar_coherencia(_cfg(3, [1, 2, 3]))  # no lanza


def test_detecta_jaula_faltante():
    problemas = p.problemas_coherencia(_cfg(3, [1, 2]))
    assert len(problemas) == 1 and "3" in problemas[0]


def test_detecta_rango_sobrante():
    problemas = p.problemas_coherencia(_cfg(1, [1, 2]))
    assert len(problemas) == 1 and "2" in problemas[0]


def test_detecta_duplicado():
    problemas = p.problemas_coherencia(_cfg(2, [1, 1, 2]))
    assert any("duplicado" in m.lower() for m in problemas)


def test_cantidad_invalida():
    assert p.problemas_coherencia(_cfg(0, [])) == [
        "La cantidad de jaulas debe ser un entero mayor que 0."
    ]


def test_verificar_lanza_valueerror():
    with pytest.raises(ValueError):
        p.verificar_coherencia(_cfg(2, [1]))


# ── Config del generador de cambios y régimen de turnos ──────────────────────

def test_migrar_rellena_generador_cambios():
    cfg = p.migrar({})  # config vacía
    gc = p.obtener_generador_cambios(cfg)
    assert gc["generador"] == "empirico"
    assert "umbral_desbaste_mm" in gc and "horizonte_dias" in gc


def test_set_generador_cambios():
    cfg = {}
    p.set_generador_cambios(cfg, generador="markov", umbral_desbaste=2.5, horizonte_dias=14)
    gc = p.obtener_generador_cambios(cfg)
    assert gc["generador"] == "markov"
    assert gc["umbral_desbaste_mm"] == 2.5
    assert gc["horizonte_dias"] == 14


def test_set_generador_cambios_fechas():
    cfg = {}
    p.set_generador_cambios(cfg, fecha_inicio="2026-01-05", fecha_fin="2026-01-19")
    gc = p.obtener_generador_cambios(cfg)
    assert gc["fecha_inicio"] == "2026-01-05" and gc["fecha_fin"] == "2026-01-19"
    # cadena vacía limpia la fecha
    p.set_generador_cambios(cfg, fecha_inicio="")
    assert p.obtener_generador_cambios(cfg)["fecha_inicio"] is None


def test_set_generador_cambios_valida():
    with pytest.raises(ValueError):
        p.set_generador_cambios({}, umbral_desbaste=-1)
    with pytest.raises(ValueError):
        p.set_generador_cambios({}, horizonte_dias=0)
    with pytest.raises(ValueError):  # fin <= inicio
        p.set_generador_cambios({}, fecha_inicio="2026-01-19", fecha_fin="2026-01-05")


def test_turnos_cambios_24x7_no_persiste():
    from modelos import turnos as t
    cfg = {"turnos_cambios": {"x": 1}}
    p.set_turnos_cambios(cfg, t.PRESETS["24x7"])  # equivalente a 24/7 ⇒ quita la clave
    assert "turnos_cambios" not in cfg
    assert p.obtener_turnos_cambios(cfg) is None


def test_turnos_cambios_persiste_si_no_es_completo():
    from modelos import turnos as t
    cfg = {}
    turnos = t.parse_compacto("100 100 100 100 100 000 000")
    p.set_turnos_cambios(cfg, turnos)
    assert p.obtener_turnos_cambios(cfg) == turnos
