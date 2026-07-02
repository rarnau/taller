# MEJORAS.md — Backlog ejecutable de mejoras propuestas

Este archivo es un backlog **autocontenido** pensado para que cada ítem se ejecute
como una tarea independiente por un agente (p. ej. Claude Opus) **sin re-analizar
todo el repo**: cada ítem trae el contexto, los archivos exactos, el diseño y los
criterios de aceptación. El análisis de origen ya está hecho; no repetirlo.

## Instrucciones para el agente ejecutor (leer SIEMPRE primero)

1. **Leé `CLAUDE.md` completo antes de tocar código.** Contiene la arquitectura y
   los invariantes no negociables (golden master, orden de la cola de eventos,
   registries de estrategias, aislamiento de tests, modo snapshot liviano).
2. **Suite**: `pip install -r requirements-dev.txt && python -m pytest -q`.
   Estado esperado al empezar: **133 passed**. Debe seguir 100% verde al terminar.
3. **Golden master** (`tests/golden_master.json`): NO se regenera salvo que el
   ítem lo indique explícitamente. Regla rápida:
   - Agregar **claves escalares nuevas** a `calcular_kpis()` NO rompe el golden
     (el `fingerprint()` de `tests/_escenarios.py` selecciona claves explícitas).
   - Agregar **campos nuevos a `Snapshot`** SÍ mueve `snapshots_sha256` ⇒ requiere
     regenerar el golden a propósito (`python tests/_generar_golden.py`) y decirlo
     en el commit. Preferí derivar KPIs de datos ya existentes.
   - Cambiar orden de iteración / desempates del motor rompe el golden: los
     `sorted()` y el orden de inserción en la cola son semántica, no estilo.
4. **Regla del snapshot liviano**: si un KPI nuevo lee un campo de los snapshots,
   agregalo a `CAMPOS_SNAPSHOT_KPI` (`modelos/eventos.py`) + su bloque en
   `TallerCilindros._BLOQUES_SNAPSHOT_KPI` (`modelos/taller.py`). Un test exige
   que registro ⇄ bloques coincidan (`tests/test_snapshot_ligero.py`).
5. **KPIs nuevos escalares**: al agregarlos a `calcular_kpis()` entran solos a
   `metric_order` ⇒ la pestaña KPIs y el CLI los renderizan automáticamente.
   Agregá su label a `KPI_META_BASE` (`config/tema.py`). Si además deben salir en
   Monte Carlo, verificá `tests/test_montecarlo.py` (puede asertar columnas).
6. **El modelo (`modelos/`) nunca importa de `gui_qt/`**, y `taller.py` nunca
   importa `kpis.py` (ciclo).
7. **Colores**: siempre desde `config/tema.py`; nada hardcodeado en la GUI.
8. Un commit por ítem, mensaje claro en inglés. Benchmark cuando el ítem sea de
   rendimiento (patrón: media de ≥20 corridas con `time.perf_counter` sobre
   `datos/simulacion_140cils_1semana.xlsx`, config default — ver commit
   "Add lightweight snapshot mode" como referencia).
9. Estado del repo al escribir esto: rama `claude/code-review-optimization-0td8ox`
   (PR #54) con: suite aislada de `config/user_config.json` (fixture en
   `tests/conftest.py`), CI en `.github/workflows/ci.yml`, modo snapshot liviano
   ya implementado (2.95x en MC). **La optimización #1 del ranking ya está hecha.**

---

## A. Optimizaciones de rendimiento (en orden de impacto restante)

### A1. Conteo por SubStock con `bisect` en `generar_snapshot` ⭐ próxima
- **Qué es**: en el modo completo, `generar_snapshot()` (`modelos/taller.py`,
  bucle `for c in self.cilindros.values()`) hace `for ss in self.lista_substocks:
  if ss.contiene_diametro(...)` por cada cilindro ⇒ O(cilindros × bandas) por
  evento. Con bandas ordenadas se resuelve en O(log bandas) por cilindro.
- **Implementación**: precomputar (al poblar `lista_substocks`, en
  `_reindexar_substocks()`) una lista de bandas ordenada por límite. Semántica a
  preservar EXACTA: el código actual asigna el cilindro a la **primera banda en
  orden de `lista_substocks` que contiene el diámetro** (`hasta < d <= desde`,
  bandas pueden solaparse). Si hay solape, el bisect simple no alcanza: detectar
  en el precómputo si las bandas son disjuntas; si lo son, usar bisect
  (`bisect_left` sobre los `hasta` ordenados + verificación `d <= desde`); si se
  solapan, caer al bucle lineal actual. Documentar el porqué en un comentario.
