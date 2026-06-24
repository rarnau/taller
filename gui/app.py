"""
Ventana principal mejorada con CustomTkinter.
"""
import os
from concurrent.futures import ProcessPoolExecutor
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import pandas as pd

from config.tema import *
from config.persistencia import cargar_config, obtener_estrategia_seleccion
from config import modelo_generador as modmod
from config.iconos import ATRAS, STOP, ADELANTE, PLAY, PAUSE
from modelos import generador_cambios as gencambios
from modelos.taller import TallerCilindros
from cli import (init_worker_simulacion, simular_cambios_worker, ctx_paralelo)

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
from gui.tab_generacion import _inicios_parada
from gui.mpl_zoom import conectar_zoom
from gui.dpi import factor_escala_dpi
from gui.animaciones import fade_in

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Evita el crash de CustomTkinter al mover la ventana entre monitores con
# distinto factor de escala (DPI): el re-escalado automático intenta reconfigurar
# el dropdown de los CTkComboBox ya destruidos y lanza un TclError
# ("invalid command name ...dropdownmenu"). Desactivarlo mantiene una escala fija
# y elimina ese callback problemático. Debe ejecutarse antes de crear la ventana.
ctk.deactivate_automatic_dpi_awareness()

# Otro crash conocido de CustomTkinter: un widget puede recibir un <Configure>
# que ya estaba en la cola de Tk *después* de ser destruido. En ese punto su
# `_canvas` es None y `_update_dimensions_event` -> `_draw` revienta con
# "AttributeError: 'NoneType' object has no attribute 'winfo_exists'". Se da, por
# ejemplo, al cerrar/recrear el panel inline de filtro del inventario (que lleva
# un CTkScrollableFrame) mientras la ventana se reajusta. Envolvemos el handler
# para que sea no-op cuando el widget ya no tiene canvas. Debe aplicarse una sola
# vez, antes de crear la ventana.
try:
    from customtkinter.windows.widgets.core_widget_classes.ctk_base_class import \
        CTkBaseClass as _CTkBaseClass

    _orig_update_dimensions_event = _CTkBaseClass._update_dimensions_event

    def _safe_update_dimensions_event(self, event):
        if getattr(self, "_canvas", None) is None:
            return
        return _orig_update_dimensions_event(self, event)

    _CTkBaseClass._update_dimensions_event = _safe_update_dimensions_event
