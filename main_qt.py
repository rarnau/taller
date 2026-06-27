#!/usr/bin/env python3
"""Entrypoint de la nueva GUI Qt (fase de migracion)."""

import os
import sys

from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui_qt.main_window import MainWindow
from gui_qt.theme import build_qss


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
