"""Pestaña «Inventario»: carga del stock + vista del stock inicial/final.

Desde aquí se **carga el stock** (hoja ``Stock_Inicial`` del Excel; el programa
de cambios ya no se toma del Excel, viene de la pestaña Generación). Se puede ver
el **stock inicial** (el cargado) o el **final** (tras simular) de forma
excluyente, filtrar por estado y **descargar a Excel** lo mostrado.

Como las otras pestañas-widget (``tab_config``/``tab_generacion``) opera sobre la
App: ``app.cargar_stock_desde`` para cargar, ``app._stock_df`` para el inicial y
``app.taller`` para el final.
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
import pandas as pd

from config.tema import (BG_CARD, ACCENT, BTN_BLUE, BTN_BLUE_HOVER, TABLE_ROW_COLORS)
from modelos.enums import EstadoCilindro

_VISTA_INICIAL = "Stock inicial"
_VISTA_FINAL = "Stock final"

# Columnas por vista (el inicial sale del DataFrame crudo; el final, del taller).
_COLS_INICIAL = ("ID", "Diámetro", "Estado", "Jaula", "Perfil")
_COLS_FINAL = ("ID", "D Original", "D Final", "Desgaste", "Estado", "SubStock", "Jaula")
_ANCHOS = {"ID": 120, "Diámetro": 110, "D Original": 110, "D Final": 100,
           "Desgaste": 100, "Estado": 130, "SubStock": 150, "Jaula": 80, "Perfil": 80}


class TabInventario(ctk.CTkFrame):
    """Carga de stock + tabla de inventario con vista inicial/final."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._construir()
        self.refrescar()

    # ── Construcción ─────────────────────────────────────────────────────

    def _construir(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(toolbar, text="📁 Cargar stock", width=130,
                      fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
                      command=self._cargar_stock).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(toolbar, text="Vista:").pack(side="left", padx=(0, 4))
        self._vista = tk.StringVar(value=_VISTA_INICIAL)
        ctk.CTkComboBox(toolbar, variable=self._vista, width=140, state="readonly",
                        values=[_VISTA_INICIAL, _VISTA_FINAL],
                        command=lambda _v: self._on_cambiar_vista()).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(toolbar, text="Filtrar estado:").pack(side="left", padx=(0, 4))
        self._filtro = tk.StringVar(value="Todos")
        ctk.CTkComboBox(toolbar, variable=self._filtro, width=140, state="readonly",
                        values=["Todos"] + [e.value for e in EstadoCilindro],
                        command=lambda _v: self._fill()).pack(side="left")

        ctk.CTkButton(toolbar, text="⬇ Descargar Excel", width=150,
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=ACCENT, hover_color=BG_CARD,
                      command=self._descargar).pack(side="right")
        self._lbl_count = tk.StringVar(value="")
        ctk.CTkLabel(toolbar, textvariable=self._lbl_count,
                     font=ctk.CTkFont(weight="bold")).pack(side="right", padx=12)

        body = ctk.CTkFrame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Treeview", background="#1e1e1e", foreground="white",
                    fieldbackground="#1e1e1e", rowheight=28)
        s.configure("Treeview.Heading", background="#333", foreground="white", relief="flat")
        s.map("Treeview.Heading", background=[("active", "#444")])

        self._tree = ttk.Treeview(body, columns=_COLS_INICIAL, show="headings",
                                  height=30, style="Treeview")
        for tag, bg in TABLE_ROW_COLORS.items():
            self._tree.tag_configure(tag, background=bg)
        vsb = ctk.CTkScrollbar(body, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

    # ── Datos por vista ──────────────────────────────────────────────────

    def _columnas(self):
        return _COLS_FINAL if self._vista.get() == _VISTA_FINAL else _COLS_INICIAL

    def _filas(self):
        """Devuelve (columnas, filas) de la vista actual aplicando el filtro de estado."""
        cols = self._columnas()
        ef = self._filtro.get()
        filas = []
        if self._vista.get() == _VISTA_FINAL:
            taller = self.app.taller
            for cil in sorted(taller.cilindros.values(), key=lambda c: c.diametro, reverse=True):
                if ef != "Todos" and cil.estado.value != ef:
                    continue
                ss = taller.obtener_substock_por_diametro(cil.diametro)
                dg = round(cil.diametro_original - cil.diametro, 2)
                filas.append((cil.id, f"{cil.diametro_original:.1f}", f"{cil.diametro:.1f}",
                              f"{dg:.2f}", cil.estado.value, ss.nombre if ss else "-",
                              cil.jaula or "-"))
        else:
            df = self.app._stock_df
            if df is not None:
                df = df.sort_values("Diámetro_mm", ascending=False)
                for _, r in df.iterrows():
                    estado = str(r.get("Estado", ""))
                    if ef != "Todos" and estado != ef:
                        continue
                    jaula = r.get("Jaula_Asignada")
                    perfil = r.get("Perfil")
                    filas.append((
                        str(r.get("ID_Cilindro", "")), f"{float(r.get('Diámetro_mm', 0)):.1f}",
                        estado,
                        "-" if pd.isna(jaula) else int(jaula),
                        "-" if (perfil is None or pd.isna(perfil) or str(perfil) == "") else str(perfil),
                    ))
        return cols, filas

    # ── Render ───────────────────────────────────────────────────────────

    def refrescar(self):
        self._on_cambiar_vista()

    def _on_cambiar_vista(self):
        cols = self._columnas()
        self._tree.configure(columns=cols)
        for c in cols:
            self._tree.heading(c, text=c)
            self._tree.column(c, width=_ANCHOS.get(c, 110), anchor="center")
        self._fill()

    def _fill(self):
        cols, filas = self._filas()
        self._tree.delete(*self._tree.get_children())
        idx_estado = cols.index("Estado")
        for fila in filas:
            tag = str(fila[idx_estado]).replace(" ", "_")
            self._tree.insert("", "end", values=fila, tags=(tag,))
        self._lbl_count.set(f"{len(filas)} cilindros")

    # ── Acciones ─────────────────────────────────────────────────────────

    def _cargar_stock(self):
        fp = filedialog.askopenfilename(
            title="Seleccionar Excel de stock (hoja Stock_Inicial)",
            filetypes=[("Excel", "*.xlsx *.xls")])
        if not fp:
            return
        self.app.cargar_stock_desde(fp)
        self._vista.set(_VISTA_INICIAL)
        self.refrescar()

    def _descargar(self):
        cols, filas = self._filas()
        if not filas:
            messagebox.showinfo("Inventario", "No hay datos para descargar.")
            return
        es_final = self._vista.get() == _VISTA_FINAL
        fp = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile="stock_final.xlsx" if es_final else "stock_inicial.xlsx")
        if not fp:
            return
        df = pd.DataFrame(filas, columns=cols)
        hoja = "Stock_Final" if es_final else "Stock_Inicial"
        with pd.ExcelWriter(fp, engine="openpyxl") as xl:
            df.to_excel(xl, sheet_name=hoja, index=False)
        messagebox.showinfo("Inventario", f"Stock exportado a:\n{fp}")


def crear_tab_inventario(tab, app):
    """Crea y empaqueta la pestaña de inventario. Devuelve el widget."""
    widget = TabInventario(tab, app)
    widget.pack(fill="both", expand=True)
    return widget
