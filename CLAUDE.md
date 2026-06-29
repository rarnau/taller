# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Launch the GUI (Qt / PySide6)
python main_qt.py

# Generate test datasets
python datos/generar_caso_parada.py
```

> **GUI migration (Tk → Qt):** the application now runs on a **PySide6 (Qt)**
> front-end under `gui_qt/` (`main_qt.py`). The old CustomTkinter/Tkinter GUI
> and its `main.py` entry point were removed. The only survivors of the old
> `gui/` package are the two **pure-Matplotlib** rendering modules
> `dashboard_principal.py` and `dashboard_detalle.py`, which `gui_qt` reuses
> for its Dashboard/Análisis panels (they have no Tk dependency). See
> *GUI structure* below.

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
main_qt.py
└── gui_qt/main_window.py   # Qt MainWindow — wires UI to model, owns playback state
    ├── modelos/taller.py   # TallerCilindros — all simulation logic (no GUI imports)
    ├── gui_qt/*.py         # Pure Qt display components (model only via main_window/services)
    └── gui/dashboard_*.py  # Shared Matplotlib renderers reused by gui_qt (no Tk)
```

**The model layer (`modelos/`) must never import from `gui/` or `gui_qt/`.**

### Simulation engine — `modelos/taller.py`

`TallerCilindros` is the central class. Key flow:

0. **Configure** — `configurar(cfg)` applies the persistent config dict (from `config/user_config.json`): global params, machine park (`configurar_maquinas`), SubStock ranges (`configurar_substocks`) and sim params (`tiempo_enfriado_h`, `max_iteraciones`). **Must run before `cargar_datos()`** — the stock needs `cantidad_jaulas` and `diametro_minimo`, and the change schedule validates against the created jaulas.

1. **Load** — `cargar_datos(ruta_excel)` reads two mandatory **data** sheets:
   - `Stock_Inicial` — cylinder inventory with initial states
   - `Programa_Cambios` — scheduled change events

   It clears only per-run data (cylinders, jaulas, events, alerts, snapshots), **not** the machines/substocks/global params set by `configurar()`. If the Excel still carries the old `Configuración`/`Máquinas` sheets they are **ignored** (with an aviso). `cargar_datos()` delegates to `cargar_datos_desde_dataframes(stock_df, cambios_df)`, which a future batch runner can call directly with in-memory DataFrames (no disk I/O per run).

2. **Simulate** — `simular(callback)` runs a priority-queue DES loop. Internal event type `_EventoSim(tipo, tiempo, datos)` has six types:
   - `"CAMBIO"` — a scheduled jaula change (datos = `EventoCambio`)
   - `"FIN_RECT"` — a machine finishes rectification (datos = machine name str)
   - `"REPONER_CRC"` — a Disponible cylinder arrives at the CRC buffer (datos = jaula int)
   - `"FIN_ENFRIADO"` — a cylinder finishes cooling and enters the rectification queue (datos = cylinder id str). Only generated when `tiempo_enfriado_h > 0`.
   - `"REANUDAR_MAQUINA"` — a machine becomes workable again (shift reopens **or** failure ends) and retries taking work (datos = machine name str). Only generated when a free machine is **not workable** (out of shift or in failure) with a non-empty queue. Like `FIN_RECT`/`FIN_ENFRIADO` it **always executes** (never deferred by a PARADA) and is **not** shifted by `_reanudar_linea` (it is wall-clock). See the work-shift design decision below.
   - `"REPOSICION"` — a batch of brand-new cylinders arrives to replace BAJAs (datos = `PedidoReposicion`). Only generated by a replenishment strategy (see the design decision below). Like `FIN_RECT` it **always executes** (never deferred by a PARADA — the new stock can reactivate the line) and is **not** shifted by `_reanudar_linea` (wall-clock logistics).

   At the top of each run `simular()` resets the **per-run state** so re-running on the same instance never accumulates: it clears `alertas`/`snapshots`/`log_simulacion`/`_sin_maquina_alertados` and calls `MaquinaRectificadora.reiniciar_estado_corrida()` on every machine (drops `historial_trabajo`, `tiempo_total_ocupada_min`, `ocupada`/`cilindro_actual` and the in-progress hitos, **keeping** the config: tasas, prioridad, `grilla_operativa`). Without the machine reset, a second `simular()` on the same taller would double-count occupancy and yield physically impossible utilization (>100%). Note this does **not** reset the cylinders' diameter/state (the engine has no copy of the original stock); a clean re-run still goes through `construir_taller`/`cargar_datos`.

   The queue is a **`heapq`** of tuples `(tiempo, secuencia, evento)` — `_ItemCola`. Push (`_push_evento`) and pop (`heapq.heappop`) are `O(log n)`. The `secuencia` field (an `itertools.count()` per run, `self._seq_cola`) breaks `tiempo` ties in **FIFO insertion order** and keeps `_EventoSim`s from ever being compared. This reproduces the exact ordering of the old `list` + stable `sort(key=tiempo)`; preserve the insertion order at each call site (see the queue-ordering note under Key Design Decisions).

