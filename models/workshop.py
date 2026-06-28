"""
Simulation engine of the cylinder workshop.
Coordinates cylinders, machines, stands and change events.
"""
import heapq
import itertools
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any, NamedTuple, Tuple
from .enums import CylinderState, GrindingType
from .cylinder import Cylinder
from .substock import SubStock
from .machine import GrindingMachine
from .stand import Stand
from .events import ChangeEvent, Alert, Snapshot
from .strategies import (
    SELECTION_STRATEGIES, DEFAULT_STRATEGY,
    ASSIGNMENT_STRATEGIES, DEFAULT_ASSIGNMENT_STRATEGY,
)
from . import shifts as shifts_mod

logger = logging.getLogger(__name__)

# ── Simulation constants ────────────────────────────────────────────────────
_DEFAULT_GRIND_MM: float = 0.8
_DEFAULT_GRIND_TYPE: str = "produccion"
# mm shaved off (production grind) when a cylinder becomes Available but its
# (profile, diameter) is not placeable in any stand: it is re-queued to grinding
# to re-profile it until it falls into a band.
_REPROFILE_MM: float = 0.8
_BUFFER_CRC_SIZE: int = 2
_MAX_SIM_ITERATIONS: int = 10_000
_MAX_FINALIZE_ITERATIONS: int = 500

# Excel sheet names (frozen data contract)
_SHEET_CONFIG = "Configuración"
_SHEET_MACHINES = "Máquinas"
_SHEET_STOCK = "Stock_Inicial"
_SHEET_CHANGES = "Programa_Cambios"


def _normalize_profile(value: Any) -> Optional[str]:
    """Normalize a profile value to a canonical str (or None if empty).

    Prevents a numeric profile read from Excel/JSON as ``4.0`` from failing to
    match a configured ``"4"``: an integer float is formatted with no decimals.
    """
    if value is None or value == "":
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value)


def _fmt_duration(minutes: float) -> str:
    """Format a duration (in minutes) in a readable way for the logs.

    - up to 60 min → ``"N min"``
    - up to 24 h   → ``"N h M min"`` (omits the minutes if 0)
    - over 24 h    → ``"N d M h"`` (days and hours)
    """
    m = int(round(minutes))
    if m <= 60:
        return f"{m} min"
    if m <= 1440:
        h, mm = divmod(m, 60)
        return f"{h} h {mm} min" if mm else f"{h} h"
    d, rest = divmod(m, 1440)
    h = rest // 60
    return f"{d} d {h} h" if h else f"{d} d"


class _SimEvent(NamedTuple):
    """Typed internal event for the simulation queue."""
    type: str       # "CHANGE" | "GRIND_END" | "REPLENISH_CRC" | "COOLING_END" | "RESUME_MACHINE"
    time: datetime
    data: Any       # ChangeEvent (CHANGE) | machine str (GRIND_END) | stand int (REPLENISH_CRC) | cylinder id str (COOLING_END)


# Priority-queue (heap) item: (time, sequence, event). The sequence counter
# breaks time ties in FIFO insertion order and avoids comparing the _SimEvents.
_QueueItem = Tuple[datetime, int, _SimEvent]


