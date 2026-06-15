"""
Componentes visuales para la representación en tiempo real del taller.
"""
import customtkinter as ctk
from config.tema import *


# Texto descriptivo del sentido de toma de la cola según la estrategia.
_SENTIDO_TOMA = {
    "mayor_diametro": "Sentido de toma:  mayor diámetro primero  →",
    "menor_diametro": "Sentido de toma:  menor diámetro primero  →",
    "fifo": "Sentido de toma:  orden de llegada (FIFO)  →",
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
    ALTO = 96

    def __init__(self, master, titulo: str, color_borde=ACCENT):
        super().__init__(master, border_width=2, border_color=color_borde,
                         width=self.ANCHO, height=self.ALTO)
        self.pack_propagate(False)  # mantiene el tamaño fijo aunque esté vacío

        self.titulo = ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=13, weight="bold"))
        self.titulo.pack(pady=(4, 2))

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(expand=True, fill="both", padx=8, pady=(0, 8))
        self.cilindros_widgets: dict = {}  # {cilindro_id: widget}

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

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.title_label = ctk.CTkLabel(
            self, text="ESTADO DEL TALLER EN TIEMPO REAL",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.pack(pady=(20, 10))

        # Dos columnas: jaulas/buffer a la izquierda, rectificadoras/cola a la derecha.
        self.columnas = ctk.CTkFrame(self, fg_color="transparent")
        self.columnas.pack(fill="both", expand=True, padx=20)

        # ── Columna izquierda: jaulas + buffer CRC ───────────────────────
        self.col_jaulas = ctk.CTkFrame(self.columnas, fg_color="transparent")
        self.col_jaulas.pack(side="left", anchor="n", padx=(0, 20))

        ctk.CTkLabel(self.col_jaulas, text="JAULAS",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(0, 10))

        self.main_container = ctk.CTkFrame(self.col_jaulas, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)
        self._crear_filas_jaulas(self.cantidad_jaulas)

        # ── Columna derecha: rectificadoras + cola ───────────────────────
        self.col_maqs = ctk.CTkFrame(self.columnas, fg_color="transparent")
        self.col_maqs.pack(side="left", anchor="n", fill="both", expand=True)

        self.maqs_title = ctk.CTkLabel(self.col_maqs, text="RECTIFICADORAS",
                                       font=ctk.CTkFont(size=18, weight="bold"))
        self.maqs_title.pack(pady=(0, 10))

        self.maqs_container = ctk.CTkFrame(self.col_maqs, fg_color="transparent")
        self.maqs_container.pack(fill="x")

        self.cola_title = ctk.CTkLabel(
            self.col_maqs, text="COLA DE ESPERA RECTIFICADO",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.cola_title.pack(pady=(24, 2))

        self.cola_sentido = ctk.CTkLabel(
            self.col_maqs, text=_SENTIDO_TOMA.get(self.estrategia, ""),
            font=ctk.CTkFont(size=12), text_color=ACCENT
        )
        self.cola_sentido.pack(pady=(0, 6))

        self.cola_container = ctk.CTkScrollableFrame(
            self.col_maqs, fg_color="transparent", orientation="horizontal", height=100
        )
        self.cola_container.pack(fill="x", pady=(0, 20))

    def _crear_filas_jaulas(self, n: int) -> None:
        """Crea N filas de jaula + CRC en el contenedor principal."""
        for i in range(1, n + 1):
            f = ctk.CTkFrame(self.main_container)
            f.pack(fill="x", pady=8)

            ctk.CTkLabel(f, text=f"J{i}", font=ctk.CTkFont(size=24, weight="bold"), width=40).pack(
                side="left", padx=(12, 8)
            )

            jf = SeccionTaller(f, "TRABAJANDO", color_borde=COLORES_ESTADO["Trabajando"])
            jf.pack(side="left", padx=8, pady=8)
            self.jaulas_frames[i] = jf

            cf = SeccionTaller(f, "BUFFER CRC", color_borde=COLORES_ESTADO["CRC"])
            cf.pack(side="left", padx=8, pady=8)
            self.crc_frames[i] = cf

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

    def set_estrategia(self, estrategia: str) -> None:
        """Define la estrategia de selección y actualiza el indicador de sentido de toma."""
        self.estrategia = estrategia
        self.cola_sentido.configure(text=_SENTIDO_TOMA.get(estrategia, "Sentido de toma  →"))

    def mostrar_maquinas(self, nombres) -> None:
        """Crea los recuadros de las rectificadoras disponibles (estado Libre)."""
        for w in self.maqs_container.winfo_children():
            w.destroy()
        self.maq_widgets.clear()
        for nombre in nombres:
            self._crear_maquina_widget(nombre)

    def _crear_maquina_widget(self, nombre: str) -> None:
        f = ctk.CTkFrame(self.maqs_container, width=200, height=100)
        f.pack(side="left", padx=10, pady=10)
        f.pack_propagate(False)

        ctk.CTkLabel(f, text=nombre, font=ctk.CTkFont(weight="bold")).pack()

        content = ctk.CTkFrame(f, fg_color="transparent")
        content.pack(expand=True, fill="both")

        prog = ctk.CTkProgressBar(f)
        prog.set(0)
        prog.configure(progress_color="gray")
        prog.pack(fill="x", padx=10, pady=5)

        lbl = ctk.CTkLabel(content, text="Libre")
        lbl.pack(expand=True)
        self.maq_widgets[nombre] = {"frame": content, "prog": prog, "label": lbl}

    def _ordenar_cola(self, lista: list) -> list:
        """Ordena la cola según el sentido de toma (el próximo a tomar queda primero)."""
        if self.estrategia == "mayor_diametro":
            return sorted(lista, key=lambda c: c["d"], reverse=True)
        if self.estrategia == "menor_diametro":
            return sorted(lista, key=lambda c: c["d"])
        return list(lista)  # FIFO: respeta el orden de llegada

    def actualizar(self, snapshot) -> None:
        """Actualiza todos los componentes visuales con el estado de un snapshot."""
        for i in range(1, self.cantidad_jaulas + 1):
            if i in snapshot.detalle_jaulas and i in self.jaulas_frames:
                self.jaulas_frames[i].actualizar(snapshot.detalle_jaulas[i], self.on_cilindro_click)
            if i in snapshot.detalle_crc and i in self.crc_frames:
                self.crc_frames[i].actualizar(snapshot.detalle_crc[i], self.on_cilindro_click)

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

        # Máquinas
        for m_nombre, data in snapshot.detalle_maquinas.items():
            if m_nombre not in self.maq_widgets:
                self._crear_maquina_widget(m_nombre)

            w = self.maq_widgets[m_nombre]
            if data:
                w["prog"].set(data["progreso"] / 100.0)
                w["label"].configure(text=f"{data['id']}\n{data['d']:.1f} mm")
                w["prog"].configure(progress_color=COLORES_ESTADO["Rectificando"])
            else:
                w["prog"].set(0)
                w["label"].configure(text="Libre")
                w["prog"].configure(progress_color="gray")
