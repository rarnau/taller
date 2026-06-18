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
