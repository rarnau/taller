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
from config.persistencia import cargar_config, obtener_generador_cambios
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
from gui.tab_tabla import llenar_tabla
from gui.tab_kpis import llenar_kpis
from gui.tab_config import crear_tab_configuracion

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
        self.archivo_cargado = None

        # Generador de cambios: modelo aprendido persistido + cambios sintéticos.
        # Si _cambios_generados está activo, la simulación usa ese Programa_Cambios
        # (con el stock del Excel) en vez de la hoja Programa_Cambios del Excel.
        self._modelo_gen = modmod.cargar_modelo()
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
        self.sidebar.grid_rowconfigure(13, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar, text="SIMULADOR\nCILINDROS", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_cargar = ctk.CTkButton(self.sidebar, text="Cargar Excel", command=self._cargar)
        self.btn_cargar.grid(row=1, column=0, padx=20, pady=10)

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

        # Generador de cambios sintéticos: subir historia adapta (refit) el modelo
        # persistido; generar cambios produce un Programa_Cambios reproducible por
        # seed que se usa con el stock del Excel cargado.
        self._crear_panel_generador(row=6)

        # Hint guía cuando aún no hay datos: acompaña a los botones de acción en
        # lugar de un overlay sobre la Vista Real. Se oculta al cargar/simular.
        self.hint_inicio = ctk.CTkLabel(
            self.sidebar,
            text="Cargue un Excel y ejecute la\nsimulación para comenzar.",
            font=ctk.CTkFont(size=FONT_SIZE_SM),
            text_color=FG_DIM,
            justify="center",
        )
        self.hint_inicio.grid(row=7, column=0, padx=20, pady=(0, 10))

        # Controles de Reproducción
        self.repro_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.repro_frame.grid(row=8, column=0, padx=20, pady=20)

        self.btn_play = ctk.CTkButton(self.repro_frame, text="▶ Play", width=60, command=self._toggle_playback)
        self.btn_play.grid(row=0, column=0, padx=5)

        self.btn_stop = ctk.CTkButton(self.repro_frame, text="⏹", width=40, command=self._stop_playback)
        self.btn_stop.grid(row=0, column=1, padx=5)

        self.label_vel = ctk.CTkLabel(self.sidebar, text="Velocidad: 1x")
        self.label_vel.grid(row=9, column=0, padx=20, pady=0)
        self.slider_vel = ctk.CTkSlider(self.sidebar, from_=1, to=100, number_of_steps=99, command=self._change_speed)
        self.slider_vel.set(10)  # 10/10 = 1.0x
        self.slider_vel.grid(row=10, column=0, padx=20, pady=10)

        self.slider_progreso = ctk.CTkSlider(self.sidebar, from_=0, to=100, command=self._seek_simulation)
        self.slider_progreso.set(0)
        self.slider_progreso.grid(row=11, column=0, padx=20, pady=10)

    def _crear_panel_generador(self, row):
        """Panel del sidebar para adaptar el modelo y generar cambios sintéticos."""
        import random

        frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        frame.grid(row=row, column=0, padx=12, pady=(4, 6), sticky="ew")

        ctk.CTkLabel(frame, text="Generador de cambios", anchor="w",
                     font=ctk.CTkFont(size=FONT_SIZE_SM, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.chk_reiniciar = ctk.CTkCheckBox(frame, text="reiniciar adaptación",
                                             font=ctk.CTkFont(size=FONT_SIZE_SM))
        self.chk_reiniciar.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.btn_historia = ctk.CTkButton(frame, text="Subir historia", height=28,
                                          command=self._subir_historia)
        self.btn_historia.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)

        # Seed + botón de regeneración aleatoria.
        ctk.CTkLabel(frame, text="Seed", anchor="w",
                     font=ctk.CTkFont(size=FONT_SIZE_SM)).grid(row=3, column=0, sticky="w")
        self.entry_seed = ctk.CTkEntry(frame, width=90, justify="center")
        self.entry_seed.insert(0, str(random.randint(0, 999999)))
        self.entry_seed.grid(row=3, column=1, sticky="e", pady=2)
        self.btn_seed = ctk.CTkButton(
            frame, text="🎲 Nueva seed", height=24,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, command=self._nueva_seed)
        self.btn_seed.grid(row=4, column=0, columnspan=2, sticky="ew", pady=2)

        self.btn_generar = ctk.CTkButton(frame, text="Generar cambios", height=28,
                                         fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
                                         command=self._generar_cambios)
        self.btn_generar.grid(row=5, column=0, columnspan=2, sticky="ew", pady=2)

        self.label_modelo = ctk.CTkLabel(
            frame, text="", anchor="w", justify="left",
            font=ctk.CTkFont(size=FONT_SIZE_SM), text_color=FG_DIM)
        self.label_modelo.grid(row=6, column=0, columnspan=2, sticky="w", pady=(2, 0))
        frame.grid_columnconfigure(0, weight=1)
        self._actualizar_label_modelo()

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
        self.tab_cfg = self.tabview.add("Configuración")
        self.tab_log = self.tabview.add("Consola")

        # Pestaña de configuración (globales + máquinas + rangos + sim, CRUD completo)
        self.cfg_widget = crear_tab_configuracion(self.tab_cfg, self)

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

    def _create_status_bar(self):
        self.status_bar = ctk.CTkFrame(self, height=25, corner_radius=0)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_label = ctk.CTkLabel(self.status_bar, text="Listo", font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=20)

    def _log(self, m):
        if hasattr(self, 'log_w'):
            self.log_w.insert("end", m + "\n")
            self.log_w.see("end")

    def _cargar(self):
        fp = filedialog.askopenfilename(title="Seleccionar Excel de Datos", filetypes=[("Excel", "*.xlsx *.xls")])
        if not fp: return
        try:
            # configurar() (globales + máquinas + rangos + sim) debe ir antes de
            # cargar_datos(): el stock necesita la cantidad de jaulas y el mínimo.
            self.taller.configurar(self.user_cfg)
            self.taller.cargar_datos(fp)
            self.archivo_cargado = fp
            # Guardar el stock para el generador y descartar cambios sintéticos
            # de una corrida previa (este Excel trae su propio Programa_Cambios).
            self._stock_df = pd.read_excel(fp, sheet_name="Stock_Inicial")
            self._cambios_generados = None
            self.status_label.configure(text=f"Cargado: {os.path.basename(fp)}")
            self._log(f"Archivo cargado: {fp}")
            for aviso in self.taller.avisos_carga:
                self._log(aviso)
            self.cfg_widget.refrescar()
            self._sincronizar_vista_con_taller()
            self._refrescar_combo_substocks()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el archivo: {e}")

    # ── Generador de cambios sintéticos ──────────────────────────────────────

    def _nueva_seed(self):
        import random
        self.entry_seed.delete(0, "end")
        self.entry_seed.insert(0, str(random.randint(0, 999999)))

    def _actualizar_label_modelo(self):
        """Refresca el resumen del modelo persistido (filas, jaulas, generador)."""
        m = self._modelo_gen
        if not m:
            txt = "Sin adaptación: suba historia."
        else:
            jaulas = ", ".join(sorted(m.get("jaulas", {}), key=int)) or "-"
            txt = (f"Modelo {m.get('clave')}: {m.get('n_filas', 0)} filas\n"
                   f"jaulas {jaulas}")
        self.label_modelo.configure(text=txt)

    def _subir_historia(self):
        """Carga un histórico y adapta (refit o desde cero) el modelo persistido."""
        fp = filedialog.askopenfilename(
            title="Seleccionar historia (CSV o Excel)",
            filetypes=[("Datos", "*.csv *.xlsx *.xls")])
        if not fp:
            return
        try:
            if fp.lower().endswith(".csv"):
                historia = pd.read_csv(fp)
            else:
                xl = pd.ExcelFile(fp, engine="openpyxl")
                hoja = "Historia" if "Historia" in xl.sheet_names else xl.sheet_names[0]
                historia = xl.parse(hoja)
            reiniciar = bool(self.chk_reiniciar.get())
            previo = None if reiniciar else self._modelo_gen
            # Se ajusta con el generador configurado; si no coincide con la clave
            # del modelo previo, ajustar_modelo arranca de cero (no mezcla claves).
            clave = obtener_generador_cambios(self.user_cfg)["generador"]
            self._modelo_gen = gencambios.ajustar_modelo(
                historia, self.user_cfg, clave=clave, modelo_previo=previo)
            modmod.guardar_modelo(self._modelo_gen)
            self._actualizar_label_modelo()
            modo = "desde cero" if reiniciar else "incremental"
            self._log(f"Historia adaptada ({modo}): {self._modelo_gen['n_filas']} filas acumuladas.")
            self.status_label.configure(text=f"Modelo adaptado ({modo}).")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo adaptar la historia: {e}")

    def _generar_cambios(self):
        """Genera un Programa_Cambios reproducible y arma el taller con el stock cargado."""
        if self._stock_df is None:
            messagebox.showwarning("Atención", "Primero cargue un Excel (para el stock).")
            return
        if not self._modelo_gen:
            messagebox.showwarning("Atención", "No hay modelo adaptado. Suba una historia primero.")
            return
        try:
            seed = int(self.entry_seed.get().strip())
        except ValueError:
            messagebox.showwarning("Atención", "La seed debe ser un número entero.")
            return
        try:
            cambios = gencambios.generar_cambios(self._modelo_gen, self.user_cfg, seed=seed)
            self._cambios_generados = cambios
            self.taller.configurar(self.user_cfg)
            self.taller.cargar_datos_desde_dataframes(self._stock_df, cambios)
            for aviso in self.taller.avisos_carga:
                self._log(aviso)
            self._sincronizar_vista_con_taller()
            self._refrescar_combo_substocks()
            self._log(f"Generados {len(cambios)} cambios (seed={seed}). Ejecute la simulación.")
            self.status_label.configure(text=f"Cambios generados (seed={seed}): {len(cambios)}.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron generar los cambios: {e}")

    def _simular(self):
        if not self.archivo_cargado and self._cambios_generados is None:
            messagebox.showwarning("Atención", "Primero debe cargar un archivo Excel.")
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
            # rangos + sim) antes de recargar los datos. Si hay un Programa_Cambios
            # sintético activo, se usa con el stock del Excel; si no, el Excel completo.
            self.taller.configurar(self.user_cfg)
            if self._cambios_generados is not None:
                self.taller.cargar_datos_desde_dataframes(self._stock_df, self._cambios_generados)
            else:
                self.taller.cargar_datos(self.archivo_cargado)
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

        # Actualizar otras pestañas
        llenar_tabla(self.tab_tabla, self.taller)
        llenar_kpis(self.tab_kpis, self.taller)

        self._refrescar_combo_substocks()
        self._render_dashboard()
        self._dash_into(self.tab_det, "analisis", crear_dashboard_detalle)
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
        """Renderiza el dashboard principal aplicando el filtro de SubStock seleccionado."""
        if not self.taller.snapshots:
            return
        sel = self.combo_dash_ss.get()
        substock = None if sel == "Global" else sel
        self._dash_into(self.dash_holder, "dashboard",
                        lambda t: crear_dashboard_principal(t, substock=substock))

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

    def _change_speed(self, value):
        self.velocidad_reproduccion = float(value) / 10.0
        self.label_vel.configure(text=f"Velocidad: {self.velocidad_reproduccion:.1f}x")

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
