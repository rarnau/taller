"""Tests para estrategias de selección de la cola de rectificado."""

from modelos.cilindro import Cilindro
from modelos.enums import EstadoCilindro, TipoRectificado
from modelos.estrategias import ESTRATEGIAS_SELECCION
from modelos.maquina import MaquinaRectificadora


def _maq(prioridad: TipoRectificado) -> MaquinaRectificadora:
    m = MaquinaRectificadora("M")
    m.prioridad_defecto = prioridad
    return m


def _cil(cid: str, mm: float, destino: int | None, tipo: TipoRectificado) -> Cilindro:
    c = Cilindro(cid, 550.0, EstadoCilindro.A_RECTIFICAR)
    c.mm_a_rectificar = mm
    c.jaula_destino = destino
    c.tipo_rectificado_actual = tipo
    return c


def test_registry_expone_estrategia_nueva_seleccion():
    assert "menor_mm_jaula_stock_desb_mas_nec_prod" in ESTRATEGIAS_SELECCION


def test_desbaste_menor_mm_y_desempate_por_jaula_menor_stock():
    """DESBASTE: elige menor mm; si empatan, menor stock comprometido por jaula."""
    est = ESTRATEGIAS_SELECCION["menor_mm_jaula_stock_desb_mas_nec_prod"]
    maq = _maq(TipoRectificado.DESBASTE)

    # Empatan en mm=1.0. Jaula 2 tiene 2 en cola; jaula 3 tiene 1 => gana jaula 3.
    c1 = _cil("C1", 1.0, 2, TipoRectificado.DESBASTE)
    c2 = _cil("C2", 1.0, 2, TipoRectificado.DESBASTE)
    c3 = _cil("C3", 1.0, 3, TipoRectificado.DESBASTE)
    elegido = est.seleccionar([c1, c2, c3], maq)
    assert elegido.id == "C3"


def test_produccion_prioriza_jaula_mas_necesitada_en_cola():
    """PRODUCCION: prefiere jaula con menor comprometido (aprox. más necesitada)."""
    est = ESTRATEGIAS_SELECCION["menor_mm_jaula_stock_desb_mas_nec_prod"]
    maq = _maq(TipoRectificado.PRODUCCION)

    # Jaula 2 tiene 2 en cola, jaula 3 tiene 1 => para producción debe preferir 3.
    # Aunque C2 tenga menor mm, C3 debe ganar por necesidad de jaula.
    c1 = _cil("C1", 1.2, 2, TipoRectificado.PRODUCCION)
    c2 = _cil("C2", 0.8, 2, TipoRectificado.PRODUCCION)
    c3 = _cil("C3", 1.0, 3, TipoRectificado.PRODUCCION)
    elegido = est.seleccionar([c1, c2, c3], maq)
    assert elegido.id == "C3"


def test_si_no_hay_jaula_destino_cae_a_menor_mm():
    est = ESTRATEGIAS_SELECCION["menor_mm_jaula_stock_desb_mas_nec_prod"]
    maq = _maq(TipoRectificado.DESBASTE)

    c1 = _cil("C1", 1.4, None, TipoRectificado.DESBASTE)
    c2 = _cil("C2", 0.9, None, TipoRectificado.DESBASTE)
    elegido = est.seleccionar([c1, c2], maq)
    assert elegido.id == "C2"
