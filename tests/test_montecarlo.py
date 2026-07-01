"""Runner Monte Carlo: muestreo, aplicación al cfg, determinismo y reanudación.

Fija las invariantes del barrido de miles de corridas (``montecarlo.py``):
- el muestreo cae dentro de los rangos y ``aplicar_a_cfg`` traduce rates→mm;
- mismo ``master_seed`` ⇒ mismas filas (seed derivada por corrida, paralelo);
- reanudar desde el CSV completa el set sin recomputar y reproduce el full;
- ``resumir`` coincide con numpy.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from modelos import generador_cambios as gencambios
from nucleo.montecarlo import (EspecMonteCarlo, aplicar_a_cfg, correr_montecarlo,
                        muestrear_overrides, resumir, _seed_corrida)

_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 0.8, "tiempo_min": 60.0},
                   "desbaste": {"mm": 5.0, "tiempo_min": 480.0}}}]


def _cfg():
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 520.0}],
        "maquinas": [dict(m) for m in _MAQ],
    }


def _stock():
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


def _modelo(cfg):
    """Modelo empírico ajustado a una historia sintética de la jaula 1."""
    historia = pd.DataFrame({
        "Jaula": [1, 1, 1, 1, 1, 1],
        "Duracion_h": [20.0, 30.0, 24.0, 40.0, 18.0, 28.0],
        "Desbaste_mm": [0.8, 5.0, 1.0, 6.0, 0.9, 4.0],
        "Fecha_Salida": pd.to_datetime(
            ["2026-01-02", "2026-01-04", "2026-01-06",
             "2026-01-08", "2026-01-10", "2026-01-12"]),
    })
    return gencambios.ajustar_modelo(historia, cfg, clave="empirico")


def _spec(cfg, runs, seed=123, chunk=2):
    spec = EspecMonteCarlo.desde_cfg(cfg)
    spec.runs = runs
    spec.master_seed = seed
    spec.chunk = chunk
    return spec


def _por_run(filas):
    return {int(r["run"]): r for r in filas}


def _assert_filas_iguales(a, b):
    assert set(a) == set(b)
    for k in a:
        if isinstance(a[k], float) or isinstance(b[k], float):
            assert float(a[k]) == pytest.approx(float(b[k]))
        else:
            assert a[k] == b[k]


# ── 1. Seed derivada ─────────────────────────────────────────────────────────

def test_seed_corrida_determinista_y_distinta():
    assert _seed_corrida(123, 0) == _seed_corrida(123, 0)
    assert _seed_corrida(123, 0) != _seed_corrida(123, 1)
    assert _seed_corrida(123, 5) != _seed_corrida(124, 5)


# ── 2. Muestreo y aplicación al cfg ──────────────────────────────────────────

def test_muestrear_en_rango():
    cfg = _cfg()
    spec = _spec(cfg, runs=1)
    rng = np.random.default_rng(7)
    ov = muestrear_overrides(spec, rng)
    r = spec.rangos
    assert r["tiempo_enfriado"][0] <= ov["tiempo_enfriado"] <= r["tiempo_enfriado"][1]
    assert r["tiempo_traslado_crc"][0] <= ov["tiempo_traslado_crc"] <= r["tiempo_traslado_crc"][1]
    mr = r["maquinas"]["G"]
    mo = ov["maquinas"]["G"]
    assert mr["rate_prod"][0] <= mo["rate_prod"] <= mr["rate_prod"][1]
    assert mr["tasa_falla"][0] <= mo["tasa_falla"] <= mr["tasa_falla"][1]


def test_aplicar_a_cfg_traduce_rate_a_mm():
    cfg = _cfg()
    spec = _spec(cfg, runs=1)
    spec.fijos["estrategia_seleccion"] = "mayor_diametro"
    overrides = {
        "tiempo_enfriado": 3.0,
        "tiempo_traslado_crc": 22.0,
        "maquinas": {"G": {"rate_prod": 0.01, "rate_desb": 0.02, "tasa_falla": 0.0}},
    }
    out = aplicar_a_cfg(cfg, overrides, spec)
    assert out["tiempo_enfriado_h"] == 3.0
    assert out["config_global"]["tiempo_traslado_crc_min"] == 22.0
    maq = next(m for m in out["maquinas"] if m["nombre"] == "G")
    # mm = rate × tiempo_min (tiempo_min se conserva del base)
    assert maq["tasas"]["produccion"]["mm"] == pytest.approx(0.01 * 60.0)
    assert maq["tasas"]["desbaste"]["mm"] == pytest.approx(0.02 * 480.0)
    # el cfg base no se muta
    assert cfg["maquinas"][0]["tasas"]["produccion"]["mm"] == 0.8


# ── 3. Determinismo en paralelo ──────────────────────────────────────────────

def test_correr_determinista(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    a = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=4),
                          csv_path=str(tmp_path / "a.csv"), max_workers=2)
    b = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=4),
                          csv_path=str(tmp_path / "b.csv"), max_workers=2)
    pa, pb = _por_run(a), _por_run(b)
    assert set(pa) == set(pb) == {0, 1, 2, 3}
    for i in pa:
        _assert_filas_iguales(pa[i], pb[i])


# ── 4. Reanudación desde el CSV ──────────────────────────────────────────────

def test_resume_completa_y_reproduce(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")

    # Corrida parcial (3) y luego reanudación a 6 sobre el mismo CSV/seed.
    correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=3),
                      csv_path=csv_path, max_workers=2)
    reanudado = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=6),
                                  csv_path=csv_path, resume=True, max_workers=2)
    # Referencia: 6 corridas frescas con el mismo master seed.
    full = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=6),
                             csv_path=str(tmp_path / "full.csv"), max_workers=2)

    pr, pf = _por_run(reanudado), _por_run(full)
    assert set(pr) == set(pf) == {0, 1, 2, 3, 4, 5}
    for i in pr:
        _assert_filas_iguales(pr[i], pf[i])


def test_resume_master_seed_distinto_falla(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")
    correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=2, seed=1),
                      csv_path=csv_path, max_workers=2)
    with pytest.raises(ValueError):
        correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=4, seed=999),
                          csv_path=csv_path, resume=True, max_workers=2)


# ── 5. Agregación ────────────────────────────────────────────────────────────

def test_resumir_coincide_con_numpy(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    filas = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=5),
                              csv_path=str(tmp_path / "mc.csv"), max_workers=2)
    resumen = resumir(filas)
    assert "bajas" in resumen and "parada_pct" in resumen
    vals = np.array([float(r["bajas"]) for r in filas])
    assert resumen["bajas"]["mean"] == pytest.approx(float(np.mean(vals)))
    assert resumen["bajas"]["p50"] == pytest.approx(float(np.percentile(vals, 50)))
    # identificadores e inputs sorteados no se resumen
    assert "run" not in resumen and "in_tiempo_enfriado" not in resumen