3. **PARADA (line stoppage)** — if after a `CAMBIO` there is no stock to form a complete pair (`_BUFFER_CRC_SIZE = 2`) for a jaula:
   - `_parar_jaula()` marks the jaula `parada=True` and records `_linea_parada_desde`
   - All subsequent `CAMBIO` events with `tiempo > _linea_parada_desde` are moved to `_cambios_diferidos` (not executed)
   - `FIN_RECT` and `REPONER_CRC` always execute — machines keep running and CRC can be replenished
   - When `_intentar_reactivar_jaulas()` succeeds (called from `FIN_RECT` handler), `_reanudar_linea()` reprograms all deferred and remaining-in-queue CAMBIO events by the stoppage duration — measured in **line working time** when a line shift regime is configured (see "PARADA reprogramming respects the line shift regime"), else wall-clock

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
- `estrategia_seleccion` / `estrategia_asignacion` / `estrategia_reposicion` — `clave` of the chosen queue-selection / cage-assignment / **cylinder-replenishment** strategy (defaults `mayor_diametro` / `jaula_mas_necesitada` / **`ninguna`**)

`DEFAULTS` is seeded from the reference Excel `datos/simulacion_140cils_1semana.xlsx` (machines G36/F36/F60). `cargar_config()` **migrates** old configs: it fills missing keys from defaults and folds the old loose `prioridades_maquinas` dict into each machine's `prioridad`.

Getters: `obtener_config_global`, `obtener_maquinas`, `obtener_rangos`, `obtener_prioridades` (derived from `maquinas`), `obtener_tiempo_enfriado`, `obtener_max_iteraciones`, `obtener_estrategia_seleccion`/`obtener_estrategia_asignacion`/`obtener_estrategia_reposicion`, `obtener_turnos(cfg, nombre)`. Mutators (single CRUD layer shared by CLI and GUI): `set_config_global`, `add_maquina`/`set_maquina`/`remove_maquina` (both take an optional `turnos` dict), `set_rango`/`remove_rango`, `set_sim`, plus `cfg_desde_excel(excel)` to seed/migrate from an old 4-sheet Excel.

**Coherence jaulas ⇄ rangos** is enforced by a single shared validator: `problemas_coherencia(cfg)` returns a list of human-readable problems (empty ⇒ OK) and `verificar_coherencia(cfg)` raises `ValueError` if any. A coherent config has **exactly one SubStock range per jaula numbered `1..cantidad_jaulas`** (no missing, extra, or duplicate jaula). The mutators do **not** enforce it (CLI editing is incremental, so intermediate states may be inconsistent); instead it is applied at the right boundaries: the **GUI** (`gui_qt/config_qt.py`) validates the candidate before persisting (and the SubStock rows are auto-synced to `cantidad_jaulas`, so it stays consistent); the **CLI** `config global`/`config jaula` commands print a **non-fatal `Aviso:`** to stderr after saving (so you can bump jaulas then add the new range in a later command); and `construir_taller(cfg, excel)` calls `verificar_coherencia` as a **hard error before any simulation** — so an incoherent config can never silently run (a missing band would otherwise let `obtener_disponibles_para_jaula` return all cylinders unfiltered, and a band for a non-existent jaula is ignored).

At startup, `MainWindow.__init__` (`gui_qt/main_window.py`) calls `taller.configurar(self.user_cfg)` (one call that builds machines, globals, ranges and sim params); it is re-applied before each file load and simulation. The `Configuración` tab (`gui_qt/config_qt.py`) edits all of these at runtime and writes them back. The CLI manages them via `cli.py config ...` subcommands; `--tiempo-enfriado`/`--max-iteraciones` on `cli.py simular` still override the JSON for a single run.

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
- `ctx_paralelo()` — the preferred multiprocessing context: **`fork`** when available (the worker inherits already-imported modules, no re-import; key when the parent is the GUI), else `spawn` (which only re-imports `cli`, never the GUI, since the worker callables live in `cli`).
- `init_worker_simulacion(cfg, stock_df, estrategia)` + `simular_cambios_worker(cambios_df)` — the **per-worker initializer pattern**: a `ProcessPoolExecutor(initializer=init_worker_simulacion, initargs=(cfg, stock_df, estrategia))` loads the shared **stock + config + estrategia once per worker** (stored in the module-level `_WORKER_STATE`, a private copy per process — *not* shared state across processes) and each task sends only its `cambios_df` (the lightest thing to pickle).
- `batch_simular(cfg, stock_df, lista_cambios, estrategia, max_workers)` — runs **N simulations in parallel** sharing stock+config+estrategia and varying only the `Programa_Cambios` (e.g. a seed sweep of the generator: pair with `gencambios.generar_cambios`). Returns the tallers **in the same order** as `lista_cambios` (empty list ⇒ `[]`).

