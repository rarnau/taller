"""
Componentes visuales para la representación en tiempo real del taller.
"""
import customtkinter as ctk
from config.tema import *

class CilindroGrafico(ctk.CTkFrame):
    """Representación visual de un cilindro."""
    def __init__(self, master, cilindro_id, diametro, color=ACCENT, command=None):
        super().__init__(master, fg_color=color, corner_radius=8, width=60, height=30)
        self.id = cilindro_id
        self.diam = diametro

        self.label = ctk.CTkLabel(self, text=f"{cilindro_id}\n{diametro:.1f}",
                                font=ctk.CTkFont(size=9, weight="bold"),
                                text_color="white")
        self.label.pack(expand=True, fill="both")

        if command:
            self.bind("<Button-1>", lambda e: command(self.id))
            self.label.bind("<Button-1>", lambda e: command(self.id))

class SeccionTaller(ctk.CTkFrame):
    """Contenedor para una sección del taller (Jaula o CRC)."""
    def __init__(self, master, titulo, color_borde=ACCENT):
        super().__init__(master, border_width=2, border_color=color_borde)
        self.titulo = ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=14, weight="bold"))
        self.titulo.pack(pady=5)

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(expand=True, fill="both", padx=10, pady=10)
        self.cilindros_widgets = {} # {cilindro_id: widget}

    def actualizar(self, lista_cilindros, on_click_callback):
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
                # Si ya existe, podrías actualizar el diámetro si fuera necesario
                self.cilindros_widgets[cid].label.configure(text=f"{cid}\n{c['d']:.1f}")
            else:
                cg = CilindroGrafico(self.container, cid, c["d"], command=on_click_callback)
                cg.pack(side="left", padx=5)
                self.cilindros_widgets[cid] = cg

class VistaRealTime(ctk.CTkScrollableFrame):
    """Panel principal que organiza todas las secciones del taller."""
    def __init__(self, master, on_cilindro_click):
        super().__init__(master)
        self.on_cilindro_click = on_cilindro_click

        # Jaulas y CRCs
        self.jaulas_frames = {}
        self.crc_frames = {}

        self._setup_ui()

    def _setup_ui(self):
        # Título
        self.title = ctk.CTkLabel(self, text="ESTADO DEL TALLER EN TIEMPO REAL", font=ctk.CTkFont(size=20, weight="bold"))
        self.title.pack(pady=20)

        # Contenedor de Jaulas
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20)

        for i in range(1, 5):
            f = ctk.CTkFrame(self.main_container)
            f.pack(fill="x", pady=10)

            # Label Jaula
            ctk.CTkLabel(f, text=f"J{i}", font=ctk.CTkFont(size=24, weight="bold"), width=50).pack(side="left", padx=20)

            # Frame Jaula (Trabajando)
            jf = SeccionTaller(f, "TRABAJANDO", color_borde=COLORES_ESTADO["Trabajando"])
            jf.pack(side="left", padx=10, pady=10, fill="y")
            self.jaulas_frames[i] = jf

            # Frame CRC
            cf = SeccionTaller(f, "BUFFER CRC", color_borde=COLORES_ESTADO["CRC"])
            cf.pack(side="left", padx=10, pady=10, fill="y")
            self.crc_frames[i] = cf

        # Máquinas
        self.maqs_title = ctk.CTkLabel(self, text="RECTIFICADORAS", font=ctk.CTkFont(size=18, weight="bold"))
        self.maqs_title.pack(pady=(30, 10))

        self.maqs_container = ctk.CTkFrame(self, fg_color="transparent")
        self.maqs_container.pack(fill="x", padx=20)
        self.maq_widgets = {}

        # Cola de rectificado
        self.cola_title = ctk.CTkLabel(self, text="COLA DE ESPERA RECTIFICADO", font=ctk.CTkFont(size=18, weight="bold"))
        self.cola_title.pack(pady=(30, 10))

        self.cola_container = ctk.CTkScrollableFrame(self, fg_color="transparent", orientation="horizontal", height=100)
        self.cola_container.pack(fill="x", padx=20, pady=(0, 30))
        self.cola_widgets = {} # {id: widget}

    def actualizar(self, snapshot):
        # Actualizar Jaulas y CRCs
        for i in range(1, 5):
            if i in snapshot.detalle_jaulas:
                self.jaulas_frames[i].actualizar(snapshot.detalle_jaulas[i], self.on_cilindro_click)
            if i in snapshot.detalle_crc:
                self.crc_frames[i].actualizar(snapshot.detalle_crc[i], self.on_cilindro_click)

        # Actualizar Máquinas
        # Actualizar Cola
        ids_nuevos_cola = [c["id"] for c in snapshot.detalle_cola_rectificado]
        ids_a_borrar_cola = [cid for cid in self.cola_widgets if cid not in ids_nuevos_cola]
        for cid in ids_a_borrar_cola:
            self.cola_widgets[cid].destroy()
            del self.cola_widgets[cid]

        for c in snapshot.detalle_cola_rectificado:
            cid = c["id"]
            if cid in self.cola_widgets:
                self.cola_widgets[cid].label.configure(text=f"{cid}\n{c['d']:.1f}")
            else:
                cg = CilindroGrafico(self.cola_container, cid, c["d"], color=COLORES_ESTADO["A rectificar"], command=self.on_cilindro_click)
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

                self.maq_widgets[m_nombre] = {"frame": content, "prog": prog, "label": ctk.CTkLabel(content, text="Libre")}
                self.maq_widgets[m_nombre]["label"].pack(expand=True)

            w = self.maq_widgets[m_nombre]
            if data:
                w["prog"].set(data["progreso"] / 100.0)
                w["label"].configure(text=f"{data['id']}\n{data['d']:.1f} mm")
                w["prog"].configure(progress_color=COLORES_ESTADO["Rectificando"])
            else:
                w["prog"].set(0)
                w["label"].configure(text="Libre")
                w["prog"].configure(progress_color="gray")
