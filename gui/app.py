"""Ventana principal."""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from config.tema import *
from config.persistencia import cargar_config, guardar_config, obtener_rangos, obtener_prioridades
from modelos.taller import TallerCilindros
from gui.tab_consola import crear_consola
from gui.dashboard_principal import crear_dashboard_principal
from gui.dashboard_detalle import crear_dashboard_detalle
from gui.tab_tabla import llenar_tabla
from gui.tab_kpis import llenar_kpis


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simulador Cilindros v3")
        self.state("zoomed")
        self.configure(bg=BG)
        self.minsize(1280, 820)
        self.option_add("*tearOff", False)
        self.taller = TallerCilindros()
        self.archivo_cargado = None
        self.user_cfg = cargar_config()
        self.rango_vars = []
        self.prio_combos = {}
        self.prio_labels = []
        self.prio_btn = None
        self._ss()
        self._ui()
        self.taller.configurar_substocks(obtener_rangos(self.user_cfg))

    def _ss(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=BG2, font=(FONT_FAMILY, FONT_SIZE))
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG, font=(FONT_FAMILY, FONT_SIZE))
        s.configure("Title.TLabel", font=(FONT_FAMILY, FONT_SIZE_XL, "bold"), foreground=ACCENT, background=BG)
        s.configure("Section.TLabel", font=(FONT_FAMILY, FONT_SIZE_LG, "bold"), foreground=ORANGE, background=BG)
        s.configure("Info.TLabel", font=(FONT_FAMILY, FONT_SIZE), foreground=FG2, background=BG)
        s.configure("Card.TFrame", background=BG2, relief="flat")
        s.configure("Panel.TFrame", background=BG_CARD, relief="flat")
        s.configure("TButton", font=(FONT_FAMILY, FONT_SIZE, "bold"), background=BTN_BLUE, foreground="white", padding=[16, 8], relief="flat")
        s.map("TButton", background=[("active", BTN_BLUE_HOVER), ("pressed", ACCENT)])
        s.configure("Green.TButton", background=BTN_BG, foreground="white", font=(FONT_FAMILY, FONT_SIZE, "bold"), padding=[16, 8])
        s.map("Green.TButton", background=[("active", BTN_BG_HOVER)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white", font=(FONT_FAMILY, FONT_SIZE, "bold"), padding=[12, 6])
        s.map("Accent.TButton", background=[("active", ACCENT_SOFT)])
        s.configure("TCombobox", fieldbackground=BG2, foreground=FG, selectbackground=BTN_BLUE_HOVER, selectforeground="#FFF", arrowcolor=ACCENT, font=(FONT_FAMILY, FONT_SIZE))
        s.map("TCombobox", fieldbackground=[("readonly", BG2)], foreground=[("readonly", FG)])
        s.configure("TEntry", fieldbackground=BG2, foreground=FG, insertcolor=ACCENT, font=(FONT_FAMILY, FONT_SIZE))
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=TAB_BG, foreground=TAB_FG, font=(FONT_FAMILY, FONT_SIZE_MD, "bold"), padding=TAB_PADDING, borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", TAB_SEL_BG)], foreground=[("selected", TAB_SEL_FG)], expand=[("selected", [0, 0, 0, 2])])

    def _ui(self):
        top = tk.Frame(self, bg=BG2, height=84, bd=0)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Frame(top, bg=ACCENT, height=3).pack(fill="x", side="bottom")

        tf = tk.Frame(top, bg=BG2)
        tf.pack(side="left", padx=(24, 12), pady=14)
        tk.Label(tf, text="◉", bg=BG2, fg=ACCENT, font=(FONT_FAMILY, FONT_SIZE_XL, "bold")).pack(side="left")
        tk.Label(tf, text="SIMULADOR CILINDROS", bg=BG2, fg=ACCENT, font=(FONT_FAMILY, FONT_SIZE_XL, "bold")).pack(side="left", padx=(6, 8))
        tk.Label(tf, text="v3", bg=BG2, fg=FG_DIM, font=(FONT_FAMILY, FONT_SIZE, "bold")).pack(side="left")
        tk.Label(tf, text="Planificación y trazabilidad", bg=BG2, fg=FG2, font=(FONT_FAMILY, FONT_SIZE_MD)).pack(side="left", padx=(14, 0))

        bf = tk.Frame(top, bg=BG2)
        bf.pack(side="right", padx=18, pady=16)
        ttk.Button(bf, text="Cargar", command=self._cargar).pack(side="left", padx=4)
        tk.Label(bf, text="Estrategia:", bg=BG2, fg=FG2, font=(FONT_FAMILY, FONT_SIZE)).pack(side="left", padx=(12, 4))
        self.combo_est = ttk.Combobox(bf, width=18, state="readonly", values=["mayor_diametro", "menor_diametro", "fifo"])
        self.combo_est.set("mayor_diametro")
        self.combo_est.pack(side="left", padx=4)
        ttk.Button(bf, text="Simular", style="Green.TButton", command=self._simular).pack(side="left", padx=4)
        ttk.Button(bf, text="Exportar", command=self._exportar).pack(side="left", padx=4)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(10, 8))
        self.tab_cfg = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_cfg, text="  Configuración  ")
        self._build_cfg()
        self.tab_log = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_log, text="  Consola  ")
        self.log_w = crear_consola(self.tab_log)
        self._log("Bienvenido al Simulador v3")
        self.tab_dash = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_dash, text="  Dashboard  ")
        self.tab_det = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_det, text="  Detalle  ")
        self.tab_tabla = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_tabla, text="  Tabla  ")
        self.tab_kpi = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_kpi, text="  KPIs  ")

        sb = tk.Frame(self, bg=BG2, height=38, bd=0)
        sb.pack(side="bottom", fill="x")
        sb.pack_propagate(False)
        tk.Frame(sb, bg=ACCENT, width=4).pack(side="left", fill="y")
        self.status = tk.StringVar(value="Listo")
        tk.Label(sb, textvariable=self.status, bg=BG2, fg=FG2, font=(FONT_FAMILY, 9), anchor="w").pack(side="left", fill="x", padx=(10, 10), pady=4)

    def _build_cfg(self):
        cv = tk.Canvas(self.tab_cfg, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(self.tab_cfg, orient="vertical", command=cv.yview)
        self.cfg_frame = ttk.Frame(cv, style="Card.TFrame")
        self.cfg_frame.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=self.cfg_frame, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        sf = self.cfg_frame
        ttk.Label(sf, text="RANGOS DE SUBSTOCK POR JAULA", style="Section.TLabel").grid(row=0, column=0, columnspan=6, pady=(20, 8), padx=20, sticky="w")
        ttk.Label(sf, text="Cada jaula acepta solo cilindros dentro de su rango.", style="Info.TLabel").grid(row=1, column=0, columnspan=6, padx=20, sticky="w")
        for i, h in enumerate(["Jaula", "Desde (mm)", "Hasta (mm)"]):
            ttk.Label(sf, text=h, font=(FONT_FAMILY, FONT_SIZE_MD, "bold"), foreground=ACCENT).grid(row=2, column=i + 1, padx=12, pady=(12, 4))
        rangos = obtener_rangos(self.user_cfg)
        self.rango_vars = []
        for idx, r in enumerate(rangos):
            row = 3 + idx
            ttk.Label(sf, text=f"J{r['jaula']}", font=(FONT_FAMILY, FONT_SIZE_LG, "bold"), foreground=ACCENT).grid(row=row, column=1, padx=12, pady=6)
            vd = tk.StringVar(value=str(r["desde"]))
            vh = tk.StringVar(value=str(r["hasta"]))
            ttk.Entry(sf, textvariable=vd, width=12, justify="center").grid(row=row, column=2, padx=12, pady=6)
            ttk.Entry(sf, textvariable=vh, width=12, justify="center").grid(row=row, column=3, padx=12, pady=6)
            self.rango_vars.append({"jaula": r["jaula"], "desde": vd, "hasta": vh})
        ttk.Button(sf, text="Guardar Rangos", style="Accent.TButton", command=self._gr).grid(row=7, column=1, columnspan=3, pady=12)
        ttk.Separator(sf, orient="horizontal").grid(row=8, column=0, columnspan=6, sticky="ew", padx=20, pady=18)
        ttk.Label(sf, text="PRIORIDAD DE MAQUINAS", style="Section.TLabel").grid(row=9, column=0, columnspan=6, pady=(8, 5), padx=20, sticky="w")
        ttk.Label(sf, text="Define que tipo de rectificado prioriza cada maquina.", style="Info.TLabel").grid(row=10, column=0, columnspan=6, padx=20, sticky="w")
        self.prio_start_row = 12
        self.lbl_prio = ttk.Label(sf, text="(Cargue un Excel)", foreground=FG_DIM)
        self.lbl_prio.grid(row=12, column=1, columnspan=3, pady=8)

    def _llenar_prios(self):
        self.lbl_prio.grid_forget()
        for l in self.prio_labels:
            l.destroy()
        self.prio_labels.clear()
        for c in self.prio_combos.values():
            c.destroy()
        self.prio_combos.clear()
        if self.prio_btn:
            self.prio_btn.destroy()
        sf = self.cfg_frame
        pg = obtener_prioridades(self.user_cfg)
        row = self.prio_start_row
        for mn in self.taller.maqs:
            l = ttk.Label(sf, text=mn, font=(FONT_FAMILY, FONT_SIZE_LG, "bold"), foreground=ACCENT)
            l.grid(row=row, column=1, padx=12, pady=6)
            self.prio_labels.append(l)
            cb = ttk.Combobox(sf, width=15, state="readonly", values=["produccion", "desbaste"])
            cb.set(pg.get(mn, "produccion"))
            cb.grid(row=row, column=2, padx=12, pady=6)
            self.prio_combos[mn] = cb
            row += 1
        self.prio_btn = ttk.Button(sf, text="Guardar Prioridades", style="Accent.TButton", command=self._gp2)
        self.prio_btn.grid(row=row, column=1, columnspan=3, pady=12)

    def _gr(self):
        rangos = []
        for rv in self.rango_vars:
            try:
                d = float(rv["desde"].get())
                h = float(rv["hasta"].get())
            except Exception:
                messagebox.showerror("Error", "No numérico")
                return
            if d <= h:
                messagebox.showerror("Error", "Desde > Hasta")
                return
            rangos.append({"jaula": rv["jaula"], "desde": d, "hasta": h})
        self.user_cfg["rangos"] = rangos
        guardar_config(self.user_cfg)
        self.taller.configurar_substocks(rangos)
        self._log("Rangos guardados.")
        self.status.set("Rangos OK")

    def _gp2(self):
        p = {mn: cb.get() for mn, cb in self.prio_combos.items()}
        self.user_cfg["prioridades_maquinas"] = p
        guardar_config(self.user_cfg)
        self.taller.aplicar_prioridades(p)
        self._log(f"Prioridades: {p}")
        self.status.set("Prioridades OK")

    def _log(self, m):
        self.log_w.insert("end", m + "\n")
        self.log_w.see("end")
        self.update_idletasks()

    def _cargar(self):
        fp = filedialog.askopenfilename(title="Excel", filetypes=[("Excel", "*.xlsx *.xls")])
        if not fp:
            return
        try:
            self.taller.configurar_substocks(obtener_rangos(self.user_cfg))
            self.taller.cargar(fp)
            p = obtener_prioridades(self.user_cfg)
            if p:
                self.taller.aplicar_prioridades(p)
            self.archivo_cargado = fp
            self._log(f"\nCargado: {os.path.basename(fp)} | {len(self.taller.cils)} cils")
            self.status.set(f"Cargado: {os.path.basename(fp)}")
            self._llenar_prios()
        except Exception as ex:
            messagebox.showerror("Error", str(ex))

    def _simular(self):
        if not self.archivo_cargado:
            messagebox.showwarning("", "Cargue Excel")
            return
        self.status.set("Simulando...")
        self._log(f"\n{'=' * 50}")
        self.taller.configurar_substocks(obtener_rangos(self.user_cfg))
        self.taller.cargar(self.archivo_cargado)
        p = {mn: cb.get() for mn, cb in self.prio_combos.items()}
        if p:
            self.taller.aplicar_prioridades(p)
            self.user_cfg["prioridades_maquinas"] = p
            guardar_config(self.user_cfg)
        self.taller.simular(self.combo_est.get(), log_callback=self._log)
        nc = sum(1 for a in self.taller.alertas if a.tipo == "CRITICO")
        self.status.set(f"Simulación completa - Alertas críticas: {nc}")
        self._dash(self.tab_dash, crear_dashboard_principal)
        self._dash(self.tab_det, crear_dashboard_detalle)
        llenar_tabla(self.tab_tabla, self.taller)
        llenar_kpis(self.tab_kpi, self.taller)
        self.nb.select(self.tab_dash)

    def _dash(self, tab, func):
        for w in tab.winfo_children():
            w.destroy()
        fig = func(self.taller)
        cv = FigureCanvasTkAgg(fig, master=tab)
        cv.draw()
        NavigationToolbar2Tk(cv, tab).update()
        cv.get_tk_widget().pack(fill="both", expand=True)

    def _exportar(self):
        if not self.taller.snaps:
            messagebox.showwarning("", "Simule primero")
            return
        fp = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")], initialfile="resultados.xlsx")
        if fp:
            self.taller.exportar_resultados(fp)
            messagebox.showinfo("OK", f"Guardado en:\n{fp}")