This is safe because each run builds a **fresh** `TallerCilindros` and the engine has no module-level mutable state (the shift grid is per-instance). The GUI uses this **same initializer path** with `max_workers=1` (see below), so a future parallel runner is a drop-in (`batch_simular`) with no new machinery.

**Picklability of the result.** Workers return the whole `TallerCilindros` back to the parent by pickle, so the engine must be picklable. The only non-picklable attribute is `self._seq_cola = itertools.count()` (the event-queue sequence counter, valid only mid-`simular()`); `TallerCilindros.__getstate__`/`__setstate__` **drop it from the pickle and recreate it on unpickle**. Everything else (snapshots, cilindros, maquinas, alertas, `log_simulacion`) is picklable. If you add another non-picklable transient to the engine, exclude it the same way.

### GUI structure — `gui_qt/main_window.py`

The GUI is a **PySide6 (Qt)** application. `main_qt.py` creates the
`QApplication`, applies the stylesheet from `gui_qt/theme.py::build_qss()`
(QSS, Dark theme; color constants still come from `config/tema.py`), and shows
`gui_qt/main_window.py::MainWindow` (a `QMainWindow`). The window has a
**sidebar** (`gui_qt/sidebar_qt.py::build_sidebar` — load buttons, run, playback
controls) and a `QTabWidget` main area. Reusable Qt building blocks live in
`gui_qt/widgets/` (`FlowCard`, `SectionCard`, `StatusBarWidget`,
`StyledTableWidget`, etc.) and layout constants in `gui_qt/ui_constants_qt.py`.

| Tab | File | Purpose |
|-----|------|---------|
| Vista Real | `gui_qt/vista_realtime.py` (`RealTimeView`) | Live playback of snapshots: jaula + CRC sections + machine widgets + queue + cooling section |
| Dashboard | `gui_qt/dashboard_qt.py` (`DashboardPanel`) | Embeds the **shared** Matplotlib `crear_dashboard_principal` (from `gui/dashboard_principal.py`) in a `FigureCanvasQTAgg` |
| Análisis | `gui_qt/analysis_qt.py` (`AnalysisPanel`) | Embeds the **shared** Matplotlib `crear_dashboard_detalle` (from `gui/dashboard_detalle.py`) in a `FigureCanvasQTAgg` |
| Inventario | `gui_qt/inventory_qt.py` (`InventoryPanel`) | Stock table (initial vs final view), per-column filtering, Excel export |
| KPIs | `gui_qt/tab_kpis_qt.py` (`KpisPanel`) | Key performance indicators (disponible/neta utilization, etc.) |
| Generación | `gui_qt/generation_qt.py` (`GenerationPanel`) | Synthetic-change generator config + adaptation + reproducible generation + timeline |
| Configuración | `gui_qt/config_qt.py` (`ConfigPanel`) | Global params, SubStock ranges, machine park CRUD, sim params; saves to `user_config.json` and applies via `taller.configurar()` |
| Consola | `gui_qt/console_qt.py` (`ConsolePanel`) | Simulation log and alerts |

**Two shared Matplotlib renderers survive in `gui/`.** `gui/dashboard_principal.py`
and `gui/dashboard_detalle.py` are **pure Matplotlib** (no Tk) and are reused by
the Qt Dashboard/Análisis panels. They expose `crear_dashboard_principal` /
`crear_dashboard_detalle` (which build an **empty preview** when `not taller.snapshots`,
via `dashboard_principal.rellenar_preview_vacio`), plus the shared
`formatter_tiempo(t0,t1)` x-axis formatter (drops the hour once the span exceeds
7 days; adds the year once it exceeds 365 days) and `_marcar_paradas` (PARADA shading).
`gui/dashboard_detalle.py` imports `formatter_tiempo`/`rellenar_preview_vacio`/`_marcar_paradas`
from `gui/dashboard_principal.py`. **Do not delete these two modules without first
moving them into `gui_qt`** — they are the only remaining `gui/` files.

