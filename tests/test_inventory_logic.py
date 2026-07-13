"""Tests de la lógica pura de orden/filtro del Inventario (gui_qt/inventory_logic.py).

El módulo no importa Qt, así que se testea headless como cualquier otro.
"""
from gui_qt.inventory_logic import filtrar_registros, ordenar_registros


def _regs():
    return [
        {"id": "CIL-010", "diametro": 560.0, "original": 570.0, "desgaste": -10.0,
         "estado": "Disponible", "jaula": None},
        {"id": "cil-002", "diametro": 574.0, "original": 574.0, "desgaste": 0.0,
         "estado": "Trabajando", "jaula": 2},
        {"id": "CIL-001", "diametro": 530.0, "original": 566.0, "desgaste": -36.0,
         "estado": "Baja", "jaula": None},
        {"id": "CIL-003", "diametro": 555.0, "original": 560.0, "desgaste": -5.0,
         "estado": "Trabajando", "jaula": 1},
    ]


# ── ordenar_registros ────────────────────────────────────────────────────────

def test_orden_numerico_asc_desc():
    ids_asc = [r["id"] for r in ordenar_registros(_regs(), "diametro", False)]
    assert ids_asc == ["CIL-001", "CIL-003", "CIL-010", "cil-002"]
    ids_desc = [r["id"] for r in ordenar_registros(_regs(), "diametro", True)]
    assert ids_desc == ["cil-002", "CIL-010", "CIL-003", "CIL-001"]


def test_orden_texto_case_insensitive():
    ids = [r["id"] for r in ordenar_registros(_regs(), "id", False)]
    assert ids == ["CIL-001", "cil-002", "CIL-003", "CIL-010"]


def test_orden_jaula_none_al_final_en_ambas_direcciones():
    asc = [r["jaula"] for r in ordenar_registros(_regs(), "jaula", False)]
    assert asc == [1, 2, None, None]
    desc = [r["jaula"] for r in ordenar_registros(_regs(), "jaula", True)]
    assert desc == [2, 1, None, None]


def test_orden_no_muta_original():
    regs = _regs()
    copia = [r["id"] for r in regs]
    ordenar_registros(regs, "diametro", True)
    assert [r["id"] for r in regs] == copia


def test_orden_estable_en_empates():
    regs = _regs()
    por_estado = ordenar_registros(regs, "estado", False)
    trabajando = [r["id"] for r in por_estado if r["estado"] == "Trabajando"]
    assert trabajando == ["cil-002", "CIL-003"]  # orden de entrada preservado


# ── filtrar_registros ────────────────────────────────────────────────────────

def test_filtro_texto_id_case_insensitive():
    ids = [r["id"] for r in filtrar_registros(_regs(), texto_id="cil-0")]
    assert len(ids) == 4  # substring en todos
    ids = [r["id"] for r in filtrar_registros(_regs(), texto_id="002")]
    assert ids == ["cil-002"]


def test_filtro_estado():
    ids = [r["id"] for r in filtrar_registros(_regs(), estado="Trabajando")]
    assert ids == ["cil-002", "CIL-003"]


def test_filtro_jaula_exacta_y_sin_jaula():
    assert [r["id"] for r in filtrar_registros(_regs(), jaula=1)] == ["CIL-003"]
    ids_sin = [r["id"] for r in filtrar_registros(_regs(), jaula="sin")]
    assert ids_sin == ["CIL-010", "CIL-001"]


def test_filtro_rango_diametro_cero_sin_limite():
    assert len(filtrar_registros(_regs(), diametro_min=0, diametro_max=0)) == 4
    ids = [r["id"] for r in filtrar_registros(_regs(), diametro_min=555.0)]
    assert ids == ["CIL-010", "cil-002", "CIL-003"]
    ids = [r["id"] for r in filtrar_registros(_regs(), diametro_max=555.0)]
    assert ids == ["CIL-001", "CIL-003"]


def test_filtros_componen_con_and():
    ids = [
        r["id"]
        for r in filtrar_registros(
            _regs(), texto_id="cil", estado="Trabajando", diametro_min=560.0
        )
    ]
    assert ids == ["cil-002"]


def test_sin_filtros_devuelve_todo():
    assert filtrar_registros(_regs()) == _regs()
