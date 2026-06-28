"""Synthetic ``Programa_Cambios`` generators learned from history.

A **pure** domain module (no GUI, no simulation state): from a real campaign
history (one row = one pair that worked in a stand for some time and was roughed
some mm), it **fits** a per-stand model and then **generates** a reproducible
``Programa_Cambios`` by *seed*.

The design separates two steps (like ``sklearn``):

- ``fit(history_df, cfg, *, prior_model=None) -> dict``: produces a serializable
  model. With a ``prior_model`` of the same ``key`` it **accumulates** over it
  (incremental refit); with ``None`` it fits **from scratch**. The model is
  persisted with ``config.modelo_generador``.
- ``generate(model, cfg, *, seed, ...) -> pandas.DataFrame``: samples campaigns
  per stand until it covers the horizon. All randomness goes through a
  ``numpy.random.default_rng(seed)``, so the same seed ⇒ the same DataFrame. No
  module state: safe for thousands of parallel simulations.

Each change is aligned to the **mill shift regime**: the teardown lands at the
end of a shift and the mount at the first hour of the next operative shift
(``models.shifts.next_shift_boundary`` + ``next_operative_start``).

Two generators are registered in ``CHANGE_GENERATORS`` (a pattern mirrored from
``models.strategies``): ``empirico`` (empirical per-stand distributions) and
``markov`` (a Markov chain over duration buckets capturing the correlation
between consecutive campaigns). To add a new one: subclass ``ChangeGenerator``
and register it; the GUI and the CLI read it from there.

Note: the persisted model dict keys, the normalized field labels, the alias
synonyms and the Excel output columns stay in Spanish on purpose — they are
persistence / data contracts.
"""
from __future__ import annotations

import copy
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import persistencia as cfgmod
from models import shifts as shifts_mod

# Exact columns the simulator expects (see CylinderWorkshop._load_changes).
OUTPUT_COLUMNS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                  "mm_a_Rectificar", "Observación"]

# Default horizon start if none is given: Monday 06:00 (T1 boundary).
_DEFAULT_START = datetime(2026, 1, 5, 6, 0, 0)

# Duration bucket edges (hours) for the Markov chain.
_DURATION_EDGES_H = [12.0, 24.0, 48.0, 72.0]


# ── History normalization ────────────────────────────────────────────────────

def _norm_key(s: Any) -> str:
    """Normalize a column name: lowercase, no accents or symbols."""
    txt = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(c for c in txt.lower() if c.isalnum())


# Accepted synonyms per logical field (keys already normalized with _norm_key).
_ALIASES = {
    "jaula": {"jaula"},
    "duracion_h": {"duracionhs", "duracion", "duracionh", "duracionhoras", "horas"},
    "desbaste_mm": {"desbaste", "desbastemm", "mmarectificar"},
    "fecha_ingreso": {"fechaingreso", "ingreso"},
    "fecha_salida": {"fechasalida", "salida"},
    "diametro": {"diametro", "diametromm"},
}


