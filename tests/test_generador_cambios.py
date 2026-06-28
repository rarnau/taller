"""Pruebas del generador sintético de Programa_Cambios.

Cubre ``models.change_generator`` (ajuste/persistencia del modelo, determinismo
por seed, esquema de salida, alineación a turnos y umbral de desbaste) y los
getters/mutadores nuevos de ``config.persistencia``.
"""
import os
import sys
from datetime import datetime

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import persistencia as p
from models import change_generator as g
from models import shifts as t
from models.workshop import CylinderWorkshop

_INICIO = datetime(2026, 1, 5, 6, 0, 0)  # lunes 06:00


def _historia():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "historia_ejemplo.csv")
    return pd.read_csv(ruta)


def _cfg():
    return p.cargar_config()


# ── Persistencia / adaptación ────────────────────────────────────────────────

def test_ajuste_desde_cero_cuenta_filas():
    hist, cfg = _historia(), _cfg()
    m = g.fit_model(hist, cfg, key="empirico")
    assert m["clave"] == "empirico"
    assert m["n_filas"] == len(hist)
    assert sorted(m["jaulas"]) == ["1", "2", "3", "4"]


def test_refit_incremental_acumula():
    hist, cfg = _historia(), _cfg()
    m1 = g.fit_model(hist, cfg, key="empirico")
    m2 = g.fit_model(hist, cfg, key="empirico", prior_model=m1)
    assert m2["n_filas"] == 2 * m1["n_filas"]
    # las muestras por jaula también se duplican
    assert len(m2["jaulas"]["1"]["duracion"]) == 2 * len(m1["jaulas"]["1"]["duracion"])


def test_refit_no_mezcla_claves_distintas():
    hist, cfg = _historia(), _cfg()
    emp = g.fit_model(hist, cfg, key="empirico")
    # ajustar markov con un modelo previo empírico ⇒ arranca de cero (no mezcla)
    mk = g.fit_model(hist, cfg, key="markov", prior_model=emp)
    assert mk["clave"] == "markov"
    assert mk["n_filas"] == len(hist)
    assert "transiciones" in mk["jaulas"]["1"]


def test_markov_conteos_acumulan_en_refit():
    hist, cfg = _historia(), _cfg()
    m1 = g.fit_model(hist, cfg, key="markov")
    m2 = g.fit_model(hist, cfg, key="markov", prior_model=m1)
    tot1 = sum(sum(d.values()) for d in m1["jaulas"]["1"]["transiciones"].values())
    tot2 = sum(sum(d.values()) for d in m2["jaulas"]["1"]["transiciones"].values())
    assert tot2 == 2 * tot1


def test_persistencia_round_trip(tmp_path, monkeypatch):
    from config import modelo_generador as mg
    monkeypatch.setattr(mg, "MODELO_PATH", str(tmp_path / "modelo.json"))
    assert mg.cargar_modelo() is None
    m = g.fit_model(_historia(), _cfg(), key="empirico")
    mg.guardar_modelo(m)
    assert mg.cargar_modelo() == m
    mg.reiniciar_modelo()
    assert mg.cargar_modelo() is None


# ── Ventana de generación (fecha_inicio / fecha_fin) ─────────────────────────

def test_ventana_fechas_del_cfg():
    cfg = _cfg()
    p.set_generador_cambios(cfg, fecha_inicio="2026-01-05", fecha_fin="2026-01-12")
    m = g.fit_model(_historia(), cfg, key="empirico")
    df = g.generate_changes(m, cfg, seed=7)  # sin inicio/fin: los toma del cfg
    fechas = pd.to_datetime(df["Fecha_Hora"])
    assert (fechas >= pd.Timestamp("2026-01-05")).all()
    assert (fechas < pd.Timestamp("2026-01-12")).all()


