"""Pruebas de la tasa de falla por máquina (capa de disponibilidad).

Cubre la lógica de dominio pura (``MaquinaRectificadora.en_falla`` y derivados),
la integración con el motor (reproducibilidad por seed, neta que baja, KPI
explícito, snapshot con el estado de falla) y la picklabilidad. Con
``tasa_falla=0`` (o sin seed) el comportamiento es idéntico al histórico.
"""
import os
import pickle
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.persistencia import cargar_config, set_maquina, obtener_tasa_falla
from modelos.kpis import calcular_kpis
from modelos.maquina import MaquinaRectificadora
from modelos.taller import TallerCilindros

_DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
_EXCEL = os.path.join(_DIR_DATOS, "simulacion_140cils_1semana.xlsx")
_LUN = datetime(2024, 1, 1, 6, 0)  # lunes


def _maquina(tasa, seed):
    m = MaquinaRectificadora("G36")
    m.tasa_falla = tasa
    m._seed_fallas = seed
    return m


# ── en_falla / disponible_para_trabajo (dominio puro) ────────────────────────

def test_sin_tasa_ni_seed_no_falla():
    assert _maquina(0.0, None).en_falla(_LUN) is False
    assert _maquina(0.0, 42).en_falla(_LUN) is False   # tasa 0
    assert _maquina(0.2, None).en_falla(_LUN) is False  # sin seed


def test_en_falla_determinista_y_reproducible():
    horas = [_LUN + timedelta(hours=h) for h in range(1000)]
    a = [_maquina(0.1, 42).en_falla(t) for t in horas]
    b = [_maquina(0.1, 42).en_falla(t) for t in horas]
    assert a == b


def test_en_falla_constante_dentro_de_la_hora():
    base = _maquina(0.3, 7)
    h = _LUN
    assert base.en_falla(h) == base.en_falla(h + timedelta(minutes=37))


def test_frecuencia_aproxima_la_tasa():
    horas = [_LUN + timedelta(hours=h) for h in range(20000)]
    frac = sum(_maquina(0.1, 123).en_falla(t) for t in horas) / len(horas)
    assert abs(frac - 0.1) < 0.02  # tolerancia estadística


def test_seeds_y_maquinas_independientes():
    horas = [_LUN + timedelta(hours=h) for h in range(1000)]
    base = [_maquina(0.1, 42).en_falla(t) for t in horas]
    otra_seed = [_maquina(0.1, 43).en_falla(t) for t in horas]
    m2 = MaquinaRectificadora("F60"); m2.tasa_falla = 0.1; m2._seed_fallas = 42
    otra_maq = [m2.en_falla(t) for t in horas]
    assert base != otra_seed and base != otra_maq


def test_disponible_para_trabajo_sin_fallas_es_esta_operativa():
    m = _maquina(0.0, None)
    assert m.disponible_para_trabajo(_LUN) == m.esta_operativa(_LUN)


def test_tasa_1_nunca_trabajable():
    m = _maquina(1.0, 5)
    assert all(not m.disponible_para_trabajo(_LUN + timedelta(hours=h)) for h in range(100))
    assert m.proxima_apertura(_LUN) is None


# ── Integración con el motor ─────────────────────────────────────────────────

def _simular(tasa_falla, seed, maquina="F60"):
    cfg = cargar_config()
    if tasa_falla > 0:
        set_maquina(cfg, maquina, tasa_falla=tasa_falla)
    t = TallerCilindros()
    t.configurar(cfg)
    t.cargar_datos(_EXCEL)
    t.simular(estrategia="mayor_diametro", callback_log=None, seed=seed)
    return t


def test_seed_reproducible_misma_corrida():
    k1 = calcular_kpis(_simular(0.15, 42))
    k2 = calcular_kpis(_simular(0.15, 42))
    assert k1["utilizacion_neta_pct"] == k2["utilizacion_neta_pct"]
    assert k1["tiempo_falla_pct"] == k2["tiempo_falla_pct"]


