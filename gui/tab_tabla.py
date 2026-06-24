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

from config.tema import (BG_CARD, FG, FG2, ACCENT, BTN_BLUE, BTN_BLUE_HOVER, TABLE_ROW_COLORS)

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
        # col → set de valores permitidos (ausente = sin filtro = todos)
        self._filtros_col: dict = {}
        self._filtro_panel = None    # panel inline de filtro abierto (o None)
        self._filtro_binds = False   # binds de cierre creados una sola vez
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

        ctk.CTkLabel(toolbar, text="Filtros: clic en una cabecera ▾",
                     text_color=FG2).pack(side="left")

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

        # Re-render al volver visible la pestaña: ttk.Treeview llenado mientras
        # estaba oculta (p. ej. tras simular en otra pestaña) puede pintarse mal.
        self.bind("<Map>", self._on_map)

    # ── Datos por vista ──────────────────────────────────────────────────

    def _columnas(self):
        return _COLS_FINAL if self._vista.get() == _VISTA_FINAL else _COLS_INICIAL

    def _filas_crudas(self):
        """(columnas, filas) de la vista actual **sin** aplicar los filtros de columna."""
        cols = self._columnas()
        filas = []
        if self._vista.get() == _VISTA_FINAL:
            taller = self.app.taller
            # El "stock final" solo tiene sentido tras simular: sin snapshots el
            # taller solo tiene el stock recién cargado (D Final == D Original), así
            # que no se muestra como si fuera un resultado.
            if not taller.snapshots:
                return cols, filas
            for cil in sorted(taller.cilindros.values(), key=lambda c: c.diametro, reverse=True):
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
                    jaula = r.get("Jaula_Asignada")
                    perfil = r.get("Perfil")
                    filas.append((
                        str(r.get("ID_Cilindro", "")), f"{float(r.get('Diámetro_mm', 0)):.1f}",
                        str(r.get("Estado", "")),
                        "-" if pd.isna(jaula) else int(jaula),
                        "-" if (perfil is None or pd.isna(perfil) or str(perfil) == "") else str(perfil),
                    ))
        return cols, filas

    def _filas_filtradas(self):
        """(columnas, filas) tras aplicar todos los filtros de columna activos."""
        cols, filas = self._filas_crudas()
        if not self._filtros_col:
            return cols, filas
        # Sólo se evalúan las columnas con filtro (idx → set de valores).
        filtros = {cols.index(c): s for c, s in self._filtros_col.items() if c in cols}
        out = [f for f in filas
               if all(str(f[idx]) in s for idx, s in filtros.items())]
        return cols, out

    # ── Render ───────────────────────────────────────────────────────────

    def refrescar(self):
        self._on_cambiar_vista()

    def _on_cambiar_vista(self):
        self._cerrar_filtro()
        self._filtros_col = {}  # columnas distintas por vista: se reinician los filtros
        self._rerender()

    def _rerender(self):
        """Reconfigura columnas + cabeceras + filas para la vista actual.

        A diferencia de ``_on_cambiar_vista`` **no** resetea los filtros: se usa
        también al re-mostrar la pestaña (ver ``_on_map``).
        """
        cols = self._columnas()
        self._tree.configure(columns=cols)
        for c in cols:
            self._tree.column(c, width=_ANCHOS.get(c, 110), anchor="center")
        self._actualizar_headings()
        self._fill()

    def _on_map(self, _event=None):
        """Re-renderiza al volver visible la pestaña (CTkTabview la desmapea).

        ``ttk.Treeview`` llenado mientras la pestaña estaba oculta (p. ej. tras
        ejecutar la simulación parado en otra pestaña) puede quedar mal pintado
        hasta un re-fill estando visible — por eso «cambiar de vista lo corregía».
        Al mostrarse se re-renderiza conservando los filtros activos.
        """
        if self._filtro_panel is None:
            self._rerender()

    def _actualizar_headings(self):
        """Texto de cabecera (con ▾ si hay filtro) + binding de click por columna."""
        for c in self._columnas():
            marca = "  ▾" if self._filtros_col.get(c) else ""
            self._tree.heading(c, text=c + marca, command=lambda col=c: self._abrir_filtro(col))

    def _fill(self):
        cols, filas = self._filas_filtradas()
        self._tree.delete(*self._tree.get_children())
        idx_estado = cols.index("Estado") if "Estado" in cols else None
        for fila in filas:
            tag = str(fila[idx_estado]).replace(" ", "_") if idx_estado is not None else ""
            self._tree.insert("", "end", values=fila, tags=(tag,) if tag else ())
        if (self._vista.get() == _VISTA_FINAL and not filas
                and not self.app.taller.snapshots):
            self._lbl_count.set("Ejecute la simulación para ver el stock final")
        else:
            self._lbl_count.set(f"{len(filas)} cilindros")

    # ── Filtro de columna (estilo Excel) ─────────────────────────────────

    def _abrir_filtro(self, col):
        """Panel **inline** (sin popup) con búsqueda + checklist de valores de ``col``.

        Mismo patrón ``place()``/click-fuera que ``gui/calendario.py``: se dibuja
        sobre el toplevel, anclado bajo la cabecera clickeada, y se cierra al hacer
        click fuera o con Escape (binds creados una sola vez). Además del checklist
        de selección, un buscador filtra los valores por contenido (substring).
        """
        self._cerrar_filtro()
        cols, filas = self._filas_crudas()
        idx = cols.index(col)
        valores = sorted({str(f[idx]) for f in filas})
        if not valores:
            return
        actual = self._filtros_col.get(col)  # set o None (= todos)

        top = self.winfo_toplevel()
        panel = ctk.CTkFrame(top, fg_color=BG_CARD, corner_radius=8,
                             border_width=1, border_color=ACCENT)
        self._filtro_panel = panel

        ctk.CTkLabel(panel, text=f"Filtrar «{col}»", text_color=FG,
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))

        # Selección por valor (persiste aunque el buscador oculte algunos valores).
        vars_val = {val: tk.BooleanVar(value=(actual is None or val in actual))
                    for val in valores}

        buscar = tk.StringVar()
        ctk.CTkEntry(panel, textvariable=buscar, width=232,
                     placeholder_text="Buscar…").pack(padx=12, pady=(0, 6))

        chk_all = tk.BooleanVar(value=actual is None)

        def _visibles():
            t = buscar.get().strip().lower()
            return [v for v in valores if t in v.lower()] if t else valores

        def _toggle_all():
            for v in _visibles():
                vars_val[v].set(chk_all.get())

        ctk.CTkCheckBox(panel, text="(Seleccionar todo)", variable=chk_all,
                        command=_toggle_all).pack(anchor="w", padx=12, pady=(0, 4))

        body = ctk.CTkScrollableFrame(panel, fg_color="transparent", width=230, height=200)
        body.pack(fill="both", expand=True, padx=8, pady=2)

        def _redibujar(*_a):
            for w in body.winfo_children():
                w.destroy()
            for val in _visibles():
                ctk.CTkCheckBox(body, text=val or "(vacío)",
                                variable=vars_val[val]).pack(anchor="w", pady=1)

        buscar.trace_add("write", _redibujar)
        _redibujar()

        def _aplicar():
            sel = {val for val, v in vars_val.items() if v.get()}
            if not sel or len(sel) == len(valores):
                self._filtros_col.pop(col, None)  # nada o todo ⇒ sin filtro
            else:
                self._filtros_col[col] = sel
            self._cerrar_filtro()
            self._actualizar_headings()
            self._fill()

        def _limpiar():
            self._filtros_col.pop(col, None)
            self._cerrar_filtro()
            self._actualizar_headings()
            self._fill()

        acc = ctk.CTkFrame(panel, fg_color="transparent")
        acc.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkButton(acc, text="Aplicar", width=80, fg_color=BTN_BLUE,
                      hover_color=BTN_BLUE_HOVER, command=_aplicar).pack(side="right", padx=4)
        ctk.CTkButton(acc, text="Limpiar", width=80, fg_color="transparent", border_width=1,
                      border_color=FG2, text_color=FG2, hover_color=BG_CARD,
                      command=_limpiar).pack(side="right", padx=4)

        # Posición: bajo la cabecera de la columna (x = ancho acumulado anterior),
        # sin desbordar el borde derecho del toplevel.
        panel.update_idletasks()
        x_off = sum(int(self._tree.column(c, "width")) for c in cols[:idx])
        x = (self._tree.winfo_rootx() - top.winfo_rootx()) + x_off
        y = (self._tree.winfo_rooty() - top.winfo_rooty())
        x = max(0, min(x, top.winfo_width() - panel.winfo_reqwidth()))
        panel.place(x=x, y=y)
        panel.lift()

        # Cierre por click-fuera/Escape: binds del toplevel creados una sola vez
        # (cada handler corta solo si el panel está cerrado), evitando el footgun
        # de unbind(seq, funcid). Mismo enfoque que gui/calendario.py.
        if not self._filtro_binds:
            top.bind("<Button-1>", self._click_fuera_filtro, add="+")
            top.bind("<Escape>", lambda _e: self._cerrar_filtro(), add="+")
            self._filtro_binds = True

    def _cerrar_filtro(self):
        if self._filtro_panel is not None:
            self._filtro_panel.destroy()
            self._filtro_panel = None

    def _click_fuera_filtro(self, event):
        """Cierra el panel si el click no cayó dentro de él."""
        if self._filtro_panel is None:
            return
        w = event.widget
        while w is not None:
            if w is self._filtro_panel:
                return
            w = getattr(w, "master", None)
        self._cerrar_filtro()

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
        cols, filas = self._filas_filtradas()
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