- **Verificación**: suite completa verde (el golden cubre esto byte a byte, incl.
  el escenario `perfiles_jaula_mas_necesitada` que SÍ tiene bandas solapadas —
  ese debe seguir usando el camino lineal). Benchmark antes/después del modo
  completo.

### A2. Índices por estado de cilindro
- **Qué es**: `obtener_cilindros_por_estado()` escanea todo `self.cilindros` y se
  llama varias veces por evento (cola de rectificado en `asignar_trabajo_maquinas`,
  disponibles en `_intentar_reactivar_jaulas`/`reponer_buffer_crc`, y el bloque
  liviano `_snap_kpi_cantidad_disponibles`).
- **Implementación**: mantener `self._por_estado: Dict[EstadoCilindro, List[Cilindro]]`
  actualizado en cada transición. ⚠️ El orden de iteración actual (orden de
  inserción de `self.cilindros`) es semántico: los `sorted()` posteriores
  desempatan por él. El índice debe preservar **orden de inserción del dict
  global**, no orden de transición — la opción segura es un índice
  `Dict[EstadoCilindro, int]` de solo conteos + escaneo solo cuando se necesita
  la lista, o listas reconstruidas con estabilidad demostrada. **Hacer esto solo
  con el golden como red y con benchmark que justifique** (si A1 ya se hizo, el
  beneficio restante puede ser chico; medí primero).
- **Riesgo alto de golden**: cualquier cambio de orden rompe. Si el benchmark no
  da >10%, abandonar el ítem y documentarlo.

### A3. `_minutos_si` por semanas completas (KPIs de turnos)
- **Qué es**: `MaquinaRectificadora.minutos_operativos_entre` / `minutos_falla_entre`
  (`modelos/maquina.py`) iteran hora por hora todo el horizonte. Se calculan al
  final de cada corrida (en `calcular_kpis`), por máquina. Crece con el horizonte
  (Monte Carlo permite hasta 120 días).
- **Implementación**: para `minutos_operativos_entre` con grilla: los minutos
  operativos de una semana completa son constantes (`sum(grilla)` × 60). Alinear
  `t0` al próximo lunes 00:00, iterar solo los bordes parciales y multiplicar las
  semanas enteras. `minutos_falla_entre` NO admite el atajo (la falla depende de
  la hora absoluta), pero puede saltear las horas fuera de turno consultando la
  grilla antes del sorteo.
- **Verificación**: test unitario nuevo comparando la versión rápida vs la
  iterativa en ~20 intervalos aleatorios (bordes raros: t0/t1 a mitad de hora,
  cruce de año). Golden intacto (mismos valores exactos).

### A4. Estructuras O(1) en asignación (`cola.remove`, `not in`)
- **Qué es**: `asignar_trabajo_maquinas` hace `cola.remove(cil)` y
  `_instalar_pareja_o_parar` hace `c not in candidatos` — O(n) dentro de bucles.
- **Decisión previa**: perfilar primero (`cProfile` sobre una corrida MC). Las
  colas reales tienen decenas de elementos; probablemente NO valga la pena.
  Solo implementar si el perfil lo muestra >5% del tiempo.

---

## B. KPIs nuevos (todos en `modelos/kpis.py::calcular_kpis`, claves escalares ⇒ golden-safe)

Para cada uno: agregar la clave al dict `kpis`, el label a `KPI_META_BASE`
(`config/tema.py`), y decidir si entra a Monte Carlo (entra solo si es escalar —
`metricas_montecarlo` toma `metric_order` automáticamente).

### B1. Retraso del programa de cambios
- **Qué**: retraso medio y máximo (horas) de los cambios ejecutados vs su hora
  original del Excel, y % de cambios ejecutados sin retraso.
- **Datos**: ya existen — en `_handle_cambio` (`modelos/taller.py`) se calcula
  `t_proc - ev.tiempo` para el log. Acumular en una lista por corrida
  `self._retrasos_cambios: List[float]` (reset al inicio de `simular()`, como los
  `_repo_*`) y exponer `retraso_medio_cambios_h` / `retraso_max_cambios_h` /
  `cambios_a_tiempo_pct` desde `calcular_kpis` (leer con `getattr(..., [])` para
  tallers sin simular). Atributo nuevo en el taller: picklable (floats).

