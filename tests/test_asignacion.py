"""Tests unitarios de la asignación de jaula por perfil y del re-perfilado.

Cubren las reglas nuevas del motor:
  - ``_asignar_jaula_destino`` nunca devuelve una jaula no admisible por
    diámetro (pre-filtro duro) y la estrategia prioriza la jaula más necesitada.
  - Un cilindro que queda no colocable (diámetro en un hueco entre bandas) se
    re-encola a rectificado con un pase de producción de ``_MM_REPERFILADO`` mm
    y emite una alerta INFO.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modelos.taller import TallerCilindros, _MM_REPERFILADO
from modelos.cilindro import Cilindro
from modelos.jaula import Jaula
from modelos.enums import EstadoCilindro, TipoRectificado

T0 = datetime(2026, 1, 1, 6, 0, 0)

# Una máquina mínima 24/7 para los tests que ejercitan rectificado.
_MAQ = [{
    "nombre": "M1", "prioridad": "produccion",
    "tasas": {"produccion": {"mm": 0.8, "tiempo_min": 60},
              "desbaste": {"mm": 5.0, "tiempo_min": 480}},
}]


def _taller(rangos, con_maquina=False):
    """Construye un taller configurado con ``rangos`` y jaulas vacías."""
    t = TallerCilindros()
    cfg = {
        "config_global": {
            "diametro_maximo": 575.0, "diametro_minimo": 520.0,
            "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": len(rangos),
        },
        "rangos": rangos,
        "estrategia_asignacion": "jaula_mas_necesitada",
    }
    if con_maquina:
        cfg["maquinas"] = _MAQ
    t.configurar(cfg)
    for j in range(1, len(rangos) + 1):
        t.jaulas[j] = Jaula(j)
    return t


_BANDAS_SOLAPADAS = [
    {"jaula": 1, "desde": 540.0, "hasta": 520.0, "perfil": "4"},
    {"jaula": 2, "desde": 555.0, "hasta": 530.0, "perfil": "2"},
    {"jaula": 3, "desde": 565.0, "hasta": 540.0, "perfil": "2"},
    {"jaula": 4, "desde": 575.0, "hasta": 555.0, "perfil": "3"},
]


def test_asignar_respeta_prefiltro_por_diametro():
    """La jaula destino siempre admite el diámetro proyectado; nunca una fuera de banda."""
    t = _taller(_BANDAS_SOLAPADAS)
    cil = Cilindro("X", 546.0, EstadoCilindro.RECTIFICANDO)
    t.cilindros[cil.id] = cil
    # 545 sólo cae en jaula 2 (530-555) y jaula 3 (540-565), ambas perfil "2".
    destino, perfil = t._asignar_jaula_destino(cil, 545.0, T0)
    assert destino in (2, 3)
    assert perfil == "2"
    assert cil.jaula_destino == destino
    # El SubStock de la jaula elegida realmente contiene el diámetro proyectado.
    assert t.obtener_substock_por_jaula(destino).contiene_diametro(545.0)


def test_asignar_sin_candidatas_deja_destino_none():
    """Si ninguna banda admite el diámetro proyectado, no se asigna jaula."""
    # Hueco 540-560 entre las dos bandas.
    t = _taller([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ])
    cil = Cilindro("X", 550.8, EstadoCilindro.RECTIFICANDO)
    t.cilindros[cil.id] = cil
    destino, _ = t._asignar_jaula_destino(cil, 550.0, T0)
    assert destino is None
    assert cil.jaula_destino is None


def test_jaula_mas_necesitada_prioriza_deficit():
    """Entre dos jaulas admisibles, elige la de mayor déficit (CRC más vacío)."""
    t = _taller(_BANDAS_SOLAPADAS)
    # Jaula 2 con CRC lleno (déficit 0); jaula 3 vacía (déficit 2). 545 cae en ambas.
    t.jaulas[2].cilindros_crc = [
        Cilindro("A", 545.0, EstadoCilindro.CRC),
        Cilindro("B", 544.0, EstadoCilindro.CRC),
    ]
    cil = Cilindro("X", 546.0, EstadoCilindro.RECTIFICANDO)
    t.cilindros[cil.id] = cil
    destino, _ = t._asignar_jaula_destino(cil, 545.0, T0)
    assert destino == 3  # la más necesitada


def test_es_colocable():
    """``_es_colocable`` refleja la admisibilidad por diámetro y perfil."""
    t = _taller([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ])  # hueco 540-560
    assert t._es_colocable(Cilindro("A", 530.0, EstadoCilindro.DISPONIBLE)) is True
    assert t._es_colocable(Cilindro("B", 550.0, EstadoCilindro.DISPONIBLE)) is False


def test_reperfilado_de_no_colocable():
    """Un cilindro que finaliza en un hueco se re-encola a producción 0.8 mm + alerta INFO."""
    t = _taller([
        {"jaula": 1, "desde": 540.0, "hasta": 520.0},
        {"jaula": 2, "desde": 575.0, "hasta": 560.0},
    ], con_maquina=True)  # hueco 540-560
    maq = t.maquinas["M1"]

    cil = Cilindro("X", 550.8, EstadoCilindro.A_RECTIFICAR)
    cil.tipo_rectificado_actual = TipoRectificado.PRODUCCION
    cil.mm_a_rectificar = 0.8
    t.cilindros[cil.id] = cil

    # Arranca el rectificado y lo finaliza: 550.8 - 0.8 = 550.0 (en el hueco).
    maq.iniciar_rectificado(cil, T0, TipoRectificado.PRODUCCION, 0.8)
    t._finalizar_y_continuar(maq, maq.tiempo_fin_rectificado, [], lambda s: None)

    # Se re-encoló a rectificado con un pase de producción de _MM_REPERFILADO mm.
    assert cil.tipo_rectificado_actual == TipoRectificado.PRODUCCION
    assert cil.mm_a_rectificar == _MM_REPERFILADO
    assert cil.jaula_destino is None
    # Y se registró la alerta INFO de "no colocable".
    assert any(a.tipo == "INFO" and "no colocable" in a.mensaje for a in t.alertas)
