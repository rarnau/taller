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


class _MenorMmJaulaMenorStockDesbMasNecesitadaProd(EstrategiaSeleccion):
    """Selección por tipo de pase:

    - DESBASTE: menor mm a rectificar; empate por jaula destino con menor stock
      comprometido (CRC + en camino), luego id para determinismo.
    - PRODUCCION: prioriza cilindros destinados a la jaula más necesitada
      (paradas primero y menor comprometido), luego menor mm, luego id.

    Nota: esta estrategia usa ``jaula_destino`` (si está definido). Si no hay
    destino en el cilindro, cae a menor mm + determinismo.
    """

    clave = "menor_mm_jaula_stock_desb_mas_nec_prod"
    etiqueta = "Menor mm + jaula stock (desb) / más necesitada (prod)"

    @staticmethod
    def _en_camino_por_jaula(cola: List[Cilindro]) -> Dict[int, int]:
        en_camino: Dict[int, int] = {}
        for c in cola:
            if c.jaula_destino is not None:
                en_camino[c.jaula_destino] = en_camino.get(c.jaula_destino, 0) + 1
        return en_camino

    def seleccionar(self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora]) -> Cilindro:
        if maquina is None:
            return min(cola, key=lambda c: (c.mm_a_rectificar, c.id))

        en_camino = self._en_camino_por_jaula(cola)

        if maquina.prioridad_defecto == TipoRectificado.DESBASTE:
            def _key_desb(c: Cilindro):
                comprometidos = en_camino.get(c.jaula_destino, 0) if c.jaula_destino is not None else 10**6
                return (c.mm_a_rectificar, comprometidos, c.id)

            return min(cola, key=_key_desb)

        # Producción: preferir jaulas más necesitadas; luego menor mm.
        def _key_prod(c: Cilindro):
            if c.jaula_destino is None:
                return (1, 10**6, c.mm_a_rectificar, c.id)
            comprometidos = en_camino.get(c.jaula_destino, 0)
            return (0, comprometidos, c.mm_a_rectificar, c.id)

        return min(cola, key=_key_prod)


