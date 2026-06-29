"""
Modelo de una máquina rectificadora de cilindros.
"""
import hashlib
from bisect import bisect_right
from datetime import datetime, timedelta
from typing import Callable, Optional, List, Dict, Any, Tuple
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro

# ── Sorteo determinista barato para la tasa de falla ─────────────────────────
# splitmix64: mezcla entera de 64 bits (avalancha) usada para derivar un número
# pseudo-aleatorio por hora sin construir/hashear un string cada vez (el sha256
# por hora era el camino más caliente en barridos largos). El sha256 se usa una
# sola vez por (máquina, seed) para la semilla base (ver _base_fallas).
_MASK64 = (1 << 64) - 1
_DOS64 = float(1 << 64)
_EPOCH_FALLAS = datetime(1970, 1, 1)


def _splitmix64(x: int) -> int:
    """Mezcla splitmix64 (entera, 64 bits). Determinista y portable entre procesos."""
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


class MaquinaRectificadora:
    """
    Simula el comportamiento de una rectificadora: capacidad, tiempos de proceso
    e historial de trabajos realizados.

    Tasas de rectificado:
      Cada tipo de pase (produccion/desbaste) tiene su propia tasa en mm/min.
      Si la tasa es 0 o el tipo no está configurado, calcular_tiempo_proceso
      devuelve float('inf'), indicando que ese tipo de pase no es posible.
    """

    def __init__(self, nombre: str):
        self.nombre: str = nombre
        self.ocupada: bool = False
        self.cilindro_actual: Optional[Cilindro] = None
        self.tiempo_fin_rectificado: Optional[datetime] = None

        # {tipo_str: {"mm": float, "t_min": float, "rate": float}}
        self.tasas_rectificado: Dict[str, Dict[str, float]] = {}
        self.prioridad_defecto: TipoRectificado = TipoRectificado.PRODUCCION

        self.historial_trabajo: List[Dict[str, Any]] = []
        self.tiempo_total_ocupada_min: float = 0.0

        # Esquema de trabajo: grilla horaria semanal 7×24 de booleanos
        # (grilla[weekday][hora]). None = siempre operativa (24/7), que reproduce
        # exactamente el comportamiento histórico. Ver modelos/turnos.py.
        self.grilla_operativa: Optional[List[List[bool]]] = None
        # Minutos de trabajo (tiempo operativo) del rectificado en curso; sirve
        # de denominador para el progreso del snapshot.
        self.minutos_trabajo_actual: float = 0.0
        # Flag para no duplicar eventos de despertar (REANUDAR_MAQUINA).
        self._despertar_programado: bool = False

        # Progreso del rectificado en curso. Con turnos se precalculan una sola
        # vez los hitos (frontera_horaria, minutos_operativos_acumulados) en
        # iniciar_rectificado y el progreso por snapshot se resuelve por bisect
        # (O(log h)) en vez de recorrer la grilla cada vez. Con grilla 24/7 los
        # hitos quedan None y el progreso es reloj directo.
        self._inicio_rectificado: Optional[datetime] = None
        self._hitos_t: Optional[List[datetime]] = None
        self._hitos_min: Optional[List[float]] = None

        # Tasa de falla: fracción [0,1] del tiempo OPERATIVO (en turno) en que la
        # máquina está caída. 0.0 (defecto) = sin fallas, comportamiento histórico
        # byte-for-byte. La realización es determinista y stateless (ver en_falla):
        # cada hora operativa se sortea por hash(seed, nombre, hora), de modo que
        # ~tasa_falla de las horas quedan en falla. La seed de la corrida (run-level)
        # la fija TallerCilindros.simular(); None ⇒ sin fallas aunque tasa>0.
        # Las fallas pausan el rectificado y se retoma al salir, igual que un hueco
        # de turno (se hornean en calcular_fin_operativo vía _hora_trabajable).
        self.tasa_falla: float = 0.0
        self._seed_fallas: Optional[int] = None
        # Caché de la semilla base (seed, nombre) → entero; evita rehashear por
        # hora. Tupla (seed, base) o None; se revalida si cambia _seed_fallas.
        self._base_fallas_cache: Optional[Tuple[Optional[int], int]] = None

    def reiniciar_estado_corrida(self) -> None:
        """Resetea el estado acumulado por una corrida (no la configuración).

        Deja la máquina como recién creada en lo que respecta a una simulación
        (libre, sin trabajo en curso, sin historial ni tiempo ocupado), pero
        conserva la configuración persistente (``tasas_rectificado``,
        ``prioridad_defecto`` y ``grilla_operativa``). Permite volver a llamar a
        ``TallerCilindros.simular()`` sobre la misma instancia sin que el
        historial y ``tiempo_total_ocupada_min`` se acumulen entre corridas
        (lo que inflaría la utilización y el Gantt).
        """
        self.ocupada = False
        self.cilindro_actual = None
        self.tiempo_fin_rectificado = None
        self.historial_trabajo = []
        self.tiempo_total_ocupada_min = 0.0
        self.minutos_trabajo_actual = 0.0
        self._despertar_programado = False
        self._inicio_rectificado = None
        self._hitos_t = None
        self._hitos_min = None

    def configurar_tasa(self, tipo: str, mm_removidos: float, tiempo_minutos: float) -> None:
        """Registra la velocidad de rectificado para un tipo de pase."""
        tasa = mm_removidos / tiempo_minutos if tiempo_minutos > 0 else 0.0
        self.tasas_rectificado[tipo] = {
            "mm": mm_removidos,
            "t_min": tiempo_minutos,
            "rate": tasa
        }

    def puede_rectificar(self, tipo: str) -> bool:
        """True si la máquina tiene una tasa útil (rate > 0) para ese tipo de pase.

        Es el predicado que respalda el centinela ``inf`` de
        :meth:`calcular_tiempo_proceso`: la asignación lo usa para no entregarle
        a una máquina un trabajo cuyo tipo no puede ejecutar.
        """
        cfg = self.tasas_rectificado.get(tipo)
        return cfg is not None and cfg["rate"] > 0

    def calcular_tiempo_proceso(self, mm_a_rectificar: float, tipo: str) -> float:
        """
        Calcula cuántos minutos tomará rectificar la cantidad indicada.

        Devuelve float('inf') si el tipo no está configurado o su tasa es 0,
        lo que excluirá este trabajo de la asignación.
        """
        if not self.puede_rectificar(tipo):
            return float("inf")
        return mm_a_rectificar / self.tasas_rectificado[tipo]["rate"]

    # ── Esquema de trabajo (turnos) ─────────────────────────────────────────

    def esta_operativa(self, dt: datetime) -> bool:
        """Indica si la máquina está en un turno operativo en el instante dado."""
        if self.grilla_operativa is None:
            return True
        return self.grilla_operativa[dt.weekday()][dt.hour]

    def _minutos_si(self, t0: datetime, t1: datetime,
                    cond: "Callable[[datetime], bool]") -> float:
        """Minutos en ``[t0, t1)`` cuyas horas cumplen ``cond(t)`` (resolución horaria).

        Recorre por fronteras horarias acumulando la fracción de cada hora que
        cae en el intervalo. Base compartida por ``minutos_operativos_entre`` y
        ``minutos_falla_entre`` (solo cambia el predicado por hora).
        """
        total = 0.0
        t = t0
        while t < t1:
            fin_hora = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            tramo_fin = min(fin_hora, t1)
            if cond(t):
                total += (tramo_fin - t).total_seconds() / 60.0
            t = tramo_fin
        return total

    def minutos_operativos_entre(self, t0: datetime, t1: datetime) -> float:
        """Minutos de tiempo operativo acumulados en el intervalo [t0, t1).

        Con grilla None (24/7) devuelve los minutos de reloj, idéntico al
        comportamiento histórico.
        """
        if t1 <= t0:
            return 0.0
        if self.grilla_operativa is None:
            return (t1 - t0).total_seconds() / 60.0
        return self._minutos_si(t0, t1, lambda t: self.grilla_operativa[t.weekday()][t.hour])

    # ── Tasa de falla (capa de disponibilidad sobre los turnos) ──────────────

    def _tiene_fallas(self) -> bool:
        """True si esta corrida modela fallas (tasa > 0 y seed fijada)."""
        return self.tasa_falla > 0 and self._seed_fallas is not None

    def _base_fallas(self) -> int:
        """Semilla base entera derivada de ``(seed, nombre)`` (sha256, cacheada).

        Se calcula una sola vez por máquina/seed (no por hora): el sha256 de la
        cadena estable ``"{seed}|{nombre}"`` da un entero reproducible entre
        procesos (no usa ``hash()``, que está salteado por proceso).
        """
        cache = self._base_fallas_cache
        if cache is None or cache[0] != self._seed_fallas:
            h = hashlib.sha256(f"{self._seed_fallas}|{self.nombre}".encode("utf-8")).digest()
            base = int.from_bytes(h[:8], "big")
            self._base_fallas_cache = (self._seed_fallas, base)
            return base
        return cache[1]

    def en_falla(self, dt: datetime) -> bool:
        """True si la máquina está caída por falla en la hora de ``dt``.

        Realización **determinista y stateless**: cada hora absoluta se sortea a
        ``[0,1)`` y se compara contra ``tasa_falla``. Así ~``tasa_falla`` de las
        horas quedan en falla, de forma reproducible (misma seed ⇒ mismo patrón),
        sin estado ni orden de consulta, e independiente de los desplazamientos
        por PARADA (la falla es un proceso de reloj exógeno, como los turnos). El
        sorteo es barato: una mezcla ``splitmix64`` del índice horario absoluto
        combinada con la semilla base (sha256 una vez por máquina/seed, no por
        hora). Con ``tasa_falla == 0`` o sin seed devuelve ``False`` siempre.
        """
        if not self._tiene_fallas():
            return False
        td = dt - _EPOCH_FALLAS
        hora_abs = td.days * 24 + td.seconds // 3600
        mezcla = _splitmix64(self._base_fallas() ^ _splitmix64(hora_abs & _MASK64))
        return (mezcla / _DOS64) < self.tasa_falla

    def disponible_para_trabajo(self, dt: datetime) -> bool:
        """True si la máquina puede rectificar en ``dt``: en turno **y** sin falla.

        Es el predicado que reemplaza a ``esta_operativa`` en toda la maquinaria
        de pausa/reanudación: una hora no trabajable (fuera de turno o en falla)
        no consume trabajo y se saltea, de modo que el cilindro queda montado y
        retoma al volver a estar trabajable. Sin fallas equivale a ``esta_operativa``.
        """
        return self.esta_operativa(dt) and not self.en_falla(dt)

    def minutos_falla_entre(self, t0: datetime, t1: datetime) -> float:
        """Minutos de tiempo **operativo** (en turno) perdidos por falla en [t0, t1).

        Solo cuenta horas que están en turno y además en falla (la falla es 'del
        tiempo disponible'). Alimenta el KPI explícito de fallas. Devuelve 0.0 si
        no hay fallas en esta corrida.
        """
        if t1 <= t0 or not self._tiene_fallas():
            return 0.0
        return self._minutos_si(t0, t1, lambda t: self.esta_operativa(t) and self.en_falla(t))

    def _construir_hitos_progreso(
        self, inicio: datetime, total_min: float
    ) -> Tuple[List[datetime], List[float]]:
        """Tabla de hitos (frontera_horaria, minutos_operativos_acumulados).

        Recorre ``inicio → fin`` hora por hora consumiendo solo las horas
        operativas, devolviendo dos listas paralelas: las fronteras horarias y
        los minutos operativos acumulados *hasta* cada frontera. La primera
        entrada es ``(inicio, 0.0)`` y la última ``(fin, total_min)``, donde
        ``fin`` es el instante de reloj en que se completan ``total_min`` de
        tiempo operativo. Cada segmento ``[hitos_t[i], hitos_t[i+1])`` cae
        íntegro dentro de una hora de grilla, así su operatividad es constante.
        Es la única fuente del fin operativo (ver ``calcular_fin_operativo``).
        Solo tiene sentido cuando hay turnos o fallas (ver ``calcular_fin_operativo``)
        y ``total_min > 0``. Las horas no trabajables (fuera de turno **o** en
        falla) se saltean: el cilindro queda montado y retoma al volver.
        """
        hitos_t: List[datetime] = [inicio]
        hitos_min: List[float] = [0.0]
        restante = total_min
        acum = 0.0
        t = inicio
        limite = inicio + timedelta(days=366)  # cota de seguridad anti-bucle
        while restante > 0 and t < limite:
            fin_hora = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            if self.disponible_para_trabajo(t):
                disp = (fin_hora - t).total_seconds() / 60.0
                if disp >= restante:
                    acum += restante
                    hitos_t.append(t + timedelta(minutes=restante))
                    hitos_min.append(acum)
                    return hitos_t, hitos_min
                acum += disp
                restante -= disp
            hitos_t.append(fin_hora)
            hitos_min.append(acum)
            t = fin_hora
        return hitos_t, hitos_min

    def calcular_fin_operativo(self, inicio: datetime, minutos_op: float) -> datetime:
        """Instante de reloj en que se completan ``minutos_op`` de tiempo operativo.

        Avanza desde ``inicio`` consumiendo solo las horas operativas y saltando
        los huecos no operativos (el cilindro queda montado y retoma donde quedó).
        Con grilla None y sin fallas devuelve ``inicio + minutos_op``
        (comportamiento histórico). Se asume que la máquina está disponible en
        ``inicio`` (solo se asigna trabajo en ese caso), por lo que siempre progresa.
        """
        if (self.grilla_operativa is None and not self._tiene_fallas()) or minutos_op <= 0:
            return inicio + timedelta(minutes=minutos_op)
        return self._construir_hitos_progreso(inicio, minutos_op)[0][-1]

    def progreso_operativo(self, tiempo: datetime) -> float:
        """Minutos operativos consumidos del rectificado en curso hasta ``tiempo``.

        O(1) sin trabajo o con grilla 24/7 (reloj directo); O(log h) con turnos,
        resolviendo por bisect sobre los hitos precalculados en iniciar_rectificado.
        """
        if self._inicio_rectificado is None:
            return 0.0
        # Sin hitos precalculados (grilla 24/7 y sin fallas) el progreso es reloj
        # directo; si se construyeron hitos (por turnos y/o fallas) se resuelven.
        if self._hitos_t is None:
            return max(0.0, (tiempo - self._inicio_rectificado).total_seconds() / 60.0)

        idx = bisect_right(self._hitos_t, tiempo) - 1
        if idx < 0:
            return 0.0
        consumido = self._hitos_min[idx]
        base = self._hitos_t[idx]
        if tiempo > base and self.disponible_para_trabajo(base):
            consumido += (tiempo - base).total_seconds() / 60.0
        return min(consumido, self._hitos_min[-1])

    def _nunca_trabajable(self) -> bool:
        """True si la máquina no puede estar trabajable en NINGÚN instante.

        Dos causas estructurales: (a) ningún turno operativo en la grilla semanal,
        o (b) tasa de falla 1.0 (toda hora cae en falla). En cualquiera de los dos
        casos no tiene sentido buscar la próxima apertura: nunca llega.
        """
        if self.grilla_operativa is not None and not any(
                any(fila) for fila in self.grilla_operativa):
            return True
        return self._tiene_fallas() and self.tasa_falla >= 1.0

    def proxima_apertura(self, desde: datetime) -> Optional[datetime]:
        """Próximo instante **trabajable** desde ``desde`` (turno y sin falla).

        None si nunca vuelve a estar trabajable. Sin turnos ni fallas devuelve
        ``desde`` (siempre trabajable). Cubre tanto la reapertura de turno como el
        fin de una falla.

        Los casos "nunca trabajable" (grilla sin turnos o ``tasa_falla == 1``) se
        detectan de forma **estructural** y devuelven ``None`` de inmediato; en el
        caso normal se busca hora por hora hasta un horizonte amplio (366 días, no
        una semana) para no perder la reapertura en barridos largos donde una falla
        densa puede estirar el hueco más allá del ciclo semanal de turnos.
        """
        if self.disponible_para_trabajo(desde):
            return desde
        if self._nunca_trabajable():
            return None
        t = desde.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        # Cota de seguridad amplia: ya descartamos el caso "nunca trabajable", así
        # que el corte solo actúa ante combinaciones degeneradas (turnos muy ralos
        # + tasa_falla casi 1) que no se dan en un barrido realista.
        limite = desde + timedelta(days=366)
        while t < limite:
            if self.disponible_para_trabajo(t):
                return t
            t += timedelta(hours=1)
        return None

    def iniciar_rectificado(
        self,
        cilindro: Cilindro,
        tiempo_actual: datetime,
        tipo: TipoRectificado,
        mm: float,
        perfil: Optional[str] = None
    ) -> None:
        """Inicia el proceso de rectificado para un cilindro.

        ``perfil`` es el perfil (bombatura) a tallar, decidido por el motor (la
        máquina sólo lo aplica físicamente). ``None`` ⇒ no cambia el perfil.
        """
        duracion_minutos = self.calcular_tiempo_proceso(mm, tipo.value)
        self.ocupada = True
        self.cilindro_actual = cilindro
        self.minutos_trabajo_actual = duracion_minutos
        self._inicio_rectificado = tiempo_actual
        # El fin contempla los huecos no trabajables (turno cerrado y/o falla): si
        # la máquina para en medio del trabajo, el cilindro retoma donde quedó al
        # reabrir. Con turnos y/o fallas se precalculan los hitos una sola vez
        # (fuente única del fin); con grilla 24/7 y sin fallas el fin es la suma
        # directa y el progreso es reloj directo.
        if (self.grilla_operativa is None and not self._tiene_fallas()) or duracion_minutos <= 0:
            self._hitos_t = None
            self._hitos_min = None
            self.tiempo_fin_rectificado = tiempo_actual + timedelta(minutes=duracion_minutos)
        else:
            self._hitos_t, self._hitos_min = self._construir_hitos_progreso(
                tiempo_actual, duracion_minutos)
            self.tiempo_fin_rectificado = self._hitos_t[-1]

        cilindro.estado = EstadoCilindro.RECTIFICANDO
        cilindro.maquina_actual = self.nombre
        cilindro.rectificado_inicio = tiempo_actual
        cilindro.rectificado_fin = self.tiempo_fin_rectificado
        cilindro.tipo_rectificado_actual = tipo
        cilindro.mm_a_rectificar = mm
        if perfil is not None:
            cilindro.perfil = perfil  # la máquina talla físicamente el perfil decidido

        cilindro.registrar_evento(
            tiempo_actual,
            f"Inicio rectificado {tipo.value} en {self.nombre}",
            f"D{cilindro.diametro}->{round(cilindro.diametro - mm, 2)} ({duracion_minutos:.0f} min)"
        )

        self.historial_trabajo.append({
            "cilindro_id": cilindro.id,
            "inicio": tiempo_actual,
            "fin": self.tiempo_fin_rectificado,
            "tipo": tipo.value,
            "mm": mm,
            "duracion": duracion_minutos
        })
        self.tiempo_total_ocupada_min += duracion_minutos

    def finalizar_rectificado(self, tiempo_actual: datetime) -> Optional[Cilindro]:
        """Finaliza el proceso actual, actualiza el cilindro y libera la máquina."""
        if not self.ocupada or not self.cilindro_actual:
            return None

        cilindro = self.cilindro_actual
        cilindro.rectificar(cilindro.mm_a_rectificar)
        cilindro.estado = EstadoCilindro.DISPONIBLE
        cilindro.maquina_actual = None

        # El rectificado ya fue aplicado arriba; se limpia el tipo/mm pendientes
        # para que el cilindro DISPONIBLE no arrastre datos del pase previo. El
        # próximo CAMBIO los reasigna antes de que vuelva a rectificarse, así que
        # esto no altera ninguna lógica (es solo higiene de estado).
        cilindro.tipo_rectificado_actual = None
        cilindro.mm_a_rectificar = 0.0

        cilindro.registrar_evento(
            tiempo_actual,
            f"Fin rectificado en {self.nombre}",
            f"Nuevo diámetro: {cilindro.diametro} mm"
        )

        self.ocupada = False
        self.cilindro_actual = None
        self.tiempo_fin_rectificado = None
        self._inicio_rectificado = None
        self._hitos_t = None
        self._hitos_min = None

        return cilindro
