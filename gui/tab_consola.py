"""Consola."""
import tkinter as tk
from tkinter import scrolledtext
from config.tema import BG, BG2, BG3, FG, FG2, ACCENT, FONT_MONO, FONT_SIZE, FONT_FAMILY


def crear_consola(tab):
    outer = tk.Frame(tab, bg=BG, padx=10, pady=10)
    outer.pack(fill="both", expand=True)
    card = tk.Frame(outer, bg=BG2, bd=1, relief="solid", highlightbackground=BG3, highlightthickness=1)
    card.pack(fill="both", expand=True)
    header = tk.Frame(card, bg=BG3, height=34)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="Bitácora de eventos", bg=BG3, fg=ACCENT, font=(FONT_FAMILY, FONT_SIZE, "bold")).pack(side="left", padx=12, pady=6)
    tk.Label(header, text="• tiempo real", bg=BG3, fg=FG2, font=(FONT_FAMILY, FONT_SIZE)).pack(side="right", padx=12)
    log = scrolledtext.ScrolledText(card, bg="#060B12", fg="#A5D6FF", font=(FONT_MONO, FONT_SIZE), insertbackground=FG, wrap="word", relief="flat", borderwidth=0, padx=12, pady=10, selectbackground="#264F78", selectforeground="#FFFFFF")
    log.pack(fill="both", expand=True, padx=2, pady=2)
    return log