**The simulation runs in a separate process, not a thread.** `simular()` is
CPU-bound pure Python, so a thread would freeze the Qt event loop (GIL).
`gui_qt/services.py::SimulationService.submit(SimulationRequest)` builds a
`ProcessPoolExecutor(max_workers=1, mp_context=ctx_paralelo(), initializer=init_worker_simulacion, initargs=(cfg, stock_df, estrategia))`
and submits `simular_cambios_worker(cambios_df)` — **the exact same initializer
path as the parallel `cli.batch_simular`** (see the parallel-execution note
above), so it's a drop-in for a future parallel runner. `MainWindow` polls the
`Future` with a `QTimer`; the GUI stays responsive. On completion the returned
taller (pickled back: snapshots/cilindros/maquinas/alertas) **replaces the current
taller**, and its `avisos_carga` + `log_simulacion` are dumped to the console.
The live `callback_log` can't cross the process boundary, so `simular()`
**accumulates** every log line into `taller.log_simulacion` (cleared at the start
of each run); that list travels back via pickle and restores the change/PARADA/BAJA
log in the console (the CLI still streams live via `callback_log=print`).
`ctx_paralelo()` prefers the **fork** context so the child inherits already-imported
modules (and the worker callables live in `cli`, so even spawn never re-imports the GUI).

Dashboards are Matplotlib `Figure` objects embedded via `FigureCanvasQTAgg`
(`gui_qt/dashboard_qt.py`/`analysis_qt.py`); always clear/close the old canvas and
figure before creating a new one to avoid memory leaks.

### Key constants (in `modelos/taller.py`)

```python
_BUFFER_CRC_SIZE = 2      # cylinders required to form a working pair
_MAX_ITERACIONES_SIM = 10_000   # only the DEFAULT for self.max_iteraciones
```

`_MAX_ITERACIONES_SIM` is just the seed for the instance attribute `self.max_iteraciones`; the loop in `simular()` reads `self.max_iteraciones` (configurable). Likewise `self.tiempo_enfriado_h` (default `0.0`) controls the cooling step.

### Adding a new simulation dataset

Copy and adapt `datos/generar_caso_parada.py`. The Excel must have the two **data** sheets (`Stock_Inicial`, `Programa_Cambios`) with the column names shown in that script. Run the script to produce the `.xlsx`, then load it from the GUI. The taller config (global params, machines, ranges) comes from `config/user_config.json`, not the Excel — adjust it from the Configuración tab or `cli.py config`. To seed/migrate config from an old 4-sheet Excel, run `python cli.py config import-excel <excel>`.

### Theme / colors

All UI color constants are in `config/tema.py`. The Qt GUI consumes them through `gui_qt/theme.py::build_qss()` (which builds the application-wide QSS stylesheet, Dark theme) and directly in the Matplotlib renderers (`gui/dashboard_*.py`, `from config.tema import ...`). Do not hardcode color strings in GUI files.

## Key Design Decisions

These are non-obvious invariants that must be preserved when modifying the engine.

### Machine selection: priority filter, then strategy
When a free machine picks a cylinder in `asignar_trabajo_maquinas()`, `seleccionar_siguiente_de_cola(cola, maquina)` selects in two steps: (1) it first filters the queue to cylinders whose `tipo_rectificado_actual` matches the machine's `prioridad_defecto`; (2) it applies the configured strategy over that subset. If **no** cylinder matches the machine's priority, it falls back to the **whole** queue and applies the strategy there. The machine's priority therefore biases *which* job it takes, but the rectification `tipo` performed is still the cylinder's own type (or `prioridad_defecto` only when the cylinder has none). Strategies are `EstrategiaSeleccion` objects (`clave`, `etiqueta`, `seleccionar(cola, maquina)`) in the `ESTRATEGIAS_SELECCION` registry (`modelos/estrategias.py`); `seleccionar` receives the already priority-filtered queue and may inspect the machine (e.g. `_MenorMmDesbasteFifoProduccion` picks min mm when the machine prioritizes desbaste, FIFO otherwise). Add a new strategy by subclassing and registering it — the GUI combo (`gui_qt`) and CLI `--estrategia` choices (`cli.py`) are derived from the registry, so no hardcoded list needs updating. The GUI shows `etiqueta` and maps it back to `clave`; the Vista Real queue-direction hint (`gui_qt/vista_realtime.py`) should get a matching entry.

