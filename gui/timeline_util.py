"""Utilidades puras (sin Tk) del timeline de Generación."""


def indice_tiempo_mas_cercano(tiempos, t):
    """Índice del elemento de ``tiempos`` (lista de ``datetime``) más cercano a ``t``.

    Devuelve ``None`` si la lista está vacía. Usado por el timeline para mapear
    el instante clickeado al snapshot de reproducción más próximo.
    """
    if not tiempos:
        return None
    return min(range(len(tiempos)),
               key=lambda i: abs((tiempos[i] - t).total_seconds()))