except Exception:  # noqa: BLE001 — si CTk cambia su layout interno, seguimos sin el guard
    pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Escala automática en alta DPI. El rescalado por-monitor de CTk está
        # desactivado (deactivate_automatic_dpi_awareness, arriba) para evitar el
        # crash del dropdown; en su lugar aplicamos UNA escala fija derivada del
        # DPI de la pantalla. Con DPI estándar (96) el factor es 1.0 (idéntico al
        # comportamiento previo); en pantallas densas agranda widgets y ventana.
        # Se hace antes de geometry() para que el tamaño contemple la escala.
        try:
            factor = factor_escala_dpi(self.winfo_fpixels("1i"))
            if abs(factor - 1.0) > 0.01:
                ctk.set_widget_scaling(factor)
                ctk.set_window_scaling(factor)
        except Exception:  # noqa: BLE001 — si la detección falla, seguimos a escala 1
            pass

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
        self._dash_firmas: dict = {}  # {tab_name: firma} — caché para no redibujar sin cambios
        self._paneles_pendientes: set = set()  # paneles pesados a renderizar al visitarlos (lazy)

        self._setup_grid()
        self._create_sidebar()
        self._create_main_content()
        self._create_status_bar()
        self._crear_atajos()

        # Aparición suave de la ventana principal (fade-in de opacidad). No-op si
        # el sistema no soporta -alpha (p. ej. X11 sin compositor).
        fade_in(self)

    def _crear_atajos(self):
        """Atajos de teclado globales: Ctrl+S guardar config, Ctrl+L cargar
        stock, Ctrl+R ejecutar simulación. ``bind_all`` para que funcionen sin
        importar qué widget tenga el foco."""
        self.bind_all("<Control-s>", lambda _e: self._atajo_guardar_config())
        self.bind_all("<Control-l>", lambda _e: self._atajo_cargar_stock())
        self.bind_all("<Control-r>", lambda _e: self._atajo_simular())

    def _atajo_guardar_config(self):
        """Ctrl+S: guarda la configuración y muestra la pestaña para ver el resultado."""
        if getattr(self, "cfg_widget", None) is not None:
            self.tabview.set("Configuración")
            self.cfg_widget._guardar()
        return "break"

    def _atajo_cargar_stock(self):
        """Ctrl+L: abre el diálogo de carga de stock (pestaña Inventario)."""
        if getattr(self, "inv_widget", None) is not None:
            self.tabview.set("Inventario")
            self.inv_widget._cargar_stock()
        return "break"

    def _atajo_simular(self):
        """Ctrl+R: ejecuta la simulación (respeta las precondiciones de _simular)."""
        if not getattr(self, "_simulando", False):
            self._simular()
        return "break"

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
        # Generación; el sidebar solo dispara la simulación y exporta. La
        # estrategia de rectificado vive ahora en la pestaña Configuración
        # (persistida en user_config.json) y se lee desde allí al simular.
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

        self.btn_paso_atras = ctk.CTkButton(self.repro_frame, text=ATRAS, width=40,
                                            command=lambda: self._paso(-1))
        self.btn_paso_atras.grid(row=0, column=0, padx=3)
        self.btn_play = ctk.CTkButton(self.repro_frame, text=f"{PLAY} Play", width=64,
                                      command=self._toggle_playback)
        self.btn_play.grid(row=0, column=1, padx=3)
        self.btn_stop = ctk.CTkButton(self.repro_frame, text=STOP, width=40, command=self._stop_playback)
        self.btn_stop.grid(row=0, column=2, padx=3)
        self.btn_paso_adelante = ctk.CTkButton(self.repro_frame, text=ADELANTE, width=40,
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

        # Marcadores de parada: una franja fina sobre el slider con un punto por
        # cada inicio de PARADA; al clickear salta la reproducción a ese momento.
        bg_sidebar = self.sidebar._apply_appearance_mode(self.sidebar.cget("fg_color"))
        self.parada_canvas = tk.Canvas(self.sidebar, height=9, highlightthickness=0,
                                       bg=bg_sidebar)
        self.parada_canvas.grid(row=9, column=0, padx=20, pady=(6, 0), sticky="ew")
        self.parada_canvas.bind("<Button-1>", self._click_parada_canvas)
        self.parada_canvas.bind("<Configure>", lambda _e: self._redibujar_paradas_sidebar())
        self._paradas_sidebar: list = []  # [(idx, x_px)] de los marcadores dibujados

        # sticky="ew" para que el slider ocupe el mismo ancho que la franja de
        # marcadores (mismo padx) y los puntos de parada queden alineados con él.
        # height/button_length reducidos: barra temporal un poco más compacta.
        self.slider_progreso = ctk.CTkSlider(self.sidebar, from_=0, to=100, height=12,
                                              button_length=6, command=self._seek_simulation)
        self.slider_progreso.set(0)
        self.slider_progreso.grid(row=10, column=0, padx=20, pady=(0, 8), sticky="ew")

    def _create_main_content(self):
        # command: al cambiar de pestaña se renderiza (lazy) el panel pesado
        # recién visible si quedó pendiente (ver _render_tab_visible).
        self.tabview = ctk.CTkTabview(self, command=self._render_tab_visible)
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

        # Estrellas iniciales en las pestañas que requieren acción del usuario.
        self.actualizar_indicadores_tabs()

    def _marcar_tab(self, nombre: str, incompleto: bool):
        """Agrega/quita un indicador ★ en la pestaña ``nombre`` (sin cambiar su clave).

        Accede al botón del segmented button de CTkTabview (API privada): si la
        estructura cambia en una versión futura, degrada a no-op (como los guards DPI).
        """
        try:
            btn = self.tabview._segmented_button._buttons_dict[nombre]
        except Exception:
            return
        # Captura del color de texto por defecto la primera vez (antes de pintarlo
        # de rojo), para poder restaurarlo al volver a "completo" sin quedar rojo.
        if not hasattr(self, "_tab_text_color_def"):
            self._tab_text_color_def = {}
        if nombre not in self._tab_text_color_def:
            try:
                self._tab_text_color_def[nombre] = btn.cget("text_color")
            except Exception:
                self._tab_text_color_def[nombre] = None
        texto = f"{nombre}  ★" if incompleto else nombre
        color = RED if incompleto else self._tab_text_color_def.get(nombre)
        try:
            if color is not None:
                btn.configure(text=texto, text_color=color)
            else:
                btn.configure(text=texto)
        except Exception:
            try:
                btn.configure(text=texto)
            except Exception:
                pass

    def actualizar_indicadores_tabs(self):
        """Marca como incompletas las pestañas que requieren acción del usuario."""
        from config.persistencia import problemas_coherencia
        self._marcar_tab("Inventario", self._stock_df is None)
        self._marcar_tab("Generación de Cambios", self._cambios_generados is None)
        self._marcar_tab("Configuración", bool(problemas_coherencia(self.user_cfg)))
        # Mismo fan-out: refrescar el estado (habilitado/deshabilitado) de los
        # botones de acción cada vez que cambia el estado de los datos.
        self._actualizar_estado_botones()

    def _actualizar_estado_botones(self):
        """Habilita/deshabilita los botones de acción según las precondiciones.

        'Ejecutar Simulación' requiere stock + cambios cargados y que no haya una
        corrida en curso; 'Exportar Resultados' requiere snapshots de una
        simulación previa. Evita que el usuario dispare acciones sin sentido.
        """
        if not hasattr(self, "btn_simular"):
            return
        simulando = getattr(self, "_simulando", False)
        puede_simular = (self._stock_df is not None
                         and self._cambios_generados is not None
                         and not simulando)
        self.btn_simular.configure(state="normal" if puede_simular else "disabled")
        hay_snaps = bool(getattr(self.taller, "snapshots", None))
        self.btn_exportar.configure(state="normal" if hay_snaps else "disabled")

    def _create_status_bar(self):
        self.status_bar = ctk.CTkFrame(self, height=25, corner_radius=0)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_label = ctk.CTkLabel(self.status_bar, text="Listo", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=20)
        # Barra de progreso indeterminada de la simulación (oculta salvo al simular).
        self.progress_sim = ctk.CTkProgressBar(self.status_bar, width=180, mode="indeterminate")
        self.progress_sim.pack(side="right", padx=20)
        self.progress_sim.pack_forget()

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
            self.actualizar_indicadores_tabs()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el stock: {e}")

    def _simular(self):
        if self._stock_df is None:
            messagebox.showwarning("Atención", "Primero cargue el stock desde la pestaña Inventario.")
            return
        if getattr(self, "_simulando", False):
            return

        # La simulación es CPU-bound en Python puro: un hilo no basta (el GIL
        # congelaba la ventana). Se corre en un PROCESO aparte
        # (ProcessPoolExecutor) y se sondea el future con self.after(); la GUI
        # queda fluida y muestra una barra de progreso indeterminada. El taller
        # resultante viaja de vuelta por pickle y reemplaza a self.taller.
        # Al simular, el aviso "Configuración guardada..." ya no aplica: borrarlo.
        if getattr(self, "cfg_widget", None) is not None:
            self.cfg_widget._limpiar_feedback()

        self._simulando = True
        self._actualizar_estado_botones()  # deshabilita 'Ejecutar' durante la corrida
        self.status_label.configure(text="Simulando...")
        self._mostrar_progreso(True)

        estrat = obtener_estrategia_seleccion(self.user_cfg)
        cambios = self._cambios_generados
        if cambios is None:
            cambios = pd.DataFrame(columns=gencambios.COLUMNAS_SALIDA)

        # Mismo camino que el runner paralelo del CLI (cli.batch_simular): el
        # stock+config+estrategia se cargan una vez por worker con un initializer
        # y la tarea solo manda el cambios_df. Acá es 1 worker (una corrida), pero
        # queda listo para reusar el patrón en simulaciones en paralelo. El
        # contexto 'fork' (cuando existe) evita re-importar/re-ejecutar módulos.
        self._sim_executor = ProcessPoolExecutor(
            max_workers=1, mp_context=ctx_paralelo(),
            initializer=init_worker_simulacion,
            initargs=(self.user_cfg, self._stock_df, estrat))
        self._sim_future = self._sim_executor.submit(simular_cambios_worker, cambios)
        self.after(100, self._poll_simulacion)

    def _poll_simulacion(self):
        """Sondea el proceso de simulación sin bloquear el event loop de Tk."""
        fut = getattr(self, "_sim_future", None)
        if fut is None:
            return
        if not fut.done():
            self.after(100, self._poll_simulacion)
            return
        self._sim_executor.shutdown(wait=False)
        self._sim_future = None
        try:
            taller = fut.result()
        except Exception as e:
            self._simular_error(e)
            return
        # Reemplazar el taller local por el resultado del proceso hijo.
        self.taller = taller
        self._simular_finalizado()

    def _mostrar_progreso(self, activo):
        """Muestra/oculta la barra de progreso indeterminada de la simulación."""
        if activo:
            self.progress_sim.pack(side="right", padx=20)
            self.progress_sim.start()
        else:
            self.progress_sim.stop()
            self.progress_sim.pack_forget()

    def _simular_error(self, e):
        self._simulando = False
        self._mostrar_progreso(False)
        self._actualizar_estado_botones()
        self.status_label.configure(text="Error en la simulación")
        messagebox.showerror("Error", f"No se pudo ejecutar la simulación: {e}")

    def _simular_finalizado(self):
        self._mostrar_progreso(False)
        self.snapshot_actual_idx = 0
        n_snaps = len(self.taller.snapshots)
        self.status_label.configure(text=f"Simulación completada. Snapshots: {n_snaps}")

        # El proceso hijo no transmite logs en vivo: se vuelcan ahora los avisos
        # de carga y el log de la simulación (cambios, paradas, bajas…) que el
        # taller acumuló durante la corrida y viajó de vuelta por pickle.
        for aviso in self.taller.avisos_carga:
            self._log(aviso)
        for linea in self.taller.log_simulacion:
            self._log(linea)

        self.slider_progreso.configure(from_=0, to=max(0, n_snaps - 1))
        self.slider_progreso.set(0)

        # Reconstruir frames de jaulas y rectificadoras de la Vista Real
        self._sincronizar_vista_con_taller()

        # Actualizar otras pestañas (Inventario: ya hay "Stock final")
        self.inv_widget.refrescar()
        self._refrescar_combo_substocks()
        self._render_paneles()
        self._redibujar_paradas_sidebar()
        # El timeline ya puede sombrear las paradas calculadas por la simulación.
        if getattr(self, "gen_widget", None) is not None:
            self.gen_widget.refrescar_timeline()
        self._log("Simulación finalizada. Use los controles de reproducción para ver los resultados.")

        # Marcar la corrida como terminada ANTES del fan-out, para que
        # _actualizar_estado_botones rehabilite 'Ejecutar' (no la ve en curso).
        self._simulando = False
        self.actualizar_indicadores_tabs()

    def _redibujar_paradas_sidebar(self):
        """Dibuja un punto por cada inicio de PARADA sobre el slider del sidebar."""
        cv = getattr(self, "parada_canvas", None)
        if cv is None:
            return
        cv.delete("all")
        self._paradas_sidebar = []
        snaps = self.taller.snapshots
        n = len(snaps)
        if n < 2:
            return
        ancho = cv.winfo_width()
        if ancho <= 1:  # aún sin layout: reintentar cuando haya ancho
            self.after(60, self._redibujar_paradas_sidebar)
            return
        for _t, idx in _inicios_parada(snaps):
            x = (idx / (n - 1)) * (ancho - 1)
            cv.create_polygon(x - 3, 1, x + 3, 1, x, 7, fill=RED, outline=RED_DARK)
            self._paradas_sidebar.append((idx, x))

    def _click_parada_canvas(self, event):
        """Salta la reproducción al marcador de parada más cercano al click."""
        if not self._paradas_sidebar:
            return
        idx, _x = min(self._paradas_sidebar, key=lambda p: abs(p[1] - event.x))
        self.ir_a_momento(idx)

    def _sincronizar_vista_con_taller(self) -> None:
        """Actualiza los frames de Vista Real con las jaulas y máquinas del taller cargado."""
        self.hint_inicio.grid_remove()  # ya hay datos: ocultar el hint guía del sidebar
        estrat = obtener_estrategia_seleccion(self.user_cfg)
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
                        lambda t: crear_dashboard_principal(t, substock=substock),
                        firma=self._firma_datos(substock))

    def _render_analisis(self):
        """Renderiza la pestaña Análisis (preview vacío + banner si aún no se simuló)."""
        self._dash_into(self.tab_det, "analisis", crear_dashboard_detalle,
                        firma=self._firma_datos())

    def _firma_datos(self, *extra):
        """Firma de los datos que alimentan un gráfico (para cachear el render).

        ``(id(taller), nº snapshots, *extra)`` captura toda diferencia *visible*:
        el taller cambia de identidad al simular (vuelve por pickle), y el nº de
        snapshots distingue cargar stock (0) de un resultado (N). ``extra`` agrega
        parámetros propios del gráfico (p. ej. el SubStock seleccionado).
        """
        return (id(self.taller), len(self.taller.snapshots)) + extra

    def _render_paneles(self):
        """Marca los paneles pesados como pendientes y refresca solo el visible.

        Lazy load: Dashboard/Análisis/KPIs no se renderizan hasta que el usuario
        visita su pestaña (o si ya está visible). Al cambiar de pestaña,
        ``_render_tab_visible`` (command del CTkTabview) renderiza el pendiente.
        """
        self._paneles_pendientes = {"Dashboard", "Análisis", "KPIs"}
        self._render_tab_visible()

    def _render_tab_visible(self):
        """Renderiza el panel de la pestaña activa si quedó pendiente (lazy load)."""
        try:
            actual = self.tabview.get()
        except Exception:
            return
        if actual not in getattr(self, "_paneles_pendientes", set()):
            return
        if actual == "Dashboard":
            self._render_dashboard()
        elif actual == "Análisis":
            self._render_analisis()
        elif actual == "KPIs":
            llenar_kpis(self.tab_kpis, self.taller)
        self._paneles_pendientes.discard(actual)

    def _dash_into(self, container, key, func, firma=None):
        # Caché por firma: si los datos no cambiaron y el canvas sigue vivo, no se
        # reconstruye la figura (evita redibujar el dashboard sin necesidad).
        if (firma is not None and self._dash_firmas.get(key) == firma
                and key in self._figs and container.winfo_children()):
            return
        # Cerrar figura anterior para liberar memoria
        if key in self._figs:
            plt.close(self._figs[key])
        for w in container.winfo_children():
            w.destroy()
        fig = func(self.taller)
        self._figs[key] = fig
        self._dash_firmas[key] = firma
        cv = FigureCanvasTkAgg(fig, master=container)
        cv.draw()
        conectar_zoom(cv)
        cv.get_tk_widget().pack(fill="both", expand=True)

    def _toggle_playback(self):
        if not self.taller.snapshots:
            messagebox.showwarning("Atención", "Debe simular antes de reproducir.")
            return

        if self.reproduciendo:
            self.reproduciendo = False
            self.btn_play.configure(text=f"{PLAY} Play")
        else:
            self.reproduciendo = True
            self.btn_play.configure(text=f"{PAUSE} Pause")
            self._playback_tick()

    def _stop_playback(self):
        self.reproduciendo = False
        self.snapshot_actual_idx = 0
        self.slider_progreso.set(0)
        self.btn_play.configure(text=f"{PLAY} Play")
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
            self.btn_play.configure(text=f"{PLAY} Play")

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
        self.btn_play.configure(text=f"{PLAY} Play")
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
        self.btn_play.configure(text=f"{PLAY} Play")
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
