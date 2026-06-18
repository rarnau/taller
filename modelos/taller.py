"""
Motor de simulación del taller de cilindros.
Coordina cilindros, máquinas, jaulas y eventos de cambio.
"""
import heapq
import itertools
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any, NamedTuple, Tuple
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro
from .substock import SubStock
from .maquina import MaquinaRectificadora
from .jaula import Jaula
from .eventos import EventoCambio, Alerta, Snapshot
from .estrategias import ESTRATEGIAS_SELECCION, ESTRATEGIA_DEFECTO
from . import turnos as turnos_mod

logger = logging.getLogger(__name__)

# ── Constantes de simulación ────────────────────────────────────────────────
_MM_RECTIFICAR_DEFECTO: float = 0.8
_TIPO_RECTIFICADO_DEFECTO: str = "produccion"
_BUFFER_CRC_SIZE: int = 2
_MAX_ITERACIONES_SIM: int = 10_000
_MAX_ITER_FINALIZACION: int = 500

# Nombres de hojas Excel
_HOJA_CONFIG = "Configuración"
_HOJA_MAQUINAS = "Máquinas"
_HOJA_STOCK = "Stock_Inicial"
_HOJA_CAMBIOS = "Programa_Cambios"


class _EventoSim(NamedTuple):
    """Evento interno tipado para la cola de simulación."""
    tipo: str       # "CAMBIO" | "FIN_RECT" | "REPONER_CRC" | "FIN_ENFRIADO"
    tiempo: datetime
    datos: Any      # EventoCambio (CAMBIO) | str máquina (FIN_RECT) | int jaula (REPONER_CRC) | str id cilindro (FIN_ENFRIADO)


# Item de la cola de prioridad (heap): (tiempo, secuencia, evento). El contador
# de secuencia rompe los empates de tiempo en orden FIFO de inserción y evita
# comparar los _EventoSim entre sí.
_ItemCola = Tuple[datetime, int, _EventoSim]


