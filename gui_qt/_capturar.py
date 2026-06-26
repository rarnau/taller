"""Utilidad de verificación: corre la app headless y captura cada pestaña a PNG.

Uso: QT_QPA_PLATFORM=offscreen python -m gui_qt._capturar <dir_salida>
"""
import os
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

from gui_qt.app import App, TABS


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/qt_caps"
    os.makedirs(out, exist_ok=True)
    app = QApplication(sys.argv)
    w = App()
    w.resize(1380, 860)
    w.show()

    loop = QEventLoop()
    estado = {"listo": False}

    def check():
        if w.taller is not None:
            estado["listo"] = True
            loop.quit()
    t = QTimer(); t.timeout.connect(check); t.start(200)
    QTimer.singleShot(60000, loop.quit)
    loop.exec()

    # Avanzar el playback a un punto intermedio para poblar Vista Real
    if w.vm and w.vm.N:
        w._seek(min(40, w.vm.N - 1))
    app.processEvents()

    for key, name in TABS:
        w._cambiar_tab(key)
        for _ in range(6):
            app.processEvents()
        path = os.path.join(out, f"{key}.png")
        w.grab().save(path)
        print(f"guardado {path}")
    print("LISTO:", estado["listo"], "snapshots:", len(w.taller.snapshots) if w.taller else 0)


if __name__ == "__main__":
    main()