def _map_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Map logical field → real column name present in ``df``."""
    present = {_norm_key(c): c for c in df.columns}
    result: Dict[str, str] = {}
    for field, aliases in _ALIASES.items():
        for a in aliases:
            if a in present:
                result[field] = present[a]
                break
    return result


def _normalize_history(history_df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """Return a normalized DataFrame with columns jaula/duracion_h/desbaste_mm.

    Tolerates the accented names of the real history. Derives ``duracion_h`` from
    the dates if the duration column is missing. Drops rows without a stand or a
    valid duration.
    """
    cols = _map_columns(history_df)
    if "jaula" not in cols:
        raise ValueError("La historia no tiene una columna 'Jaula' reconocible.")

    out = pd.DataFrame()
    out["jaula"] = pd.to_numeric(history_df[cols["jaula"]], errors="coerce")

    if "duracion_h" in cols:
        out["duracion_h"] = pd.to_numeric(history_df[cols["duracion_h"]], errors="coerce")
    elif "fecha_ingreso" in cols and "fecha_salida" in cols:
        entry = pd.to_datetime(history_df[cols["fecha_ingreso"]], errors="coerce")
        exit_ = pd.to_datetime(history_df[cols["fecha_salida"]], errors="coerce")
        out["duracion_h"] = (exit_ - entry).dt.total_seconds() / 3600.0
    else:
        raise ValueError("La historia no tiene duración ni fechas para derivarla.")

    if "desbaste_mm" in cols:
        out["desbaste_mm"] = pd.to_numeric(history_df[cols["desbaste_mm"]], errors="coerce")
    else:
        out["desbaste_mm"] = np.nan

    if "fecha_salida" in cols:
        out["fecha_salida"] = pd.to_datetime(history_df[cols["fecha_salida"]], errors="coerce")
    elif "fecha_ingreso" in cols:
        out["fecha_salida"] = pd.to_datetime(history_df[cols["fecha_ingreso"]], errors="coerce")
    else:
        out["fecha_salida"] = pd.NaT

    out = out.dropna(subset=["jaula", "duracion_h"])
    out = out[out["duracion_h"] > 0]
    out["jaula"] = out["jaula"].astype(int)
    # Missing roughing: imputed with the configured threshold (kept as marginal
    # 'desbaste') so the row is not lost; rarely happens with real data.
    threshold = float(cfgmod.obtener_generador_cambios(cfg)["umbral_desbaste_mm"])
    out["desbaste_mm"] = out["desbaste_mm"].fillna(threshold)
    return out.reset_index(drop=True)


def _type_from_roughing(mm: float, threshold: float) -> str:
    """Classify the grinding type by the mm-to-rough threshold."""
    return "desbaste" if float(mm) > float(threshold) else "produccion"


def _duration_bucket(h: float) -> str:
    """Duration bucket label (for the Markov chain state)."""
    for i, e in enumerate(_DURATION_EDGES_H):
        if h < e:
            return f"d{i}"
    return f"d{len(_DURATION_EDGES_H)}"


def resolve_seed(seed: Optional[int]) -> int:
    """Return a concrete seed (reproducible-random if ``seed is None``)."""
    if seed is not None:
        return int(seed)
    return int(np.random.SeedSequence().generate_state(1)[0])


# ── Generators ───────────────────────────────────────────────────────────────

class ChangeGenerator:
    """Base: fits a per-stand model and generates a reproducible Programa_Cambios."""

    key: str = ""
    label: str = ""
    description: str = ""

    # -- Fit -----------------------------------------------------------------
    def _empty_stand_model(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _accumulate_stand(self, mj: Dict[str, Any], group: pd.DataFrame,
                          cfg: Dict[str, Any]) -> None:
        raise NotImplementedError

    def fit(self, history_df: pd.DataFrame, cfg: Dict[str, Any], *,
            prior_model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fit (or incrementally refine) the model from the history."""
        norm = _normalize_history(history_df, cfg)

        if prior_model and prior_model.get("clave") == self.key:
            model = copy.deepcopy(prior_model)
        else:
            model = {"clave": self.key, "n_filas": 0,
                     "fecha_min": None, "fecha_max": None, "jaulas": {}}

        model["n_filas"] = int(model.get("n_filas", 0)) + len(norm)
        dates = norm["fecha_salida"].dropna()
        if not dates.empty:
            fmin, fmax = dates.min().isoformat(), dates.max().isoformat()
            model["fecha_min"] = min(filter(None, [model.get("fecha_min"), fmin]))
            model["fecha_max"] = max(filter(None, [model.get("fecha_max"), fmax]))

        for stand, group in norm.groupby("jaula"):
            mj = model["jaulas"].setdefault(str(int(stand)), self._empty_stand_model())
            self._accumulate_stand(mj, group, cfg)
        return model

    # -- Generation ----------------------------------------------------------
    def _sample_campaign(self, rng, mj: Dict[str, Any],
                         prev_state: Optional[str]) -> tuple:
        """Return (duracion_h, desbaste_mm, new_state) for the stand."""
        raise NotImplementedError

    def generate(self, model: Dict[str, Any], cfg: Dict[str, Any], *,
                 seed: Optional[int] = None, start: Optional[datetime] = None,
                 end: Optional[datetime] = None,
                 horizon_days: Optional[int] = None,
                 change_grid: Optional[List[List[bool]]] = None) -> pd.DataFrame:
        """Generate the ``Programa_Cambios`` by sampling campaigns per stand.

        The window ``[start, end)`` is resolved, in priority order: explicit
        arguments → ``fecha_inicio``/``fecha_fin`` from the cfg → legacy
        ``horizonte_dias`` (days from ``start``) → 7 days from ``_DEFAULT_START``.
        """
        gc = cfgmod.obtener_generador_cambios(cfg)
        cg = cfgmod.obtener_config_global(cfg)
        threshold = float(gc["umbral_desbaste_mm"])
        stand_count = int(cg["cantidad_jaulas"])

        seed = resolve_seed(seed)
        rng = np.random.default_rng(seed)

        if start is None and gc.get("fecha_inicio"):
            start = pd.to_datetime(gc["fecha_inicio"]).to_pydatetime()
        if start is None:
            start = _DEFAULT_START
        # Precedence of ``end``: explicit arg → explicit horizon_days →
        # cfg.fecha_fin → cfg.horizonte_dias legacy → 7 days. An explicit horizon
        # beats the persisted date (avoids inverted windows).
        if end is None and horizon_days is not None:
            end = start + timedelta(days=int(horizon_days))
        if end is None and gc.get("fecha_fin"):
            end = pd.to_datetime(gc["fecha_fin"]).to_pydatetime()
        if end is None:
            end = start + timedelta(days=int(gc.get("horizonte_dias", 7)))

        rows: List[Dict[str, Any]] = []
        stand_models = model.get("jaulas", {})
        for stand in range(1, stand_count + 1):
            mj = stand_models.get(str(stand))
            if not mj:
                continue  # no history for that stand ⇒ no changes generated
            t = start
            prev_state: Optional[str] = None
            while True:
                dur_h, rough_mm, prev_state = self._sample_campaign(rng, mj, prev_state)
                if dur_h <= 0:
                    break
                t = t + timedelta(hours=float(dur_h))
                if t >= end:
                    break
                date_time = shifts_mod.next_operative_start(
                    change_grid, shifts_mod.next_shift_boundary(t))
                if date_time is None or date_time >= end:
                    break
                rows.append({
                    "Fecha_Hora": date_time,
                    "Jaula": stand,
                    "Tipo_Rectificado": _type_from_roughing(rough_mm, threshold),
                    "mm_a_Rectificar": round(float(rough_mm), 3),
                })

        rows.sort(key=lambda f: (f["Fecha_Hora"], f["Jaula"]))
        note = f"Generado {self.key} seed={seed}"
        for i, f in enumerate(rows, start=1):
            f["ID_Cambio"] = f"C{i}"
            f["Observación"] = note
        return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


