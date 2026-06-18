"""Pestaña de Configuración: edición de la configuración persistente del taller.

Edita y persiste (en ``config/user_config.json``) toda la configuración
estructural: parámetros globales, parque de máquinas (CRUD completo), rangos de
SubStock por jaula y parámetros de simulación. El Excel cargado solo aporta
datos (stock + cambios), por lo que esta pantalla es la fuente de verdad de la
configuración.
"""
import customtkinter as ctk

from config.tema import (
    BG_CARD, FG, FG2, ACCENT, GREEN, RED, FONT_FAMILY,
    FONT_SIZE, FONT_SIZE_MD, FONT_SIZE_LG, BTN_BLUE, BTN_BLUE_HOVER,
)
from config.persistencia import (
    guardar_config, obtener_rangos, obtener_maquinas, obtener_config_global,
    obtener_tiempo_enfriado, obtener_max_iteraciones,
)
from modelos.enums import TipoRectificado
from modelos import turnos as turnos_mod

_TIPOS_RECT = [t.value for t in TipoRectificado]


def _card(parent, titulo, subtitulo=None):
    """Crea una tarjeta contenedora con título y subtítulo opcional."""
    card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
    card.pack(fill="x", padx=4, pady=(0, 16))

    ctk.CTkLabel(
        card, text=titulo, anchor="w",
        font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_LG, weight="bold"),
        text_color=ACCENT,
    ).pack(fill="x", padx=20, pady=(16, 0))

    if subtitulo:
        ctk.CTkLabel(
            card, text=subtitulo, anchor="w", justify="left",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
            text_color=FG2,
        ).pack(fill="x", padx=20, pady=(2, 8))

    cuerpo = ctk.CTkFrame(card, fg_color="transparent")
    cuerpo.pack(fill="x", padx=20, pady=(4, 18))
    return cuerpo


def _fila_param(parent, etiqueta, ayuda=None, ancho_entry=120):
    """Crea una fila etiqueta + entry (+ ayuda opcional) y devuelve el entry."""
    fila = ctk.CTkFrame(parent, fg_color="transparent")
    fila.pack(fill="x", pady=3)
    ctk.CTkLabel(
        fila, text=etiqueta, width=220, anchor="w", text_color=FG,
        font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
    ).pack(side="left", padx=4)
    entry = ctk.CTkEntry(fila, width=ancho_entry, justify="center")
    entry.pack(side="left", padx=4)
    if ayuda:
        ctk.CTkLabel(
            fila, text=ayuda, anchor="w", text_color=FG2,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
        ).pack(side="left", padx=4)
    return entry


