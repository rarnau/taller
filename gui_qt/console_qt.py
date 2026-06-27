"""Pestaña Consola para la GUI Qt."""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class ConsolePanel(QWidget):
    """Consola de solo lectura para avisos y log de simulacion."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.log = QPlainTextEdit()
        self.log.setObjectName("ConsoleView")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("La salida de simulacion aparecera aqui...")
        root.addWidget(self.log)

    def set_lines(self, lines) -> None:
        """Reemplaza el contenido completo y deja el scroll al final."""
        text = "\n".join(lines) if lines else ""
        self.log.setPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def append_line(self, line: str) -> None:
        """Agrega una linea al final conservando comportamiento de tail."""
        self.log.appendPlainText(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
