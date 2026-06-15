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

from config.tema import *
from config.persistencia import cargar_config, guardar_config, obtener_rangos, obtener_prioridades
from modelos.taller import TallerCilindros

# Nota: Estos módulos se irán actualizando a CustomTkinter o eliminando si se integran
# de forma diferente en la nueva GUI.
from gui.tab_consola import crear_consola
from gui.vista_realtime import VistaRealTime
from gui.dashboard_principal import crear_dashboard_principal
from gui.dashboard_detalle import crear_dashboard_detalle
from gui.tab_tabla import llenar_tabla
from gui.tab_kpis import llenar_kpis
from gui.tab_config import crear_tab_configuracion

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Configuración de ventana
        self.title("Simulador de Cilindros Pro v4")
        self.geometry("1400x900")

        # Inicialización de lógica
        self.taller = TallerCilindros()
        self.user_cfg = cargar_config()
        self.taller.configurar_substocks(obtener_rangos(self.user_cfg))
        self.archivo_cargado = None

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
        self.sidebar.grid_rowconfigure(10, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar, text="SIMULADOR\nCILINDROS", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_cargar = ctk.CTkButton(self.sidebar, text="Cargar Excel", command=self._cargar)
        self.btn_cargar.grid(row=1, column=0, padx=20, pady=10)

        self.label_estrat = ctk.CTkLabel(self.sidebar, text="Estrategia:", anchor="w")
        self.label_estrat.grid(row=2, column=0, padx=20, pady=(10, 0))
        self.combo_est = ctk.CTkComboBox(self.sidebar, values=["mayor_diametro", "menor_diametro", "fifo"])
        self.combo_est.set("mayor_diametro")
        self.combo_est.grid(row=3, column=0, padx=20, pady=10)

        self.btn_simular = ctk.CTkButton(self.sidebar, text="Ejecutar Simulación", fg_color=GREEN, hover_color="#2BB46B", command=self._simular)
        self.btn_simular.grid(row=4, column=0, padx=20, pady=10)

        self.btn_exportar = ctk.CTkButton(self.sidebar, text="Exportar Resultados", command=self._exportar)
        self.btn_exportar.grid(row=5, column=0, padx=20, pady=10)

        # Controles de Reproducción
        self.repro_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.repro_frame.grid(row=6, column=0, padx=20, pady=20)

        self.btn_play = ctk.CTkButton(self.repro_frame, text="▶ Play", width=60, command=self._toggle_playback)
        self.btn_play.grid(row=0, column=0, padx=5)

        self.btn_stop = ctk.CTkButton(self.repro_frame, text="⏹", width=40, command=self._stop_playback)
        self.btn_stop.grid(row=0, column=1, padx=5)

        self.slider_progreso = ctk.CTkSlider(self.sidebar, from_=0, to=100, command=self._seek_simulation)
        self.slider_progreso.set(0)
        self.slider_progreso.grid(row=9, column=0, padx=20, pady=10)

        self.label_vel = ctk.CTkLabel(self.sidebar, text="Velocidad: 1x")
        self.label_vel.grid(row=7, column=0, padx=20, pady=0)
        self.slider_vel = ctk.CTkSlider(self.sidebar, from_=1, to=100, number_of_steps=99, command=self._change_speed)
        self.slider_vel.set(10)  # 10/10 = 1.0x
        self.slider_vel.grid(row=8, column=0, padx=20, pady=10)

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

        # Pestaña de configuración (rangos por jaula y prioridades de máquinas)
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

        # Placeholder para la vista real
        self.label_real = ctk.CTkLabel(self.tab_visual, text="Cargue un archivo y simule para ver la vista en tiempo real", font=ctk.CTkFont(size=16))
        self.label_real.pack(pady=100)

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
            self.taller.cargar_datos(fp)
            self.archivo_cargado = fp
            self.status_label.configure(text=f"Cargado: {os.path.basename(fp)}")
            self._log(f"Archivo cargado: {fp}")
            self.cfg_widget.refrescar()
            # Mostrar en Vista Real las rectificadoras y jaulas del Excel cargado
            self.taller.configurar_substocks(obtener_rangos(self.user_cfg))
            self.vista_rt.ajustar_jaulas(self.taller.cantidad_jaulas)
            self.vista_rt.mostrar_maquinas(list(self.taller.maquinas.keys()))
            self.vista_rt.set_estrategia(self.combo_est.get())
            self._refrescar_combo_substocks()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el archivo: {e}")

    def _simular(self):
        if not self.archivo_cargado:
            messagebox.showwarning("Atención", "Primero debe cargar un archivo Excel.")
            return

        self.status_label.configure(text="Simulando...")
        self.update_idletasks()

        # Resetear estado del taller cargando los datos de nuevo
        self.taller.cargar_datos(self.archivo_cargado)
        self.taller.configurar_substocks(obtener_rangos(self.user_cfg))
        prios = obtener_prioridades(self.user_cfg)
        if prios:
            self.taller.aplicar_prioridades_maquinas(prios)

        # Ejecutar simulación
        estrat = self.combo_est.get()
        self.taller.simular(estrategia=estrat, callback_log=self._log)

        self.snapshot_actual_idx = 0
        n_snaps = len(self.taller.snapshots)
        self.status_label.configure(text=f"Simulación completada. Snapshots: {n_snaps}")

        self.slider_progreso.configure(from_=0, to=max(0, n_snaps - 1))
        self.slider_progreso.set(0)

        # Reconstruir frames de jaulas y rectificadoras de la Vista Real
        self.vista_rt.ajustar_jaulas(self.taller.cantidad_jaulas)
        self.vista_rt.mostrar_maquinas(list(self.taller.maquinas.keys()))
        self.vista_rt.set_estrategia(estrat)

        # Actualizar otras pestañas
        llenar_tabla(self.tab_tabla, self.taller)
        llenar_kpis(self.tab_kpis, self.taller)

        self._refrescar_combo_substocks()
        self._render_dashboard()
        self._dash_into(self.tab_det, "analisis", crear_dashboard_detalle)
        self._log("Simulación finalizada. Use los controles de reproducción para ver los resultados.")

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
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
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
