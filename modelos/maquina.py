"""
Modelo de una máquina rectificadora de cilindros.
"""
from bisect import bisect_right
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro


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

    def configurar_tasa(self, tipo: str, mm_removidos: float, tiempo_minutos: float) -> None:
        """Registra la velocidad de rectificado para un tipo de pase."""
        tasa = mm_removidos / tiempo_minutos if tiempo_minutos > 0 else 0.0
        self.tasas_rectificado[tipo] = {
            "mm": mm_removidos,
            "t_min": tiempo_minutos,
            "rate": tasa
        }

    def calcular_tiempo_proceso(self, mm_a_rectificar: float, tipo: str) -> float:
        """
        Calcula cuántos minutos tomará rectificar la cantidad indicada.

        Devuelve float('inf') si el tipo no está configurado o su tasa es 0,
        lo que excluirá este trabajo de la asignación.
        """
        cfg = self.tasas_rectificado.get(tipo)
        if cfg is None or cfg["rate"] <= 0:
            return float("inf")
        return mm_a_rectificar / cfg["rate"]

    # ── Esquema de trabajo (turnos) ─────────────────────────────────────────

    def esta_operativa(self, dt: datetime) -> bool:
        """Indica si la máquina está en un turno operativo en el instante dado."""
        if self.grilla_operativa is None:
            return True
        return self.grilla_operativa[dt.weekday()][dt.hour]

    def minutos_operativos_entre(self, t0: datetime, t1: datetime) -> float:
        """Minutos de tiempo operativo acumulados en el intervalo [t0, t1).

        Con grilla None (24/7) devuelve los minutos de reloj, idéntico al
        comportamiento histórico.
        """
        if t1 <= t0:
            return 0.0
        if self.grilla_operativa is None:
            return (t1 - t0).total_seconds() / 60.0

        total = 0.0
        t = t0
        while t < t1:
            fin_hora = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            tramo_fin = min(fin_hora, t1)
            if self.grilla_operativa[t.weekday()][t.hour]:
                total += (tramo_fin - t).total_seconds() / 60.0
            t = tramo_fin
        return total

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
        Solo tiene sentido con ``grilla_operativa is not None`` y ``total_min > 0``.
        """
        hitos_t: List[datetime] = [inicio]
        hitos_min: List[float] = [0.0]
        restante = total_min
        acum = 0.0
        t = inicio
        limite = inicio + timedelta(days=366)  # cota de seguridad anti-bucle
        while restante > 0 and t < limite:
            fin_hora = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            if self.grilla_operativa[t.weekday()][t.hour]:
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
        Con grilla None devuelve ``inicio + minutos_op`` (comportamiento histórico).
        Se asume que la máquina está operativa en ``inicio`` (solo se asigna
        trabajo en ese caso), por lo que siempre progresa.
        """
        if self.grilla_operativa is None or minutos_op <= 0:
            return inicio + timedelta(minutes=minutos_op)
        return self._construir_hitos_progreso(inicio, minutos_op)[0][-1]

    def progreso_operativo(self, tiempo: datetime) -> float:
        """Minutos operativos consumidos del rectificado en curso hasta ``tiempo``.

        O(1) sin trabajo o con grilla 24/7 (reloj directo); O(log h) con turnos,
        resolviendo por bisect sobre los hitos precalculados en iniciar_rectificado.
        """
        if self._inicio_rectificado is None:
            return 0.0
        if self.grilla_operativa is None or self._hitos_t is None:
            return max(0.0, (tiempo - self._inicio_rectificado).total_seconds() / 60.0)

        idx = bisect_right(self._hitos_t, tiempo) - 1
        if idx < 0:
            return 0.0
        consumido = self._hitos_min[idx]
        base = self._hitos_t[idx]
        if tiempo > base and self.grilla_operativa[base.weekday()][base.hour]:
            consumido += (tiempo - base).total_seconds() / 60.0
        return min(consumido, self._hitos_min[-1])

    def proxima_apertura(self, desde: datetime) -> Optional[datetime]:
        """Próximo instante operativo a partir de ``desde`` (None si nunca lo está)."""
        if self.grilla_operativa is None or self.esta_operativa(desde):
            return desde
        t = desde.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        limite = desde + timedelta(days=8)  # una semana basta para cubrir el ciclo
        while t < limite:
            if self.grilla_operativa[t.weekday()][t.hour]:
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
        # El fin contempla los turnos no operativos: si la máquina para en medio
        # del trabajo, el cilindro retoma donde quedó al reabrir el turno. Con
        # turnos se precalculan los hitos una sola vez (fuente única del fin); con
        # grilla 24/7 el fin es la suma directa y el progreso es reloj directo.
        if self.grilla_operativa is None or duracion_minutos <= 0:
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
