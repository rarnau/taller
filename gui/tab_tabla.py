"""Tabla adaptada."""
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from config.tema import BG, BG2, BG3, FG, FG2, ACCENT, FONT_FAMILY, FONT_SIZE, TABLE_ROW_COLORS
from modelos.enums import EstadoCilindro


def llenar_tabla(tab, taller):
    for w in tab.winfo_children():
        w.destroy()

    toolbar = ctk.CTkFrame(tab, fg_color="transparent")
    toolbar.pack(fill="x", padx=10, pady=10)

    ctk.CTkLabel(toolbar, text="Filtrar estado:").pack(side="left", padx=10)

    # Derivado del enum para no duplicar la lista de estados (auto-incluye nuevos).
    est = ["Todos"] + [e.value for e in EstadoCilindro]
    fv = tk.StringVar(value="Todos")
    fc = ctk.CTkComboBox(toolbar, variable=fv, values=est, state="readonly", command=lambda v: _fill(v))
    fc.pack(side="left", padx=10)

    cv = tk.StringVar(value="")
    ctk.CTkLabel(toolbar, textvariable=cv, font=ctk.CTkFont(weight="bold")).pack(side="right", padx=10)

    body = ctk.CTkFrame(tab)
    body.pack(fill="both", expand=True, padx=10, pady=10)

    cols = ("ID", "D Original", "D Final", "Desgaste", "Estado", "SubStock", "Jaula")
    tree = ttk.Treeview(body, columns=cols, show="headings", height=30)

    s = ttk.Style()
    s.theme_use("clam")
    s.configure("Treeview", background="#1e1e1e", foreground="white", fieldbackground="#1e1e1e", rowheight=28)
    s.configure("Treeview.Heading", background="#333", foreground="white", relief="flat")
    s.map("Treeview.Heading", background=[("active", "#444")])

    tree.configure(style="Treeview")

    ws = {"ID": 120, "D Original": 110, "D Final": 100, "Desgaste": 100, "Estado": 130, "SubStock": 150, "Jaula": 80}
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=ws.get(c, 110), anchor="center")

    # Colores de filas
    for tag, bg in TABLE_ROW_COLORS.items():
        tree.tag_configure(tag, background=bg)

    def _fill(ef="Todos"):
        tree.delete(*tree.get_children())
        cnt = 0
        for cil in sorted(taller.cilindros.values(), key=lambda c: c.diametro, reverse=True):
            if ef != "Todos" and cil.estado.value != ef:
                continue
            ss2 = taller.obtener_substock_por_diametro(cil.diametro)
            tag = cil.estado.value.replace(" ", "_")
            dg = round(cil.diametro_original - cil.diametro, 2)
            tree.insert("", "end", values=(cil.id, f"{cil.diametro_original:.1f}", f"{cil.diametro:.1f}", f"{dg:.2f}", cil.estado.value, ss2.nombre if ss2 else "-", cil.jaula or "-"), tags=(tag,))
            cnt += 1
        cv.set(f"{cnt} cilindros")

    _fill()

    vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
