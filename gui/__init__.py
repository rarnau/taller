"""Paquete GUI.

``App`` se expone de forma perezosa: importar un submódulo liviano (p. ej.
``gui.validacion_config``, sin dependencias de Tk) no debe arrastrar
``customtkinter``/``tkinter``. Acceder a ``gui.App`` (o ``from gui import App``)
sí carga la app completa.
"""


def __getattr__(name):
    if name == "App":
        from .app import App
        return App
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