### Cage assignment by perfil: diameter pre-filter, then strategy (decide vs apply)
A cylinder carries a physical **perfil** (bombatura, `Cilindro.perfil`) that only changes when ground. SubStock diameter bands **may overlap** and contiguous cages may **share a perfil**, so a cylinder can be admissible for several cages. At the moment a machine **starts** grinding (`asignar_trabajo_maquinas` → `iniciar_rectificado`, the physical instant the perfil is cut), `_asignar_jaula_destino(cil, nuevo_diam, tiempo)` decides the destination cage: (1) **hard diameter pre-filter** — only cages whose SubStock contains the **projected** diameter `nuevo_diam = diametro − mm` are candidates (a cylinder is **never** assigned to a cage whose band rejects its diameter, mirroring the machine-priority pre-filter); (2) the configured `EstrategiaAsignacion` (registry `ESTRATEGIAS_ASIGNACION` in `modelos/estrategias.py`, default `_JaulaMasNecesitada` = most-deficient cage, stopped cages first) picks one. The engine **decides** (cage ⇒ perfil); the machine only **applies** — `perfil` is passed as an input to `iniciar_rectificado`, which stamps `cil.perfil`. The chosen cage is tagged on `cil.jaula_destino` (reset to `None` on retirement at CAMBIO, re-decided next grind). `obtener_disponibles_para_jaula` then honors destino + perfil + diameter (`_admisible_en_jaula`). Add a strategy by subclassing `EstrategiaAsignacion` and registering it — GUI combo (`gui_qt/config_qt.py`) and CLI `--estrategia-asignacion` (`cli.py`) derive from the registry. **Golden invariant:** with non-overlapping bands and **no** perfil (default config), the projected diameter falls in exactly one band ⇒ one candidate ⇒ identical to the old geometric pull, so the existing golden scenarios are byte-for-byte unchanged (only the new `perfiles_jaula_mas_necesitada` scenario was added). Persisted in `config/user_config.json`: per-cage `rangos[i]["perfil"]` (optional) and root `estrategia_asignacion`.

### Re-perfilado of non-placeable cylinders
If a cylinder becomes `Disponible` but its `(perfil, diámetro)` is admissible in **no** cage (e.g. its diameter lands in a gap between bands), it is **not** left as dead stock: `_finalizar_y_continuar` (right after `finalizar_rectificado`) checks `_es_colocable(cil)`; if false and `diámetro > diametro_minimo`, it logs an **INFO alert** and **re-queues** the cylinder to `A_RECTIFICAR` with a forced **producción `_MM_REPERFILADO` (0.8) mm** pass and `jaula_destino = None`. The next `iniciar_rectificado` re-runs `_asignar_jaula_destino` with the new projected diameter, so the strategy re-decides. The loop terminates on its own: each pass trims 0.8 mm until the diameter falls in a band, or drops below `diametro_minimo` ⇒ **BAJA** (existing branch in `asignar_trabajo_maquinas`). Under contiguous bands without perfiles this never triggers (reinforcing the golden invariant).

### Cylinder replenishment (reposición) is strategy-driven and opt-in
A third strategy registry — `ESTRATEGIAS_REPOSICION` (`modelos/estrategias.py`, mirror of selección/asignación: `clave`/`etiqueta` + `planificar(taller, tiempo_baja) → List[PedidoReposicion]`) — decides whether and when **brand-new cylinders arrive** to replace BAJAs. The default is **`_SinReposicion` ("ninguna")**, which returns `[]` always — so the engine never injects cylinders and the **golden master is unchanged byte-for-byte** (the new behavior is opt-in via `config/user_config.json::estrategia_reposicion`). The shipped concrete strategy `_LoteMensual` ("lote_4_mensual") delivers a **lote of 4 new cylinders at `diametro_maximo`** per every 4 BAJAs, arriving the **first operative day of the next month** (`turnos.primer_dia_operativo_mes_siguiente` snaps to the line shift regime `grilla_cambios`, else day 1 at 00:00); accumulated lotes are **staggered one per month** (8 BAJAs ⇒ 4 next month + 4 the month after), chained off `_repo_ultima_llegada`.

The strategy is **stateless** (singleton shared across parallel processes); all run-state lives on the taller — `_repo_bajas_pendientes`, `_repo_ultima_llegada`, `_repo_contador_id`, `_repo_pendientes_fuera`, `_cambios_pendientes` — reset at the top of `simular()` (like the machine reset). It is fired from `_planificar_reposicion(tiempo, cola)`, called **only** at the single runtime-BAJA point in `_finalizar_y_continuar` (the rectify-then-BAJA branch); load-time BAJAs (`_cargar_stock`) are pre-existing scrap and do **not** replenish. Each returned `PedidoReposicion(tiempo_llegada, cantidad, diametro)` is scheduled as a `"REPOSICION"` event. The `_handle_reposicion` handler creates the new `Cilindro`s (id `NUEVO-NNN`) in state **`A_RECTIFICAR`** with a producción pass: they route through `iniciar_rectificado`, which gives them a first preparation grind (`_MM_RECTIFICAR_DEFECTO` mm — a `mm 0` is raised to the minimum pass at `asignar_trabajo_maquinas:895`), stamps their perfil and decides their `jaula_destino`, then they become Disponible and feed CRC reposition / jaula reactivation. Picklability is unaffected (the `PedidoReposicion` lives only in the transient queue, not on the instance; the new attrs are plain int/datetime/None). Surfaced in the CLI (`config sim --estrategia-reposicion`) and the GUI Configuración tab (`cb_strategy_reposicion`), both auto-derived from the registry. Guarded by `tests/test_reposicion.py`.

