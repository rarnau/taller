"""Filtro por jaula del Dashboard (evolución de estados + buffer).

El adaptador ``extraer_datos_dashboard`` expone series por jaula con
**atribución única** (``Snapshot.conteo_estado_por_jaula``), de modo que la
suma sobre jaulas de cada estado (los no-BAJA, que sí tienen jaula) coincide
con el conteo global — sin duplicar cilindros aun con bandas solapadas.
"""
from datetime import datetime

import pandas as pd

from gui_qt.dashboard_data import extraer_datos_dashboard
from modelos.enums import EstadoCilindro
from modelos.taller import TallerCilindros

_COLS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
         "mm_a_Rectificar", "Observación"]


def _cfg(cantidad, rangos):
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": cantidad},
        "rangos": rangos,
        "maquinas": [{"nombre": "G", "prioridad": "produccion",
                      "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                                "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}],
    }


def _fila(cid, d, estado="Disponible", jaula=None, pos=None):
    return {"ID_Cilindro": cid, "Diámetro_mm": d, "Estado": estado,
            "Jaula_Asignada": jaula, "Posición": pos}


def _cambio(jaula=1, hora=datetime(2026, 7, 6, 8, 0)):
    return {"ID_Cambio": f"C{jaula}", "Fecha_Hora": hora, "Jaula": jaula,
            "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 1.0, "Observación": ""}


def _taller(cfg, stock, cambios=None):
    # Sin cambios el motor no genera snapshots; se garantiza al menos uno.
    cambios = list(cambios) if cambios else [_cambio()]
    t = TallerCilindros()
    t.configurar(cfg)
    t.cargar_datos_desde_dataframes(pd.DataFrame(stock), pd.DataFrame(cambios, columns=_COLS))
    t.simular(callback_log=None)
    return t


def test_series_por_jaula_suman_el_global_sin_bajas():
    """Para cada estado no-BAJA y cada snapshot, la suma sobre jaulas de las
    series por jaula == la serie global (atribución única, sin duplicar)."""
    cfg = _cfg(2, [{"jaula": 1, "desde": 547.0, "hasta": 520.0},
                   {"jaula": 2, "desde": 575.0, "hasta": 547.0}])
    stock = [_fila("W1", 540.0, "Trabajando", 1, 1), _fila("W2", 540.0, "Trabajando", 1, 2),
             _fila("W3", 560.0, "Trabajando", 2, 1), _fila("W4", 560.0, "Trabajando", 2, 2),
             _fila("D1", 545.0), _fila("D2", 560.0), _fila("D3", 570.0)]
    cambios = [{"ID_Cambio": "C1", "Fecha_Hora": datetime(2026, 7, 6, 8, 0), "Jaula": 1,
                "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 1.0, "Observación": ""}]
    d = extraer_datos_dashboard(_taller(cfg, stock, cambios))

    assert d.jaulas == [1, 2]
    baja = EstadoCilindro.BAJA.value
    n = len(d.tiempos)
    for estado in d.estados:
        if estado == baja:
            continue  # los BAJA no se atribuyen a una jaula (van a "sin banda")
        for i in range(n):
            suma = sum(d.series_estado_por_jaula[j][estado][i] for j in d.jaulas)
            assert suma == d.series_estado[estado][i], f"{estado}@{i}"


def test_buffer_por_jaula_desde_conteo_unico():
    """Disponible/CRC por jaula salen de conteo_estado_por_jaula y su suma es el
    global (todos los Disponibles/CRC son no-BAJA ⇒ atribuidos a una jaula)."""
    cfg = _cfg(2, [{"jaula": 1, "desde": 547.0, "hasta": 520.0},
                   {"jaula": 2, "desde": 575.0, "hasta": 547.0}])
    stock = [_fila("W1", 540.0, "Trabajando", 1, 1), _fila("W2", 540.0, "Trabajando", 1, 2),
             _fila("W3", 560.0, "Trabajando", 2, 1), _fila("W4", 560.0, "Trabajando", 2, 2),
             _fila("D1", 545.0), _fila("D2", 546.0), _fila("D3", 560.0), _fila("D4", 570.0)]
    d = extraer_datos_dashboard(_taller(cfg, stock))
    disp = EstadoCilindro.DISPONIBLE.value
    for i in range(len(d.tiempos)):
        suma = sum(d.series_estado_por_jaula[j].get(disp, [0])[i] for j in d.jaulas)
        assert suma == d.disponibles[i], f"disponibles@{i}"


def test_bandas_solapadas_no_duplican():
    """Con J2 y J3 de banda idéntica (solape total), un cilindro cuenta en UNA
    sola (la de menor nº): la suma por jaula sigue siendo el global."""
    cfg = _cfg(3, [{"jaula": 1, "desde": 540.0, "hasta": 520.0},
                   {"jaula": 2, "desde": 575.0, "hasta": 540.0},
                   {"jaula": 3, "desde": 575.0, "hasta": 540.0}])  # = banda J2
    stock = [_fila("W1", 530.0, "Trabajando", 1, 1), _fila("W2", 530.0, "Trabajando", 1, 2),
             _fila("W3", 560.0, "Trabajando", 2, 1), _fila("W4", 560.0, "Trabajando", 2, 2),
             _fila("W5", 560.0, "Trabajando", 3, 1), _fila("W6", 560.0, "Trabajando", 3, 2),
             _fila("D1", 555.0), _fila("D2", 565.0)]
    d = extraer_datos_dashboard(_taller(cfg, stock))
    disp = EstadoCilindro.DISPONIBLE.value
    for i in range(len(d.tiempos)):
        suma = sum(d.series_estado_por_jaula[j].get(disp, [0])[i] for j in d.jaulas)
        assert suma == d.disponibles[i], f"disponibles@{i}"
