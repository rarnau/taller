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

There are no automated tests or linters configured. Validation is done by running the application and loading an Excel file.

## Architecture Overview

**Simulador de Cilindros Pro v4** — a discrete-event simulation (DES) tool for a rolling mill (taller de laminación). Operators load an Excel file describing cylinder inventory and a change schedule; the engine simulates cylinder lifecycle transitions and the GUI replays them.

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

1. **Load** — `cargar_datos(ruta_excel)` reads four mandatory sheets:
   - `Configuración` — global params (diameter range, jaula count, CRC transport time)
   - `Máquinas` — rectification rates per machine and type
   - `Stock_Inicial` — cylinder inventory with initial states
   - `Programa_Cambios` — scheduled change events

2. **Simulate** — `simular(callback)` runs a priority-queue DES loop. Internal event type `_EventoSim(tipo, tiempo, datos)` has three types:
   - `"CAMBIO"` — a scheduled jaula change (datos = `EventoCambio`)
   - `"FIN_RECT"` — a machine finishes rectification (datos = machine name str)
   - `"REPONER_CRC"` — a Disponible cylinder arrives at the CRC buffer (datos = jaula int)

3. **PARADA (line stoppage)** — if after a `CAMBIO` there is no stock to form a complete pair (`_BUFFER_CRC_SIZE = 2`) for a jaula:
   - `_parar_jaula()` marks the jaula `parada=True` and records `_linea_parada_desde`
   - All subsequent `CAMBIO` events with `tiempo > _linea_parada_desde` are moved to `_cambios_diferidos` (not executed)
   - `FIN_RECT` and `REPONER_CRC` always execute — machines keep running and CRC can be replenished
   - When `_intentar_reactivar_jaulas()` succeeds (called from `FIN_RECT` handler), `_reanudar_linea()` shifts all deferred and remaining-in-queue CAMBIO events by the stoppage duration

4. **Snapshot** — `generar_snapshot(tiempo)` is called after every event and records full taller state into `self.snapshots`. The GUI uses snapshots for playback; `Snapshot.jaulas_paradas` is a list of jaula IDs currently stopped.

### Cylinder lifecycle (states in `modelos/enums.py`)

```
Trabajando ──cambio──> A rectificar ──maquina libre──> Rectificando ──fin──> Disponible
                                                                                │
CRC <──reponer_crc──────────────────────────────────────────────────────────────┘
 │
 └──instalado──> Trabajando

Cualquier estado ──diametro < minimo──> Baja
```

SubStock ranges: `hasta < diámetro <= desde` (hasta is the lower exclusive bound, desde is the upper inclusive bound). Each jaula has an associated SubStock; a cylinder can only replenish a jaula's CRC if its diameter falls in that SubStock's range.

### Configuration persistence

`config/persistencia.py` loads/saves `config/user_config.json` with:
- `rangos` — SubStock diameter ranges per jaula (overrides defaults)
- `prioridades_maquinas` — preferred rectification type per machine

At startup, `App.__init__` calls `taller.configurar_substocks()` with these ranges. The `Configuración` tab in the GUI (`gui/tab_config.py`) allows editing and saving these at runtime.

### GUI structure — `gui/app.py`

Single `App(CTk)` window with a sidebar and a tabbed main area:

| Tab | File | Purpose |
|-----|------|---------|
| Vista Real | `gui/vista_realtime.py` | Live playback of snapshots; jaula + CRC sections + machine widgets + queue |
| Dashboard | `gui/dashboard_principal.py` | Matplotlib stacked-area charts, buffer, machine utilization, Gantt |
| Detalle | `gui/dashboard_detalle.py` | Per-cylinder detail chart (click a cylinder in Vista Real) |
| Inventario | `gui/tab_tabla.py` | Full cylinder table |
| KPIs | `gui/tab_kpis.py` | Key performance indicators |
| Configuración | `gui/tab_config.py` | Editable SubStock ranges and machine priorities |
| Consola | `gui/tab_consola.py` | Simulation log and alerts |

Playback is driven by a background thread in `App`; at each tick it calls `vista_rt.actualizar(snapshot)` on the Tk main thread via `self.after()`.

Dashboards are rendered with Matplotlib `Figure` objects embedded via `FigureCanvasTkAgg`. The `App._figs` dict caches open figures; always close the old figure before creating a new one to avoid memory leaks.

### Key constants (in `modelos/taller.py`)

```python
_BUFFER_CRC_SIZE = 2      # cylinders required to form a working pair
_MAX_ITERACIONES_SIM = 10_000
```

### Adding a new simulation dataset

Copy and adapt `datos/generar_caso_parada.py`. The Excel must have exactly four sheets with the column names shown in that script. Run the script to produce the `.xlsx`, then load it from the GUI.

### Theme / colors

All UI color constants are in `config/tema.py` and imported with `from config.tema import *`. The app uses CustomTkinter Dark mode. Do not hardcode color strings in GUI files.
