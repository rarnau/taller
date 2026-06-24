"""Pestaña de Configuración: edición de la configuración persistente del taller.

Edita y persiste (en ``config/user_config.json``) toda la configuración
estructural: parámetros globales, parque de máquinas (CRUD completo), rangos de
SubStock por jaula y parámetros de simulación. El Excel cargado solo aporta
datos (stock + cambios), por lo que esta pantalla es la fuente de verdad de la
configuración.
"""
import customtkinter as ctk

from config.tema import (
    BG_CARD, FG, FG2, ACCENT, GREEN, RED, YELLOW, FONT_FAMILY,
    FONT_SIZE, FONT_SIZE_MD, FONT_SIZE_LG, BTN_BLUE, BTN_BLUE_HOVER,
)
from gui.validacion_config import _estado_validacion
from config.persistencia import (
    guardar_config, obtener_rangos, obtener_maquinas, obtener_config_global,
    obtener_tiempo_enfriado, obtener_max_iteraciones, verificar_coherencia,
    obtener_estrategia_asignacion, obtener_estrategia_seleccion,
)
from modelos.enums import TipoRectificado
from modelos.estrategias import ESTRATEGIAS_ASIGNACION, ESTRATEGIAS_SELECCION
from modelos import turnos as turnos_mod
from gui.editor_turnos import abrir_editor_turnos

