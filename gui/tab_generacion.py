"""Pestaña «Generación de Cambios».

Concentra todo el flujo del generador sintético de ``Programa_Cambios``:

- **Configuración** del generador (movida desde la pestaña Configuración):
  algoritmo, umbral de desbaste, horizonte y régimen de turnos del laminador.
- **Adaptación**: subir historia (refit incremental o desde cero) e información
  útil del modelo aprendido y persistido.
- **Generación**: seed reproducible + botón para generar y simular.
- **Timeline** de los cambios generados, por jaula, sombreando los tramos en que
  la línea quedó PARADA (reusa ``_marcar_paradas`` del dashboard principal).

Como ``tab_config``, este widget lee/escribe ``app.user_cfg`` y opera sobre
``app.taller``; la App sigue siendo la dueña del modelo y la simulación.
"""
import customtkinter as ctk
import pandas as pd
from tkinter import filedialog, messagebox

from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter
from matplotlib.patches import Patch
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config.tema import (BG_CARD, FG, FG2, ACCENT, GREEN, RED, FONT_FAMILY,
                         FONT_SIZE, FONT_SIZE_MD, FONT_SIZE_LG, BTN_BLUE,
                         BTN_BLUE_HOVER, TIPO_RECT_COLORS)
from config.persistencia import (guardar_config, obtener_generador_cambios,
                                 obtener_turnos_cambios, set_generador_cambios,
                                 set_turnos_cambios)
from config import modelo_generador as modmod
from modelos import generador_cambios as gencambios
from modelos.generador_cambios import GENERADORES_CAMBIOS
from modelos import turnos as turnos_mod
from gui.editor_turnos import abrir_editor_turnos
from gui.dashboard_principal import _marcar_paradas

# Generadores: etiqueta visible ↔ clave persistida (la GUI muestra la etiqueta).
_GEN_ETIQUETAS = {g.etiqueta: clave for clave, g in GENERADORES_CAMBIOS.items()}
_GEN_CLAVE_A_ETIQUETA = {clave: g.etiqueta for clave, g in GENERADORES_CAMBIOS.items()}


def _card(parent, titulo, **pack_kw):
    """Tarjeta contenedora con título; devuelve el cuerpo donde apilar filas."""
    card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
    card.pack(**pack_kw)
    ctk.CTkLabel(
        card, text=titulo, anchor="w",
        font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_LG, weight="bold"),
        text_color=ACCENT,
    ).pack(fill="x", padx=16, pady=(12, 6))
    cuerpo = ctk.CTkFrame(card, fg_color="transparent")
    cuerpo.pack(fill="both", expand=True, padx=16, pady=(0, 12))
    return cuerpo


