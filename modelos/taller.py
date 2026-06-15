"""
Motor de simulación del taller de cilindros.
Coordina cilindros, máquinas, jaulas y eventos de cambio.
"""
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any, NamedTuple
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro
from .substock import SubStock
from .maquina import MaquinaRectificadora
from .jaula import Jaula
from .eventos import EventoCambio, Alerta, Snapshot

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
    tipo: str       # "CAMBIO" | "FIN_RECT"
    tiempo: datetime
    datos: Any      # EventoCambio (CAMBIO) | str nombre máquina (FIN_RECT)


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

    ESTADOS_NOMBRES = ["Trabajando", "CRC", "Disponible", "A rectificar", "Rectificando", "Baja"]

    def __init__(self):
        self.cilindros: Dict[str, Cilindro] = {}
        self.lista_substocks: List[SubStock] = []
        self.maquinas: Dict[str, MaquinaRectificadora] = {}
        self.jaulas: Dict[int, Jaula] = {}
        self.eventos_programados: List[EventoCambio] = []
        self.alertas: List[Alerta] = []
        self.snapshots: List[Snapshot] = []

        # Parámetros de configuración (sobreescritos al cargar Excel)
        self.diametro_maximo: float = 575.0
        self.diametro_minimo: float = 520.0
        self.tiempo_traslado_crc_min: float = 10.0
        self.cantidad_jaulas: int = 4
        self.estrategia_seleccion: str = "mayor_diametro"

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

    # ── Carga de datos desde Excel ──────────────────────────────────────────

    def cargar_datos(self, ruta_excel: str) -> None:
        """Carga configuración e inventario inicial desde un archivo Excel."""
        self.cilindros.clear()
        self.maquinas.clear()
        self.jaulas.clear()
        self.eventos_programados.clear()
        self.alertas.clear()
        self.snapshots.clear()

        try:
            xl = pd.ExcelFile(ruta_excel, engine="openpyxl")
        except Exception as exc:
            raise IOError(f"No se pudo abrir el archivo Excel '{ruta_excel}': {exc}") from exc

        hojas_requeridas = [_HOJA_CONFIG, _HOJA_MAQUINAS, _HOJA_STOCK, _HOJA_CAMBIOS]
        faltantes = [h for h in hojas_requeridas if h not in xl.sheet_names]
        if faltantes:
            raise ValueError(f"Hojas faltantes en el Excel: {faltantes}")

        self._cargar_configuracion(xl.parse(_HOJA_CONFIG))
        self._cargar_maquinas(xl.parse(_HOJA_MAQUINAS))
        self._cargar_stock(xl.parse(_HOJA_STOCK))
        self._cargar_cambios(xl.parse(_HOJA_CAMBIOS))

    def _cargar_configuracion(self, df: pd.DataFrame) -> None:
        """Aplica los parámetros generales de la hoja Configuración."""
        cfg = dict(zip(df["Parámetro"], df["Valor"]))
        self.diametro_maximo = float(cfg.get("Diámetro Máximo (mm)", self.diametro_maximo))
        self.diametro_minimo = float(cfg.get("Diámetro Mínimo (mm)", self.diametro_minimo))
        self.tiempo_traslado_crc_min = float(
            cfg.get("Tiempo Disponible→CRC por pareja (min)", self.tiempo_traslado_crc_min)
        )
        self.cantidad_jaulas = int(cfg.get("Cantidad de Jaulas", self.cantidad_jaulas))

    def _cargar_maquinas(self, df: pd.DataFrame) -> None:
        """Carga las tasas de rectificado de cada máquina."""
        for idx, row in df.iterrows():
            nombre = str(row["Máquina"])
            tipo_str = str(row["Tipo_Rectificado"])
            try:
                TipoRectificado(tipo_str)
            except ValueError as exc:
                raise ValueError(
                    f"Tipo de rectificado inválido '{tipo_str}' en hoja Máquinas, fila {idx}"
                ) from exc
            if nombre not in self.maquinas:
                self.maquinas[nombre] = MaquinaRectificadora(nombre)
            self.maquinas[nombre].configurar_tasa(tipo_str, float(row["mm_removidos"]), float(row["Tiempo_min"]))

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

    def _instalar_en_jaula(self, cil: Cilindro, jaula_id: int, tiempo: datetime, motivo: str) -> None:
        """Mueve un cilindro al estado TRABAJANDO en la jaula indicada."""
        jaula = self.jaulas[jaula_id]
        cil.estado = EstadoCilindro.TRABAJANDO
        cil.jaula = jaula_id
        if cil in jaula.cilindros_crc:
            jaula.cilindros_crc.remove(cil)
        jaula.cilindros_trabajando.append(cil)
        cil.registrar_evento(tiempo, motivo)

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

    def seleccionar_siguiente_de_cola(self, cola: List[Cilindro]) -> Optional[Cilindro]:
        """Aplica la estrategia de selección sobre la cola de rectificado."""
        if not cola:
            return None
        if self.estrategia_seleccion == "mayor_diametro":
            return max(cola, key=lambda c: c.diametro)
        if self.estrategia_seleccion == "menor_diametro":
            return min(cola, key=lambda c: c.diametro)
        return cola[0]  # FIFO por defecto

    # ── Snapshot ────────────────────────────────────────────────────────────

    def generar_snapshot(self, tiempo: datetime) -> None:
        """Captura el estado completo del taller para reproducción y gráficos."""
        sn = Snapshot(tiempo)

        for est in EstadoCilindro:
            sn.conteo_por_estado[est.value] = len(self.obtener_cilindros_por_estado(est))

        sn.cantidad_disponibles = sn.conteo_por_estado.get(EstadoCilindro.DISPONIBLE.value, 0)
        sn.cantidad_crc_total = sn.conteo_por_estado.get(EstadoCilindro.CRC.value, 0)
        sn.cantidad_bajas = sn.conteo_por_estado.get(EstadoCilindro.BAJA.value, 0)
        sn.maquinas_ocupadas = sum(1 for m in self.maquinas.values() if m.ocupada)

        for j_id, jaula in self.jaulas.items():
            sn.crc_por_jaula[j_id] = len(jaula.cilindros_crc)
            sn.detalle_jaulas[j_id] = [{"id": c.id, "d": c.diametro} for c in jaula.cilindros_trabajando]
            sn.detalle_crc[j_id] = [{"id": c.id, "d": c.diametro} for c in jaula.cilindros_crc]

        for m_nombre, maq in self.maquinas.items():
            if maq.ocupada and maq.cilindro_actual:
                c = maq.cilindro_actual
                progreso = 0.0
                if maq.tiempo_fin_rectificado and c.rectificado_inicio:
                    total = (maq.tiempo_fin_rectificado - c.rectificado_inicio).total_seconds()
                    transcurrido = (tiempo - c.rectificado_inicio).total_seconds()
                    progreso = min(100.0, max(0.0, (transcurrido / total) * 100)) if total > 0 else 0.0
                sn.detalle_maquinas[m_nombre] = {"id": c.id, "d": c.diametro, "progreso": progreso}
            else:
                sn.detalle_maquinas[m_nombre] = None

        sn.detalle_cola_rectificado = [{"id": c.id, "d": c.diametro} for c in self.obtener_cola_rectificado()]

        for ss in self.lista_substocks:
            conteo: Dict[str, int] = {}
            for c in self.cilindros.values():
                if c.estado != EstadoCilindro.BAJA and ss.contiene_diametro(c.diametro):
                    conteo[c.estado.value] = conteo.get(c.estado.value, 0) + 1
            sn.conteo_por_substock[ss.nombre] = conteo
            sn.disponibles_por_substock[ss.nombre] = conteo.get(EstadoCilindro.DISPONIBLE.value, 0)

        self.snapshots.append(sn)

    # ── Lógica de asignación ────────────────────────────────────────────────

    def asignar_trabajo_maquinas(self, tiempo: datetime) -> List[_EventoSim]:
        """Intenta asignar cilindros de la cola a máquinas libres."""
        nuevos_eventos: List[_EventoSim] = []
        for nombre, maq in self.maquinas.items():
            if maq.ocupada:
                continue
            cola = self.obtener_cola_rectificado()
            if not cola:
                break
            cil = self.seleccionar_siguiente_de_cola(cola)
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
                continue

            maq.iniciar_rectificado(cil, tiempo, tipo, mm)
            nuevos_eventos.append(_EventoSim("FIN_RECT", maq.tiempo_fin_rectificado, nombre))

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
        self.generar_snapshot(t_actual)

        cola: List[_EventoSim] = [_EventoSim("CAMBIO", ev.tiempo, ev) for ev in self.eventos_programados]
        nuevos = self.asignar_trabajo_maquinas(t_actual)
        cola.extend(nuevos)
        cola.sort(key=lambda x: x.tiempo)

        eventos_procesados: set = set()
        iteracion = 0
        while cola and iteracion < _MAX_ITERACIONES_SIM:
            iteracion += 1
            ev_sim = cola.pop(0)

            if ev_sim.tipo == "FIN_RECT":
                maq_nombre = ev_sim.datos
                maq = self.maquinas.get(maq_nombre)
                if not maq or not maq.ocupada:
                    continue
                if maq.tiempo_fin_rectificado and abs((maq.tiempo_fin_rectificado - ev_sim.tiempo).total_seconds()) > 2:
                    continue

                cil_terminado = maq.finalizar_rectificado(ev_sim.tiempo)
                if cil_terminado:
                    # Programar reposición del CRC (tarda tiempo_traslado_crc_min)
                    for j_id in range(1, self.cantidad_jaulas + 1):
                        if len(self.jaulas[j_id].cilindros_crc) < _BUFFER_CRC_SIZE:
                            cola.append(_EventoSim(
                                "REPONER_CRC",
                                ev_sim.tiempo + timedelta(minutes=self.tiempo_traslado_crc_min),
                                j_id
                            ))

                nuevos = self.asignar_trabajo_maquinas(ev_sim.tiempo)
                cola.extend(nuevos)
                cola.sort(key=lambda x: x.tiempo)
                self.generar_snapshot(ev_sim.tiempo)

            elif ev_sim.tipo == "REPONER_CRC":
                j_id = ev_sim.datos
                # Solo repone (y genera snapshot) si el CRC sigue incompleto
                if len(self.jaulas[j_id].cilindros_crc) < _BUFFER_CRC_SIZE:
                    self.reponer_buffer_crc(j_id, ev_sim.tiempo)
                    self.generar_snapshot(ev_sim.tiempo)

            elif ev_sim.tipo == "CAMBIO":
                ev = ev_sim.datos
                if ev.id in eventos_procesados:
                    continue
                eventos_procesados.add(ev.id)
                jaula = self.jaulas[ev.jaula]

                _log(f"  {ev.tiempo.strftime('%m-%d %H:%M')} | Jaula {ev.jaula} | Cambio a {ev.tipo.value} | CRC={len(jaula.cilindros_crc)}")

                # 1. Los cilindros trabajando pasan a cola de rectificado
                for cil in list(jaula.cilindros_trabajando):
                    cil.estado = EstadoCilindro.A_RECTIFICAR
                    cil.jaula = None
                    cil.tipo_rectificado_actual = ev.tipo
                    cil.mm_a_rectificar = ev.mm_a_rectificar
                    cil.registrar_evento(ev.tiempo, f"Retirado de Jaula {ev.jaula} para rectificado")
                jaula.cilindros_trabajando.clear()

                # 2. Subir cilindros del CRC a la jaula
                if len(jaula.cilindros_crc) >= _BUFFER_CRC_SIZE:
                    pareja = list(jaula.cilindros_crc[:_BUFFER_CRC_SIZE])
                    for cil in pareja:
                        self._instalar_en_jaula(cil, ev.jaula, ev.tiempo, f"Instalado en Jaula {ev.jaula} (desde CRC)")
                else:
                    # Caso crítico: CRC insuficiente
                    for cil in list(jaula.cilindros_crc):
                        self._instalar_en_jaula(cil, ev.jaula, ev.tiempo, f"Instalado en Jaula {ev.jaula} (urgente)")

                    deficit = _BUFFER_CRC_SIZE - len(jaula.cilindros_trabajando)
                    if deficit > 0:
                        disponibles = sorted(
                            self.obtener_disponibles_para_jaula(ev.jaula),
                            key=lambda c: c.diametro, reverse=True
                        )
                        for cil in disponibles[:deficit]:
                            self._instalar_en_jaula(
                                cil, ev.jaula, ev.tiempo,
                                f"Instalado en Jaula {ev.jaula} (directo desde disponible)"
                            )

                    deficit = _BUFFER_CRC_SIZE - len(jaula.cilindros_trabajando)
                    if deficit > 0:
                        self.alertas.append(
                            Alerta(ev.tiempo, "CRITICO",
                                   f"STOCK INSUFICIENTE Jaula {ev.jaula}: faltan {deficit} cilindros",
                                   ev.jaula)
                        )
                        _log(f"  >>> ALERTA CRÍTICA: Jaula {ev.jaula} desabastecida! <<<")

                # 3. Asignar trabajo a máquinas y snapshot con el CRC ya vaciado
                nuevos = self.asignar_trabajo_maquinas(ev.tiempo)
                cola.extend(nuevos)
                # 4. Programar la reposición del CRC (tarda tiempo_traslado_crc_min)
                cola.append(_EventoSim(
                    "REPONER_CRC",
                    ev.tiempo + timedelta(minutes=self.tiempo_traslado_crc_min),
                    ev.jaula
                ))
                cola.sort(key=lambda x: x.tiempo)
                self.generar_snapshot(ev.tiempo)

        if cola and iteracion >= _MAX_ITERACIONES_SIM:
            msg = f"ADVERTENCIA: Límite de {_MAX_ITERACIONES_SIM} iteraciones alcanzado con {len(cola)} eventos pendientes."
            logger.warning(msg)
            _log(msg)

        # Finalizar rectificados en curso al terminar los eventos programados
        for _ in range(_MAX_ITER_FINALIZACION):
            hay_actividad = False
            for maq in self.maquinas.values():
                if maq.ocupada and maq.tiempo_fin_rectificado:
                    hay_actividad = True
                    t_fin = maq.tiempo_fin_rectificado
                    maq.finalizar_rectificado(t_fin)
                    for j_id in range(1, self.cantidad_jaulas + 1):
                        if len(self.jaulas[j_id].cilindros_crc) < _BUFFER_CRC_SIZE:
                            self.reponer_buffer_crc(j_id, t_fin + timedelta(minutes=self.tiempo_traslado_crc_min))
                    self.asignar_trabajo_maquinas(t_fin)
                    self.generar_snapshot(t_fin)
            if not hay_actividad:
                break

        t_final = max(s.tiempo for s in self.snapshots) + timedelta(minutes=30) if self.snapshots else datetime.now()
        self.generar_snapshot(t_final)

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
