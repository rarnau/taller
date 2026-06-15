"""Consola adaptada."""
import customtkinter as ctk
from tkinter import scrolledtext
from config.tema import BG, BG2, BG3, FG, FG2, ACCENT, FONT_MONO, FONT_SIZE, FONT_FAMILY


def crear_consola(tab):
    log = scrolledtext.ScrolledText(tab, bg="#060B12", fg="#A5D6FF",
                                  font=(FONT_MONO, FONT_SIZE),
                                  insertbackground=FG, wrap="word",
                                  relief="flat", borderwidth=0,
                                  padx=12, pady=10,
                                  selectbackground="#264F78",
                                  selectforeground="#FFFFFF")
    log.pack(fill="both", expand=True, padx=10, pady=10)
    return log