ESTRATEGIAS_SELECCION: Dict[str, EstrategiaSeleccion] = {
    e.clave: e for e in (
        _MayorDiametro(),
        _MenorDiametro(),
        _Fifo(),
        _MenorMmDesbasteFifoProduccion(),
        _MenorMmJaulaMenorStockDesbMasNecesitadaProd(),
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
        en_camino_por_jaula = _en_camino_por_jaula(taller)

        def _orden(j: int):
            jaula = taller.jaulas[j]
            parada = 0 if getattr(jaula, "parada", False) else 1  # paradas primero
            comprometidos = len(jaula.cilindros_crc) + en_camino_por_jaula.get(j, 0)
            return (parada, comprometidos, j)  # menor tupla = más necesitada

        return min(jaulas_candidatas, key=_orden)


def _en_camino_por_jaula(taller: "TallerCilindros") -> Dict[int, int]:
    """Conteo de cilindros comprometidos por jaula destino (no instalados aún)."""
    en_camino: Dict[int, int] = {}
    for c in taller.cilindros.values():
        if c.jaula_destino is not None and c.estado in _ESTADOS_EN_CAMINO:
            en_camino[c.jaula_destino] = en_camino.get(c.jaula_destino, 0) + 1
    return en_camino


class _PrioridadJ1J4ConPiso(EstrategiaAsignacion):
    """Estrategia DEFINIDA de balance de stock: prioriza J1/J4 con piso mínimo.

    Los pesos y el piso viven en la estrategia (no hay configuración por
    jaula). Entre las candidatas (ya admisibles por diámetro) elige con esta
    precedencia:

    1. Jaulas paradas primero (precedente de "jaula más necesitada").
    2. **Piso de seguridad** (``PISO_STOCK`` = 10): toda candidata cuyo stock
       activo esté por debajo del piso va antes que las que lo superan; entre
       varias bajo el piso gana la más vacía (menor stock absoluto).
    3. Sobre el piso, **balance ponderado**: menor ``stock/peso`` con los
       ``PESOS`` fijos J1=1.44, J2=1.2, J3=1.0, J4=1.2 (jaulas fuera del dict
       pesan 1.0) — J1 apunta a un 20% más de stock que J2, y J2/J4 a un 20%
       más que J3, antes de perder la preferencia.
    4. Desempate por número de jaula (determinista).

    El stock comparado es ``TallerCilindros.stock_activos_por_jaula()``:
    cilindros no BAJA con atribución única (sin repetidos con bandas
    solapadas), la misma métrica del gráfico de evolución de Análisis. Como
    toda estrategia de asignación, solo tiene efecto cuando las bandas se
    solapan (bandas disjuntas ⇒ una única candidata).
    """

    clave, etiqueta = "prioridad_j1_j4_piso10", "Prioridad J1/J4 +20% (piso 10)"
    PISO_STOCK = 10
    PESOS = {1: 1.44, 2: 1.2, 3: 1.0, 4: 1.2}

    def asignar(self, cilindro: Cilindro, jaulas_candidatas: List[int],
                taller: "TallerCilindros") -> int:
        stock = taller.stock_activos_por_jaula()

        def _orden(j: int):
            jaula = taller.jaulas[j]
            parada = 0 if getattr(jaula, "parada", False) else 1  # paradas primero
            s = stock.get(j, 0)
            if s < self.PISO_STOCK:
                return (parada, 0, float(s), j)   # bajo el piso: la más vacía primero
            peso = self.PESOS.get(j, 1.0)
            return (parada, 1, s / peso, j)       # sobre el piso: balance ponderado

        return min(jaulas_candidatas, key=_orden)


ESTRATEGIAS_ASIGNACION: Dict[str, EstrategiaAsignacion] = {
    e.clave: e for e in (
        _JaulaMasNecesitada(),
        _PrioridadJ1J4ConPiso(),
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


class _StockConstante(EstrategiaReposicion):
    """Reposición 1:1 inmediata: por cada BAJA entra 1 cilindro nuevo."""

    clave, etiqueta = "stock_constante", "Stock constante (1 baja -> 1 alta)"

    def planificar(self, taller: "TallerCilindros",
                   tiempo_baja: datetime) -> List[PedidoReposicion]:
        return [PedidoReposicion(tiempo_baja, 1, taller.diametro_maximo)]


ESTRATEGIAS_REPOSICION: Dict[str, EstrategiaReposicion] = {
    e.clave: e for e in (
        _SinReposicion(),
        _LoteMensual(),
        _StockConstante(),
    )
}
ESTRATEGIA_REPOSICION_DEFECTO = "ninguna"


# ── Tabla de familias de estrategia ──────────────────────────────────────────
#
# Las tres familias (selección / asignación / reposición) se cablean igual en
# varios consumidores (clave en user_config.json + atributo del taller, flag del
# CLI, combo de la GUI, registro y defecto). Esta tabla declarativa es la fuente
# única que recorren `cli.py` (flags de `config sim`), `gui_qt/config_qt.py`
# (combos) y `TallerCilindros.configurar` (lectura de config), para que agregar
# una familia nueva sea registrar la estrategia + añadir UNA fila aquí.


@dataclass(frozen=True)
class FamiliaEstrategia:
    clave_cfg: str        # clave en user_config.json y atributo del taller
    flag_cli: str         # flag de `cli.py config sim` (p. ej. "--estrategia-seleccion")
    dest_cli: str         # argparse dest del flag (p. ej. "estrategia_seleccion")
    etiqueta_ui: str      # etiqueta de la fila en la GUI
    registro: Dict[str, object]
    defecto: str


FAMILIAS_ESTRATEGIA = (
    FamiliaEstrategia("estrategia_seleccion", "--estrategia-seleccion",
                      "estrategia_seleccion", "Estrategia de seleccion",
                      ESTRATEGIAS_SELECCION, ESTRATEGIA_DEFECTO),
    FamiliaEstrategia("estrategia_asignacion", "--estrategia-asignacion",
                      "estrategia_asignacion", "Estrategia de asignacion",
                      ESTRATEGIAS_ASIGNACION, ESTRATEGIA_ASIGNACION_DEFECTO),
    FamiliaEstrategia("estrategia_reposicion", "--estrategia-reposicion",
                      "estrategia_reposicion", "Estrategia de reposicion",
                      ESTRATEGIAS_REPOSICION, ESTRATEGIA_REPOSICION_DEFECTO),
)