def _fila_entry(parent, etiqueta, ayuda=None, ancho=110):
    """Fila etiqueta + entry (+ ayuda opcional); devuelve el entry."""
    fila = ctk.CTkFrame(parent, fg_color="transparent")
    fila.pack(fill="x", pady=2)
    ctk.CTkLabel(fila, text=etiqueta, width=150, anchor="w", text_color=FG,
                 font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
    entry = ctk.CTkEntry(fila, width=ancho, justify="center")
    entry.pack(side="left", padx=4)
    if ayuda:
        ctk.CTkLabel(fila, text=ayuda, anchor="w", text_color=FG2,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left", padx=4)
    return entry


class TabGeneracion(ctk.CTkFrame):
    """Editor + generador + timeline del Programa_Cambios sintético."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._fig = None
        self._canvas = None
        self._turnos_holder = [None]  # estado mutable del régimen de cambios (None = 24/7)
        self._construir()
        self.refrescar()

    # ── Construcción ─────────────────────────────────────────────────────

    def _construir(self):
        # Fila superior: tres tarjetas (configuración | adaptación | generación).
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))

        cfg = _card(top, "Configuración del generador",
                    side="left", fill="both", expand=True, padx=(0, 6), anchor="n")
        fila_gen = ctk.CTkFrame(cfg, fg_color="transparent")
        fila_gen.pack(fill="x", pady=2)
        ctk.CTkLabel(fila_gen, text="Algoritmo", width=150, anchor="w", text_color=FG,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
        self._combo_generador = ctk.CTkComboBox(
            fila_gen, values=list(_GEN_ETIQUETAS.keys()), width=210, state="readonly")
        self._combo_generador.pack(side="left", padx=4)
        self._entry_umbral = _fila_entry(cfg, "Umbral desbaste", "mm")
        self._entry_horizonte = _fila_entry(cfg, "Horizonte", "días")
        fila_tc = ctk.CTkFrame(cfg, fg_color="transparent")
        fila_tc.pack(fill="x", pady=2)
        ctk.CTkLabel(fila_tc, text="Turnos (cambios)", width=150, anchor="w", text_color=FG,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
        self._btn_turnos = ctk.CTkButton(
            fila_tc, text=turnos_mod.resumen(None), width=130,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_CARD,
            command=lambda: abrir_editor_turnos(self, self._turnos_holder, self._btn_turnos))
        self._btn_turnos.pack(side="left", padx=4)
        ctk.CTkButton(cfg, text="💾 Guardar configuración", height=30,
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
                      command=self._guardar_config).pack(anchor="w", pady=(8, 0))

        adap = _card(top, "Adaptación (modelo aprendido)",
                     side="left", fill="both", expand=True, padx=6, anchor="n")
        self._chk_reiniciar = ctk.CTkCheckBox(adap, text="reiniciar adaptación (desde cero)",
                                              font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE))
        self._chk_reiniciar.pack(anchor="w", pady=(0, 4))
        ctk.CTkButton(adap, text="📈 Subir historia", height=30,
                      command=self._subir_historia).pack(fill="x", pady=2)
        self._label_modelo = ctk.CTkLabel(
            adap, text="", anchor="w", justify="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE), text_color=FG2)
        self._label_modelo.pack(anchor="w", fill="x", pady=(6, 0))

        gen = _card(top, "Generación",
                    side="left", fill="both", expand=True, padx=(6, 0), anchor="n")
        fila_seed = ctk.CTkFrame(gen, fg_color="transparent")
        fila_seed.pack(fill="x", pady=2)
        ctk.CTkLabel(fila_seed, text="Seed", width=60, anchor="w", text_color=FG,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
        self._entry_seed = ctk.CTkEntry(fila_seed, width=110, justify="center")
        self._entry_seed.pack(side="left", padx=4)
        ctk.CTkButton(gen, text="🎲 Nueva seed", height=26,
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=ACCENT, command=self._nueva_seed).pack(fill="x", pady=2)
        ctk.CTkButton(gen, text="▶ Generar cambios y simular", height=34,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD, weight="bold"),
                      fg_color=GREEN, hover_color="#2BB46B",
                      command=self._generar_cambios).pack(fill="x", pady=(4, 0))
        self._label_estado = ctk.CTkLabel(
            gen, text="", anchor="w", justify="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE), text_color=FG2)
        self._label_estado.pack(anchor="w", fill="x", pady=(6, 0))

        # Timeline (ocupa el resto del alto).
        cont = _card(self, "Timeline de cambios generados (paradas de línea en rojo)",
                     fill="both", expand=True, padx=10, pady=(4, 10))
        self._timeline_holder = cont
        self._nueva_seed()

    # ── Refresco desde la configuración ──────────────────────────────────

    def refrescar(self):
        """Carga en la UI la config del generador y el resumen del modelo."""
        cfg = self.app.user_cfg
        gc = obtener_generador_cambios(cfg)
        self._combo_generador.set(_GEN_CLAVE_A_ETIQUETA.get(
            gc["generador"], next(iter(_GEN_ETIQUETAS))))
        self._entry_umbral.delete(0, "end")
        self._entry_umbral.insert(0, f"{float(gc['umbral_desbaste_mm']):.1f}")
        self._entry_horizonte.delete(0, "end")
        self._entry_horizonte.insert(0, str(int(gc["horizonte_dias"])))
        self._turnos_holder[0] = obtener_turnos_cambios(cfg)
        self._btn_turnos.configure(text=turnos_mod.resumen(self._turnos_holder[0]))
        self._actualizar_label_modelo()

    def _actualizar_label_modelo(self):
        """Muestra información útil de la adaptación persistida."""
        m = self.app._modelo_gen
        if not m:
            self._label_modelo.configure(
                text="Sin adaptación.\nSuba una historia para entrenar el modelo.")
            return
        jaulas = m.get("jaulas", {})
        por_jaula = []
        for j in sorted(jaulas, key=int):
            mj = jaulas[j]
            # nº de campañas observadas por jaula (empírico: muestras; markov: conteos)
            n = len(mj.get("duracion", [])) if "duracion" in mj else \
                sum(len(s.get("duracion", [])) for s in mj.get("muestras", {}).values())
            por_jaula.append(f"  jaula {j}: {n} campañas")
        txt = (f"Generador: {m.get('clave')}\n"
               f"Filas acumuladas: {m.get('n_filas', 0)}\n"
               f"Período: {self._fmt_fecha(m.get('fecha_min'))} → {self._fmt_fecha(m.get('fecha_max'))}\n"
               + "\n".join(por_jaula))
        self._label_modelo.configure(text=txt)

    @staticmethod
    def _fmt_fecha(iso):
        return (iso or "—")[:10]

    # ── Acciones ─────────────────────────────────────────────────────────

    def _nueva_seed(self):
        import random
        self._entry_seed.delete(0, "end")
        self._entry_seed.insert(0, str(random.randint(0, 999999)))

    def _guardar_config(self):
        """Persiste la config del generador y la aplica en caliente."""
        try:
            generador = _GEN_ETIQUETAS.get(
                self._combo_generador.get(), next(iter(_GEN_ETIQUETAS.values())))
            umbral = float(self._entry_umbral.get().strip())
            horizonte = int(float(self._entry_horizonte.get().strip()))
            set_generador_cambios(self.app.user_cfg, generador=generador,
                                  umbral_desbaste=umbral, horizonte_dias=horizonte)
            set_turnos_cambios(self.app.user_cfg, self._turnos_holder[0])
        except (ValueError, TypeError):
            self._estado("Valores inválidos: revise umbral (mm) y horizonte (días).", error=True)
            return
        guardar_config(self.app.user_cfg)
        self.app.taller.configurar(self.app.user_cfg)
        self._estado("✓ Configuración del generador guardada.", error=False)

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
            reiniciar = bool(self._chk_reiniciar.get())
            previo = None if reiniciar else self.app._modelo_gen
            # Se ajusta con el generador configurado; si no coincide con la clave del
            # modelo previo, ajustar_modelo arranca de cero (no mezcla claves).
            clave = obtener_generador_cambios(self.app.user_cfg)["generador"]
            self.app._modelo_gen = gencambios.ajustar_modelo(
                historia, self.app.user_cfg, clave=clave, modelo_previo=previo)
            modmod.guardar_modelo(self.app._modelo_gen)
            self._actualizar_label_modelo()
            modo = "desde cero" if reiniciar else "incremental"
            self.app._log(f"Historia adaptada ({modo}): {self.app._modelo_gen['n_filas']} filas acumuladas.")
            self._estado(f"✓ Adaptación {modo} ({self.app._modelo_gen['n_filas']} filas).", error=False)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo adaptar la historia: {e}")

    def _generar_cambios(self):
        """Genera el Programa_Cambios, dibuja el timeline y dispara la simulación."""
        if self.app._stock_df is None:
            messagebox.showwarning("Atención", "Primero cargue un Excel (para el stock).")
            return
        if not self.app._modelo_gen:
            messagebox.showwarning("Atención", "No hay modelo adaptado. Suba una historia primero.")
            return
        try:
            seed = int(self._entry_seed.get().strip())
        except ValueError:
            messagebox.showwarning("Atención", "La seed debe ser un número entero.")
            return
        try:
            cambios = gencambios.generar_cambios(self.app._modelo_gen, self.app.user_cfg, seed=seed)
            self.app._cambios_generados = cambios
            self.app.taller.configurar(self.app.user_cfg)
            self.app.taller.cargar_datos_desde_dataframes(self.app._stock_df, cambios)
            for aviso in self.app.taller.avisos_carga:
                self.app._log(aviso)
            self.app._sincronizar_vista_con_taller()
            self.app._refrescar_combo_substocks()
            self.refrescar_timeline()  # timeline inmediato (sin paradas aún)
            self._estado(f"✓ {len(cambios)} cambios (seed={seed}). Simulando paradas…", error=False)
            self.app._log(f"Generados {len(cambios)} cambios (seed={seed}).")
            # La simulación (en hilo) calcula las paradas; al terminar refresca el
            # timeline vía App._simular_finalizado → refrescar_timeline().
            self.app._simular()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron generar los cambios: {e}")

    # ── Timeline ─────────────────────────────────────────────────────────

    def refrescar_timeline(self):
        """Redibuja el timeline con los cambios generados y las paradas (si hay sim)."""
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None
        if self._fig is not None:
            import matplotlib.pyplot as plt
            plt.close(self._fig)
            self._fig = None
        cambios = self.app._cambios_generados
        if cambios is None or len(cambios) == 0:
            return
        self._fig = self._construir_figura(cambios, self.app.taller)
        self._canvas = FigureCanvasTkAgg(self._fig, master=self._timeline_holder)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill="both", expand=True)

    def _construir_figura(self, cambios, taller):
        """Figura del timeline: un punto por cambio (por jaula) + paradas en rojo."""
        fig = Figure(figsize=(16, 5), facecolor="#1A1A1A")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#222222")
        ax.tick_params(colors=FG, labelsize=8)
        ax.grid(True, axis="x", alpha=0.12, color="white", linestyle="--")
        for sp in ax.spines.values():
            sp.set_color("#444")

        n_jaulas = max(taller.cantidad_jaulas, int(cambios["Jaula"].max()))
        fechas = pd.to_datetime(cambios["Fecha_Hora"])
        for tipo, color in TIPO_RECT_COLORS.items():
            mask = cambios["Tipo_Rectificado"] == tipo
            if mask.any():
                ax.scatter(fechas[mask], cambios["Jaula"][mask], s=70, color=color,
                           edgecolors="white", linewidths=0.4, zorder=3, label=tipo.capitalize())

        # Paradas de línea (si ya se simuló): reusa la lógica del dashboard.
        snaps = taller.snapshots
        if snaps:
            tiempos = [s.tiempo for s in snaps]
            _marcar_paradas(ax, tiempos, snaps)

        ax.set_yticks(range(1, n_jaulas + 1))
        ax.set_yticklabels([f"Jaula {j}" for j in range(1, n_jaulas + 1)], color=FG, fontsize=9)
        ax.set_ylim(0.5, n_jaulas + 0.5)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))
        handles, labels = ax.get_legend_handles_labels()
        if snaps and any(getattr(s, "jaulas_paradas", []) for s in snaps):
            handles.append(Patch(facecolor=RED, alpha=0.18, label="Línea parada"))
        ax.legend(handles=handles, loc="upper right", fontsize=8,
                  facecolor="#333", edgecolor="#333", labelcolor=FG)
        fig.tight_layout()
        return fig

    # ── Helpers de estado ────────────────────────────────────────────────

    def _estado(self, mensaje, error):
        self._label_estado.configure(text=mensaje, text_color=RED if error else GREEN)


def crear_tab_generacion(tab, app):
    """Crea y empaqueta la pestaña de generación. Devuelve el widget."""
    widget = TabGeneracion(tab, app)
    widget.pack(fill="both", expand=True)
    return widget
