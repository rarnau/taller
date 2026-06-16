"""Estrategias de selección de la cola de rectificado.

Cada estrategia es un objeto con: `clave` (id para GUI/CLI/persistencia),
`etiqueta` (texto a mostrar) y `seleccionar(cola, maquina)`, que recibe la cola
YA filtrada por prioridad de la máquina y devuelve el cilindro a rectificar.
Para agregar una estrategia nueva: subclasar EstrategiaSeleccion y registrarla
en ESTRATEGIAS_SELECCION; la GUI y el CLI la toman de ahí.
"""
from typing import Dict, List, Optional

from .cilindro import Cilindro
from .enums import TipoRectificado
from .maquina import MaquinaRectificadora


class EstrategiaSeleccion:
    """Estrategia de selección de un cilindro de la cola de rectificado."""

    clave: str = ""
    etiqueta: str = ""

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
        raise NotImplementedError


class _MayorDiametro(EstrategiaSeleccion):
    clave, etiqueta = "mayor_diametro", "Mayor diámetro"

    def seleccionar(self, cola, maquina):
        return max(cola, key=lambda c: c.diametro)


class _MenorDiametro(EstrategiaSeleccion):
    clave, etiqueta = "menor_diametro", "Menor diámetro"

    def seleccionar(self, cola, maquina):
        return min(cola, key=lambda c: c.diametro)


class _Fifo(EstrategiaSeleccion):
    clave, etiqueta = "fifo", "FIFO (orden de llegada)"

    def seleccionar(self, cola, maquina):
        return cola[0]


class _MenorMmDesbasteFifoProduccion(EstrategiaSeleccion):
    """Menor mm a rectificar cuando la máquina prioriza desbaste; FIFO en otro caso."""

    clave = "menor_mm_desb_fifo_prod"
    etiqueta = "Menor mm desbaste / FIFO producción"

    def seleccionar(self, cola, maquina):
        if maquina is not None and maquina.prioridad_defecto == TipoRectificado.DESBASTE:
            return min(cola, key=lambda c: c.mm_a_rectificar)
        return cola[0]


ESTRATEGIAS_SELECCION: Dict[str, EstrategiaSeleccion] = {
    e.clave: e for e in (
        _MayorDiametro(),
        _MenorDiametro(),
        _Fifo(),
        _MenorMmDesbasteFifoProduccion(),
    )
}
ESTRATEGIA_DEFECTO = "fifo"
