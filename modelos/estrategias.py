"""Estrategias de selección de la cola de rectificado.

Cada estrategia es un objeto con: `clave` (id para GUI/CLI/persistencia),
`etiqueta` (texto a mostrar) y `seleccionar(cola, maquina)`, que recibe la cola
YA filtrada por prioridad de la máquina y devuelve el cilindro a rectificar.
Para agregar una estrategia nueva: subclasar EstrategiaSeleccion y registrarla
en ESTRATEGIAS_SELECCION; la GUI y el CLI la toman de ahí.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Dict, FrozenSet, List, Optional, Set, Tuple, TypeVar

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
    etiqueta = "desb menor mm + jaula / prod jaula"

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


# ── Estrategias de trasvase de cilindros entre jaulas ────────────────────────
#
# Con bandas solapadas y perfiles, una jaula puede quedarse sin cilindros
# UTILIZABLES (perfil propio) mientras una banda superior tiene excedente
# diámetro-admisible de otro perfil. La estrategia de trasvase decide,
# proactivamente, qué cilindros Disponibles re-perfilar (pase de producción de
# MM_REPERFILADO mm hacia una jaula receptora) para nivelar el stock útil.
# Se invoca tras cada CAMBIO y tras cada fin de rectificado (ver
# TallerCilindros._planificar_trasvases); es STATELESS (singleton compartido
# entre procesos): el contador de la corrida vive en el taller (_trasvases) y
# los parámetros en la config (taller.trasvase_umbral / trasvase_objetivo).
# Para agregar una estrategia nueva: subclasar EstrategiaTrasvase y registrarla
# en ESTRATEGIAS_TRASVASE; la GUI y el CLI la toman de ahí.

# mm del pase de producción de un re-perfilado (cambio de perfil fuera de un
# cambio programado). Fuente única del valor: el motor lo consume como
# taller._MM_REPERFILADO (alias) y las estrategias de trasvase lo usan para
# proyectar el diámetro post-pase de los candidatos.
MM_REPERFILADO: float = 0.8


class EstrategiaTrasvase:
    """Estrategia de trasvase proactivo de cilindros entre jaulas."""

    clave: str = ""
    etiqueta: str = ""

    def planificar(self, taller: "TallerCilindros",
                   tiempo: datetime) -> List[Tuple[Cilindro, int]]:
        """Devuelve pares (cilindro, jaula receptora) a re-perfilar (puede ser [])."""
        raise NotImplementedError


class _SinTrasvase(EstrategiaTrasvase):
    """Por defecto: el taller nunca trasvasa (comportamiento histórico)."""

    clave, etiqueta = "ninguno", "Sin trasvase"

    def planificar(self, taller: "TallerCilindros",
                   tiempo: datetime) -> List[Tuple[Cilindro, int]]:
        return []


class _CascadaUmbral(EstrategiaTrasvase):
    """Cascada superior → inferior por umbral/objetivo de stock útil.

    Cuando el stock útil de una jaula (``taller.stock_util_por_jaula``: los
    cilindros que HOY pueden servirla, perfil incluido) cae bajo
    ``taller.trasvase_umbral``, se re-perfilan Disponibles de bandas
    **superiores** hacia ella hasta dejarla en ``taller.trasvase_objetivo`` —
    o lo que se pueda (mejor esfuerzo). Reglas:

    - **Dirección**: el flujo es siempre de rangos superiores a inferiores
      (rectificar solo reduce diámetro). Un candidato solo puede donarse si
      todas sus jaulas "dueñas" son estrictamente superiores a la receptora en
      el orden de bandas (stock sin dueña = stock muerto, se permite siempre).
      Dueñas de un candidato: su ``jaula_destino`` si está reservado (el caso
      normal — todo cilindro rectificado queda Disponible con la reserva de su
      jaula hasta instalarse), o las jaulas donde es admisible si está libre.
    - **Dos costos de trasvase**: si el candidato ya entra en la receptora por
      diámetro y perfil (solo lo retiene una reserva a otra jaula), se
      **reasigna sin pase** (0 mm, disponible al instante). Si no, se
      re-perfila con **un pase** de ``MM_REPERFILADO`` mm: solo es candidato si
      el diámetro proyectado cae en la banda receptora y no baja del mínimo.
      El descenso multi-banda lo cubre la **cascada** de jaulas, no pases
      encadenados de un mismo cilindro.
    - **Piso del donante = el umbral**: ninguna donación deja a una jaula
      donante por debajo del umbral. Un donante puede quedar entre umbral y
      objetivo: como las jaulas se procesan de inferior a superior, al llegar
      su turno se rellena desde SUS superiores hasta el objetivo (efecto
      cascada dentro de la misma ronda).
    - **Determinismo**: candidatos ordenados por costo (reasignación antes que
      re-perfilado), luego mayor holgura del donante, mayor diámetro y por
      último id; jaulas por banda (desde asc, nº asc).
    """

    clave, etiqueta = "cascada_umbral", "Cascada sup→inf por umbral"

    def planificar(self, taller: "TallerCilindros",
                   tiempo: datetime) -> List[Tuple[Cilindro, int]]:
        objetivo = int(getattr(taller, "trasvase_objetivo", 12))
        umbral = min(int(getattr(taller, "trasvase_umbral", 8)), objetivo)

        # Orden de bandas: inferior primero (por límite superior 'desde'
        # ascendente; desempate por nº de jaula). Jaulas sin SubStock no juegan.
        con_banda = [
            (ss.desde, j)
            for j in range(1, taller.cantidad_jaulas + 1)
            if (ss := taller.obtener_substock_por_jaula(j)) is not None
        ]
        orden = [j for _, j in sorted(con_banda)]
        if len(orden) < 2:
            return []
        pos = {j: i for i, j in enumerate(orden)}

        usable = dict(taller.stock_util_por_jaula())

        # Early-out: si ninguna jaula arranca bajo umbral, el plan es vacío. La
        # cascada solo marca una jaula donante (``donaron``) DESPUÉS de que una
        # jaula bajo umbral tire de ella, así que sin ninguna jaula bajo umbral
        # el bucle de abajo no dispara nada. Evita construir la lista completa
        # de candidatos en cada evento con el stock sano (el caso normal), que
        # es donde se iba el grueso del tiempo. Byte-idéntico.
        if all(usable.get(j, 0) >= umbral for j in orden):
            return []

        # Candidatos: TODOS los Disponibles, con su set de jaulas "dueñas" (las
        # que pierden 1 útil si se dona). Un reservado (jaula_destino, el caso
        # normal tras un rectificado) tiene una única dueña: su reserva; un
        # libre, las jaulas donde es admisible hoy.
        candidatos: List[Tuple[Cilindro, FrozenSet[int]]] = []
        for c in taller.cilindros.values():
            if c.estado != EstadoCilindro.DISPONIBLE:
                continue
            if c.jaula_destino is not None:
                duenas = (frozenset({int(c.jaula_destino)})
                          if c.jaula_destino in pos else frozenset())
            else:
                duenas = frozenset(j for j in orden if taller._admisible_en_jaula(c, j))
            candidatos.append((c, duenas))

        plan: List[Tuple[Cilindro, int]] = []
        elegidos: Set[str] = set()
        donaron: Set[int] = set()

        for j in orden:  # de inferior a superior: la cascada se resuelve en 1 ronda
            stock_j = usable.get(j, 0)
            if not (stock_j < umbral or (j in donaron and stock_j < objetivo)):
                continue
            ss_j = taller.obtener_substock_por_jaula(j)
            deficit = objetivo - stock_j
            while deficit > 0:
                mejor: Optional[Tuple[Cilindro, FrozenSet[int]]] = None
                mejor_orden = None
                for c, duenas in candidatos:
                    if c.id in elegidos or j in duenas:
                        continue  # ya elegido / ya es útil para j (no hace falta nada)
                    # Reasignación pura: ya entra en j por diámetro y perfil,
                    # solo lo retiene una reserva a otra jaula (0 mm de costo).
                    reasignable = (ss_j.contiene_diametro(c.diametro)
                                   and taller._perfil_compatible(c.perfil, ss_j.perfil))
                    if not reasignable:
                        d_fin = round(c.diametro - MM_REPERFILADO, 2)
                        if d_fin < taller.diametro_minimo or not ss_j.contiene_diametro(d_fin):
                            continue  # el pase no lo deja dentro de la banda receptora
                    if any(pos[k] <= pos[j] for k in duenas):
                        continue  # dirección: solo desde bandas superiores
                    if any(usable.get(k, 0) - 1 < umbral for k in duenas):
                        continue  # piso del donante: nunca dejarlo bajo el umbral
                    holgura = min((usable.get(k, 0) - umbral for k in duenas),
                                  default=10 ** 9)  # stock muerto: holgura infinita
                    orden_cand = (0 if reasignable else 1, -holgura, -c.diametro, c.id)
                    if mejor is None or orden_cand < mejor_orden:
                        mejor, mejor_orden = (c, duenas), orden_cand
                if mejor is None:
                    break  # sin candidatos: mejor esfuerzo ("o intentarlo")
                c, duenas = mejor
                elegidos.add(c.id)
                for k in duenas:
                    usable[k] = usable.get(k, 0) - 1
                    donaron.add(k)
                usable[j] = usable.get(j, 0) + 1
                plan.append((c, j))
                deficit -= 1
        return plan


ESTRATEGIAS_TRASVASE: Dict[str, EstrategiaTrasvase] = {
    e.clave: e for e in (
        _SinTrasvase(),
        _CascadaUmbral(),
    )
}
ESTRATEGIA_TRASVASE_DEFECTO = "ninguno"


# ── Estrategias de montaje POR JAULA ─────────────────────────────────────────
#
# Cuando una jaula toma stock (subir la pareja al CRC, rearmar la pareja de
# trabajo o la colocación inicial), la estrategia de montaje de ESA jaula
# decide qué Disponible admisible va primero. Es configuración POR JAULA
# (campo opcional ``montaje`` de cada entrada de ``rangos`` en
# user_config.json, como ``perfil``), así que NO entra en FAMILIAS_ESTRATEGIA
# (esa tabla cablea claves globales del cfg). El motor la consulta vía
# ``TallerCilindros._ordenar_montaje``; la GUI (columna Montaje de la tabla de
# rangos) y el CLI (``config jaula set --montaje``) derivan sus opciones de
# este registro. Son funciones puras de ordenamiento: estables por diámetro
# únicamente (los empates conservan el orden de inserción, semántica del
# motor), sin estado.


class EstrategiaMontaje:
    """Orden en que los Disponibles admisibles se montan en una jaula."""

    clave: str = ""
    etiqueta: str = ""

    def ordenar(self, disponibles: List[Cilindro]) -> List[Cilindro]:
        """Devuelve los candidatos ordenados (el primero se monta primero)."""
        raise NotImplementedError


class _MontajeMayorDiametro(EstrategiaMontaje):
    """Histórico (default): primero el de mayor diámetro."""

    clave, etiqueta = "mayor_diametro", "Mayor diámetro"

    def ordenar(self, disponibles: List[Cilindro]) -> List[Cilindro]:
        # Byte-idéntico al sort histórico del motor (estable, reverse=True).
        return sorted(disponibles, key=lambda c: c.diametro, reverse=True)


class _MontajeMenorDiametro(EstrategiaMontaje):
    """Primero el de menor diámetro (apura la rotación del stock chico)."""

    clave, etiqueta = "menor_diametro", "Menor diámetro"

    def ordenar(self, disponibles: List[Cilindro]) -> List[Cilindro]:
        return sorted(disponibles, key=lambda c: c.diametro)


ESTRATEGIAS_MONTAJE: Dict[str, EstrategiaMontaje] = {
    e.clave: e for e in (
        _MontajeMayorDiametro(),
        _MontajeMenorDiametro(),
    )
}
ESTRATEGIA_MONTAJE_DEFECTO = "mayor_diametro"


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
    FamiliaEstrategia("estrategia_trasvase", "--estrategia-trasvase",
                      "estrategia_trasvase", "Estrategia de trasvase",
                      ESTRATEGIAS_TRASVASE, ESTRATEGIA_TRASVASE_DEFECTO),
)
