"""La distribución de diámetros del panel Análisis varía con el snapshot.

``extraer_datos_analisis`` expone ahora ``dist_bins_por_snapshot`` (un
histograma por snapshot, reconstruido del mismo mapa que ya varía con el
timeline) con **bordes fijos** (mismos bins en cada foto, así las barras no
saltan) y un ``dist_max_count`` global (para escalar alturas comparables).
"""
from datetime import datetime

import pandas as pd

from gui_qt import analysis_data as ad
from modelos.enums import EstadoCilindro
from modelos.taller import TallerCilindros

_COLS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
         "mm_a_Rectificar", "Observación"]


def _cfg():
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 520.0}],
        "maquinas": [{"nombre": "G", "prioridad": "produccion",
                      "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                                "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}],
    }


def _stock():
    return pd.DataFrame([
        {"ID_Cilindro": "W1", "Diámetro_mm": 560.0, "Estado": "Trabajando",
         "Jaula_Asignada": 1, "Posición": 1},
        {"ID_Cilindro": "W2", "Diámetro_mm": 560.0, "Estado": "Trabajando",
         "Jaula_Asignada": 1, "Posición": 2},
        {"ID_Cilindro": "D1", "Diámetro_mm": 555.0, "Estado": "Disponible",
         "Jaula_Asignada": 1, "Posición": 0},
        {"ID_Cilindro": "D2", "Diámetro_mm": 548.0, "Estado": "Disponible",
         "Jaula_Asignada": 1, "Posición": 0},
    ])


def _cambios():
    return pd.DataFrame([
        {"ID_Cambio": "C1", "Fecha_Hora": datetime(2026, 7, 6, 8, 0), "Jaula": 1,
         "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 3.0, "Observación": ""},
    ], columns=_COLS)


def _data():
    t = TallerCilindros()
    t.configurar(_cfg())
    t.cargar_datos_desde_dataframes(_stock(), _cambios())
    t.simular(callback_log=None)
    return t, ad.extraer_datos_analisis(t, _stock())


def test_hay_un_histograma_por_snapshot():
    t, data = _data()
    assert len(data.dist_bins_por_snapshot) == len(t.snapshots)
    assert len(data.dist_bins_por_snapshot) > 1  # el escenario tiene varios


def test_bordes_de_bins_fijos_entre_snapshots():
    """Todas las fotos comparten exactamente los mismos bordes de bin."""
    _, data = _data()
    ref = [(b.left, b.right) for b in data.dist_bins_por_snapshot[0]]
    for bins in data.dist_bins_por_snapshot:
        assert [(b.left, b.right) for b in bins] == ref


def test_la_distribucion_varia_con_el_snapshot():
    """Al menos dos snapshots tienen conteos distintos (si no, no 'varía')."""
    _, data = _data()
    firmas = {tuple(b.count for b in bins) for bins in data.dist_bins_por_snapshot}
    assert len(firmas) > 1


def test_max_count_global_y_ultimo_coincide_con_dist_bins():
    _, data = _data()
    # dist_max_count es el máximo sobre todos los bins de todos los snapshots.
    real = max(b.count for bins in data.dist_bins_por_snapshot for b in bins)
    assert data.dist_max_count == real
    # dist_bins (fallback) == última foto, con los mismos bordes.
    assert [(b.left, b.right, b.count) for b in data.dist_bins] == \
           [(b.left, b.right, b.count) for b in data.dist_bins_por_snapshot[-1]]


def test_conteo_por_snapshot_son_los_activos():
    """La suma de conteos de cada foto = nº de cilindros no-BAJA en esa foto
    (según el mapa por snapshot, misma fuente que el mapa de cilindros)."""
    _, data = _data()
    baja = EstadoCilindro.BAJA.value
    for i, bins in enumerate(data.dist_bins_por_snapshot):
        activos = sum(1 for (_d, est) in data.mapa_puntos_por_snapshot[i] if est != baja)
        assert sum(b.count for b in bins) == activos