class TabConfiguracion(ctk.CTkScrollableFrame):
    """Editor de la configuración persistente del taller."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._filas_rangos = []      # [(e_jaula, e_min, e_max, frame_fila)]
        self._filas_maquinas = []    # [(e_nom, e_pmm, e_pmin, e_dmm, e_dmin, combo_prio, turnos_holder, frame_fila)]
        self._cont_rangos = None
        self._cont_maquinas = None
        # Entries de parámetros globales
        self._e_diam_max = None
        self._e_diam_min = None
        self._e_crc = None
        self._e_jaulas = None
        # Entries de parámetros de simulación
        self._entry_enfriado = None
        self._entry_max_iter = None
        self._label_estado = None
        self._feedback_after = None   # id del timer que borra el feedback transitorio

        self._construir()
        self.refrescar()

    # ── Construcción de la UI ────────────────────────────────────────────

    def _construir(self):
        # Dos columnas: izquierda → globales + rangos; derecha → máquinas + sim.
        # El reparto es responsive: en pantallas anchas van lado a lado; en
        # estrechas se apilan a ancho completo (ver _aplicar_layout) para que la
        # tabla de máquinas no recorte la columna "Prioridad".
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="both", expand=True)

        self._col_izq = ctk.CTkFrame(cols, fg_color="transparent")
        self._col_der = ctk.CTkFrame(cols, fg_color="transparent")
        self._layout_mode = None
        self._aplicar_layout("ancho")  # layout inicial; <Configure> lo ajusta
        # Escuchamos el resize en el frame interno (no en el CTkScrollableFrame):
        # bindear <Configure> sobre self pisaría el binding interno de CTk que
        # recalcula la scrollregion y rompería el scroll vertical.
        cols.bind("<Configure>", self._on_resize)
        col_izq, col_der = self._col_izq, self._col_der

        # Sección 1: Parámetros globales del taller (columna izquierda)
        cuerpo_g = _card(
            col_izq,
            "Parámetros Globales del Taller",
            "Rango de diámetro útil, traslado al CRC y cantidad de jaulas.",
        )
        self._e_diam_max = _fila_param(cuerpo_g, "Diámetro máximo (mm)")
        self._e_diam_min = _fila_param(cuerpo_g, "Diámetro mínimo (mm)", "bajo este, el cilindro es BAJA")
        self._e_crc = _fila_param(cuerpo_g, "Traslado Disponible→CRC (min)")
        self._e_jaulas = _fila_param(cuerpo_g, "Cantidad de jaulas")

        # Sección 2: Rangos de SubStock por jaula (columna izquierda)
        cuerpo_r = _card(
            col_izq,
            "Rangos de SubStock por Jaula",
            "Cada jaula admite cilindros cuyo diámetro cumpla  Desde (mín) < diámetro ≤ Hasta (máx).",
        )

        cab = ctk.CTkFrame(cuerpo_r, fg_color="transparent")
        cab.pack(fill="x", pady=(0, 6))
        for txt, w in [("Jaula", 70), ("Desde (mín, mm)", 140), ("Hasta (máx, mm)", 140), ("", 40)]:
            ctk.CTkLabel(
                cab, text=txt, width=w, anchor="w",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold"),
                text_color=FG2,
            ).pack(side="left", padx=4)

        self._cont_rangos = ctk.CTkFrame(cuerpo_r, fg_color="transparent")
        self._cont_rangos.pack(fill="x")

        ctk.CTkButton(
            cuerpo_r, text="+ Agregar jaula", width=140, height=30,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_CARD,
            command=self._agregar_fila_rango,
        ).pack(anchor="w", pady=(10, 0))

        # Sección 3: Máquinas (CRUD completo, columna derecha)
        cuerpo_m = _card(
            col_der,
            "Máquinas Rectificadoras",
            "Tasas por tipo (mm removidos y minutos), prioridad y esquema de turnos.",
        )

        cab_m = ctk.CTkFrame(cuerpo_m, fg_color="transparent")
        cab_m.pack(fill="x", pady=(0, 6))
        for txt, w in [("Nombre", 84), ("Prod mm", 58), ("Prod min", 58),
                       ("Desb mm", 58), ("Desb min", 58), ("Prioridad", 110),
                       ("Turnos", 96), ("", 36)]:
            ctk.CTkLabel(
                cab_m, text=txt, width=w, anchor="w",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold"),
                text_color=FG2,
            ).pack(side="left", padx=2)

        self._cont_maquinas = ctk.CTkFrame(cuerpo_m, fg_color="transparent")
        self._cont_maquinas.pack(fill="x")

        ctk.CTkButton(
            cuerpo_m, text="+ Agregar máquina", width=160, height=30,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_CARD,
            command=self._agregar_fila_maquina,
        ).pack(anchor="w", pady=(10, 0))

        # Sección 4: Parámetros de simulación (columna derecha)
        cuerpo_p = _card(
            col_der,
            "Parámetros de Simulación",
            "Tiempo de enfriado tras retirar un cilindro y tope de iteraciones del motor.",
        )
        self._entry_enfriado = _fila_param(cuerpo_p, "Tiempo de enfriado (h)", "0 = sin enfriado")
        self._entry_max_iter = _fila_param(cuerpo_p, "Máximo de iteraciones")

        # Footer: guardar + estado
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=4, pady=(4, 20))

        ctk.CTkButton(
            footer, text="💾  Guardar configuración", height=40, width=220,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD, weight="bold"),
            fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
            command=self._guardar,
        ).pack(side="left")

        self._label_estado = ctk.CTkLabel(
            footer, text="", anchor="w",
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        )
        self._label_estado.pack(side="left", padx=16)

    # ── Layout responsive ────────────────────────────────────────────────

    # Ancho (px) por debajo del cual las dos columnas se apilan a ancho completo.
    # Dos columnas lado a lado necesitan ~1300 px para que la tabla de máquinas
    # (incluida la columna "Prioridad") quepa sin recortarse.
    _UMBRAL_APILADO = 1300

    def _on_resize(self, event=None):
        # event.width es el ancho del frame interno (≈ viewport visible).
        ancho = event.width if event is not None else self.winfo_width()
        modo = "ancho" if ancho >= self._UMBRAL_APILADO else "estrecho"
        if modo != self._layout_mode:
            self._aplicar_layout(modo)

    def _aplicar_layout(self, modo):
        """Reparte las dos columnas lado a lado ('ancho') o apiladas ('estrecho')."""
        self._layout_mode = modo
        self._col_izq.pack_forget()
        self._col_der.pack_forget()
        if modo == "ancho":
            self._col_izq.pack(side="left", fill="both", expand=True, padx=(0, 8), anchor="n")
            self._col_der.pack(side="left", fill="both", expand=True, padx=(8, 0), anchor="n")
        else:
            self._col_izq.pack(side="top", fill="x", anchor="n")
            self._col_der.pack(side="top", fill="x", anchor="n", pady=(16, 0))

    # ── Filas de rangos ──────────────────────────────────────────────────

    def _agregar_fila_rango(self, jaula="", minimo="", maximo=""):
        """Crea fila: Jaula | Desde (mín) | Hasta (máx).

        ``minimo`` es el límite inferior (interno: ``hasta``),
        ``maximo`` es el límite superior (interno: ``desde``).
        """
        fila = ctk.CTkFrame(self._cont_rangos, fg_color="transparent")
        fila.pack(fill="x", pady=3)

        e_jaula = ctk.CTkEntry(fila, width=70, justify="center")
        e_jaula.insert(0, str(jaula))
        e_jaula.pack(side="left", padx=4)

        e_min = ctk.CTkEntry(fila, width=140, justify="center")
        e_min.insert(0, str(minimo))
        e_min.pack(side="left", padx=4)

        e_max = ctk.CTkEntry(fila, width=140, justify="center")
        e_max.insert(0, str(maximo))
        e_max.pack(side="left", padx=4)

        # e_min = hasta (lower bound), e_max = desde (upper bound) internamente
        registro = (e_jaula, e_min, e_max, fila)

        ctk.CTkButton(
            fila, text="🗑", width=40, fg_color="transparent",
            text_color=RED, hover_color=BG_CARD,
            command=lambda: self._quitar_fila_rango(registro),
        ).pack(side="left", padx=4)

        self._filas_rangos.append(registro)

    def _quitar_fila_rango(self, registro):
        registro[3].destroy()
        self._filas_rangos.remove(registro)

    # ── Filas de máquinas ────────────────────────────────────────────────

    def _agregar_fila_maquina(self, nombre="", prod_mm="", prod_min="",
                              desb_mm="", desb_min="", prioridad=_TIPOS_RECT[0],
                              turnos=None):
        fila = ctk.CTkFrame(self._cont_maquinas, fg_color="transparent")
        fila.pack(fill="x", pady=3)

        def _entry(width, valor):
            e = ctk.CTkEntry(fila, width=width, justify="center")
            e.insert(0, str(valor))
            e.pack(side="left", padx=2)
            return e

        e_nom = _entry(84, nombre)
        e_pmm = _entry(58, prod_mm)
        e_pmin = _entry(58, prod_min)
        e_dmm = _entry(58, desb_mm)
        e_dmin = _entry(58, desb_min)

        combo = ctk.CTkComboBox(fila, values=_TIPOS_RECT, width=110, state="readonly")
        combo.set(prioridad if prioridad in _TIPOS_RECT else _TIPOS_RECT[0])
        combo.pack(side="left", padx=2)

        # Estado mutable del esquema de turnos de la fila (None = 24/7).
        turnos_holder = [turnos]
        btn_turnos = ctk.CTkButton(
            fila, text=turnos_mod.resumen(turnos), width=96,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_CARD,
        )
        btn_turnos.pack(side="left", padx=2)
        btn_turnos.configure(
            command=lambda: self._abrir_editor_turnos(turnos_holder, btn_turnos))

        registro = (e_nom, e_pmm, e_pmin, e_dmm, e_dmin, combo, turnos_holder, fila)

        ctk.CTkButton(
            fila, text="🗑", width=36, fg_color="transparent",
            text_color=RED, hover_color=BG_CARD,
            command=lambda: self._quitar_fila_maquina(registro),
        ).pack(side="left", padx=2)

        self._filas_maquinas.append(registro)

    def _quitar_fila_maquina(self, registro):
        registro[-1].destroy()
        self._filas_maquinas.remove(registro)

    def _abrir_editor_turnos(self, turnos_holder, btn_turnos):
        """Abre un popup con la grilla 7 días × 3 turnos y presets."""
        win = ctk.CTkToplevel(self)
        win.title("Esquema de turnos")
        win.configure(fg_color=BG_CARD)
        win.transient(self.winfo_toplevel())
        win.grab_set()

        t_actual = turnos_mod.normalizar(turnos_holder[0])
        # vars[dia][turno] = BooleanVar
        variables = {d: [ctk.BooleanVar(value=t_actual[d][i]) for i in range(turnos_mod.NUM_TURNOS)]
                     for d in turnos_mod.DIAS}

        ctk.CTkLabel(
            win, text="Marque los turnos operativos por día (T3 22–06 cubre la madrugada siguiente).",
            text_color=FG2, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
        ).grid(row=0, column=0, columnspan=4, padx=16, pady=(14, 8), sticky="w")

        for c, etiqueta in enumerate(turnos_mod.TURNO_LABELS):
            ctk.CTkLabel(
                win, text=etiqueta, text_color=FG2,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold"),
            ).grid(row=1, column=c + 1, padx=8, pady=2)

        for r, dia in enumerate(turnos_mod.DIAS):
            ctk.CTkLabel(
                win, text=turnos_mod.DIAS_NOMBRES[r], width=90, anchor="w", text_color=FG,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
            ).grid(row=r + 2, column=0, padx=(16, 8), pady=2, sticky="w")
            for c in range(turnos_mod.NUM_TURNOS):
                ctk.CTkCheckBox(win, text="", variable=variables[dia][c], width=24).grid(
                    row=r + 2, column=c + 1, padx=8, pady=2)

        def _aplicar_preset(clave):
            preset = turnos_mod.PRESETS[clave]
            for d in turnos_mod.DIAS:
                for i in range(turnos_mod.NUM_TURNOS):
                    variables[d][i].set(preset[d][i])

        presets_fila = ctk.CTkFrame(win, fg_color="transparent")
        presets_fila.grid(row=9, column=0, columnspan=4, padx=16, pady=(10, 4), sticky="w")
        for clave in ("24x7", "off", "lv3"):
            ctk.CTkButton(
                presets_fila, text=turnos_mod.PRESET_LABELS[clave], width=110, height=28,
                fg_color="transparent", border_width=1, border_color=ACCENT,
                text_color=ACCENT, hover_color=BG_CARD,
                command=lambda k=clave: _aplicar_preset(k),
            ).pack(side="left", padx=4)

        def _aceptar():
            nuevo = {d: [variables[d][i].get() for i in range(turnos_mod.NUM_TURNOS)]
                     for d in turnos_mod.DIAS}
            # 24/7 se guarda como None para mantener limpia la configuración.
            turnos_holder[0] = None if turnos_mod.es_completo(nuevo) else nuevo
            btn_turnos.configure(text=turnos_mod.resumen(turnos_holder[0]))
            win.destroy()

        acciones = ctk.CTkFrame(win, fg_color="transparent")
        acciones.grid(row=10, column=0, columnspan=4, padx=16, pady=(8, 16), sticky="e")
        ctk.CTkButton(acciones, text="Cancelar", width=100, height=30,
                      fg_color="transparent", border_width=1, border_color=FG2,
                      text_color=FG2, hover_color=BG_CARD,
                      command=win.destroy).pack(side="left", padx=4)
        ctk.CTkButton(acciones, text="Aceptar", width=100, height=30,
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
                      command=_aceptar).pack(side="left", padx=4)

    # ── Refresco desde la configuración actual ───────────────────────────

    def refrescar(self):
        """Rellena la UI con los valores actuales de la configuración."""
        cfg = self.app.user_cfg

        # Parámetros globales
        cg = obtener_config_global(cfg)
        for entry, clave, fmt in (
            (self._e_diam_max, "diametro_maximo", "{:.1f}"),
            (self._e_diam_min, "diametro_minimo", "{:.1f}"),
            (self._e_crc, "tiempo_traslado_crc_min", "{:.1f}"),
            (self._e_jaulas, "cantidad_jaulas", "{:d}"),
        ):
            entry.delete(0, "end")
            try:
                entry.insert(0, fmt.format(cg[clave]))
            except (KeyError, ValueError):
                entry.insert(0, str(cg.get(clave, "")))

        # Rangos
        for *_, fila in self._filas_rangos:
            fila.destroy()
        self._filas_rangos.clear()
        for r in obtener_rangos(cfg):
            self._agregar_fila_rango(r.get("jaula", ""), r.get("hasta", ""), r.get("desde", ""))

        # Máquinas
        for *_, fila in self._filas_maquinas:
            fila.destroy()
        self._filas_maquinas.clear()
        for m in obtener_maquinas(cfg):
            tasas = m.get("tasas", {})
            prod = tasas.get("produccion", {})
            desb = tasas.get("desbaste", {})
            self._agregar_fila_maquina(
                m.get("nombre", ""),
                prod.get("mm", ""), prod.get("tiempo_min", ""),
                desb.get("mm", ""), desb.get("tiempo_min", ""),
                m.get("prioridad", _TIPOS_RECT[0]),
                m.get("turnos"),
            )

        # Parámetros de simulación
        self._entry_enfriado.delete(0, "end")
        self._entry_enfriado.insert(0, f"{obtener_tiempo_enfriado(cfg):.1f}")
        self._entry_max_iter.delete(0, "end")
        self._entry_max_iter.insert(0, str(obtener_max_iteraciones(cfg)))

    # ── Guardado ─────────────────────────────────────────────────────────

    def _guardar(self):
        try:
            config_global = self._recoger_globales()
            rangos = self._recoger_rangos()
            maquinas = self._recoger_maquinas()
            tiempo_enfriado, max_iter = self._recoger_parametros()
        except ValueError as exc:
            self._feedback(str(exc), error=True)
            return

        self.app.user_cfg["config_global"] = config_global
        self.app.user_cfg["maquinas"] = maquinas
        self.app.user_cfg["rangos"] = rangos
        self.app.user_cfg["tiempo_enfriado_h"] = tiempo_enfriado
        self.app.user_cfg["max_iteraciones"] = max_iter
        self.app.user_cfg.pop("prioridades_maquinas", None)  # esquema viejo, ya migrado
        guardar_config(self.app.user_cfg)

        # Aplicar en caliente al taller (reconstruye máquinas, rangos y globales)
        self.app.taller.configurar(self.app.user_cfg)

        self._feedback("✓ Configuración guardada y aplicada. Recargue/simule para verla en la vista.", error=False)

    def _recoger_globales(self):
        def _num(entry, etiqueta, entero=False):
            txt = entry.get().strip()
            try:
                return int(float(txt)) if entero else float(txt)
            except ValueError:
                raise ValueError(f"Valor inválido en '{etiqueta}'.")

        diam_max = _num(self._e_diam_max, "Diámetro máximo")
        diam_min = _num(self._e_diam_min, "Diámetro mínimo")
        crc = _num(self._e_crc, "Traslado Disponible→CRC")
        jaulas = _num(self._e_jaulas, "Cantidad de jaulas", entero=True)
        if diam_max <= diam_min:
            raise ValueError("El diámetro máximo debe ser mayor que el mínimo.")
        if jaulas <= 0:
            raise ValueError("La cantidad de jaulas debe ser mayor que 0.")
        if crc < 0:
            raise ValueError("El tiempo de traslado al CRC no puede ser negativo.")
        return {
            "diametro_maximo": diam_max, "diametro_minimo": diam_min,
            "tiempo_traslado_crc_min": crc, "cantidad_jaulas": jaulas,
        }

    def _recoger_parametros(self):
        """Lee y valida el tiempo de enfriado (float ≥ 0) y el máx. de iteraciones (int > 0)."""
        try:
            tiempo_enfriado = round(float(self._entry_enfriado.get().strip()), 1)
        except ValueError:
            raise ValueError("Tiempo de enfriado inválido: debe ser un número (p. ej. 8.0).")
        if tiempo_enfriado < 0:
            raise ValueError("El tiempo de enfriado no puede ser negativo.")

        try:
            max_iter = int(float(self._entry_max_iter.get().strip()))
        except ValueError:
            raise ValueError("Máximo de iteraciones inválido: debe ser un entero.")
        if max_iter <= 0:
            raise ValueError("El máximo de iteraciones debe ser mayor que 0.")

        return tiempo_enfriado, max_iter

    def _recoger_rangos(self):
        rangos = []
        # Tuple: (e_jaula, e_min, e_max, fila)
        # e_min = "Desde (mín)" en UI = hasta interno (lower bound)
        # e_max = "Hasta (máx)" en UI = desde interno (upper bound)
        for e_jaula, e_min, e_max, _ in self._filas_rangos:
            j_txt = e_jaula.get().strip()
            min_txt = e_min.get().strip()
            max_txt = e_max.get().strip()
            if not (j_txt or min_txt or max_txt):
                continue
            try:
                jaula = int(float(j_txt))
                hasta = float(min_txt)
                desde = float(max_txt)
            except ValueError:
                raise ValueError(f"Valores inválidos en la jaula '{j_txt or '?'}'.")
            if desde <= hasta:
                raise ValueError(
                    f"Jaula {jaula}: 'Hasta (máx)' ({desde}) debe ser mayor que 'Desde (mín)' ({hasta})."
                )
            rangos.append({"jaula": jaula, "desde": desde, "hasta": hasta})

        if not rangos:
            raise ValueError("Debe definir al menos un rango de jaula.")
        return rangos

    def _recoger_maquinas(self):
        maquinas = []
        nombres = set()
        for e_nom, e_pmm, e_pmin, e_dmm, e_dmin, combo, turnos_holder, _ in self._filas_maquinas:
            nombre = e_nom.get().strip()
            campos = [e_pmm.get().strip(), e_pmin.get().strip(), e_dmm.get().strip(), e_dmin.get().strip()]
            if not nombre and not any(campos):
                continue  # fila vacía, se ignora
            if not nombre:
                raise ValueError("Hay una máquina sin nombre.")
            if nombre in nombres:
                raise ValueError(f"Nombre de máquina repetido: '{nombre}'.")
            nombres.add(nombre)
            try:
                pmm, pmin, dmm, dmin = (float(c) for c in campos)
            except ValueError:
                raise ValueError(f"Tasas inválidas en la máquina '{nombre}' (deben ser números).")
            maq = {
                "nombre": nombre,
                "prioridad": combo.get(),
                "tasas": {
                    "produccion": {"mm": pmm, "tiempo_min": pmin},
                    "desbaste": {"mm": dmm, "tiempo_min": dmin},
                },
            }
            # Turnos solo se persisten si no es 24/7 (None), para no ensuciar el JSON.
            if turnos_holder[0] is not None:
                maq["turnos"] = turnos_holder[0]
            maquinas.append(maq)
        if not maquinas:
            raise ValueError("Debe definir al menos una máquina.")
        return maquinas

    def _feedback(self, mensaje, error):
        """Muestra un mensaje de estado transitorio que se borra solo a los segundos."""
        self._label_estado.configure(text=mensaje, text_color=RED if error else GREEN)
        if self._feedback_after is not None:
            self.after_cancel(self._feedback_after)
        # Los errores quedan más tiempo a la vista que la confirmación de guardado.
        demora_ms = 12000 if error else 6000
        self._feedback_after = self.after(demora_ms, self._limpiar_feedback)

    def _limpiar_feedback(self):
        self._feedback_after = None
        if self._label_estado is not None:
            self._label_estado.configure(text="")


def crear_tab_configuracion(tab, app):
    """Crea y empaqueta la pestaña de configuración. Devuelve el widget para refrescos posteriores."""
    widget = TabConfiguracion(tab, app)
    widget.pack(fill="both", expand=True, padx=10, pady=10)
    return widget
