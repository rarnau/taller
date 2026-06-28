"""Pruebas del esquema de trabajo por turnos.

Cubre la lógica de dominio pura (``models/shifts.py``), los métodos de
calendario de la máquina (``GrindingMachine``) y una verificación de
integración de que un esquema restrictivo cambia el resultado de la simulación
sin romper el motor.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.persistencia import cargar_config
from models import shifts as T
from models.kpis import compute_kpis
from models.machine import GrindingMachine
from models.workshop import CylinderWorkshop

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Lunes 2024-01-01 a las 06:00 (weekday()==0).
LUN_0600 = datetime(2024, 1, 1, 6, 0)


# ── models/shifts.py ─────────────────────────────────────────────────────────

def test_expandir_24x7_todas_las_horas():
    g = T.expand(T.PRESETS["24x7"])
    assert all(all(fila) for fila in g)
    assert len(g) == 7 and all(len(fila) == 24 for fila in g)


def test_expandir_turnos_a_horas_correctas():
    solo_t1 = T.normalize({"lun": [True, False, False]})
    g = T.expand(solo_t1)
    assert g[0][6] and g[0][13]            # 06–13 operativo
    assert not g[0][5] and not g[0][14]    # fuera de 06–14


def test_t3_cruza_medianoche_al_dia_siguiente():
    # T3 del lunes (22–06) cubre lunes 22–23 y martes 00–05.
    solo_t3 = T.normalize({"lun": [False, False, True]})
    g = T.expand(solo_t3)
    assert g[0][22] and g[0][23]
    assert g[1][0] and g[1][5] and not g[1][6]


def test_domingo_t3_envuelve_a_lunes():
    solo_dom_t3 = T.normalize({"dom": [False, False, True]})
    g = T.expand(solo_dom_t3)
    assert g[6][22] and g[6][23]
    assert g[0][0] and g[0][5]  # lunes madrugada


def test_off_no_tiene_horas():
    g = T.expand(T.PRESETS["off"])
    assert not any(any(fila) for fila in g)


def test_preset_3escuadras_sin_t3_sabado_ni_domingo():
    p = T.PRESETS["3escuadras"]
    # Lunes a viernes: los tres turnos operativos.
    for d in ("lun", "mar", "mie", "jue", "vie"):
        assert p[d] == [True, True, True]
    # Sábado: T1 y T2 operativos, T3 apagado; domingo completo apagado.
    assert p["sab"] == [True, True, False]
    assert p["dom"] == [False, False, False]
    g = T.expand(p)
    assert g[5][6] and g[5][14]          # sábado T1/T2 operativos
    assert not g[5][22] and not g[5][23]  # sábado T3 apagado
    assert not any(g[6])                  # domingo sin ninguna hora


def test_parse_format_roundtrip():
    s = T.format_compact(T.PRESETS["lv3"])
    assert T.parse_compact(s) == T.normalize(T.PRESETS["lv3"])


def test_parse_compacto_contiguo():
    turnos = T.parse_compact("111111111111111110000")  # 21 dígitos
    assert turnos["sab"] == [True, True, False]
    assert turnos["dom"] == [False, False, False]


def test_parse_compacto_invalido():
    import pytest
    with pytest.raises(ValueError):
        T.parse_compact("111 111")  # faltan grupos


def test_resumen():
    assert T.summary(None) == "24/7"
    assert T.summary(T.PRESETS["24x7"]) == "24/7"
    assert T.summary(T.PRESETS["off"]) == "Apagada"
    assert T.summary(T.PRESETS["lv3"]) == "5d × 3t"


# ── GrindingMachine (calendar) ────────────────────────────────────────────────

def _maquina_un_turno():
    """Máquina operativa solo T1 (06–14) de lunes a viernes."""
    turnos = {d: ([True, False, False] if i < 5 else [False, False, False])
              for i, d in enumerate(T.DAYS)}
    m = GrindingMachine("X")
    m.operating_grid = T.expand(turnos)
    return m


def test_grilla_none_es_24x7():
    m = GrindingMachine("X")
    assert m.operating_grid is None
    assert m.is_operative(datetime(2024, 1, 1, 3, 0))
    # Sin grilla, el fin es la suma directa (comportamiento histórico).
    assert m.compute_operative_end(LUN_0600, 120) == datetime(2024, 1, 1, 8, 0)
    assert m.operative_minutes_between(LUN_0600, datetime(2024, 1, 1, 8, 0)) == 120.0


def test_esta_operativa():
    m = _maquina_un_turno()
    assert m.is_operative(LUN_0600)
    assert not m.is_operative(datetime(2024, 1, 1, 15, 0))  # fuera de T1
    assert not m.is_operative(datetime(2024, 1, 6, 8, 0))   # sábado


def test_calcular_fin_operativo_salta_huecos():
    m = _maquina_un_turno()
    # 600 min (10 h): 8 h el lunes (06→14) + 2 h el martes (06→08).
    assert m.compute_operative_end(LUN_0600, 600) == datetime(2024, 1, 2, 8, 0)


def test_calcular_fin_operativo_dentro_de_ventana():
    m = _maquina_un_turno()
    assert m.compute_operative_end(LUN_0600, 120) == datetime(2024, 1, 1, 8, 0)


def test_proxima_apertura():
    m = _maquina_un_turno()
    # Operativa ya: devuelve el mismo instante.
    assert m.next_opening(LUN_0600) == LUN_0600
    # Fuera de turno el lunes por la tarde -> martes 06:00.
    assert m.next_opening(datetime(2024, 1, 1, 15, 0)) == datetime(2024, 1, 2, 6, 0)


def test_proxima_apertura_apagada_es_none():
    m = GrindingMachine("Y")
    m.operating_grid = T.expand(T.PRESETS["off"])
    assert m.next_opening(LUN_0600) is None


def test_minutos_operativos_entre_excluye_huecos():
    m = _maquina_un_turno()
    # Lunes 06:00 a martes 06:00 = solo las 8 h operativas del lunes.
    assert m.operative_minutes_between(LUN_0600, datetime(2024, 1, 2, 6, 0)) == 480.0


def test_progreso_operativo_equivale_a_minutos_operativos_entre():
    """El cálculo rápido por hitos (bisect) coincide con el walk hora-por-hora.

    Blinda el refactor de rendimiento de generate_snapshot: para un trabajo que
    cruza un hueco cerrado, ``operative_progress(t)`` debe dar lo mismo que
    ``operative_minutes_between(inicio, t)`` en cualquier ``t`` de ``[inicio, fin]``.
    """
    from datetime import timedelta

    from models.cylinder import Cylinder
    from models.enums import GrindingType

    m = _maquina_un_turno()
    m.configure_rate("produccion", 1.0, 1.0)  # 1 mm/min -> 600 min = 10 h operativas
    cil = Cylinder("CIL-1", 560.0, 575.0)
    # 600 min operativos cruzando el cierre del lunes (06→14) hacia el martes.
    m.start_grinding(cil, LUN_0600, GrindingType.PRODUCTION, 600.0)
    fin = m.grinding_end_time
    assert fin == datetime(2024, 1, 2, 8, 0)  # 8 h el lunes + 2 h el martes

    # Muestreo denso en [inicio, fin]: fronteras de hora, instantes intermedios,
    # dentro del hueco cerrado (lunes tarde/noche) y el extremo final.
    t = LUN_0600
    while t <= fin:
        esperado = m.operative_minutes_between(LUN_0600, t)
        assert abs(m.operative_progress(t) - esperado) < 1e-6, t
        t += timedelta(minutes=37)
    # Extremos exactos: inicio (0) y fin (= total operativo).
    assert m.operative_progress(LUN_0600) == 0.0
    assert abs(m.operative_progress(fin) - 600.0) < 1e-6


# ── Integración: el esquema cambia el resultado sin romper el motor ───────────

def _fingerprint_minimo(taller: CylinderWorkshop):
    """Resumen liviano: tiempo del último snapshot y nº de cilindros disponibles."""
    ultimo = taller.snapshots[-1]
    return ultimo.tiempo, ultimo.cantidad_disponibles


def test_turnos_restrictivos_cambian_la_simulacion():
    excel = os.path.join(_DATA_DIR, "simulacion_140cils_1semana.xlsx")

    # Corrida base (24/7).
    cfg_base = cargar_config()
    t_base = CylinderWorkshop()
    t_base.configure(cfg_base)
    t_base.load_data(excel)
    t_base.simulate(strategy="mayor_diametro", callback_log=None)

    # Corrida con todas las máquinas en un único turno L–V (cuello de botella).
    cfg_turno = cargar_config()
    turnos = {d: ([True, False, False] if i < 5 else [False, False, False])
              for i, d in enumerate(T.DAYS)}
    for m in cfg_turno["maquinas"]:
        m["turnos"] = turnos
    t_turno = CylinderWorkshop()
    t_turno.configure(cfg_turno)
    t_turno.load_data(excel)
    t_turno.simulate(strategy="mayor_diametro", callback_log=None)

    # El motor no se rompe y el horario restrictivo alarga la operación
    # (el último snapshot ocurre más tarde que en 24/7).
    assert t_turno.snapshots and t_base.snapshots
    assert t_turno.snapshots[-1].tiempo > t_base.snapshots[-1].tiempo


def test_default_no_define_turnos():
    """La config por defecto deja las máquinas 24/7 (grilla None), sin regresión."""
    cfg = cargar_config()
    assert all("turnos" not in m for m in cfg["maquinas"])
    t = CylinderWorkshop()
    t.configure(cfg)
    assert all(maq.operating_grid is None for maq in t.machines.values())


# ── KPIs de utilización disponible vs neta ────────────────────────────────────

def _simular_con_turnos(turnos):
    """Corre la simulación de referencia; ``turnos=None`` deja las máquinas 24/7."""
    excel = os.path.join(_DATA_DIR, "simulacion_140cils_1semana.xlsx")
    cfg = cargar_config()
    if turnos is not None:
        for m in cfg["maquinas"]:
            m["turnos"] = turnos
    t = CylinderWorkshop()
    t.configure(cfg)
    t.load_data(excel)
    t.simulate(strategy="mayor_diametro", callback_log=None)
    return t


def test_kpis_disponible_total_en_24x7():
    """En 24/7 la disponibilidad es 100% (operativo == calendario) por máquina."""
    k = compute_kpis(_simular_con_turnos(None))
    disp, neta = k["utilizacion_maquinas_pct"], k["utilizacion_neta_pct"]
    assert set(disp) == set(neta) and disp
    for m in disp:
        assert abs(disp[m] - 100.0) < 1e-6     # disponible = calendario/calendario
        assert 0.0 <= neta[m] <= 100.0


def test_kpis_descomposicion_con_turno_restringido():
    """Con turnos cerrados: disponible = operativo/calendario < 100; neta = ocupada/operativo.

    Verifica la descomposición tipo OEE: disponible × neta == utilización global
    (ocupada/calendario).
    """
    turnos = {d: ([True, False, False] if i < 5 else [False, False, False])
              for i, d in enumerate(T.DAYS)}
    t = _simular_con_turnos(turnos)
    k = compute_kpis(t)
    disp, neta = k["utilizacion_maquinas_pct"], k["utilizacion_neta_pct"]
    cal_min = (t.snapshots[-1].tiempo - t.snapshots[0].tiempo).total_seconds() / 60
    for nombre, mq in t.machines.items():
        assert 0.0 <= disp[nombre] <= 100.0
        assert 0.0 <= neta[nombre] <= 100.0
        op = mq.operative_minutes_between(t.snapshots[0].tiempo, t.snapshots[-1].tiempo)
        assert abs(disp[nombre] - op / cal_min * 100) < 1e-6          # disponible = operativo/calendario
        global_util = mq.total_busy_min / cal_min * 100                # ocupada/calendario
        assert abs(disp[nombre] / 100 * neta[nombre] - global_util) < 1e-6
    # Con turnos cerrados la disponibilidad es estrictamente < 100 en todas.
    assert all(disp[m] < 100.0 - 1e-6 for m in disp)
