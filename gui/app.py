"""
Ventana principal mejorada con CustomTkinter.
"""
import os
import threading
import time
import customtkinter as ctk
from tkinter import filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import pandas as pd

from config.tema import *
from config.persistencia import cargar_config
from config import modelo_generador as modmod
from modelos.estrategias import ESTRATEGIAS_SELECCION
from modelos import generador_cambios as gencambios
from modelos.taller import TallerCilindros

# Cada pestaña es un componente de display puro; App es el único que conoce
# tanto el modelo (TallerCilindros) como la UI y los conecta.
from gui.tab_consola import crear_consola
from gui.vista_realtime import VistaRealTime
from gui.dashboard_principal import crear_dashboard_principal
from gui.dashboard_detalle import crear_dashboard_detalle
from gui.tab_tabla import crear_tab_inventario
from gui.tab_kpis import llenar_kpis
from gui.tab_config import crear_tab_configuracion
from gui.tab_generacion import crear_tab_generacion

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Evita el crash de CustomTkinter al mover la ventana entre monitores con
# distinto factor de escala (DPI): el re-escalado automático intenta reconfigurar
# el dropdown de los CTkComboBox ya destruidos y lanza un TclError
# ("invalid command name ...dropdownmenu"). Desactivarlo mantiene una escala fija
# y elimina ese callback problemático. Debe ejecutarse antes de crear la ventana.
ctk.deactivate_automatic_dpi_awareness()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configuración de ventana
        self.title("Simulador de Cilindros Pro v4")
        self.geometry("1400x900")

        # Inicialización de lógica
        self.taller = TallerCilindros()
        self.user_cfg = cargar_config()
        # La configuración estructural (globales + máquinas + rangos + sim) vive
        # en el JSON y se aplica con un único configurar(); el Excel solo aporta
        # datos. configurar() debe ir antes de cualquier cargar_datos().
        self.taller.configurar(self.user_cfg)

        # Flujo desacoplado: el stock se carga desde la pestaña Inventario
        # (``_stock_df``) y los cambios se generan/suben desde la pestaña
        # Generación (``_cambios_generados``); la simulación combina ambos.
        self._modelo_gen = modmod.cargar_modelo()
        self._historia_df = None      # última historia subida (para el popup de ajuste)
        self._stock_df = None
        self._cambios_generados = None

        # Estado de reproducción
        self.reproduciendo = False
        self.snapshot_actual_idx = 0
        self.velocidad_reproduccion = 1.0

        self._figs: dict = {}  # {tab_name: Figure} — para cerrar figuras al regenerar

        self._setup_grid()
        self._create_sidebar()
        self._create_main_content()
        self._create_status_bar()

    def _setup_grid(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def _create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(11, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar, text="SIMULADOR\nCILINDROS", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # El stock se carga desde la pestaña Inventario y los cambios desde
        # Generación; el sidebar solo dispara la simulación y exporta.
        self.label_estrat = ctk.CTkLabel(self.sidebar, text="Estrategia de rectificado:", anchor="w")
        self.label_estrat.grid(row=2, column=0, padx=20, pady=(10, 0))
        # El combo muestra etiquetas legibles; se mapean a la clave de estrategia
        # que espera el motor. Ambas se derivan del registro ESTRATEGIAS_SELECCION.
        self._estrat_por_etiqueta = {e.etiqueta: clave for clave, e in ESTRATEGIAS_SELECCION.items()}
        self.combo_est = ctk.CTkComboBox(self.sidebar, values=list(self._estrat_por_etiqueta.keys()))
        self.combo_est.set(ESTRATEGIAS_SELECCION["mayor_diametro"].etiqueta)
        self.combo_est.grid(row=3, column=0, padx=20, pady=10)

        self.btn_simular = ctk.CTkButton(self.sidebar, text="Ejecutar Simulación", fg_color=GREEN, hover_color="#2BB46B", command=self._simular)
        self.btn_simular.grid(row=4, column=0, padx=20, pady=10)

        self.btn_exportar = ctk.CTkButton(self.sidebar, text="Exportar Resultados", command=self._exportar)
        self.btn_exportar.grid(row=5, column=0, padx=20, pady=10)

        # Hint guía cuando aún no hay datos: acompaña a los botones de acción en
        # lugar de un overlay sobre la Vista Real. Se oculta al cargar/simular.
        self.hint_inicio = ctk.CTkLabel(
            self.sidebar,
            text="Cargue el stock en Inventario,\ngenere/suba los cambios en\nGeneración y ejecute la simulación.",
            font=ctk.CTkFont(size=FONT_SIZE_SM),
            text_color=FG_DIM,
            justify="center",
        )
        self.hint_inicio.grid(row=6, column=0, padx=20, pady=(0, 10))

        # Controles de Reproducción: paso atrás / play / stop / paso adelante.
        self.repro_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.repro_frame.grid(row=7, column=0, padx=20, pady=(20, 4))

        self.btn_paso_atras = ctk.CTkButton(self.repro_frame, text="⏪", width=40,
                                            command=lambda: self._paso(-1))
        self.btn_paso_atras.grid(row=0, column=0, padx=3)
        self.btn_play = ctk.CTkButton(self.repro_frame, text="▶ Play", width=64,
                                      command=self._toggle_playback)
        self.btn_play.grid(row=0, column=1, padx=3)
        self.btn_stop = ctk.CTkButton(self.repro_frame, text="⏹", width=40, command=self._stop_playback)
        self.btn_stop.grid(row=0, column=2, padx=3)
        self.btn_paso_adelante = ctk.CTkButton(self.repro_frame, text="⏩", width=40,
                                               command=lambda: self._paso(1))
        self.btn_paso_adelante.grid(row=0, column=3, padx=3)

        # Velocidad: botones discretos (1× 2× 5× 10×) en vez de una barra.
        self.vel_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.vel_frame.grid(row=8, column=0, padx=20, pady=(4, 4))
        ctk.CTkLabel(self.vel_frame, text="Velocidad:").grid(row=0, column=0, padx=(0, 6))
        self._btns_vel = {}
        for i, v in enumerate((1, 2, 5, 10)):
            b = ctk.CTkButton(self.vel_frame, text=f"{v}×", width=40,
                              command=lambda vv=v: self._set_velocidad(vv))
            b.grid(row=0, column=i + 1, padx=2)
            self._btns_vel[v] = b
        self._set_velocidad(1)

        self.slider_progreso = ctk.CTkSlider(self.sidebar, from_=0, to=100, command=self._seek_simulation)
        self.slider_progreso.set(0)
        self.slider_progreso.grid(row=9, column=0, padx=20, pady=10)

    def _create_main_content(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=(10, 10), pady=(0, 10), sticky="nsew")

        self.tab_visual = self.tabview.add("Vista Real")
        self.vista_rt = VistaRealTime(self.tab_visual, on_cilindro_click=self._mostrar_detalle_cilindro)
        self.vista_rt.pack(fill="both", expand=True)

        self.tab_dash = self.tabview.add("Dashboard")
        self.tab_det = self.tabview.add("Análisis")
        self.tab_tabla = self.tabview.add("Inventario")
        self.tab_kpis = self.tabview.add("KPIs")
        self.tab_gen = self.tabview.add("Generación de Cambios")
        self.tab_cfg = self.tabview.add("Configuración")
        self.tab_log = self.tabview.add("Consola")

        # Pestaña de inventario (carga de stock + vista inicial/final + descarga)
        self.inv_widget = crear_tab_inventario(self.tab_tabla, self)

        # Pestaña de configuración (globales + máquinas + rangos + sim, CRUD completo)
        self.cfg_widget = crear_tab_configuracion(self.tab_cfg, self)

        # Pestaña de generación de cambios (config del generador + adaptación + timeline)
        self.gen_widget = crear_tab_generacion(self.tab_gen, self)

        # Dashboard: barra de control con selector de SubStock para la evolución temporal
        self.dash_ctrl = ctk.CTkFrame(self.tab_dash, fg_color="transparent")
        self.dash_ctrl.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(self.dash_ctrl, text="Evolución temporal:").pack(side="left", padx=(0, 8))
        self.combo_dash_ss = ctk.CTkComboBox(
            self.dash_ctrl, values=["Global"], width=220, state="readonly",
            command=lambda _v: self._render_dashboard()
        )
        self.combo_dash_ss.set("Global")
        self.combo_dash_ss.pack(side="left")
        self.dash_holder = ctk.CTkFrame(self.tab_dash, fg_color="transparent")
        self.dash_holder.pack(fill="both", expand=True)

        # Consola
        self.log_w = crear_consola(self.tab_log)
        self._log("Bienvenido al Simulador v4 Pro")

        # Preview inicial: Dashboard/Análisis/KPIs con todo en 0 y gráficos vacíos
        # más el banner "Se mostrarán datos una vez corrida la simulación".
        self._render_paneles()

    def _create_status_bar(self):
        self.status_bar = ctk.CTkFrame(self, height=25, corner_radius=0)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_label = ctk.CTkLabel(self.status_bar, text="Listo", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=20)

    def _log(self, m):
        if hasattr(self, 'log_w'):
            self.log_w.insert("end", m + "\n")
            self.log_w.see("end")

    def cargar_stock_desde(self, fp):
        """Carga **solo el stock** (hoja Stock_Inicial) desde un Excel.

        Llamado por la pestaña Inventario. Arma el taller con el stock y un
        Programa_Cambios vacío (los cambios llegan luego desde Generación), y
        descarta cualquier cambio sintético de una corrida previa.
        """
        try:
            # configurar() (globales + máquinas + rangos + sim) debe ir antes de
            # cargar_datos_*(): el stock necesita la cantidad de jaulas y el mínimo.
            self.taller.configurar(self.user_cfg)
            stock_df = pd.read_excel(fp, sheet_name="Stock_Inicial")
            cambios_vacios = pd.DataFrame(columns=gencambios.COLUMNAS_SALIDA)
            self.taller.cargar_datos_desde_dataframes(stock_df, cambios_vacios)
            self._stock_df = stock_df
            self._cambios_generados = None
            self.status_label.configure(text=f"Stock cargado: {os.path.basename(fp)}")
            self._log(f"Stock cargado: {fp}")
            for aviso in self.taller.avisos_carga:
                self._log(aviso)
            self.cfg_widget.refrescar()
            self._sincronizar_vista_con_taller()
            self._refrescar_combo_substocks()
            self._render_paneles()
            # Stock nuevo ⇒ se descartan los cambios: limpiar el timeline.
            if getattr(self, "gen_widget", None) is not None:
                self.gen_widget.refrescar_timeline()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el stock: {e}")

    def _simular(self):
        if self._stock_df is None:
            messagebox.showwarning("Atención", "Primero cargue el stock desde la pestaña Inventario.")
            return
        if getattr(self, "_simulando", False):
            return

        # La carga del Excel y la simulación corren en un hilo aparte para no
        # bloquear el event loop de Tkinter (la ventana se congelaba mientras
        # tanto). Los logs y la actualización de la UI se marshalan al hilo de
        # Tk con self.after(); el taller solo se lee desde la UI una vez que el
        # hilo termina (en _simular_finalizado).
        # Al simular, el aviso "Configuración guardada..." ya no aplica: borrarlo.
        if getattr(self, "cfg_widget", None) is not None:
            self.cfg_widget._limpiar_feedback()

        self._simulando = True
        self.btn_simular.configure(state="disabled")
        self.status_label.configure(text="Simulando...")
        self.update_idletasks()

        estrat = self._estrat_por_etiqueta.get(self.combo_est.get(), "mayor_diametro")
        threading.Thread(target=self._simular_worker, args=(estrat,), daemon=True).start()

    def _simular_worker(self, estrat):
        """Corre carga + simulación fuera del hilo de Tk (no toca widgets)."""
        try:
            # Resetear estado del taller: configurar() (globales + máquinas +
            # rangos + sim) antes de recargar los datos. Se combina el stock
            # (Inventario) con los cambios (Generación); si no hay cambios, se
            # simula con un Programa_Cambios vacío.
            self.taller.configurar(self.user_cfg)
            cambios = self._cambios_generados
            if cambios is None:
                cambios = pd.DataFrame(columns=gencambios.COLUMNAS_SALIDA)
            self.taller.cargar_datos_desde_dataframes(self._stock_df, cambios)
            self.taller.simular(estrategia=estrat, callback_log=self._log_async)
        except Exception as e:
            self.after(0, lambda err=e: self._simular_error(err))
            return
        self.after(0, self._simular_finalizado)

    def _log_async(self, m):
        """Callback de log seguro para hilos: difiere el insert al hilo de Tk."""
        self.after(0, lambda: self._log(m))

    def _simular_error(self, e):
        self._simulando = False
        self.btn_simular.configure(state="normal")
        self.status_label.configure(text="Error en la simulación")
        messagebox.showerror("Error", f"No se pudo ejecutar la simulación: {e}")

    def _simular_finalizado(self):
        self.snapshot_actual_idx = 0
        n_snaps = len(self.taller.snapshots)
        self.status_label.configure(text=f"Simulación completada. Snapshots: {n_snaps}")

        self.slider_progreso.configure(from_=0, to=max(0, n_snaps - 1))
        self.slider_progreso.set(0)

        # Reconstruir frames de jaulas y rectificadoras de la Vista Real
        self._sincronizar_vista_con_taller()

        # Actualizar otras pestañas (Inventario: ya hay "Stock final")
        self.inv_widget.refrescar()
        self._refrescar_combo_substocks()
        self._render_paneles()
        # El timeline ya puede sombrear las paradas calculadas por la simulación.
        if getattr(self, "gen_widget", None) is not None:
            self.gen_widget.refrescar_timeline()
        self._log("Simulación finalizada. Use los controles de reproducción para ver los resultados.")

        self.btn_simular.configure(state="normal")
        self._simulando = False

    def _sincronizar_vista_con_taller(self) -> None:
        """Actualiza los frames de Vista Real con las jaulas y máquinas del taller cargado."""
        self.hint_inicio.grid_remove()  # ya hay datos: ocultar el hint guía del sidebar
        estrat = self._estrat_por_etiqueta.get(self.combo_est.get(), "mayor_diametro")
        self.vista_rt.ajustar_jaulas(self.taller.cantidad_jaulas)
        self.vista_rt.mostrar_maquinas(list(self.taller.maquinas.keys()))
        self.vista_rt.set_estrategia(estrat)

        # Gráfico de stock Disponible por jaula: mapa jaula→SubStock y escala
        # (máximo de disponibles sobre todo el run, para normalizar las barras).
        mapa = {j: ss.nombre
                for j in range(1, self.taller.cantidad_jaulas + 1)
                if (ss := self.taller.obtener_substock_por_jaula(j)) is not None}
        escala = max((v for sn in self.taller.snapshots
                      for v in sn.disponibles_por_substock.values()), default=0)
        self.vista_rt.configurar_disponibilidad(mapa, escala)

    def _refrescar_combo_substocks(self):
        """Actualiza las opciones del selector de SubStock del Dashboard."""
        nombres = [ss.nombre for ss in self.taller.lista_substocks]
        valores = ["Global"] + nombres
        self.combo_dash_ss.configure(values=valores)
        if self.combo_dash_ss.get() not in valores:
            self.combo_dash_ss.set("Global")

    def _render_dashboard(self):
        """Renderiza el dashboard principal aplicando el filtro de SubStock seleccionado.

        Sin snapshots dibuja un preview vacío con banner (no retorna en blanco).
        """
        sel = self.combo_dash_ss.get()
        substock = None if sel == "Global" else sel
        self._dash_into(self.dash_holder, "dashboard",
                        lambda t: crear_dashboard_principal(t, substock=substock))

    def _render_analisis(self):
        """Renderiza la pestaña Análisis (preview vacío + banner si aún no se simuló)."""
        self._dash_into(self.tab_det, "analisis", crear_dashboard_detalle)

    def _render_paneles(self):
        """Refresca Dashboard, Análisis y KPIs (preview pre-simulación incluido)."""
        self._render_dashboard()
        self._render_analisis()
        llenar_kpis(self.tab_kpis, self.taller)

    def _dash_into(self, container, key, func):
        # Cerrar figura anterior para liberar memoria
        if key in self._figs:
            plt.close(self._figs[key])
        for w in container.winfo_children():
            w.destroy()
        fig = func(self.taller)
        self._figs[key] = fig
        cv = FigureCanvasTkAgg(fig, master=container)
        cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True)

    def _toggle_playback(self):
        if not self.taller.snapshots:
            messagebox.showwarning("Atención", "Debe simular antes de reproducir.")
            return

        if self.reproduciendo:
            self.reproduciendo = False
            self.btn_play.configure(text="▶ Play")
        else:
            self.reproduciendo = True
            self.btn_play.configure(text="⏸ Pause")
            self._playback_tick()

    def _stop_playback(self):
        self.reproduciendo = False
        self.snapshot_actual_idx = 0
        self.slider_progreso.set(0)
        self.btn_play.configure(text="▶ Play")
        self._update_realtime_view()

    def _seek_simulation(self, value):
        self.snapshot_actual_idx = int(value)
        self._update_realtime_view()

    def _playback_tick(self):
        if not self.reproduciendo:
            return

        if self.snapshot_actual_idx < len(self.taller.snapshots):
            self._update_realtime_view()
            self.snapshot_actual_idx += 1
            ms = int(1000 / self.velocidad_reproduccion)
            self.after(ms, self._playback_tick)
        else:
            self.reproduciendo = False
            self.btn_play.configure(text="▶ Play")

    def _update_realtime_view(self):
        if self.snapshot_actual_idx < len(self.taller.snapshots):
            snap = self.taller.snapshots[self.snapshot_actual_idx]
            self.status_label.configure(text=f"Simulación: {snap.tiempo.strftime('%Y-%m-%d %H:%M')} ({self.snapshot_actual_idx + 1}/{len(self.taller.snapshots)})")
            self.slider_progreso.set(self.snapshot_actual_idx)
            self.vista_rt.actualizar(snap)

    def _mostrar_detalle_cilindro(self, id_cilindro):
        cil = self.taller.cilindros.get(id_cilindro)
        if cil:
            msg = f"ID: {cil.id}\nDiámetro: {cil.diametro} mm\nEstado: {cil.estado.value}\n"
            if cil.jaula: msg += f"Jaula: {cil.jaula}\n"
            msg += f"\nHistorial ({len(cil.historial)} eventos)"
            messagebox.showinfo(f"Detalle Cilindro {id_cilindro}", msg)

    def _set_velocidad(self, v):
        """Fija la velocidad de reproducción y resalta el botón activo."""
        self.velocidad_reproduccion = float(v)
        for vv, b in self._btns_vel.items():
            activo = vv == v
            b.configure(fg_color=BTN_BLUE if activo else "transparent",
                        border_width=0 if activo else 1, border_color=ACCENT,
                        text_color="white" if activo else ACCENT,
                        hover_color=BTN_BLUE_HOVER if activo else BG_CARD)

    def _paso(self, delta):
        """Avanza/retrocede un snapshot (pausa la reproducción)."""
        if not self.taller.snapshots:
            return
        self.reproduciendo = False
        self.btn_play.configure(text="▶ Play")
        n = len(self.taller.snapshots)
        self.snapshot_actual_idx = max(0, min(n - 1, self.snapshot_actual_idx + delta))
        self._update_realtime_view()

    def ir_a_momento(self, idx):
        """Salta la reproducción al snapshot ``idx`` y muestra la Vista Real.

        Lo usa el timeline de Generación al clickear un marcador de parada.
        """
        if not self.taller.snapshots:
            return
        n = len(self.taller.snapshots)
        self.reproduciendo = False
        self.btn_play.configure(text="▶ Play")
        self.snapshot_actual_idx = max(0, min(n - 1, int(idx)))
        self._update_realtime_view()
        self.tabview.set("Vista Real")

    def _exportar(self):
        if not self.taller.snapshots:
            messagebox.showwarning("Atención", "Primero debe ejecutar la simulación.")
            return
        fp = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile="resultados_simulacion.xlsx")
        if fp:
            self.taller.exportar_resultados(fp)
            messagebox.showinfo("Éxito", f"Resultados exportados a:\n{fp}")

if __name__ == "__main__":
    app = App()
    app.mainloop()