def test_fin_explicito_pisa_cfg():
    cfg = _cfg()
    p.set_generador_cambios(cfg, fecha_inicio="2026-01-05", fecha_fin="2026-02-01")
    m = g.fit_model(_historia(), cfg, key="empirico")
    corto = g.generate_changes(m, cfg, seed=7, start=_INICIO, end=datetime(2026, 1, 8))
    assert (pd.to_datetime(corto["Fecha_Hora"]) < pd.Timestamp("2026-01-08")).all()


# ── Determinismo ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("clave", ["empirico", "markov"])
def test_misma_seed_mismo_dataframe(clave):
    cfg = _cfg()
    m = g.fit_model(_historia(), cfg, key=clave)
    a = g.generate_changes(m, cfg, seed=123, start=_INICIO)
    b = g.generate_changes(m, cfg, seed=123, start=_INICIO)
    assert a.equals(b)


def test_seeds_distintas_difieren():
    cfg = _cfg()
    m = g.fit_model(_historia(), cfg, key="empirico")
    a = g.generate_changes(m, cfg, seed=1, start=_INICIO)
    c = g.generate_changes(m, cfg, seed=2, start=_INICIO)
    assert not a.equals(c)


# ── Esquema de salida ────────────────────────────────────────────────────────

def test_columnas_y_carga_en_simulador():
    cfg = _cfg()
    m = g.fit_model(_historia(), cfg, key="empirico")
    df = g.generate_changes(m, cfg, seed=7, start=_INICIO)
    assert list(df.columns) == g.OUTPUT_COLUMNS
    assert len(df) > 0

    # El DataFrame pasa por el cargador del motor sin error.
    stock = pd.read_excel(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "simulacion_caso_parada.xlsx"),
        sheet_name="Stock_Inicial")
    taller = CylinderWorkshop()
    taller.configure(cfg)
    taller.load_data_from_dataframes(stock, df)
    assert len(taller.scheduled_events) == len(df)


# ── Alineación a turnos ──────────────────────────────────────────────────────

def test_24x7_cae_en_fronteras():
    cfg = _cfg()
    m = g.fit_model(_historia(), cfg, key="empirico")
    df = g.generate_changes(m, cfg, seed=5, start=_INICIO)  # turnos_cambios None ⇒ 24/7
    assert {x.hour for x in df["Fecha_Hora"]} <= {6, 14, 22}


def test_turnos_con_huecos_salta_gap():
    cfg = _cfg()
    p.set_turnos_cambios(cfg, t.parse_compact("100 100 100 100 100 000 000"))
    m = g.fit_model(_historia(), cfg, key="empirico")
    grilla = g.change_grid_from_cfg(cfg)
    df = g.get_generator("empirico").generate(
        m, cfg, seed=5, start=_INICIO, horizon_days=14, change_grid=grilla)
    assert all(x.hour == 6 for x in df["Fecha_Hora"])   # sólo T1 operativo
    assert all(x.weekday() < 5 for x in df["Fecha_Hora"])  # sin fines de semana


# ── Umbral de desbaste ───────────────────────────────────────────────────────

def test_umbral_clasifica_tipo():
    assert g._type_from_roughing(5.0, 1.0) == "desbaste"
    assert g._type_from_roughing(0.8, 1.0) == "produccion"
    assert g._type_from_roughing(1.0, 1.0) == "produccion"  # límite inclusivo abajo


def test_umbral_en_salida():
    cfg = _cfg()
    m = g.fit_model(_historia(), cfg, key="empirico")
    df = g.generate_changes(m, cfg, seed=123, start=_INICIO)
    umbral = p.obtener_generador_cambios(cfg)["umbral_desbaste_mm"]
    for _, row in df.iterrows():
        esperado = "desbaste" if row["mm_a_Rectificar"] > umbral else "produccion"
        assert row["Tipo_Rectificado"] == esperado


# ── Registro ─────────────────────────────────────────────────────────────────

def test_registro_tiene_ambos_generadores():
    assert set(g.CHANGE_GENERATORS) >= {"empirico", "markov"}
    assert g.DEFAULT_GENERATOR in g.CHANGE_GENERATORS