_TIPOS_RECT = [t.value for t in TipoRectificado]
# Estrategias de asignación: etiqueta visible ↔ clave persistida (como el combo
# de selección en gui/app.py). La GUI muestra la etiqueta y guarda la clave.
_ASIGNACION_ETIQUETAS = {e.etiqueta: clave for clave, e in ESTRATEGIAS_ASIGNACION.items()}
_ASIGNACION_CLAVE_A_ETIQUETA = {clave: e.etiqueta for clave, e in ESTRATEGIAS_ASIGNACION.items()}
# Estrategias de selección de la cola de rectificado: etiqueta visible ↔ clave.
_SELECCION_ETIQUETAS = {e.etiqueta: clave for clave, e in ESTRATEGIAS_SELECCION.items()}
_SELECCION_CLAVE_A_ETIQUETA = {clave: e.etiqueta for clave, e in ESTRATEGIAS_SELECCION.items()}


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
        # Entries de parámetros globales (incluye el tiempo de enfriado)
        self._e_diam_max = None
        self._e_diam_min = None
        self._e_crc = None
        self._e_jaulas = None
        self._entry_enfriado = None
        # Entries de parámetros de simulación
        self._entry_max_iter = None
        self._combo_asignacion = None
        self._combo_seleccion = None
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
            "Rango de diámetro útil, traslado al CRC, cantidad de jaulas, tiempo de enfriado, estrategia de rectificado y de asignación.",
        )
        self._e_diam_max = _fila_param(cuerpo_g, "Diámetro máximo (mm)")
        self._e_diam_min = _fila_param(cuerpo_g, "Diámetro mínimo (mm)", "bajo este, el cilindro es BAJA")
        self._e_crc = _fila_param(cuerpo_g, "Traslado Disponible→CRC (min)")
        self._e_jaulas = _fila_param(cuerpo_g, "Cantidad de jaulas")
        # Cambiar la cantidad de jaulas crea/elimina filas de SubStock al vuelo.
        # Se sincroniza al confirmar (Enter) o al salir del campo, no en cada
        # tecla, para no destruir filas mientras se escribe un número de 2 dígitos.
        self._e_jaulas.bind("<FocusOut>", self._on_cambio_cantidad_jaulas)
        self._e_jaulas.bind("<Return>", self._on_cambio_cantidad_jaulas)
        self._entry_enfriado = _fila_param(cuerpo_g, "Tiempo de enfriado (h)", "0 = sin enfriado")

        # Estrategia de selección de la cola de rectificado (combo etiqueta↔clave).
        fila_sel = ctk.CTkFrame(cuerpo_g, fg_color="transparent")
        fila_sel.pack(fill="x", pady=3)
        ctk.CTkLabel(
            fila_sel, text="Estrategia de rectificado", width=220, anchor="w", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        ).pack(side="left", padx=4)
        self._combo_seleccion = ctk.CTkComboBox(
            fila_sel, values=list(_SELECCION_ETIQUETAS.keys()), width=240, state="readonly")
        self._combo_seleccion.pack(side="left", padx=4)

        # Estrategia de asignación de jaula destino (combo etiqueta↔clave).
        fila_asig = ctk.CTkFrame(cuerpo_g, fg_color="transparent")
        fila_asig.pack(fill="x", pady=3)
        ctk.CTkLabel(
            fila_asig, text="Estrategia de asignación", width=220, anchor="w", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        ).pack(side="left", padx=4)
        self._combo_asignacion = ctk.CTkComboBox(
            fila_asig, values=list(_ASIGNACION_ETIQUETAS.keys()), width=240, state="readonly")
        self._combo_asignacion.pack(side="left", padx=4)

        # Sección 2: Rangos de SubStock por jaula (columna izquierda)
        cuerpo_r = _card(
            col_izq,
            "Rangos de SubStock por Jaula",
            "Cada jaula admite cilindros cuyo diámetro cumpla  Desde (mín) < diámetro ≤ Hasta (máx).",
        )

        cab = ctk.CTkFrame(cuerpo_r, fg_color="transparent")
        cab.pack(fill="x", pady=(0, 6))
        for txt, w in [("Jaula", 70), ("Desde (mín, mm)", 140), ("Hasta (máx, mm)", 140),
                       ("Perfil", 90)]:
            ctk.CTkLabel(
                cab, text=txt, width=w, anchor="w",
                font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold"),
                text_color=FG2,
            ).pack(side="left", padx=4)

        self._cont_rangos = ctk.CTkFrame(cuerpo_r, fg_color="transparent")
        self._cont_rangos.pack(fill="x")

        ctk.CTkLabel(
            cuerpo_r,
            text="Las jaulas se crean/eliminan al cambiar «Cantidad de jaulas».",
            anchor="w", text_color=FG2,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
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
            "Tope de iteraciones del motor.",
        )
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

        # Validación en vivo: <KeyRelease> en TODOS los entries de globales.
        # OJO: los binds de cantidad de jaulas (<FocusOut>/<Return> →
        # _on_cambio_cantidad_jaulas) se conservan; acá solo se AGREGA <KeyRelease>.
        self._entries_globales = [
            self._e_diam_max, self._e_diam_min, self._e_crc, self._e_jaulas,
            self._entry_enfriado, self._entry_max_iter,
        ]
        # Color de borde por defecto de un CTkEntry, para restaurarlo cuando es válido.
        try:
            self._border_normal = self._e_diam_max.cget("border_color")
        except Exception:
            self._border_normal = FG2
        for e in self._entries_globales:
            e.bind("<KeyRelease>", self._validar_en_vivo)

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

    def _crear_fila_rango(self, jaula, minimo="", maximo="", perfil=""):
        """Crea una fila de SubStock para una jaula fija: Jaula | Desde | Hasta | Perfil.

        El número de jaula **no es editable** (es una etiqueta): las filas se
        crean/eliminan al cambiar «Cantidad de jaulas». Solo se editan los
        límites y el perfil. ``minimo`` es el límite inferior (interno:
        ``hasta``), ``maximo`` el superior (interno: ``desde``). ``perfil`` es
        opcional (vacío = sin perfil exigido).
        """
        fila = ctk.CTkFrame(self._cont_rangos, fg_color="transparent")
        fila.pack(fill="x", pady=3)

        ctk.CTkLabel(
            fila, text=str(jaula), width=70, anchor="center", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        ).pack(side="left", padx=4)

        e_min = ctk.CTkEntry(fila, width=140, justify="center")
        if minimo != "":
            e_min.insert(0, str(minimo))
        e_min.pack(side="left", padx=4)

        e_max = ctk.CTkEntry(fila, width=140, justify="center")
        if maximo != "":
            e_max.insert(0, str(maximo))
        e_max.pack(side="left", padx=4)

        e_perfil = ctk.CTkEntry(fila, width=90, justify="center")
        if perfil not in ("", None):
            e_perfil.insert(0, str(perfil))
        e_perfil.pack(side="left", padx=4)

        # Validación en vivo de los límites/perfil de la fila.
        for e in (e_min, e_max, e_perfil):
            e.bind("<KeyRelease>", self._validar_en_vivo)

        # Registro: (jaula:int, e_min=hasta interno, e_max=desde interno, e_perfil, fila)
        self._filas_rangos.append((int(jaula), e_min, e_max, e_perfil, fila))

    def _on_cambio_cantidad_jaulas(self, event=None):
        """Sincroniza las filas de SubStock cuando cambia «Cantidad de jaulas»."""
        txt = self._e_jaulas.get().strip()
        try:
            n = int(float(txt))
        except ValueError:
            return  # texto inválido: se valida al guardar, no tocamos las filas
        if n > 0:
            self._sincronizar_filas_rango(n)
            # Preview en vivo del cambio de jaulas (informativo) y luego validación.
            if self._label_estado is not None:
                self._label_estado.configure(
                    text=f"↳ {n} jaula(s) ⇒ {n} fila(s) de SubStock",
                    text_color=ACCENT)
        self._validar_en_vivo()

    def _sincronizar_filas_rango(self, n):
        """Ajusta la cantidad de filas de SubStock a ``n`` jaulas (numeradas 1..n).

        Conserva los valores ya cargados; agrega filas vacías para las jaulas
        nuevas y elimina las sobrantes desde el final.
        """
        n = max(0, int(n))
        actual = len(self._filas_rangos)
        if n < actual:
            for _jaula, _e_min, _e_max, _e_perfil, fila in self._filas_rangos[n:]:
                fila.destroy()
            del self._filas_rangos[n:]
        else:
            for jaula in range(actual + 1, n + 1):
                self._crear_fila_rango(jaula)

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
        """Abre el popup compartido de edición de turnos (grilla 7×3 + presets)."""
        abrir_editor_turnos(self, turnos_holder, btn_turnos)

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

        # Rangos: una fila por jaula (1..N), con el número no editable y la
        # cantidad ligada a «Cantidad de jaulas». Se conservan los límites
        # guardados; las jaulas sin rango quedan con los campos vacíos.
        for *_, fila in self._filas_rangos:
            fila.destroy()
        self._filas_rangos.clear()
        rangos_cfg = {int(r["jaula"]): r for r in obtener_rangos(cfg)}
        try:
            n = int(cg.get("cantidad_jaulas", len(rangos_cfg)))
        except (TypeError, ValueError):
            n = len(rangos_cfg)
        n = max(n, 1)
        for jaula in range(1, n + 1):
            r = rangos_cfg.get(jaula, {})
            self._crear_fila_rango(jaula, r.get("hasta", ""), r.get("desde", ""), r.get("perfil", ""))

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
        clave_sel = obtener_estrategia_seleccion(cfg)
        self._combo_seleccion.set(_SELECCION_CLAVE_A_ETIQUETA.get(
            clave_sel, next(iter(_SELECCION_ETIQUETAS))))
        clave_asig = obtener_estrategia_asignacion(cfg)
        self._combo_asignacion.set(_ASIGNACION_CLAVE_A_ETIQUETA.get(
            clave_asig, next(iter(_ASIGNACION_ETIQUETAS))))

        # Mostrar el estado de validación al abrir/refrescar la pestaña.
        self._validar_en_vivo()

    # ── Guardado ─────────────────────────────────────────────────────────

    def _guardar(self):
        try:
            config_global = self._recoger_globales()
            rangos = self._recoger_rangos()
            maquinas = self._recoger_maquinas()
            tiempo_enfriado, max_iter = self._recoger_parametros()
            # Coherencia jaulas ⇄ rangos: validar el candidato ANTES de persistir
            # (misma verificación que usa el CLI), para no guardar un estado roto.
            verificar_coherencia({"config_global": config_global, "rangos": rangos})
        except ValueError as exc:
            msg = str(exc)
            if not msg.startswith("❌"):
                msg = "❌ " + msg
            self._feedback(msg, error=True)
            return

        self.app.user_cfg["config_global"] = config_global
        self.app.user_cfg["maquinas"] = maquinas
        self.app.user_cfg["rangos"] = rangos
        self.app.user_cfg["tiempo_enfriado_h"] = tiempo_enfriado
        self.app.user_cfg["max_iteraciones"] = max_iter
        self.app.user_cfg["estrategia_seleccion"] = _SELECCION_ETIQUETAS.get(
            self._combo_seleccion.get(), next(iter(_SELECCION_ETIQUETAS.values())))
        self.app.user_cfg["estrategia_asignacion"] = _ASIGNACION_ETIQUETAS.get(
            self._combo_asignacion.get(), next(iter(_ASIGNACION_ETIQUETAS.values())))
        self.app.user_cfg.pop("prioridades_maquinas", None)  # esquema viejo, ya migrado
        guardar_config(self.app.user_cfg)

        # Aplicar en caliente al taller (reconstruye máquinas, rangos y globales)
        self.app.taller.configurar(self.app.user_cfg)

        self._feedback("✓ Configuración guardada y aplicada.", error=False)

        # Refrescar la estrella de la pestaña Configuración (estado ya coherente).
        if hasattr(self.app, "actualizar_indicadores_tabs"):
            self.app.actualizar_indicadores_tabs()

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
        """Lee los rangos de SubStock (uno por jaula, numeradas 1..N).

        El número de jaula viene de la fila (no es editable). La coherencia con
        «Cantidad de jaulas» la valida ``verificar_coherencia`` en ``_guardar``
        (la misma verificación compartida con el CLI).
        """
        rangos = []
        # Tuple: (jaula, e_min, e_max, e_perfil, fila)
        # e_min = "Desde (mín)" en UI = hasta interno (lower bound)
        # e_max = "Hasta (máx)" en UI = desde interno (upper bound)
        for jaula, e_min, e_max, e_perfil, _ in self._filas_rangos:
            min_txt = e_min.get().strip()
            max_txt = e_max.get().strip()
            try:
                hasta = float(min_txt)
                desde = float(max_txt)
            except ValueError:
                raise ValueError(
                    f"Jaula {jaula}: defina valores numéricos en 'Desde (mín)' y 'Hasta (máx)'."
                )
            if desde <= hasta:
                raise ValueError(
                    f"Jaula {jaula}: 'Hasta (máx)' ({desde}) debe ser mayor que 'Desde (mín)' ({hasta})."
                )
            r = {"jaula": jaula, "desde": desde, "hasta": hasta}
            perfil = e_perfil.get().strip()
            if perfil:
                r["perfil"] = perfil
            rangos.append(r)

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

    # ── Validación en vivo ───────────────────────────────────────────────

    def _recoger_crudo(self):
        """Arma los dicts/listas de strings crudos (globales + filas de rango).

        Sin conversión ni validación: alimenta a ``_estado_validacion`` (puro).
        Devuelve ``(globales, rangos)``.
        """
        globales = {
            "diam_max": self._e_diam_max.get(),
            "diam_min": self._e_diam_min.get(),
            "crc": self._e_crc.get(),
            "jaulas": self._e_jaulas.get(),
            "enfriado": self._entry_enfriado.get(),
            "max_iter": self._entry_max_iter.get(),
        }
        rangos = []
        for jaula, e_min, e_max, e_perfil, _ in self._filas_rangos:
            rangos.append({
                "jaula": jaula,
                "min": e_min.get(),
                "max": e_max.get(),
                "perfil": e_perfil.get(),
            })
        return globales, rangos

    def _validar_en_vivo(self, event=None):
        """Valida en vivo y refleja el resultado en el label (sin timer).

        Pinta de rojo el borde de los entries inválidos y restaura el normal en
        los válidos. A diferencia de ``_feedback``, el mensaje **no se borra solo**.
        """
        if self._label_estado is None:
            return
        globales, rangos = self._recoger_crudo()
        mensaje, es_error = _estado_validacion(globales, rangos)
        # ⚠ (requerido) en amarillo; ❌ (inválido) en rojo; ✓ en verde.
        if not es_error:
            color = GREEN
        elif mensaje.startswith("⚠"):
            color = YELLOW
        else:
            color = RED
        self._label_estado.configure(text=mensaje, text_color=color)
        self._marcar_entries_invalidos(es_error, globales, rangos)

    def _marcar_entries_invalidos(self, es_error, globales, rangos):
        """Resalta en rojo el/los entry(s) que disparan el problema; el resto, normal."""
        culpables = set()
        if es_error:
            culpables = self._entries_culpables(globales, rangos)
        for e in self._entries_globales:
            self._pintar_borde(e, e in culpables)
        for _jaula, e_min, e_max, e_perfil, _ in self._filas_rangos:
            for e in (e_min, e_max, e_perfil):
                self._pintar_borde(e, e in culpables)

    def _entries_culpables(self, globales, rangos):
        """Devuelve el conjunto de entries asociados al primer problema detectado.

        Reproduce el orden de ``_estado_validacion`` para señalar el campo exacto.
        """
        import gui.validacion_config as _vc
        culp = set()
        mapa_glob = {
            "diam_max": self._e_diam_max, "diam_min": self._e_diam_min,
            "crc": self._e_crc, "jaulas": self._e_jaulas,
            "enfriado": self._entry_enfriado, "max_iter": self._entry_max_iter,
        }
        # Requerido vacío / no numérico en globales.
        for clave in _vc._ETIQUETAS_GLOBALES:
            if str(globales.get(clave, "")).strip() == "":
                culp.add(mapa_glob[clave]); return culp
        for clave in _vc._ETIQUETAS_GLOBALES:
            try:
                float(str(globales[clave]).strip())
            except ValueError:
                culp.add(mapa_glob[clave]); return culp
        v = {k: float(str(globales[k]).strip()) for k in _vc._ETIQUETAS_GLOBALES}
        if v["diam_max"] <= v["diam_min"]:
            culp.update({self._e_diam_max, self._e_diam_min}); return culp
        if int(v["jaulas"]) <= 0:
            culp.add(self._e_jaulas); return culp
        if v["crc"] < 0:
            culp.add(self._e_crc); return culp
        if v["enfriado"] < 0:
            culp.add(self._entry_enfriado); return culp
        if v["max_iter"] <= 0:
            culp.add(self._entry_max_iter); return culp
        # Rangos.
        filas = {f[0]: f for f in self._filas_rangos}
        for r in rangos:
            fila = filas.get(r["jaula"])
            if fila is None:
                continue
            _j, e_min, e_max, _ep, _ = fila
            min_txt, max_txt = str(r.get("min", "")).strip(), str(r.get("max", "")).strip()
            if min_txt == "" or max_txt == "":
                if min_txt == "":
                    culp.add(e_min)
                if max_txt == "":
                    culp.add(e_max)
                return culp
            try:
                hasta = float(min_txt); desde = float(max_txt)
            except ValueError:
                culp.update({e_min, e_max}); return culp
            if desde <= hasta:
                culp.update({e_min, e_max}); return culp
        return culp

    def _pintar_borde(self, entry, invalido):
        """Pinta el borde del entry de rojo (inválido) o lo restaura al normal."""
        try:
            entry.configure(border_color=RED if invalido else self._border_normal)
        except Exception:
            pass

    def _feedback(self, mensaje, error):
        """Muestra un mensaje de estado transitorio que se borra solo a los segundos."""
        self._label_estado.configure(text=mensaje, text_color=RED if error else GREEN)
        if self._feedback_after is not None:
            self.after_cancel(self._feedback_after)
        # Los errores quedan algo más de tiempo a la vista que la confirmación.
        demora_ms = 5000 if error else 3000
        self._feedback_after = self.after(demora_ms, self._limpiar_feedback)

    def _limpiar_feedback(self):
        """Borra el mensaje de estado y cancela el timer pendiente (si lo hay)."""
        if self._feedback_after is not None:
            self.after_cancel(self._feedback_after)
            self._feedback_after = None
        if self._label_estado is not None:
            self._label_estado.configure(text="")


def crear_tab_configuracion(tab, app):
    """Crea y empaqueta la pestaña de configuración. Devuelve el widget para refrescos posteriores."""
    widget = TabConfiguracion(tab, app)
    widget.pack(fill="both", expand=True, padx=10, pady=10)
    return widget