def test_seeds_distintas_cambian_resultado():
    k1 = calcular_kpis(_simular(0.15, 42))
    k2 = calcular_kpis(_simular(0.15, 99))
    assert k1["tiempo_falla_pct"] != k2["tiempo_falla_pct"]


def test_falla_baja_la_neta_y_no_la_disponible():
    base = calcular_kpis(_simular(0.0, None))
    con = calcular_kpis(_simular(0.2, 42))
    # La disponible (turnos/calendario) no cambia; la neta de la máquina con falla baja.
    assert con["utilizacion_maquinas_pct"]["F60"] == base["utilizacion_maquinas_pct"]["F60"]
    assert con["utilizacion_neta_pct"]["F60"] < base["utilizacion_neta_pct"]["F60"]
    assert con["tiempo_falla_pct"]["F60"] > 0
    # Las máquinas sin tasa de falla no se ven afectadas.
    assert con["tiempo_falla_pct"]["G36"] == 0.0


def test_kpi_falla_excluido_de_metricas_escalares():
    k = calcular_kpis(_simular(0.1, 42))
    assert "tiempo_falla_pct" in k
    assert "tiempo_falla_pct" not in k["metric_order"]  # es dict por máquina, no escalar


def test_snapshot_marca_estado_de_falla():
    # Con tasa alta, en algún snapshot la máquina está en falla.
    t = _simular(0.5, 42)
    assert any(s.detalle_maquinas_falla.get("F60") for s in t.snapshots)
    # Las máquinas sin falla nunca aparecen en falla.
    assert all(not s.detalle_maquinas_falla.get("G36") for s in t.snapshots)


def test_sin_seed_no_hay_fallas_aunque_haya_tasa():
    t = _simular(0.3, None)  # tasa>0 pero seed None ⇒ sin fallas
    k = calcular_kpis(t)
    assert k["tiempo_falla_pct"]["F60"] == 0.0
    assert all(not any(s.detalle_maquinas_falla.values()) for s in t.snapshots)


# ── Picklabilidad (paso a procesos / batch / Monte Carlo) ────────────────────

def test_maquina_picklable_conserva_y_reproduce_fallas():
    m = _maquina(0.2, 42)
    m2 = pickle.loads(pickle.dumps(m))
    assert m2.tasa_falla == 0.2 and m2._seed_fallas == 42
    horas = [_LUN + timedelta(hours=h) for h in range(500)]
    assert [m.en_falla(t) for t in horas] == [m2.en_falla(t) for t in horas]


def test_taller_simulado_con_fallas_picklable():
    t = _simular(0.2, 42)
    t2 = pickle.loads(pickle.dumps(t))
    assert calcular_kpis(t2)["tiempo_falla_pct"] == calcular_kpis(t)["tiempo_falla_pct"]


# ── Datos para el Gantt (gui_qt/dashboard_data, sin dependencia de Qt) ───────

def test_tramos_falla_dashboard_data():
    # dashboard_data sólo importa config.tema + modelos.kpis (no Qt): testeable headless.
    from gui_qt.dashboard_data import extraer_datos_dashboard, tramos_falla_maquina

    con = _simular(0.3, 42)
    data = extraer_datos_dashboard(con)
    # La máquina con falla tiene tramos; las que no, lista vacía.
    assert data.tramos_falla["F60"], "se esperaban tramos de falla en F60"
    assert data.tramos_falla["G36"] == []
    # Disjuntos de las paradas de turno (en 24/7 las paradas son []).
    f0, f1 = data.tramos_falla["F60"][0]
    assert f1 > f0
    # tasa_falla=0 ⇒ ningún tramo en ninguna máquina.
    base = extraer_datos_dashboard(_simular(0.0, None))
    assert all(v == [] for v in base.tramos_falla.values())
    # El helper devuelve [] para una máquina sin fallas configuradas.
    maq = con.maquinas["G36"]
    t0, t1 = con.snapshots[0].tiempo, con.snapshots[-1].tiempo
    assert tramos_falla_maquina(maq, t0, t1) == []
