#!/usr/bin/env python3
"""Lanzador de la GUI Qt (PySide6) — clon del rediseño web del simulador.

Alternativa a ``main.py`` (CustomTkinter); ambas comparten el mismo motor en
``modelos/`` sin modificarlo. Ejecutar con: ``python main_qt.py``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from gui_qt.app import App


def main():
    app = QApplication(sys.argv)
    ventana = App()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
