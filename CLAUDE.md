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

At startup, `App.__init__` calls `taller.configurar(self.user_cfg)` (one call that builds machines, globals, ranges and sim params); it is re-applied before each file load and simulation. The `Configuración` tab (`gui/tab_config.py`) edits all of these at runtime and writes them back. The CLI manages them via `cli.py config ...` subcommands; `--tiempo-enfriado`/`--max-iteraciones` on `cli.py simular` still override the JSON for a single run.

**CLI subcommands** (`cli.py`):
- `simular <excel> [--estrategia --config --export --json --json-out --quiet --tiempo-enfriado --max-iteraciones]`
- `config show | export <json> | import <json> | import-excel <excel>`
- `config global [--diametro-max --diametro-min --crc-min --jaulas]`
- `config maquina list|add|remove|set` (set/add accept `--turnos "<compacto>"` or `--turnos-preset {24x7,off,lv3}`) and `config jaula list|set|remove`
- `config sim [--tiempo-enfriado --max-iteraciones]`

`construir_taller(cfg, excel)` and `ejecutar_simulacion(...)` in `cli.py` are GUI-free entry points; `construir_taller` (configurar + cargar_datos) is the intended base for a future batch runner of many independent parallel simulations.

### GUI structure — `gui/app.py`

Single `App(CTk)` window with a sidebar and a tabbed main area:

| Tab | File | Purpose |
|-----|------|---------|
| Vista Real | `gui/vista_realtime.py` | Live playback of snapshots; jaula + CRC sections + machine widgets + queue |
| Dashboard | `gui/dashboard_principal.py` | Matplotlib stacked-area charts, buffer, machine utilization, Gantt |
| Detalle | `gui/dashboard_detalle.py` | Per-cylinder detail chart (click a cylinder in Vista Real) |
| Inventario | `gui/tab_tabla.py` | Full cylinder table |
| KPIs | `gui/tab_kpis.py` | Key performance indicators |
| Configuración | `gui/tab_config.py` | Responsive two-column layout: global params + SubStock ranges (left); machine park CRUD + simulation params (cooling time, max iterations) (right). Below `_UMBRAL_APILADO` px wide the columns stack to full width (`_on_resize`/`_aplicar_layout`) so the machine table's "Prioridad" column isn't clipped on narrow screens. Saves to `user_config.json` and applies via `taller.configurar()` |
| Consola | `gui/tab_consola.py` | Simulation log and alerts |

Playback is driven by a background thread in `App`; at each tick it calls `vista_rt.actualizar(snapshot)` on the Tk main thread via `self.after()`.

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

`gui/app.py` calls `ctk.deactivate_automatic_dpi_awareness()` at module load, **before** the window is created. This is required: when the window is dragged between monitors with different DPI scaling, CustomTkinter's auto-rescaler tries to reconfigure the already-destroyed dropdown of a `CTkComboBox` and raises `TclError: invalid command name ...dropdownmenu`. Deactivating it pins the scale to 1 and removes that callback. **Tradeoff:** widgets are not auto-rescaled to per-monitor DPI. Do not re-enable without first solving the combobox-dropdown crash.

In `gui/vista_realtime.py`, the machine widgets ("rectificadoras") use a `grid` of uniform weighted columns (`grid_columnconfigure(..., weight=1, uniform="maq")`, `sticky="ew"`) so they share the available width responsively — do **not** give them a fixed width. The "Cargue un Excel y ejecute la simulación..." guidance hint (`self.hint_inicio` in `gui/app.py`) lives in the **sidebar** under the action buttons (not as an overlay on Vista Real), and is hidden with `grid_remove()` in `_sincronizar_vista_con_taller()` once data is loaded. The "EN ENFRIAMIENTO" section lives in the **right** column (under the queue) to keep all jaulas visible in the left column.

## Key Design Decisions

These are non-obvious invariants that must be preserved when modifying the engine.

