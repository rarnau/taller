"""Zoom interactivo (rueda + doble-clic para resetear) para ejes Matplotlib
embebidos. Sin dependencias de Tk: se conecta a un FigureCanvas cualquiera."""

def _nuevos_limites(lim, centro, scale):
    """Nuevo (lo, hi) al escalar el intervalo `lim`=(lo,hi) por `scale` alrededor
    de `centro`. scale<1 acerca (zoom in), scale>1 aleja (zoom out)."""
    lo, hi = lim
    return (centro - (centro - lo) * scale, centro + (hi - centro) * scale)

def conectar_zoom(canvas, base_scale=1.2):
    """Conecta zoom-rueda + doble-clic-reset a un FigureCanvas (cualquier backend).

    - Rueda arriba = acercar; rueda abajo = alejar, centrado en el cursor, sobre
      el eje bajo el puntero (event.inaxes).
    - Doble clic = restaura los límites originales (capturados al conectar) del eje.
    Devuelve el canvas. No interfiere con otros handlers (usa scroll_event y
    button_press_event con dblclick)."""
    originales = {}
    for ax in canvas.figure.get_axes():
        originales[ax] = (ax.get_xlim(), ax.get_ylim())

    def _on_scroll(event):
        ax = event.inaxes
        if ax is None or event.xdata is None or event.ydata is None:
            return
        scale = (1.0 / base_scale) if event.button == "up" else base_scale
        ax.set_xlim(_nuevos_limites(ax.get_xlim(), event.xdata, scale))
        ax.set_ylim(_nuevos_limites(ax.get_ylim(), event.ydata, scale))
        canvas.draw_idle()

    def _on_click(event):
        if not getattr(event, "dblclick", False):
            return
        ax = event.inaxes
        if ax is None or ax not in originales:
            return
        x, y = originales[ax]
        ax.set_xlim(x)
        ax.set_ylim(y)
        canvas.draw_idle()

    canvas.mpl_connect("scroll_event", _on_scroll)
    canvas.mpl_connect("button_press_event", _on_click)
    return canvas
