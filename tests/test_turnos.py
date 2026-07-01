"""Pruebas del esquema de trabajo por turnos.

Cubre la lógica de dominio pura (``modelos/turnos.py``), los métodos de
calendario de la máquina (``MaquinaRectificadora``) y una verificación de
integración de que un esquema restrictivo cambia el resultado de la simulación
sin romper el motor.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.persistencia import cargar_config
from modelos import turnos as T
from modelos.kpis import calcular_kpis
from modelos.maquina import MaquinaRectificadora
from modelos.taller import TallerCilindros

_DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")

# Lunes 2024-01-01 a las 06:00 (weekday()==0).
LUN_0600 = datetime(2024, 1, 1, 6, 0)


# ── modelos/turnos.py ────────────────────────────────────────────────────────

def test_expandir_24x7_todas_las_horas():
    g = T.expandir(T.PRESETS["24x7"])
    assert all(all(fila) for fila in g)
    assert len(g) == 7 and all(len(fila) == 24 for fila in g)


def test_expandir_turnos_a_horas_correctas():
    solo_t1 = T.normalizar({"lun": [True, False, False]})
    g = T.expandir(solo_t1)
    assert g[0][6] and g[0][13]            # 06–13 operativo
    assert not g[0][5] and not g[0][14]    # fuera de 06–14


def test_t3_cruza_medianoche_al_dia_siguiente():
    # T3 del lunes (22–06) cubre lunes 22–23 y martes 00–05.
    solo_t3 = T.normalizar({"lun": [False, False, True]})
    g = T.expandir(solo_t3)
    assert g[0][22] and g[0][23]
    assert g[1][0] and g[1][5] and not g[1][6]


def test_domingo_t3_envuelve_a_lunes():
    solo_dom_t3 = T.normalizar({"dom": [False, False, True]})
    g = T.expandir(solo_dom_t3)
    assert g[6][22] and g[6][23]
    assert g[0][0] and g[0][5]  # lunes madrugada


def test_off_no_tiene_horas():
    g = T.expandir(T.PRESETS["off"])
    assert not any(any(fila) for fila in g)


def test_preset_3escuadras_sin_t3_sabado_ni_domingo():
    p = T.PRESETS["3escuadras"]
    # Lunes a viernes: los tres turnos operativos.
    for d in ("lun", "mar", "mie", "jue", "vie"):
        assert p[d] == [True, True, True]
    # Sábado: T1 y T2 operativos, T3 apagado; domingo completo apagado.
    assert p["sab"] == [True, True, False]
    assert p["dom"] == [False, False, False]
    g = T.expandir(p)
    assert g[5][6] and g[5][14]          # sábado T1/T2 operativos
    assert not g[5][22] and not g[5][23]  # sábado T3 apagado
    assert not any(g[6])                  # domingo sin ninguna hora


def test_parse_format_roundtrip():
    s = T.format_compacto(T.PRESETS["lv3"])
    assert T.parse_compacto(s) == T.normalizar(T.PRESETS["lv3"])


def test_parse_compacto_contiguo():
    turnos = T.parse_compacto("111111111111111110000")  # 21 dígitos
    assert turnos["sab"] == [True, True, False]
    assert turnos["dom"] == [False, False, False]


def test_parse_compacto_invalido():
    import pytest
    with pytest.raises(ValueError):
        T.parse_compacto("111 111")  # faltan grupos


def test_resumen():
    assert T.resumen(None) == "24/7"
    assert T.resumen(T.PRESETS["24x7"]) == "24/7"
    assert T.resumen(T.PRESETS["off"]) == "Apagada"
    assert T.resumen(T.PRESETS["lv3"]) == "5d × 3t"


# ── MaquinaRectificadora (calendario) ────────────────────────────────────────

def _maquina_un_turno():
    """Máquina operativa solo T1 (06–14) de lunes a viernes."""
    turnos = {d: ([True, False, False] if i < 5 else [False, False, False])
              for i, d in enumerate(T.DIAS)}
    m = MaquinaRectificadora("X")
    m.grilla_operativa = T.expandir(turnos)
    return m


def test_grilla_none_es_24x7():
    m = MaquinaRectificadora("X")
    assert m.grilla_operativa is None
    assert m.esta_operativa(datetime(2024, 1, 1, 3, 0))
    # Sin grilla, el fin es la suma directa (comportamiento histórico).
    assert m.calcular_fin_operativo(LUN_0600, 120) == datetime(2024, 1, 1, 8, 0)
    assert m.minutos_operativos_entre(LUN_0600, datetime(2024, 1, 1, 8, 0)) == 120.0


def test_esta_operativa():
    m = _maquina_un_turno()
    assert m.esta_operativa(LUN_0600)
    assert not m.esta_operativa(datetime(2024, 1, 1, 15, 0))  # fuera de T1
    assert not m.esta_operativa(datetime(2024, 1, 6, 8, 0))   # sábado


def test_calcular_fin_operativo_salta_huecos():
    m = _maquina_un_turno()
    # 600 min (10 h): 8 h el lunes (06→14) + 2 h el martes (06→08).
    assert m.calcular_fin_operativo(LUN_0600, 600) == datetime(2024, 1, 2, 8, 0)


def test_calcular_fin_operativo_dentro_de_ventana():
    m = _maquina_un_turno()
    assert m.calcular_fin_operativo(LUN_0600, 120) == datetime(2024, 1, 1, 8, 0)


def test_proxima_apertura():
    m = _maquina_un_turno()
    # Operativa ya: devuelve el mismo instante.
    assert m.proxima_apertura(LUN_0600) == LUN_0600
    # Fuera de turno el lunes por la tarde -> martes 06:00.
    assert m.proxima_apertura(datetime(2024, 1, 1, 15, 0)) == datetime(2024, 1, 2, 6, 0)


def test_proxima_apertura_apagada_es_none():
    m = MaquinaRectificadora("Y")
    m.grilla_operativa = T.expandir(T.PRESETS["off"])
    assert m.proxima_apertura(LUN_0600) is None


def test_minutos_operativos_entre_excluye_huecos():
    m = _maquina_un_turno()
    # Lunes 06:00 a martes 06:00 = solo las 8 h operativas del lunes.
    assert m.minutos_operativos_entre(LUN_0600, datetime(2024, 1, 2, 6, 0)) == 480.0


def test_progreso_operativo_equivale_a_minutos_operativos_entre():
    """El cálculo rápido por hitos (bisect) coincide con el walk hora-por-hora.

    Blinda el refactor de rendimiento de generar_snapshot: para un trabajo que
    cruza un hueco cerrado, ``progreso_operativo(t)`` debe dar lo mismo que
    ``minutos_operativos_entre(inicio, t)`` en cualquier ``t`` de ``[inicio, fin]``.
    """
    from datetime import timedelta

    from modelos.cilindro import Cilindro
    from modelos.enums import TipoRectificado

    m = _maquina_un_turno()
    m.configurar_tasa("produccion", 1.0, 1.0)  # 1 mm/min -> 600 min = 10 h operativas
    cil = Cilindro("CIL-1", 560.0, 575.0)
    # 600 min operativos cruzando el cierre del lunes (06→14) hacia el martes.
    m.iniciar_rectificado(cil, LUN_0600, TipoRectificado.PRODUCCION, 600.0)
    fin = m.tiempo_fin_rectificado
    assert fin == datetime(2024, 1, 2, 8, 0)  # 8 h el lunes + 2 h el martes

    # Muestreo denso en [inicio, fin]: fronteras de hora, instantes intermedios,
    # dentro del hueco cerrado (lunes tarde/noche) y el extremo final.
    t = LUN_0600
    while t <= fin:
        esperado = m.minutos_operativos_entre(LUN_0600, t)
        assert abs(m.progreso_operativo(t) - esperado) < 1e-6, t
        t += timedelta(minutes=37)
    # Extremos exactos: inicio (0) y fin (= total operativo).
    assert m.progreso_operativo(LUN_0600) == 0.0
    assert abs(m.progreso_operativo(fin) - 600.0) < 1e-6


# ── Integración: el esquema cambia el resultado sin romper el motor ───────────

def _fingerprint_minimo(taller: TallerCilindros):
    """Resumen liviano: tiempo del último snapshot y nº de cilindros disponibles."""
    ultimo = taller.snapshots[-1]
    return ultimo.tiempo, ultimo.cantidad_disponibles


def test_turnos_restrictivos_cambian_la_simulacion():
    excel = os.path.join(_DIR_DATOS, "simulacion_140cils_1semana.xlsx")

    # Corrida base (24/7).
    cfg_base = cargar_config()
    t_base = TallerCilindros()
    t_base.configurar(cfg_base)
    t_base.cargar_datos(excel)
    t_base.simular(estrategia="mayor_diametro", callback_log=None)

    # Corrida con todas las máquinas en un único turno L–V (cuello de botella).
    cfg_turno = cargar_config()
    turnos = {d: ([True, False, False] if i < 5 else [False, False, False])
              for i, d in enumerate(T.DIAS)}
    for m in cfg_turno["maquinas"]:
        m["turnos"] = turnos
    t_turno = TallerCilindros()
    t_turno.configurar(cfg_turno)
    t_turno.cargar_datos(excel)
    t_turno.simular(estrategia="mayor_diametro", callback_log=None)

    # El motor no se rompe y el horario restrictivo alarga la operación
    # (el último snapshot ocurre más tarde que en 24/7).
    assert t_turno.snapshots and t_base.snapshots
    assert t_turno.snapshots[-1].tiempo > t_base.snapshots[-1].tiempo


def test_default_no_define_turnos():
    """La config por defecto deja las máquinas 24/7 (grilla None), sin regresión."""
    cfg = cargar_config()
    assert all("turnos" not in m for m in cfg["maquinas"])
    t = TallerCilindros()
    t.configurar(cfg)
    assert all(maq.grilla_operativa is None for maq in t.maquinas.values())


# ── KPIs de utilización disponible vs neta ────────────────────────────────────

def _simular_con_turnos(turnos):
    """Corre la simulación de referencia; ``turnos=None`` deja las máquinas 24/7."""
    excel = os.path.join(_DIR_DATOS, "simulacion_140cils_1semana.xlsx")
    cfg = cargar_config()
    if turnos is not None:
        for m in cfg["maquinas"]:
            m["turnos"] = turnos
    t = TallerCilindros()
    t.configurar(cfg)
    t.cargar_datos(excel)
    t.simular(estrategia="mayor_diametro", callback_log=None)
    return t


def test_kpis_disponible_total_en_24x7():
    """En 24/7 la disponibilidad es 100% (operativo == calendario) por máquina."""
    k = calcular_kpis(_simular_con_turnos(None))
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
              for i, d in enumerate(T.DIAS)}
    t = _simular_con_turnos(turnos)
    k = calcular_kpis(t)
    disp, neta = k["utilizacion_maquinas_pct"], k["utilizacion_neta_pct"]
    cal_min = (t.snapshots[-1].tiempo - t.snapshots[0].tiempo).total_seconds() / 60
    for nombre, mq in t.maquinas.items():
        assert 0.0 <= disp[nombre] <= 100.0
        assert 0.0 <= neta[nombre] <= 100.0
        op = mq.minutos_operativos_entre(t.snapshots[0].tiempo, t.snapshots[-1].tiempo)
        assert abs(disp[nombre] - op / cal_min * 100) < 1e-6          # disponible = operativo/calendario
        global_util = mq.tiempo_total_ocupada_min / cal_min * 100      # ocupada/calendario
        assert abs(disp[nombre] / 100 * neta[nombre] - global_util) < 1e-6
    # Con turnos cerrados la disponibilidad es estrictamente < 100 en todas.
    assert all(disp[m] < 100.0 - 1e-6 for m in disp)


def test_kpis_exponen_tiempo_y_porcentaje_de_parada():
    """El KPI de parada agrega duración total y % del horizonte en metric_meta."""
    from tests._escenarios import ejecutar_escenario, ESCENARIOS

    t = ejecutar_escenario(ESCENARIOS["parada_mayor_diametro"])
    k = calcular_kpis(t)
    parada_s = 0.0
    total_s = 0.0
    for i, snap in enumerate(t.snapshots[:-1]):
        dt = (t.snapshots[i + 1].tiempo - snap.tiempo).total_seconds()
        if dt <= 0:
            continue
        total_s += dt
        if snap.jaulas_paradas:
            parada_s += dt

    assert abs(k["tiempo_parada_h"] - parada_s / 3600.0) < 1e-6
    assert "tiempo_parada_h" in k["metric_order"]
    meta = k["metric_meta"]["tiempo_parada_h"]
    assert meta["label"]
    assert meta["detail"] == f"{(parada_s / total_s * 100.0):.1f}% del horizonte"


# ── Tiempo laborable de la línea (minutos_operativos / avanzar_operativo) ─────

_GRID_LV = T.expandir({d: ([True, True, True] if i < 5 else [False, False, False])
                       for i, d in enumerate(T.DIAS)})


def test_minutos_operativos_none_es_reloj():
    a, b = datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 5, 30)
    assert T.minutos_operativos(None, a, b) == 5.5 * 60
    assert T.minutos_operativos(None, b, a) == 0.0  # intervalo vacío


def test_avanzar_operativo_none_es_reloj():
    t = datetime(2024, 1, 3, 9, 0)
    assert T.avanzar_operativo(None, t, 125) == t + timedelta(minutes=125)
    assert T.avanzar_operativo(None, t, 0) == t


def test_avanzar_operativo_roundtrip_consume_solo_laborable():
    """avanzar consume exactamente N min laborables desde el snap de inicio.

    Invariante independiente del wraparound de T3:
    minutos_operativos(grid, snap(t), avanzar(t, N)) == N.
    """
    for t in (datetime(2024, 1, 5, 22, 0),   # viernes (con derrame T3 al sábado)
              datetime(2024, 1, 6, 3, 0),     # madrugada sábado
              datetime(2024, 1, 7, 12, 0),    # domingo (fuera de turno)
              datetime(2024, 1, 8, 10, 0)):   # lunes operativo
        for n in (30, 180, 600, 3000):
            r = T.avanzar_operativo(_GRID_LV, t, n)
            start = T.proximo_inicio_operativo(_GRID_LV, t)
            assert start is not None
            assert abs(T.minutos_operativos(_GRID_LV, start, r) - n) < 1e-6


def test_avanzar_operativo_snapea_fuera_de_turno():
    """Si arranca fuera de turno, el resultado cae dentro de una hora operativa."""
    dom = datetime(2024, 1, 7, 12, 0)  # domingo, fuera de turno
    r = T.avanzar_operativo(_GRID_LV, dom, 0)
    assert _GRID_LV[r.weekday()][r.hour]            # snap a hora operativa
    assert r == T.proximo_inicio_operativo(_GRID_LV, dom)


def test_avanzar_operativo_regimen_apagado_degrada_a_reloj():
    grid_off = T.expandir(T.PRESETS["off"])
    t = datetime(2024, 1, 3, 9, 0)
    assert T.avanzar_operativo(grid_off, t, 120) == t + timedelta(minutes=120)
    assert T.minutos_operativos(grid_off, t, t + timedelta(hours=5)) == 0.0