### Machine selection: priority filter, then strategy
When a free machine picks a cylinder in `asignar_trabajo_maquinas()`, `seleccionar_siguiente_de_cola(cola, maquina)` selects in two steps: (1) it first filters the queue to cylinders whose `tipo_rectificado_actual` matches the machine's `prioridad_defecto`; (2) it applies the configured strategy over that subset. If **no** cylinder matches the machine's priority, it falls back to the **whole** queue and applies the strategy there. The machine's priority therefore biases *which* job it takes, but the rectification `tipo` performed is still the cylinder's own type (or `prioridad_defecto` only when the cylinder has none). Strategies are `EstrategiaSeleccion` objects (`clave`, `etiqueta`, `seleccionar(cola, maquina)`) in the `ESTRATEGIAS_SELECCION` registry (`modelos/estrategias.py`); `seleccionar` receives the already priority-filtered queue and may inspect the machine (e.g. `_MenorMmDesbasteFifoProduccion` picks min mm when the machine prioritizes desbaste, FIFO otherwise). Add a new strategy by subclassing and registering it — the GUI combo (`gui/app.py`) and CLI `--estrategia` choices (`cli.py`) are derived from the registry, so no hardcoded list needs updating. The GUI shows `etiqueta` and maps it back to `clave`; `_SENTIDO_TOMA` in `gui/vista_realtime.py` should get a matching entry for the queue-direction hint.

### Cooling (Enfriando) is opt-in and physical
With `tiempo_enfriado_h == 0.0` (default) the cooling state does **not** exist: the CAMBIO handler sends retired cylinders straight to `A_RECTIFICAR`, exactly as before. With a positive value, each retired cylinder goes to `ENFRIANDO` and a `FIN_ENFRIADO` event is scheduled at `t + tiempo_enfriado_h`. Like `FIN_RECT`/`REPONER_CRC`, `FIN_ENFRIADO` **always executes** — it is never deferred during a PARADA and is **not** shifted by `_reanudar_linea` (cooling is a wall-clock physical process, not a scheduled change). `tipo_rectificado_actual`/`mm_a_rectificar` are stamped at CAMBIO time and survive the cooling step. Cooling cylinders are not in any jaula, the CRC, or a machine; they are tracked purely by state and surfaced via `Snapshot.detalle_enfriando` (the global "EN ENFRIAMIENTO" section in Vista Real). `generar_snapshot()` counts them automatically because it iterates the whole `EstadoCilindro` enum. The stacked-area chart (`TallerCilindros.ESTADOS_NOMBRES`), the detail map (`ey` dict in `dashboard_detalle.py`), and the table filter (`tab_tabla.py`) all **derive** their state lists from `EstadoCilindro` (no hardcoded `"Enfriando"`), so a new state added to the enum surfaces in all three automatically.

### Work shifts (esquema de trabajo) gate machine rectification, not the line
Each `MaquinaRectificadora` carries an optional weekly operative calendar `grilla_operativa` — a **7×24 boolean grid** (`grid[weekday][hour]`, `weekday` from `datetime.weekday()`, 0 = Monday). `None` ⇒ **always operative (24/7)**, which reproduces the historical behavior byte-for-byte (so the golden master is unchanged by default). The user-facing config is 3 daily shifts (T1 06–14, T2 14–22, **T3 22–06 next day**) per day-of-week; `modelos/turnos.py` (pure domain, no GUI/engine state) is the single source of truth for shift hours, presets, compact-string parse/format, `resumen()`, and `expandir(turnos) → grid`. **T3 belongs to the day it starts**: its hours 22–23 land on day `d` and 00–05 on day `d+1` (week wraparound). The grid is built per `TallerCilindros` instance in `configurar_maquinas()` — no module-level mutable state, so thousands of parallel sims are safe. The grid is also the hook for a future random machine-failure feature (turn off a random % of hours).

Only **machine rectification** is gated by the calendar; the rolling line never stops for shifts — `CAMBIO` and `FIN_ENFRIADO` fire as usual. `iniciar_rectificado` computes `tiempo_fin_rectificado` via `calcular_fin_operativo(inicio, minutos)`, which walks the grid hour-by-hour consuming only operative minutes and **bakes non-operative gaps into the finish time** — so a half-done cylinder stays mounted (machine remains `ocupada`) and "resumes where it stopped" with no preemption logic. `asignar_trabajo_maquinas` skips a machine that is not `esta_operativa(tiempo)`; if such a free machine has queued work, it schedules **one** `REANUDAR_MAQUINA` event at `proxima_apertura(tiempo)` (deduped via `maq._despertar_programado`) to wake it when its shift reopens. Snapshot progress uses `minutos_operativos_entre(inicio, tiempo) / minutos_trabajo_actual` (not wall-clock), so the progress bar doesn't advance during a closed shift. With `grilla_operativa is None` all these helpers collapse to the old wall-clock arithmetic.

