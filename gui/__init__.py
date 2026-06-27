"""Módulos de renderizado Matplotlib compartidos.

Tras la migración de la GUI a Qt (``gui_qt/``), este paquete ya **no**
contiene la interfaz vieja de Tkinter/CustomTkinter. Solo conserva los dos
módulos de dibujo Matplotlib puros — ``dashboard_principal`` y
``dashboard_detalle`` — que ``gui_qt`` reutiliza para sus paneles Dashboard y
Análisis. No tiene dependencias de Tk.
"""
