"""Selector de fecha con calendario desplegable **inline** (sin popup/Toplevel).

A diferencia de un ``DateEntry`` clásico (que abre una ventana flotante aparte),
el panel del calendario se dibuja con ``place()`` sobre la **misma ventana** de
nivel superior, justo debajo del campo, de modo que aparece "dentro" de la
ventana. Expone la misma mini-API que un ``CTkEntry`` (``get``/``delete``/
``insert``) para ser un reemplazo directo de los entries de fecha existentes.
"""
import calendar
from datetime import date, datetime, timedelta

import customtkinter as ctk

from config.tema import (BG2, BG3, BG_CARD, FG, FG2, ACCENT, BTN_BLUE,
                         BTN_BLUE_HOVER, FONT_FAMILY, FONT_SIZE)
from config.iconos import CALENDARIO

_DIAS = ["L", "M", "X", "J", "V", "S", "D"]
_MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
          "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


class SelectorFecha(ctk.CTkFrame):
    """Entry de fecha ``YYYY-MM-DD`` con calendario desplegable inline."""

    def __init__(self, parent, width=110):
        super().__init__(parent, fg_color="transparent")
        self._entry = ctk.CTkEntry(self, width=width, justify="center")
        self._entry.pack(side="left")
        ctk.CTkButton(self, text=CALENDARIO, width=30, fg_color="transparent",
                      border_width=1, border_color=ACCENT, text_color=ACCENT,
                      hover_color=BG_CARD, command=self._toggle).pack(side="left", padx=(4, 0))
        self._entry.bind("<Button-1>", lambda _e: self._abrir())
        self._panel = None
        self._grid = None
        self._lbl_mes = None
        self._binds_hechos = False  # los binds del toplevel se crean una sola vez
        self._vista = None  # primer día del mes mostrado

    # ── Mini-API estilo CTkEntry (reemplazo directo) ─────────────────────────

    def get(self):
        return self._entry.get()

    def delete(self, a, b):
        self._entry.delete(a, b)

    def insert(self, i, s):
        self._entry.insert(i, s)

    # ── Lógica de fechas ─────────────────────────────────────────────────────

    def _fecha_actual(self):
        try:
            return datetime.strptime(self._entry.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            return date.today()

    def _mes_prev(self):
        if self._panel is None:
            return
        self._vista = (self._vista - timedelta(days=1)).replace(day=1)
        self._dibujar()

    def _mes_next(self):
        if self._panel is None:
            return
        y, m = self._vista.year, self._vista.month
        self._vista = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        self._dibujar()

    def _elegir(self, dia):
        self._entry.delete(0, "end")
        self._entry.insert(0, dia.isoformat())
        self._cerrar()

    # ── Despliegue / cierre ──────────────────────────────────────────────────

    def _toggle(self):
        self._cerrar() if self._panel is not None else self._abrir()

    def _abrir(self):
        if self._panel is not None:
            return
        self._vista = self._fecha_actual().replace(day=1)
        top = self.winfo_toplevel()
        self._panel = ctk.CTkFrame(top, fg_color=BG_CARD, corner_radius=8,
                                   border_width=1, border_color=ACCENT)
        # Header con flechas: se crea UNA sola vez (no se destruye al navegar) para
        # que el botón clickeado siga existiendo cuando corre _click_fuera.
        head = ctk.CTkFrame(self._panel, fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(6, 2))
        ctk.CTkButton(head, text="‹", width=28, fg_color=BG3, hover_color=ACCENT,
                      command=self._mes_prev).pack(side="left")
        self._lbl_mes = ctk.CTkLabel(
            head, text="", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold"))
        self._lbl_mes.pack(side="left", expand=True)
        ctk.CTkButton(head, text="›", width=28, fg_color=BG3, hover_color=ACCENT,
                      command=self._mes_next).pack(side="right")
        # La grilla de días vive en su propio frame; sólo ese se reconstruye.
        self._grid = ctk.CTkFrame(self._panel, fg_color="transparent")
        self._grid.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._dibujar()
        self.update_idletasks()
        x = self._entry.winfo_rootx() - top.winfo_rootx()
        y = self._entry.winfo_rooty() - top.winfo_rooty() + self._entry.winfo_height() + 2
        self._panel.place(x=x, y=y)
        self._panel.lift()
        # Cerrar al hacer click fuera o con Escape. Los binds del toplevel se
        # crean UNA sola vez y nunca se quitan (cada handler corta solo si el
        # panel está cerrado): así se evita el footgun de unbind(seq, funcid),
        # que puede borrar todos los binds de ese evento. Se agregan tras el
        # click que abre, así ese mismo evento no los dispara.
        if not self._binds_hechos:
            top.bind("<Button-1>", self._click_fuera, add="+")
            top.bind("<Escape>", lambda _e: self._cerrar(), add="+")
            self._binds_hechos = True

    def _cerrar(self):
        if self._panel is None:
            return
        self._panel.destroy()
        self._panel = self._grid = self._lbl_mes = None

    def _click_fuera(self, event):
        """Cierra el panel si el click no cayó dentro de él ni del propio selector."""
        if self._panel is None:
            return
        w = event.widget
        while w is not None:
            if w in (self._panel, self):
                return
            w = getattr(w, "master", None)
        self._cerrar()

    # ── Dibujo del calendario ────────────────────────────────────────────────

    def _dibujar(self):
        # Sólo se reconstruye la grilla de días; el header (con flechas) persiste.
        for w in self._grid.winfo_children():
            w.destroy()
        y, m = self._vista.year, self._vista.month
        self._lbl_mes.configure(text=f"{_MESES[m - 1]} {y}")

        for c, d in enumerate(_DIAS):
            ctk.CTkLabel(self._grid, text=d, width=32, text_color=FG2,
                         font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE)
                         ).grid(row=0, column=c, padx=1, pady=1)

        sel = self._fecha_actual()
        cal = calendar.Calendar(firstweekday=0)  # lunes
        for r, semana in enumerate(cal.monthdatescalendar(y, m), start=1):
            for c, dia in enumerate(semana):
                es_mes = dia.month == m
                es_sel = dia == sel
                ctk.CTkButton(
                    self._grid, text=str(dia.day), width=32, height=26,
                    fg_color=BTN_BLUE if es_sel else (BG3 if es_mes else BG2),
                    text_color=FG if es_mes else FG2, hover_color=BTN_BLUE_HOVER,
                    command=lambda dd=dia: self._elegir(dd)
                ).grid(row=r, column=c, padx=1, pady=1)
