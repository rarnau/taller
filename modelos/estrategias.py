"""Estrategias de selección de la cola de rectificado.

Cada estrategia es un objeto con: `clave` (id para GUI/CLI/persistencia),
`etiqueta` (texto a mostrar) y `seleccionar(cola, maquina)`, que recibe la cola
YA filtrada por prioridad de la máquina y devuelve el cilindro a rectificar.
Para agregar una estrategia nueva: subclasar EstrategiaSeleccion y registrarla
en ESTRATEGIAS_SELECCION; la GUI y el CLI la toman de ahí.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, TypeVar

from . import turnos
from .cilindro import Cilindro
from .enums import EstadoCilindro, TipoRectificado
from .maquina import MaquinaRectificadora

if TYPE_CHECKING:  # solo para anotaciones: evita el ciclo taller → estrategias
    from .taller import TallerCilindros

_E = TypeVar("_E")


def resolver(registro: Dict[str, _E], clave: str, defecto: str) -> _E:
    """Devuelve la estrategia ``clave`` del registro, o la de ``defecto`` si falta."""
    return registro.get(clave, registro[defecto])


class EstrategiaSeleccion:
    """Estrategia de selección de un cilindro de la cola de rectificado."""

    clave: str = ""
    etiqueta: str = ""

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
        raise NotImplementedError


class _MayorDiametro(EstrategiaSeleccion):
    clave, etiqueta = "mayor_diametro", "Mayor diámetro"

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
        return max(cola, key=lambda c: c.diametro)


class _MenorDiametro(EstrategiaSeleccion):
    clave, etiqueta = "menor_diametro", "Menor diámetro"

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
        return min(cola, key=lambda c: c.diametro)


class _Fifo(EstrategiaSeleccion):
    clave, etiqueta = "fifo", "FIFO (orden de llegada)"

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
        return cola[0]


class _MenorMmDesbasteFifoProduccion(EstrategiaSeleccion):
    """Menor mm a rectificar cuando la máquina prioriza desbaste; FIFO en otro caso."""

    clave = "menor_mm_desb_fifo_prod"
    etiqueta = "Menor mm desbaste / FIFO producción"

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
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


# ── Estrategias de asignación de jaula destino ───────────────────────────────
#
# Al iniciar un rectificado el motor decide a qué jaula se destina el cilindro
# (y por tanto qué perfil se le talla). La estrategia recibe las jaulas YA
# filtradas por diámetro admisible (pre-filtro duro) y elige una de ellas. Para
# agregar una estrategia nueva: subclasar EstrategiaAsignacion y registrarla en
# ESTRATEGIAS_ASIGNACION; la GUI y el CLI la toman de ahí.

# Estados de un cilindro "en camino" a una jaula (comprometido pero no instalado).
_ESTADOS_EN_CAMINO = frozenset((
    EstadoCilindro.ENFRIANDO,
    EstadoCilindro.A_RECTIFICAR,
    EstadoCilindro.RECTIFICANDO,
    EstadoCilindro.DISPONIBLE,
    EstadoCilindro.CRC,
))


class EstrategiaAsignacion:
    """Estrategia de asignación de la jaula destino al iniciar un rectificado."""

    clave: str = ""
    etiqueta: str = ""

    def asignar(self, cilindro: Cilindro, jaulas_candidatas: List[int],
                taller: "TallerCilindros") -> int:
        raise NotImplementedError


class _JaulaMasNecesitada(EstrategiaAsignacion):
    """Entre las candidatas (ya admisibles por diámetro), la de mayor déficit.

    Prioriza jaulas paradas; luego el mayor déficit de stock
    (``_BUFFER_CRC_SIZE`` − CRC − cilindros ya destinados en camino);
    desempate por número de jaula (menor primero) para ser determinista.
    """

    clave, etiqueta = "jaula_mas_necesitada", "Jaula más necesitada"

    def asignar(self, cilindro: Cilindro, jaulas_candidatas: List[int],
                taller: "TallerCilindros") -> int:
        # El déficit es buffer − (CRC + en_camino); el término "buffer" es igual
        # para todas las candidatas, así que ordenar por menor (CRC + en_camino)
        # equivale a mayor déficit (la más necesitada), sin depender del buffer.
        # Un solo pase cuenta los "en camino" por jaula destino (antes se
        # re-escaneaban todos los cilindros por cada candidata, O(candidatas×cil)).
        en_camino_por_jaula: Dict[int, int] = {}
        for c in taller.cilindros.values():
            if c.jaula_destino is not None and c.estado in _ESTADOS_EN_CAMINO:
                en_camino_por_jaula[c.jaula_destino] = en_camino_por_jaula.get(c.jaula_destino, 0) + 1

        def _orden(j: int):
            jaula = taller.jaulas[j]
            parada = 0 if getattr(jaula, "parada", False) else 1  # paradas primero
            comprometidos = len(jaula.cilindros_crc) + en_camino_por_jaula.get(j, 0)
            return (parada, comprometidos, j)  # menor tupla = más necesitada

        return min(jaulas_candidatas, key=_orden)


ESTRATEGIAS_ASIGNACION: Dict[str, EstrategiaAsignacion] = {
    e.clave: e for e in (
        _JaulaMasNecesitada(),
    )
}
ESTRATEGIA_ASIGNACION_DEFECTO = "jaula_mas_necesitada"


# ── Estrategias de reposición de cilindros ───────────────────────────────────
#
# Cuando un cilindro cae por debajo del diámetro mínimo se da de BAJA. La
# estrategia de reposición decide si (y cuándo) llegan cilindros nuevos para
# reemplazarlo. Se invoca tras cada BAJA de runtime (ver TallerCilindros.
# _planificar_reposicion); es STATELESS (singleton compartido entre procesos):
# todo el estado mutable de la corrida vive en el taller (_repo_bajas_pendientes,
# _repo_ultima_llegada). Para agregar una estrategia nueva: subclasar
# EstrategiaReposicion y registrarla en ESTRATEGIAS_REPOSICION; la GUI y el CLI
# la toman de ahí.


@dataclass
class PedidoReposicion:
    """Un lote de cilindros nuevos a agendar: cuándo llegan, cuántos y a qué diámetro."""
    tiempo_llegada: datetime
    cantidad: int
    diametro: float


class EstrategiaReposicion:
    """Estrategia de reposición de cilindros nuevos ante las BAJAs."""

    clave: str = ""
    etiqueta: str = ""

    def planificar(self, taller: "TallerCilindros",
                   tiempo_baja: datetime) -> List[PedidoReposicion]:
        """Tras una BAJA en ``tiempo_baja``, devuelve los lotes a agendar (puede ser [])."""
        raise NotImplementedError


class _SinReposicion(EstrategiaReposicion):
    """Por defecto: el taller nunca repone (comportamiento histórico)."""

    clave, etiqueta = "ninguna", "Sin reposición"

    def planificar(self, taller: "TallerCilindros",
                   tiempo_baja: datetime) -> List[PedidoReposicion]:
        return []


class _LoteMensual(EstrategiaReposicion):
    """Cada ``TAMANO_LOTE`` bajas ⇒ un lote de cilindros nuevos al diámetro máximo.

    El lote llega el primer día operativo (régimen de la línea, ``grilla_cambios``)
    del mes siguiente. Si se acumula más de un lote, se escalonan uno por mes
    (8 bajas ⇒ 4 el mes siguiente y 4 el mes posterior), encadenando desde
    ``taller._repo_ultima_llegada``.
    """

    clave, etiqueta = "lote_4_mensual", "Lote de 4 al mes siguiente"
    TAMANO_LOTE = 4

    def planificar(self, taller: "TallerCilindros",
                   tiempo_baja: datetime) -> List[PedidoReposicion]:
        pedidos: List[PedidoReposicion] = []
        ref = taller._repo_ultima_llegada or tiempo_baja
        pend = taller._repo_bajas_pendientes
        while pend >= self.TAMANO_LOTE:
            llegada = turnos.primer_dia_operativo_mes_siguiente(taller.grilla_cambios, ref)
            pedidos.append(PedidoReposicion(llegada, self.TAMANO_LOTE, taller.diametro_maximo))
            pend -= self.TAMANO_LOTE
            ref = llegada  # el próximo lote llega el mes siguiente a éste
        return pedidos


ESTRATEGIAS_REPOSICION: Dict[str, EstrategiaReposicion] = {
    e.clave: e for e in (
        _SinReposicion(),
        _LoteMensual(),
    )
}
ESTRATEGIA_REPOSICION_DEFECTO = "ninguna"