class _EmpiricalGenerator(ChangeGenerator):
    """Empirical per-stand distributions: samples duration and roughing i.i.d."""

    key, label = "empirico", "Distribuciones empíricas por jaula"
    description = (
        "Aprende, por cada jaula, las distribuciones de duración de campaña y de "
        "mm desbastados a partir de la historia, y las muestrea de forma "
        "independiente (i.i.d.): cada cambio se sortea sin mirar el anterior. "
        "Simple y robusto; ideal cuando no hay correlación entre campañas "
        "consecutivas.")

    def _empty_stand_model(self) -> Dict[str, Any]:
        return {"duracion": [], "desbaste": []}

    def _accumulate_stand(self, mj, group, cfg):
        mj["duracion"].extend(float(x) for x in group["duracion_h"])
        mj["desbaste"].extend(float(x) for x in group["desbaste_mm"])

    def _sample_campaign(self, rng, mj, prev_state):
        dur = mj.get("duracion") or []
        rough = mj.get("desbaste") or []
        if not dur:
            return 0.0, 0.0, None
        d = float(dur[rng.integers(len(dur))])
        m = float(rough[rng.integers(len(rough))]) if rough else 0.0
        return d, m, None


class _MarkovGenerator(ChangeGenerator):
    """Per-stand Markov chain over duration buckets (+ type).

    Captures the correlation between consecutive campaigns: the bucket of the
    next campaign is conditioned on the previous one. Within each state a
    concrete duration and roughing are sampled from the accumulated observations.
    """

    key, label = "markov", "Cadena de Markov por jaula"
    description = (
        "Cadena de Markov por jaula: agrupa las campañas en buckets de duración "
        "y aprende con qué probabilidad una campaña de cierta duración (y tipo) es "
        "seguida por otra. Captura la correlación entre campañas consecutivas "
        "(p. ej. que tras una campaña larga suele venir una corta); la duración y "
        "el desbaste concretos se muestrean de las observaciones de ese estado.")

    def _empty_stand_model(self) -> Dict[str, Any]:
        return {"inicial": {}, "transiciones": {}, "muestras": {}}

    @staticmethod
    def _state(dur_h: float, rough_mm: float, threshold: float) -> str:
        return f"{_duration_bucket(dur_h)}:{_type_from_roughing(rough_mm, threshold)}"

    def _accumulate_stand(self, mj, group, cfg):
        threshold = float(cfgmod.obtener_generador_cambios(cfg)["umbral_desbaste_mm"])
        rows = group.sort_values("fecha_salida", na_position="last")
        prev: Optional[str] = None
        for _, row in rows.iterrows():
            dur, rough = float(row["duracion_h"]), float(row["desbaste_mm"])
            st = self._state(dur, rough, threshold)
            if prev is None:
                mj["inicial"][st] = mj["inicial"].get(st, 0) + 1
            else:
                trans = mj["transiciones"].setdefault(prev, {})
                trans[st] = trans.get(st, 0) + 1
            samples = mj["muestras"].setdefault(st, {"duracion": [], "desbaste": []})
            samples["duracion"].append(dur)
            samples["desbaste"].append(rough)
            prev = st

    @staticmethod
    def _choose(rng, counts: Dict[str, int]) -> Optional[str]:
        if not counts:
            return None
        states = list(counts.keys())
        weights = np.array([counts[e] for e in states], dtype=float)
        weights /= weights.sum()
        return str(rng.choice(states, p=weights))

    def _sample_campaign(self, rng, mj, prev_state):
        if prev_state is None:
            state = self._choose(rng, mj.get("inicial", {}))
        else:
            state = self._choose(rng, mj.get("transiciones", {}).get(prev_state, {}))
            if state is None:  # state with no observed transitions: restart
                state = self._choose(rng, mj.get("inicial", {}))
        if state is None:
            return 0.0, 0.0, None
        samples = mj.get("muestras", {}).get(state)
        if not samples or not samples.get("duracion"):
            return 0.0, 0.0, None
        dur = samples["duracion"]
        rough = samples["desbaste"]
        d = float(dur[rng.integers(len(dur))])
        m = float(rough[rng.integers(len(rough))]) if rough else 0.0
        return d, m, state


