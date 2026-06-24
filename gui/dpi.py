"""Cálculo del factor de escala para alta DPI (puro, sin Tk).

El rescalado automático por-monitor de CustomTkinter queda desactivado en
``gui/app.py`` (evita un crash del dropdown de los CTkComboBox al mover la
ventana entre monitores con distinto DPI). Como contrapartida la escala queda
fija; este módulo deriva **una** escala fija del DPI detectado al arrancar, para
que en pantallas de alta densidad los widgets no se vean diminutos.
"""

# DPI de referencia (100% de escala en la mayoría de los sistemas).
_DPI_BASE = 96.0


def factor_escala_dpi(dpi, base: float = _DPI_BASE,
                      minimo: float = 1.0, maximo: float = 2.0) -> float:
    """Factor de escala de widgets derivado del ``dpi`` detectado de la pantalla.

    ``base`` (96) corresponde al 100%. El resultado se acota a ``[minimo, maximo]``
    para no producir escalas extremas ante una detección dudosa. Con DPI estándar
    (96) devuelve ``1.0`` (comportamiento idéntico al previo). ``dpi`` no positivo
    ⇒ ``minimo``.
    """
    if not dpi or dpi <= 0:
        return minimo
    return max(minimo, min(maximo, dpi / base))