class TallerCilindros:
    """
    Clase principal que gestiona la lógica de la simulación.

    Responsabilidades:
      - Carga de datos desde Excel (cargar_datos)
      - Consultas de estado (obtener_*, seleccionar_*)
      - Generación de snapshots para la GUI
      - Ejecución de la simulación (simular)
      - Exportación de resultados
    """

    # Derivado del enum (en su orden de definición) para no duplicar la lista de
    # estados: al agregar un estado a EstadoCilindro, los gráficos lo recogen solos.
    ESTADOS_NOMBRES = [e.value for e in EstadoCilindro]

    def __init__(self):
        self.cilindros: Dict[str, Cilindro] = {}
        self.lista_substocks: List[SubStock] = []
        self.maquinas: Dict[str, MaquinaRectificadora] = {}
        self.jaulas: Dict[int, Jaula] = {}
        self.eventos_programados: List[EventoCambio] = []
        self.alertas: List[Alerta] = []
        self.snapshots: List[Snapshot] = []
        self.avisos_carga: List[str] = []  # avisos surgidos al cargar datos (para la GUI)

        # Parámetros de configuración (sobreescritos al cargar Excel)
        self.diametro_maximo: float = 575.0
        self.diametro_minimo: float = 520.0
        self.tiempo_traslado_crc_min: float = 10.0
        self.cantidad_jaulas: int = 4
        self.estrategia_seleccion: str = "mayor_diametro"

        # Tiempo de enfriado (horas) entre Trabajando y A rectificar. 0.0 = sin
        # estado de enfriado (comportamiento histórico). Máximo de iteraciones
        # del bucle de simulación (tope de seguridad configurable).
        self.tiempo_enfriado_h: float = 0.0
        self.max_iteraciones: int = _MAX_ITERACIONES_SIM

        # Recurso único de traslado Disponible→CRC (grúa/operario).
        # Las reposiciones se serializan: solo se mueve una pareja a la vez.
        self._recurso_crc_libre_en: Optional[datetime] = None
        self._reposicion_pendiente: set = set()

        # Parada de línea: cuando alguna jaula se detiene, la línea entera se
        # frena. Mientras dure, los CAMBIO posteriores se difieren; al reanudar,
        # todo el programa de cambios restante se desplaza por la duración total.
        self._linea_parada_desde: Optional[datetime] = None
        self._cambios_diferidos: List["_EventoSim"] = []

        # Contador de secuencia de la cola de eventos (heap). Se reinicia al
        # inicio de cada simulación; declarado aquí para que _push_evento no
        # dependa de un atributo que solo existe a mitad de corrida.
        self._seq_cola = itertools.count()

    # ── Configuración externa ───────────────────────────────────────────────

    def configurar_substocks(self, rangos_config: List[Dict[str, Any]]) -> None:
        """Define los rangos de diámetros para cada jaula."""
        self.lista_substocks.clear()
        for r in rangos_config:
            jaula = int(r["jaula"])
            desde = float(r["desde"])
            hasta = float(r["hasta"])
            nombre = f"SS{jaula} ({hasta:.0f}-{desde:.0f})"
            self.lista_substocks.append(SubStock(nombre, jaula, desde, hasta, jaula_asignada=jaula))

    def aplicar_prioridades_maquinas(self, prioridades: Dict[str, str]) -> None:
        """Asigna el tipo de rectificado prioritario a cada máquina."""
        for nombre, tipo in prioridades.items():
            if nombre in self.maquinas:
                try:
                    self.maquinas[nombre].prioridad_defecto = TipoRectificado(tipo)
                except ValueError:
                    logger.warning("Tipo de prioridad inválido '%s' para máquina '%s', ignorado.", tipo, nombre)

    def configurar(self, cfg: Dict[str, Any]) -> None:
        """Aplica la configuración estructural persistente (el JSON de usuario).

        Punto único de configuración del taller. DEBE llamarse **antes** de
        ``cargar_datos()``: el stock necesita ``cantidad_jaulas`` y
        ``diametro_minimo`` para inicializarse, y el programa de cambios valida
        contra las jaulas ya creadas.

        Acepta el dict completo de ``config/persistencia.py`` (claves
        ``config_global``, ``maquinas``, ``rangos``, ``tiempo_enfriado_h`` y
        ``max_iteraciones``); las que falten se ignoran sin error.
        """
        cg = cfg.get("config_global", {})
        if "diametro_maximo" in cg:
            self.diametro_maximo = float(cg["diametro_maximo"])
        if "diametro_minimo" in cg:
            self.diametro_minimo = float(cg["diametro_minimo"])
        if "tiempo_traslado_crc_min" in cg:
            self.tiempo_traslado_crc_min = float(cg["tiempo_traslado_crc_min"])
        if "cantidad_jaulas" in cg:
            self.cantidad_jaulas = int(cg["cantidad_jaulas"])

        if "maquinas" in cfg:
            self.configurar_maquinas(cfg["maquinas"])
        if "rangos" in cfg:
            self.configurar_substocks(cfg["rangos"])
        if "tiempo_enfriado_h" in cfg:
            self.tiempo_enfriado_h = float(cfg["tiempo_enfriado_h"])
        if "max_iteraciones" in cfg:
            self.max_iteraciones = int(cfg["max_iteraciones"])

    def configurar_maquinas(self, maquinas_config: List[Dict[str, Any]]) -> None:
        """Reconstruye el parque de máquinas desde la configuración persistente.

        Cada entrada: ``{"nombre", "prioridad", "tasas": {tipo: {"mm", "tiempo_min"}}}``.
        """
        self.maquinas.clear()
        for m in maquinas_config:
            nombre = str(m["nombre"])
            maq = MaquinaRectificadora(nombre)
            for tipo_str, tasa in (m.get("tasas") or {}).items():
                try:
                    TipoRectificado(tipo_str)
                except ValueError:
                    logger.warning("Tipo de rectificado inválido '%s' para máquina '%s', ignorado.", tipo_str, nombre)
                    continue
                maq.configurar_tasa(tipo_str, float(tasa["mm"]), float(tasa["tiempo_min"]))
            prioridad = m.get("prioridad")
            if prioridad:
                try:
                    maq.prioridad_defecto = TipoRectificado(prioridad)
                except ValueError:
                    logger.warning("Prioridad inválida '%s' para máquina '%s', ignorada.", prioridad, nombre)
            # Esquema de trabajo (turnos): si está configurado, se expande a la
            # grilla horaria 7×24; si no, queda None (siempre operativa, 24/7).
            esquema = m.get("turnos")
            maq.grilla_operativa = turnos_mod.expandir(esquema) if esquema else None
            self.maquinas[nombre] = maq

    # ── Carga de datos desde Excel ──────────────────────────────────────────

    def cargar_datos(self, ruta_excel: str) -> None:
        """Carga el inventario inicial y el programa de cambios desde un Excel.

        El Excel solo contiene **datos variables**: las hojas ``Stock_Inicial``
        y ``Programa_Cambios``. La configuración estructural (parámetros
        globales, máquinas y rangos) vive en el JSON de usuario y debe aplicarse
        antes con :meth:`configurar`. Si el archivo trae las hojas viejas
        ``Configuración``/``Máquinas`` se ignoran (con un aviso).
        """
        try:
            xl = pd.ExcelFile(ruta_excel, engine="openpyxl")
        except Exception as exc:
            raise IOError(f"No se pudo abrir el archivo Excel '{ruta_excel}': {exc}") from exc

        hojas_requeridas = [_HOJA_STOCK, _HOJA_CAMBIOS]
        faltantes = [h for h in hojas_requeridas if h not in xl.sheet_names]
        if faltantes:
            raise ValueError(f"Hojas faltantes en el Excel: {faltantes}")

        ignoradas = [h for h in (_HOJA_CONFIG, _HOJA_MAQUINAS) if h in xl.sheet_names]

        self.cargar_datos_desde_dataframes(xl.parse(_HOJA_STOCK), xl.parse(_HOJA_CAMBIOS))

        if ignoradas:
            msg = (
                f"AVISO: el Excel trae hojas de configuración antiguas {ignoradas} que se "
                f"ignoran. La configuración del taller se gestiona desde la pantalla "
                f"Configuración o el CLI (config import-excel para volcarlas al JSON)."
            )
            logger.warning(msg)
            self.avisos_carga.append(msg)

    def cargar_datos_desde_dataframes(self, stock_df: pd.DataFrame,
                                      cambios_df: pd.DataFrame) -> None:
        """Carga stock y cambios desde DataFrames ya en memoria.

        Separar esta lógica de la lectura del ``.xlsx`` permite que un futuro
        runner de lotes ejecute miles de simulaciones independientes pasando los
        DataFrames directamente, sin I/O de disco por corrida. Requiere que
        :meth:`configurar` ya se haya aplicado (máquinas, rangos y globales).
        """
        # Solo se limpian los datos por-corrida; NO las máquinas, los substocks
        # ni los parámetros globales, que los fija configurar() previamente.
        self.cilindros.clear()
        self.jaulas.clear()
        self.eventos_programados.clear()
        self.alertas.clear()
        self.snapshots.clear()
        self.avisos_carga.clear()

        self._cargar_stock(stock_df)
        self._cargar_cambios(cambios_df)

        # Fallback: si nadie configuró substocks, se derivan rangos iguales a
        # partir del rango global y la cantidad de jaulas, para que el motor
        # funcione aun sin configurar() (tests, scripts, verificaciones).
        if not self.lista_substocks:
            self._derivar_substocks_por_defecto()

    def _derivar_substocks_por_defecto(self) -> None:
        """
        Divide el rango global (diametro_minimo, diametro_maximo] en N bandas
        iguales, una por jaula. Se invoca automáticamente desde cargar_datos()
        si lista_substocks está vacía, garantizando que el motor funcione
        correctamente sin necesidad de llamar configurar_substocks() primero.
        """
        n = self.cantidad_jaulas
        paso = (self.diametro_maximo - self.diametro_minimo) / n
        for i in range(n):
            jaula = i + 1
            hasta = self.diametro_minimo + i * paso
            desde = hasta + paso
            nombre = f"SS{jaula} ({hasta:.0f}-{desde:.0f})"
            self.lista_substocks.append(
                SubStock(nombre, jaula, desde, hasta, jaula_asignada=jaula)
            )
        logger.info(
            "SubStocks derivados automáticamente (%d bandas de %.2f mm cada una).",
            n, paso
        )

    def _cargar_stock(self, df: pd.DataFrame) -> None:
        """Carga el stock inicial de cilindros e inicializa las jaulas."""
        for idx, row in df.iterrows():
            try:
                estado = EstadoCilindro(row["Estado"])
            except ValueError as exc:
                raise ValueError(
                    f"Estado inválido '{row['Estado']}' en hoja Stock_Inicial, fila {idx}"
                ) from exc

            jaula_id = int(row["Jaula_Asignada"]) if pd.notna(row.get("Jaula_Asignada")) else None
            pos = int(row["Posición"]) if pd.notna(row.get("Posición")) else None
            cil = Cilindro(str(row["ID_Cilindro"]), float(row["Diámetro_mm"]), estado, jaula_id, pos)

            if estado in (EstadoCilindro.A_RECTIFICAR, EstadoCilindro.RECTIFICANDO):
                mm_col = row.get("mm_a_Rectificar")
                cil.mm_a_rectificar = float(mm_col) if pd.notna(mm_col) else _MM_RECTIFICAR_DEFECTO
                tipo_col = row.get("Tipo_Rectificado")
                tipo_str = str(tipo_col) if pd.notna(tipo_col) else _TIPO_RECTIFICADO_DEFECTO
                try:
                    cil.tipo_rectificado_actual = TipoRectificado(tipo_str)
                except ValueError as exc:
                    raise ValueError(
                        f"Tipo rectificado inválido '{tipo_str}' en hoja Stock_Inicial, fila {idx}"
                    ) from exc
                if estado == EstadoCilindro.RECTIFICANDO:
                    cil.estado = EstadoCilindro.A_RECTIFICAR

            self.cilindros[cil.id] = cil

        # Cilindros que ya vienen por debajo del mínimo utilizable -> BAJA.
        # (Durante la simulación esto no puede ocurrir; solo desde datos iniciales.)
        for cil in self.cilindros.values():
            if cil.estado != EstadoCilindro.BAJA and cil.diametro < self.diametro_minimo:
                logger.warning(
                    "Cilindro %s con diámetro %.2f < mínimo %.2f: marcado BAJA al cargar.",
                    cil.id, cil.diametro, self.diametro_minimo
                )
                cil.estado = EstadoCilindro.BAJA
                cil.jaula = None

        # Aviso: cilindros que vienen marcados BAJA pese a estar sobre el mínimo.
        # No se modifica su estado (el dato del Excel es la fuente de verdad);
        # solo se registra para revisión manual, ya que podrían estar fuera de
        # servicio por motivos ajenos al diámetro (fisuras, defectos, etc.).
        bajas_sobre_minimo = [
            cil for cil in self.cilindros.values()
            if cil.estado == EstadoCilindro.BAJA and cil.diametro >= self.diametro_minimo
        ]
        if bajas_sobre_minimo:
            ids = ", ".join(f"{c.id} ({c.diametro:.2f})" for c in bajas_sobre_minimo)
            msg = (
                f"AVISO: {len(bajas_sobre_minimo)} cilindro(s) vienen marcados BAJA en los datos "
                f"pese a estar sobre el mínimo ({self.diametro_minimo:.2f}): {ids}"
            )
            logger.warning(msg)
            self.avisos_carga.append(msg)

        # Inicializar jaulas y ubicar cilindros
        for j_id in range(1, self.cantidad_jaulas + 1):
            self.jaulas[j_id] = Jaula(j_id)

        for cil in self.cilindros.values():
            if cil.estado == EstadoCilindro.TRABAJANDO and cil.jaula:
                if cil.jaula in self.jaulas:
                    self.jaulas[cil.jaula].cilindros_trabajando.append(cil)
                else:
                    logger.warning("Cilindro %s asignado a jaula inexistente %s.", cil.id, cil.jaula)
            elif cil.estado == EstadoCilindro.CRC and cil.jaula:
                if cil.jaula in self.jaulas:
                    self.jaulas[cil.jaula].cilindros_crc.append(cil)

        self._garantizar_parejas_iniciales()

    def _cargar_cambios(self, df: pd.DataFrame) -> None:
        """Carga el programa de cambios de cilindros."""
        for idx, row in df.iterrows():
            tipo_str = str(row["Tipo_Rectificado"])
            try:
                tipo = TipoRectificado(tipo_str)
            except ValueError as exc:
                raise ValueError(
                    f"Tipo rectificado inválido '{tipo_str}' en hoja Programa_Cambios, fila {idx}"
                ) from exc

            jaula_val = int(row["Jaula"])
            if jaula_val not in self.jaulas:
                raise ValueError(
                    f"Jaula {jaula_val} en Programa_Cambios fila {idx} fuera de rango "
                    f"(1-{self.cantidad_jaulas})"
                )

            evento = EventoCambio(
                id_evento=str(row["ID_Cambio"]),
                tiempo=pd.to_datetime(row["Fecha_Hora"]),
                jaula=jaula_val,
                tipo=tipo,
                mm_a_rectificar=float(row["mm_a_Rectificar"]),
                observacion=str(row.get("Observación", ""))
            )
            self.eventos_programados.append(evento)

        self.eventos_programados.sort(key=lambda e: e.tiempo)

    # ── Helpers internos ────────────────────────────────────────────────────

    def _garantizar_parejas_iniciales(self) -> None:
        """Asegura que cada jaula tenga sus cilindros trabajando al inicio si hay stock."""
        for j_id, jaula in self.jaulas.items():
            while len(jaula.cilindros_trabajando) < _BUFFER_CRC_SIZE:
                if jaula.cilindros_crc:
                    cil = jaula.cilindros_crc.pop(0)
                    cil.estado = EstadoCilindro.TRABAJANDO
                    cil.jaula = j_id
                    jaula.cilindros_trabajando.append(cil)
                    continue
                disponibles = sorted(
                    self.obtener_disponibles_para_jaula(j_id), key=lambda c: c.diametro, reverse=True
                )
                if disponibles:
                    cil = disponibles[0]
                    cil.estado = EstadoCilindro.TRABAJANDO
                    cil.jaula = j_id
                    jaula.cilindros_trabajando.append(cil)
                    continue
                break

            # Una jaula no puede arrancar con menos de una pareja completa.
            if len(jaula.cilindros_trabajando) < _BUFFER_CRC_SIZE:
                jaula.parada = True
                logger.warning(
                    "Jaula %s arranca PARADA: solo %d cilindro(s) en su rango de diámetros.",
                    j_id, len(jaula.cilindros_trabajando)
                )

    def _instalar_en_jaula(self, cil: Cilindro, jaula_id: int, tiempo: datetime, motivo: str) -> None:
        """Mueve un cilindro al estado TRABAJANDO en la jaula indicada."""
        jaula = self.jaulas[jaula_id]
        cil.estado = EstadoCilindro.TRABAJANDO
        cil.jaula = jaula_id
        if cil in jaula.cilindros_crc:
            jaula.cilindros_crc.remove(cil)
        jaula.cilindros_trabajando.append(cil)
        cil.registrar_evento(tiempo, motivo)

    def _instalar_pareja_o_parar(self, jaula_id: int, tiempo: datetime) -> bool:
        """
        Completa la pareja de trabajo de una jaula (CRC primero, luego disponibles
        del rango). Una jaula no puede operar con menos de _BUFFER_CRC_SIZE
        cilindros: si no hay stock suficiente para completarla, NO instala ninguno
        y devuelve False (la jaula debe quedar PARADA).
        """
        jaula = self.jaulas[jaula_id]
        faltan = _BUFFER_CRC_SIZE - len(jaula.cilindros_trabajando)
        if faltan <= 0:
            return True

        candidatos = list(jaula.cilindros_crc)
        if len(candidatos) < faltan:
            disponibles = sorted(
                self.obtener_disponibles_para_jaula(jaula_id),
                key=lambda c: c.diametro, reverse=True
            )
            candidatos += [c for c in disponibles if c not in candidatos]

        if len(candidatos) < faltan:
            return False  # no se puede formar la pareja -> PARADA

        for cil in candidatos[:faltan]:
            self._instalar_en_jaula(cil, jaula_id, tiempo, f"Instalado en Jaula {jaula_id}")
        return True

    def _parar_jaula(self, jaula_id: int, tiempo: datetime, log) -> None:
        """
        Marca una jaula como PARADA (si no lo estaba) y, con ella, detiene toda
        la línea: registra el instante en que la línea se frenó (si no lo estaba).
        """
        jaula = self.jaulas[jaula_id]
        if not jaula.parada:
            jaula.parada = True
            jaula.parada_desde = tiempo
            self.alertas.append(Alerta(
                tiempo, "CRITICO",
                f"PARADA Jaula {jaula_id}: sin stock para formar la pareja de cilindros",
                jaula_id
            ))
            log(f"  >>> JAULA {jaula_id} PARADA: sin CRC ni disponibles para formar pareja <<<")

        # La línea entera se detiene desde el primer instante de parada.
        if self._linea_parada_desde is None:
            self._linea_parada_desde = tiempo
            log(f"  >>> LÍNEA DETENIDA desde {tiempo.strftime('%m-%d %H:%M')} "
                "(se difieren los cambios posteriores) <<<")

    def _intentar_reactivar_jaulas(self, tiempo: datetime, log, cola: List[_ItemCola]) -> bool:
        """
        Intenta rearmar las jaulas en PARADA si ya hay stock para una pareja.

        Si tras el intento NO queda ninguna jaula parada, la línea se reanuda:
        todo el programa de cambios restante (eventos diferidos durante la parada
        y los que aún quedan en la cola, posteriores al inicio de la parada) se
        desplaza por la duración total de la parada de línea.
        Las máquinas y la reposición del CRC nunca se detienen.
        Devuelve True si reactivó al menos una jaula.
        """
        reactivo = False
        for jaula_id, jaula in self.jaulas.items():
            if not jaula.parada:
                continue
            if self._instalar_pareja_o_parar(jaula_id, tiempo):
                dur = (tiempo - jaula.parada_desde).total_seconds() / 60 if jaula.parada_desde else 0.0
                jaula.parada = False
                jaula.parada_desde = None
                self.alertas.append(Alerta(
                    tiempo, "INFO",
                    f"Jaula {jaula_id} reactivada tras {dur:.0f} min de parada", jaula_id
                ))
                log(f"  >>> JAULA {jaula_id} REACTIVADA tras {dur:.0f} min de parada <<<")
                reactivo = True

        # ¿Se reanuda la línea? Solo si ya no queda ninguna jaula parada.
        if self._linea_parada_desde is not None and not any(j.parada for j in self.jaulas.values()):
            self._reanudar_linea(tiempo, log, cola)

        return reactivo

    def _reanudar_linea(self, tiempo: datetime, log, cola: List[_ItemCola]) -> None:
        """
        Reanuda la línea tras una parada: desplaza por la duración total de la
        parada todos los CAMBIO pendientes (los diferidos y los que siguen en la
        cola con tiempo posterior al inicio de la parada). Reintegra los diferidos.
        """
        inicio = self._linea_parada_desde
        dur = (tiempo - inicio).total_seconds() / 60 if inicio else 0.0
        retraso = timedelta(minutes=dur)

        # Partir del orden canónico de la cola (= orden de extracción del heap,
        # idéntico a la lista ordenada del esquema anterior) antes de desplazar.
        eventos = [ev for _, _, ev in sorted(cola)]

        # Desplazar in situ los CAMBIO que aún están en la cola (posteriores al
        # inicio), conservando su posición relativa como hacía el sort anterior.
        for i, ev_s in enumerate(eventos):
            if ev_s.tipo == "CAMBIO" and ev_s.tiempo > inicio:
                eventos[i] = _EventoSim(ev_s.tipo, ev_s.tiempo + retraso, ev_s.datos)

        # Reintegrar los cambios diferidos durante la parada, ya desplazados.
        for ev_s in self._cambios_diferidos:
            eventos.append(_EventoSim(ev_s.tipo, ev_s.tiempo + retraso, ev_s.datos))
        n_dif = len(self._cambios_diferidos)
        self._cambios_diferidos = []

        # Sort estable por tiempo (igual que antes) y reconstrucción del heap
        # reasignando la secuencia en ese orden: preserva el desempate exacto y
        # deja los eventos que se inserten después (seq mayor) detrás ante empate.
        eventos.sort(key=lambda x: x.tiempo)
        cola[:] = [(ev.tiempo, next(self._seq_cola), ev) for ev in eventos]
        heapq.heapify(cola)
        self._linea_parada_desde = None

        self.alertas.append(Alerta(
            tiempo, "INFO",
            f"LÍNEA REANUDADA tras {dur:.0f} min; programa de cambios desplazado {dur:.0f} min "
            f"({n_dif} cambio(s) diferido(s) reprogramado(s))"
        ))
        log(f"  >>> LÍNEA REANUDADA tras {dur:.0f} min | programa desplazado {dur:.0f} min "
            f"| {n_dif} cambio(s) diferido(s) <<<")

    # ── Consultas de estado ─────────────────────────────────────────────────

    def obtener_substock_por_diametro(self, diametro: float) -> Optional[SubStock]:
        """Encuentra a qué SubStock pertenece un diámetro."""
        for ss in self.lista_substocks:
            if ss.contiene_diametro(diametro):
                return ss
        return None

    def obtener_substock_por_jaula(self, jaula_id: int) -> Optional[SubStock]:
        """Obtiene el SubStock configurado para una jaula específica."""
        for ss in self.lista_substocks:
            if ss.jaula_asignada == jaula_id:
                return ss
        return None

    def obtener_cilindros_por_estado(self, estado: EstadoCilindro) -> List[Cilindro]:
        """Filtra la lista de cilindros por su estado actual."""
        return [c for c in self.cilindros.values() if c.estado == estado]

    def obtener_disponibles_para_jaula(self, jaula_id: int) -> List[Cilindro]:
        """Obtiene cilindros disponibles que cumplen el rango de diámetro de la jaula."""
        ss = self.obtener_substock_por_jaula(jaula_id)
        disponibles = self.obtener_cilindros_por_estado(EstadoCilindro.DISPONIBLE)
        if ss is None:
            return disponibles
        return [c for c in disponibles if ss.contiene_diametro(c.diametro)]

    def obtener_cola_rectificado(self) -> List[Cilindro]:
        """Obtiene la lista de cilindros esperando rectificado."""
        return self.obtener_cilindros_por_estado(EstadoCilindro.A_RECTIFICAR)

    def seleccionar_siguiente_de_cola(
        self, cola: List[Cilindro], maquina: Optional[MaquinaRectificadora] = None
    ) -> Optional[Cilindro]:
        """Elige el siguiente cilindro a rectificar para una máquina.

        Selección en dos pasos:
          1. Filtro por prioridad: si se pasa una máquina, se consideran primero
             los cilindros cuyo tipo de rectificado coincide con su
             prioridad_defecto. Si ninguno coincide (o no se pasa máquina), se
             consideran todos los de la cola.
          2. Estrategia: sobre el subconjunto resultante se aplica la estrategia
             de selección configurada (ver ESTRATEGIAS_SELECCION).
        """
        if not cola:
            return None

        candidatos = cola
        if maquina is not None:
            preferidos = [c for c in cola if c.tipo_rectificado_actual == maquina.prioridad_defecto]
            if preferidos:
                candidatos = preferidos

        estrategia = ESTRATEGIAS_SELECCION.get(
            self.estrategia_seleccion, ESTRATEGIAS_SELECCION[ESTRATEGIA_DEFECTO]
        )
        return estrategia.seleccionar(candidatos, maquina)

    # ── Snapshot ────────────────────────────────────────────────────────────

    def generar_snapshot(self, tiempo: datetime) -> None:
        """Captura el estado completo del taller para reproducción y gráficos.

        Recorre ``self.cilindros`` **una sola vez** acumulando a la vez el conteo
        por estado, el detalle de la cola de rectificado y de enfriando, y los
        conteos por SubStock (antes eran ~9 pasadas completas sobre el dict por
        snapshot, y se genera un snapshot por evento). El resultado es idéntico.
        """
        sn = Snapshot(tiempo)

        # Todos los estados presentes como clave (incluso con valor 0), igual que
        # antes: la GUI y los gráficos esperan la clave aunque no haya cilindros.
        sn.conteo_por_estado = {est.value: 0 for est in EstadoCilindro}
        # Solo estados presentes por SubStock (no se siembran ceros), como antes.
        conteo_substock: Dict[str, Dict[str, int]] = {ss.nombre: {} for ss in self.lista_substocks}

        for c in self.cilindros.values():
            estado_val = c.estado.value
            sn.conteo_por_estado[estado_val] += 1
            # El orden de estas listas sigue el de self.cilindros.values(), igual
            # que obtener_cola_rectificado()/obtener_cilindros_por_estado() antes.
            if c.estado == EstadoCilindro.A_RECTIFICAR:
                sn.detalle_cola_rectificado.append({"id": c.id, "d": c.diametro})
            elif c.estado == EstadoCilindro.ENFRIANDO:
                sn.detalle_enfriando.append({"id": c.id, "d": c.diametro})
            if c.estado != EstadoCilindro.BAJA:
                for ss in self.lista_substocks:
                    if ss.contiene_diametro(c.diametro):
                        cs = conteo_substock[ss.nombre]
                        cs[estado_val] = cs.get(estado_val, 0) + 1

        sn.cantidad_disponibles = sn.conteo_por_estado.get(EstadoCilindro.DISPONIBLE.value, 0)
        sn.cantidad_crc_total = sn.conteo_por_estado.get(EstadoCilindro.CRC.value, 0)
        sn.cantidad_bajas = sn.conteo_por_estado.get(EstadoCilindro.BAJA.value, 0)
        sn.maquinas_ocupadas = sum(1 for m in self.maquinas.values() if m.ocupada)

        for j_id, jaula in self.jaulas.items():
            sn.crc_por_jaula[j_id] = len(jaula.cilindros_crc)
            sn.detalle_jaulas[j_id] = [{"id": c.id, "d": c.diametro} for c in jaula.cilindros_trabajando]
            sn.detalle_crc[j_id] = [{"id": c.id, "d": c.diametro} for c in jaula.cilindros_crc]
            if jaula.parada:
                sn.jaulas_paradas.append(j_id)

        for m_nombre, maq in self.maquinas.items():
            sn.detalle_maquinas_operativa[m_nombre] = maq.esta_operativa(tiempo)
            if maq.ocupada and maq.cilindro_actual:
                c = maq.cilindro_actual
                progreso = 0.0
                # Progreso por tiempo operativo: no avanza durante los turnos en
                # que la máquina está parada. Con grilla None equivale al reloj.
                if maq.minutos_trabajo_actual > 0 and c.rectificado_inicio:
                    consumido = maq.progreso_operativo(tiempo)
                    progreso = min(100.0, max(0.0, (consumido / maq.minutos_trabajo_actual) * 100))
                sn.detalle_maquinas[m_nombre] = {"id": c.id, "d": c.diametro, "progreso": progreso}
            else:
                sn.detalle_maquinas[m_nombre] = None

        for ss in self.lista_substocks:
            conteo = conteo_substock[ss.nombre]
            sn.conteo_por_substock[ss.nombre] = conteo
            sn.disponibles_por_substock[ss.nombre] = conteo.get(EstadoCilindro.DISPONIBLE.value, 0)

        self.snapshots.append(sn)

    # ── Lógica de asignación ────────────────────────────────────────────────

    def asignar_trabajo_maquinas(self, tiempo: datetime) -> List[_EventoSim]:
        """Intenta asignar cilindros de la cola a máquinas libres.

        Una máquina solo toma trabajo si está en un turno operativo (ver
        esquema de trabajo en modelos/turnos.py). Las máquinas libres fuera de
        turno con cola pendiente se "despiertan" con un evento REANUDAR_MAQUINA
        al comienzo de su próximo turno.
        """
        nuevos_eventos: List[_EventoSim] = []
        cola = self.obtener_cola_rectificado()
        for nombre, maq in self.maquinas.items():
            if maq.ocupada:
                continue
            # Fuera de turno: no rectifica. Si hay cola, programar un despertar
            # en la próxima apertura (sin duplicar) y seguir con otras máquinas.
            if not maq.esta_operativa(tiempo):
                if cola and not maq._despertar_programado:
                    apertura = maq.proxima_apertura(tiempo)
                    if apertura is not None:
                        maq._despertar_programado = True
                        nuevos_eventos.append(_EventoSim("REANUDAR_MAQUINA", apertura, nombre))
                continue
            if not cola:
                break
            cil = self.seleccionar_siguiente_de_cola(cola, maq)
            if cil is None:
                continue

            mm = cil.mm_a_rectificar if cil.mm_a_rectificar > 0 else _MM_RECTIFICAR_DEFECTO
            tipo = cil.tipo_rectificado_actual if cil.tipo_rectificado_actual else maq.prioridad_defecto
            nuevo_diam = cil.diametro - mm

            if nuevo_diam < self.diametro_minimo:
                cil.estado = EstadoCilindro.BAJA
                cil.registrar_evento(
                    tiempo, "BAJA",
                    f"Diámetro proyectado {nuevo_diam:.2f} < {self.diametro_minimo}"
                )
                self.alertas.append(Alerta(tiempo, "INFO", f"Cilindro {cil.id} dado de BAJA"))
                cola.remove(cil)
                continue

            maq.iniciar_rectificado(cil, tiempo, tipo, mm)
            nuevos_eventos.append(_EventoSim("FIN_RECT", maq.tiempo_fin_rectificado, nombre))
            cola.remove(cil)

        return nuevos_eventos

    def reponer_buffer_crc(self, jaula_id: int, tiempo: datetime) -> bool:
        """Intenta llenar el CRC de una jaula con cilindros disponibles."""
        jaula = self.jaulas[jaula_id]
        necesarios = _BUFFER_CRC_SIZE - len(jaula.cilindros_crc)
        if necesarios <= 0:
            return True

        disponibles = sorted(
            self.obtener_disponibles_para_jaula(jaula_id), key=lambda c: c.diametro, reverse=True
        )
        completados = 0
        for cil in disponibles:
            if completados >= necesarios:
                break
            cil.estado = EstadoCilindro.CRC
            cil.jaula = jaula_id
            jaula.cilindros_crc.append(cil)
            cil.registrar_evento(tiempo, f"Traslado a CRC Jaula {jaula_id}")
            completados += 1

        return completados >= necesarios

    def _push_evento(self, cola: List[_ItemCola], evento: _EventoSim) -> None:
        """Inserta un evento en la cola de prioridad (heap) por (tiempo, secuencia).

        El contador de secuencia rompe los empates de tiempo en orden FIFO de
        inserción, reproduciendo exactamente el orden que daba el list.sort()
        estable por tiempo del esquema anterior (y evita comparar _EventoSim).
        """
        heapq.heappush(cola, (evento.tiempo, next(self._seq_cola), evento))

    def _programar_reposicion_crc(self, jaula_id: int, tiempo_solicitud: datetime, cola: List[_ItemCola]) -> None:
        """
        Encola una reposición del CRC respetando el recurso único de traslado.

        El traslado Disponible→CRC lo realiza un único recurso (grúa/operario),
        por lo que las reposiciones se serializan: cada pareja tarda
        tiempo_traslado_crc_min y la siguiente no comienza hasta que la anterior
        termina. Si ya hay una reposición pendiente para la jaula, o su CRC ya
        está completo, no se programa nada.
        """
        if jaula_id in self._reposicion_pendiente:
            return
        if len(self.jaulas[jaula_id].cilindros_crc) >= _BUFFER_CRC_SIZE:
            return

        libre_en = self._recurso_crc_libre_en or tiempo_solicitud
        inicio = max(tiempo_solicitud, libre_en)
        fin = inicio + timedelta(minutes=self.tiempo_traslado_crc_min)
        self._recurso_crc_libre_en = fin
        self._reposicion_pendiente.add(jaula_id)
        self._push_evento(cola, _EventoSim("REPONER_CRC", fin, jaula_id))

    # ── Manejadores de eventos de simulación ────────────────────────────────

    def _finalizar_y_continuar(self, maquina: MaquinaRectificadora, tiempo: datetime,
                               cola: List[_ItemCola], log: Callable[[str], None]) -> None:
        """Cierra un rectificado y reactiva el flujo dependiente.

        Tras liberar la máquina: rearma jaulas paradas con el nuevo stock,
        repone el CRC, reasigna trabajo a las máquinas libres y toma snapshot.
        Compartido por el manejador de FIN_RECT y por el drenaje final de la
        simulación (ambos cierran rectificados en curso de idéntica forma).
        """
        cil_terminado = maquina.finalizar_rectificado(tiempo)
        if cil_terminado:
            # Prioridad: rearmar jaulas paradas antes de reponer el CRC.
            self._intentar_reactivar_jaulas(tiempo, log, cola)
            for j_id in range(1, self.cantidad_jaulas + 1):
                self._programar_reposicion_crc(j_id, tiempo, cola)
        for ev in self.asignar_trabajo_maquinas(tiempo):
            self._push_evento(cola, ev)
        self.generar_snapshot(tiempo)

    def _handle_fin_rect(self, ev_sim: "_EventoSim", cola: List[_ItemCola],
                         log: Callable[[str], None]) -> None:
        """FIN_RECT: una máquina termina un rectificado.

        Nunca se difiere durante una PARADA: es justo lo que produce el stock
        que permite reanudar la línea.
        """
        maquina = self.maquinas.get(ev_sim.datos)
        if not maquina or not maquina.ocupada:
            return
        # Descarta FIN_RECT obsoletos (la máquina ya fue reasignada): el fin
        # registrado debe coincidir con el del evento.
        if (maquina.tiempo_fin_rectificado
                and abs((maquina.tiempo_fin_rectificado - ev_sim.tiempo).total_seconds()) > 2):
            return
        self._finalizar_y_continuar(maquina, ev_sim.tiempo, cola, log)

    def _handle_reponer_crc(self, ev_sim: "_EventoSim", cola: List[_ItemCola],
                            log: Callable[[str], None]) -> None:
        """REPONER_CRC: llega una pareja al buffer CRC (siempre se ejecuta, aun en PARADA)."""
        j_id = ev_sim.datos
        self._reposicion_pendiente.discard(j_id)
        # Solo repone (y genera snapshot) si el CRC sigue incompleto.
        if len(self.jaulas[j_id].cilindros_crc) < _BUFFER_CRC_SIZE:
            self.reponer_buffer_crc(j_id, ev_sim.tiempo)
            self._intentar_reactivar_jaulas(ev_sim.tiempo, log, cola)
            self.generar_snapshot(ev_sim.tiempo)

    def _handle_fin_enfriado(self, ev_sim: "_EventoSim", cola: List[_ItemCola],
                             log: Callable[[str], None]) -> None:
        """FIN_ENFRIADO: un cilindro termina de enfriarse y entra a la cola de rectificado.

        El enfriado es un proceso físico: se completa siempre, también durante
        una PARADA (igual que FIN_RECT).
        """
        cil = self.cilindros.get(ev_sim.datos)
        if cil and cil.estado == EstadoCilindro.ENFRIANDO:
            cil.estado = EstadoCilindro.A_RECTIFICAR
            cil.registrar_evento(ev_sim.tiempo, "Fin de enfriado, pasa a cola de rectificado")
            for ev in self.asignar_trabajo_maquinas(ev_sim.tiempo):
                self._push_evento(cola, ev)
            self.generar_snapshot(ev_sim.tiempo)

    def _handle_reanudar_maquina(self, ev_sim: "_EventoSim", cola: List[_ItemCola],
                                 log: Callable[[str], None]) -> None:
        """REANUDAR_MAQUINA: una máquina reabre su turno y reintenta tomar trabajo.

        Es un proceso de reloj (turnos): siempre se ejecuta, también durante una
        PARADA, y _reanudar_linea no lo desplaza (igual que FIN_RECT/FIN_ENFRIADO).
        """
        maquina = self.maquinas.get(ev_sim.datos)
        if not maquina:
            return
        maquina._despertar_programado = False
        for ev in self.asignar_trabajo_maquinas(ev_sim.tiempo):
            self._push_evento(cola, ev)
        self.generar_snapshot(ev_sim.tiempo)

    def _handle_cambio(self, ev_sim: "_EventoSim", cola: List[_ItemCola],
                       log: Callable[[str], None]) -> None:
        """CAMBIO: cambio de jaula programado. Único evento que una PARADA difiere."""
        ev = ev_sim.datos
        if ev.id in self._eventos_procesados:
            return

        # Línea detenida: se difieren los cambios posteriores al inicio de la
        # parada (los simultáneos a la parada sí se ejecutan). Se reprograman al
        # reanudarse la línea, desplazados por la duración total de la parada.
        if (self._linea_parada_desde is not None
                and ev_sim.tiempo > self._linea_parada_desde):
            self._cambios_diferidos.append(ev_sim)
            return

        self._eventos_procesados.add(ev.id)
        jaula = self.jaulas[ev.jaula]

        # ev_sim.tiempo es el tiempo real de procesamiento (puede estar desplazado
        # respecto al ev.tiempo original si hubo una PARADA).
        t_proc = ev_sim.tiempo
        retraso_str = (f" [orig {ev.tiempo.strftime('%H:%M')}, retr "
                       f"{int((t_proc - ev.tiempo).total_seconds() / 60)} min]"
                       if t_proc != ev.tiempo else "")
        log(f"  {t_proc.strftime('%m-%d %H:%M')} | Jaula {ev.jaula} | Cambio a {ev.tipo.value}"
            f" | CRC={len(jaula.cilindros_crc)}{retraso_str}")

        # 1. Los cilindros trabajando salen de la jaula. Con enfriado configurado
        #    pasan a ENFRIANDO (entran a rectificado al disparar FIN_ENFRIADO);
        #    si es 0, van directo a A_RECTIFICAR (comportamiento histórico).
        for cil in list(jaula.cilindros_trabajando):
            cil.jaula = None
            cil.tipo_rectificado_actual = ev.tipo
            cil.mm_a_rectificar = ev.mm_a_rectificar
            if self.tiempo_enfriado_h > 0:
                cil.estado = EstadoCilindro.ENFRIANDO
                fin_enfriado = t_proc + timedelta(hours=self.tiempo_enfriado_h)
                cil.registrar_evento(
                    t_proc, f"En enfriado tras Jaula {ev.jaula} ({self.tiempo_enfriado_h:.1f} h)")
                self._push_evento(cola, _EventoSim("FIN_ENFRIADO", fin_enfriado, cil.id))
            else:
                cil.estado = EstadoCilindro.A_RECTIFICAR
                cil.registrar_evento(t_proc, f"Retirado de Jaula {ev.jaula} para rectificado")
        jaula.cilindros_trabajando.clear()

        # 2. Subir una pareja completa a la jaula; si no hay stock, PARADA.
        #    La jaula no puede operar con menos de _BUFFER_CRC_SIZE cilindros.
        if self._instalar_pareja_o_parar(ev.jaula, t_proc):
            jaula.parada = False
            jaula.parada_desde = None
        else:
            self._parar_jaula(ev.jaula, t_proc, log)

        # 3. Asignar trabajo a máquinas y 4. programar reposición del CRC con el
        #    CRC ya vaciado; luego snapshot. El orden de inserción (asignaciones
        #    antes que la reposición) fija el desempate ante igual tiempo.
        for ev_nuevo in self.asignar_trabajo_maquinas(t_proc):
            self._push_evento(cola, ev_nuevo)
        self._programar_reposicion_crc(ev.jaula, t_proc, cola)
        self.generar_snapshot(t_proc)

    # ── Simulación ──────────────────────────────────────────────────────────

    def simular(self, estrategia: str = "mayor_diametro", callback_log: Optional[Callable[[str], None]] = None) -> None:
        """Ejecuta la simulación completa basada en los eventos programados."""
        self.estrategia_seleccion = estrategia
        self.alertas.clear()
        self.snapshots.clear()

        def _log(msg: str) -> None:
            if callback_log:
                callback_log(msg)

        if not self.eventos_programados:
            _log("No hay eventos programados para simular.")
            return

        _log(f"Iniciando simulación | Estrategia: {estrategia} | Cilindros: {len(self.cilindros)}")

        t_actual = self.eventos_programados[0].tiempo - timedelta(minutes=1)
        self._recurso_crc_libre_en = t_actual
        self._reposicion_pendiente = set()
        self._linea_parada_desde = None
        self._cambios_diferidos = []
        self._eventos_procesados: set = set()
        self._seq_cola = itertools.count()
        self.generar_snapshot(t_actual)

        # Cola de prioridad (heap) por (tiempo, secuencia): push/pop en O(log n)
        # en lugar del list.sort() O(n log n) por evento del esquema anterior.
        # El orden de inserción inicial (todos los CAMBIO y luego las asignaciones
        # a máquinas) fija el desempate ante igual tiempo, igual que antes.
        cola: List[_ItemCola] = []
        for ev in self.eventos_programados:
            self._push_evento(cola, _EventoSim("CAMBIO", ev.tiempo, ev))
        for ev in self.asignar_trabajo_maquinas(t_actual):
            self._push_evento(cola, ev)

        # Despacho por tipo de evento. Una PARADA de línea solo difiere los CAMBIO
        # (ver _handle_cambio); FIN_RECT/REPONER_CRC/FIN_ENFRIADO siempre se
        # ejecutan: las máquinas siguen produciendo el stock que reanuda la línea.
        handlers = {
            "FIN_RECT": self._handle_fin_rect,
            "REPONER_CRC": self._handle_reponer_crc,
            "FIN_ENFRIADO": self._handle_fin_enfriado,
            "REANUDAR_MAQUINA": self._handle_reanudar_maquina,
            "CAMBIO": self._handle_cambio,
        }

        iteracion = 0
        while cola and iteracion < self.max_iteraciones:
            iteracion += 1
            _, _, ev_sim = heapq.heappop(cola)
            handler = handlers.get(ev_sim.tipo)
            if handler:
                handler(ev_sim, cola, _log)

        if cola and iteracion >= self.max_iteraciones:
            msg = f"ADVERTENCIA: Límite de {self.max_iteraciones} iteraciones alcanzado con {len(cola)} eventos pendientes."
            logger.warning(msg)
            _log(msg)

        # Finalizar rectificados en curso al terminar los eventos programados,
        # con la misma lógica que FIN_RECT (vía _finalizar_y_continuar).
        for _ in range(_MAX_ITER_FINALIZACION):
            hay_actividad = False
            for maquina in self.maquinas.values():
                if maquina.ocupada and maquina.tiempo_fin_rectificado:
                    hay_actividad = True
                    self._finalizar_y_continuar(maquina, maquina.tiempo_fin_rectificado, cola, _log)
            if not hay_actividad:
                break

        t_final = max(s.tiempo for s in self.snapshots) + timedelta(minutes=30) if self.snapshots else datetime.now()
        self.generar_snapshot(t_final)

        # Cambios que nunca se ejecutaron por una parada de línea sin reanudar.
        sin_ejecutar = (list(self._cambios_diferidos)
                        + [ev for _, _, ev in cola if ev.tipo == "CAMBIO"])
        if sin_ejecutar:
            ids = ", ".join(e.datos.id for e in sin_ejecutar)
            msg = (f"ADVERTENCIA: {len(sin_ejecutar)} cambio(s) no se ejecutaron por parada "
                   f"de línea sin reanudar: {ids}")
            logger.warning(msg)
            _log(f"  >>> {msg} <<<")

        nc = sum(1 for a in self.alertas if a.tipo == "CRITICO")
        nb = len(self.obtener_cilindros_por_estado(EstadoCilindro.BAJA))
        _log(f"\nSimulación finalizada | Alertas Críticas: {nc} | Bajas: {nb}")

    # ── Exportación ─────────────────────────────────────────────────────────

    def exportar_resultados(self, ruta_archivo: str) -> None:
        """Guarda el estado final y alertas en un archivo Excel."""
        datos_finales = []
        for cil in self.cilindros.values():
            ss = self.obtener_substock_por_diametro(cil.diametro)
            datos_finales.append({
                "ID": cil.id,
                "D_Original": cil.diametro_original,
                "D_Final": cil.diametro,
                "Desgaste_Total": round(cil.diametro_original - cil.diametro, 2),
                "Estado": cil.estado.value,
                "SubStock": ss.nombre if ss else "-",
                "Jaula": cil.jaula if cil.jaula else "-"
            })

        df_stock = pd.DataFrame(datos_finales).sort_values("D_Final", ascending=False)

        alertas_list = [
            {"Tiempo": a.tiempo, "Tipo": a.tipo, "Mensaje": a.mensaje, "Jaula": a.jaula if a.jaula else "-"}
            for a in self.alertas
        ]
        df_alertas = (
            pd.DataFrame(alertas_list) if alertas_list
            else pd.DataFrame(columns=["Tiempo", "Tipo", "Mensaje", "Jaula"])
        )

        with pd.ExcelWriter(ruta_archivo, engine="openpyxl") as writer:
            df_stock.to_excel(writer, sheet_name="Stock_Final", index=False)
            df_alertas.to_excel(writer, sheet_name="Alertas", index=False)
