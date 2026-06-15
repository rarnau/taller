"""
Componentes visuales para la representación en tiempo real del taller.
"""
import customtkinter as ctk
from config.tema import *


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
    """Contenedor para una sección del taller (Jaula o CRC)."""

    def __init__(self, master, titulo: str, color_borde=ACCENT):
        super().__init__(master, border_width=2, border_color=color_borde)
        self.titulo = ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=14, weight="bold"))
        self.titulo.pack(pady=5)

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(expand=True, fill="both", padx=10, pady=10)
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
                cg.pack(side="left", padx=5)
                self.cilindros_widgets[cid] = cg


class VistaRealTime(ctk.CTkScrollableFrame):
    """Panel principal que organiza todas las secciones del taller."""

    def __init__(self, master, on_cilindro_click, cantidad_jaulas: int = 4):
        super().__init__(master)
        self.on_cilindro_click = on_cilindro_click
        self.cantidad_jaulas = cantidad_jaulas

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
        self.title_label.pack(pady=20)

        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20)

        self._crear_filas_jaulas(self.cantidad_jaulas)

        self.maqs_title = ctk.CTkLabel(self, text="RECTIFICADORAS", font=ctk.CTkFont(size=18, weight="bold"))
        self.maqs_title.pack(pady=(30, 10))

        self.maqs_container = ctk.CTkFrame(self, fg_color="transparent")
        self.maqs_container.pack(fill="x", padx=20)

        self.cola_title = ctk.CTkLabel(
            self, text="COLA DE ESPERA RECTIFICADO",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.cola_title.pack(pady=(30, 10))

        self.cola_container = ctk.CTkScrollableFrame(
            self, fg_color="transparent", orientation="horizontal", height=100
        )
        self.cola_container.pack(fill="x", padx=20, pady=(0, 30))

    def _crear_filas_jaulas(self, n: int) -> None:
        """Crea N filas de jaula + CRC en el contenedor principal."""
        for i in range(1, n + 1):
            f = ctk.CTkFrame(self.main_container)
            f.pack(fill="x", pady=10)

            ctk.CTkLabel(f, text=f"J{i}", font=ctk.CTkFont(size=24, weight="bold"), width=50).pack(
                side="left", padx=20
            )

            jf = SeccionTaller(f, "TRABAJANDO", color_borde=COLORES_ESTADO["Trabajando"])
            jf.pack(side="left", padx=10, pady=10, fill="y")
            self.jaulas_frames[i] = jf

            cf = SeccionTaller(f, "BUFFER CRC", color_borde=COLORES_ESTADO["CRC"])
            cf.pack(side="left", padx=10, pady=10, fill="y")
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

    def actualizar(self, snapshot) -> None:
        """Actualiza todos los componentes visuales con el estado de un snapshot."""
        for i in range(1, self.cantidad_jaulas + 1):
            if i in snapshot.detalle_jaulas and i in self.jaulas_frames:
                self.jaulas_frames[i].actualizar(snapshot.detalle_jaulas[i], self.on_cilindro_click)
            if i in snapshot.detalle_crc and i in self.crc_frames:
                self.crc_frames[i].actualizar(snapshot.detalle_crc[i], self.on_cilindro_click)

        # Actualizar Cola de rectificado
        ids_nuevos_cola = [c["id"] for c in snapshot.detalle_cola_rectificado]
        for cid in [cid for cid in self.cola_widgets if cid not in ids_nuevos_cola]:
            self.cola_widgets[cid].destroy()
            del self.cola_widgets[cid]

        for c in snapshot.detalle_cola_rectificado:
            cid = c["id"]
            if cid in self.cola_widgets:
                self.cola_widgets[cid].label.configure(text=f"{cid}\n{c['d']:.1f}")
            else:
                cg = CilindroGrafico(
                    self.cola_container, cid, c["d"],
                    color=COLORES_ESTADO["A rectificar"],
                    command=self.on_cilindro_click
                )
                cg.pack(side="left", padx=5)
                self.cola_widgets[cid] = cg

        # Actualizar Máquinas
        for m_nombre, data in snapshot.detalle_maquinas.items():
            if m_nombre not in self.maq_widgets:
                f = ctk.CTkFrame(self.maqs_container, width=200, height=100)
                f.pack(side="left", padx=10, pady=10)
                f.pack_propagate(False)

                ctk.CTkLabel(f, text=m_nombre, font=ctk.CTkFont(weight="bold")).pack()

                content = ctk.CTkFrame(f, fg_color="transparent")
                content.pack(expand=True, fill="both")

                prog = ctk.CTkProgressBar(f)
                prog.pack(fill="x", padx=10, pady=5)

                lbl = ctk.CTkLabel(content, text="Libre")
                lbl.pack(expand=True)
                self.maq_widgets[m_nombre] = {"frame": content, "prog": prog, "label": lbl}

            w = self.maq_widgets[m_nombre]
            if data:
                w["prog"].set(data["progreso"] / 100.0)
                w["label"].configure(text=f"{data['id']}\n{data['d']:.1f} mm")
                w["prog"].configure(progress_color=COLORES_ESTADO["Rectificando"])
            else:
                w["prog"].set(0)
                w["label"].configure(text="Libre")
                w["prog"].configure(progress_color="gray")
