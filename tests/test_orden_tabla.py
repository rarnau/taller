"""Tests headless del ordenamiento type-aware de la tabla de Inventario."""
from gui.orden_tabla import ordenar_filas, _es_numerico, _a_float

_COLS = ("ID", "Diámetro", "Estado")


def _ids(filas):
    return [f[0] for f in filas]


def test_orden_numerico_ascendente():
    filas = [("A", "550.0", "x"), ("B", "547.0", "y"), ("C", "561.0", "z")]
    out = ordenar_filas(_COLS, filas, "Diámetro", desc=False)
    assert _ids(out) == ["B", "A", "C"]


def test_orden_numerico_descendente():
    filas = [("A", "550.0", "x"), ("B", "547.0", "y"), ("C", "561.0", "z")]
    out = ordenar_filas(_COLS, filas, "Diámetro", desc=True)
    assert _ids(out) == ["C", "A", "B"]


def test_placeholders_al_final_en_ascendente():
    filas = [("A", "550.0", "x"), ("B", "-", "y"), ("C", "547.0", "z"), ("D", "", "w")]
    out = ordenar_filas(_COLS, filas, "Diámetro", desc=False)
    # Numéricos ordenados, placeholders ("-"/"") al final.
    assert _ids(out[:2]) == ["C", "A"]
    assert set(_ids(out[2:])) == {"B", "D"}


def test_columna_no_numerica_alfabetico_case_insensitive():
    filas = [("A", "1", "banana"), ("B", "2", "Apple"), ("C", "3", "cherry")]
    out = ordenar_filas(_COLS, filas, "Estado", desc=False)
    assert _ids(out) == ["B", "A", "C"]


def test_sort_col_none_devuelve_copia_sin_cambios():
    filas = [("A", "2", "x"), ("B", "1", "y")]
    out = ordenar_filas(_COLS, filas, None, desc=False)
    assert out == filas
    assert out is not filas  # lista nueva


def test_sort_col_inexistente_devuelve_copia():
    filas = [("A", "2", "x"), ("B", "1", "y")]
    out = ordenar_filas(_COLS, filas, "NoExiste", desc=True)
    assert out == filas
    assert out is not filas


def test_es_numerico():
    assert _es_numerico("550.0")
    assert _es_numerico("-")      # placeholder
    assert _es_numerico("")       # placeholder
    assert _es_numerico(" 12 ")
    assert not _es_numerico("abc")


def test_a_float():
    assert _a_float("550.0") == 550.0
    assert _a_float("-") == float("inf")
    assert _a_float("") == float("inf")
    assert _a_float("abc") == float("inf")
