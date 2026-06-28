"""Tests unitarios de la asignación de jaula por perfil y del re-perfilado.

Cubren las reglas nuevas del motor:
  - ``_assign_target_stand`` nunca devuelve una jaula no admisible por
    diámetro (pre-filtro duro) y la estrategia prioriza la jaula más necesitada.
  - Un cilindro que queda no colocable (diámetro en un hueco entre bandas) se
    re-encola a rectificado con un pase de producción de ``_REPROFILE_MM`` mm
    y emite una alerta INFO.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.workshop import CylinderWorkshop, _REPROFILE_MM
from models.cylinder import Cylinder
from models.stand import Stand
from models.enums import CylinderState, GrindingType

T0 = datetime(2026, 1, 1, 6, 0, 0)

# Una máquina mínima 24/7 para los tests que ejercitan rectificado.
_MAQ = [{
    "nombre": "M1", "prioridad": "produccion",
    "tasas": {"produccion": {"mm": 0.8, "tiempo_min": 60},
              "desbaste": {"mm": 5.0, "tiempo_min": 480}},
}]


def _workshop(rangos, with_machine=False):
    """Construye un taller configurado con ``rangos`` y jaulas vacías."""
    t = CylinderWorkshop()
    cfg = {
        "config_global": {
            "diametro_maximo": 575.0, "diametro_minimo": 520.0,
            "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": len(rangos),
        },
        "rangos": rangos,
        "estrategia_asignacion": "jaula_mas_necesitada",
    }
    if with_machine:
        cfg["maquinas"] = _MAQ
    t.configure(cfg)
    for j in range(1, len(rangos) + 1):
        t.stands[j] = Stand(j)
    return t


_BANDAS_SOLAPADAS = [
    {"jaula": 1, "desde": 540.0, "hasta": 520.0, "perfil": "4"},
    {"jaula": 2, "desde": 555.0, "hasta": 530.0, "perfil": "2"},
    {"jaula": 3, "desde": 565.0, "hasta": 540.0, "perfil": "2"},
    {"jaula": 4, "desde": 575.0, "hasta": 555.0, "perfil": "3"},
]


def test_asignar_respeta_prefiltro_por_diametro():
    """La jaula destino siempre admite el diámetro proyectado; nunca una fuera de banda."""
    t = _workshop(_BANDAS_SOLAPADAS)
    cil = Cylinder("X", 546.0, CylinderState.GRINDING)
    t.cylinders[cil.id] = cil
    # 545 sólo cae en jaula 2 (530-555) y jaula 3 (540-565), ambas perfil "2".
    destino, perfil = t._assign_target_stand(cil, 545.0, T0)
    assert destino in (2, 3)
    assert perfil == "2"
    assert cil.target_stand == destino
    # El SubStock de la jaula elegida realmente contiene el diámetro proyectado.
    assert t.get_substock_by_stand(destino).contains_diameter(545.0)


def test_asignar_sin_candidatas_deja_destino_none():
    """Si ninguna banda admite el diámetro proyectado, no se asigna jaula."""
    # Hueco 540-560 entre las dos bandas.
    t = _workshop([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ])
    cil = Cylinder("X", 550.8, CylinderState.GRINDING)
    t.cylinders[cil.id] = cil
    destino, _ = t._assign_target_stand(cil, 550.0, T0)
    assert destino is None
    assert cil.target_stand is None


def test_jaula_mas_necesitada_prioriza_deficit():
    """Entre dos jaulas admisibles, elige la de mayor déficit (CRC más vacío)."""
    t = _workshop(_BANDAS_SOLAPADAS)
    # Jaula 2 con CRC lleno (déficit 0); jaula 3 vacía (déficit 2). 545 cae en ambas.
    t.stands[2].crc_cylinders = [
        Cylinder("A", 545.0, CylinderState.CRC),
        Cylinder("B", 544.0, CylinderState.CRC),
    ]
    cil = Cylinder("X", 546.0, CylinderState.GRINDING)
    t.cylinders[cil.id] = cil
    destino, _ = t._assign_target_stand(cil, 545.0, T0)
    assert destino == 3  # la más necesitada


def test_es_colocable():
    """``_is_placeable`` refleja la admisibilidad por diámetro y perfil."""
    t = _workshop([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ])  # hueco 540-560
    assert t._is_placeable(Cylinder("A", 530.0, CylinderState.AVAILABLE)) is True
    assert t._is_placeable(Cylinder("B", 550.0, CylinderState.AVAILABLE)) is False


def test_reperfilado_de_no_colocable():
    """Un cilindro que finaliza en un hueco se re-encola a producción 0.8 mm + alerta INFO."""
    t = _workshop([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ], with_machine=True)  # hueco 540-560
    maq = t.machines["M1"]

    cil = Cylinder("X", 550.8, CylinderState.TO_GRIND)
    cil.current_grinding_type = GrindingType.PRODUCTION
    cil.mm_to_grind = 0.8
    t.cylinders[cil.id] = cil

    # Arranca el rectificado y lo finaliza: 550.8 - 0.8 = 550.0 (en el hueco).
    maq.start_grinding(cil, T0, GrindingType.PRODUCTION, 0.8)
    t._finish_and_continue(maq, maq.grinding_end_time, [], lambda s: None)

    # Se re-encoló a rectificado con un pase de producción de _REPROFILE_MM mm.
    assert cil.current_grinding_type == GrindingType.PRODUCTION
    assert cil.mm_to_grind == _REPROFILE_MM
    assert cil.target_stand is None
    # Y se registró la alerta INFO de "no colocable".
    assert any(a.type == "INFO" and "no colocable" in a.message for a in t.alerts)


# Una máquina sólo capaz de producción (desbaste con tiempo 0 ⇒ rate 0 ⇒ inf).
_MAQ_SOLO_PROD = [{
    "nombre": "SoloProd", "prioridad": "produccion",
    "tasas": {"produccion": {"mm": 0.8, "tiempo_min": 60},
              "desbaste": {"mm": 5.0, "tiempo_min": 0}},
}]


def _workshop_prod_only():
    t = CylinderWorkshop()
    t.configure({
        "config_global": {
            "diametro_maximo": 575.0, "diametro_minimo": 520.0,
            "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1,
        },
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 520.0}],
        "maquinas": _MAQ_SOLO_PROD,
    })
    t.stands[1] = Stand(1)
    return t


def test_maquina_sin_tasa_no_es_seleccionada():
    """``select_next_from_queue`` no entrega un trabajo cuyo tipo la máquina
    no puede ejecutar (evita el tiempo de proceso ``inf``)."""
    t = _workshop_prod_only()
    maq = t.machines["SoloProd"]
    cil = Cylinder("D", 555.0, CylinderState.TO_GRIND)
    cil.current_grinding_type = GrindingType.ROUGHING
    cil.mm_to_grind = 5.0
    assert t.select_next_from_queue([cil], maq) is None


def test_asignar_sin_maquina_capaz_no_crashea_y_alerta():
    """Un pase de desbaste con sólo una máquina de producción no debe caer con
    OverflowError: el cilindro queda en espera y se emite una alerta WARNING (1 vez)."""
    t = _workshop_prod_only()
    cil = Cylinder("D", 555.0, CylinderState.TO_GRIND)
    cil.current_grinding_type = GrindingType.ROUGHING
    cil.mm_to_grind = 5.0
    t.cylinders[cil.id] = cil

    eventos = t.assign_machine_work(T0)  # antes: OverflowError
    assert eventos == []
    assert cil.state == CylinderState.TO_GRIND  # sigue en cola
    warns = [a for a in t.alerts if a.type == "WARNING" and cil.id in a.message]
    assert len(warns) == 1
    # No se duplica el aviso en llamadas sucesivas.
    t.assign_machine_work(T0)
    warns = [a for a in t.alerts if a.type == "WARNING" and cil.id in a.message]
    assert len(warns) == 1


def test_jaula_inicial_sin_pareja_no_queda_hibrida():
    """Con un solo cilindro en su rango, la jaula arranca PARADA con 0 trabajando.

    "Pareja completa o nada": el cilindro parcial no debe quedar en la lista de
    trabajando junto con la jaula marcada PARADA (estado híbrido). Y como el CRC
    se llena **de a parejas** (nunca un cilindro suelto), el parcial NO va al CRC:
    queda Disponible pero RESERVADO a la jaula (target_stand) y se reactiva con
    la pareja completa en cuanto aparece un compañero de su rango.
    """
    import pandas as pd

    t = CylinderWorkshop()
    t.configure({
        "config_global": {
            "diametro_maximo": 575.0, "diametro_minimo": 520.0,
            "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1,
        },
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 520.0}],
        "maquinas": _MAQ,
    })
    stock = pd.DataFrame([
        {"ID_Cilindro": "A", "Diámetro_mm": 560.0, "Estado": "Trabajando",
         "Jaula_Asignada": 1, "Posición": 1},
    ])
    cambios = pd.DataFrame(
        [], columns=["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                     "mm_a_Rectificar", "Observación"])
    t.load_data_from_dataframes(stock, cambios)

    stand = t.stands[1]
    assert stand.stopped is True
    assert stand.working_cylinders == []             # no híbrido
    assert stand.crc_cylinders == []                 # el CRC nunca recibe un suelto
    # El parcial queda Disponible pero reservado a la jaula 1 (target_stand).
    cil_a = t.cylinders["A"]
    assert cil_a.state == CylinderState.AVAILABLE
    assert cil_a.target_stand == 1
    assert [c.id for c in t.get_available_for_stand(1)] == ["A"]

    # Al aparecer un compañero compatible, se reactiva con pareja COMPLETA.
    companero = Cylinder("B", 558.0, CylinderState.AVAILABLE)
    t.cylinders["B"] = companero
    assert t._install_pair_or_stop(1, T0) is True
    assert {c.id for c in stand.working_cylinders} == {"A", "B"}