**Deliveries outside the simulation window [A, B] are recorded, not delivered.** A lote arrives the *first operative day of next month*, which usually falls **after** the last scheduled change B (the end of the studied window) — and B itself **shifts later with PARADAs** (deferred CAMBIOs are reprogrammed). Without a guard, processing such a delivery would extend the simulation ~a month into an idle future, badly diluting the **neta** utilization KPI (the operative denominator spans the empty gap). So `simular()` tracks `_cambios_pendientes` (unexecuted CAMBIOs, decremented in `_handle_cambio`); when `_handle_reposicion` runs with `_cambios_pendientes == 0` (no change left in queue **or** deferred ⇒ the delivery is past B), it **does not create cylinders or a snapshot** — it logs an INFO "pedido de reposición pendiente … (fuera del horizonte simulado)" alert and accumulates `_repo_pendientes_fuera`. This uses the heap's time ordering: by the time a next-month REPOSICION pops, every in-window CAMBIO (including PARADA-shifted ones, which sit later in the queue) has already been processed, so a still-pending change ⇒ the delivery is in-window and is delivered normally (it can even reactivate a stopped line). The window end is thus derived from the *actual* (post-shift) last change, not a fixed date. Both outcomes are surfaced as scalar KPIs from `calcular_kpis()` (`modelos/kpis.py`) — `reposicion_entregados` (new cylinders delivered in-window = `_repo_contador_id`) and `reposicion_pendientes` (`_repo_pendientes_fuera`) — so they auto-render as cards in the KPIs tab (`metric_order`) and in the CLI summary (printed only when non-zero); the per-event INFO alert/log line carries the same info in the console.

### Cooling (Enfriando) is opt-in and physical
With `tiempo_enfriado_h == 0.0` (default) the cooling state does **not** exist: the CAMBIO handler sends retired cylinders straight to `A_RECTIFICAR`, exactly as before. With a positive value, each retired cylinder goes to `ENFRIANDO` and a `FIN_ENFRIADO` event is scheduled at `t + tiempo_enfriado_h`. Like `FIN_RECT`/`REPONER_CRC`, `FIN_ENFRIADO` **always executes** — it is never deferred during a PARADA and is **not** shifted by `_reanudar_linea` (cooling is a wall-clock physical process, not a scheduled change). `tipo_rectificado_actual`/`mm_a_rectificar` are stamped at CAMBIO time and survive the cooling step. Cooling cylinders are not in any jaula, the CRC, or a machine; they are tracked purely by state and surfaced via `Snapshot.detalle_enfriando` (the global "EN ENFRIAMIENTO" section in Vista Real). `generar_snapshot()` counts them automatically because it iterates the whole `EstadoCilindro` enum. The stacked-area chart (`TallerCilindros.ESTADOS_NOMBRES`), the detail map (`ey` dict in `dashboard_detalle.py`), and the table filter (`gui_qt/inventory_qt.py`) all **derive** their state lists from `EstadoCilindro` (no hardcoded `"Enfriando"`), so a new state added to the enum surfaces in all three automatically.

### Work shifts (esquema de trabajo) gate machine rectification, not the line
Each `MaquinaRectificadora` carries an optional weekly operative calendar `grilla_operativa` — a **7×24 boolean grid** (`grid[weekday][hour]`, `weekday` from `datetime.weekday()`, 0 = Monday). `None` ⇒ **always operative (24/7)**, which reproduces the historical behavior byte-for-byte (so the golden master is unchanged by default). The user-facing config is 3 daily shifts (T1 06–14, T2 14–22, **T3 22–06 next day**) per day-of-week; `modelos/turnos.py` (pure domain, no GUI/engine state) is the single source of truth for shift hours, presets (`PRESETS`/`PRESET_LABELS`: `24x7`, `off`, `lv3`, **`3escuadras`** = all shifts except Sat-T3 and all of Sunday), compact-string parse/format, `resumen()`, and `expandir(turnos) → grid`. The Qt shift editor (`gui_qt`) offers the presets in a dropdown and the CLI `--turnos-preset` choices both derive from `PRESETS`, so a new preset surfaces everywhere automatically. **T3 belongs to the day it starts**: its hours 22–23 land on day `d` and 00–05 on day `d+1` (week wraparound). The grid is built per `TallerCilindros` instance in `configurar_maquinas()` — no module-level mutable state, so thousands of parallel sims are safe. A second availability layer — the **machine failure rate** — composes on top of this grid (see "Machine failure rate" below).

