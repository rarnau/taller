"""Sets de Monte Carlo: sidecar de spec, pausa/reanudación y parciales.

Fija las invariantes de la gestión de sets (``nucleo/montecarlo.py``):
- la spec del set (rangos/fijos/seed) se persiste en ``<csv>.spec.json`` y su
  carga es un round-trip fiel (con el master seed ya resuelto);
- pausar con ``cancelar`` corta limpio y reanudar completa el set con filas
  idénticas a una corrida sin pausa (determinismo por seed derivada);
- extender ``runs`` sobre el mismo CSV agrega corridas sin recomputar las hechas;
- reanudar con otros rangos/fijos que los del sidecar es un error;
- ``on_parcial`` entrega acumulados crecientes hasta el total;
- ``aplicar_a_cfg`` respeta los fijos nuevos (estrategia de reposición y
  prioridad por máquina).
"""
import threading

import pytest

from config.persistencia import (obtener_estrategia_reposicion, obtener_maquinas,
                                 obtener_prioridades)
from nucleo.montecarlo import (aplicar_a_cfg, cargar_filas_csv, cargar_spec_sidecar,
                               correr_montecarlo, guardar_spec_sidecar,
                               ruta_spec_sidecar)
from tests.test_montecarlo import (_assert_filas_iguales, _cfg, _modelo, _por_run,
                                   _spec, _stock)


# ── 1. Sidecar de spec ───────────────────────────────────────────────────────

def test_sidecar_se_escribe_y_roundtrip(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")
    spec = _spec(cfg, runs=2, seed=11)
    correr_montecarlo(cfg, _stock(), modelo, spec, csv_path=csv_path, max_workers=2)

    cargada = cargar_spec_sidecar(csv_path)
    assert cargada is not None
    assert cargada.runs == 2
    assert cargada.master_seed == 11  # ya resuelto (no None)
    # Round-trip del espacio de muestreo (normalizado a tipos JSON).
    import json
    norm = lambda x: json.loads(json.dumps(x))  # noqa: E731
    assert norm(cargada.rangos) == norm(spec.rangos)
    assert norm(cargada.fijos) == norm(spec.fijos)


def test_cargar_spec_sidecar_inexistente(tmp_path):
    assert cargar_spec_sidecar(str(tmp_path / "no_existe.csv")) is None


def test_cargar_filas_csv_publico(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")
    filas = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=3, seed=5),
                              csv_path=csv_path, max_workers=2)
    leidas = cargar_filas_csv(csv_path)
    assert [int(r["run"]) for r in leidas] == [0, 1, 2]
    pa, pb = _por_run(filas), _por_run(leidas)
    for i in pa:
        _assert_filas_iguales(pa[i], pb[i])
    assert cargar_filas_csv(str(tmp_path / "no_existe.csv")) == []


# ── 2. Pausa (cancelar) + reanudación == corrida completa ────────────────────

def test_pausa_y_reanudacion_reproduce_el_full(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")

    # Pausa disparada apenas hay avance: el Event se setea desde on_progress
    # (mismo mecanismo cooperativo que usa el botón de la GUI).
    cancelar = threading.Event()
    spec = _spec(cfg, runs=6, seed=77, chunk=1)

    def _pausar_pronto(hechos, total):
        if hechos >= 2:
            cancelar.set()

    parciales = correr_montecarlo(cfg, _stock(), modelo, spec, csv_path=csv_path,
                                  max_workers=2, cancelar=cancelar,
                                  on_progress=_pausar_pronto)
    assert 0 < len(parciales) < 6          # cortó antes de completar
    assert len(cargar_filas_csv(csv_path)) == len(parciales)  # lo hecho quedó en el CSV

    # Reanudar completa el set; el resultado es idéntico al full sin pausa.
    reanudado = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=6, seed=77, chunk=1),
                                  csv_path=csv_path, resume=True, max_workers=2)
    full = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=6, seed=77, chunk=1),
                             csv_path=str(tmp_path / "full.csv"), max_workers=2)
    pr, pf = _por_run(reanudado), _por_run(full)
    assert set(pr) == set(pf) == {0, 1, 2, 3, 4, 5}
    for i in pr:
        _assert_filas_iguales(pr[i], pf[i])


def test_extender_runs_agrega_corridas(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")
    primeras = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=3, seed=9),
                                 csv_path=csv_path, max_workers=2)
    extendidas = correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=5, seed=9),
                                   csv_path=csv_path, resume=True, max_workers=2)
    assert {int(r["run"]) for r in extendidas} == {0, 1, 2, 3, 4}
    # Las 3 originales no se recomputaron distinto.
    pa, pb = _por_run(primeras), _por_run(extendidas)
    for i in pa:
        _assert_filas_iguales(pa[i], pb[i])
    # El sidecar refleja el nuevo total del set.
    assert cargar_spec_sidecar(csv_path).runs == 5


def test_reanudar_con_otro_espacio_falla(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    csv_path = str(tmp_path / "mc.csv")
    correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=2, seed=3),
                      csv_path=csv_path, max_workers=2)

    otra = _spec(cfg, runs=4, seed=3)
    otra.rangos = dict(otra.rangos)
    otra.rangos["tiempo_enfriado"] = [1.0, 9.0]  # espacio distinto
    with pytest.raises(ValueError, match="otros rangos"):
        correr_montecarlo(cfg, _stock(), modelo, otra,
                          csv_path=csv_path, resume=True, max_workers=2)


# ── 3. Parciales ─────────────────────────────────────────────────────────────

def test_on_parcial_acumula_hasta_el_total(tmp_path):
    cfg = _cfg()
    modelo = _modelo(cfg)
    llamadas = []
    correr_montecarlo(cfg, _stock(), modelo, _spec(cfg, runs=4, seed=21, chunk=2),
                      csv_path=str(tmp_path / "mc.csv"), max_workers=2,
                      on_parcial=lambda filas, hechos, total:
                          llamadas.append((len(filas), hechos, total)))
    assert llamadas, "on_parcial nunca se llamó"
    ns = [n for n, _, _ in llamadas]
    assert ns == sorted(ns)                      # acumulado creciente
    assert llamadas[-1] == (4, 4, 4)             # el último trae el set completo
    for n, hechos, total in llamadas:
        assert n == hechos and total == 4


# ── 4. Fijos nuevos en aplicar_a_cfg ─────────────────────────────────────────

def test_aplicar_a_cfg_reposicion_y_prioridad():
    cfg = _cfg()
    spec = _spec(cfg, runs=1)
    spec.fijos["estrategia_reposicion"] = "lote_4_mensual"
    spec.fijos["prioridad_por_maquina"] = {"G": "desbaste"}
    overrides = {"tiempo_enfriado": 0.0, "tiempo_traslado_crc": 10.0, "maquinas": {}}
    out = aplicar_a_cfg(cfg, overrides, spec)
    assert obtener_estrategia_reposicion(out) == "lote_4_mensual"
    assert obtener_prioridades(out)["G"] == "desbaste"
    # Prioridad inválida o de máquina inexistente: se ignora sin romper.
    spec.fijos["prioridad_por_maquina"] = {"G": "cualquiera", "NO_EXISTE": "desbaste"}
    out2 = aplicar_a_cfg(cfg, overrides, spec)
    assert obtener_prioridades(out2)["G"] == "produccion"  # la del cfg base
    # El cfg base nunca se muta.
    assert obtener_maquinas(cfg)[0].get("prioridad") == "produccion"
