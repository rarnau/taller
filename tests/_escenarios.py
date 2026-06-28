"""Regression scenario definitions and computation of their *fingerprint*.

This module is the shared source of truth between:
  - ``_generar_golden.py`` (regenerates the reference JSON on purpose), and
  - ``test_regresion.py`` (compares the current run against that JSON).

A *fingerprint* is a 100% serializable, deterministic dict summarizing a
simulation result (KPIs, number of snapshots, alerts, final state of each
cylinder and a hash of the full content of all snapshots). If an engine
refactor preserves behavior, all fingerprints must stay identical.

Note: the scenario names, the fingerprint output dict keys, the enum string
values and the alert message text stay in Spanish on purpose — they are the
golden-master contract.
"""
import hashlib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.persistencia import cargar_config
from models.kpis import compute_kpis
from models.workshop import CylinderWorkshop

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_master.json")

# Each scenario: name -> {excel, strategy, cooling}
SCENARIOS = {
    "parada_mayor_diametro": {
        "excel": "simulacion_caso_parada.xlsx", "strategy": "mayor_diametro", "cooling": 0.0,
    },
    "parada_fifo": {
        "excel": "simulacion_caso_parada.xlsx", "strategy": "fifo", "cooling": 0.0,
    },
    "parada_enfriado_8h": {
        "excel": "simulacion_caso_parada.xlsx", "strategy": "mayor_diametro", "cooling": 8.0,
    },
    "cils140_mayor_diametro": {
        "excel": "simulacion_140cils_1semana.xlsx", "strategy": "mayor_diametro", "cooling": 0.0,
    },
    "cils140_menor_mm_desb": {
        "excel": "simulacion_140cils_1semana.xlsx", "strategy": "menor_mm_desb_fifo_prod", "cooling": 0.0,
    },
    # Overlapping bands + profiles: stands 2 and 3 share profile "2" with ranges
    # that overlap, so the assignment strategy chooses among candidates. Brings
    # its own config (independent of user_config.json) via "cfg".
    "perfiles_jaula_mas_necesitada": {
        "excel": "simulacion_caso_perfiles.xlsx", "strategy": "mayor_diametro",
        "cooling": 0.0, "cfg": "perfiles",
    },
}


def _profiles_cfg() -> dict:
    """Self-contained config with overlapping bands + profiles (see generate_profiles_case.py)."""
    cfg = cargar_config()
    cfg["config_global"] = {
        "diametro_maximo": 575.0, "diametro_minimo": 520.0,
        "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 4,
    }
    cfg["rangos"] = [
        {"jaula": 1, "desde": 540.0, "hasta": 520.0, "perfil": "4"},
        {"jaula": 2, "desde": 555.0, "hasta": 530.0, "perfil": "2"},
        {"jaula": 3, "desde": 565.0, "hasta": 540.0, "perfil": "2"},
        {"jaula": 4, "desde": 575.0, "hasta": 555.0, "perfil": "3"},
    ]
    cfg["estrategia_asignacion"] = "jaula_mas_necesitada"
    return cfg


def run_scenario(esc: dict) -> CylinderWorkshop:
    """Build and simulate a workshop for a given scenario (no GUI, no extra I/O)."""
    cfg = _profiles_cfg() if esc.get("cfg") == "perfiles" else cargar_config()
    cfg["tiempo_enfriado_h"] = esc["cooling"]
    workshop = CylinderWorkshop()
    workshop.configure(cfg)
    workshop.load_data(os.path.join(_DATA_DIR, esc["excel"]))
    workshop.simulate(strategy=esc["strategy"], callback_log=None)
    return workshop


def serialize_snapshots(workshop: CylinderWorkshop) -> list:
    """Canonical, full serialization of ALL the run's snapshots.

    Dumps *all* fields of each ``Snapshot`` —exactly the data the GUI consumes
    for playback: counts by state and by SubStock, stand, CRC, machine,
    grinding-queue and cooling detail—. Uses ``__dict__`` so any new Snapshot
    field is covered automatically.
    """
    out = []
    for sn in workshop.snapshots:
        out.append({k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in sn.__dict__.items()})
    return out


def digest_snapshots(workshop: CylinderWorkshop) -> str:
    """sha256 hash of the canonical serialization of the snapshots.

    It is the safety net for the data the GUI sees: any change in any field of
    any snapshot (order included in the detail lists) moves the hash.
    ``sort_keys`` normalizes the dict key order (the GUI accesses by key); the
    list order is preserved.
    """
    data = json.dumps(serialize_snapshots(workshop), sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def fingerprint(workshop: CylinderWorkshop) -> dict:
    """Deterministic, serializable summary of a simulation result."""
    k = compute_kpis(workshop)
    return {
        "kpis": {
            "cilindros_totales": k["cilindros_totales"],
            "activos": k["activos"],
            "bajas": k["bajas"],
            "alertas_criticas": k["alertas_criticas"],
            "cambios_programados": k["cambios_programados"],
            "rectificados_realizados": k["rectificados_realizados"],
            "horizonte_simulacion_h": round(k["horizonte_simulacion_h"], 4),
            "diametro_promedio_mm": round(k["diametro_promedio_mm"], 4),
            "desgaste_medio_mm": round(k["desgaste_medio_mm"], 4),
            "utilizacion_maquinas_pct": {
                m: round(v, 4) for m, v in k["utilizacion_maquinas_pct"].items()
            },
        },
        "n_snapshots": len(workshop.snapshots),
        "n_alertas": len(workshop.alerts),
        "alertas": [
            {"tiempo": a.time.isoformat(), "tipo": a.type, "mensaje": a.message, "jaula": a.stand}
            for a in workshop.alerts
        ],
        "cilindros": sorted(
            [c.id, c.state.value, round(c.diameter, 2)] for c in workshop.cylinders.values()
        ),
        # Hash of the full content of all snapshots (the GUI data).
        "snapshots_sha256": digest_snapshots(workshop),
    }


def fingerprint_all() -> dict:
    """Run all scenarios and return {name: fingerprint}."""
    return {name: fingerprint(run_scenario(esc)) for name, esc in SCENARIOS.items()}