Only **machine rectification** is gated by the calendar; the rolling line never stops for shifts — `CAMBIO` and `FIN_ENFRIADO` fire as usual. `iniciar_rectificado` computes `tiempo_fin_rectificado` via `calcular_fin_operativo(inicio, minutos)`, which walks the grid hour-by-hour consuming only operative minutes and **bakes non-operative gaps into the finish time** — so a half-done cylinder stays mounted (machine remains `ocupada`) and "resumes where it stopped" with no preemption logic. `asignar_trabajo_maquinas` skips a machine that is not `disponible_para_trabajo(tiempo)` (= in-shift **and** not in failure); if such a free machine has queued work, it schedules **one** `REANUDAR_MAQUINA` event at `proxima_apertura(tiempo)` (deduped via `maq._despertar_programado`) to wake it when it next becomes workable (shift reopen **or** failure end). Snapshot progress uses `minutos_operativos_entre(inicio, tiempo) / minutos_trabajo_actual` (not wall-clock), so the progress bar doesn't advance during a closed shift. With `grilla_operativa is None` (and no failures) all these helpers collapse to the old wall-clock arithmetic.

**Two utilization KPIs** (`modelos/kpis.py`, the single source consumed by the KPIs tab, CLI and dashboard) form an **OEE-style decomposition** where `disponible × neta == overall utilization (ocupada/calendar)`: **disponible** = `tiempo_operativo / tiempo_calendario` (key `utilizacion_maquinas_pct`; the **availability factor** = fraction of the calendar the machine is in-shift, where operative = calendar − closed-shift time = `minutos_operativos_entre(snapshots[0], snapshots[-1])`; **100% under 24/7**) and **neta** = `tiempo_total_ocupada_min / tiempo_operativo` (key `utilizacion_neta_pct`; the **utilization of available time** = ocupada / operative, where ocupada = operative − idle (machine free) − failures). **Failures are modeled** (see "Machine failure rate"): they pause grinding, so a machine accomplishes less per operative minute and the neta drops on its own; the failure share is also exposed explicitly as `tiempo_falla_pct` per machine (`minutos_falla_entre / operative`, a dict — so it stays out of the scalar `metric_order` and out of the golden fingerprint). The **disponible** factor stays shift-only (failures do **not** reduce it). **Regenerating the golden:** changing `utilizacion_maquinas_pct` from `ocupada/calendar` to `operativo/calendar` changes its value even for the 24/7 golden scenarios (it becomes 100% for every machine), so the golden master was regenerated on purpose. The Dashboard utilization panel draws **two grouped bars per machine** (disponible in `ACCENT`, neta in `PURPLE`) sourced from `calcular_kpis()` (the single source — not recomputed inline), and the Gantt shades each machine's closed-shift spans in `RED_DARK` (`_tramos_parada_maquina`). The **KPIs tab** (`gui_qt/tab_kpis_qt.py`) renders two separate sections — "UTILIZACIÓN DISPONIBLE" and "UTILIZACIÓN NETA" — listing machines in the **same order** (`list(k["utilizacion_maquinas_pct"])`); each machine card's border, fill tint and percentage text are colored by `_color_util(pct)`, a red→yellow→green gradient (0% red, 50% yellow, 100% green) interpolated from the `RED`/`YELLOW`/`GREEN` tema constants.

