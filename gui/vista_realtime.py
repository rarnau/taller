"""
Componentes visuales para la representación en tiempo real del taller.
"""
import customtkinter as ctk

from config.tema import *

# Alto (px) del área de cada barra del gráfico de stock disponible por jaula.
_ALTO_BARRA = 90


# Texto descriptivo del sentido de toma de la cola según la estrategia.
_SENTIDO_TOMA = {
    "mayor_diametro": "Sentido de toma:  mayor diámetro primero  →",
    "menor_diametro": "Sentido de toma:  menor diámetro primero  →",
    "fifo": "Sentido de toma:  orden de llegada (FIFO)  →",
    "menor_mm_desb_fifo_prod": "Sentido de toma:  menor mm (desbaste) / FIFO (producción)  →",
}


class CilindroGrafico(ctk.CTkFrame):
    """Representación visual de un cilindro."""

    def __init__(self, master, cilindro_id: str, diametro: float, color=ACCENT, command=None):
        super().__init__(master, fg_color=color, corner_radius=8, width=60, height=30)
        self.id = cilindro_id
        self.diam = diametro

        self.label = ctk.CTkLabel(
            self,
            text=f"{cilindro_id}\n{diametro:.1f}",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color="white"
        )
        self.label.pack(expand=True, fill="both")

        if command:
            self.bind("<Button-1>", lambda e: command(self.id))
            self.label.bind("<Button-1>", lambda e: command(self.id))


class SeccionTaller(ctk.CTkFrame):
    """Contenedor de tamaño fijo para una sección del taller (Jaula o CRC)."""

    # Tamaño fijo para que los recuadros no aparezcan enormes cuando están vacíos.
    ANCHO = 190
    ALTO = 84

    def __init__(self, master, titulo: str, color_borde=ACCENT):
        super().__init__(master, border_width=2, border_color=color_borde,
                         width=self.ANCHO, height=self.ALTO)
        self.pack_propagate(False)  # mantiene el tamaño fijo aunque esté vacío

        self._titulo_orig = titulo
        self._color_borde_orig = color_borde
        self.parada = False

        self.titulo = ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=13, weight="bold"))
        self.titulo.pack(pady=(4, 2))

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(expand=True, fill="both", padx=8, pady=(0, 8))
        self.cilindros_widgets: dict = {}  # {cilindro_id: widget}

    def set_parada(self, parada: bool) -> None:
        """Resalta la sección como PARADA (borde rojo y título de aviso)."""
        if parada == self.parada:
            return
        self.parada = parada
        if parada:
            self.configure(border_color=RED, border_width=3)
            self.titulo.configure(text="⛔ PARADA", text_color=RED)
        else:
            self.configure(border_color=self._color_borde_orig, border_width=2)
            self.titulo.configure(text=self._titulo_orig, text_color=FG)

    def actualizar(self, lista_cilindros: list, on_click_callback) -> None:
        ids_nuevos = [c["id"] for c in lista_cilindros]

        # Eliminar cilindros que ya no están
        ids_a_borrar = [cid for cid in self.cilindros_widgets if cid not in ids_nuevos]
        for cid in ids_a_borrar:
            self.cilindros_widgets[cid].destroy()
            del self.cilindros_widgets[cid]

        # Actualizar o añadir cilindros
        for c in lista_cilindros:
            cid = c["id"]
            if cid in self.cilindros_widgets:
                self.cilindros_widgets[cid].label.configure(text=f"{cid}\n{c['d']:.1f}")
            else:
                cg = CilindroGrafico(self.container, cid, c["d"], command=on_click_callback)
                cg.pack(side="left", padx=4)
                self.cilindros_widgets[cid] = cg


