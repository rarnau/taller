"""Iconografía centralizada de la GUI (glyphs de botones y controles).

Fuente única de los íconos, para mantenerlos consistentes (un ícono por
concepto) y poder cambiarlos en un solo lugar — incluida una futura migración a
una fuente de íconos tipo Font Awesome. Se usan glyphs que Tk ya renderiza en
este proyecto, así que centralizar no cambia el render, solo lo unifica.
"""
# Archivo / datos
CARGAR = "📁"          # cargar/subir un archivo
GUARDAR = "💾"         # guardar configuración
DESCARGAR = "⬇"        # descargar / exportar
SUBIR_HISTORIA = "📈"  # subir histórico para adaptar el modelo
ELIMINAR = "🗑"        # eliminar fila/elemento
CALENDARIO = "📅"      # selector de fecha
# Generación / acciones
GENERAR = "▶"          # generar / ejecutar
SEED = "🎲"            # nueva seed
AJUSTAR = "🔍"         # ver / ajustar
INFO = "ⓘ"             # ayuda / información
# Reproducción
PLAY = "▶"
PAUSE = "⏸"
STOP = "⏹"
ATRAS = "⏪"
ADELANTE = "⏩"
# Estados (Vista Real)
PARADA = "⛔"
OPERATIVA = "●"
FUERA_TURNO = "⏸"
