"""El CRC se llena **de a parejas**: nunca un cilindro suelto.

Regla del taller: el traslado Disponible→CRC mueve la pareja completa
(`_BUFFER_CRC_SIZE`) en un viaje; si no hay disponibles para completarla no se
mueve ninguno (quedan Disponible y la reactivación de la jaula los toma directo
del stock). Lo mismo al arrancar: una jaula con un solo cilindro en su rango no
deja ese suelto en el CRC, sino Disponible reservado a la jaula.

Estos tests fijan esa regla a nivel unitario (`reponer_buffer_crc` y el arranque)
y como invariante sobre todos los escenarios (ningún snapshot muestra un CRC
impar).
"""
from datetime import datetime

import pandas as pd
import pytest

from config.persistencia import cargar_config
from modelos.taller import TallerCilindros, _BUFFER_CRC_SIZE
from modelos.jaula import Jaula
from modelos.cilindro import Cilindro
from modelos.enums import EstadoCilindro
from _escenarios import ESCENARIOS, ejecutar_escenario

T0 = datetime(2026, 6, 1, 8, 0)
_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                   "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}]


def _taller_una_jaula():
    t = TallerCilindros()
    t.configurar(cargar_config())
    t.jaulas = {1: Jaula(1)}
    ss = t.obtener_substock_por_jaula(1)
    return t, (ss.hasta + ss.desde) / 2  # un diámetro dentro del rango de J1


def test_reponer_no_coloca_cilindro_suelto():
    """Un único disponible no entra al CRC: queda Disponible (pareja incompleta)."""
    t, diam = _taller_una_jaula()
    c1 = Cilindro("C1", diam, EstadoCilindro.DISPONIBLE)
    t.cilindros = {"C1": c1}
    assert t.reponer_buffer_crc(1, T0) is False
    assert t.jaulas[1].cilindros_crc == []
    assert c1.estado == EstadoCilindro.DISPONIBLE


def test_reponer_coloca_pareja_completa():
    """Con dos disponibles se mueve la pareja completa al CRC."""
    t, diam = _taller_una_jaula()
    t.cilindros = {f"C{i}": Cilindro(f"C{i}", diam, EstadoCilindro.DISPONIBLE)
                   for i in range(2)}
    assert t.reponer_buffer_crc(1, T0) is True
    assert len(t.jaulas[1].cilindros_crc) == _BUFFER_CRC_SIZE


def test_arranque_un_solo_cilindro_no_va_al_crc():
    """Al cargar, una jaula con un solo cilindro arranca PARADA y el CRC vacío."""
    t = TallerCilindros()
    t.configurar({
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 520.0}],
        "maquinas": _MAQ,
    })
    stock = pd.DataFrame([
        {"ID_Cilindro": "A", "Diámetro_mm": 560.0, "Estado": "Trabajando",
         "Jaula_Asignada": 1, "Posición": 1},
    ])
    cambios = pd.DataFrame([], columns=["ID_Cambio", "Fecha_Hora", "Jaula",
                                        "Tipo_Rectificado", "mm_a_Rectificar", "Observación"])
    t.cargar_datos_desde_dataframes(stock, cambios)
    jaula = t.jaulas[1]
    assert jaula.parada is True
    assert jaula.cilindros_crc == []                       # nunca un suelto en el CRC
    assert t.cilindros["A"].estado == EstadoCilindro.DISPONIBLE
    assert t.cilindros["A"].jaula_destino == 1             # reservado a su jaula


def test_reactivacion_no_reparte_un_cilindro_a_dos_jaulas():
    """Con bandas solapadas, dos jaulas paradas no se reparten el mismo cilindro.

    ``_intentar_reactivar_jaulas`` calcula los DISPONIBLE una sola vez y quita los
    consumidos de la lista compartida, así que cada cilindro entra en exactamente
    una jaula (la de menor id, que reactiva primero). Es el caso que el golden no
    cubre (sus bandas no se solapan ⇒ un cilindro es admisible en una sola jaula).
    """
    t = TallerCilindros()
    t.configurar({
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 2},
        # Bandas solapadas: un Ø 560 es admisible en AMBAS jaulas.
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 540.0},
                   {"jaula": 2, "desde": 575.0, "hasta": 540.0}],
        "maquinas": _MAQ,
    })
    t.jaulas = {1: Jaula(1), 2: Jaula(2)}
    for j in t.jaulas.values():
        j.parada = True
        j.parada_desde = T0
    t.cilindros = {f"C{i}": Cilindro(f"C{i}", 560.0, EstadoCilindro.DISPONIBLE)
                   for i in range(4)}

    t._intentar_reactivar_jaulas(T0, lambda *_a: None, [])

    ids1 = {c.id for c in t.jaulas[1].cilindros_trabajando}
    ids2 = {c.id for c in t.jaulas[2].cilindros_trabajando}
    assert len(ids1) == _BUFFER_CRC_SIZE and len(ids2) == _BUFFER_CRC_SIZE
    assert ids1.isdisjoint(ids2)                       # nadie en dos jaulas
    assert ids1 | ids2 == {f"C{i}" for i in range(4)}  # los 4 instalados, sin repetir
    assert not t.jaulas[1].parada and not t.jaulas[2].parada


@pytest.mark.parametrize("nombre", list(ESCENARIOS))
def test_crc_nunca_impar_en_snapshots(nombre):
    """En ningún snapshot de ningún escenario el CRC de una jaula es impar."""
    t = ejecutar_escenario(ESCENARIOS[nombre])
    for s in t.snapshots:
        for jaula_id, n in s.crc_por_jaula.items():
            assert n % _BUFFER_CRC_SIZE == 0, (
                f"{nombre}: CRC impar ({n}) en jaula {jaula_id} a t={s.tiempo}")
