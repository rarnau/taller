"""Tests del factor de escala por DPI (módulo puro, headless)."""
from gui.dpi import factor_escala_dpi


def test_dpi_estandar_no_escala():
    assert factor_escala_dpi(96.0) == 1.0


def test_dpi_alto_escala():
    assert factor_escala_dpi(144.0) == 1.5  # 150%


def test_clamp_maximo():
    assert factor_escala_dpi(400.0, maximo=2.0) == 2.0


def test_clamp_minimo_y_dpi_invalido():
    assert factor_escala_dpi(48.0) == 1.0   # nunca por debajo del mínimo
    assert factor_escala_dpi(0) == 1.0
    assert factor_escala_dpi(None) == 1.0
