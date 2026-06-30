"""Runner liviano de KPIs para barridos en paralelo (``runner.batch_kpis``).

``batch_kpis`` es la variante liviana de ``batch_simular``: cada worker calcula
``calcular_kpis(taller)`` en su propio proceso y descarta el taller, así que solo
cruza el pickle el dict chico de métricas (sin snapshots/cilindros). Estos tests
fijan que (1) calcula lo mismo que ``calcular_kpis`` sobre los tallers de
``batch_simular`` — no diverge de la fuente única —, (2) es determinista en
paralelo, (3) respeta los bordes (lista vacía, validación de ``seeds``).
"""
from datetime import datetime

import pandas as pd
import pytest

from modelos.kpis import calcular_kpis
from runner import batch_kpis, batch_simular

_COLS_CAMBIOS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                 "mm_a_Rectificar", "Observación"]
_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                   "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}]


def _cfg():
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 520.0}],
        "maquinas": _MAQ,
    }


def _stock():
    # Una pareja trabajando + dos disponibles para reponer tras los cambios.
    filas = [
        {"ID_Cilindro": "T1", "Diámetro_mm": 560.0, "Estado": "Trabajando",
         "Jaula_Asignada": 1, "Posición": 1},
        {"ID_Cilindro": "T2", "Diámetro_mm": 560.0, "Estado": "Trabajando",
         "Jaula_Asignada": 1, "Posición": 2},
        {"ID_Cilindro": "D1", "Diámetro_mm": 555.0, "Estado": "Disponible",
         "Jaula_Asignada": 1, "Posición": 0},
        {"ID_Cilindro": "D2", "Diámetro_mm": 555.0, "Estado": "Disponible",
         "Jaula_Asignada": 1, "Posición": 0},
    ]
    return pd.DataFrame(filas)


def _df_cambios(rows):
    return pd.DataFrame(rows, columns=_COLS_CAMBIOS)


def _lista_cambios():
    c1 = _df_cambios([
        {"ID_Cambio": "C1", "Fecha_Hora": datetime(2026, 6, 15, 8, 0), "Jaula": 1,
         "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 2.0, "Observación": ""},
    ])
    c2 = _df_cambios([
        {"ID_Cambio": "C1", "Fecha_Hora": datetime(2026, 6, 15, 8, 0), "Jaula": 1,
         "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 2.0, "Observación": ""},
        {"ID_Cambio": "C2", "Fecha_Hora": datetime(2026, 6, 15, 14, 0), "Jaula": 1,
         "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 3.0, "Observación": ""},
    ])
    return [c1, c2]


def _solo_escalares(kpis):
    """Subconjunto comparable: las métricas escalares (las que el dict marca)."""
    return {k: kpis[k] for k in kpis["metric_order"]}


def test_batch_kpis_equivale_a_calcular_sobre_batch_simular():
    """Cada dict de batch_kpis == calcular_kpis del taller equivalente, en orden."""
    cfg, stock, lista = _cfg(), _stock(), _lista_cambios()

    kpis_livianos = batch_kpis(cfg, stock, lista, max_workers=2)
    tallers = batch_simular(cfg, stock, lista, max_workers=2)
    kpis_pesados = [calcular_kpis(t) for t in tallers]

    assert len(kpis_livianos) == len(lista)
    for liviano, pesado in zip(kpis_livianos, kpis_pesados):
        assert _solo_escalares(liviano) == pytest.approx(_solo_escalares(pesado))


def test_batch_kpis_es_determinista_en_paralelo():
    """Misma entrada dos veces ⇒ KPIs idénticos (orden y valores)."""
    cfg, stock, lista = _cfg(), _stock(), _lista_cambios()

    a = batch_kpis(cfg, stock, lista, max_workers=2)
    b = batch_kpis(cfg, stock, lista, max_workers=2)

    assert len(a) == len(b) == len(lista)
    for ka, kb in zip(a, b):
        assert _solo_escalares(ka) == pytest.approx(_solo_escalares(kb))


def test_batch_kpis_lista_vacia():
    assert batch_kpis(_cfg(), _stock(), []) == []


def test_batch_kpis_seeds_alineadas_y_desalineadas():
    cfg, stock, lista = _cfg(), _stock(), _lista_cambios()

    # Alineadas: una seed por corrida ⇒ una salida por corrida.
    res = batch_kpis(cfg, stock, lista, seeds=[1, 2], max_workers=2)
    assert len(res) == len(lista)

    # Desalineadas: mismo guard que batch_simular.
    with pytest.raises(ValueError):
        batch_kpis(cfg, stock, lista, seeds=[1])
