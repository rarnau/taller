"""Popup compartido para editar un esquema de turnos (7 días × 3 turnos).

Lo usan la pestaña de Configuración (turnos de máquina) y la de Generación de
Cambios (régimen de turnos del laminador), por lo que vive aparte para no
duplicar la grilla ni los presets.
"""
import customtkinter as ctk

from config.tema import (BG_CARD, FG, FG2, ACCENT, FONT_FAMILY, FONT_SIZE,
                         FONT_SIZE_MD, BTN_BLUE, BTN_BLUE_HOVER)
from modelos import turnos as turnos_mod


def abrir_editor_turnos(parent, turnos_holder, btn_turnos):
    """Abre un popup con la grilla 7 días × 3 turnos y presets.

    ``turnos_holder`` es una lista de un elemento (estado mutable): se escribe el
    nuevo esquema (o ``None`` si equivale a 24/7) al aceptar. ``btn_turnos`` es el
    botón cuyo texto refleja el resumen del esquema elegido.
    """
    win = ctk.CTkToplevel(parent)
    win.title("Esquema de turnos")
    win.configure(fg_color=BG_CARD)
    win.transient(parent.winfo_toplevel())
    win.grab_set()

    t_actual = turnos_mod.normalizar(turnos_holder[0])
    # vars[dia][turno] = BooleanVar
    variables = {d: [ctk.BooleanVar(value=t_actual[d][i]) for i in range(turnos_mod.NUM_TURNOS)]
                 for d in turnos_mod.DIAS}

    ctk.CTkLabel(
        win, text="Marque los turnos operativos por día (T3 22–06 cubre la madrugada siguiente).",
        text_color=FG2, font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
    ).grid(row=0, column=0, columnspan=4, padx=16, pady=(14, 8), sticky="w")

    for c, etiqueta in enumerate(turnos_mod.TURNO_LABELS):
        ctk.CTkLabel(
            win, text=etiqueta, text_color=FG2,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE, weight="bold"),
        ).grid(row=1, column=c + 1, padx=8, pady=2)

    for r, dia in enumerate(turnos_mod.DIAS):
        ctk.CTkLabel(
            win, text=turnos_mod.DIAS_NOMBRES[r], width=90, anchor="w", text_color=FG,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE_MD),
        ).grid(row=r + 2, column=0, padx=(16, 8), pady=2, sticky="w")
        for c in range(turnos_mod.NUM_TURNOS):
            ctk.CTkCheckBox(win, text="", variable=variables[dia][c], width=24).grid(
                row=r + 2, column=c + 1, padx=8, pady=2)

    def _aplicar_preset(clave):
        preset = turnos_mod.PRESETS[clave]
        for d in turnos_mod.DIAS:
            for i in range(turnos_mod.NUM_TURNOS):
                variables[d][i].set(preset[d][i])

    presets_fila = ctk.CTkFrame(win, fg_color="transparent")
    presets_fila.grid(row=9, column=0, columnspan=4, padx=16, pady=(10, 4), sticky="w")
    for clave in turnos_mod.PRESETS:
        ctk.CTkButton(
            presets_fila, text=turnos_mod.PRESET_LABELS[clave], width=110, height=28,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            text_color=ACCENT, hover_color=BG_CARD,
            command=lambda k=clave: _aplicar_preset(k),
        ).pack(side="left", padx=4)

    def _aceptar():
        nuevo = {d: [variables[d][i].get() for i in range(turnos_mod.NUM_TURNOS)]
                 for d in turnos_mod.DIAS}
        # 24/7 se guarda como None para mantener limpia la configuración.
        turnos_holder[0] = None if turnos_mod.es_completo(nuevo) else nuevo
        btn_turnos.configure(text=turnos_mod.resumen(turnos_holder[0]))
        win.destroy()

    acciones = ctk.CTkFrame(win, fg_color="transparent")
    acciones.grid(row=10, column=0, columnspan=4, padx=16, pady=(8, 16), sticky="e")
    ctk.CTkButton(acciones, text="Cancelar", width=100, height=30,
                  fg_color="transparent", border_width=1, border_color=FG2,
                  text_color=FG2, hover_color=BG_CARD,
                  command=win.destroy).pack(side="left", padx=4)
    ctk.CTkButton(acciones, text="Aceptar", width=100, height=30,
                  fg_color=BTN_BLUE, hover_color=BTN_BLUE_HOVER,
                  command=_aceptar).pack(side="left", padx=4)
