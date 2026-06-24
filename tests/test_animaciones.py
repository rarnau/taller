"""Tests de la matemática pura de animación (interpolación de alpha)."""
from gui.animaciones import pasos_alpha


def test_termina_en_fin():
    vals = pasos_alpha(0.0, 1.0, 10)
    assert len(vals) == 10
    assert vals[-1] == 1.0
    assert vals[0] > 0.0  # no incluye el inicio (0.0)


def test_monotona_creciente():
    vals = pasos_alpha(0.0, 1.0, 12)
    assert all(b > a for a, b in zip(vals, vals[1:]))


def test_n_minimo():
    assert pasos_alpha(0.0, 1.0, 0) == [1.0]
    assert pasos_alpha(0.0, 1.0, 1) == [1.0]
