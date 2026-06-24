"""Tests de la utilidad pura del timeline (mapeo tiempo → índice de snapshot)."""
from datetime import datetime

from gui.timeline_util import indice_tiempo_mas_cercano


def test_lista_vacia():
    assert indice_tiempo_mas_cercano([], datetime(2025, 1, 1)) is None


def test_mas_cercano():
    ts = [datetime(2025, 1, 1, 0), datetime(2025, 1, 1, 12), datetime(2025, 1, 2, 0)]
    assert indice_tiempo_mas_cercano(ts, datetime(2025, 1, 1, 10)) == 1
    assert indice_tiempo_mas_cercano(ts, datetime(2025, 1, 1, 1)) == 0
    assert indice_tiempo_mas_cercano(ts, datetime(2025, 1, 1, 23)) == 2


def test_exacto():
    ts = [datetime(2025, 1, 1, 0), datetime(2025, 1, 1, 12)]
    assert indice_tiempo_mas_cercano(ts, datetime(2025, 1, 1, 12)) == 1
