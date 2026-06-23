"""Pestaña «Generación de Cambios».

Concentra todo el flujo del generador sintético de ``Programa_Cambios``:

- **Configuración** del generador (movida desde la pestaña Configuración):
  algoritmo, umbral de desbaste, ventana de fechas (inicio/fin) y régimen de
  turnos del laminador.
- **Adaptación**: subir historia (refit incremental o desde cero), información
  útil del modelo y un popup para elegir modelo, reajustarlo y previsualizar.
- **Generación**: seed reproducible; "Generar cambios" los deja disponibles (la
  simulación se ejecuta aparte desde el panel lateral) o se sube un Excel de cambios.
- **Timeline** de los cambios generados, por jaula, sombreando en gris los días
  sin turno (no se trabaja) y en rojo los tramos con la línea PARADA (tras simular;
  reusa ``_marcar_paradas`` del dashboard principal).

Como ``tab_config``, este widget lee/escribe ``app.user_cfg`` y opera sobre
``app.taller``; la App sigue siendo la dueña del modelo y la simulación.
"""
import statistics
import customtkinter as ctk
import pandas as pd
from datetime import timedelta
from tkinter import filedialog, messagebox

from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config.tema import (BG_CARD, FG, FG2, FG_DIM, ACCENT, GREEN, RED, FONT_FAMILY,
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
from gui.dashboard_principal import _marcar_paradas, formatter_tiempo
from gui.calendario import SelectorFecha

# Generadores: etiqueta visible ↔ clave persistida (la GUI muestra la etiqueta).
_GEN_ETIQUETAS = {g.etiqueta: clave for clave, g in GENERADORES_CAMBIOS.items()}
_GEN_CLAVE_A_ETIQUETA = {clave: g.etiqueta for clave, g in GENERADORES_CAMBIOS.items()}

# Modos del gráfico del popup de adaptación.
_MODO_HISTORIA = "Historia subida"
_MODO_COMPARA = "Generado (antes→después)"


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


def _tramos_sin_turno(grilla, t0, t1):
    """Tramos (inicio, fin) en [t0, t1) no operativos del régimen de cambios.

    Análogo a ``dashboard_principal._tramos_parada_maquina`` pero sobre la grilla
    del laminador. Devuelve [] con régimen 24/7 (``grilla is None``).
    """
    if grilla is None:
        return []
    tramos = []
    t = t0.replace(minute=0, second=0, microsecond=0)
    ini = None
    while t < t1:
        if not grilla[t.weekday()][t.hour]:
            if ini is None:
                ini = max(t, t0)
        elif ini is not None:
            tramos.append((ini, t))
            ini = None
        t += timedelta(hours=1)
    if ini is not None:
        tramos.append((ini, t1))
    return tramos


def _inicios_parada(snapshots):
    """[(tiempo, idx)] de cada transición a PARADA (inicio de un tramo parado)."""
    out, en_parada = [], False
    for k, s in enumerate(snapshots):
        f = bool(getattr(s, "jaulas_paradas", []))
        if f and not en_parada:
            out.append((s.tiempo, k))
        en_parada = f
    return out


def _fig_timeline(figsize):
    """Figura + eje con el estilo oscuro común de los timelines/comparación."""
    fig = Figure(figsize=figsize, facecolor="#1A1A1A")
    ax = fig.add_subplot(111)
    ax.set_facecolor("#222222")
    ax.tick_params(colors=FG, labelsize=8)
    ax.grid(True, axis="x", alpha=0.12, color="white", linestyle="--")
    for sp in ax.spines.values():
        sp.set_color("#444")
    return fig, ax


def _eje_jaulas(ax, n_jaulas):
    """Eje Y por jaula (1..n, invertido) común a los timelines."""
    ax.set_yticks(range(1, n_jaulas + 1))
    ax.set_yticklabels([f"Jaula {j}" for j in range(1, n_jaulas + 1)], color=FG, fontsize=9)
    ax.set_ylim(0.5, n_jaulas + 0.5)
    ax.invert_yaxis()


def _resumen_modelo(m):
    """Texto con los parámetros aprendidos de un modelo (para label y popup)."""
    if not m:
        return "Sin adaptación."
    jaulas = m.get("jaulas", {})
    por_jaula = []
    for j in sorted(jaulas, key=int):
        mj = jaulas[j]
        if "duracion" in mj:  # empírico: muestras acumuladas
            por_jaula.append(f"  jaula {j}: {len(mj['duracion'])} campañas")
        else:  # markov: estados + transiciones
            n = sum(len(s.get("duracion", [])) for s in mj.get("muestras", {}).values())
            est = len(mj.get("muestras", {}))
            trans = sum(len(d) for d in mj.get("transiciones", {}).values())
            por_jaula.append(f"  jaula {j}: {n} campañas, {est} estados, {trans} transiciones")
    fmin = (m.get("fecha_min") or "—")[:10]
    fmax = (m.get("fecha_max") or "—")[:10]
    return (f"Generador: {m.get('clave')}\n"
            f"Filas acumuladas: {m.get('n_filas', 0)}\n"
            f"Período: {fmin} → {fmax}\n" + "\n".join(por_jaula))


def _muestras_jaula(mj):
    """(duraciones, desbastes) acumulados de una jaula, sea empírico o markov."""
    if "duracion" in mj:  # empírico: muestras directas
        return list(mj.get("duracion", [])), list(mj.get("desbaste", []))
    dur, desb = [], []  # markov: acumuladas dentro de cada estado
    for s in mj.get("muestras", {}).values():
        dur.extend(s.get("duracion", []))
        desb.extend(s.get("desbaste", []))
    return dur, desb


def _parametros_modelo(m, umbral):
    """Parámetros aprendidos de un modelo como dict ordenado {nombre: valor_str}.

    Agregados **independientes del tipo de modelo** (campañas, duración y desbaste
    medios, % desbaste por jaula) para poder comparar 'antes → después' aunque el
    modelo cambie de empírico a markov.
    """
    params = {}
    if not m:
        return params
    params["Filas acumuladas"] = str(m.get("n_filas", 0))
    jaulas = m.get("jaulas", {})
    params["Jaulas con datos"] = str(len(jaulas))
    umbral = float(umbral)
    for j in sorted(jaulas, key=int):
        dur, desb = _muestras_jaula(jaulas[j])
        params[f"Jaula {j} · campañas"] = str(len(dur))
        params[f"Jaula {j} · duración media (h)"] = (
            f"{statistics.fmean(dur):.1f}" if dur else "—")
        params[f"Jaula {j} · desbaste medio (mm)"] = (
            f"{statistics.fmean(desb):.2f}" if desb else "—")
        params[f"Jaula {j} · % desbaste"] = (
            f"{100 * sum(1 for x in desb if x > umbral) / len(desb):.0f}%" if desb else "—")
    return params


def _parametros_modelo_especificos(m):
    """Parámetros **propios del tipo de modelo** que se ajustan.

    - empírico: dispersión y rango de duración/desbaste por jaula.
    - markov: nº de estados, estado inicial dominante y transición más frecuente.
    """
    params = {}
    if not m:
        return params
    jaulas = m.get("jaulas", {})
    es_markov = m.get("clave") == "markov"
    for j in sorted(jaulas, key=int):
        mj = jaulas[j]
        if es_markov or "transiciones" in mj:
            params[f"Jaula {j} · nº estados"] = str(len(mj.get("muestras", {})))
            ini = mj.get("inicial", {})
            if ini:
                tot = sum(ini.values())
                est, cnt = max(ini.items(), key=lambda kv: kv[1])
                params[f"Jaula {j} · estado inicial"] = f"{est} ({100 * cnt / tot:.0f}%)"
            mejor = None
            for src, dests in mj.get("transiciones", {}).items():
                for dst, c in dests.items():
                    if mejor is None or c > mejor[2]:
                        mejor = (src, dst, c)
            if mejor:
                params[f"Jaula {j} · transición top"] = f"{mejor[0]} → {mejor[1]}"
        else:  # empírico
            dur, desb = _muestras_jaula(mj)
            if dur:
                params[f"Jaula {j} · dur σ (h)"] = (
                    f"{statistics.pstdev(dur):.1f}" if len(dur) > 1 else "0.0")
                params[f"Jaula {j} · dur rango (h)"] = f"{min(dur):.0f}–{max(dur):.0f}"
            if desb:
                params[f"Jaula {j} · desb σ (mm)"] = (
                    f"{statistics.pstdev(desb):.2f}" if len(desb) > 1 else "0.00")
                params[f"Jaula {j} · desb rango (mm)"] = f"{min(desb):.2f}–{max(desb):.2f}"
    return params


def _parametros_completos(m, umbral):
    """Agregados + parámetros propios del modelo (para la tabla Antes→Después)."""
    return {**_parametros_modelo(m, umbral), **_parametros_modelo_especificos(m)}


def _leer_historia(fp):
    """Lee una historia desde CSV o Excel (hoja 'Historia' o la primera)."""
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp)
    xl = pd.ExcelFile(fp, engine="openpyxl")
    hoja = "Historia" if "Historia" in xl.sheet_names else xl.sheet_names[0]
    return xl.parse(hoja)


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


