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
        self._filas_rangos = []      # [(e_jaula, e_desde, e_hasta, frame_fila)]
        self._filas_maquinas = []    # [(e_nom, e_pmm, e_pmin, e_dmm, e_dmin, combo_prio, frame_fila)]
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
        self.bind("<Configure>", self._on_resize)
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
            "Cada jaula admite cilindros cuyo diámetro cumpla  Hasta (mín) < diámetro ≤ Desde (máx).",
        )

        cab = ctk.CTkFrame(cuerpo_r, fg_color="transparent")
        cab.pack(fill="x", pady=(0, 6))
        for txt, w in [("Jaula", 70), ("Desde (máx, mm)", 140), ("Hasta (mín, mm)", 140), ("", 40)]:
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
            "Tasas por tipo (mm removidos y minutos) y prioridad de rectificado.",
        )

        cab_m = ctk.CTkFrame(cuerpo_m, fg_color="transparent")
        cab_m.pack(fill="x", pady=(0, 6))
        for txt, w in [("Nombre", 84), ("Prod mm", 58), ("Prod min", 58),
                       ("Desb mm", 58), ("Desb min", 58), ("Prioridad", 110), ("", 36)]:
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
        modo = "ancho" if self.winfo_width() >= self._UMBRAL_APILADO else "estrecho"
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

    def _agregar_fila_rango(self, jaula="", desde="", hasta=""):
        fila = ctk.CTkFrame(self._cont_rangos, fg_color="transparent")
        fila.pack(fill="x", pady=3)

        e_jaula = ctk.CTkEntry(fila, width=70, justify="center")
        e_jaula.insert(0, str(jaula))
        e_jaula.pack(side="left", padx=4)

        e_desde = ctk.CTkEntry(fila, width=140, justify="center")
        e_desde.insert(0, str(desde))
        e_desde.pack(side="left", padx=4)

        e_hasta = ctk.CTkEntry(fila, width=140, justify="center")
        e_hasta.insert(0, str(hasta))
        e_hasta.pack(side="left", padx=4)

        registro = (e_jaula, e_desde, e_hasta, fila)

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
                              desb_mm="", desb_min="", prioridad=_TIPOS_RECT[0]):
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

        registro = (e_nom, e_pmm, e_pmin, e_dmm, e_dmin, combo, fila)

        ctk.CTkButton(
            fila, text="🗑", width=36, fg_color="transparent",
            text_color=RED, hover_color=BG_CARD,
            command=lambda: self._quitar_fila_maquina(registro),
        ).pack(side="left", padx=2)

        self._filas_maquinas.append(registro)

    def _quitar_fila_maquina(self, registro):
        registro[6].destroy()
        self._filas_maquinas.remove(registro)

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
            self._agregar_fila_rango(r.get("jaula", ""), r.get("desde", ""), r.get("hasta", ""))

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
        for e_jaula, e_desde, e_hasta, _ in self._filas_rangos:
            j_txt, d_txt, h_txt = e_jaula.get().strip(), e_desde.get().strip(), e_hasta.get().strip()
            if not (j_txt or d_txt or h_txt):
                continue  # fila vacía, se ignora
            try:
                jaula = int(float(j_txt))
                desde = float(d_txt)
                hasta = float(h_txt)
            except ValueError:
                raise ValueError(f"Valores inválidos en la jaula '{j_txt or '?'}'.")
            if desde <= hasta:
                raise ValueError(
                    f"Jaula {jaula}: 'Desde (máx)' ({desde}) debe ser mayor que 'Hasta (mín)' ({hasta})."
                )
            rangos.append({"jaula": jaula, "desde": desde, "hasta": hasta})

        if not rangos:
            raise ValueError("Debe definir al menos un rango de jaula.")
        return rangos

    def _recoger_maquinas(self):
        maquinas = []
        nombres = set()
        for e_nom, e_pmm, e_pmin, e_dmm, e_dmin, combo, _ in self._filas_maquinas:
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
            maquinas.append({
                "nombre": nombre,
                "prioridad": combo.get(),
                "tasas": {
                    "produccion": {"mm": pmm, "tiempo_min": pmin},
                    "desbaste": {"mm": dmm, "tiempo_min": dmin},
                },
            })
        if not maquinas:
            raise ValueError("Debe definir al menos una máquina.")
        return maquinas

    def _feedback(self, mensaje, error):
        self._label_estado.configure(text=mensaje, text_color=RED if error else GREEN)


def crear_tab_configuracion(tab, app):
    """Crea y empaqueta la pestaña de configuración. Devuelve el widget para refrescos posteriores."""
    widget = TabConfiguracion(tab, app)
    widget.pack(fill="both", expand=True, padx=10, pady=10)
    return widget