### B2. Espera en cola de rectificado
- **Qué**: espera media/máxima (h) entre entrar a `A_RECTIFICAR` y empezar el
  rectificado, y largo máximo de la cola.
- **Datos**: estampar `cil._cola_desde = tiempo` cuando el cilindro entra a
  `A_RECTIFICAR` (en `_handle_cambio`, `_handle_fin_enfriado`, re-perfilado y
  `_handle_reposicion`) y en `iniciar_rectificado`… mejor: acumular la espera en
  el taller al momento de `maq.iniciar_rectificado` en `asignar_trabajo_maquinas`
  (diferencia `tiempo - cil._cola_desde`). Largo de cola: max de
  `conteo_por_estado["A rectificar"]` sobre snapshots ⚠️ — eso lee un campo de
  snapshot ⇒ si se quiere en MC, registrar `conteo_por_estado` en
  `CAMPOS_SNAPSHOT_KPI` + bloque (es barato: ya se computa contando estados).
  Alternativa sin snapshots: trackear el máximo en vivo en el taller.

### B3. Duración de episodios de PARADA (media / p90 / máxima)
- **Qué**: hoy hay total (`tiempo_parada_h`) y episodios (`paradas` en MC), no
  distribución.
- **Datos**: en `_intentar_reactivar_jaulas` ya se calcula `dur` por jaula
  reactivada — acumular en `self._duraciones_parada: List[float]`. Sumar la
  parada de línea sin reanudar al final de `simular()` si quedó abierta.
  Exponer `parada_media_h` / `parada_max_h`.

### B4. Vida útil restante de la flota
- **Qué**: mm totales disponibles hasta `diametro_minimo` sumados sobre cilindros
  activos (`vida_util_total_mm`), y estimación de campañas restantes
  (`vida_util_total_mm / desgaste_medio_mm` si desgaste > 0).
- **Datos**: todo está en `taller.cilindros` al final. Cálculo directo en
  `calcular_kpis`. KPI de compras: el más valioso para negocio de esta lista.

### B5. mm desperdiciados en re-perfilado
- **Qué**: nº de pases de re-perfilado × `_MM_REPERFILADO` (0.8). Detecta bandas
  mal diseñadas.
- **Datos**: contar en la rama de re-perfilado de `_finalizar_y_continuar`
  (`self._reperfilados: int`). Exponer `reperfilados` y `mm_reperfilado`.

### B6. Utilización del recurso CRC (grúa)
- **Qué**: % del horizonte con el recurso de traslado ocupado.
- **Datos**: en `_programar_reposicion_crc` se conoce `inicio`/`fin` de cada
  traslado — acumular `self._crc_ocupado_min += tiempo_traslado_crc_min` y
  dividir por el horizonte en `calcular_kpis`.

### B7. Throughput por máquina
- **Qué**: cilindros/día y mm removidos totales por máquina.
- **Datos**: `maq.historial_trabajo` ya tiene todo (`len` y `sum(h["mm"])`).
  ⚠️ Son dicts por-máquina como `utilizacion_maquinas_pct` ⇒ quedan FUERA de
  `metric_order` (solo escalares); mostrarlos en la pestaña KPIs como sección
  por máquina (patrón de "UTILIZACIÓN DISPONIBLE" en `gui_qt/tab_kpis_qt.py`)
  y aplanarlos en `metricas_montecarlo` con prefijo (patrón existente).

### B8. KPI económico (requiere config nueva)
- **Qué**: costo total = horas de parada × costo/h + mm rectificados × costo/mm
  + cilindros nuevos × costo/unidad. Parámetros en `config_global`
  (`costo_hora_parada`, `costo_mm_rectificado`, `costo_cilindro_nuevo`,
  default 0 ⇒ KPI en 0, sin impacto).
- **Implementación**: mutadores en `config/persistencia.py` (patrón
  `set_config_global`), campos en la pestaña Configuración
  (`gui_qt/config_qt.py::_build_global_group`), cálculo en `calcular_kpis`.
  `cargar_config()` ya migra claves faltantes desde `DEFAULTS`.

---

## C. Funcionalidades nuevas — Monte Carlo (`nucleo/montecarlo.py` + `gui_qt/montecarlo_qt.py`)

