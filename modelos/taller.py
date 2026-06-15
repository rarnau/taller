"""
Motor de simulación del taller de cilindros.
Coordina cilindros, máquinas, jaulas y eventos de cambio.
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro
from .substock import SubStock
from .maquina import MaquinaRectificadora
from .jaula import Jaula
from .eventos import EventoCambio, Alerta, Snapshot


class TallerCilindros:
    """
    Clase principal que gestiona la lógica de la simulación.
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

        # Parámetros de configuración
        self.diametro_maximo = 575.0
        self.diametro_minimo = 520.0
        self.tiempo_traslado_crc_min = 10.0
        self.cantidad_jaulas = 4
        self.estrategia_seleccion = "mayor_diametro"

    def configurar_substocks(self, rangos_config: List[Dict[str, Any]]):
        """Define los rangos de diámetros para cada jaula."""
        self.lista_substocks.clear()
        for r in rangos_config:
            jaula = int(r["jaula"])
            desde = float(r["desde"])
            hasta = float(r["hasta"])
            nombre = f"SS{jaula} ({hasta:.0f}-{desde:.0f})"
            self.lista_substocks.append(SubStock(nombre, jaula, desde, hasta, jaula_asignada=jaula))

    def aplicar_prioridades_maquinas(self, prioridades: Dict[str, str]):
        """Asigna el tipo de rectificado prioritario a cada máquina."""
        for nombre, tipo in prioridades.items():
            if nombre in self.maquinas:
                self.maquinas[nombre].prioridad_defecto = TipoRectificado(tipo)

    def cargar_datos(self, ruta_excel: str):
        """Carga toda la configuración inicial y estado del taller desde un Excel."""
        self.cilindros.clear()
        self.maquinas.clear()
        self.jaulas.clear()
        self.eventos_programados.clear()
        self.alertas.clear()
        self.snapshots.clear()

        # 1. Cargar Configuración General
        df_cfg = pd.read_excel(ruta_excel, sheet_name="Configuración", engine="openpyxl")
        cfg_dict = dict(zip(df_cfg["Parámetro"], df_cfg["Valor"]))
        self.diametro_maximo = float(cfg_dict.get("Diámetro Máximo (mm)", 575))
        self.diametro_minimo = float(cfg_dict.get("Diámetro Mínimo (mm)", 520))
        self.tiempo_traslado_crc_min = float(cfg_dict.get("Tiempo Disponible→CRC por pareja (min)", 10))
        self.cantidad_jaulas = int(cfg_dict.get("Cantidad de Jaulas", 4))

        # 2. Cargar Máquinas
        df_maqs = pd.read_excel(ruta_excel, sheet_name="Máquinas", engine="openpyxl")
        for _, row in df_maqs.iterrows():
            nombre = str(row["Máquina"])
            if nombre not in self.maquinas:
                self.maquinas[nombre] = MaquinaRectificadora(nombre)
            self.maquinas[nombre].configurar_tasa(
                str(row["Tipo_Rectificado"]),
                float(row["mm_removidos"]),
                float(row["Tiempo_min"])
            )

        # 3. Cargar Stock Inicial
        df_stock = pd.read_excel(ruta_excel, sheet_name="Stock_Inicial", engine="openpyxl")
        for _, row in df_stock.iterrows():
            estado = EstadoCilindro(row["Estado"])
            jaula_id = int(row["Jaula_Asignada"]) if pd.notna(row.get("Jaula_Asignada")) else None
            pos = int(row["Posición"]) if pd.notna(row.get("Posición")) else None

            cil = Cilindro(str(row["ID_Cilindro"]), float(row["Diámetro_mm"]), estado, jaula_id, pos)

            if estado in (EstadoCilindro.A_RECTIFICAR, EstadoCilindro.RECTIFICANDO):
                cil.mm_a_rectificar = float(row["mm_a_Rectificar"]) if "mm_a_Rectificar" in row.index and pd.notna(row.get("mm_a_Rectificar")) else 0.8
                tipo_str = str(row["Tipo_Rectificado"]) if "Tipo_Rectificado" in row.index and pd.notna(row.get("Tipo_Rectificado")) else "produccion"
                cil.tipo_rectificado_actual = TipoRectificado(tipo_str)
                if estado == EstadoCilindro.RECTIFICANDO:
                    cil.estado = EstadoCilindro.A_RECTIFICAR

            self.cilindros[cil.id] = cil

        # Inicializar Jaulas
        for j_id in range(1, self.cantidad_jaulas + 1):
            self.jaulas[j_id] = Jaula(j_id)

        # Ubicar cilindros en jaulas
        for cil in self.cilindros.values():
            if cil.estado == EstadoCilindro.TRABAJANDO and cil.jaula:
                self.jaulas[cil.jaula].cilindros_trabajando.append(cil)
            elif cil.estado == EstadoCilindro.CRC and cil.jaula:
                self.jaulas[cil.jaula].cilindros_crc.append(cil)

        self._garantizar_parejas_iniciales()

        # 4. Cargar Programa de Cambios
        df_cambios = pd.read_excel(ruta_excel, sheet_name="Programa_Cambios", engine="openpyxl")
        for _, row in df_cambios.iterrows():
            evento = EventoCambio(
                id_evento=str(row["ID_Cambio"]),
                tiempo=pd.to_datetime(row["Fecha_Hora"]),
                jaula=int(row["Jaula"]),
                tipo=TipoRectificado(str(row["Tipo_Rectificado"])),
                mm_a_rectificar=float(row["mm_a_Rectificar"]),
                observacion=str(row.get("Observación", ""))
            )
            self.eventos_programados.append(evento)

        self.eventos_programados.sort(key=lambda e: e.tiempo)

    def _garantizar_parejas_iniciales(self):
        """Asegura que cada jaula tenga sus 2 cilindros trabajando al inicio si hay stock."""
        for j_id, jaula in self.jaulas.items():
            while len(jaula.cilindros_trabajando) < 2:
                # 1. Intentar desde CRC
                if jaula.cilindros_crc:
                    cil = jaula.cilindros_crc.pop(0)
                    cil.estado = EstadoCilindro.TRABAJANDO
                    cil.jaula = j_id
                    jaula.cilindros_trabajando.append(cil)
                    continue

                # 2. Intentar desde Disponible
                disponibles = sorted(self.obtener_disponibles_para_jaula(j_id), key=lambda c: c.diametro, reverse=True)
                if disponibles:
                    cil = disponibles[0]
                    cil.estado = EstadoCilindro.TRABAJANDO
                    cil.jaula = j_id
                    jaula.cilindros_trabajando.append(cil)
                    continue
                break

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
        """Obtiene cilindros disponibles que cumplen el rango de la jaula."""
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
        elif self.estrategia_seleccion == "menor_diametro":
            return min(cola, key=lambda c: c.diametro)
        # Por defecto FIFO (primer elemento de la lista)
        return cola[0]

    def generar_snapshot(self, tiempo: datetime):
        """Captura el estado actual para la posteridad (y la GUI)."""
        sn = Snapshot(tiempo)

        # Conteos globales
        for est in EstadoCilindro:
            sn.conteo_por_estado[est.value] = len(self.obtener_cilindros_por_estado(est))

        sn.cantidad_disponibles = sn.conteo_por_estado.get(EstadoCilindro.DISPONIBLE.value, 0)
        sn.cantidad_crc_total = sn.conteo_por_estado.get(EstadoCilindro.CRC.value, 0)
        sn.cantidad_bajas = sn.conteo_por_estado.get(EstadoCilindro.BAJA.value, 0)
        sn.maquinas_ocupadas = sum(1 for m in self.maquinas.values() if m.ocupada)

        # Info por Jaula
        for j_id, jaula in self.jaulas.items():
            sn.crc_por_jaula[j_id] = len(jaula.cilindros_crc)
            sn.detalle_jaulas[j_id] = [{"id": c.id, "d": c.diametro} for c in jaula.cilindros_trabajando]
            sn.detalle_crc[j_id] = [{"id": c.id, "d": c.diametro} for c in jaula.cilindros_crc]

        # Info por Máquina
        for m_nombre, maq in self.maquinas.items():
            if maq.ocupada and maq.cilindro_actual:
                c = maq.cilindro_actual
                progreso = 0.0
                if maq.tiempo_fin_rectificado and c.rectificado_inicio:
                    total = (maq.tiempo_fin_rectificado - c.rectificado_inicio).total_seconds()
                    transcurrido = (tiempo - c.rectificado_inicio).total_seconds()
                    progreso = min(100.0, max(0.0, (transcurrido / total) * 100))
                sn.detalle_maquinas[m_nombre] = {"id": c.id, "d": c.diametro, "progreso": progreso}
            else:
                sn.detalle_maquinas[m_nombre] = None

        # Info de cola de rectificado
        cola = self.obtener_cola_rectificado()
        sn.detalle_cola_rectificado = [{"id": c.id, "d": c.diametro} for c in cola]

        # Info por SubStock
        for ss in self.lista_substocks:
            conteo = {}
            for c in self.cilindros.values():
                if c.estado != EstadoCilindro.BAJA and ss.contiene_diametro(c.diametro):
                    conteo[c.estado.value] = conteo.get(c.estado.value, 0) + 1
            sn.conteo_por_substock[ss.nombre] = conteo
            sn.disponibles_por_substock[ss.nombre] = conteo.get(EstadoCilindro.DISPONIBLE.value, 0)

        self.snapshots.append(sn)

    def asignar_trabajo_maquinas(self, tiempo: datetime) -> List[tuple]:
        """Intenta asignar cilindros de la cola a máquinas libres."""
        nuevos_eventos = []
        for nombre, maq in self.maquinas.items():
            if maq.ocupada:
                continue

            cola = self.obtener_cola_rectificado()
            if not cola:
                break

            cil = self.seleccionar_siguiente_de_cola(cola)
            if cil is None:
                continue

            # Verificar si llegará a baja tras rectificar
            mm = cil.mm_a_rectificar if cil.mm_a_rectificar > 0 else 0.8
            tipo = cil.tipo_rectificado_actual if cil.tipo_rectificado_actual else maq.prioridad_defecto
            nuevo_diam = cil.diametro - mm

            if nuevo_diam < self.diametro_minimo:
                cil.estado = EstadoCilindro.BAJA
                cil.registrar_evento(tiempo, "BAJA", f"Diámetro proyectado {nuevo_diam:.2f} < {self.diametro_minimo}")
                self.alertas.append(Alerta(tiempo, "INFO", f"Cilindro {cil.id} dado de BAJA"))
                continue

            maq.iniciar_rectificado(cil, tiempo, tipo, mm)
            nuevos_eventos.append(("FIN_RECT", maq.tiempo_fin_rectificado, nombre))

        return nuevos_eventos

    def reponer_buffer_crc(self, jaula_id: int, tiempo: datetime) -> bool:
        """Intenta llenar el CRC de una jaula con cilindros disponibles."""
        jaula = self.jaulas[jaula_id]
        necesarios = 2 - len(jaula.cilindros_crc)
        if necesarios <= 0:
            return True

        disponibles = sorted(self.obtener_disponibles_para_jaula(jaula_id), key=lambda c: c.diametro, reverse=True)
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

    def simular(self, estrategia: str = "mayor_diametro", callback_log: Optional[Callable[[str], None]] = None):
        """Ejecuta la simulación completa basada en los eventos programados."""
        self.estrategia_seleccion = estrategia
        self.alertas.clear()
        self.snapshots.clear()

        def _log(msg):
            if callback_log:
                callback_log(msg)

        if not self.eventos_programados:
            _log("No hay eventos programados para simular.")
            return

        _log(f"Iniciando simulación | Estrategia: {estrategia} | Cilindros: {len(self.cilindros)}")

        # Tiempo inicial
        t_actual = self.eventos_programados[0].tiempo - timedelta(minutes=1)
        self.generar_snapshot(t_actual)

        # Cola de eventos de simulación (tipo, tiempo, datos)
        # Tipos: "CAMBIO" (evento programado), "FIN_RECT" (máquina termina)
        cola_eventos = [("CAMBIO", ev.tiempo, ev) for ev in self.eventos_programados]

        # Primeras asignaciones a máquinas
        nuevos = self.asignar_trabajo_maquinas(t_actual)
        cola_eventos.extend(nuevos)
        cola_eventos.sort(key=lambda x: x[1])

        eventos_procesados = set()
        iteracion = 0
        while cola_eventos and iteracion < 10000:
            iteracion += 1
            tipo_ev, t_ev, data = cola_eventos.pop(0)

            if tipo_ev == "FIN_RECT":
                maq_nombre = data
                maq = self.maquinas.get(maq_nombre)
                if not maq or not maq.ocupada:
                    continue
                # Verificación de seguridad de tiempo
                if maq.tiempo_fin_rectificado and abs((maq.tiempo_fin_rectificado - t_ev).total_seconds()) > 2:
                    continue

                cil_terminado = maq.finalizar_rectificado(t_ev)
                if cil_terminado:
                    # Al terminar un rectificado, intentar reponer CRC en todas las jaulas
                    for j_id in range(1, self.cantidad_jaulas + 1):
                        if len(self.jaulas[j_id].cilindros_crc) < 2:
                            self.reponer_buffer_crc(j_id, t_ev + timedelta(minutes=self.tiempo_traslado_crc_min))

                # Intentar asignar nuevo trabajo a la máquina libre
                nuevos = self.asignar_trabajo_maquinas(t_ev)
                cola_eventos.extend(nuevos)
                cola_eventos.sort(key=lambda x: x[1])
                self.generar_snapshot(t_ev)

            elif tipo_ev == "CAMBIO":
                ev = data
                if ev.id in eventos_procesados:
                    continue
                eventos_procesados.add(ev.id)
                jaula = self.jaulas[ev.jaula]

                _log(f"  {ev.tiempo.strftime('%m-%d %H:%M')} | Jaula {ev.jaula} | Cambio a {ev.tipo.value} | CRC={len(jaula.cilindros_crc)}")

                # 1. Los que estaban trabajando pasan a rectificado
                for cil in list(jaula.cilindros_trabajando):
                    cil.estado = EstadoCilindro.A_RECTIFICAR
                    cil.jaula = None
                    cil.tipo_rectificado_actual = ev.tipo
                    cil.mm_a_rectificar = ev.mm_a_rectificar
                    cil.registrar_evento(ev.tiempo, f"Retirado de Jaula {ev.jaula} para rectificado")
                jaula.cilindros_trabajando.clear()

                # 2. Subir cilindros del CRC a la Jaula
                if len(jaula.cilindros_crc) >= 2:
                    pareja = jaula.cilindros_crc[:2]
                    for cil in pareja:
                        cil.estado = EstadoCilindro.TRABAJANDO
                        cil.jaula = ev.jaula
                        jaula.cilindros_crc.remove(cil)
                        jaula.cilindros_trabajando.append(cil)
                        cil.registrar_evento(ev.tiempo, f"Instalado en Jaula {ev.jaula} (desde CRC)")
                else:
                    # Caso crítico: no hay suficiente en CRC
                    for cil in list(jaula.cilindros_crc):
                        cil.estado = EstadoCilindro.TRABAJANDO
                        cil.jaula = ev.jaula
                        jaula.cilindros_crc.remove(cil)
                        jaula.cilindros_trabajando.append(cil)
                        cil.registrar_evento(ev.tiempo, f"Instalado en Jaula {ev.jaula} (urgente)")

                    deficit = 2 - len(jaula.cilindros_trabajando)
                    if deficit > 0:
                        # Intentar sacar directo de disponibles si el CRC falló
                        disponibles = sorted(self.obtener_disponibles_para_jaula(ev.jaula), key=lambda c: c.diametro, reverse=True)
                        for cil in disponibles[:deficit]:
                            cil.estado = EstadoCilindro.TRABAJANDO
                            cil.jaula = ev.jaula
                            jaula.cilindros_trabajando.append(cil)
                            cil.registrar_evento(ev.tiempo, f"Instalado en Jaula {ev.jaula} (directo desde disponible)")
                            deficit -= 1

                    if deficit > 0:
                        self.alertas.append(Alerta(ev.tiempo, "CRITICO", f"STOCK INSUFICIENTE Jaula {ev.jaula}: faltan {deficit} cilindros", ev.jaula))
                        _log(f"  >>> ALERTA CRÍTICA: Jaula {ev.jaula} desabastecida! <<<")

                # 3. Intentar reponer el CRC tras el hueco dejado
                self.reponer_buffer_crc(ev.jaula, ev.tiempo + timedelta(minutes=self.tiempo_traslado_crc_min))

                # 4. Ver si las máquinas pueden tomar los cilindros recién bajados
                nuevos = self.asignar_trabajo_maquinas(ev.tiempo)
                cola_eventos.extend(nuevos)
                cola_eventos.sort(key=lambda x: x[1])
                self.generar_snapshot(ev.tiempo)

        # Finalizar rectificados en curso al terminar los eventos
        for _ in range(500):
            hay_actividad = False
            for maq in self.maquinas.values():
                if maq.ocupada and maq.tiempo_fin_rectificado:
                    hay_actividad = True
                    t_fin = maq.tiempo_fin_rectificado
                    maq.finalizar_rectificado(t_fin)
                    for j_id in range(1, self.cantidad_jaulas + 1):
                        if len(self.jaulas[j_id].cilindros_crc) < 2:
                            self.reponer_buffer_crc(j_id, t_fin + timedelta(minutes=self.tiempo_traslado_crc_min))
                    self.asignar_trabajo_maquinas(t_fin)
                    self.generar_snapshot(t_fin)
            if not hay_actividad:
                break

        # Snapshot final
        t_final = max(s.tiempo for s in self.snapshots) + timedelta(minutes=30) if self.snapshots else datetime.now()
        self.generar_snapshot(t_final)

        nc = sum(1 for a in self.alertas if a.tipo == "CRITICO")
        nb = len(self.obtener_cilindros_por_estado(EstadoCilindro.BAJA))
        _log(f"\nSimulación finalizada | Alertas Críticas: {nc} | Bajas: {nb}")

    def exportar_resultados(self, ruta_archivo: str):
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

        alertas_list = []
        for a in self.alertas:
            alertas_list.append({
                "Tiempo": a.tiempo,
                "Tipo": a.tipo,
                "Mensaje": a.mensaje,
                "Jaula": a.jaula if a.jaula else "-"
            })
        df_alertas = pd.DataFrame(alertas_list) if alertas_list else pd.DataFrame(columns=["Tiempo", "Tipo", "Mensaje", "Jaula"])

        with pd.ExcelWriter(ruta_archivo, engine="openpyxl") as writer:
            df_stock.to_excel(writer, sheet_name="Stock_Final", index=False)
            df_alertas.to_excel(writer, sheet_name="Alertas", index=False)
