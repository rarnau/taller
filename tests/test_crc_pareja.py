"""El CRC se llena **de a parejas**: nunca un cilindro suelto.

Regla del taller: el traslado Disponible→CRC mueve la pareja completa
(`_BUFFER_CRC_SIZE`) en un viaje; si no hay disponibles para completarla no se
mueve ninguno (quedan Disponible y la reactivación de la jaula los toma directo
del stock). Lo mismo al arrancar: una jaula con un solo cilindro en su rango no
deja ese suelto en el CRC, sino Disponible reservado a la jaula.

Estos tests fijan esa regla a nivel unitario (`replenish_crc_buffer` y el
arranque) y como invariante sobre todos los escenarios (ningún snapshot muestra
un CRC impar).
"""
from datetime import datetime

import pandas as pd
import pytest

from config.persistencia import cargar_config
from models.workshop import CylinderWorkshop, _BUFFER_CRC_SIZE
from models.stand import Stand
from models.cylinder import Cylinder
from models.enums import CylinderState
from _escenarios import SCENARIOS, run_scenario

T0 = datetime(2026, 6, 1, 8, 0)
_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                   "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}]


def _workshop_one_stand():
    t = CylinderWorkshop()
    t.configure(cargar_config())
    t.stands = {1: Stand(1)}
    ss = t.get_substock_by_stand(1)
    return t, (ss.lower + ss.upper) / 2  # a diameter within the range of S1


def test_reponer_no_coloca_cilindro_suelto():
    """Un único disponible no entra al CRC: queda Disponible (pareja incompleta)."""
    t, diam = _workshop_one_stand()
    c1 = Cylinder("C1", diam, CylinderState.AVAILABLE)
    t.cylinders = {"C1": c1}
    assert t.replenish_crc_buffer(1, T0) is False
    assert t.stands[1].crc_cylinders == []
    assert c1.state == CylinderState.AVAILABLE


def test_reponer_coloca_pareja_completa():
    """Con dos disponibles se mueve la pareja completa al CRC."""
    t, diam = _workshop_one_stand()
    t.cylinders = {f"C{i}": Cylinder(f"C{i}", diam, CylinderState.AVAILABLE)
                   for i in range(2)}
    assert t.replenish_crc_buffer(1, T0) is True
    assert len(t.stands[1].crc_cylinders) == _BUFFER_CRC_SIZE


def test_arranque_un_solo_cilindro_no_va_al_crc():
    """Al cargar, una jaula con un solo cilindro arranca PARADA y el CRC vacío."""
    t = CylinderWorkshop()
    t.configure({
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
    t.load_data_from_dataframes(stock, cambios)
    stand = t.stands[1]
    assert stand.stopped is True
    assert stand.crc_cylinders == []                       # nunca un suelto en el CRC
    assert t.cylinders["A"].state == CylinderState.AVAILABLE
    assert t.cylinders["A"].target_stand == 1              # reservado a su jaula


@pytest.mark.parametrize("nombre", list(SCENARIOS))
def test_crc_nunca_impar_en_snapshots(nombre):
    """En ningún snapshot de ningún escenario el CRC de una jaula es impar."""
    t = run_scenario(SCENARIOS[nombre])
    for s in t.snapshots:
        for jaula_id, n in s.crc_por_jaula.items():
            assert n % _BUFFER_CRC_SIZE == 0, (
                f"{nombre}: CRC impar ({n}) en jaula {jaula_id} a t={s.tiempo}")