### C1. Análisis de sensibilidad (tornado) ⭐ el de mayor valor
- **Qué**: correlación de Spearman entre cada input sorteado (columnas `in_*` del
  CSV, ya presentes en cada fila) y cada KPI. Responde "qué parámetro mueve la
  aguja".
- **Implementación**: función pura `sensibilidad(filas) -> Dict[kpi, List[(input, rho)]]`
  en `nucleo/montecarlo.py` (usar `scipy` NO — no está en requirements; Spearman
  se implementa con numpy: rankear con `np.argsort` dos veces y correlacionar
  rangos con `np.corrcoef`). CLI: imprimir top-5 por KPI destacado tras el
  resumen. GUI: widget de barras horizontales (tornado) pintado nativo — copiar
  el patrón de `_HistogramWidget` en `gui_qt/montecarlo_qt.py`, con un combo para
  elegir el KPI. Test con datos sintéticos de correlación conocida (y ~ 2x ⇒
  rho ≈ 1; y ~ ruido ⇒ rho ≈ 0).

### C2. Scatter input → KPI en la GUI
- **Qué**: gráfico de dispersión (un punto por corrida) con combos input/KPI.
- **Implementación**: widget nativo nuevo junto a `_HistogramWidget` (mismo
  patrón de `paintEvent`); los datos ya están en `self._filas` del panel.

### C3. Distribuciones por parámetro (triangular / PERT)
- **Qué**: hoy todo es uniforme (`muestrear_overrides`, `_u`). Permitir
  `[min, moda, max]` ⇒ `rng.triangular`.
- **Implementación**: `_u` acepta par de 2 (uniforme, retrocompatible) o de 3
  (triangular). Persistencia: el spec ya guarda listas — validar largo. GUI:
  tercer slider opcional (o dejar solo CLI/JSON en una primera fase, documentado).
  ⚠️ Reproducibilidad: mantener el MISMO orden de consumo del `rng` para que las
  seeds derivadas sigan siendo reproducibles dentro de una misma spec.

### C4. Latin Hypercube Sampling
- **Qué**: cubrir mejor el espacio con menos corridas.
- **Implementación**: complejo con el diseño actual (cada corrida sortea
  independiente con `seed_i`; LHS necesita coordinar los estratos entre corridas).
  Camino: pre-generar en el orquestador (`correr_montecarlo`) una matriz LHS
  (`runs × n_params`) con el master_seed (numpy puro: permutar estratos por
  columna) y pasarle a cada worker su fila como overrides ya sorteados (la tarea
  pasa de `i` a `(i, overrides)`). Mantener el modo actual como default
  (`spec.fijos["muestreo"] = "uniforme"|"lhs"`). ⚠️ Rompe la reanudación por
  índice solo si cambia el muestreo entre corridas — validar como se valida
  `master_seed` en el CSV.

### C5. Detención por convergencia
- **Qué**: correr hasta que el error estándar del KPI objetivo < umbral, con tope
  en `runs`.
- **Implementación**: en `correr_montecarlo`, tras cada chunk calcular
  `std/sqrt(n)` del KPI objetivo (`spec.fijos["kpi_convergencia"]`, opcional) y
  cortar limpio (cancelar futures pendientes con `fut.cancel()`; los no
  cancelables terminan y se escriben igual). El CSV sigue siendo reanudable.

### C6. Drill-down: abrir una corrida en la GUI
- **Qué**: desde la tabla de resultados MC, "ver la corrida X en Vista Real".
- **Implementación**: requiere `dump_dir` activado (checkbox ya existe,
  `chk_dump`). Doble click en fila de la tabla ⇒ cargar
  `dump_dir/run_XXXXXX.pkl` (pickle del taller **completo** — el worker ya
  desactiva el modo liviano con dump_dir) y reemplazar `MainWindow.taller` +
  playback (reusar el camino de `_poll_simulation` al asignar el taller). Botón
  alternativo: "cargar corrida p90 de <KPI>".

### C7. Presets de spec con nombre
- **Qué**: guardar/cargar specs MC nombradas ("pesimista", "verano").
- **Implementación**: `config/user_config.json::montecarlo_presets: {nombre: spec}`
  (getters/mutadores en `persistencia.py`), combo + botones guardar/borrar en el
  panel MC. `obtener_montecarlo` no cambia (el preset se aplica encima al elegirlo).