def _fila_fecha(parent, etiqueta):
    """Fila etiqueta + selector de fecha con calendario inline; devuelve el selector."""
    fila = ctk.CTkFrame(parent, fg_color="transparent")
    fila.pack(fill="x", pady=2)
    ctk.CTkLabel(fila, text=etiqueta, width=150, anchor="w", text_color=FG,
                 font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
    sel = SelectorFecha(fila, width=110)
    sel.pack(side="left", padx=4)
    return sel


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
                    side="left", fill="x", expand=True, padx=(0, 6), anchor="n")
        fila_gen = ctk.CTkFrame(cfg, fg_color="transparent")
        fila_gen.pack(fill="x", pady=2)
        ctk.CTkLabel(fila_gen, text="Algoritmo", width=150, anchor="w", text_color=FG,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
        self._combo_generador = ctk.CTkComboBox(
            fila_gen, values=list(_GEN_ETIQUETAS.keys()), width=210, state="readonly")
        self._combo_generador.pack(side="left", padx=4)
        self._entry_umbral = _fila_entry(cfg, "Umbral desbaste", "mm")
        self._entry_fecha_ini = _fila_fecha(cfg, "Fecha inicio")
        self._entry_fecha_fin = _fila_fecha(cfg, "Fecha fin")
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
                     side="left", fill="x", expand=True, padx=6, anchor="n")
        self._chk_reiniciar = ctk.CTkCheckBox(adap, text="reiniciar adaptación (desde cero)",
                                              font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE))
        self._chk_reiniciar.pack(anchor="w", pady=(0, 4))
        ctk.CTkButton(adap, text="📈 Subir historia", height=30,
                      command=self._subir_historia).pack(fill="x", pady=2)
        self._btn_ajustar = ctk.CTkButton(
            adap, text="🔍 Ver / ajustar adaptación", height=30, state="disabled",
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_CARD,
            command=self._abrir_popup_adaptacion)
        self._btn_ajustar.pack(fill="x", pady=2)
        self._label_modelo = ctk.CTkLabel(
            adap, text="", anchor="w", justify="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE), text_color=FG2)
        self._label_modelo.pack(anchor="w", fill="x", pady=(6, 0))

        gen = _card(top, "Generación",
                    side="left", fill="x", expand=True, padx=(6, 0), anchor="n")
        fila_seed = ctk.CTkFrame(gen, fg_color="transparent")
        fila_seed.pack(fill="x", pady=2)
        ctk.CTkLabel(fila_seed, text="Seed", width=60, anchor="w", text_color=FG,
                     font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)).pack(side="left")
        self._entry_seed = ctk.CTkEntry(fila_seed, width=110, justify="center")
        self._entry_seed.pack(side="left", padx=4)
        ctk.CTkButton(gen, text="▶ Generar cambios", height=34,
                      font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD, weight="bold"),
                      fg_color=GREEN, hover_color="#2BB46B",
                      command=self._generar_cambios).pack(fill="x", pady=(4, 2))
        # Botones secundarios al mismo nivel (misma fila).
        fila_sec = ctk.CTkFrame(gen, fg_color="transparent")
        fila_sec.pack(fill="x", pady=2)
        ctk.CTkButton(fila_sec, text="🎲 Nueva seed", height=30,
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=ACCENT, hover_color=BG_CARD,
                      command=self._nueva_seed).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(fila_sec, text="📁 Subir Excel de cambios", height=30,
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=ACCENT, hover_color=BG_CARD,
                      command=self._subir_cambios).pack(side="left", expand=True, fill="x", padx=(3, 0))
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
        self._entry_fecha_ini.delete(0, "end")
        self._entry_fecha_ini.insert(0, gc.get("fecha_inicio") or "")
        self._entry_fecha_fin.delete(0, "end")
        self._entry_fecha_fin.insert(0, gc.get("fecha_fin") or "")
        self._turnos_holder[0] = obtener_turnos_cambios(cfg)
        self._btn_turnos.configure(text=turnos_mod.resumen(self._turnos_holder[0]))
        if self.app._historia_df is not None:
            self._btn_ajustar.configure(state="normal")
        self._actualizar_label_modelo()

    def _actualizar_label_modelo(self):
        """Muestra información útil de la adaptación persistida."""
        m = self.app._modelo_gen
        if not m:
            self._label_modelo.configure(
                text="Sin adaptación.\nSuba una historia para entrenar el modelo.")
            return
        self._label_modelo.configure(text=_resumen_modelo(m))

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
            fecha_ini = self._entry_fecha_ini.get().strip()
            fecha_fin = self._entry_fecha_fin.get().strip()
            # Validar formato de fecha (si no están vacías).
            for f in (fecha_ini, fecha_fin):
                if f:
                    pd.to_datetime(f)
            set_generador_cambios(self.app.user_cfg, generador=generador,
                                  umbral_desbaste=umbral,
                                  fecha_inicio=fecha_ini, fecha_fin=fecha_fin)
            set_turnos_cambios(self.app.user_cfg, self._turnos_holder[0])
        except ValueError as e:
            self._estado(str(e), error=True)
            return
        except Exception:
            self._estado("Valores inválidos: revise umbral (mm) y fechas (YYYY-MM-DD).", error=True)
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
            historia = _leer_historia(fp)
            self.app._historia_df = historia  # se conserva para el popup de ajuste
            self._btn_ajustar.configure(state="normal")
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
            self._estado(f"✓ Adaptación {modo} ({self.app._modelo_gen['n_filas']} filas). "
                         f"Use 'Ver / ajustar' para previsualizar.", error=False)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo adaptar la historia: {e}")

    def _generar_cambios(self):
        """Genera el Programa_Cambios, lo deja disponible y dibuja el timeline.

        **No** simula: la simulación se ejecuta aparte desde el botón lateral.
        """
        if self.app._stock_df is None:
            messagebox.showwarning("Atención", "Primero cargue el stock desde la pestaña Inventario.")
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
            self._aplicar_cambios(cambios)
            self._estado(f"✓ {len(cambios)} cambios (seed={seed}). "
                         f"Ejecute la simulación desde el panel lateral.", error=False)
            self.app._log(f"Generados {len(cambios)} cambios (seed={seed}).")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron generar los cambios: {e}")

    def _subir_cambios(self):
        """Carga un Programa_Cambios desde un Excel y lo deja disponible."""
        if self.app._stock_df is None:
            messagebox.showwarning("Atención", "Primero cargue el stock desde la pestaña Inventario.")
            return
        fp = filedialog.askopenfilename(
            title="Seleccionar Excel de cambios (hoja Programa_Cambios)",
            filetypes=[("Excel", "*.xlsx *.xls")])
        if not fp:
            return
        try:
            xl = pd.ExcelFile(fp, engine="openpyxl")
            hoja = "Programa_Cambios" if "Programa_Cambios" in xl.sheet_names else xl.sheet_names[0]
            cambios = xl.parse(hoja)
            faltan = [c for c in gencambios.COLUMNAS_SALIDA if c not in cambios.columns]
            if faltan:
                raise ValueError(f"Faltan columnas en Programa_Cambios: {faltan}")
            self._aplicar_cambios(cambios[gencambios.COLUMNAS_SALIDA])
            self._estado(f"✓ {len(cambios)} cambios cargados del Excel. "
                         f"Ejecute la simulación desde el panel lateral.", error=False)
            self.app._log(f"Cambios cargados del Excel: {len(cambios)}.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el Excel de cambios: {e}")

    def _aplicar_cambios(self, cambios):
        """Deja los cambios disponibles, arma el taller con el stock y refresca el timeline."""
        self.app._cambios_generados = cambios
        self.app.taller.configurar(self.app.user_cfg)
        self.app.taller.cargar_datos_desde_dataframes(self.app._stock_df, cambios)
        for aviso in self.app.taller.avisos_carga:
            self.app._log(aviso)
        self.app._sincronizar_vista_con_taller()
        self.app._refrescar_combo_substocks()
        self.refrescar_timeline()  # sin paradas aún (no se simuló)

    # ── Popup de previsualización + ajuste del modelo ────────────────────

    def _abrir_popup_adaptacion(self):
        """Popup para elegir modelo, reajustarlo sobre la historia y previsualizar.

        Muestra **qué se está adaptando**, una tabla **Antes → Después** de los
        parámetros aprendidos (resaltando los que cambian), un botón de **ayuda**
        que explica cada distribución y un **gráfico** de los cambios previsualizados.
        """
        if self.app._historia_df is None:
            messagebox.showinfo("Adaptación", "Suba una historia primero.")
            return
        win = ctk.CTkToplevel(self)
        win.title("Ver / ajustar adaptación")
        win.configure(fg_color=BG_CARD)
        win.geometry("820x720")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        # Estado del popup: modelo temporal + figura/canvas del preview (a cerrar)
        # + caché de la conversión de la historia (constante durante el popup).
        pop = {"modelo": None, "fig": None, "canvas": None, "hist_df": None}
        umbral = float(obtener_generador_cambios(self.app.user_cfg)["umbral_desbaste_mm"])

        # ── Selector de modelo + ajustar + ayuda ─────────────────────────────
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(top, text="Modelo:", text_color=FG).pack(side="left")
        combo = ctk.CTkComboBox(top, values=list(_GEN_ETIQUETAS.keys()), width=240, state="readonly")
        combo.set(self._combo_generador.get())
        combo.pack(side="left", padx=8)
        btn_ajustar = ctk.CTkButton(top, text="Ajustar", width=90)
        btn_ajustar.pack(side="left", padx=4)
        ctk.CTkButton(top, text="ⓘ", width=32, fg_color="transparent", border_width=1,
                      border_color=ACCENT, text_color=ACCENT, hover_color=BG_CARD,
                      command=lambda: self._mostrar_ayuda_modelo(win, combo.get())).pack(side="left", padx=4)

        # Qué se está adaptando (modelo + filas de historia + período).
        lbl_que = ctk.CTkLabel(win, text="", anchor="w", justify="left", text_color=FG,
                               font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD, weight="bold"))
        lbl_que.pack(fill="x", padx=16, pady=(2, 4))

        # ── Tabla de parámetros: Antes → Después ─────────────────────────────
        ctk.CTkLabel(win, text="Parámetros aprendidos (antes → después; en verde los que cambian):",
                     anchor="w", text_color=FG2).pack(fill="x", padx=16, pady=(2, 0))
        diff_frame = ctk.CTkScrollableFrame(win, height=210, fg_color="#222222")
        diff_frame.pack(fill="x", padx=16, pady=(2, 8))

        # ── Previsualización como gráfico (historia subida ⇄ comparación) ────
        fila_modo = ctk.CTkFrame(win, fg_color="transparent")
        fila_modo.pack(fill="x", padx=16, pady=(2, 0))
        ctk.CTkLabel(fila_modo, text="Previsualización:", text_color=FG2).pack(side="left", padx=(0, 8))
        seg_modo = ctk.CTkSegmentedButton(
            fila_modo, values=[_MODO_HISTORIA, _MODO_COMPARA],
            command=lambda _v: _render_chart(seg_modo.get()))
        seg_modo.set(_MODO_HISTORIA)
        seg_modo.pack(side="left")
        chart_holder = ctk.CTkFrame(win, fg_color="transparent")
        chart_holder.pack(fill="both", expand=True, padx=16, pady=(2, 8))

        # ── Acciones ─────────────────────────────────────────────────────────
        acc = ctk.CTkFrame(win, fg_color="transparent")
        acc.pack(fill="x", padx=16, pady=(0, 14))
        btn_cerrar = ctk.CTkButton(acc, text="Cerrar", width=100, fg_color="transparent",
                                   border_width=1, border_color=FG2, text_color=FG2,
                                   hover_color=BG_CARD)
        btn_cerrar.pack(side="right", padx=4)
        btn_apply = ctk.CTkButton(acc, text="Aplicar", width=120, state="disabled",
                                  fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER)
        btn_apply.pack(side="right", padx=4)

        def _render_diff(antes, despues):
            for w in diff_frame.winfo_children():
                w.destroy()
            cab = ("Parámetro", "Antes", "Después")
            for col, txt in enumerate(cab):
                ctk.CTkLabel(diff_frame, text=txt, anchor="w", text_color=ACCENT,
                             font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold")
                             ).grid(row=0, column=col, sticky="w", padx=(0, 24), pady=(0, 2))
            claves = list(despues.keys()) + [k for k in antes if k not in despues]
            for i, k in enumerate(claves, start=1):
                a = antes.get(k, "—")
                d = despues.get(k, "—")
                cambia = a != d
                ctk.CTkLabel(diff_frame, text=k, anchor="w", text_color=FG2,
                             font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)
                             ).grid(row=i, column=0, sticky="w", padx=(0, 24))
                ctk.CTkLabel(diff_frame, text=a, anchor="w", text_color=FG_DIM,
                             font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)
                             ).grid(row=i, column=1, sticky="w", padx=(0, 24))
                ctk.CTkLabel(diff_frame, text=("→ " + d) if cambia else d, anchor="w",
                             text_color=GREEN if cambia else FG,
                             font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE,
                                              weight="bold" if cambia else "normal")
                             ).grid(row=i, column=2, sticky="w")

        def _render_chart(modo):
            if pop["canvas"] is not None:
                pop["canvas"].get_tk_widget().destroy()
                pop["canvas"] = None
            if pop["fig"] is not None:
                import matplotlib.pyplot as plt
                plt.close(pop["fig"])
                pop["fig"] = None
            for w in chart_holder.winfo_children():
                w.destroy()
            try:
                seed = int(self._entry_seed.get().strip())
            except ValueError:
                seed = 0
            try:
                if modo == _MODO_HISTORIA:
                    # Cambios de la historia subida (los que se usan para ajustar).
                    # La conversión es constante durante el popup ⇒ se cachea.
                    if pop["hist_df"] is None:
                        pop["hist_df"] = self._historia_a_cambios()
                    df = pop["hist_df"]
                    if df is None or len(df) == 0:
                        ctk.CTkLabel(chart_holder, text="(la historia no tiene fechas para graficar)",
                                     text_color=FG2).pack(pady=20)
                        return
                    pop["fig"] = self._construir_figura(df, self.app.taller, figsize=(7.6, 3.0))
                else:
                    # Comparación: generación con el modelo actual (antes) vs el temporal (después).
                    antes = (gencambios.generar_cambios(self.app._modelo_gen, self.app.user_cfg, seed=seed)
                             if self.app._modelo_gen else None)
                    despues = (gencambios.generar_cambios(pop["modelo"], self.app.user_cfg, seed=seed)
                               if pop["modelo"] else None)
                    pop["fig"] = self._figura_comparacion(antes, despues, self.app.taller, figsize=(7.6, 3.0))
            except Exception as e:
                ctk.CTkLabel(chart_holder, text=f"(no se pudo graficar: {e})",
                             text_color=FG2).pack(pady=20)
                return
            pop["canvas"] = FigureCanvasTkAgg(pop["fig"], master=chart_holder)
            pop["canvas"].draw()
            pop["canvas"].get_tk_widget().pack(fill="both", expand=True)

        def _ajustar():
            clave = _GEN_ETIQUETAS.get(combo.get(), next(iter(_GEN_ETIQUETAS.values())))
            try:
                modelo = gencambios.ajustar_modelo(self.app._historia_df, self.app.user_cfg, clave=clave)
                pop["modelo"] = modelo
                etiqueta = _GEN_CLAVE_A_ETIQUETA.get(clave, clave)
                fmin = (modelo.get("fecha_min") or "—")[:10]
                fmax = (modelo.get("fecha_max") or "—")[:10]
                lbl_que.configure(text=f"Adaptando «{etiqueta}» · {modelo.get('n_filas', 0)} "
                                       f"filas de historia · período {fmin} → {fmax}")
                _render_diff(_parametros_completos(self.app._modelo_gen, umbral),
                             _parametros_completos(modelo, umbral))
                _render_chart(seg_modo.get())
                btn_apply.configure(state="normal")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo ajustar/previsualizar: {e}", parent=win)

        def _cerrar():
            if pop["fig"] is not None:
                import matplotlib.pyplot as plt
                plt.close(pop["fig"])
            win.destroy()

        def _aplicar():
            if pop["modelo"] is None:
                return
            self.app._modelo_gen = pop["modelo"]
            modmod.guardar_modelo(pop["modelo"])
            set_generador_cambios(self.app.user_cfg, generador=pop["modelo"]["clave"])
            guardar_config(self.app.user_cfg)
            self._combo_generador.set(_GEN_CLAVE_A_ETIQUETA.get(
                pop["modelo"]["clave"], next(iter(_GEN_ETIQUETAS))))
            self._actualizar_label_modelo()
            self.app._log(f"Adaptación aplicada: modelo {pop['modelo']['clave']}.")
            _cerrar()

        btn_ajustar.configure(command=_ajustar)
        btn_apply.configure(command=_aplicar)
        btn_cerrar.configure(command=_cerrar)
        win.protocol("WM_DELETE_WINDOW", _cerrar)
        _ajustar()  # ajuste inicial con el modelo preseleccionado

    def _mostrar_ayuda_modelo(self, parent, etiqueta):
        """Muestra la ayuda del **modelo seleccionado** (no de todos)."""
        clave = _GEN_ETIQUETAS.get(etiqueta)
        g = GENERADORES_CAMBIOS.get(clave)
        if g is None:
            return
        messagebox.showinfo(f"¿Qué hace «{g.etiqueta}»?", g.descripcion, parent=parent)

    def _historia_a_cambios(self):
        """Convierte la historia subida en un DataFrame tipo Programa_Cambios.

        Reusa la normalización del generador (jaula/duración/desbaste/fecha) para
        poder graficar los cambios históricos con ``_construir_figura``.
        """
        norm = gencambios._normalizar_historia(self.app._historia_df, self.app.user_cfg)
        umbral = float(obtener_generador_cambios(self.app.user_cfg)["umbral_desbaste_mm"])
        df = pd.DataFrame({
            "Fecha_Hora": pd.to_datetime(norm["fecha_salida"]),
            "Jaula": norm["jaula"].astype(int),
            "Tipo_Rectificado": [gencambios._tipo_desde_desbaste(x, umbral) for x in norm["desbaste_mm"]],
            "mm_a_Rectificar": norm["desbaste_mm"],
        })
        return df.dropna(subset=["Fecha_Hora"])

    def _figura_comparacion(self, antes_df, despues_df, taller, figsize=(7.6, 3.0)):
        """Figura que superpone los cambios generados 'antes' (huecos) y 'después' (rellenos)."""
        fig, ax = _fig_timeline(figsize)

        presentes = [d for d in (antes_df, despues_df) if d is not None and len(d)]
        n_jaulas = taller.cantidad_jaulas
        for d in presentes:
            n_jaulas = max(n_jaulas, int(d["Jaula"].max()))

        handles = []
        if antes_df is not None and len(antes_df):
            ax.scatter(pd.to_datetime(antes_df["Fecha_Hora"]), antes_df["Jaula"], s=60,
                       facecolors="none", edgecolors=FG2, linewidths=1.0, zorder=3)
            handles.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="none",
                                  markeredgecolor=FG2, label="Antes (modelo actual)"))
        if despues_df is not None and len(despues_df):
            ax.scatter(pd.to_datetime(despues_df["Fecha_Hora"]), despues_df["Jaula"], s=45,
                       color=ACCENT, edgecolors="white", linewidths=0.4, zorder=4)
            handles.append(Line2D([0], [0], marker="o", color="none", markerfacecolor=ACCENT,
                                  markeredgecolor="white", label="Después (ajuste nuevo)"))

        _eje_jaulas(ax, n_jaulas)
        if presentes:
            fechas = pd.concat([pd.to_datetime(d["Fecha_Hora"]) for d in presentes])
            ax.xaxis.set_major_formatter(
                formatter_tiempo(fechas.min(), fechas.max() + pd.Timedelta(hours=1)))
        if handles:
            ax.legend(handles=handles, loc="upper right", fontsize=8,
                      facecolor="#333", edgecolor="#333", labelcolor=FG)
        else:
            ax.text(0.5, 0.5, "(sin cambios para comparar)", transform=ax.transAxes,
                    ha="center", va="center", color=FG2)
        fig.tight_layout()
        return fig

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
        self._fig = self._construir_figura(cambios, self.app.taller, pickable_paradas=True)
        self._canvas = FigureCanvasTkAgg(self._fig, master=self._timeline_holder)
        self._canvas.mpl_connect("pick_event", self._on_pick_parada)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill="both", expand=True)

    def _on_pick_parada(self, event):
        """Click en un marcador ▼ de parada: salta la reproducción a ese momento."""
        idx_map = getattr(self, "_parada_snap_idx", [])
        if not idx_map or not len(getattr(event, "ind", [])):
            return
        snap_idx = idx_map[event.ind[0]]
        if hasattr(self.app, "ir_a_momento"):
            self.app.ir_a_momento(snap_idx)

    def _construir_figura(self, cambios, taller, figsize=(16, 5), pickable_paradas=False):
        """Figura del timeline: un punto por cambio (por jaula) + paradas en rojo.

        Con ``pickable_paradas`` se dibujan marcadores ▼ clickeables en el inicio
        de cada parada (item "magnético"); el mapeo a índice de snapshot queda en
        ``self._parada_snap_idx`` para que ``_on_pick_parada`` salte la reproducción.
        """
        fig, ax = _fig_timeline(figsize)

        n_jaulas = max(taller.cantidad_jaulas,
                       int(cambios["Jaula"].max()) if len(cambios) else 0)
        fechas = pd.to_datetime(cambios["Fecha_Hora"])

        # Sombrear los días/tramos sin turno del laminador (no se trabaja). Se
        # dibuja primero para que quede por detrás de los puntos y las paradas.
        grilla = gencambios.grilla_cambios_desde_cfg(self.app.user_cfg)
        hay_sin_turno = False
        if grilla is not None and len(fechas):
            t0, t1 = fechas.min(), fechas.max() + pd.Timedelta(hours=1)
            for ini, fin in _tramos_sin_turno(grilla, t0, t1):
                ax.axvspan(ini, fin, color=FG2, alpha=0.13, zorder=0)
                hay_sin_turno = True

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

        # Marcadores ▼ "magnéticos" en el inicio de cada parada (clickeables).
        self._parada_snap_idx = []
        hay_marcadores = False
        if pickable_paradas and snaps:
            inicios = _inicios_parada(snaps)
            if inicios:
                self._parada_snap_idx = [idx for _, idx in inicios]
                ax.scatter([t for t, _ in inicios], [1.0] * len(inicios),
                           transform=ax.get_xaxis_transform(), marker="v", s=90,
                           color=RED, edgecolors="white", linewidths=0.5,
                           clip_on=False, zorder=6, picker=5)
                hay_marcadores = True

        _eje_jaulas(ax, n_jaulas)
        if len(fechas):
            ax.xaxis.set_major_formatter(
                formatter_tiempo(fechas.min(), fechas.max() + pd.Timedelta(hours=1)))
        handles, labels = ax.get_legend_handles_labels()
        if hay_sin_turno:
            handles.append(Patch(facecolor=FG2, alpha=0.13, label="Sin turno (no se trabaja)"))
        if snaps and any(getattr(s, "jaulas_paradas", []) for s in snaps):
            handles.append(Patch(facecolor=RED, alpha=0.18, label="Línea parada"))
        if hay_marcadores:
            handles.append(Line2D([0], [0], marker="v", color="none", markerfacecolor=RED,
                                  markeredgecolor="white", markersize=8,
                                  label="Parada (clic → ir al momento)"))
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
