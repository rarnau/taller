"""Tabla."""
import tkinter as tk
from tkinter import ttk
from config.tema import BG, BG2, BG3, FG, FG2, ACCENT, FONT_FAMILY, FONT_SIZE, TABLE_ROW_COLORS


def llenar_tabla(tab, taller):
    for w in tab.winfo_children():
        w.destroy()
    shell = tk.Frame(tab, bg=BG, padx=10, pady=10)
    shell.pack(fill="both", expand=True)
    card = tk.Frame(shell, bg=BG2, bd=1, relief="solid", highlightbackground=BG3, highlightthickness=1)
    card.pack(fill="both", expand=True)

    header = tk.Frame(card, bg=BG3, height=44)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="Inventario de cilindros", bg=BG3, fg=ACCENT, font=(FONT_FAMILY, 13, "bold")).pack(side="left", padx=12, pady=8)

    toolbar = tk.Frame(card, bg=BG2)
    toolbar.pack(fill="x", padx=10, pady=(8, 0))
    tk.Label(toolbar, text="Filtrar estado:", bg=BG2, fg=FG2, font=(FONT_FAMILY, FONT_SIZE)).pack(side="left", padx=(2, 6), pady=6)
    est = ["Todos", "Trabajando", "CRC", "Disponible", "A rectificar", "Rectificando", "Baja"]
    fv = tk.StringVar(value="Todos")
    fc = ttk.Combobox(toolbar, textvariable=fv, values=est, width=18, state="readonly")
    fc.pack(side="left", padx=4, pady=6)
    cv = tk.StringVar(value="")
    tk.Label(toolbar, textvariable=cv, bg=BG2, fg=ACCENT, font=(FONT_FAMILY, FONT_SIZE, "bold")).pack(side="right", padx=8, pady=6)

    body = tk.Frame(card, bg=BG2)
    body.pack(fill="both", expand=True, padx=10, pady=10)
    cols = ("ID", "D Original", "D Final", "Desgaste", "Estado", "SubStock", "Jaula")
    tree = ttk.Treeview(body, columns=cols, show="headings", height=30)
    s = ttk.Style()
    s.configure("T.Treeview", background=BG2, foreground=FG, fieldbackground=BG2, rowheight=28, font=(FONT_FAMILY, FONT_SIZE))
    s.configure("T.Treeview.Heading", background=BG3, foreground=ACCENT, font=(FONT_FAMILY, FONT_SIZE, "bold"), relief="flat")
    s.map("T.Treeview.Heading", background=[("active", BG3)])
    s.map("T.Treeview", background=[("selected", "#264F78")], foreground=[("selected", "#FFF")])
    tree.configure(style="T.Treeview")
    ss = {}

    def sc(cn):
        r = ss.get(cn, False)
        items = [(tree.set(k, cn), k) for k in tree.get_children("")]
        try:
            items.sort(key=lambda item: float(item[0]), reverse=r)
        except (TypeError, ValueError):
            items.sort(key=lambda item: str(item[0]), reverse=r)
        for i2, (_, k) in enumerate(items):
            tree.move(k, "", i2)
        ss[cn] = not r

    ws = {"ID": 120, "D Original": 110, "D Final": 100, "Desgaste": 100, "Estado": 130, "SubStock": 150, "Jaula": 80}
    for c in cols:
        tree.heading(c, text=c, command=lambda _c=c: sc(_c))
        tree.column(c, width=ws.get(c, 110), anchor="center", minwidth=60)
    for tag, bg in TABLE_ROW_COLORS.items():
        tree.tag_configure(tag, background=bg, foreground="#E6EDF3")

    def _fill(ef="Todos"):
        tree.delete(*tree.get_children())
        cnt = 0
        for cil in sorted(taller.cils.values(), key=lambda c: c.diametro, reverse=True):
            if ef != "Todos" and cil.estado.value != ef:
                continue
            ss2 = taller.get_ss(cil.diametro)
            tag = cil.estado.value.replace(" ", "_")
            dg = round(cil.diam_original - cil.diametro, 2)
            tree.insert("", "end", values=(cil.id, f"{cil.diam_original:.1f}", f"{cil.diametro:.1f}", f"{dg:.2f}", cil.estado.value, ss2.nombre if ss2 else "-", cil.jaula or "-"), tags=(tag,))
            cnt += 1
        cv.set(f"{cnt} cilindros")

    _fill()
    fc.bind("<<ComboboxSelected>>", lambda e: _fill(fv.get()))
    vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(fill="both", expand=True)