CHANGE_GENERATORS: Dict[str, ChangeGenerator] = {
    g.key: g for g in (
        _EmpiricalGenerator(),
        _MarkovGenerator(),
    )
}
DEFAULT_GENERATOR = "empirico"


# ── High-level facade (CLI / GUI / batch) ─────────────────────────────────────

def get_generator(key: Optional[str]) -> ChangeGenerator:
    """Return the generator registered for ``key`` (or the default)."""
    return CHANGE_GENERATORS.get(key or DEFAULT_GENERATOR,
                                 CHANGE_GENERATORS[DEFAULT_GENERATOR])


def change_grid_from_cfg(cfg: Dict[str, Any]) -> Optional[List[List[bool]]]:
    """Expand the change-shift regime into a grid (None if it is 24/7)."""
    shifts = cfgmod.obtener_turnos_cambios(cfg)
    return None if shifts is None else shifts_mod.expand(shifts)


def fit_model(history_df: pd.DataFrame, cfg: Dict[str, Any], *,
              key: Optional[str] = None,
              prior_model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fit the model of the ``key`` generator (incremental refit with a prior)."""
    gen = get_generator(key)
    return gen.fit(history_df, cfg, prior_model=prior_model)


def generate_changes(model: Dict[str, Any], cfg: Dict[str, Any], *,
                     seed: Optional[int] = None, start: Optional[datetime] = None,
                     end: Optional[datetime] = None,
                     horizon_days: Optional[int] = None) -> pd.DataFrame:
    """Generate the Programa_Cambios from a fitted model, with the cfg regime."""
    gen = get_generator(model.get("clave"))
    return gen.generate(model, cfg, seed=seed, start=start, end=end,
                        horizon_days=horizon_days,
                        change_grid=change_grid_from_cfg(cfg))
