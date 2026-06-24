# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Launch the GUI
python main.py

# Generate test datasets
python datos/generar_caso_parada.py
```

### Tests

A golden-master regression suite guards the simulation engine (`modelos/taller.py`):

```bash
pip install -r requirements-dev.txt   # adds pytest
python -m pytest                       # runs tests/
```

`tests/_escenarios.py` defines scenarios (PARADA, cooling, the 140-cylinder week, several strategies) and a deterministic `fingerprint()` (KPIs + snapshot count + alerts + final per-cylinder state). `tests/test_regresion.py` compares each run against `tests/golden_master.json`. When a behavior change is **intended**, regenerate the baseline on purpose with `python tests/_generar_golden.py`; otherwise a failing test means the engine changed behavior. There are no linters configured.

## Architecture Overview

**Simulador de Cilindros Pro v4** — a discrete-event simulation (DES) tool for a rolling mill (taller de laminación). Operators load an Excel file describing cylinder inventory and a change schedule; the engine simulates cylinder lifecycle transitions and the GUI replays them.

**Config vs data separation:** the Excel carries only **variable data** (the `Stock_Inicial` and `Programa_Cambios` sheets). The **structural configuration** of the taller (global params, machine park, per-jaula SubStock ranges, simulation params) is **persistent** in `config/user_config.json` and is edited from the GUI's Configuración tab or the `cli.py config` subcommands — never from the Excel. The model applies it via `taller.configurar(cfg)` **before** `cargar_datos()`.

### Layer separation

```
main.py
└── gui/app.py              # CTk App — wires UI to model, owns playback state
    ├── modelos/taller.py   # TallerCilindros — all simulation logic (no GUI imports)
    └── gui/*.py            # Pure display components (no model imports except app.py)
```

**The model layer (`modelos/`) must never import from `gui/`.**

### Simulation engine — `modelos/taller.py`

`TallerCilindros` is the central class. Key flow:

0. **Configure** — `configurar(cfg)` applies the persistent config dict (from `config/user_config.json`): global params, machine park (`configurar_maquinas`), SubStock ranges (`configurar_substocks`) and sim params (`tiempo_enfriado_h`, `max_iteraciones`). **Must run before `cargar_datos()`** — the stock needs `cantidad_jaulas` and `diametro_minimo`, and the change schedule validates against the created jaulas.

1. **Load** — `cargar_datos(ruta_excel)` reads two mandatory **data** sheets:
   - `Stock_Inicial` — cylinder inventory with initial states
   - `Programa_Cambios` — scheduled change events

   It clears only per-run data (cylinders, jaulas, events, alerts, snapshots), **not** the machines/substocks/global params set by `configurar()`. If the Excel still carries the old `Configuración`/`Máquinas` sheets they are **ignored** (with an aviso). `cargar_datos()` delegates to `cargar_datos_desde_dataframes(stock_df, cambios_df)`, which a future batch runner can call directly with in-memory DataFrames (no disk I/O per run).

2. **Simulate** — `simular(callback)` runs a priority-queue DES loop. Internal event type `_EventoSim(tipo, tiempo, datos)` has five types:
   - `"CAMBIO"` — a scheduled jaula change (datos = `EventoCambio`)
   - `"FIN_RECT"` — a machine finishes rectification (datos = machine name str)
   - `"REPONER_CRC"` — a Disponible cylinder arrives at the CRC buffer (datos = jaula int)
   - `"FIN_ENFRIADO"` — a cylinder finishes cooling and enters the rectification queue (datos = cylinder id str). Only generated when `tiempo_enfriado_h > 0`.
   - `"REANUDAR_MAQUINA"` — a machine reopens its shift and retries taking work (datos = machine name str). Only generated when a free machine is **out of shift** with a non-empty queue. Like `FIN_RECT`/`FIN_ENFRIADO` it **always executes** (never deferred by a PARADA) and is **not** shifted by `_reanudar_linea` (it is wall-clock). See the work-shift design decision below.

   The queue is a **`heapq`** of tuples `(tiempo, secuencia, evento)` — `_ItemCola`. Push (`_push_evento`) and pop (`heapq.heappop`) are `O(log n)`. The `secuencia` field (an `itertools.count()` per run, `self._seq_cola`) breaks `tiempo` ties in **FIFO insertion order** and keeps `_EventoSim`s from ever being compared. This reproduces the exact ordering of the old `list` + stable `sort(key=tiempo)`; preserve the insertion order at each call site (see the queue-ordering note under Key Design Decisions).

3. **PARADA (line stoppage)** — if after a `CAMBIO` there is no stock to form a complete pair (`_BUFFER_CRC_SIZE = 2`) for a jaula:
   - `_parar_jaula()` marks the jaula `parada=True` and records `_linea_parada_desde`
   - All subsequent `CAMBIO` events with `tiempo > _linea_parada_desde` are moved to `_cambios_diferidos` (not executed)
   - `FIN_RECT` and `REPONER_CRC` always execute — machines keep running and CRC can be replenished
   - When `_intentar_reactivar_jaulas()` succeeds (called from `FIN_RECT` handler), `_reanudar_linea()` shifts all deferred and remaining-in-queue CAMBIO events by the stoppage duration

4. **Snapshot** — `generar_snapshot(tiempo)` is called after every event and records full taller state into `self.snapshots`. The GUI uses snapshots for playback; `Snapshot.jaulas_paradas` is a list of jaula IDs currently stopped. It traverses `self.cilindros` **once** to accumulate the per-state counts, the rectification/cooling detail lists and the per-SubStock counts together (it used to make ~9 full passes per snapshot, one per `EstadoCilindro` plus one per SubStock). Two structural invariants the single pass keeps: `conteo_por_estado` carries **every** enum state as a key (even with value 0), while `conteo_por_substock` carries **only present** states.

### Cylinder lifecycle (states in `modelos/enums.py`)

```
Trabajando ──cambio──> Enfriando ──fin_enfriado──> A rectificar ──maquina libre──> Rectificando ──fin──> Disponible
                       (espera N h)                                                                        │
CRC <──reponer_crc─────────────────────────────────────────────────────────────────────────────────────────┘
 │
 └──instalado──> Trabajando

Cualquier estado ──diametro < minimo──> Baja
```

The `Enfriando` step is only inserted when `tiempo_enfriado_h > 0`; with the default `0.0` the cylinder goes straight `Trabajando ──cambio──> A rectificar` (historical behavior, byte-for-byte identical KPIs).

SubStock ranges: `hasta < diámetro <= desde` (hasta is the lower exclusive bound, desde is the upper inclusive bound). Each jaula has an associated SubStock; a cylinder can only replenish a jaula's CRC if its diameter falls in that SubStock's range.

### Configuration persistence

`config/persistencia.py` loads/saves `config/user_config.json`, which is the source of truth for the taller's structural config:
- `config_global` — `diametro_maximo`, `diametro_minimo`, `tiempo_traslado_crc_min`, `cantidad_jaulas`
- `maquinas` — list of `{nombre, prioridad, tasas: {produccion|desbaste: {mm, tiempo_min}}, turnos?}`. The optional `turnos` is the per-machine work schedule (see the work-shift design decision); **absent ⇒ 24/7** (no key persisted for that case).
- `rangos` — SubStock diameter ranges per jaula
- `tiempo_enfriado_h` — cooling hours between Trabajando and rectification (float, default `0.0`)
- `max_iteraciones` — cap on the simulation loop (int, default `10000`)

`DEFAULTS` is seeded from the reference Excel `datos/simulacion_140cils_1semana.xlsx` (machines G36/F36/F60). `cargar_config()` **migrates** old configs: it fills missing keys from defaults and folds the old loose `prioridades_maquinas` dict into each machine's `prioridad`.

Getters: `obtener_config_global`, `obtener_maquinas`, `obtener_rangos`, `obtener_prioridades` (derived from `maquinas`), `obtener_tiempo_enfriado`, `obtener_max_iteraciones`, `obtener_turnos(cfg, nombre)`. Mutators (single CRUD layer shared by CLI and GUI): `set_config_global`, `add_maquina`/`set_maquina`/`remove_maquina` (both take an optional `turnos` dict), `set_rango`/`remove_rango`, `set_sim`, plus `cfg_desde_excel(excel)` to seed/migrate from an old 4-sheet Excel.

**Coherence jaulas ⇄ rangos** is enforced by a single shared validator: `problemas_coherencia(cfg)` returns a list of human-readable problems (empty ⇒ OK) and `verificar_coherencia(cfg)` raises `ValueError` if any. A coherent config has **exactly one SubStock range per jaula numbered `1..cantidad_jaulas`** (no missing, extra, or duplicate jaula). The mutators do **not** enforce it (CLI editing is incremental, so intermediate states may be inconsistent); instead it is applied at the right boundaries: the **GUI** (`tab_config._guardar`) validates the candidate before persisting (and the SubStock rows are auto-synced to `cantidad_jaulas`, so it stays consistent); the **CLI** `config global`/`config jaula` commands print a **non-fatal `Aviso:`** to stderr after saving (so you can bump jaulas then add the new range in a later command); and `construir_taller(cfg, excel)` calls `verificar_coherencia` as a **hard error before any simulation** — so an incoherent config can never silently run (a missing band would otherwise let `obtener_disponibles_para_jaula` return all cylinders unfiltered, and a band for a non-existent jaula is ignored).

At startup, `App.__init__` calls `taller.configurar(self.user_cfg)` (one call that builds machines, globals, ranges and sim params); it is re-applied before each file load and simulation. The `Configuración` tab (`gui/tab_config.py`) edits all of these at runtime and writes them back. The CLI manages them via `cli.py config ...` subcommands; `--tiempo-enfriado`/`--max-iteraciones` on `cli.py simular` still override the JSON for a single run.

**CLI subcommands** (`cli.py`):
- `simular <excel> [--estrategia --config --export --json --json-out --quiet --tiempo-enfriado --max-iteraciones]`
- `config show | export <json> | import <json> | import-excel <excel>`
- `config global [--diametro-max --diametro-min --crc-min --jaulas]`
- `config maquina list|add|remove|set` (set/add accept `--turnos "<compacto>"` or `--turnos-preset {24x7,off,lv3,3escuadras}`) and `config jaula list|set|remove`
- `config sim [--tiempo-enfriado --max-iteraciones]`
- `config generador [--generador --umbral-desbaste --fecha-inicio --fecha-fin --horizonte-dias]` and `config turnos-cambios [--turnos | --turnos-preset]` — synthetic-change generator config (`generador_cambios` block: `generador`, `umbral_desbaste_mm`, `fecha_inicio`/`fecha_fin` ISO window — `horizonte_dias` kept as legacy fallback — and the optional `turnos_cambios` laminador regime)
- `modelo ajustar <historia>|show|reset` and `generar-cambios [<historia>] [--seed --inicio --fin --horizonte-dias --umbral-desbaste --salida --ajustar]` — fit/inspect the persisted learned model and emit a reproducible `Programa_Cambios`

`construir_taller(cfg, excel)` and `ejecutar_simulacion(...)` in `cli.py` are GUI-free entry points; `construir_taller` (configurar + cargar_datos) is the intended base for a future batch runner of many independent parallel simulations.

**Parallel execution (process pool + per-worker initializer).** `simular()` is CPU-bound pure Python, so it runs in **separate processes**, not threads (the GIL serializes threads). `cli.py` exposes the picklable, GUI-free building blocks:
- `simular_desde_dataframes(cfg, stock_df, cambios_df, estrategia)` — build + simulate + return the taller (one run).
- `ctx_paralelo()` — the preferred multiprocessing context: **`fork`** when available (the worker inherits already-imported modules, no re-import; key when the parent is the GUI), else `spawn` (which only re-imports `cli`, never `gui.app`, since the worker callables live in `cli`).
- `init_worker_simulacion(cfg, stock_df, estrategia)` + `simular_cambios_worker(cambios_df)` — the **per-worker initializer pattern**: a `ProcessPoolExecutor(initializer=init_worker_simulacion, initargs=(cfg, stock_df, estrategia))` loads the shared **stock + config + estrategia once per worker** (stored in the module-level `_WORKER_STATE`, a private copy per process — *not* shared state across processes) and each task sends only its `cambios_df` (the lightest thing to pickle).
- `batch_simular(cfg, stock_df, lista_cambios, estrategia, max_workers)` — runs **N simulations in parallel** sharing stock+config+estrategia and varying only the `Programa_Cambios` (e.g. a seed sweep of the generator: pair with `gencambios.generar_cambios`). Returns the tallers **in the same order** as `lista_cambios` (empty list ⇒ `[]`).

This is safe because each run builds a **fresh** `TallerCilindros` and the engine has no module-level mutable state (the shift grid is per-instance). The GUI uses this **same initializer path** with `max_workers=1` (see below), so a future parallel runner is a drop-in (`batch_simular`) with no new machinery.

**Picklability of the result.** Workers return the whole `TallerCilindros` back to the parent by pickle, so the engine must be picklable. The only non-picklable attribute is `self._seq_cola = itertools.count()` (the event-queue sequence counter, valid only mid-`simular()`); `TallerCilindros.__getstate__`/`__setstate__` **drop it from the pickle and recreate it on unpickle**. Everything else (snapshots, cilindros, maquinas, alertas, `log_simulacion`) is picklable. If you add another non-picklable transient to the engine, exclude it the same way.

### GUI structure — `gui/app.py`

Single `App(CTk)` window with a sidebar and a tabbed main area:

| Tab | File | Purpose |
|-----|------|---------|
| Vista Real | `gui/vista_realtime.py` | Live playback of snapshots; jaula + CRC sections + machine widgets + queue |
| Dashboard | `gui/dashboard_principal.py` | Matplotlib stacked-area charts, buffer, machine utilization, Gantt |
| Detalle | `gui/dashboard_detalle.py` | Per-cylinder detail chart (click a cylinder in Vista Real). The "Distribución de Diámetros (Activos)" histogram paints **each SubStock's diameter zone** `[hasta, desde]` (`_pintar_zonas_substock`): a faint full-height tint over the bars + labeled `J{n}` strips stacked in **lanes** above the histogram. Since SubStock bands **may overlap**, lanes are assigned by *lane packing* (non-overlapping bands share a lane, overlapping ones get separate stacked lanes), so overlaps are visible without one zone hiding another; colors come from `JAULA_COLORS` (`config/tema.py`). The bottom-right panel is **"Evolución de SubStock (disponibles)"**: one **steps-post** line per SubStock of its `disponibles_por_substock` count over time (colored by jaula, labeled `J{n} · {nombre}`), with PARADA spans shaded via `dashboard_principal._marcar_paradas` and the shared `formatter_tiempo` x-axis (it replaced the old per-jaula change scatter timeline) |
| Inventario | `gui/tab_tabla.py` | Stateful `TabInventario`: **loads the stock** ("Cargar stock" → `App.cargar_stock_desde`, reads only the `Stock_Inicial` sheet — the change schedule no longer comes from the Excel), a **"Vista" toggle** between *Stock inicial* (from `app._stock_df`) and *Stock final* (from `app.taller.cilindros`, post-sim) shown one at a time — *Stock final* is **gated on `taller.snapshots`**: before simulating it shows empty with the hint "Ejecute la simulación para ver el stock final" (so the freshly-loaded stock isn't shown as if it were a result), **Excel-style per-column autofilters** rendered as an **inline `place()` panel** (no Toplevel — same binds-once + click-outside/Escape pattern as `gui/calendario.py`) anchored under the clicked heading, with a **search box** that filters the value list by substring **on top of** the checklist of distinct values ("(Seleccionar todo)"/Aplicar/Limpiar; active filters kept in `_filtros_col` and a ▾ marks filtered headings — the old single estado combo is gone, estado now filters as a column), and **"Descargar Excel"** of the current view. A **`<Map>` bind re-renders** the table when the tab becomes visible (`_on_map`→`_rerender`, preserving filters): `ttk.Treeview` filled while the tab is hidden — e.g. the post-sim `refrescar()` while the user sits on another tab, since CTkTabview `grid_forget()`s inactive tabs — can paint wrong until a re-fill while visible (which is why "changing the Vista corrected it") |
| KPIs | `gui/tab_kpis.py` | Key performance indicators |
| Generación de Cambios | `gui/tab_generacion.py` | Self-contained synthetic-change workflow: generator **config** (algorithm, desbaste threshold, **fecha inicio/fin** of the window, laminador shift regime — moved here out of Configuración; the fecha inicio/fin fields use an **inline calendar dropdown** `gui/calendario.SelectorFecha` that overlays the window via `place()` rather than a separate Toplevel popup), **adaptation** (upload history → refit incremental or from scratch + persisted-model info + a **"Ver / ajustar adaptación" popup** to pick a model, refit it on the held `app._historia_df`, and Apply/persist — it follows a **preview → confirm → apply** flow (changing the model combo **previews live** via `_preview()`: recomputes the fit and refreshes the diff/chart **without confirming**, and *resets* the confirmed model so "Aplicar" stays disabled; **"Ajustar"** (`_ajustar`) **confirms/stages** the previewed model into `pop["modelo"]` and enables "Aplicar"; **"Aplicar"** (`_aplicar`) persists **only** the confirmed `pop["modelo"]`, never a model that was merely previewed — a status label tracks the state). The popup states *what* is being adapted, shows an **"Antes → Después" parameter table** combining model-agnostic per-jaula aggregates (`_parametros_modelo`/`_muestras_jaula`) **and the model's own learned parameters** (`_parametros_modelo_especificos`: empírico ⇒ duration/desbaste σ + range; markov ⇒ nº estados + dominant initial state + top transition — markov state labels `d{i}:tipo` are shown via `_etiqueta_estado` as readable hour ranges like `<12h·desbaste`/`12–24h·produccion` instead of the raw `d0/d1…` buckets, which read as "ceros"), changed values in green; a **ⓘ help button** showing **only the selected model's** `descripcion` (`_mostrar_ayuda_modelo`); and a **chart with a `CTkSegmentedButton` toggle** — "Historia subida" (plots the uploaded history as changes via `_historia_a_cambios` + `_construir_figura`) vs "Generado (antes→después)" (overlays `generar_cambios` from the applied model, hollow, vs the temp model, filled, via `_figura_comparacion`)), **generation** (reproducible seed) and a Matplotlib **timeline** of generated changes per jaula shading **non-working spans of the laminador regime in grey** (`_tramos_sin_turno`) and the line-stopped (PARADA) spans in red (reuses `dashboard_principal._marcar_paradas`), plus **clickable ▼ "magnetic" parada markers** (`_inicios_parada` + `picker=True` + `mpl_connect("pick_event")`) that call `app.ir_a_momento(idx)` to seek playback to that snapshot and switch to Vista Real. Like `tab_config` it reads/writes `app.user_cfg` and drives `app.taller`. **"Generar cambios" is decoupled from simulation**: it builds the taller from the stock + `Programa_Cambios`, leaves them in `app._cambios_generados` and redraws the timeline, but does **not** simulate — the sidebar "Ejecutar Simulación" runs it (then `_simular_finalizado` calls `gen_widget.refrescar_timeline()` so PARADA bands appear). "Subir Excel de cambios" loads a `Programa_Cambios` sheet directly |
| Configuración | `gui/tab_config.py` | Responsive two-column layout: global params (incl. cooling time) + SubStock ranges (left); machine park CRUD + simulation params (max iterations) (right). Below `_UMBRAL_APILADO` px wide the columns stack to full width (`_on_resize`/`_aplicar_layout`) so the machine table's "Prioridad" column isn't clipped on narrow screens. **SubStock rows are bound 1:1 to `cantidad_jaulas`**: there is no "add jaula" button — the rows are created/destroyed by `_sincronizar_filas_rango(n)` when "Cantidad de jaulas" changes (on `<Return>`/`<FocusOut>`, never per-keystroke, to preserve values while typing a multi-digit number), the jaula number is a read-only label (only Desde/Hasta are editable), and `_guardar` verifies `len(rangos) == cantidad_jaulas` (`_recoger_rangos(esperado=...)`) so no jaula is left without a band and no band targets a non-existent jaula. Saves to `user_config.json` and applies via `taller.configurar()`. The shift-grid popup editor is shared with the generación tab via `gui/editor_turnos.abrir_editor_turnos` |
| Consola | `gui/tab_consola.py` | Simulation log and alerts |

Playback is driven by `self.after()` ticks in `App`; at each tick it calls `vista_rt.actualizar(snapshot)` on the Tk main thread. The sidebar controls are **step-back ⏪ / play / stop / step-forward ⏩** (`_paso(±1)`, clamped, pauses) plus **discrete speed buttons 1×/2×/5×/10×** (`_set_velocidad`, highlights the active one — replaces the old speed slider; `velocidad_reproduccion` feeds `_playback_tick`'s `1000/v` ms interval) and the progress slider as seek. A thin `tk.Canvas` **above the slider** draws a ▼ dot per **PARADA start** (`_redibujar_paradas_sidebar` using `tab_generacion._inicios_parada`); clicking a dot maps the x to the nearest parada index and calls `ir_a_momento(idx)`.

**The simulation runs in a separate process, not a thread.** `simular()` is CPU-bound pure Python, so a thread still froze the Tk loop (GIL). `App._simular` builds a `ProcessPoolExecutor(max_workers=1, mp_context=ctx_paralelo(), initializer=init_worker_simulacion, initargs=(cfg, stock_df, estrategia))` and submits `simular_cambios_worker(cambios_df)` — **the exact same initializer path as the parallel `cli.batch_simular`** (see the parallel-execution note above), so it's a drop-in for a future parallel runner. It polls the `future` with `self.after(100, _poll_simulacion)` — the GUI stays responsive and shows an **indeterminate `CTkProgressBar`** in the status bar. On completion the returned taller (pickled back: snapshots/cilindros/maquinas/alertas) **replaces `self.taller`**, then `_simular_finalizado` dumps its `avisos_carga` **and `log_simulacion`** to the console and refreshes everything. The live `callback_log` can't cross the process boundary, so `simular()` **accumulates** every log line into `taller.log_simulacion` (cleared at the start of each run); that list travels back via pickle and is what restores the change/PARADA/BAJA log in the console (the CLI still also streams live via `callback_log=print`). `ctx_paralelo()` prefers the **fork** context so the child inherits already-imported modules (and the worker callables live in `cli`, so even spawn never re-imports `gui.app`).

**Dashboard, Análisis and KPIs render an empty preview before simulating** (banner `dashboard_principal.MSG_SIN_DATOS` "Se mostrarán datos una vez corrida la simulación" + zeroed/empty charts): `crear_dashboard_principal`/`crear_dashboard_detalle` build their panels empty when `not t.snapshots` (instead of returning blank, via the shared `dashboard_principal.rellenar_preview_vacio(fig, celdas, styler)` — each dashboard passes its own `_style_ax`), `tab_kpis.llenar_kpis` shows the banner and derives machine names from `taller.maquinas` so utilization cards read 0%. `App._render_paneles()` (called at startup, on stock load, and post-sim) refreshes all three. Time axes use `dashboard_principal.formatter_tiempo(t0,t1)` which drops the hour (`%d/%m`) once the span exceeds 7 days and **adds the year (`%d/%m/%y`) once it exceeds 365 days** (so multi-year histories don't lose the year) to avoid overlapping labels (reused across both dashboards and the generación timeline).

Dashboards are rendered with Matplotlib `Figure` objects embedded via `FigureCanvasTkAgg`. The `App._figs` dict caches open figures; always close the old figure before creating a new one to avoid memory leaks.

### Key constants (in `modelos/taller.py`)

```python
_BUFFER_CRC_SIZE = 2      # cylinders required to form a working pair
_MAX_ITERACIONES_SIM = 10_000   # only the DEFAULT for self.max_iteraciones
```

`_MAX_ITERACIONES_SIM` is just the seed for the instance attribute `self.max_iteraciones`; the loop in `simular()` reads `self.max_iteraciones` (configurable). Likewise `self.tiempo_enfriado_h` (default `0.0`) controls the cooling step.

### Adding a new simulation dataset

Copy and adapt `datos/generar_caso_parada.py`. The Excel must have the two **data** sheets (`Stock_Inicial`, `Programa_Cambios`) with the column names shown in that script. Run the script to produce the `.xlsx`, then load it from the GUI. The taller config (global params, machines, ranges) comes from `config/user_config.json`, not the Excel — adjust it from the Configuración tab or `cli.py config`. To seed/migrate config from an old 4-sheet Excel, run `python cli.py config import-excel <excel>`.

### Theme / colors

All UI color constants are in `config/tema.py` and imported with `from config.tema import *`. The app uses CustomTkinter Dark mode. Do not hardcode color strings in GUI files.

### GUI: DPI scaling and Vista Real layout

`gui/app.py` calls `ctk.deactivate_automatic_dpi_awareness()` at module load, **before** the window is created. This is required: when the window is dragged between monitors with different DPI scaling, CustomTkinter's auto-rescaler tries to reconfigure the already-destroyed dropdown of a `CTkComboBox` and raises `TclError: invalid command name ...dropdownmenu`. Deactivating it pins the per-monitor auto-rescale callback off and removes that callback. **Tradeoff:** widgets are not auto-rescaled *live* when moved between monitors.

To still scale on high-DPI screens, `App.__init__` applies **one fixed scale at startup** (not the per-monitor live rescale): it reads the display DPI via `self.winfo_fpixels("1i")` and computes a clamped factor with `gui/dpi.py::factor_escala_dpi(dpi)` (pure, tested in `tests/test_dpi.py`; 96 DPI ⇒ 1.0, clamped to `[1.0, 2.0]`), then calls `ctk.set_widget_scaling`/`set_window_scaling` **before** `geometry()`. This is safe because with `deactivate_automatic_dpi_awareness=True`, `ScalingTracker.update_scaling_callbacks_all` uses `widget_scaling` directly and never re-arms the crashing per-monitor callback. With a standard 96-DPI screen the factor is 1.0, byte-for-byte the previous behavior. Do not re-enable the *automatic* awareness without first solving the combobox-dropdown crash.

Also at module load, `gui/app.py` wraps `CTkBaseClass._update_dimensions_event` with a guard (`_safe_update_dimensions_event`): a widget can receive a `<Configure>` event already queued in Tk **after** it was destroyed (its `_canvas` is `None`), so `_update_dimensions_event` → `_draw` would raise `AttributeError: 'NoneType' object has no attribute 'winfo_exists'`. The wrapper is a no-op when `_canvas` is `None` (the widget is gone — nothing to redraw), live widgets are unaffected. It happens e.g. when the inline filter panel (a `CTkScrollableFrame`) is closed/recreated mid-resize. The monkeypatch is wrapped in `try/except` so a future CTk layout change degrades gracefully instead of breaking startup.

In `gui/vista_realtime.py`, the machine widgets ("rectificadoras") use a `grid` of uniform weighted columns (`grid_columnconfigure(..., weight=1, uniform="maq")`, `sticky="ew"`) so they share the available width responsively — do **not** give them a fixed width. The "Cargue un Excel y ejecute la simulación..." guidance hint (`self.hint_inicio` in `gui/app.py`) lives in the **sidebar** under the action buttons (not as an overlay on Vista Real), and is hidden with `grid_remove()` in `_sincronizar_vista_con_taller()` once data is loaded. The "EN ENFRIAMIENTO" section lives in the **right** column (under the queue) to keep all jaulas visible in the left column.

## Key Design Decisions

These are non-obvious invariants that must be preserved when modifying the engine.

### Machine selection: priority filter, then strategy
When a free machine picks a cylinder in `asignar_trabajo_maquinas()`, `seleccionar_siguiente_de_cola(cola, maquina)` selects in two steps: (1) it first filters the queue to cylinders whose `tipo_rectificado_actual` matches the machine's `prioridad_defecto`; (2) it applies the configured strategy over that subset. If **no** cylinder matches the machine's priority, it falls back to the **whole** queue and applies the strategy there. The machine's priority therefore biases *which* job it takes, but the rectification `tipo` performed is still the cylinder's own type (or `prioridad_defecto` only when the cylinder has none). Strategies are `EstrategiaSeleccion` objects (`clave`, `etiqueta`, `seleccionar(cola, maquina)`) in the `ESTRATEGIAS_SELECCION` registry (`modelos/estrategias.py`); `seleccionar` receives the already priority-filtered queue and may inspect the machine (e.g. `_MenorMmDesbasteFifoProduccion` picks min mm when the machine prioritizes desbaste, FIFO otherwise). Add a new strategy by subclassing and registering it — the GUI combo (`gui/app.py`) and CLI `--estrategia` choices (`cli.py`) are derived from the registry, so no hardcoded list needs updating. The GUI shows `etiqueta` and maps it back to `clave`; `_SENTIDO_TOMA` in `gui/vista_realtime.py` should get a matching entry for the queue-direction hint.

### Cage assignment by perfil: diameter pre-filter, then strategy (decide vs apply)
A cylinder carries a physical **perfil** (bombatura, `Cilindro.perfil`) that only changes when ground. SubStock diameter bands **may overlap** and contiguous cages may **share a perfil**, so a cylinder can be admissible for several cages. At the moment a machine **starts** grinding (`asignar_trabajo_maquinas` → `iniciar_rectificado`, the physical instant the perfil is cut), `_asignar_jaula_destino(cil, nuevo_diam, tiempo)` decides the destination cage: (1) **hard diameter pre-filter** — only cages whose SubStock contains the **projected** diameter `nuevo_diam = diametro − mm` are candidates (a cylinder is **never** assigned to a cage whose band rejects its diameter, mirroring the machine-priority pre-filter); (2) the configured `EstrategiaAsignacion` (registry `ESTRATEGIAS_ASIGNACION` in `modelos/estrategias.py`, default `_JaulaMasNecesitada` = most-deficient cage, stopped cages first) picks one. The engine **decides** (cage ⇒ perfil); the machine only **applies** — `perfil` is passed as an input to `iniciar_rectificado`, which stamps `cil.perfil`. The chosen cage is tagged on `cil.jaula_destino` (reset to `None` on retirement at CAMBIO, re-decided next grind). `obtener_disponibles_para_jaula` then honors destino + perfil + diameter (`_admisible_en_jaula`). Add a strategy by subclassing `EstrategiaAsignacion` and registering it — GUI combo (`gui/tab_config.py`) and CLI `--estrategia-asignacion` (`cli.py`) derive from the registry. **Golden invariant:** with non-overlapping bands and **no** perfil (default config), the projected diameter falls in exactly one band ⇒ one candidate ⇒ identical to the old geometric pull, so the existing golden scenarios are byte-for-byte unchanged (only the new `perfiles_jaula_mas_necesitada` scenario was added). Persisted in `config/user_config.json`: per-cage `rangos[i]["perfil"]` (optional) and root `estrategia_asignacion`.

### Re-perfilado of non-placeable cylinders
If a cylinder becomes `Disponible` but its `(perfil, diámetro)` is admissible in **no** cage (e.g. its diameter lands in a gap between bands), it is **not** left as dead stock: `_finalizar_y_continuar` (right after `finalizar_rectificado`) checks `_es_colocable(cil)`; if false and `diámetro > diametro_minimo`, it logs an **INFO alert** and **re-queues** the cylinder to `A_RECTIFICAR` with a forced **producción `_MM_REPERFILADO` (0.8) mm** pass and `jaula_destino = None`. The next `iniciar_rectificado` re-runs `_asignar_jaula_destino` with the new projected diameter, so the strategy re-decides. The loop terminates on its own: each pass trims 0.8 mm until the diameter falls in a band, or drops below `diametro_minimo` ⇒ **BAJA** (existing branch in `asignar_trabajo_maquinas`). Under contiguous bands without perfiles this never triggers (reinforcing the golden invariant).

### Cooling (Enfriando) is opt-in and physical
With `tiempo_enfriado_h == 0.0` (default) the cooling state does **not** exist: the CAMBIO handler sends retired cylinders straight to `A_RECTIFICAR`, exactly as before. With a positive value, each retired cylinder goes to `ENFRIANDO` and a `FIN_ENFRIADO` event is scheduled at `t + tiempo_enfriado_h`. Like `FIN_RECT`/`REPONER_CRC`, `FIN_ENFRIADO` **always executes** — it is never deferred during a PARADA and is **not** shifted by `_reanudar_linea` (cooling is a wall-clock physical process, not a scheduled change). `tipo_rectificado_actual`/`mm_a_rectificar` are stamped at CAMBIO time and survive the cooling step. Cooling cylinders are not in any jaula, the CRC, or a machine; they are tracked purely by state and surfaced via `Snapshot.detalle_enfriando` (the global "EN ENFRIAMIENTO" section in Vista Real). `generar_snapshot()` counts them automatically because it iterates the whole `EstadoCilindro` enum. The stacked-area chart (`TallerCilindros.ESTADOS_NOMBRES`), the detail map (`ey` dict in `dashboard_detalle.py`), and the table filter (`tab_tabla.py`) all **derive** their state lists from `EstadoCilindro` (no hardcoded `"Enfriando"`), so a new state added to the enum surfaces in all three automatically.

### Work shifts (esquema de trabajo) gate machine rectification, not the line
Each `MaquinaRectificadora` carries an optional weekly operative calendar `grilla_operativa` — a **7×24 boolean grid** (`grid[weekday][hour]`, `weekday` from `datetime.weekday()`, 0 = Monday). `None` ⇒ **always operative (24/7)**, which reproduces the historical behavior byte-for-byte (so the golden master is unchanged by default). The user-facing config is 3 daily shifts (T1 06–14, T2 14–22, **T3 22–06 next day**) per day-of-week; `modelos/turnos.py` (pure domain, no GUI/engine state) is the single source of truth for shift hours, presets (`PRESETS`/`PRESET_LABELS`: `24x7`, `off`, `lv3`, **`3escuadras`** = all shifts except Sat-T3 and all of Sunday), compact-string parse/format, `resumen()`, and `expandir(turnos) → grid`. The GUI shift editor (`gui/editor_turnos.py`) offers the presets in a **`CTkOptionMenu` dropdown** (not a row of buttons, so the popup width is constant as presets grow) and the CLI `--turnos-preset` choices both derive from `PRESETS`, so a new preset surfaces everywhere automatically. **T3 belongs to the day it starts**: its hours 22–23 land on day `d` and 00–05 on day `d+1` (week wraparound). The grid is built per `TallerCilindros` instance in `configurar_maquinas()` — no module-level mutable state, so thousands of parallel sims are safe. The grid is also the hook for a future random machine-failure feature (turn off a random % of hours).

Only **machine rectification** is gated by the calendar; the rolling line never stops for shifts — `CAMBIO` and `FIN_ENFRIADO` fire as usual. `iniciar_rectificado` computes `tiempo_fin_rectificado` via `calcular_fin_operativo(inicio, minutos)`, which walks the grid hour-by-hour consuming only operative minutes and **bakes non-operative gaps into the finish time** — so a half-done cylinder stays mounted (machine remains `ocupada`) and "resumes where it stopped" with no preemption logic. `asignar_trabajo_maquinas` skips a machine that is not `esta_operativa(tiempo)`; if such a free machine has queued work, it schedules **one** `REANUDAR_MAQUINA` event at `proxima_apertura(tiempo)` (deduped via `maq._despertar_programado`) to wake it when its shift reopens. Snapshot progress uses `minutos_operativos_entre(inicio, tiempo) / minutos_trabajo_actual` (not wall-clock), so the progress bar doesn't advance during a closed shift. With `grilla_operativa is None` all these helpers collapse to the old wall-clock arithmetic.

**Two utilization KPIs** (`modelos/kpis.py`, the single source consumed by the KPIs tab, CLI and dashboard) form an **OEE-style decomposition** where `disponible × neta == overall utilization (ocupada/calendar)`: **disponible** = `tiempo_operativo / tiempo_calendario` (key `utilizacion_maquinas_pct`; the **availability factor** = fraction of the calendar the machine is in-shift, where operative = calendar − closed-shift time = `minutos_operativos_entre(snapshots[0], snapshots[-1])`; **100% under 24/7**) and **neta** = `tiempo_total_ocupada_min / tiempo_operativo` (key `utilizacion_neta_pct`; the **utilization of available time** = ocupada / operative, where ocupada = operative − idle (machine free) − failures; **failures aren't modeled yet ⇒ 0**). **Regenerating the golden:** changing `utilizacion_maquinas_pct` from `ocupada/calendar` to `operativo/calendar` changes its value even for the 24/7 golden scenarios (it becomes 100% for every machine), so the golden master was regenerated on purpose. The Dashboard utilization panel draws **two grouped bars per machine** (disponible in `ACCENT`, neta in `PURPLE`) sourced from `calcular_kpis()` (the single source — not recomputed inline), and the Gantt shades each machine's closed-shift spans in `RED_DARK` (`_tramos_parada_maquina`). The **KPIs tab** (`gui/tab_kpis.py`) renders two separate sections — "UTILIZACIÓN DISPONIBLE" and "UTILIZACIÓN NETA" — listing machines in the **same order** (`list(k["utilizacion_maquinas_pct"])`); each machine card's border, fill tint and percentage text are colored by `_color_util(pct)`, a red→yellow→green gradient (0% red, 50% yellow, 100% green) interpolated from the `RED`/`YELLOW`/`GREEN` tema constants.

**Vista Real surfaces the per-machine shift state.** `generar_snapshot()` records `Snapshot.detalle_maquinas_operativa[nombre] = maq.esta_operativa(tiempo)` (a plain `{nombre: bool}`, distinct from `detalle_maquinas` which is `None` for any free machine and so can't tell "free in shift" from "off shift"). `gui/vista_realtime.py` renders each machine widget in one of **three** states by reading both dicts: **rectificando** (busy → purple border + cylinder), **libre y operativa** (free + operative → GREEN border + "● Libre (operativa)", the highlight requested for an idle machine that *could* take work), and **fuera de turno** (free + not operative → `RED_DARK` border + "⏸ Fuera de turno"). Under 24/7 (`grilla_operativa is None`) `esta_operativa` is always `True`, so a free machine always shows the green "operativa" highlight. **Adding `detalle_maquinas_operativa` to `Snapshot` changes `snapshots_sha256`** (it serializes every `Snapshot.__dict__` field) but not KPIs/n_snapshots/alerts/cylinders — this is an intended snapshot-data change, so the golden was regenerated on purpose.

### PARADA is all-or-nothing
`_instalar_pareja_o_parar()` never installs a partial pair. If there are fewer than `_BUFFER_CRC_SIZE` cylinders available in a jaula's range, it installs **none** and returns `False`. A jaula with only one cylinder working is not a valid state.

### The CRC buffer is filled in pairs — never a lone cylinder
The Disponible→CRC transport moves a **complete pair** (`_BUFFER_CRC_SIZE`) per trip, never a single cylinder, so a jaula's CRC count is always **0 or 2** (never odd). Two places enforce this: (1) `reponer_buffer_crc()` is **all-or-nothing** — if there aren't enough disponibles to complete the pair it moves **none** (they stay Disponible) and returns `False`; (2) at startup, `_garantizar_parejas_iniciales()` does **not** park a lone partial cylinder in the CRC — it leaves it **Disponible but reserved** to its jaula via `jaula_destino` (so no other jaula can take it) and marks the jaula PARADA. Either way the lone cylinder waits as Disponible; reactivation still works because `_instalar_pareja_o_parar()` forms the pair from **CRC + disponibles** together (and `obtener_disponibles_para_jaula` honors the `jaula_destino` reservation). The golden master is **unchanged** (no golden scenario produced an odd CRC). Guarded by `tests/test_crc_pareja.py` (unit + the invariant "no snapshot shows an odd `crc_por_jaula`").

### PARADA stops the entire line, not just the affected jaula
When any jaula goes PARADA, `_linea_parada_desde` is set and ALL subsequent `CAMBIO` events (those with `tiempo > _linea_parada_desde`) are moved to `_cambios_diferidos`. CAMBIO events at the exact same timestamp as the stoppage **do** execute. The line resumes only when **no** jaula remains stopped.

### Machines and CRC replenishment never stop during a PARADA
`FIN_RECT` and `REPONER_CRC` events always execute. This is intentional: rectification is what produces the stock that allows the line to restart. `asignar_trabajo_maquinas()` is called unconditionally after every `FIN_RECT`, even during a stoppage.

### Reactivation has priority over CRC replenishment
In the `FIN_RECT` handler, `_intentar_reactivar_jaulas()` is called **before** `_programar_reposicion_crc()`. This ensures a freshly rectified cylinder goes to rearm a stopped jaula first.

### Two-layer time: `ev_sim.tiempo` vs `ev.tiempo`
`_EventoSim.tiempo` is the actual processing time (may be shifted during line resumption). `ev_sim.datos.tiempo` (the original `EventoCambio.tiempo`) is the time from the Excel file. All simulation logic (cylinder events, snapshots, machine assignment) must use `ev_sim.tiempo`, never `ev.tiempo`.

### Event queue ordering: `heapq` keyed by `(tiempo, secuencia)`
The event queue is a `heapq` of `_ItemCola = (tiempo, secuencia, evento)`. **Always push via `_push_evento(cola, evento)`** — never `heapq.heappush` directly — so the `secuencia` counter (`self._seq_cola`, an `itertools.count()` reset at the top of `simular()`) is assigned in insertion order. That counter is what makes the order deterministic: at equal `tiempo`, events fire in **FIFO insertion order**, exactly reproducing the old `list` + stable `sort(key=tiempo)`. Two consequences to respect when editing handlers: (1) at a given timestamp, the **order in which you push matters** — e.g. `_handle_cambio` pushes the machine assignments *before* the CRC reposition, so assignments win ties; keep that order if you touch it. (2) `_reanudar_linea` can't just shift tiempos in place (the heap array isn't fully sorted): it rebuilds from `sorted(cola)` (canonical pop order), shifts the deferred/remaining CAMBIO events, stable-sorts by `tiempo`, then **re-stamps `secuencia`** in that order and `heapq.heapify`s. This keeps the post-resume order identical to the old code and leaves any later-pushed event (higher seq) after equal-`tiempo` ones.

### SubStock boundary convention
`hasta < diámetro <= desde` — `hasta` is exclusive (lower bound), `desde` is inclusive (upper bound). This is the opposite of what the variable names suggest at first glance.

### SubStock auto-derivation
`cargar_datos_desde_dataframes()` (which `cargar_datos()` delegates to) is self-sufficient for ranges: if `lista_substocks` is empty when it finishes loading, `_derivar_substocks_por_defecto()` divides the global diameter range into N equal bands (one per jaula). This means code that loads data without calling `configurar()`/`configurar_substocks()` first still gets working ranges. **Machines are not auto-derived** — they must come from `configurar()` (the config JSON), since rates can't be inferred. The App and CLI always call `configurar()` before loading, which takes precedence and is not affected by this fallback.

### Cylinders marked BAJA in Excel above the minimum diameter
The simulation does **not** change their state — the Excel is the source of truth. They may be out of service for reasons unrelated to diameter (cracks, defects). A warning is added to `taller.avisos_carga` and shown in the console after loading.

### Rectify-then-BAJA: a doomed pass is still ground before scrapping
When a queued pass would project a diameter below `diametro_minimo`, the cylinder is **not** scrapped in place. `asignar_trabajo_maquinas` lets it go through `iniciar_rectificado` like any other (with `jaula_destino=None`, since no SubStock admits the projected diameter); the grind **runs and actually reduces the diameter**, and only at `_finalizar_y_continuar` — right after `finalizar_rectificado`, **before** the re-perfilado branch — does the cylinder fall to **BAJA** if its (now real) diameter dropped below the minimum. So a scrapped cylinder's final diameter reflects its last cut (e.g. ends at 517, not frozen at 522). This **changes the engine on purpose** (it occupies a machine for the final pass); the golden master happens to be **unaffected** because no golden scenario (≤ 1 week) grinds a cylinder below the minimum — if a future scenario does, regenerate the golden deliberately.

### Single CRC transport resource
Only one pair of cylinders can be in transit to CRC at a time, serialized via `_recurso_crc_libre_en` and `_reposicion_pendiente`. Do not add parallel CRC transport logic.

### Snapshot granularity
A snapshot is generated after **every** event (CAMBIO, FIN_RECT, REPONER_CRC, FIN_ENFRIADO). Do not skip snapshots for performance — the GUI seekbar depends on having a snapshot at each simulation step. The cost of each snapshot was instead cut by making `generar_snapshot()` a single pass over `self.cilindros` (see step 4 of the simulation flow); that is where snapshot performance work belongs.