**Two utilization KPIs** (`modelos/kpis.py`, the single source consumed by the KPIs tab, CLI and dashboard): **disponible** = `tiempo_total_ocupada_min / tiempo_operativo` (key `utilizacion_maquinas_pct`; "of the hours the machine was in-shift/available, how much it ground", where operative time = `minutos_operativos_entre(snapshots[0], snapshots[-1])`) and **neta** = `tiempo_total_ocupada_min / tiempo_calendario` (key `utilizacion_neta_pct`; over the whole calendar). Since operative ≤ calendar, **`neta ≤ disponible`** (disponible is its ceiling) and they are **equal under 24/7** (operative == calendar). The golden fingerprint reads only `utilizacion_maquinas_pct`, and its value is **unchanged** because every golden scenario is 24/7 (operative == calendar, so `ocupada/operativo == ocupada/calendario`). The Dashboard utilization panel draws **two grouped bars per machine** (disponible in `ACCENT`, neta in `PURPLE`) sourced from `calcular_kpis()` (the single source — not recomputed inline), and the Gantt shades each machine's closed-shift spans in `RED_DARK` (`_tramos_parada_maquina`). The **KPIs tab** (`gui/tab_kpis.py`) renders two separate sections — "UTILIZACIÓN DISPONIBLE" and "UTILIZACIÓN NETA" — listing machines in the **same order** (`list(k["utilizacion_maquinas_pct"])`); each machine card's border, fill tint and percentage text are colored by `_color_util(pct)`, a red→yellow→green gradient (0% red, 50% yellow, 100% green) interpolated from the `RED`/`YELLOW`/`GREEN` tema constants.

**Vista Real surfaces the per-machine shift state.** `generar_snapshot()` records `Snapshot.detalle_maquinas_operativa[nombre] = maq.esta_operativa(tiempo)` (a plain `{nombre: bool}`, distinct from `detalle_maquinas` which is `None` for any free machine and so can't tell "free in shift" from "off shift"). `gui/vista_realtime.py` renders each machine widget in one of **three** states by reading both dicts: **rectificando** (busy → purple border + cylinder), **libre y operativa** (free + operative → GREEN border + "● Libre (operativa)", the highlight requested for an idle machine that *could* take work), and **fuera de turno** (free + not operative → `RED_DARK` border + "⏸ Fuera de turno"). Under 24/7 (`grilla_operativa is None`) `esta_operativa` is always `True`, so a free machine always shows the green "operativa" highlight. **Adding `detalle_maquinas_operativa` to `Snapshot` changes `snapshots_sha256`** (it serializes every `Snapshot.__dict__` field) but not KPIs/n_snapshots/alerts/cylinders — this is an intended snapshot-data change, so the golden was regenerated on purpose.

### PARADA is all-or-nothing
`_instalar_pareja_o_parar()` never installs a partial pair. If there are fewer than `_BUFFER_CRC_SIZE` cylinders available in a jaula's range, it installs **none** and returns `False`. A jaula with only one cylinder working is not a valid state.

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

### Single CRC transport resource
Only one pair of cylinders can be in transit to CRC at a time, serialized via `_recurso_crc_libre_en` and `_reposicion_pendiente`. Do not add parallel CRC transport logic.

### Snapshot granularity
A snapshot is generated after **every** event (CAMBIO, FIN_RECT, REPONER_CRC, FIN_ENFRIADO). Do not skip snapshots for performance — the GUI seekbar depends on having a snapshot at each simulation step. The cost of each snapshot was instead cut by making `generar_snapshot()` a single pass over `self.cilindros` (see step 4 of the simulation flow); that is where snapshot performance work belongs.
