"""Generadores sintéticos del ``Programa_Cambios`` aprendidos de la historia.

Módulo de dominio **puro** (sin GUI ni estado de simulación): a partir de un
histórico real de campañas (una fila = una pareja que trabajó en una jaula
durante cierto tiempo y se desbastó cierto mm), **ajusta** un modelo por jaula y
luego **genera** un ``Programa_Cambios`` reproducible por *seed*.

El diseño separa dos pasos (como ``sklearn``):

- ``ajustar(historia_df, cfg, *, modelo_previo=None) -> dict``: produce un modelo
  serializable. Con ``modelo_previo`` de la misma ``clave`` **acumula** sobre él
  (refit incremental); con ``None`` ajusta **desde cero**. El modelo se persiste
  con ``config.modelo_generador``.
- ``generar(modelo, cfg, *, seed, ...) -> pandas.DataFrame``: muestrea campañas
  por jaula hasta cubrir el horizonte. Toda la aleatoriedad pasa por un
  ``numpy.random.default_rng(seed)``, así que misma seed ⇒ mismo DataFrame. Sin
  estado de módulo: seguro para miles de simulaciones en paralelo.

Cada cambio se alinea al **régimen de turnos del laminador**: el desmontaje cae a
fin de turno y el montaje a la primera hora del siguiente turno operativo
(``modelos.turnos.proximo_borde_turno`` + ``proximo_inicio_operativo``).

Se registran dos generadores en ``GENERADORES_CAMBIOS`` (patrón calcado de
``modelos.estrategias``): ``empirico`` (distribuciones empíricas por jaula) y
``markov`` (cadena de Markov sobre buckets de duración que captura la correlación
entre campañas consecutivas). Agregar uno nuevo: subclasar ``GeneradorCambios`` y
registrarlo; la GUI y el CLI lo toman de ahí.
"""
from __future__ import annotations

import copy
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import persistencia as cfgmod
from modelos import turnos as turnos_mod

# Columnas exactas que espera el simulador (ver TallerCilindros._cargar_cambios).
COLUMNAS_SALIDA = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                   "mm_a_Rectificar", "Observación"]

# Inicio por defecto del horizonte si no se pasa uno: lunes 06:00 (frontera T1).
_INICIO_DEFECTO = datetime(2026, 1, 5, 6, 0, 0)

# Fronteras de bucket de duración (horas) para la cadena de Markov.
_EDGES_DURACION_H = [12.0, 24.0, 48.0, 72.0]


# ── Normalización de la historia ─────────────────────────────────────────────

def _norm_key(s: Any) -> str:
    """Normaliza un nombre de columna: minúsculas, sin acentos ni símbolos."""
    txt = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(c for c in txt.lower() if c.isalnum())


# Sinónimos aceptados por campo lógico (claves ya normalizadas con _norm_key).
_ALIAS = {
    "jaula": {"jaula"},
    "duracion_h": {"duracionhs", "duracion", "duracionh", "duracionhoras", "horas"},
    "desbaste_mm": {"desbaste", "desbastemm", "mmarectificar"},
    "fecha_ingreso": {"fechaingreso", "ingreso"},
    "fecha_salida": {"fechasalida", "salida"},
    "diametro": {"diametro", "diametromm"},
}


def _mapear_columnas(df: pd.DataFrame) -> Dict[str, str]:
    """Mapea campo lógico → nombre real de columna presente en ``df``."""
    presentes = {_norm_key(c): c for c in df.columns}
    salida: Dict[str, str] = {}
    for campo, alias in _ALIAS.items():
        for a in alias:
            if a in presentes:
                salida[campo] = presentes[a]
                break
    return salida


