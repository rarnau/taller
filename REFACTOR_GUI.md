# Plan de refactorización de la GUI (`gui_qt/`)

> Documento de hoja de ruta. **No describe cambios ya aplicados**, sino
> oportunidades de mejora detectadas en el código actual de la interfaz Qt para
> abordar de forma incremental. El objetivo es reducir el texto/estilo
> hardcodeado y la duplicación, sin alterar comportamiento.

## Contexto

La GUI migró de Tkinter a **PySide6 (Qt)** y vive en `gui_qt/`. El estilo está
bien centralizado en `gui_qt/theme.py` (QSS) y `config/tema.py` (paleta), pero
el resto presenta tres focos de deuda: **strings de UI hardcodeados** (sin
i18n), **colores/medidas mágicas** repartidos por los paneles, y **patrones de
UI duplicados** que ya tienen (o merecen) un widget reutilizable. Este documento
los cataloga y propone un orden de ataque por retorno/esfuerzo.

---

## Estructura actual de `gui_qt/`

| Archivo | ~Líneas | Rol |
|---|---|---|
| `theme.py` | ~1040 | QSS global (estilos + colores). **Bien centralizado.** |
| `generation_qt.py` | ~1090 | Panel Generación (adaptación de modelo, timeline). El más grande. |
| `config_qt.py` | ~810 | Panel Configuración (globales, rangos, máquinas, sim). |
| `main_window.py` | ~590 | Ventana principal, tabs, playback, orquestación. |
| `vista_realtime.py` | ~530 | Vista Real (jaulas, CRC, máquinas, cola, enfriado). |
| `inventory_qt.py` | ~300 | Tabla de inventario + filtros + export. |
| `sidebar_qt.py` | ~140 | Sidebar (carga, run, reproducción). |
| `dashboard_qt.py` | ~145 | Dashboard nativo (grid 2×2). |
| `tab_kpis_qt.py` | ~135 | KPIs (tarjetas de métrica). |
| `playback_slider_qt.py` | ~120 | Slider de snapshots con marcadores de PARADA. |
| `analysis_qt.py` | ~60 | Análisis (Matplotlib embebido). |
| `console_qt.py` | ~30 | Consola de log/alertas. |
| `ui_constants_qt.py` | ~12 | Constantes de layout (hoy **casi vacío**). |
| `widgets/` | — | `FlowCard`, `SectionCard`, `StatusBarWidget`, `StyledTableWidget`, `LabeledFieldRow`, `TabsCornerInfoWidget`, editores de tabla, y los nuevos `DashboardCard`/charts. |

---

## 1. Strings de UI hardcodeados (sin i18n)

Hay **~50+ literales en español** repartidos por 12+ archivos; **no existe** un
módulo central de strings. Ejemplos representativos:

- `vista_realtime.py`: `"JAULAS"`, `"STOCK DISPONIBLE POR JAULA"`, `"RECTIFICADORAS"`, `"COLA A RECTIFICAR"`.
- `main_window.py`: título de ventana, estados `"● excel cargado"`, `"● simulando"`, `"● simulacion completa"`.
- `tab_kpis_qt.py`: `"UTILIZACION DISPONIBLE"`, `"UTILIZACION NETA"`, banner sin datos.
- `widgets/flow_card_qt.py`: `"FLUJO"`, `"Inventario"`, `"Generacion"`, `"Simulacion"`.
- `console_qt.py`, `inventory_qt.py`, `config_qt.py`, `generation_qt.py`: placeholders, títulos y mensajes de diálogo.

**Patrones recurrentes:** títulos de sección en MAYÚSCULAS, etiquetas de estado
con bullet `"● ..."`, mensajes de estado vacío (`"0 registros"`, `"-"`).

**Propuesta:** crear `gui_qt/ui_strings.py` con categorías (`TITLES`,
`STATUS`, `PLACEHOLDERS`, `BUTTONS`, `DIALOGS`). Beneficio inmediato:
consistencia y un único lugar para corregir tildes/typos (hoy conviven
`"simulacion"` sin tilde y textos con tilde); deja la puerta abierta a i18n
real (dict por idioma) sin tocar los paneles.

> Nota: hoy hay **inconsistencia de acentuación** (p. ej. `"Generacion"` vs
> `"Generación"`). Centralizar es la oportunidad para unificarla.

## 2. Colores hardcodeados fuera de la paleta

`config/tema.py` (paleta) y `theme.py` (QSS) son la fuente de verdad, pero hay
**~25 hex sueltos** en código Python de los paneles:

