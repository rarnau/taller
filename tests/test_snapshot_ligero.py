"""Modo de snapshot liviano (TallerCilindros.snapshot_ligero, para Monte Carlo).

Fija las invariantes del modo liviano:
- KPIs idénticos al modo completo (metricas_montecarlo y calcular_kpis escalares),
  mismo len(snapshots), sobre un escenario con PARADAs (jaulas_paradas/paradas/
  parada_pct no triviales);
- el registro CAMPOS_SNAPSHOT_KPI (modelos/eventos.py) está 1:1 con los bloques
  de cómputo del motor, todo campo del registro queda efectivamente poblado y
  todo campo pesado fuera del registro queda en su vacío de Snapshot.__init__;
- el wiring de Monte Carlo: el worker usa liviano salvo dump_dir (el pickle de
  drill-down necesita snapshots completos);
- el flag es un bool y no rompe el pickle del taller.

El default (snapshot_ligero=False, completo) ya lo cubre el golden master.
"""
import os
import pickle
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modelos.eventos import CAMPOS_SNAPSHOT_KPI, Snapshot
from modelos.kpis import calcular_kpis, metricas_montecarlo
from modelos.taller import TallerCilindros
from tests._escenarios import ESCENARIOS, ejecutar_escenario

# Escenario con PARADAs reales (ver datos/generar_caso_parada.py): así
# jaulas_paradas, "paradas" y "parada_pct" no son triviales en el assert.
_ESC_PARADA = ESCENARIOS["parada_mayor_diametro"]


def _ejecutar(esc, ligero: bool) -> TallerCilindros:
    """Mismo escenario que el golden, con el modo de snapshot elegido."""
    if not ligero:
        return ejecutar_escenario(esc)
    from config.persistencia import cargar_config
    cfg = cargar_config()
    cfg["tiempo_enfriado_h"] = esc["tiempo_enfriado"]
    taller = TallerCilindros()
    taller.configurar(cfg)
    taller.cargar_datos(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos", esc["excel"]))
    taller.snapshot_ligero = True
    taller.simular(estrategia=esc["estrategia"], callback_log=None)
    return taller


@pytest.fixture(scope="module")
def talleres():
    """El escenario PARADA corrido dos veces: completo y liviano."""
    return _ejecutar(_ESC_PARADA, ligero=False), _ejecutar(_ESC_PARADA, ligero=True)


# ── 1. Equivalencia de KPIs (el contrato del modo liviano) ───────────────────

def test_kpis_identicos_entre_modos(talleres):
    completo, ligero = talleres
    # Mismo escenario, misma cantidad de eventos ⇒ mismos snapshots (uno por evento).
    assert len(ligero.snapshots) == len(completo.snapshots) > 0

    mc_c = metricas_montecarlo(completo)
    mc_l = metricas_montecarlo(ligero)
    assert mc_l == mc_c

    # No trivial: el escenario efectivamente produce PARADAs.
    assert mc_c["paradas"] > 0
    assert mc_c["parada_pct"] > 0
    assert any(s.jaulas_paradas for s in completo.snapshots)

    k_c, k_l = calcular_kpis(completo), calcular_kpis(ligero)
    assert k_l["metric_order"] == k_c["metric_order"]
    for clave in k_c["metric_order"]:
        assert k_l[clave] == k_c[clave], clave


# ── 2. Cobertura del registro CAMPOS_SNAPSHOT_KPI ────────────────────────────

def test_registro_y_bloques_coinciden():
    """Cada campo del registro tiene exactamente su bloque de cómputo (y viceversa)."""
    assert set(TallerCilindros._BLOQUES_SNAPSHOT_KPI) == set(CAMPOS_SNAPSHOT_KPI)


def test_campos_kpi_poblados_en_liviano(talleres):
    """Todo campo del registro existe en el Snapshot liviano y quedó poblado
    (idéntico, snapshot a snapshot, al del modo completo)."""
    completo, ligero = talleres
    for campo in CAMPOS_SNAPSHOT_KPI:
        assert hasattr(ligero.snapshots[0], campo)
        for sn_c, sn_l in zip(completo.snapshots, ligero.snapshots):
            assert getattr(sn_l, campo) == getattr(sn_c, campo), campo
    # Poblados de verdad (no quedaron en el vacío de Snapshot.__init__ por error):
    # en este escenario hay disponibles y hay jaulas paradas en algún instante.
    assert any(s.cantidad_disponibles > 0 for s in ligero.snapshots)
    assert any(s.jaulas_paradas for s in ligero.snapshots)


def test_campos_pesados_vacios_en_liviano(talleres):
    """Todo campo FUERA del registro queda en su vacío de Snapshot.__init__
    (detecta si alguien vuelve a computarlos en liviano sin querer). La lista
    de campos pesados se deriva del propio Snapshot, no se duplica a mano."""
    _, ligero = talleres
    for sn in ligero.snapshots:
        vacio = Snapshot(sn.tiempo)  # referencia: los defaults de __init__
        for campo, valor_defecto in vacio.__dict__.items():
            if campo in CAMPOS_SNAPSHOT_KPI:
                continue
            assert getattr(sn, campo) == valor_defecto, campo


# ── 3. Wiring Monte Carlo: liviano salvo dump_dir ────────────────────────────

def _preparar_worker_mc(dump_dir):
    """Ejecuta el initializer del pool en este mismo proceso (estado module-level)."""
    from nucleo import montecarlo as mc
    from tests.test_montecarlo import _cfg, _modelo, _spec, _stock

    cfg = _cfg()
    mc.init_worker_montecarlo(cfg, _stock(), _modelo(cfg), _spec(cfg, runs=1),
                              dump_dir=dump_dir)
    return mc


def test_worker_mc_con_dump_dir_snapshots_completos(tmp_path):
    """Con dump_dir el worker NO usa liviano: el pickle sirve para playback."""
    dump = str(tmp_path / "dump")
    os.makedirs(dump)
    mc = _preparar_worker_mc(dump)
    fila_dump = mc.simular_montecarlo_worker(0)

    with open(os.path.join(dump, "run_000000.pkl"), "rb") as fp:
        taller = pickle.load(fp)
    assert taller.snapshot_ligero is False
    assert taller.snapshots
    # Detalle de playback presente (campo pesado poblado) en el último snapshot.
    assert taller.snapshots[-1].conteo_por_estado
    assert taller.snapshots[-1].detalle_maquinas

    # Sin dump_dir el worker usa liviano y las métricas son las mismas.
    mc = _preparar_worker_mc(None)
    fila_ligera = mc.simular_montecarlo_worker(0)
    assert fila_ligera == fila_dump


# ── 4. Flag: default y picklabilidad ─────────────────────────────────────────

def test_flag_default_false_y_picklable(talleres):
    assert TallerCilindros().snapshot_ligero is False
    _, ligero = talleres
    clon = pickle.loads(pickle.dumps(ligero))
    assert clon.snapshot_ligero is True
    assert len(clon.snapshots) == len(ligero.snapshots)