class CylinderWorkshop:
    """
    Main class managing the simulation logic.

    Responsibilities:
      - Loading data from Excel (load_data)
      - State queries (get_*, select_*)
      - Snapshot generation for the GUI
      - Running the simulation (simulate)
      - Exporting results
    """

    # Derived from the enum (in its definition order) to avoid duplicating the
    # state list: adding a state to CylinderState makes the charts pick it up.
    STATE_NAMES = [e.value for e in CylinderState]

    def __init__(self):
        self.cylinders: Dict[str, Cylinder] = {}
        self.substocks: List[SubStock] = []
        self.machines: Dict[str, GrindingMachine] = {}
        self.stands: Dict[int, Stand] = {}
        self.scheduled_events: List[ChangeEvent] = []
        self.alerts: List[Alert] = []
        self.snapshots: List[Snapshot] = []
        self.load_warnings: List[str] = []  # warnings raised while loading data (for the GUI)
        # Log of the last simulation (accumulated in simulate()): lets it be shown
        # in the GUI console even though the run happens in a separate process (the
        # live callback_log does not cross the process boundary; this list does,
        # via pickle of the resulting workshop).
        self.simulation_log: List[str] = []
        # IDs already warned about "no machine can grind its type" (alert once).
        self._no_machine_alerted: set = set()

        # Configuration parameters (overwritten when loading Excel)
        self.max_diameter: float = 575.0
        self.min_diameter: float = 520.0
        self.crc_transfer_time_min: float = 10.0
        self.stand_count: int = 4
        self.selection_strategy: str = "mayor_diametro"
        self.assignment_strategy: str = DEFAULT_ASSIGNMENT_STRATEGY

        # Cooling time (hours) between Working and To-grind. 0.0 = no cooling
        # state (historical behavior). Maximum iterations of the simulation loop
        # (configurable safety cap).
        self.cooling_time_h: float = 0.0
        self.max_iterations: int = _MAX_SIM_ITERATIONS

        # Single Available→CRC transport resource (crane/operator). Replenishments
        # are serialized: only one pair is moved at a time.
        self._crc_resource_free_at: Optional[datetime] = None
        self._pending_replenishment: set = set()

        # Line stoppage: when any stand stops, the whole line halts. While it
        # lasts, later CHANGEs are deferred; on resume, all the remaining change
        # schedule is shifted by the total duration.
        self._line_stopped_since: Optional[datetime] = None
        self._deferred_changes: List["_SimEvent"] = []

        # Event-queue (heap) sequence counter. Reset at the start of each
        # simulation; declared here so _push_event does not depend on an
        # attribute that only exists mid-run.
        self._queue_seq = itertools.count()

    # ── Pickling (passing to processes: GUI worker and batch_simular) ────────

    def __getstate__(self):
        # itertools.count() is not picklable. It is just a transient event-queue
        # counter (valid only mid-simulate()), so it is excluded from the pickle
        # and recreated on unpickle. The rest of the state (snapshots, cylinders,
        # machines, alerts) is picklable.
        state = self.__dict__.copy()
        state.pop("_queue_seq", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._queue_seq = itertools.count()

    # ── External configuration ──────────────────────────────────────────────

    def configure_substocks(self, ranges_config: List[Dict[str, Any]]) -> None:
        """Define the diameter ranges for each stand."""
        self.substocks.clear()
        for r in ranges_config:
            stand = int(r["jaula"])
            upper = float(r["desde"])
            lower = float(r["hasta"])
            profile = _normalize_profile(r.get("perfil"))
            name = f"SS{stand} ({lower:.0f}-{upper:.0f})"
            self.substocks.append(
                SubStock(name, stand, upper, lower, assigned_stand=stand, profile=profile))

    def apply_machine_priorities(self, priorities: Dict[str, str]) -> None:
        """Assign the priority grinding type to each machine."""
        for name, pass_type in priorities.items():
            if name in self.machines:
                try:
                    self.machines[name].default_priority = GrindingType(pass_type)
                except ValueError:
                    logger.warning("Tipo de prioridad inválido '%s' para máquina '%s', ignorado.", pass_type, name)

    def configure(self, cfg: Dict[str, Any]) -> None:
        """Apply the persistent structural configuration (the user JSON).

        Single configuration entry point of the workshop. It MUST be called
        **before** ``load_data()``: the stock needs ``cantidad_jaulas`` and
        ``diametro_minimo`` to initialize, and the change schedule validates
        against the already-created stands.

        Accepts the full dict from ``config/persistencia.py`` (keys
        ``config_global``, ``maquinas``, ``rangos``, ``tiempo_enfriado_h`` and
        ``max_iteraciones``); missing ones are ignored without error.
        """
        cg = cfg.get("config_global", {})
        if "diametro_maximo" in cg:
            self.max_diameter = float(cg["diametro_maximo"])
        if "diametro_minimo" in cg:
            self.min_diameter = float(cg["diametro_minimo"])
        if "tiempo_traslado_crc_min" in cg:
            self.crc_transfer_time_min = float(cg["tiempo_traslado_crc_min"])
        if "cantidad_jaulas" in cg:
            self.stand_count = int(cg["cantidad_jaulas"])

        if "maquinas" in cfg:
            self.configure_machines(cfg["maquinas"])
        if "rangos" in cfg:
            self.configure_substocks(cfg["rangos"])
        if "tiempo_enfriado_h" in cfg:
            self.cooling_time_h = float(cfg["tiempo_enfriado_h"])
        if "max_iteraciones" in cfg:
            self.max_iterations = int(cfg["max_iteraciones"])
        if "estrategia_seleccion" in cfg:
            self.selection_strategy = str(cfg["estrategia_seleccion"])
        if "estrategia_asignacion" in cfg:
            self.assignment_strategy = str(cfg["estrategia_asignacion"])

    def configure_machines(self, machines_config: List[Dict[str, Any]]) -> None:
        """Rebuild the machine park from the persistent configuration.

        Each entry: ``{"nombre", "prioridad", "tasas": {type: {"mm", "tiempo_min"}}}``.
        """
        self.machines.clear()
        for m in machines_config:
            name = str(m["nombre"])
            maq = GrindingMachine(name)
            for type_str, rate in (m.get("tasas") or {}).items():
                try:
                    GrindingType(type_str)
                except ValueError:
                    logger.warning("Tipo de rectificado inválido '%s' para máquina '%s', ignorado.", type_str, name)
                    continue
                maq.configure_rate(type_str, float(rate["mm"]), float(rate["tiempo_min"]))
            priority = m.get("prioridad")
            if priority:
                try:
                    maq.default_priority = GrindingType(priority)
                except ValueError:
                    logger.warning("Prioridad inválida '%s' para máquina '%s', ignorada.", priority, name)
            # Work schedule (shifts): if configured, expand it to the 7×24 hourly
            # grid; otherwise it stays None (always operative, 24/7).
            schedule = m.get("turnos")
            maq.operating_grid = shifts_mod.expand(schedule) if schedule else None
            self.machines[name] = maq

    # ── Loading data from Excel ─────────────────────────────────────────────

    def load_data(self, excel_path: str) -> None:
        """Load the initial inventory and the change schedule from an Excel.

        The Excel only holds **variable data**: the ``Stock_Inicial`` and
        ``Programa_Cambios`` sheets. The structural configuration (global params,
        machines and ranges) lives in the user JSON and must be applied first via
        :meth:`configure`. If the file carries the old ``Configuración``/
        ``Máquinas`` sheets they are ignored (with a warning).
        """
        try:
            xl = pd.ExcelFile(excel_path, engine="openpyxl")
        except Exception as exc:
            raise IOError(f"No se pudo abrir el archivo Excel '{excel_path}': {exc}") from exc

        required_sheets = [_SHEET_STOCK, _SHEET_CHANGES]
        missing = [h for h in required_sheets if h not in xl.sheet_names]
        if missing:
            raise ValueError(f"Hojas faltantes en el Excel: {missing}")

        ignored = [h for h in (_SHEET_CONFIG, _SHEET_MACHINES) if h in xl.sheet_names]

        self.load_data_from_dataframes(xl.parse(_SHEET_STOCK), xl.parse(_SHEET_CHANGES))

        if ignored:
            msg = (
                f"AVISO: el Excel trae hojas de configuración antiguas {ignored} que se "
                f"ignoran. La configuración del taller se gestiona desde la pantalla "
                f"Configuración o el CLI (config import-excel para volcarlas al JSON)."
            )
            logger.warning(msg)
            self.load_warnings.append(msg)

    def load_data_from_dataframes(self, stock_df: pd.DataFrame,
                                  changes_df: pd.DataFrame) -> None:
        """Load stock and changes from in-memory DataFrames.

        Splitting this logic from reading the ``.xlsx`` lets a future batch
        runner execute thousands of independent simulations passing the
        DataFrames directly, with no per-run disk I/O. Requires that
        :meth:`configure` has already been applied (machines, ranges and globals).
        """
        # Only the per-run data is cleared; NOT the machines, the substocks or the
        # global params, which are set beforehand by configure().
        self.cylinders.clear()
        self.stands.clear()
        self.scheduled_events.clear()
        self.alerts.clear()
        self.snapshots.clear()
        self.load_warnings.clear()
        self._no_machine_alerted.clear()

        self._load_stock(stock_df)
        self._load_changes(changes_df)

        # Fallback: if nobody configured substocks, equal ranges are derived from
        # the global range and the stand count, so the engine works even without
        # configure() (tests, scripts, checks).
        if not self.substocks:
            self._derive_default_substocks()

    def _derive_default_substocks(self) -> None:
        """
        Divide the global range (min_diameter, max_diameter] into N equal bands,
        one per stand. Called automatically from load_data() if substocks is
        empty, guaranteeing the engine works correctly without needing to call
        configure_substocks() first.
        """
        n = self.stand_count
        step = (self.max_diameter - self.min_diameter) / n
        for i in range(n):
            stand = i + 1
            lower = self.min_diameter + i * step
            upper = lower + step
            name = f"SS{stand} ({lower:.0f}-{upper:.0f})"
            self.substocks.append(
                SubStock(name, stand, upper, lower, assigned_stand=stand)
            )
        logger.info(
            "SubStocks derivados automáticamente (%d bandas de %.2f mm cada una).",
            n, step
        )

    def _load_stock(self, df: pd.DataFrame) -> None:
        """Load the initial cylinder stock and initialize the stands."""
        for idx, row in df.iterrows():
            try:
                state = CylinderState(row["Estado"])
            except ValueError as exc:
                raise ValueError(
                    f"Estado inválido '{row['Estado']}' en hoja Stock_Inicial, fila {idx}"
                ) from exc

            stand_id = int(row["Jaula_Asignada"]) if pd.notna(row.get("Jaula_Asignada")) else None
            pos = int(row["Posición"]) if pd.notna(row.get("Posición")) else None
            cil = Cylinder(str(row["ID_Cilindro"]), float(row["Diámetro_mm"]), state, stand_id, pos)

            # Physical profile: optional Excel column; if missing, derived from the
            # assigned stand's profile (a cylinder "comes" with its profile).
            profile_col = row.get("Perfil")
            if pd.notna(profile_col) and str(profile_col) != "":
                cil.profile = _normalize_profile(profile_col)
            elif stand_id is not None:
                cil.profile = self.profile_by_stand(stand_id)

            if state in (CylinderState.TO_GRIND, CylinderState.GRINDING):
                mm_col = row.get("mm_a_Rectificar")
                cil.mm_to_grind = float(mm_col) if pd.notna(mm_col) else _DEFAULT_GRIND_MM
                type_col = row.get("Tipo_Rectificado")
                type_str = str(type_col) if pd.notna(type_col) else _DEFAULT_GRIND_TYPE
                try:
                    cil.current_grinding_type = GrindingType(type_str)
                except ValueError as exc:
                    raise ValueError(
                        f"Tipo rectificado inválido '{type_str}' en hoja Stock_Inicial, fila {idx}"
                    ) from exc
                if state == CylinderState.GRINDING:
                    cil.state = CylinderState.TO_GRIND

            self.cylinders[cil.id] = cil

        # Cylinders already below the usable minimum -> SCRAPPED.
        # (During the simulation this cannot happen; only from initial data.)
        for cil in self.cylinders.values():
            if cil.state != CylinderState.SCRAPPED and cil.diameter < self.min_diameter:
                logger.warning(
                    "Cilindro %s con diámetro %.2f < mínimo %.2f: marcado BAJA al cargar.",
                    cil.id, cil.diameter, self.min_diameter
                )
                cil.state = CylinderState.SCRAPPED
                cil.stand = None

        # Warning: cylinders marked SCRAPPED despite being above the minimum.
        # Their state is not modified (the Excel datum is the source of truth);
        # it is only recorded for manual review, since they may be out of service
        # for reasons unrelated to diameter (cracks, defects, etc.).
        scrapped_above_min = [
            cil for cil in self.cylinders.values()
            if cil.state == CylinderState.SCRAPPED and cil.diameter >= self.min_diameter
        ]
        if scrapped_above_min:
            ids = ", ".join(f"{c.id} ({c.diameter:.2f})" for c in scrapped_above_min)
            msg = (
                f"AVISO: {len(scrapped_above_min)} cilindro(s) vienen marcados BAJA en los datos "
                f"pese a estar sobre el mínimo ({self.min_diameter:.2f}): {ids}"
            )
            logger.warning(msg)
            self.load_warnings.append(msg)

        # WORKING/CRC cylinders with no assigned stand: they could not be placed in
        # any stand (initial placement requires cil.stand) and would become dead
        # stock. They are reclassified to AVAILABLE so they can replenish any
        # diameter-compatible stand, and a warning is recorded for review.
        without_stand = [
            cil for cil in self.cylinders.values()
            if cil.state in (CylinderState.WORKING, CylinderState.CRC)
            and cil.stand is None
        ]
        if without_stand:
            for cil in without_stand:
                cil.state = CylinderState.AVAILABLE
                cil.stand = None
                cil.target_stand = None
            ids = ", ".join(c.id for c in without_stand)
            msg = (
                f"AVISO: {len(without_stand)} cilindro(s) venían en estado Trabajando/CRC "
                f"sin jaula asignada; se reclasifican a Disponible: {ids}"
            )
            logger.warning(msg)
            self.load_warnings.append(msg)

        # Initialize stands and place cylinders
        for j_id in range(1, self.stand_count + 1):
            self.stands[j_id] = Stand(j_id)

        for cil in self.cylinders.values():
            if cil.state == CylinderState.WORKING and cil.stand:
                if cil.stand in self.stands:
                    self.stands[cil.stand].working_cylinders.append(cil)
                else:
                    logger.warning("Cilindro %s asignado a jaula inexistente %s.", cil.id, cil.stand)
            elif cil.state == CylinderState.CRC and cil.stand:
                if cil.stand in self.stands:
                    self.stands[cil.stand].crc_cylinders.append(cil)

        self._ensure_initial_pairs()

    def _load_changes(self, df: pd.DataFrame) -> None:
        """Load the cylinder change schedule."""
        for idx, row in df.iterrows():
            type_str = str(row["Tipo_Rectificado"])
            try:
                grinding_type = GrindingType(type_str)
            except ValueError as exc:
                raise ValueError(
                    f"Tipo rectificado inválido '{type_str}' en hoja Programa_Cambios, fila {idx}"
                ) from exc

            stand_val = int(row["Jaula"])
            if stand_val not in self.stands:
                raise ValueError(
                    f"Jaula {stand_val} en Programa_Cambios fila {idx} fuera de rango "
                    f"(1-{self.stand_count})"
                )

            event = ChangeEvent(
                event_id=str(row["ID_Cambio"]),
                time=pd.to_datetime(row["Fecha_Hora"]),
                stand=stand_val,
                grinding_type=grinding_type,
                mm_to_grind=float(row["mm_a_Rectificar"]),
                note=str(row.get("Observación", ""))
            )
            self.scheduled_events.append(event)

        self.scheduled_events.sort(key=lambda e: e.time)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _ensure_initial_pairs(self) -> None:
        """Ensure each stand has its working cylinders at the start if there is stock."""
        for j_id, stand in self.stands.items():
            while len(stand.working_cylinders) < _BUFFER_CRC_SIZE:
                if stand.crc_cylinders:
                    cil = stand.crc_cylinders.pop(0)
                    cil.state = CylinderState.WORKING
                    cil.stand = j_id
                    stand.working_cylinders.append(cil)
                    continue
                available = sorted(
                    self.get_available_for_stand(j_id), key=lambda c: c.diameter, reverse=True
                )
                if available:
                    cil = available[0]
                    cil.state = CylinderState.WORKING
                    cil.stand = j_id
                    stand.working_cylinders.append(cil)
                    continue
                break

            # A stand cannot start with less than a complete pair ("complete pair
            # or nothing"): if _BUFFER_CRC_SIZE was not reached, the partial
            # cylinders already installed are emptied to the stand's CRC buffer
            # (they stay committed to it and _install_pair_or_stop will take them
            # first on reactivation). This way the STOPPED stand starts with 0
            # working, without the hybrid state (stopped + 1 working).
            if len(stand.working_cylinders) < _BUFFER_CRC_SIZE:
                partials = stand.working_cylinders
                stand.working_cylinders = []
                # Workshop rule: the CRC is filled in pairs, never a lone cylinder.
                # The partial is NOT put in the CRC: it stays Available but
                # RESERVED to this stand (target_stand), so no other stand takes it
                # and _install_pair_or_stop reintegrates it as soon as there is a
                # second cylinder of its range (the stand starts STOPPED).
                for cil in partials:
                    cil.state = CylinderState.AVAILABLE
                    cil.stand = None
                    cil.target_stand = j_id
                stand.stopped = True
                logger.warning(
                    "Jaula %s arranca PARADA: solo %d cilindro(s) en su rango de "
                    "diámetros (reservados como Disponible a la espera de pareja).",
                    j_id, len(partials)
                )

    def _install_in_stand(self, cil: Cylinder, stand_id: int, time: datetime, reason: str) -> None:
        """Move a cylinder to the WORKING state in the given stand."""
        stand = self.stands[stand_id]
        cil.state = CylinderState.WORKING
        cil.stand = stand_id
        if cil in stand.crc_cylinders:
            stand.crc_cylinders.remove(cil)
        stand.working_cylinders.append(cil)
        cil.record_event(time, reason)

    def _install_pair_or_stop(self, stand_id: int, time: datetime) -> bool:
        """
        Complete a stand's working pair (CRC first, then available cylinders of the
        range). A stand cannot operate with less than _BUFFER_CRC_SIZE cylinders:
        if there is not enough stock to complete it, it installs NONE and returns
        False (the stand must stay STOPPED).
        """
        stand = self.stands[stand_id]
        missing = _BUFFER_CRC_SIZE - len(stand.working_cylinders)
        if missing <= 0:
            return True

        candidates = list(stand.crc_cylinders)
        if len(candidates) < missing:
            available = sorted(
                self.get_available_for_stand(stand_id),
                key=lambda c: c.diameter, reverse=True
            )
            candidates += [c for c in available if c not in candidates]

        if len(candidates) < missing:
            return False  # the pair cannot be formed -> STOPPED

        for cil in candidates[:missing]:
            self._install_in_stand(cil, stand_id, time, f"Instalado en Jaula {stand_id}")
        return True

    def _stop_stand(self, stand_id: int, time: datetime, log) -> None:
        """
        Mark a stand as STOPPED (if it was not) and, with it, halt the whole line:
        record the instant the line stopped (if it had not).
        """
        stand = self.stands[stand_id]
        if not stand.stopped:
            stand.stopped = True
            stand.stopped_since = time
            self.alerts.append(Alert(
                time, "CRITICO",
                f"PARADA Jaula {stand_id}: sin stock para formar la pareja de cilindros",
                stand_id
            ))
            log(f"  >>> JAULA {stand_id} PARADA: sin CRC ni disponibles para formar pareja <<<")

        # The whole line stops from the first instant of stoppage.
        if self._line_stopped_since is None:
            self._line_stopped_since = time
            log(f"  >>> LÍNEA DETENIDA desde {time.strftime('%m-%d %H:%M')} "
                "(se difieren los cambios posteriores) <<<")

    def _try_reactivate_stands(self, time: datetime, log, queue: List[_QueueItem]) -> bool:
        """
        Try to rebuild the STOPPED stands if there is already stock for a pair.

        If after the attempt NO stand remains stopped, the line resumes: the whole
        remaining change schedule (events deferred during the stoppage and the
        ones still in the queue, after the stoppage start) is shifted by the total
        line-stoppage duration. The machines and CRC replenishment never stop.
        Returns True if it reactivated at least one stand.
        """
        reactivated = False
        for stand_id, stand in self.stands.items():
            if not stand.stopped:
                continue
            if self._install_pair_or_stop(stand_id, time):
                dur = (time - stand.stopped_since).total_seconds() / 60 if stand.stopped_since else 0.0
                stand.stopped = False
                stand.stopped_since = None
                self.alerts.append(Alert(
                    time, "INFO",
                    f"Jaula {stand_id} reactivada tras {_fmt_duration(dur)} de parada", stand_id
                ))
                log(f"  >>> JAULA {stand_id} REACTIVADA tras {_fmt_duration(dur)} de parada <<<")
                reactivated = True

        # Does the line resume? Only if no stand remains stopped.
        if self._line_stopped_since is not None and not any(j.stopped for j in self.stands.values()):
            self._resume_line(time, log, queue)

        return reactivated

    def _resume_line(self, time: datetime, log, queue: List[_QueueItem]) -> None:
        """
        Resume the line after a stoppage: shift by the total stoppage duration all
        the pending CHANGEs (the deferred ones and those still in the queue with a
        time after the stoppage start). Reintegrates the deferred ones.
        """
        start = self._line_stopped_since
        dur = (time - start).total_seconds() / 60 if start else 0.0
        delay = timedelta(minutes=dur)

        # Start from the canonical queue order (= heap pop order, identical to the
        # sorted list of the previous scheme) before shifting.
        events = [ev for _, _, ev in sorted(queue)]

        # Shift in place the CHANGEs still in the queue (after the start), keeping
        # their relative position as the previous sort did.
        for i, ev_s in enumerate(events):
            if ev_s.type == "CHANGE" and ev_s.time > start:
                events[i] = _SimEvent(ev_s.type, ev_s.time + delay, ev_s.data)

        # Reintegrate the changes deferred during the stoppage, already shifted.
        for ev_s in self._deferred_changes:
            events.append(_SimEvent(ev_s.type, ev_s.time + delay, ev_s.data))
        n_def = len(self._deferred_changes)
        self._deferred_changes = []

        # Stable sort by time (as before) and heap rebuild reassigning the
        # sequence in that order: preserves the exact tie-break and leaves events
        # inserted later (higher seq) after equal-time ones.
        events.sort(key=lambda x: x.time)
        queue[:] = [(ev.time, next(self._queue_seq), ev) for ev in events]
        heapq.heapify(queue)
        self._line_stopped_since = None

        self.alerts.append(Alert(
            time, "INFO",
            f"LÍNEA REANUDADA tras {_fmt_duration(dur)}; programa de cambios desplazado "
            f"{_fmt_duration(dur)} ({n_def} cambio(s) diferido(s) reprogramado(s))"
        ))
        log(f"  >>> LÍNEA REANUDADA tras {_fmt_duration(dur)} | programa desplazado {_fmt_duration(dur)} "
            f"| {n_def} cambio(s) diferido(s) <<<")

    # ── State queries ───────────────────────────────────────────────────────

    def get_substock_by_diameter(self, diameter: float) -> Optional[SubStock]:
        """Find which SubStock a diameter belongs to."""
        for ss in self.substocks:
            if ss.contains_diameter(diameter):
                return ss
        return None

    def get_substock_by_stand(self, stand_id: int) -> Optional[SubStock]:
        """Get the SubStock configured for a specific stand."""
        for ss in self.substocks:
            if ss.assigned_stand == stand_id:
                return ss
        return None

    def profile_by_stand(self, stand_id: int) -> Optional[str]:
        """Return the profile (convexity) required by a stand (None = any)."""
        ss = self.get_substock_by_stand(stand_id)
        return ss.profile if ss is not None else None

    @staticmethod
    def _profile_compatible(cyl_profile: Optional[str], stand_profile: Optional[str]) -> bool:
        """True if a cylinder with ``cyl_profile`` can go to a stand of ``stand_profile``.

        If the stand requires no profile (None) or the cylinder has no profile
        (None), they are compatible; otherwise they must match. This preserves the
        historical behavior (no profiles ⇒ always compatible).
        """
        return stand_profile is None or cyl_profile is None or cyl_profile == stand_profile

    def get_cylinders_by_state(self, state: CylinderState) -> List[Cylinder]:
        """Filter the cylinder list by their current state."""
        return [c for c in self.cylinders.values() if c.state == state]

    def _admissible_in_stand(self, cil: Cylinder, stand_id: int) -> bool:
        """True if ``cil`` (by diameter and profile) is admissible in the given stand.

        If the cylinder has a target stand (``target_stand``), it is only
        admissible in THAT stand. Otherwise it requires a diameter in band and a
        compatible profile. Hard diameter pre-filter (workshop rule).
        """
        if cil.target_stand is not None:
            return cil.target_stand == stand_id
        ss = self.get_substock_by_stand(stand_id)
        if ss is None:
            return True
        return ss.contains_diameter(cil.diameter) and self._profile_compatible(cil.profile, ss.profile)

    def _is_placeable(self, cil: Cylinder) -> bool:
        """True if ``cil`` is admissible (diameter+profile) in some stand."""
        return any(self._admissible_in_stand(cil, j) for j in range(1, self.stand_count + 1))

    def get_available_for_stand(self, stand_id: int) -> List[Cylinder]:
        """Get available cylinders admissible (diameter + profile + target) in the stand."""
        available = self.get_cylinders_by_state(CylinderState.AVAILABLE)
        return [c for c in available if self._admissible_in_stand(c, stand_id)]

    def get_grinding_queue(self) -> List[Cylinder]:
        """Get the list of cylinders waiting to be ground."""
        return self.get_cylinders_by_state(CylinderState.TO_GRIND)

    @staticmethod
    def _effective_type(cil: Cylinder, maq: GrindingMachine) -> GrindingType:
        """Pass type that would be executed: the cylinder's own, or the machine
        priority when the cylinder has none. Single source used by selection
        (capability filter) and by assignment."""
        return cil.current_grinding_type if cil.current_grinding_type else maq.default_priority

    def select_next_from_queue(
        self, queue: List[Cylinder], machine: Optional[GrindingMachine] = None
    ) -> Optional[Cylinder]:
        """Choose the next cylinder to grind for a machine.

        Three-step selection:
          0. Capability filter: if a machine is given, only the cylinders whose
             pass type the machine **can execute** (has a usable rate) are
             considered. Without this, a machine with no rate for the requested
             type would get an ``inf`` process time and the simulation would crash
             building the ``timedelta`` (see machine.compute_process_time). If it
             can do none of the queue, returns ``None`` (another machine takes it).
          1. Priority filter: among the processable ones, the cylinders whose
             grinding type matches their default_priority are considered first. If
             none match (or no machine is given), all processable are considered.
          2. Strategy: the configured selection strategy is applied over the
             resulting subset (see SELECTION_STRATEGIES).
        """
        if not queue:
            return None

        candidates = queue
        if machine is not None:
            processable = [c for c in queue
                           if machine.can_grind(self._effective_type(c, machine).value)]
            if not processable:
                return None
            candidates = processable
            preferred = [c for c in processable if c.current_grinding_type == machine.default_priority]
            if preferred:
                candidates = preferred

        strategy = SELECTION_STRATEGIES.get(
            self.selection_strategy, SELECTION_STRATEGIES[DEFAULT_STRATEGY]
        )
        return strategy.select(candidates, machine)

    # ── Snapshot ────────────────────────────────────────────────────────────

    def generate_snapshot(self, time: datetime) -> None:
        """Capture the full workshop state for playback and charts.

        Walks ``self.cylinders`` **only once**, accumulating at the same time the
        count by state, the grinding-queue and cooling detail, and the per-SubStock
        counts (it used to be ~9 full passes over the dict per snapshot, and a
        snapshot is generated per event). The result is identical.
        """
        sn = Snapshot(time)

        # All states present as a key (even with value 0), as before: the GUI and
        # the charts expect the key even if there are no cylinders.
        sn.conteo_por_estado = {st.value: 0 for st in CylinderState}
        # Only present states per SubStock (no zeros seeded), as before.
        substock_count: Dict[str, Dict[str, int]] = {ss.name: {} for ss in self.substocks}

        for c in self.cylinders.values():
            state_val = c.state.value
            sn.conteo_por_estado[state_val] += 1
            # The order of these lists follows self.cylinders.values(), same as
            # get_grinding_queue()/get_cylinders_by_state() before.
            if c.state == CylinderState.TO_GRIND:
                sn.detalle_cola_rectificado.append({"id": c.id, "d": c.diameter})
            elif c.state == CylinderState.COOLING:
                sn.detalle_enfriando.append({"id": c.id, "d": c.diameter})
            if c.state != CylinderState.SCRAPPED:
                for ss in self.substocks:
                    if ss.contains_diameter(c.diameter):
                        cs = substock_count[ss.name]
                        cs[state_val] = cs.get(state_val, 0) + 1

        sn.cantidad_disponibles = sn.conteo_por_estado.get(CylinderState.AVAILABLE.value, 0)
        sn.cantidad_crc_total = sn.conteo_por_estado.get(CylinderState.CRC.value, 0)
        sn.cantidad_bajas = sn.conteo_por_estado.get(CylinderState.SCRAPPED.value, 0)
        sn.maquinas_ocupadas = sum(1 for m in self.machines.values() if m.busy)

        for j_id, stand in self.stands.items():
            sn.crc_por_jaula[j_id] = len(stand.crc_cylinders)
            sn.detalle_jaulas[j_id] = [{"id": c.id, "d": c.diameter} for c in stand.working_cylinders]
            sn.detalle_crc[j_id] = [{"id": c.id, "d": c.diameter} for c in stand.crc_cylinders]
            if stand.stopped:
                sn.jaulas_paradas.append(j_id)

        for m_name, maq in self.machines.items():
            sn.detalle_maquinas_operativa[m_name] = maq.is_operative(time)
            if maq.busy and maq.current_cylinder:
                c = maq.current_cylinder
                progress = 0.0
                # Progress by operative time: it does not advance during the shifts
                # in which the machine is off. With grid None it equals the clock.
                if maq.current_work_minutes > 0 and c.grinding_start:
                    consumed = maq.operative_progress(time)
                    progress = min(100.0, max(0.0, (consumed / maq.current_work_minutes) * 100))
                sn.detalle_maquinas[m_name] = {"id": c.id, "d": c.diameter, "progreso": progress}
            else:
                sn.detalle_maquinas[m_name] = None

        for ss in self.substocks:
            counts = substock_count[ss.name]
            sn.conteo_por_substock[ss.name] = counts
            sn.disponibles_por_substock[ss.name] = counts.get(CylinderState.AVAILABLE.value, 0)

        self.snapshots.append(sn)

    # ── Assignment logic ────────────────────────────────────────────────────

    def assign_machine_work(self, time: datetime) -> List[_SimEvent]:
        """Try to assign cylinders from the queue to free machines.

        A machine only takes work if it is in an operative shift (see the work
        schedule in models/shifts.py). Free machines off shift with pending queue
        are "woken up" with a RESUME_MACHINE event at the start of their next shift.
        """
        new_events: List[_SimEvent] = []
        queue = self.get_grinding_queue()
        for name, maq in self.machines.items():
            if maq.busy:
                continue
            # Off shift: it does not grind. If there is a queue, schedule a wake-up
            # at the next opening (without duplicating) and continue with others.
            if not maq.is_operative(time):
                if queue and not maq._wakeup_scheduled:
                    opening = maq.next_opening(time)
                    if opening is not None:
                        maq._wakeup_scheduled = True
                        new_events.append(_SimEvent("RESUME_MACHINE", opening, name))
                continue
            if not queue:
                break
            cil = self.select_next_from_queue(queue, maq)
            if cil is None:
                continue

            mm = cil.mm_to_grind if cil.mm_to_grind > 0 else _DEFAULT_GRIND_MM
            grinding_type = self._effective_type(cil, maq)
            new_diam = cil.diameter - mm

            # A pass projecting a diameter < minimum is NOT scrapped in place: the
            # grind runs anyway (it really reduces the diameter) and the SCRAP is
            # decided only at the end, in _finish_and_continue, once the real
            # diameter dropped below the minimum ("grind then scrap").
            # The engine decides the target stand (and therefore the profile) with
            # the projected diameter after grinding; the machine only applies it.
            _, profile = self._assign_target_stand(cil, new_diam, time)
            maq.start_grinding(cil, time, grinding_type, mm, profile)
            new_events.append(_SimEvent("GRIND_END", maq.grinding_end_time, name))
            queue.remove(cil)

        # Safe degradation: a cylinder whose pass type NO machine can execute
        # (missing rate) is never assigned and would get stuck in the queue.
        # Before this reached start_grinding with an ``inf`` process time and
        # crashed with OverflowError; now it stays waiting and is warned once per
        # cylinder (controlled WARNING, without halting the simulation).
        for cil in queue:
            if cil.id in self._no_machine_alerted:
                continue
            if not any(maq.can_grind(self._effective_type(cil, maq).value)
                       for maq in self.machines.values()):
                self._no_machine_alerted.add(cil.id)
                type_txt = cil.current_grinding_type.value if cil.current_grinding_type else "?"
                self.alerts.append(Alert(
                    time, "WARNING",
                    f"Cilindro {cil.id}: ninguna máquina tiene tasa para el pase "
                    f"'{type_txt}'; queda en espera (revise la configuración de máquinas)."
                ))

        return new_events

    def _assign_target_stand(self, cil: Cylinder, final_diameter: float,
                             time: datetime) -> Tuple[Optional[int], Optional[str]]:
        """Decide a cylinder's target stand when its grind starts.

        Pre-filters the stands by **admissible projected diameter** (hard workshop
        rule: never assigned to a stand whose SubStock does not admit the
        diameter) and applies the configured assignment strategy over the
        candidates. Returns ``(target_stand, profile)`` and tags
        ``cil.target_stand`` (the machine cuts the profile). If no stand admits the
        diameter, returns ``(None, current_profile)`` and leaves
        ``target_stand=None`` (non-placeable stock, re-profiled when finished).
        """
        candidates = [
            j for j in range(1, self.stand_count + 1)
            if (ss := self.get_substock_by_stand(j)) is not None
            and ss.contains_diameter(final_diameter)
        ]
        if not candidates:
            cil.target_stand = None
            return None, cil.profile

        strategy = ASSIGNMENT_STRATEGIES.get(
            self.assignment_strategy, ASSIGNMENT_STRATEGIES[DEFAULT_ASSIGNMENT_STRATEGY]
        )
        target = strategy.assign(cil, candidates, self)
        cil.target_stand = target
        return target, self.profile_by_stand(target)

    def replenish_crc_buffer(self, stand_id: int, time: datetime) -> bool:
        """Try to fill a stand's CRC with available cylinders.

        The transport to the CRC moves **in pairs** (`_BUFFER_CRC_SIZE`): the
        transport resource moves the full pair in one trip, never a lone cylinder.
        If there are not enough available to complete what is missing, it moves
        **none** (they stay Available) and returns False — the stand reactivation
        (`_install_pair_or_stop`) takes them straight from the stock anyway.
        """
        stand = self.stands[stand_id]
        needed = _BUFFER_CRC_SIZE - len(stand.crc_cylinders)
        if needed <= 0:
            return True

        available = sorted(
            self.get_available_for_stand(stand_id), key=lambda c: c.diameter, reverse=True
        )
        if len(available) < needed:
            return False  # incomplete pair: a lone cylinder is not put in the CRC

        for cil in available[:needed]:
            cil.state = CylinderState.CRC
            cil.stand = stand_id
            stand.crc_cylinders.append(cil)
            cil.record_event(time, f"Traslado a CRC Jaula {stand_id}")

        return True

    def _push_event(self, queue: List[_QueueItem], event: _SimEvent) -> None:
        """Insert an event into the priority queue (heap) by (time, sequence).

        The sequence counter breaks time ties in FIFO insertion order, exactly
        reproducing the order given by the previous scheme's stable list.sort() by
        time (and avoids comparing the _SimEvents).
        """
        heapq.heappush(queue, (event.time, next(self._queue_seq), event))

    def _schedule_crc_replenishment(self, stand_id: int, request_time: datetime, queue: List[_QueueItem]) -> None:
        """
        Queue a CRC replenishment respecting the single transport resource.

        The Available→CRC transport is performed by a single resource
        (crane/operator), so replenishments are serialized: each pair takes
        crc_transfer_time_min and the next one does not start until the previous
        one finishes. If there is already a pending replenishment for the stand,
        or its CRC is already complete, nothing is scheduled.
        """
        if stand_id in self._pending_replenishment:
            return
        if len(self.stands[stand_id].crc_cylinders) >= _BUFFER_CRC_SIZE:
            return

        free_at = self._crc_resource_free_at or request_time
        start = max(request_time, free_at)
        end = start + timedelta(minutes=self.crc_transfer_time_min)
        self._crc_resource_free_at = end
        self._pending_replenishment.add(stand_id)
        self._push_event(queue, _SimEvent("REPLENISH_CRC", end, stand_id))

    # ── Simulation event handlers ───────────────────────────────────────────

    def _finish_and_continue(self, machine: GrindingMachine, time: datetime,
                             queue: List[_QueueItem], log: Callable[[str], None]) -> None:
        """Close a grind and reactivate the dependent flow.

        After freeing the machine: rebuilds stopped stands with the new stock,
        replenishes the CRC, reassigns work to the free machines and takes a
        snapshot. Shared by the GRIND_END handler and the final drain of the
        simulation (both close in-progress grinds in the same way).
        """
        finished_cil = machine.finish_grinding(time)
        if finished_cil and finished_cil.diameter < self.min_diameter:
            # The pass was already applied (real diameter reduced): now that it
            # dropped below the minimum, it is finally scrapped ("grind then scrap").
            finished_cil.state = CylinderState.SCRAPPED
            finished_cil.record_event(
                time, "BAJA",
                f"Diámetro {finished_cil.diameter:.2f} < {self.min_diameter}")
            self.alerts.append(Alert(
                time, "INFO", f"Cilindro {finished_cil.id} dado de BAJA"))
            finished_cil = None  # do not treat it as a freshly Available cylinder
        if (finished_cil and not self._is_placeable(finished_cil)
                and finished_cil.diameter > self.min_diameter):
            # Not placeable in any stand (its profile/diameter does not fit):
            # instead of becoming dead stock, it is re-queued to grinding with a
            # production pass of _REPROFILE_MM mm; on restart the strategy
            # re-decides the stand (and the profile) with the new projected diameter.
            self.alerts.append(Alert(
                time, "INFO",
                f"Cilindro {finished_cil.id} no colocable; re-perfilado "
                f"producción {_REPROFILE_MM} mm"))
            finished_cil.state = CylinderState.TO_GRIND
            finished_cil.current_grinding_type = GrindingType.PRODUCTION
            finished_cil.mm_to_grind = _REPROFILE_MM
            finished_cil.target_stand = None
            finished_cil.record_event(time, "No colocable: re-perfilado a producción")
            finished_cil = None  # do not treat it as a freshly Available cylinder
        if finished_cil:
            # Priority: rebuild stopped stands before replenishing the CRC.
            self._try_reactivate_stands(time, log, queue)
            for j_id in range(1, self.stand_count + 1):
                self._schedule_crc_replenishment(j_id, time, queue)
        for ev in self.assign_machine_work(time):
            self._push_event(queue, ev)
        self.generate_snapshot(time)

    def _handle_grind_end(self, ev_sim: "_SimEvent", queue: List[_QueueItem],
                          log: Callable[[str], None]) -> None:
        """GRIND_END: a machine finishes a grind.

        Never deferred during a STOPPAGE: it is exactly what produces the stock
        that lets the line resume.
        """
        machine = self.machines.get(ev_sim.data)
        if not machine or not machine.busy:
            return
        # Discard obsolete GRIND_END (the machine was already reassigned): the
        # recorded end must match the event's.
        if (machine.grinding_end_time
                and abs((machine.grinding_end_time - ev_sim.time).total_seconds()) > 2):
            return
        self._finish_and_continue(machine, ev_sim.time, queue, log)

    def _handle_replenish_crc(self, ev_sim: "_SimEvent", queue: List[_QueueItem],
                              log: Callable[[str], None]) -> None:
        """REPLENISH_CRC: a pair arrives at the CRC buffer (always runs, even in STOPPAGE)."""
        j_id = ev_sim.data
        self._pending_replenishment.discard(j_id)
        # Only replenishes (and generates a snapshot) if the CRC is still incomplete.
        if len(self.stands[j_id].crc_cylinders) < _BUFFER_CRC_SIZE:
            self.replenish_crc_buffer(j_id, ev_sim.time)
            self._try_reactivate_stands(ev_sim.time, log, queue)
            self.generate_snapshot(ev_sim.time)

    def _handle_cooling_end(self, ev_sim: "_SimEvent", queue: List[_QueueItem],
                            log: Callable[[str], None]) -> None:
        """COOLING_END: a cylinder finishes cooling and enters the grinding queue.

        Cooling is a physical process: it always completes, also during a STOPPAGE
        (like GRIND_END).
        """
        cil = self.cylinders.get(ev_sim.data)
        if cil and cil.state == CylinderState.COOLING:
            cil.state = CylinderState.TO_GRIND
            cil.record_event(ev_sim.time, "Fin de enfriado, pasa a cola de rectificado")
            for ev in self.assign_machine_work(ev_sim.time):
                self._push_event(queue, ev)
            self.generate_snapshot(ev_sim.time)

    def _handle_resume_machine(self, ev_sim: "_SimEvent", queue: List[_QueueItem],
                               log: Callable[[str], None]) -> None:
        """RESUME_MACHINE: a machine reopens its shift and retries taking work.

        It is a wall-clock process (shifts): it always runs, also during a
        STOPPAGE, and _resume_line does not shift it (like GRIND_END/COOLING_END).
        """
        machine = self.machines.get(ev_sim.data)
        if not machine:
            return
        machine._wakeup_scheduled = False
        for ev in self.assign_machine_work(ev_sim.time):
            self._push_event(queue, ev)
        self.generate_snapshot(ev_sim.time)

    def _handle_change(self, ev_sim: "_SimEvent", queue: List[_QueueItem],
                       log: Callable[[str], None]) -> None:
        """CHANGE: a scheduled stand change. The only event a STOPPAGE defers."""
        ev = ev_sim.data
        if ev.id in self._processed_events:
            return

        # Line stopped: changes after the stoppage start are deferred (the ones
        # simultaneous to the stoppage do run). They are rescheduled when the line
        # resumes, shifted by the total stoppage duration.
        if (self._line_stopped_since is not None
                and ev_sim.time > self._line_stopped_since):
            self._deferred_changes.append(ev_sim)
            return

        self._processed_events.add(ev.id)
        stand = self.stands[ev.stand]

        # ev_sim.time is the real processing time (it may be shifted with respect
        # to the original ev.time if there was a STOPPAGE).
        t_proc = ev_sim.time
        delay_str = (f" [orig {ev.time.strftime('%H:%M')}, retr "
                     f"{_fmt_duration((t_proc - ev.time).total_seconds() / 60)}]"
                     if t_proc != ev.time else "")
        log(f"  {t_proc.strftime('%m-%d %H:%M')} | Jaula {ev.stand} | Cambio a {ev.grinding_type.value}"
            f" | CRC={len(stand.crc_cylinders)}{delay_str}")

        # 1. The working cylinders leave the stand. With cooling configured they go
        #    to COOLING (they enter grinding when COOLING_END fires); if it is 0,
        #    they go straight to TO_GRIND (historical behavior).
        for cil in list(stand.working_cylinders):
            cil.stand = None
            cil.target_stand = None  # re-decided at the next grind
            cil.current_grinding_type = ev.grinding_type
            cil.mm_to_grind = ev.mm_to_grind
            if self.cooling_time_h > 0:
                cil.state = CylinderState.COOLING
                cooling_end = t_proc + timedelta(hours=self.cooling_time_h)
                cil.record_event(
                    t_proc, f"En enfriado tras Jaula {ev.stand} ({self.cooling_time_h:.1f} h)")
                self._push_event(queue, _SimEvent("COOLING_END", cooling_end, cil.id))
            else:
                cil.state = CylinderState.TO_GRIND
                cil.record_event(t_proc, f"Retirado de Jaula {ev.stand} para rectificado")
        stand.working_cylinders.clear()

        # 2. Mount a complete pair to the stand; if there is no stock, STOPPAGE.
        #    The stand cannot operate with less than _BUFFER_CRC_SIZE cylinders.
        if self._install_pair_or_stop(ev.stand, t_proc):
            stand.stopped = False
            stand.stopped_since = None
        else:
            self._stop_stand(ev.stand, t_proc, log)

        # 3. Assign work to machines and 4. schedule the CRC replenishment with the
        #    CRC already emptied; then snapshot. The insertion order (assignments
        #    before the replenishment) sets the tie-break at equal time.
        for new_ev in self.assign_machine_work(t_proc):
            self._push_event(queue, new_ev)
        self._schedule_crc_replenishment(ev.stand, t_proc, queue)
        self.generate_snapshot(t_proc)

    # ── Simulation ──────────────────────────────────────────────────────────

    def simulate(self, strategy: str = "mayor_diametro", callback_log: Optional[Callable[[str], None]] = None) -> None:
        """Run the full simulation based on the scheduled events."""
        self.selection_strategy = strategy
        self.alerts.clear()
        self.snapshots.clear()
        self.simulation_log.clear()

        def _log(msg: str) -> None:
            # Always accumulated (the GUI dumps it after a run in a separate
            # process) and, if there is a live callback (CLI/test in the same
            # process), it is also emitted immediately.
            self.simulation_log.append(msg)
            if callback_log:
                callback_log(msg)

        if not self.scheduled_events:
            _log("No hay eventos programados para simular.")
            return

        _log(f"Iniciando simulación | Estrategia: {strategy} | Cilindros: {len(self.cylinders)}")

        t_current = self.scheduled_events[0].time - timedelta(minutes=1)
        self._crc_resource_free_at = t_current
        self._pending_replenishment = set()
        self._line_stopped_since = None
        self._deferred_changes = []
        self._processed_events: set = set()
        self._queue_seq = itertools.count()
        self.generate_snapshot(t_current)

        # Priority queue (heap) by (time, sequence): push/pop in O(log n) instead
        # of the previous scheme's list.sort() O(n log n) per event. The initial
        # insertion order (all the CHANGEs and then the machine assignments) sets
        # the tie-break at equal time, as before.
        queue: List[_QueueItem] = []
        for ev in self.scheduled_events:
            self._push_event(queue, _SimEvent("CHANGE", ev.time, ev))
        for ev in self.assign_machine_work(t_current):
            self._push_event(queue, ev)

        # Dispatch by event type. A line STOPPAGE only defers the CHANGEs (see
        # _handle_change); GRIND_END/REPLENISH_CRC/COOLING_END always run: the
        # machines keep producing the stock that resumes the line.
        handlers = {
            "GRIND_END": self._handle_grind_end,
            "REPLENISH_CRC": self._handle_replenish_crc,
            "COOLING_END": self._handle_cooling_end,
            "RESUME_MACHINE": self._handle_resume_machine,
            "CHANGE": self._handle_change,
        }

        iteration = 0
        while queue and iteration < self.max_iterations:
            iteration += 1
            _, _, ev_sim = heapq.heappop(queue)
            handler = handlers.get(ev_sim.type)
            if handler:
                handler(ev_sim, queue, _log)

        if queue and iteration >= self.max_iterations:
            msg = f"ADVERTENCIA: Límite de {self.max_iterations} iteraciones alcanzado con {len(queue)} eventos pendientes."
            logger.warning(msg)
            _log(msg)

        # Finalize in-progress grinds when the scheduled events end, with the same
        # logic as GRIND_END (via _finish_and_continue).
        for _ in range(_MAX_FINALIZE_ITERATIONS):
            had_activity = False
            for machine in self.machines.values():
                if machine.busy and machine.grinding_end_time:
                    had_activity = True
                    self._finish_and_continue(machine, machine.grinding_end_time, queue, _log)
            if not had_activity:
                break

        t_final = max(s.tiempo for s in self.snapshots) + timedelta(minutes=30) if self.snapshots else datetime.now()
        self.generate_snapshot(t_final)

        # Changes that never ran due to a line stoppage without resume.
        not_run = (list(self._deferred_changes)
                   + [ev for _, _, ev in queue if ev.type == "CHANGE"])
        if not_run:
            ids = ", ".join(e.data.id for e in not_run)
            msg = (f"ADVERTENCIA: {len(not_run)} cambio(s) no se ejecutaron por parada "
                   f"de línea sin reanudar: {ids}")
            logger.warning(msg)
            _log(f"  >>> {msg} <<<")

        nc = sum(1 for a in self.alerts if a.type == "CRITICO")
        nb = len(self.get_cylinders_by_state(CylinderState.SCRAPPED))
        _log(f"\nSimulación finalizada | Alertas Críticas: {nc} | Bajas: {nb}")

    # ── Export ──────────────────────────────────────────────────────────────

    def export_results(self, file_path: str) -> None:
        """Save the final state and alerts to an Excel file."""
        final_rows = []
        for cil in self.cylinders.values():
            ss = self.get_substock_by_diameter(cil.diameter)
            final_rows.append({
                "ID": cil.id,
                "D_Original": cil.original_diameter,
                "D_Final": cil.diameter,
                "Desgaste_Total": round(cil.original_diameter - cil.diameter, 2),
                "Estado": cil.state.value,
                "SubStock": ss.name if ss else "-",
                "Jaula": cil.stand if cil.stand else "-"
            })

        df_stock = pd.DataFrame(final_rows).sort_values("D_Final", ascending=False)

        alerts_list = [
            {"Tiempo": a.time, "Tipo": a.type, "Mensaje": a.message, "Jaula": a.stand if a.stand else "-"}
            for a in self.alerts
        ]
        df_alerts = (
            pd.DataFrame(alerts_list) if alerts_list
            else pd.DataFrame(columns=["Tiempo", "Tipo", "Mensaje", "Jaula"])
        )

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df_stock.to_excel(writer, sheet_name="Stock_Final", index=False)
            df_alerts.to_excel(writer, sheet_name="Alertas", index=False)
