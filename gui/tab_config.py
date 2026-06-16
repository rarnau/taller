"""Pestaña de Configuración: edición de rangos de jaulas y prioridades de máquinas."""
import customtkinter as ctk

from config.tema import (
    BG_CARD, FG, FG2, ACCENT, GREEN, RED, FONT_FAMILY,
    FONT_SIZE, FONT_SIZE_MD, FONT_SIZE_LG, BTN_BLUE, BTN_BLUE_HOVER,
)
from config.persistencia import (
    guardar_config, obtener_rangos, obtener_prioridades,
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


class TabConfiguracion(ctk.CTkScrollableFrame):
    """Editor de configuración persistente (rangos por jaula y prioridades de máquinas)."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._filas_rangos = []      # [(entry_jaula, entry_desde, entry_hasta, frame_fila)]
        self._combos_prio = {}       # {nombre_maquina: CTkComboBox}
        self._cont_rangos = None
        self._cont_prio = None
        self._entry_enfriado = None
        self._entry_max_iter = None
        self._label_estado = None

        self._construir()
        self.refrescar()

    # ── Construcción de la UI ────────────────────────────────────────────

    def _construir(self):
        # Layout en dos columnas para aprovechar el ancho de la pestaña:
        #   izquierda → rangos por jaula;  derecha → prioridades + parámetros.
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="both", expand=True)

        col_izq = ctk.CTkFrame(cols, fg_color="transparent")
        col_izq.pack(side="left", fill="both", expand=True, padx=(0, 8), anchor="n")

        col_der = ctk.CTkFrame(cols, fg_color="transparent")
        col_der.pack(side="left", fill="both", expand=True, padx=(8, 0), anchor="n")

        # Sección 1: Rangos de SubStock por jaula (columna izquierda)
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

        # Sección 2: Prioridades de máquinas (columna derecha)
        self._cont_prio = _card(
            col_der,
            "Prioridades de Rectificado por Máquina",
            "Tipo de rectificado por defecto cuando el cilindro no especifica uno.",
        )

        # Sección 3: Parámetros de simulación (columna derecha)
        cuerpo_p = _card(
            col_der,
            "Parámetros de Simulación",
            "Tiempo de enfriado tras retirar un cilindro y tope de iteraciones del motor.",
        )

        fila_enf = ctk.CTkFrame(cuerpo_p, fg_color="transparent")
        fila_enf.pack(fill="x", pady=3)
        ctk.CTkLabel(
            fila_enf, text="Tiempo de enfriado (h)", width=200, anchor="w", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        ).pack(side="left", padx=4)
        self._entry_enfriado = ctk.CTkEntry(fila_enf, width=120, justify="center")
        self._entry_enfriado.pack(side="left", padx=4)
        ctk.CTkLabel(
            fila_enf, text="0 = sin enfriado", anchor="w", text_color=FG2,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
        ).pack(side="left", padx=4)

        fila_iter = ctk.CTkFrame(cuerpo_p, fg_color="transparent")
        fila_iter.pack(fill="x", pady=3)
        ctk.CTkLabel(
            fila_iter, text="Máximo de iteraciones", width=200, anchor="w", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        ).pack(side="left", padx=4)
        self._entry_max_iter = ctk.CTkEntry(fila_iter, width=120, justify="center")
        self._entry_max_iter.pack(side="left", padx=4)

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

    # ── Refresco desde el estado actual ──────────────────────────────────

    def refrescar(self):
        """Rellena la UI con los valores actuales de configuración y máquinas cargadas."""
        # Rangos
        for *_, fila in self._filas_rangos:
            fila.destroy()
        self._filas_rangos.clear()

        for r in obtener_rangos(self.app.user_cfg):
            self._agregar_fila_rango(r.get("jaula", ""), r.get("desde", ""), r.get("hasta", ""))

        # Parámetros de simulación
        self._entry_enfriado.delete(0, "end")
        self._entry_enfriado.insert(0, f"{obtener_tiempo_enfriado(self.app.user_cfg):.1f}")
        self._entry_max_iter.delete(0, "end")
        self._entry_max_iter.insert(0, str(obtener_max_iteraciones(self.app.user_cfg)))

        # Prioridades de máquinas
        for w in self._cont_prio.winfo_children():
            w.destroy()
        self._combos_prio.clear()

        maquinas = sorted(self.app.taller.maquinas.keys())
        prio_guardadas = obtener_prioridades(self.app.user_cfg)

        if not maquinas:
            ctk.CTkLabel(
                self._cont_prio,
                text="Cargue un archivo Excel para listar las máquinas disponibles.",
                anchor="w", text_color=FG2,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
            ).pack(fill="x", pady=4)
            return

        for nombre in maquinas:
            fila = ctk.CTkFrame(self._cont_prio, fg_color="transparent")
            fila.pack(fill="x", pady=3)

            ctk.CTkLabel(
                fila, text=nombre, width=200, anchor="w", text_color=FG,
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
            ).pack(side="left", padx=4)

            combo = ctk.CTkComboBox(fila, values=_TIPOS_RECT, width=180, state="readonly")
            actual = prio_guardadas.get(nombre, self.app.taller.maquinas[nombre].prioridad_defecto.value)
            combo.set(actual if actual in _TIPOS_RECT else _TIPOS_RECT[0])
            combo.pack(side="left", padx=4)

            self._combos_prio[nombre] = combo

    # ── Guardado ─────────────────────────────────────────────────────────

    def _guardar(self):
        try:
            rangos = self._recoger_rangos()
            tiempo_enfriado, max_iter = self._recoger_parametros()
        except ValueError as exc:
            self._feedback(str(exc), error=True)
            return

        prioridades = {n: c.get() for n, c in self._combos_prio.items()}

        self.app.user_cfg["rangos"] = rangos
        self.app.user_cfg["prioridades_maquinas"] = prioridades
        self.app.user_cfg["tiempo_enfriado_h"] = tiempo_enfriado
        self.app.user_cfg["max_iteraciones"] = max_iter
        guardar_config(self.app.user_cfg)

        # Aplicar en caliente al taller
        self.app.taller.configurar_substocks(rangos)
        if prioridades:
            self.app.taller.aplicar_prioridades_maquinas(prioridades)
        self.app.taller.tiempo_enfriado_h = tiempo_enfriado
        self.app.taller.max_iteraciones = max_iter

        self._feedback("✓ Configuración guardada y aplicada.", error=False)

    def _recoger_parametros(self):
        """Lee y valida el tiempo de enfriado (float ≥ 0, 1 decimal) y el máx. de iteraciones (int > 0)."""
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

    def _feedback(self, mensaje, error):
        self._label_estado.configure(text=mensaje, text_color=RED if error else GREEN)


def crear_tab_configuracion(tab, app):
    """Crea y empaqueta la pestaña de configuración. Devuelve el widget para refrescos posteriores."""
    widget = TabConfiguracion(tab, app)
    widget.pack(fill="both", expand=True, padx=10, pady=10)
    return widget