### C8. Cancelación de un barrido en curso — ✅ HECHO
Implementado como **pausa/reanudación de sets**: `correr_montecarlo` acepta
`cancelar: threading.Event` (corte limpio), persiste la spec en el sidecar
`<csv>.spec.json`, valida el espacio de muestreo al reanudar y publica
parciales (`on_parcial`) cada chunk; la GUI tiene Pausar / Reanudar-agregar /
Abrir set y gráficos progresivos (~10%). Ver `tests/test_montecarlo_sets.py`.
Esto también cubre la mitad de C7 (sets durables por archivo, aún sin nombre).

---

## D. Mejoras de GUI (`gui_qt/`)

### D1. Progreso real de la simulación
- **Qué**: la barra durante `simular()` no informa avance real.
- **Implementación**: `simular()` acepta `contador_eventos` opcional (objeto con
  `.value`, p. ej. `multiprocessing.Value("i")`) y lo incrementa por iteración
  del bucle. `SimulationService` lo crea con el `mp_context` y lo pasa por
  `initargs` a `init_worker_simulacion` (guardarlo en `_WORKER_STATE`);
  `MainWindow._poll_simulation` lee `.value` y setea
  `progress_sim` (total ≈ `len(eventos_programados)` × ~3 eventos derivados —
  usar total estimado y clamp a 99% hasta terminar). Golden intacto (parámetro
  opcional sin efecto en la lógica).

### D2. Ficha de cilindro (click en Vista Real / Inventario)
- **Qué**: `Cilindro.registrar_evento` acumula el historial completo y hoy no se
  ve en ninguna parte.
- **Implementación**: diálogo `QDialog` con tabla del historial + datos actuales
  (diámetro original/actual, perfil, jaula destino). Abrir desde click en
  `CylinderChip` (`gui_qt/vista_realtime.py`) y desde la fila del Inventario.
  El diálogo necesita acceso a `MainWindow.taller.cilindros[id]` — pasar un
  callback getter, no el taller entero.

### D3. Consola con niveles y filtro
- **Qué**: `gui_qt/console_qt.py` es texto plano.
- **Implementación**: colorear líneas por contenido (`>>>` paradas en RED,
  `BAJA` en ORANGE, resto FG — colores de `config/tema.py`), checkboxes de
  filtro (cambios / paradas / bajas / reposición) y botón exportar `.txt`.
  Las líneas vienen de `taller.log_simulacion` (lista de str) — filtrar por
  patrones simples, sin tocar el motor.

### D4. Atajos de teclado
- **Qué**: espacio = play/pausa, ←/→ = step, Home/End = inicio/fin.
- **Implementación**: `QShortcut` en `MainWindow` llamando `_toggle_play` /
  `_step` / `_go_to_snapshot`. Cuidar no capturar el espacio cuando el foco está
  en un campo de texto (los botones ya usan `NoFocus`, alcanza con
  `Qt.ApplicationShortcut` + verificación del foco).

### D5. Deltas en la pestaña KPIs
- **Qué**: mostrar la variación vs la corrida anterior en cada card.
- **Implementación**: `KpisPanel` guarda el dict `k` anterior; al renderizar,
  pasar `delta` a `SummaryCard` (ya acepta `detail`; agregar sufijo
  "▲ +2 / ▼ −1.3" coloreado). Resetear al cargar otro Excel.

### D6. Tooltips con valores en charts nativos
- **Qué**: los charts de Dashboard/Análisis no informan valores al hover.
- **Implementación**: en `_TimeChart` (`gui_qt/widgets/dashboard_charts_qt.py`)
  habilitar `setMouseTracking(True)`, en `mouseMoveEvent` mapear x→snapshot más
  cercano y mostrar `QToolTip.showText` con tiempo + valores de las series.
  Hacerlo en la base `_TimeChart` para que Stacked/Buffer lo hereden.

### D7. Archivos recientes
- **Qué**: reabrir los últimos Excel sin navegar.
- **Implementación**: `QSettings` (org/app fijos) con lista de rutas; menú
  desplegable en el botón de carga de la sidebar (`gui_qt/sidebar_qt.py`).

### D8. Preview de bandas en Configuración
- **Qué**: al editar rangos, mostrar cuántos cilindros del stock cargado caen en
  cada banda (detecta bandas vacías antes de simular).
- **Implementación**: `ConfigPanel` recibe (callback) el `stock_df` actual;
  columna extra de solo lectura en la tabla de rangos, recalculada en
  `_refresh_coherence_status` (ya se dispara con cada edición).