**Vista Real surfaces the per-machine shift state.** `generar_snapshot()` records `Snapshot.detalle_maquinas_operativa[nombre] = maq.esta_operativa(tiempo)` (a plain `{nombre: bool}`, distinct from `detalle_maquinas` which is `None` for any free machine and so can't tell "free in shift" from "off shift"). `gui_qt/vista_realtime.py` renders each machine widget in one of **three** states by reading both dicts: **rectificando** (busy → purple border + cylinder), **libre y operativa** (free + operative → GREEN border + "● Libre (operativa)", the highlight requested for an idle machine that *could* take work), and **fuera de turno** (free + not operative → `RED_DARK` border + "⏸ Fuera de turno"). Under 24/7 (`grilla_operativa is None`) `esta_operativa` is always `True`, so a free machine always shows the green "operativa" highlight. **Adding `detalle_maquinas_operativa` to `Snapshot` changes `snapshots_sha256`** (it serializes every `Snapshot.__dict__` field) but not KPIs/n_snapshots/alerts/cylinders — this is an intended snapshot-data change, so the golden was regenerated on purpose. `generar_snapshot()` also records `Snapshot.detalle_maquinas_falla[nombre] = maq.en_falla(tiempo)` (per-instant failure state); adding it likewise moved `snapshots_sha256` only (golden regenerated on purpose). **Vista Real renders a 4th machine state from it**: when in-shift **and** in failure, the widget uses `mode="falla"` (border/label in `DASH_FALLA` = `#FF6B6B`, a red **less dark** than the shift `RED_DARK`) showing "En falla" (or "Rectificando · falla" if a cylinder is mounted/paused); precedence is `falla (in-shift) → busy → idle → off`. The **Gantt** marks failure spans in the same `DASH_FALLA`: `gui_qt/dashboard_data.py::tramos_falla_maquina` (sibling of `tramos_parada_maquina`, condition `esta_operativa(t) and en_falla(t)`, so spans are **disjoint** from the dark-red `DASH_PARADA` shift spans), threaded via `DashboardData.tramos_falla` into `GanttChart.set_data(..., fallas=)` and the Gantt legend ("Falla"). The **Configuración** tab edits per-machine failure as a "Falla %" column (reuses the existing text-cell editor; persisted as `tasa_falla` fraction only when > 0). The GUI uses the **generation seed** as the failures seed: `GenerationPanel` resolves the seed once (`resolver_seed`) and passes it via `on_cambios_generated(df, seed)` → `MainWindow.fallas_seed` → `SimulationRequest.seed` → `init_worker_simulacion`; loading a `Programa_Cambios` from Excel leaves `fallas_seed=None` (no failures).

### Machine failure rate (tasa de falla) is a second availability layer over shifts
Each `MaquinaRectificadora` has a `tasa_falla` (fraction `[0,1]` of **operative** time lost to failures, default `0.0` ⇒ no failures, byte-for-byte historical) plus a run-level `_seed_fallas` set by `simular(seed=...)`. `en_falla(dt)` is a **deterministic, stateless** per-hour Bernoulli draw — `sha256(seed, nombre, absolute-hour) → [0,1) < tasa_falla` — so ~`tasa_falla` of operative hours are down, reproducibly (same seed ⇒ same pattern), independent of call order and of PARADA shifts (failures are an exogenous wall-clock process, like cooling/shifts), with nothing to precompute and trivially picklable (stores only `tasa_falla`+`_seed_fallas`+`nombre`). **Failures compose with shifts via `disponible_para_trabajo(dt) = esta_operativa(dt) and not en_falla(dt)`**, which replaces the raw grid check in the pause/resume machinery (`_construir_hitos_progreso`, `calcular_fin_operativo`, `progreso_operativo`, `proxima_apertura`) — so a failure mid-grind bakes into `tiempo_fin_rectificado` exactly like a closed shift (cylinder stays mounted, resumes; no preemption event). The 24/7 fast-paths now key off `grilla_operativa is None and not _tiene_fallas()`, and `minutos_operativos_entre` (the **disponible** KPI) is **left untouched** (shift-only) — failures show only in **neta** and in the explicit `tiempo_falla_pct` (`minutos_falla_entre` = operative hours that are failed). **The same seed that generated the `Programa_Cambios` drives the failures**: thread it via `simular(seed=)` / `ejecutar_simulacion(seed=)` / CLI `simular --seed-fallas`, and for Monte Carlo via `batch_simular(..., seeds=[...])` (per-run seed, paired with each `cambios_df`; the worker task may be a bare `cambios_df` or a `(cambios_df, seed)` tuple). `tasa_falla` is persisted per machine **only when > 0** (mirror of `turnos`); CLI `config maquina add/set --tasa-falla`, getter `obtener_tasa_falla`. With `tasa_falla == 0` or no seed, `en_falla` is always `False` and every path collapses to the shift-only behavior (golden KPIs/trajectory identical; only the new `detalle_maquinas_falla` snapshot field moved the hash).

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

### PARADA reprogramming respects the line shift regime (working-time delay)
When the line resumes, `_reanudar_linea` advances every pending CAMBIO by the stoppage duration. If a **line shift regime** is configured (`turnos_cambios` in the config → expanded into `TallerCilindros.grilla_cambios` by `configurar()`, `None` ⇒ 24/7), the delay is measured in **line working time**, not wall-clock: each CAMBIO is advanced over the working calendar via `turnos.avanzar_operativo(grilla_cambios, t, dur_work)` where `dur_work = turnos.minutos_operativos(grilla_cambios, inicio, tiempo)`. Consequences: (a) a stoppage that spans non-working hours of the line barely delays the program (those hours weren't productive anyway), and (b) no reprogrammed CAMBIO lands outside a line shift (`avanzar_operativo` is *snap-then-advance*: an off-grid time first jumps to the next operative hour). This makes `turnos_cambios` affect the **simulation** (PARADA reprogramming), not only the synthetic-change **generator** — same field, now consumed in both places, mirroring how the machine `turnos` gate grinding. With `grilla_cambios is None` (default, and every golden/Excel scenario, which don't set `turnos_cambios`) the delay is wall-clock and the displacement **and** the "LÍNEA REANUDADA … programa desplazado …" alert text are **byte-for-byte identical** to before (golden unchanged). The pure helpers `minutos_operativos`/`avanzar_operativo` live in `modelos/turnos.py` (no engine/GUI state) and reuse `proximo_inicio_operativo`. `FIN_RECT`/`REPONER_CRC`/`FIN_ENFRIADO`/`REANUDAR_MAQUINA` are **not** reprogrammed (wall-clock, exogenous).

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