class VistaRealTime(ctk.CTkScrollableFrame):
    """Panel principal que organiza todas las secciones del taller."""

    def __init__(self, master, on_cilindro_click, cantidad_jaulas: int = 4):
        super().__init__(master)
        self.on_cilindro_click = on_cilindro_click
        self.cantidad_jaulas = cantidad_jaulas
        self.estrategia = "mayor_diametro"

        self.jaulas_frames: dict = {}
        self.crc_frames: dict = {}
        self.maq_widgets: dict = {}
        self.cola_widgets: dict = {}
        self.enfriando_widgets: dict = {}

        # Gráfico de barras de stock Disponible por jaula. _mapa_substocks mapea
        # jaula -> nombre de su SubStock (clave de Snapshot.disponibles_por_substock);
        # _escala_disp es el máximo (sobre todo el run) para normalizar la altura.
        self.barras_disp: dict = {}   # {jaula: {"col","area","bar","lbl_val"}}
        self._mapa_substocks: dict = {}
        self._escala_disp: int = 0

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.title_label = ctk.CTkLabel(
            self, text="ESTADO DEL TALLER EN TIEMPO REAL",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.title_label.pack(pady=(8, 6))

        # Dos columnas: jaulas/buffer a la izquierda, rectificadoras/cola/enfriado a la derecha.
        self.columnas = ctk.CTkFrame(self, fg_color="transparent")
        self.columnas.pack(fill="both", expand=True, padx=20)

        # ── Columna izquierda: jaulas + buffer CRC ───────────────────────
        self.col_jaulas = ctk.CTkFrame(self.columnas, fg_color="transparent")
        self.col_jaulas.pack(side="left", anchor="n", padx=(0, 20))

        ctk.CTkLabel(self.col_jaulas, text="JAULAS",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(0, 4))

        self.main_container = ctk.CTkFrame(self.col_jaulas, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)
        self._crear_filas_jaulas(self.cantidad_jaulas)

        # ── Gráfico de barras: stock Disponible por jaula ─────────────────
        ctk.CTkLabel(self.col_jaulas, text="STOCK DISPONIBLE POR JAULA",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORES_ESTADO["Disponible"]).pack(pady=(14, 4))

        self.disp_container = ctk.CTkFrame(self.col_jaulas, fg_color="transparent")
        self.disp_container.pack(fill="x", pady=(0, 10))
        self._crear_barras_disponibilidad(self.cantidad_jaulas)

        # ── Columna derecha: rectificadoras + cola + enfriado ─────────────
        self.col_maqs = ctk.CTkFrame(self.columnas, fg_color="transparent")
        self.col_maqs.pack(side="left", anchor="n", fill="both", expand=True)

        self.maqs_title = ctk.CTkLabel(self.col_maqs, text="RECTIFICADORAS",
                                       font=ctk.CTkFont(size=16, weight="bold"))
        self.maqs_title.pack(pady=(0, 4))

        self.maqs_container = ctk.CTkFrame(self.col_maqs, fg_color="transparent")
        self.maqs_container.pack(fill="x")

        self.cola_title = ctk.CTkLabel(
            self.col_maqs, text="COLA DE ESPERA RECTIFICADO",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.cola_title.pack(pady=(14, 2))

        self.cola_sentido = ctk.CTkLabel(
            self.col_maqs, text=_SENTIDO_TOMA.get(self.estrategia, ""),
            font=ctk.CTkFont(size=12), text_color=ACCENT
        )
        self.cola_sentido.pack(pady=(0, 4))

        self.cola_container = ctk.CTkScrollableFrame(
            self.col_maqs, fg_color="transparent", orientation="horizontal", height=90
        )
        self.cola_container.pack(fill="x", pady=(0, 6))

        # ── Sección global de cilindros en enfriado ──────────────────────
        ctk.CTkLabel(self.col_maqs, text="EN ENFRIAMIENTO",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORES_ESTADO["Enfriando"]).pack(pady=(14, 4))

        self.enfriando_container = ctk.CTkScrollableFrame(
            self.col_maqs, fg_color="transparent", orientation="horizontal", height=70
        )
        self.enfriando_container.pack(fill="x", pady=(0, 10))

    def _crear_filas_jaulas(self, n: int) -> None:
        """Crea N filas de jaula + CRC en el contenedor principal."""
        for i in range(1, n + 1):
            f = ctk.CTkFrame(self.main_container)
            f.pack(fill="x", pady=4)

            ctk.CTkLabel(f, text=f"J{i}", font=ctk.CTkFont(size=22, weight="bold"), width=36).pack(
                side="left", padx=(10, 6)
            )

            jf = SeccionTaller(f, "TRABAJANDO", color_borde=COLORES_ESTADO["Trabajando"])
            jf.pack(side="left", padx=6, pady=6)
            self.jaulas_frames[i] = jf

            cf = SeccionTaller(f, "BUFFER CRC", color_borde=COLORES_ESTADO["CRC"])
            cf.pack(side="left", padx=6, pady=6)
            self.crc_frames[i] = cf

    def _crear_barras_disponibilidad(self, n: int) -> None:
        """Crea N barras verticales (una por jaula) para el stock Disponible."""
        for w in self.disp_container.winfo_children():
            w.destroy()
        self.barras_disp.clear()
        for i in range(1, n + 1):
            col = ctk.CTkFrame(self.disp_container, fg_color="transparent")
            col.pack(side="left", expand=True, padx=6)

            lbl_val = ctk.CTkLabel(col, text="0", font=ctk.CTkFont(size=13, weight="bold"),
                                   text_color=FG)
            lbl_val.pack()

            # Área de alto fijo con fondo tenue; la barra crece desde abajo.
            area = ctk.CTkFrame(col, height=_ALTO_BARRA, width=44, fg_color=BG3, corner_radius=4)
            area.pack()
            area.pack_propagate(False)
            bar = ctk.CTkFrame(area, height=0, fg_color=COLORES_ESTADO["Disponible"],
                               corner_radius=4)
            bar.pack(side="bottom", fill="x")

            ctk.CTkLabel(col, text=f"J{i}", font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=FG_DIM).pack(pady=(2, 0))

            self.barras_disp[i] = {"col": col, "area": area, "bar": bar, "lbl_val": lbl_val}

    def configurar_disponibilidad(self, mapa_substocks: dict, escala_max: int) -> None:
        """Define el mapeo jaula→SubStock y la escala (máximo) para normalizar las barras."""
        self._mapa_substocks = dict(mapa_substocks)
        self._escala_disp = max(1, int(escala_max))

    def ajustar_jaulas(self, cantidad_jaulas: int) -> None:
        """Reconstruye las filas de jaulas si la cantidad difiere de la actual."""
        if self.cantidad_jaulas == cantidad_jaulas and self.jaulas_frames:
            return
        self.cantidad_jaulas = cantidad_jaulas
        for w in self.main_container.winfo_children():
            w.destroy()
        self.jaulas_frames.clear()
        self.crc_frames.clear()
        self._crear_filas_jaulas(cantidad_jaulas)
        self._crear_barras_disponibilidad(cantidad_jaulas)

    def set_estrategia(self, estrategia: str) -> None:
        """Define la estrategia de selección y actualiza el indicador de sentido de toma."""
        self.estrategia = estrategia
        self.cola_sentido.configure(text=_SENTIDO_TOMA.get(estrategia, "Sentido de toma  →"))

    def mostrar_maquinas(self, nombres) -> None:
        """Crea los recuadros de las rectificadoras disponibles (estado Libre)."""
        for w in self.maqs_container.winfo_children():
            w.destroy()
        self.maq_widgets.clear()
        # Columnas uniformes que se reparten el ancho disponible (responsive):
        # las rectificadoras se achican/agrandan al mover la app de pantalla.
        total = max(1, len(nombres))
        for c in range(total):
            self.maqs_container.grid_columnconfigure(c, weight=1, uniform="maq")
        # Resetea pesos de columnas sobrantes de una carga previa con más máquinas.
        for c in range(total, total + 8):
            self.maqs_container.grid_columnconfigure(c, weight=0, uniform="")
        for nombre in nombres:
            self._crear_maquina_widget(nombre)

    def _crear_maquina_widget(self, nombre: str) -> None:
        columna = len(self.maq_widgets)
        self.maqs_container.grid_columnconfigure(columna, weight=1, uniform="maq")
        f = ctk.CTkFrame(self.maqs_container, height=90, border_width=2, border_color=BG3)
        f.grid(row=0, column=columna, padx=6, pady=6, sticky="ew")
        f.grid_propagate(False)

        ctk.CTkLabel(f, text=nombre, font=ctk.CTkFont(weight="bold")).pack()

        content = ctk.CTkFrame(f, fg_color="transparent")
        content.pack(expand=True, fill="both")

        prog = ctk.CTkProgressBar(f)
        prog.set(0)
        prog.configure(progress_color="gray")
        prog.pack(fill="x", padx=10, pady=5)

        lbl = ctk.CTkLabel(content, text="Libre")
        lbl.pack(expand=True)
        self.maq_widgets[nombre] = {"outer": f, "frame": content, "prog": prog, "label": lbl}

    def _ordenar_cola(self, lista: list) -> list:
        """Ordena la cola según el sentido de toma (el próximo a tomar queda primero)."""
        if self.estrategia == "mayor_diametro":
            return sorted(lista, key=lambda c: c["d"], reverse=True)
        if self.estrategia == "menor_diametro":
            return sorted(lista, key=lambda c: c["d"])
        return list(lista)  # FIFO: respeta el orden de llegada

    def actualizar(self, snapshot) -> None:
        """Actualiza todos los componentes visuales con el estado de un snapshot."""
        paradas = set(getattr(snapshot, "jaulas_paradas", []))
        disp_por_ss = getattr(snapshot, "disponibles_por_substock", {})
        for i in range(1, self.cantidad_jaulas + 1):
            if i in snapshot.detalle_jaulas and i in self.jaulas_frames:
                self.jaulas_frames[i].actualizar(snapshot.detalle_jaulas[i], self.on_cilindro_click)
                self.jaulas_frames[i].set_parada(i in paradas)
            if i in snapshot.detalle_crc and i in self.crc_frames:
                self.crc_frames[i].actualizar(snapshot.detalle_crc[i], self.on_cilindro_click)
            # Barra de stock Disponible de la jaula (altura ∝ valor / escala).
            if i in self.barras_disp:
                val = disp_por_ss.get(self._mapa_substocks.get(i), 0)
                alto = 0 if val == 0 else max(3, int(val / self._escala_disp * _ALTO_BARRA))
                self.barras_disp[i]["bar"].configure(height=alto)
                self.barras_disp[i]["lbl_val"].configure(text=str(val))

        # Cola de rectificado: se reconstruye ordenada según el sentido de toma.
        for w in self.cola_widgets.values():
            w.destroy()
        self.cola_widgets.clear()

        for idx, c in enumerate(self._ordenar_cola(snapshot.detalle_cola_rectificado)):
            # El primero (próximo a tomar) se resalta con el color de acento.
            color = ACCENT if idx == 0 else COLORES_ESTADO["A rectificar"]
            cg = CilindroGrafico(
                self.cola_container, c["id"], c["d"],
                color=color, command=self.on_cilindro_click
            )
            cg.pack(side="left", padx=5)
            self.cola_widgets[c["id"]] = cg

        # Cilindros en enfriado: sección global, se reconstruye en cada snapshot.
        for w in self.enfriando_widgets.values():
            w.destroy()
        self.enfriando_widgets.clear()
        for c in getattr(snapshot, "detalle_enfriando", []):
            cg = CilindroGrafico(
                self.enfriando_container, c["id"], c["d"],
                color=COLORES_ESTADO["Enfriando"], command=self.on_cilindro_click
            )
            cg.pack(side="left", padx=5)
            self.enfriando_widgets[c["id"]] = cg

        # Máquinas: tres estados visuales —
        #   rectificando (ocupada), libre y operativa (resaltada en verde) y
        #   fuera de turno por régimen de trabajo (parada, en rojo oscuro).
        operativas = getattr(snapshot, "detalle_maquinas_operativa", {})
        for m_nombre, data in snapshot.detalle_maquinas.items():
            if m_nombre not in self.maq_widgets:
                self._crear_maquina_widget(m_nombre)

            w = self.maq_widgets[m_nombre]
            operativa = operativas.get(m_nombre, True)
            if data:
                w["prog"].set(data["progreso"] / 100.0)
                w["label"].configure(text=f"{data['id']}\n{data['d']:.1f} mm", text_color=FG)
                w["prog"].configure(progress_color=COLORES_ESTADO["Rectificando"])
                w["outer"].configure(border_color=COLORES_ESTADO["Rectificando"])
            elif operativa:
                # Libre y dentro de turno: disponible para tomar trabajo.
                w["prog"].set(0)
                w["label"].configure(text="● Libre\n(operativa)", text_color=GREEN)
                w["prog"].configure(progress_color="gray")
                w["outer"].configure(border_color=GREEN)
            else:
                # Libre pero fuera de turno: parada por régimen de trabajo.
                w["prog"].set(0)
                w["label"].configure(text="⏸ Fuera de turno", text_color=RED)
                w["prog"].configure(progress_color=RED_DARK)
                w["outer"].configure(border_color=RED_DARK)