### D9. Throttle del playback rápido
- **Qué**: a velocidad alta se encolan repaints de todos los snapshots
  intermedios.
- **Implementación**: en `_play_tick` avanzar el índice N pasos por tick según
  velocidad y renderizar SOLO el snapshot final del salto (el slider ya refleja
  el índice). Verificar que `_on_seek` no re-renderice dos veces.

---

## E. Otras utilidades

### E1. Comparador A/B de escenarios
- **Qué**: correr el mismo Excel con dos configs/estrategias y ver KPIs lado a
  lado con deltas.
- **Implementación**: núcleo en `nucleo/runner.py` (`comparar(cfg_a, cfg_b, excel)
  -> (kpis_a, kpis_b)` usando `batch_simular` con 2 tareas). CLI:
  `cli.py comparar <excel> --estrategia-a ... --estrategia-b ...` imprimiendo
  tabla con Δ. GUI (fase 2): pestaña o diálogo con dos columnas de cards.

### E2. `cli.py validar <excel>`
- **Qué**: chequear el Excel sin simular: hojas presentes, columnas, estados
  válidos, diámetros vs rango global, jaulas del programa dentro de
  `1..cantidad_jaulas`, avisos de BAJA sobre el mínimo.
- **Implementación**: reusar `cargar_datos` dentro de try + volcar
  `avisos_carga`; agregar chequeos suaves extra (diámetros fuera de toda banda).
  Exit code 0/1. Subcomando en `cli.py` (patrón de `_cmd_simular`).

### E3. Reporte HTML exportable
- **Qué**: un HTML autocontenido con KPIs, alertas y series (sin dependencias
  nuevas: SVG inline generado a mano o tablas).
- **Implementación**: `nucleo/reporte.py` (GUI-free) que tome el taller y
  escriba HTML (plantilla f-string; colores de `config/tema.py`). CLI:
  `simular --reporte out.html`. GUI: botón en KPIs.

### E4. Estrategias nuevas (1 ítem por estrategia)
- **Selección "urgencia"**: prioriza cilindros cuya `jaula_destino` (o banda
  compatible) tiene menor stock comprometido — reusar el conteo "en camino" de
  `_JaulaMasNecesitada`. Registrar en `ESTRATEGIAS_SELECCION`
  (`modelos/estrategias.py`); GUI/CLI la toman solos del registry.
- **Reposición "punto de re-orden"**: pedir lote cuando los Disponibles+CRC de
  una banda caen bajo un umbral configurable (parámetro en el cfg, no en la
  estrategia — son stateless/singleton). Registrar en `ESTRATEGIAS_REPOSICION`.
  ⚠️ `planificar()` se llama solo tras BAJAs; para re-orden real hay que
  llamarla también tras consumos (punto único: `_instalar_pareja_o_parar`) —
  evaluar impacto y documentar. Golden intacto (default sigue "ninguna").

### E5. Guardar/cargar sesión
- **Qué**: persistir el taller simulado (`pickle`) para reabrir sin re-simular.
- **Implementación**: botones en la sidebar; `pickle.dump(taller)` /
  `pickle.load` + el camino existente de asignación de taller de
  `_poll_simulation` (playback, consola, tabs). Validar versión con un campo
  `formato: 1` en un wrapper dict.

### E6. Linters y empaquetado
- **Qué**: `ruff` (reglas básicas: F, E, I) + `pyproject.toml` con metadata y
  entry points `taller-cli` / `taller-gui`. Agregar `ruff check` al CI.
- **Implementación**: config mínima en `pyproject.toml`; arreglar solo lo que
  ruff marque sin cambiar semántica (imports sin uso, etc.). NO activar
  reformateo masivo (diff gigante, riesgo de conflictos).

---

## Orden sugerido de ejecución

| Prioridad | Ítems | Motivo |
|---|---|---|
| 1 | C1 (tornado), B4 (vida útil), B1 (retraso programa) | Máximo valor de decisión, bajo riesgo |
| 2 | A1 (bisect), D1 (progreso) | Rendimiento + UX básica (C8 ya hecho) |
| 3 | B3/B5/B6/B7, D3, D4, D5, E2 | KPIs y GUI incrementales |
| 4 | C3, C6, C7, D2, D6–D9, E1, E3, E5 | Funcionalidad ampliada |
| 5 | A2, A3, A4, C4, C5, E4, E6, B8 | Requieren medición previa o decisiones de producto |
