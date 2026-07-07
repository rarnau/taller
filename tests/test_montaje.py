"""Estrategia de montaje POR JAULA (qué Disponible sube primero al CRC/jaula).

Cada jaula puede elegir el orden de montaje de su stock admisible:
``mayor_diametro`` (histórico, default con el campo ausente) o
``menor_diametro``. Se persiste como campo opcional ``montaje`` de cada entrada
de ``rangos`` (mismo patrón que ``perfil``) y gobierna los tres puntos de
montaje del motor: colocación inicial, rearme de pareja y subida al CRC
(``TallerCilindros._ordenar_montaje``).
"""
from datetime import datetime

import pandas as pd
import pytest

from config.persistencia import cargar_config, set_rango
from modelos.enums import EstadoCilindro
from modelos.estrategias import ESTRATEGIA_MONTAJE_DEFECTO, ESTRATEGIAS_MONTAJE
from modelos.taller import TallerCilindros

_COLS_CAMBIOS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                 "mm_a_Rectificar", "Observación"]
_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                   "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}]


def _cfg(montaje=None):
    rango = {"jaula": 1, "desde": 575.0, "hasta": 520.0}
    if montaje:
        rango["montaje"] = montaje
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [rango],
        "maquinas": _MAQ,
    }


def _fila(cid, diam, estado="Disponible", jaula=None, pos=None):
    return {"ID_Cilindro": cid, "Diámetro_mm": diam, "Estado": estado,
            "Jaula_Asignada": jaula, "Posición": pos}


_DISPONIBLES = [_fila("D570", 570.0), _fila("D565", 565.0),
                _fila("D545", 545.0), _fila("D540", 540.0)]


def _taller(cfg, stock_rows, cambios_rows=()):
    t = TallerCilindros()
    t.configurar(cfg)
    t.cargar_datos_desde_dataframes(
        pd.DataFrame(stock_rows), pd.DataFrame(list(cambios_rows), columns=_COLS_CAMBIOS))
    return t


# ── 1. Subida al CRC (reponer_buffer_crc) ────────────────────────────────────

def test_crc_mayor_diametro_por_defecto():
    """Sin campo 'montaje' la pareja que sube al CRC es la de mayor diámetro."""
    t = _taller(_cfg(), [_fila("W1", 560.0, "Trabajando", 1, 1),
                         _fila("W2", 560.0, "Trabajando", 1, 2)] + _DISPONIBLES)
    assert t.reponer_buffer_crc(1, datetime(2026, 7, 6, 8, 0))
    assert [c.id for c in t.jaulas[1].cilindros_crc] == ["D570", "D565"]


def test_crc_menor_diametro():
    t = _taller(_cfg("menor_diametro"),
                [_fila("W1", 560.0, "Trabajando", 1, 1),
                 _fila("W2", 560.0, "Trabajando", 1, 2)] + _DISPONIBLES)
    assert t.reponer_buffer_crc(1, datetime(2026, 7, 6, 8, 0))
    assert [c.id for c in t.jaulas[1].cilindros_crc] == ["D540", "D545"]


# ── 2. Colocación inicial (_garantizar_parejas_iniciales) ────────────────────

def test_colocacion_inicial_respeta_montaje():
    t_mayor = _taller(_cfg(), list(_DISPONIBLES))
    assert sorted(c.id for c in t_mayor.jaulas[1].cilindros_trabajando) == ["D565", "D570"]

    t_menor = _taller(_cfg("menor_diametro"), list(_DISPONIBLES))
    assert sorted(c.id for c in t_menor.jaulas[1].cilindros_trabajando) == ["D540", "D545"]


# ── 3. Rearme de pareja (_instalar_pareja_o_parar, vía un CAMBIO) ────────────

def _cambio(hora=datetime(2026, 7, 6, 8, 0)):
    return {"ID_Cambio": "C1", "Fecha_Hora": hora, "Jaula": 1,
            "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 1.0,
            "Observación": ""}


def test_cambio_monta_segun_estrategia():
    """Al CAMBIO (CRC vacío), la pareja instalada sale del stock según la
    estrategia de la jaula."""
    for montaje, esperados in ((None, {"D565", "D570"}),
                               ("menor_diametro", {"D540", "D545"})):
        t = _taller(_cfg(montaje),
                    [_fila("W1", 560.0, "Trabajando", 1, 1),
                     _fila("W2", 560.0, "Trabajando", 1, 2)] + _DISPONIBLES,
                    cambios_rows=[_cambio()])
        t.simular(callback_log=None)
        instalados_primero = {
            c.id for c in t.cilindros.values()
            if any(h["evento"] == "Instalado en Jaula 1" for h in c.historial[:2])
            and c.id.startswith("D")
        }
        assert instalados_primero == esperados, f"montaje={montaje}"


# ── 4. Config: persistencia y registro ───────────────────────────────────────

def test_set_rango_montaje_roundtrip():
    cfg = cargar_config()
    set_rango(cfg, 1, desde=547.0, hasta=520.0, montaje="menor_diametro")
    r1 = next(r for r in cfg["rangos"] if r["jaula"] == 1)
    assert r1["montaje"] == "menor_diametro"

    # None conserva; "" lo quita (vuelve al default).
    set_rango(cfg, 1, desde=547.0, hasta=520.0)
    assert r1["montaje"] == "menor_diametro"
    set_rango(cfg, 1, desde=547.0, hasta=520.0, montaje="")
    assert "montaje" not in next(r for r in cfg["rangos"] if r["jaula"] == 1)

    with pytest.raises(ValueError):
        set_rango(cfg, 1, desde=547.0, hasta=520.0, montaje="al_azar")

    # configurar() lo baja al SubStock (y el ausente queda en el default).
    set_rango(cfg, 2, desde=563.0, hasta=539.0, montaje="menor_diametro")
    t = TallerCilindros()
    t.configurar(cfg)
    assert t.obtener_substock_por_jaula(2).montaje == "menor_diametro"
    assert t.obtener_substock_por_jaula(1).montaje == ESTRATEGIA_MONTAJE_DEFECTO


def test_registro_expone_las_dos_estrategias():
    assert set(ESTRATEGIAS_MONTAJE) == {"mayor_diametro", "menor_diametro"}
    assert ESTRATEGIA_MONTAJE_DEFECTO == "mayor_diametro"
    # El orden es puro y estable: empates conservan el orden de entrada.
    class _C:  # noqa: N801 - stub mínimo con diámetro
        def __init__(self, i, d):
            self.id, self.diametro = i, d
    cils = [_C("a", 550.0), _C("b", 550.0), _C("c", 560.0)]
    assert [c.id for c in ESTRATEGIAS_MONTAJE["mayor_diametro"].ordenar(cils)] == ["c", "a", "b"]
    assert [c.id for c in ESTRATEGIAS_MONTAJE["menor_diametro"].ordenar(cils)] == ["a", "b", "c"]
