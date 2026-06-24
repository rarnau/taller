"""Animaciones suaves para ventanas Tk (fade de opacidad).

Tk no soporta opacidad por-widget (no se puede *fade* de un frame/tab por
separado), pero **sí** la opacidad de ventanas top-level (root y Toplevel) vía
el atributo ``-alpha``. Este módulo anima ese atributo con ``after()`` para dar
una aparición suave a la ventana principal y a los popups. Degrada a no-op si el
sistema (p. ej. X11 sin compositor) no soporta ``-alpha``.
"""


def pasos_alpha(inicio: float, fin: float, n: int):
    """Lista de ``n`` valores de alpha interpolados linealmente de ``inicio`` a ``fin``.

    Incluye ``fin`` como último valor (no incluye ``inicio``), de modo que la
    animación termina exactamente en la opacidad objetivo. Función pura testeable.
    """
    n = max(1, int(n))
    return [inicio + (fin - inicio) * (i + 1) / n for i in range(n)]


def fade_in(ventana, duracion_ms: int = 180, pasos: int = 12, alpha_final: float = 1.0):
    """Anima la opacidad de ``ventana`` (root o Toplevel) de 0 a ``alpha_final``.

    No-op seguro si la ventana no soporta ``-alpha``. Usa ``after()`` sobre la
    propia ventana, así no bloquea el event loop.
    """
    try:
        ventana.attributes("-alpha", 0.0)
    except Exception:
        return
    valores = pasos_alpha(0.0, alpha_final, pasos)
    intervalo = max(1, int(duracion_ms / len(valores)))

    def _tick(i: int = 0):
        if i >= len(valores):
            return
        try:
            ventana.attributes("-alpha", valores[i])
        except Exception:
            return
        ventana.after(intervalo, lambda: _tick(i + 1))

    _tick()