- `inventory_qt.py`: dict de colores de fila por estado (`"#213347"`, `"#17352D"`, …) que duplica/!sincroniza con `TABLE_ROW_COLORS` de `tema.py`.
- `generation_qt.py`: colores de figuras Matplotlib (`"#16191d"`, `"#9aa3b2"`, `"#35D18A"`, `"#FF6B6B"`) inline.
- `vista_realtime.py`: leyenda `("● Trabajando","#4A9EFF")`, `("● CRC","#F0A32E")`, `("● Disponible","#35C98A")`.
- `tab_kpis_qt.py`: `"#F97316"` para “Desgaste Medio”.

**Propuesta:** derivar estos colores de `config/tema.py` (idealmente con nombres
semánticos, p. ej. reutilizar `COLORES_ESTADO`/`COLORES_ESTADO_DASH` ya
existentes). El Dashboard nuevo ya sigue este patrón con el bloque `DASH_*` de
`tema.py`: usarlo de modelo. Para los colores de Matplotlib de `generation_qt`,
importar de `tema` igual que hacen los renderers de `gui/dashboard_*`.

## 3. Constantes mágicas de layout

`ui_constants_qt.py` tiene ~12 líneas (sólo sidebar/status bar). Hay **~30+
números repetidos** para márgenes, alturas y anchos:

- Márgenes `(12,12,12,12)`, `(14,14,14,14)`, `(16,14,16,14)` en `config_qt.py`, `generation_qt.py`, `tab_kpis_qt.py`.
- Alturas: `setMinimumHeight(76)` (lane box), `100` (timeline), `200/300` (tabla), `38` (botón).
- Anchos: `220`, `130`, `440`, `560` (combos y diálogos).

**Propuesta:** expandir `ui_constants_qt.py` con grupos `MARGIN_*`, `SPACING_*`,
`HEIGHT_*`, `WIDTH_*` y reemplazar los literales. Facilita ajustes de diseño
globales y da coherencia visual entre tabs.

## 4. Duplicación / patrones extraíbles a `widgets/`

- **`SectionCard` subutilizado:** `config_qt.py` arma a mano la card
  (`QFrame#CardSoft` + título + hint) en 4 métodos `_build_*_group()` casi
  idénticos. Migrarlos a `widgets/section_card_qt.py::SectionCard` ahorra
  ~100–200 líneas y unifica el estilo.
- **Diálogo de turnos duplicado:** `config_qt.py::TurnosDialog` y un editor de
  turnos equivalente en `generation_qt.py` (grilla 7×3 de checkboxes + presets).
  Consolidar en un `widgets/turnos_editor_qt.py` reutilizable (~100 líneas
  menos, una sola fuente de la UX de turnos).
- **Tarjeta de métrica duplicada:** `tab_kpis_qt.py::KpiCard` y las
  `GenKpiCard` de `generation_qt.py` resuelven lo mismo (título + valor +
  color). Extraer un `widgets/metric_card_qt.py` genérico (también lo aprovecha
  el Dashboard a futuro).
- **Etiqueta de estado con bullet:** `"● ..."` aparece en `tabs_corner_qt.py`,
  `status_bar_qt.py`, `config_qt.py`, `vista_realtime.py`. Un
  `widgets/state_indicator_qt.py` (`StateIndicatorLabel(text, state)`) unifica
  color y formato.

## 5. Otras observaciones menores

- `generation_qt.py` (~1090 líneas) concentra demasiada responsabilidad
  (modelo + timeline + tabla + diálogo de turnos): candidato a dividir en
  sub-widgets una vez extraídos los puntos 4.
- Patrón de **limpieza de layout antes de re-render** (`while layout.count(): …
  deleteLater()`) repetido en varios paneles: podría vivir en un helper
  `widgets/_layout.py::clear_layout(layout)`.

---

## Orden sugerido (por retorno/esfuerzo)

**Fase 1 — Fundacional (bajo riesgo, alto alcance):**
1. `gui_qt/ui_strings.py` (centralizar strings, unificar acentuación).
2. Expandir `ui_constants_qt.py` (márgenes/altos/anchos).
3. Derivar colores de paneles desde `config/tema.py` (eliminar hex sueltos).

**Fase 2 — Eliminar duplicación con widgets:**
4. Migrar `config_qt.py` a `SectionCard`.
5. Consolidar el editor de turnos en un único widget.
6. Extraer `MetricCard` y `StateIndicatorLabel`.

**Fase 3 — Estructura:**
7. Dividir `generation_qt.py` en sub-widgets.
8. Helper `clear_layout` y base común opcional para paneles de tab.

Cada fase es independiente y verificable visualmente (la lógica de simulación no
se toca; los tests del motor siguen siendo el guardrail).