def _normalizar_historia(historia_df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """Devuelve un DataFrame normalizado con columnas jaula/duracion_h/desbaste_mm.

    Tolera los nombres acentuados del histórico real. Deriva ``duracion_h`` de las
    fechas si no viene la columna de duración. Descarta filas sin jaula o sin
    duración válida.
    """
    cols = _mapear_columnas(historia_df)
    if "jaula" not in cols:
        raise ValueError("La historia no tiene una columna 'Jaula' reconocible.")

    out = pd.DataFrame()
    out["jaula"] = pd.to_numeric(historia_df[cols["jaula"]], errors="coerce")

    if "duracion_h" in cols:
        out["duracion_h"] = pd.to_numeric(historia_df[cols["duracion_h"]], errors="coerce")
    elif "fecha_ingreso" in cols and "fecha_salida" in cols:
        ing = pd.to_datetime(historia_df[cols["fecha_ingreso"]], errors="coerce")
        sal = pd.to_datetime(historia_df[cols["fecha_salida"]], errors="coerce")
        out["duracion_h"] = (sal - ing).dt.total_seconds() / 3600.0
    else:
        raise ValueError("La historia no tiene duración ni fechas para derivarla.")

    if "desbaste_mm" in cols:
        out["desbaste_mm"] = pd.to_numeric(historia_df[cols["desbaste_mm"]], errors="coerce")
    else:
        out["desbaste_mm"] = np.nan

    if "fecha_salida" in cols:
        out["fecha_salida"] = pd.to_datetime(historia_df[cols["fecha_salida"]], errors="coerce")
    elif "fecha_ingreso" in cols:
        out["fecha_salida"] = pd.to_datetime(historia_df[cols["fecha_ingreso"]], errors="coerce")
    else:
        out["fecha_salida"] = pd.NaT

    out = out.dropna(subset=["jaula", "duracion_h"])
    out = out[out["duracion_h"] > 0]
    out["jaula"] = out["jaula"].astype(int)
    # Desbaste faltante: se imputa con el umbral configurado (queda como 'desbaste'
    # marginal) para no perder la fila; rara vez ocurre con datos reales.
    umbral = float(cfgmod.obtener_generador_cambios(cfg)["umbral_desbaste_mm"])
    out["desbaste_mm"] = out["desbaste_mm"].fillna(umbral)
    return out.reset_index(drop=True)


def _tipo_desde_desbaste(mm: float, umbral: float) -> str:
    """Clasifica el tipo de rectificado por umbral de mm a desbastar."""
    return "desbaste" if float(mm) > float(umbral) else "produccion"


def _bucket_duracion(h: float) -> str:
    """Etiqueta del bucket de duración (para el estado de la cadena de Markov)."""
    for i, e in enumerate(_EDGES_DURACION_H):
        if h < e:
            return f"d{i}"
    return f"d{len(_EDGES_DURACION_H)}"


def resolver_seed(seed: Optional[int]) -> int:
    """Devuelve una seed concreta (aleatoria reproducible si ``seed is None``)."""
    if seed is not None:
        return int(seed)
    return int(np.random.SeedSequence().generate_state(1)[0])


# ── Generadores ──────────────────────────────────────────────────────────────

class GeneradorCambios:
    """Base: ajusta un modelo por jaula y genera un Programa_Cambios reproducible."""

    clave: str = ""
    etiqueta: str = ""

    # -- Fit -----------------------------------------------------------------
    def _modelo_jaula_vacio(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _acumular_jaula(self, mj: Dict[str, Any], grupo: pd.DataFrame,
                        cfg: Dict[str, Any]) -> None:
        raise NotImplementedError

    def ajustar(self, historia_df: pd.DataFrame, cfg: Dict[str, Any], *,
                modelo_previo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Ajusta (o refina incrementalmente) el modelo a partir de la historia."""
        norm = _normalizar_historia(historia_df, cfg)

        if modelo_previo and modelo_previo.get("clave") == self.clave:
            modelo = copy.deepcopy(modelo_previo)
        else:
            modelo = {"clave": self.clave, "n_filas": 0,
                      "fecha_min": None, "fecha_max": None, "jaulas": {}}

        modelo["n_filas"] = int(modelo.get("n_filas", 0)) + len(norm)
        fechas = norm["fecha_salida"].dropna()
        if not fechas.empty:
            fmin, fmax = fechas.min().isoformat(), fechas.max().isoformat()
            modelo["fecha_min"] = min(filter(None, [modelo.get("fecha_min"), fmin]))
            modelo["fecha_max"] = max(filter(None, [modelo.get("fecha_max"), fmax]))

        for jaula, grupo in norm.groupby("jaula"):
            mj = modelo["jaulas"].setdefault(str(int(jaula)), self._modelo_jaula_vacio())
            self._acumular_jaula(mj, grupo, cfg)
        return modelo

    # -- Generación ----------------------------------------------------------
    def _muestrear_campania(self, rng, mj: Dict[str, Any],
                            estado_previo: Optional[str]) -> tuple:
        """Devuelve (duracion_h, desbaste_mm, estado_nuevo) para la jaula."""
        raise NotImplementedError

    def generar(self, modelo: Dict[str, Any], cfg: Dict[str, Any], *,
                seed: Optional[int] = None, inicio: Optional[datetime] = None,
                horizonte_dias: Optional[int] = None,
                grilla_cambios: Optional[List[List[bool]]] = None) -> pd.DataFrame:
        """Genera el ``Programa_Cambios`` muestreando campañas por jaula."""
        gc = cfgmod.obtener_generador_cambios(cfg)
        cg = cfgmod.obtener_config_global(cfg)
        umbral = float(gc["umbral_desbaste_mm"])
        if horizonte_dias is None:
            horizonte_dias = int(gc["horizonte_dias"])
        n_jaulas = int(cg["cantidad_jaulas"])

        seed = resolver_seed(seed)
        rng = np.random.default_rng(seed)
        if inicio is None:
            inicio = _INICIO_DEFECTO
        fin = inicio + timedelta(days=int(horizonte_dias))

        filas: List[Dict[str, Any]] = []
        modelo_jaulas = modelo.get("jaulas", {})
        for jaula in range(1, n_jaulas + 1):
            mj = modelo_jaulas.get(str(jaula))
            if not mj:
                continue  # sin historia para esa jaula ⇒ no se generan cambios
            t = inicio
            estado_previo: Optional[str] = None
            while True:
                dur_h, desb_mm, estado_previo = self._muestrear_campania(rng, mj, estado_previo)
                if dur_h <= 0:
                    break
                t = t + timedelta(hours=float(dur_h))
                if t >= fin:
                    break
                fecha = turnos_mod.proximo_inicio_operativo(
                    grilla_cambios, turnos_mod.proximo_borde_turno(t))
                if fecha is None or fecha >= fin:
                    break
                filas.append({
                    "Fecha_Hora": fecha,
                    "Jaula": jaula,
                    "Tipo_Rectificado": _tipo_desde_desbaste(desb_mm, umbral),
                    "mm_a_Rectificar": round(float(desb_mm), 3),
                })

        filas.sort(key=lambda f: (f["Fecha_Hora"], f["Jaula"]))
        obs = f"Generado {self.clave} seed={seed}"
        for i, f in enumerate(filas, start=1):
            f["ID_Cambio"] = f"C{i}"
            f["Observación"] = obs
        return pd.DataFrame(filas, columns=COLUMNAS_SALIDA)


class _GeneradorEmpirico(GeneradorCambios):
    """Distribuciones empíricas por jaula: muestrea duración y desbaste i.i.d."""

    clave, etiqueta = "empirico", "Distribuciones empíricas por jaula"

    def _modelo_jaula_vacio(self) -> Dict[str, Any]:
        return {"duracion": [], "desbaste": []}

    def _acumular_jaula(self, mj, grupo, cfg):
        mj["duracion"].extend(float(x) for x in grupo["duracion_h"])
        mj["desbaste"].extend(float(x) for x in grupo["desbaste_mm"])

    def _muestrear_campania(self, rng, mj, estado_previo):
        dur = mj.get("duracion") or []
        desb = mj.get("desbaste") or []
        if not dur:
            return 0.0, 0.0, None
        d = float(dur[rng.integers(len(dur))])
        m = float(desb[rng.integers(len(desb))]) if desb else 0.0
        return d, m, None


class _GeneradorMarkov(GeneradorCambios):
    """Cadena de Markov por jaula sobre buckets de duración (+ tipo).

    Captura la correlación entre campañas consecutivas: el bucket de la próxima
    campaña se condiciona al de la anterior. Dentro de cada estado se muestrea una
    duración y un desbaste concretos de las observaciones acumuladas.
    """

    clave, etiqueta = "markov", "Cadena de Markov por jaula"

    def _modelo_jaula_vacio(self) -> Dict[str, Any]:
        return {"inicial": {}, "transiciones": {}, "muestras": {}}

    @staticmethod
    def _estado(dur_h: float, desb_mm: float, umbral: float) -> str:
        return f"{_bucket_duracion(dur_h)}:{_tipo_desde_desbaste(desb_mm, umbral)}"

    def _acumular_jaula(self, mj, grupo, cfg):
        umbral = float(cfgmod.obtener_generador_cambios(cfg)["umbral_desbaste_mm"])
        filas = grupo.sort_values("fecha_salida", na_position="last")
        prev: Optional[str] = None
        for _, row in filas.iterrows():
            dur, desb = float(row["duracion_h"]), float(row["desbaste_mm"])
            est = self._estado(dur, desb, umbral)
            if prev is None:
                mj["inicial"][est] = mj["inicial"].get(est, 0) + 1
            else:
                trans = mj["transiciones"].setdefault(prev, {})
                trans[est] = trans.get(est, 0) + 1
            muestras = mj["muestras"].setdefault(est, {"duracion": [], "desbaste": []})
            muestras["duracion"].append(dur)
            muestras["desbaste"].append(desb)
            prev = est

    @staticmethod
    def _elegir(rng, conteos: Dict[str, int]) -> Optional[str]:
        if not conteos:
            return None
        estados = list(conteos.keys())
        pesos = np.array([conteos[e] for e in estados], dtype=float)
        pesos /= pesos.sum()
        return str(rng.choice(estados, p=pesos))

    def _muestrear_campania(self, rng, mj, estado_previo):
        if estado_previo is None:
            estado = self._elegir(rng, mj.get("inicial", {}))
        else:
            estado = self._elegir(rng, mj.get("transiciones", {}).get(estado_previo, {}))
            if estado is None:  # estado sin transiciones observadas: reinicia
                estado = self._elegir(rng, mj.get("inicial", {}))
        if estado is None:
            return 0.0, 0.0, None
        muestras = mj.get("muestras", {}).get(estado)
        if not muestras or not muestras.get("duracion"):
            return 0.0, 0.0, None
        dur = muestras["duracion"]
        desb = muestras["desbaste"]
        d = float(dur[rng.integers(len(dur))])
        m = float(desb[rng.integers(len(desb))]) if desb else 0.0
        return d, m, estado


GENERADORES_CAMBIOS: Dict[str, GeneradorCambios] = {
    g.clave: g for g in (
        _GeneradorEmpirico(),
        _GeneradorMarkov(),
    )
}
GENERADOR_DEFECTO = "empirico"


# ── Fachada de alto nivel (CLI / GUI / batch) ─────────────────────────────────

def obtener_generador(clave: Optional[str]) -> GeneradorCambios:
    """Devuelve el generador registrado para ``clave`` (o el por defecto)."""
    return GENERADORES_CAMBIOS.get(clave or GENERADOR_DEFECTO,
                                   GENERADORES_CAMBIOS[GENERADOR_DEFECTO])


def grilla_cambios_desde_cfg(cfg: Dict[str, Any]) -> Optional[List[List[bool]]]:
    """Expande el régimen de turnos de cambios a grilla (None si es 24/7)."""
    turnos = cfgmod.obtener_turnos_cambios(cfg)
    return None if turnos is None else turnos_mod.expandir(turnos)


def ajustar_modelo(historia_df: pd.DataFrame, cfg: Dict[str, Any], *,
                   clave: Optional[str] = None,
                   modelo_previo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ajusta el modelo del generador ``clave`` (refit incremental con previo)."""
    gen = obtener_generador(clave)
    return gen.ajustar(historia_df, cfg, modelo_previo=modelo_previo)


def generar_cambios(modelo: Dict[str, Any], cfg: Dict[str, Any], *,
                    seed: Optional[int] = None, inicio: Optional[datetime] = None,
                    horizonte_dias: Optional[int] = None) -> pd.DataFrame:
    """Genera el Programa_Cambios desde un modelo ya ajustado, con el régimen del cfg."""
    gen = obtener_generador(modelo.get("clave"))
    return gen.generar(modelo, cfg, seed=seed, inicio=inicio,
                       horizonte_dias=horizonte_dias,
                       grilla_cambios=grilla_cambios_desde_cfg(cfg))
