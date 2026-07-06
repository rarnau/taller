"""Tests de la estrategia definida "Prioridad J1/J4 +20% (piso 10)" y de la
métrica de activos por jaula con atribución única.

Dos mecanismos nuevos (opt-in; la estrategia por defecto no cambia):
  - ``TallerCilindros.stock_activos_por_jaula()``: cada cilindro activo (no
    BAJA) se atribuye a UNA sola jaula (trabajando/CRC → jaula física,
    destinado → destino, resto → banda más baja por diámetro, 0 = sin banda),
    de modo que la suma es el total de activos aun con bandas solapadas. El
    snapshot lo expone en ``activos_por_jaula`` (alimenta el gráfico de
    Análisis "Evolución de stock por jaula").
  - Estrategia ``prioridad_j1_j4_piso10`` (pesos y piso DEFINIDOS en la
    estrategia, sin configuración por jaula): paradas primero, luego piso de
    10 (gana la más vacía), luego balance ponderado stock/peso con pesos
    J1=1.44, J2=1.2, J3=1.0, J4=1.2.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modelos.cilindro import Cilindro
from modelos.enums import EstadoCilindro
from modelos.estrategias import ESTRATEGIAS_ASIGNACION, _PrioridadJ1J4ConPiso
from modelos.jaula import Jaula
from modelos.taller import TallerCilindros

T0 = datetime(2026, 1, 1, 6, 0, 0)

# Bandas solapadas: 545 cae en las jaulas 2 (530-555) y 3 (540-565) a la vez.
_BANDAS_SOLAPADAS = [
    {"jaula": 1, "desde": 540.0, "hasta": 520.0},
    {"jaula": 2, "desde": 555.0, "hasta": 530.0},
    {"jaula": 3, "desde": 565.0, "hasta": 540.0},
    {"jaula": 4, "desde": 575.0, "hasta": 555.0},
]


def _taller(rangos=_BANDAS_SOLAPADAS):
    t = TallerCilindros()
    t.configurar({
        "config_global": {
            "diametro_maximo": 575.0, "diametro_minimo": 520.0,
            "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": len(rangos),
        },
        "rangos": rangos,
    })
    for j in range(1, len(rangos) + 1):
        t.jaulas[j] = Jaula(j)
    t._estrategia_asig_obj = ESTRATEGIAS_ASIGNACION["prioridad_j1_j4_piso10"]
    return t


def _agregar(t, id_, diametro, estado=EstadoCilindro.DISPONIBLE, jaula=None, destino=None):
    cil = Cilindro(id_, diametro, estado, jaula=jaula)
    cil.jaula_destino = destino
    t.cilindros[id_] = cil
    return cil


# ── stock_activos_por_jaula: atribución única ───────────────────────────────

def test_atribucion_unica_por_prioridad_de_regla():
    t = _taller()
    _agregar(t, "TRAB", 545.0, EstadoCilindro.TRABAJANDO, jaula=4)   # física gana
    _agregar(t, "CRC", 545.0, EstadoCilindro.CRC, jaula=1)           # física gana
    _agregar(t, "DEST", 545.0, EstadoCilindro.DISPONIBLE, destino=3)  # destino gana
    _agregar(t, "DIAM", 545.0)          # sin destino: banda más baja (jaula 2)
    _agregar(t, "BAJA", 545.0, EstadoCilindro.BAJA)                  # no cuenta
    stock = t.stock_activos_por_jaula()
    assert stock == {1: 1, 2: 1, 3: 1, 4: 1}
    assert sum(stock.values()) == 4  # 5 cilindros, 1 BAJA: total activos = 4


def test_atribucion_sin_banda_va_a_clave_cero_y_el_total_cierra():
    # Hueco 540-560 entre las dos bandas.
    t = _taller([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ])
    _agregar(t, "A", 530.0)
    _agregar(t, "HUECO", 550.0)  # en el hueco: ninguna banda lo contiene
    stock = t.stock_activos_por_jaula()
    assert stock[1] == 1 and stock[0] == 1
    assert sum(stock.values()) == 2


def test_con_solape_no_se_cuenta_dos_veces():
    """A diferencia del conteo por SubStock, el activo en el solape cuenta 1 vez."""
    t = _taller()
    _agregar(t, "A", 545.0)  # cae en las bandas de J2 y J3
    stock = t.stock_activos_por_jaula()
    assert sum(stock.values()) == 1


def test_snapshot_expone_activos_por_jaula_y_suma_activos():
    t = _taller()
    _agregar(t, "A", 545.0)
    _agregar(t, "B", 562.0, EstadoCilindro.A_RECTIFICAR)
    _agregar(t, "C", 530.0, EstadoCilindro.BAJA)
    t.generar_snapshot(T0)
    sn = t.snapshots[-1]
    assert sum(sn.activos_por_jaula.values()) == 2  # C es BAJA
    # Todas las jaulas presentes como clave (aun con 0), como conteo_por_estado.
    assert set(sn.activos_por_jaula) >= {1, 2, 3, 4}
    # El snapshot replica exactamente la métrica canónica del motor.
    assert sn.activos_por_jaula == t.stock_activos_por_jaula()


# ── Estrategia prioridad_j1_j4_piso10 ────────────────────────────────────────

def _poblar(t, jaula, n, diam):
    """Agrega ``n`` disponibles destinados a ``jaula`` (atribución por destino)."""
    for i in range(n):
        _agregar(t, f"J{jaula}-{i}", diam, destino=jaula)


def test_bajo_el_piso_gana_la_mas_vacia_aunque_pese_menos():
    """J3 (peso 1.0) con 4 activos le gana a J2 (peso 1.2) con 7: ambas bajo el
    piso de 10, gana la más vacía sin mirar pesos."""
    t = _taller()
    _poblar(t, 2, 7, 545.0)
    _poblar(t, 3, 4, 550.0)
    cil = _agregar(t, "X", 546.0, EstadoCilindro.RECTIFICANDO)
    destino, _ = t._asignar_jaula_destino(cil, 545.0, T0)  # candidatas: 2 y 3
    assert destino == 3


def test_sobre_el_piso_gana_la_ponderada():
    """Con ambas sobre el piso y stock igual (12 y 12): 12/1.2 < 12/1.0 ⇒ J2."""
    t = _taller()
    _poblar(t, 2, 12, 545.0)
    _poblar(t, 3, 12, 550.0)
    cil = _agregar(t, "X", 546.0, EstadoCilindro.RECTIFICANDO)
    destino, _ = t._asignar_jaula_destino(cil, 545.0, T0)
    assert destino == 2  # peso 1.2: pide 20% más que J3 antes de ceder


def test_sobre_el_piso_el_factor_20_se_respeta():
    """J2 con >20% más de stock que J3 deja de ser preferida: 15/1.2 > 12/1.0."""
    t = _taller()
    _poblar(t, 2, 15, 545.0)
    _poblar(t, 3, 12, 550.0)
    cil = _agregar(t, "X", 546.0, EstadoCilindro.RECTIFICANDO)
    destino, _ = t._asignar_jaula_destino(cil, 545.0, T0)
    assert destino == 3


def test_piso_le_gana_a_la_ponderacion():
    """J3 bajo el piso (9) va antes que J2 sobre el piso (10), aunque J2 pese más."""
    t = _taller()
    _poblar(t, 2, 10, 545.0)
    _poblar(t, 3, 9, 550.0)
    cil = _agregar(t, "X", 546.0, EstadoCilindro.RECTIFICANDO)
    destino, _ = t._asignar_jaula_destino(cil, 545.0, T0)
    assert destino == 3


def test_parada_va_primero():
    t = _taller()
    _poblar(t, 2, 3, 545.0)    # J2 mucho más vacía...
    _poblar(t, 3, 12, 550.0)
    t.jaulas[3].parada = True  # ...pero J3 está parada
    cil = _agregar(t, "X", 546.0, EstadoCilindro.RECTIFICANDO)
    destino, _ = t._asignar_jaula_destino(cil, 545.0, T0)
    assert destino == 3


def test_pesos_y_piso_definidos_en_la_estrategia():
    """Los parámetros viven en la estrategia (no en la config de jaulas)."""
    e = _PrioridadJ1J4ConPiso
    assert e.PISO_STOCK == 10
    assert e.PESOS == {1: 1.44, 2: 1.2, 3: 1.0, 4: 1.2}
    # J1 20% sobre J2, J2 y J4 20% sobre J3.
    assert abs(e.PESOS[1] / e.PESOS[2] - 1.2) < 1e-9
    assert abs(e.PESOS[2] / e.PESOS[3] - 1.2) < 1e-9
    assert abs(e.PESOS[4] / e.PESOS[3] - 1.2) < 1e-9


# ── Datos del gráfico de Análisis (sin Qt) ───────────────────────────────────

def test_evolucion_analisis_total_es_activos():
    from gui_qt import analysis_data as ad

    t = _taller()
    _agregar(t, "A", 545.0)                   # solape J2/J3: cuenta 1 vez
    _agregar(t, "B", 562.0)                   # J3 y J4 se solapan? 562 cae en J3 (540-565) y J4 (555-575)
    _agregar(t, "C", 525.0)                   # J1
    _agregar(t, "D", 530.0, EstadoCilindro.BAJA)
    t.generar_snapshot(T0)

    data = ad.extraer_datos_analisis(t)
    total_ultimo = sum(serie[-1] for serie in data.evol_substock.values())
    assert total_ultimo == 3  # activos exactos, sin repetidos ni la BAJA
