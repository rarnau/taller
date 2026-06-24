from gui.mpl_zoom import _nuevos_limites
def test_zoom_in_centrado():
    lo, hi = _nuevos_limites((0.0, 10.0), 5.0, 0.5)
    assert (lo, hi) == (2.5, 7.5)
def test_zoom_out_centrado():
    lo, hi = _nuevos_limites((0.0, 10.0), 5.0, 2.0)
    assert (lo, hi) == (-5.0, 15.0)
def test_centro_desplazado():
    lo, hi = _nuevos_limites((0.0, 10.0), 0.0, 0.5)
    assert (lo, hi) == (0.0, 5.0)
