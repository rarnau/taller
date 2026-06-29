"""Estrategia de reposición de cilindros (lote de 4 al mes siguiente).

Cuando se completan ``TAMANO_LOTE`` (4) BAJAs de runtime, llega un lote de 4
cilindros nuevos (al diámetro máximo) el primer día operativo del mes siguiente;
lotes acumulados se escalonan uno por mes. La estrategia por defecto ("ninguna")
no repone nada (preserva el comportamiento histórico / golden master).

Estos tests fijan: (1) el helper de calendario, (2) la lógica de lotes de la
estrategia, y (3) la simulación end-to-end (aparecen cilindros ``NUEVO-*``).
"""
from datetime import datetime

import pandas as pd

from config.persistencia import cargar_config
from modelos import turnos
from modelos.estrategias import ESTRATEGIAS_REPOSICION, _LoteMensual
from modelos.enums import EstadoCilindro
from modelos.taller import TallerCilindros, _MM_RECTIFICAR_DEFECTO

_COLS_CAMBIOS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                 "mm_a_Rectificar", "Observación"]
_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                   "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}]


# ── 1. Helper de calendario ──────────────────────────────────────────────────

def test_primer_dia_mes_siguiente_sin_grilla():
    """Sin régimen (24/7): día 1 del mes siguiente a las 00:00."""
    r = turnos.primer_dia_operativo_mes_siguiente(None, datetime(2026, 6, 15, 9, 30))
    assert r == datetime(2026, 7, 1, 0, 0)


def test_primer_dia_mes_siguiente_borde_diciembre():
    """Diciembre → enero del año siguiente."""
    r = turnos.primer_dia_operativo_mes_siguiente(None, datetime(2026, 12, 10, 0, 0))
    assert r == datetime(2027, 1, 1, 0, 0)


def test_primer_dia_mes_siguiente_respeta_grilla():
    """Con régimen, el resultado cae en una hora operativa del mes siguiente."""
    grilla = turnos.expandir(turnos.PRESETS["lv3"])  # L-V con 3 turnos; finde acotado
    r = turnos.primer_dia_operativo_mes_siguiente(grilla, datetime(2026, 6, 15, 9, 30))
    assert r >= datetime(2026, 7, 1, 0, 0)
    assert grilla[r.weekday()][r.hour] is True


# ── 2. Lógica de lotes de _LoteMensual ───────────────────────────────────────

def _taller_repo():
    t = TallerCilindros()
    t.configurar(cargar_config())
    t.grilla_cambios = None
    t._repo_ultima_llegada = None
    t._repo_bajas_pendientes = 0
    return t


def test_lote_un_lote_por_cada_cuatro():
    t = _taller_repo()
    t._repo_bajas_pendientes = 4
    pedidos = _LoteMensual().planificar(t, datetime(2026, 6, 20, 10, 0))
    assert len(pedidos) == 1
    assert pedidos[0].cantidad == 4
    assert pedidos[0].diametro == t.diametro_maximo
    assert pedidos[0].tiempo_llegada == datetime(2026, 7, 1, 0, 0)


def test_lote_menos_de_cuatro_no_repone():
    t = _taller_repo()
    t._repo_bajas_pendientes = 3
    assert _LoteMensual().planificar(t, datetime(2026, 6, 20, 10, 0)) == []


def test_lote_ocho_se_escalonan_en_meses_consecutivos():
    """8 pendientes ⇒ 2 lotes, en meses consecutivos (uno por mes)."""
    t = _taller_repo()
    t._repo_bajas_pendientes = 8
    pedidos = _LoteMensual().planificar(t, datetime(2026, 6, 20, 10, 0))
    assert [p.tiempo_llegada for p in pedidos] == [
        datetime(2026, 7, 1, 0, 0), datetime(2026, 8, 1, 0, 0)]


def test_lote_encadena_desde_ultima_llegada():
    """Una baja nueva con una llegada ya agendada programa el mes posterior."""
    t = _taller_repo()
    t._repo_ultima_llegada = datetime(2026, 7, 1, 0, 0)
    t._repo_bajas_pendientes = 4
    pedidos = _LoteMensual().planificar(t, datetime(2026, 6, 25, 10, 0))
    assert pedidos[0].tiempo_llegada == datetime(2026, 8, 1, 0, 0)


# ── 3. Simulación end-to-end ─────────────────────────────────────────────────

def _df_cambios(rows):
    return pd.DataFrame(rows, columns=_COLS_CAMBIOS)


# Cambios que muelen 4 cilindros por debajo del mínimo (4 BAJAs) el 15-jun.
_CAMBIOS_BAJAS = [
    {"ID_Cambio": "C1", "Fecha_Hora": datetime(2026, 6, 15, 8, 0), "Jaula": 1,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 5.0, "Observación": ""},
    {"ID_Cambio": "C2", "Fecha_Hora": datetime(2026, 6, 15, 12, 0), "Jaula": 1,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 5.0, "Observación": ""},
]
# Cambio tardío (jul) que mantiene la ventana abierta más allá de la entrega 01-jul.
_CAMBIO_TARDIO = {"ID_Cambio": "C3", "Fecha_Hora": datetime(2026, 7, 5, 8, 0),
                  "Jaula": 1, "Tipo_Rectificado": "produccion",
                  "mm_a_Rectificar": 1.0, "Observación": ""}


def _stock_con_bajas():
    """2 trabajando + 4 disponibles, todos a 522 (un pase de 5 mm ⇒ 517 < 520 ⇒ BAJA)."""
    return pd.DataFrame(
        [{"ID_Cilindro": "W1", "Diámetro_mm": 522.0, "Estado": "Trabajando",
          "Jaula_Asignada": 1, "Posición": 1},
         {"ID_Cilindro": "W2", "Diámetro_mm": 522.0, "Estado": "Trabajando",
          "Jaula_Asignada": 1, "Posición": 2}]
        + [{"ID_Cilindro": f"D{i}", "Diámetro_mm": 522.0, "Estado": "Disponible",
            "Jaula_Asignada": None, "Posición": None} for i in range(4)]
    )


def _cfg_con_bajas(estrategia_reposicion: str) -> dict:
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 519.0}],
        "maquinas": _MAQ,
        "estrategia_reposicion": estrategia_reposicion,
    }


def _taller_con_bajas(estrategia_reposicion: str, cambio_tardio: bool = False) -> TallerCilindros:
    t = TallerCilindros()
    t.configurar(_cfg_con_bajas(estrategia_reposicion))
    rows = list(_CAMBIOS_BAJAS) + ([_CAMBIO_TARDIO] if cambio_tardio else [])
    t.cargar_datos_desde_dataframes(_stock_con_bajas(), _df_cambios(rows))
    t.simular(callback_log=None)
    return t


def test_reposicion_inyecta_cilindros_nuevos():
    """Entrega DENTRO de la ventana (hay un cambio tardío): las 4 BAJAs ⇒ 4 NUEVO-*."""
    t = _taller_con_bajas("lote_4_mensual", cambio_tardio=True)
    bajas = [c for c in t.cilindros.values() if c.estado == EstadoCilindro.BAJA]
    nuevos = [c for c in t.cilindros.values() if c.id.startswith("NUEVO-")]
    assert len(bajas) >= 4
    assert len(nuevos) == 4
    assert t._repo_pendientes_fuera == 0
    # Llegan al diámetro máximo y reciben un único pase de preparación (el motor
    # eleva un mm 0 al pase mínimo), así que quedan a máximo − _MM_RECTIFICAR_DEFECTO.
    assert all(
        t.diametro_maximo - _MM_RECTIFICAR_DEFECTO - 0.01 <= c.diametro <= t.diametro_maximo
        for c in nuevos)


def test_reposicion_fuera_de_ventana_queda_pendiente():
    """Entrega DESPUÉS del último cambio (B): no entrega, registra pedido pendiente.

    Sin cambio tardío, la llegada (01-jul) cae tras el último cambio (15-jun): no
    se crean cilindros, no se extiende la simulación (el último snapshot queda
    dentro de la ventana) y se anota el pedido pendiente.
    """
    t = _taller_con_bajas("lote_4_mensual", cambio_tardio=False)
    assert [c for c in t.cilindros.values() if c.id.startswith("NUEVO-")] == []
    assert t._repo_pendientes_fuera == 4
    assert t.snapshots[-1].tiempo < datetime(2026, 7, 1, 0, 0)
    assert any("pendiente" in a.mensaje.lower() for a in t.alertas)


def test_sin_reposicion_no_inyecta_nada():
    """La estrategia por defecto ('ninguna') no crea cilindros nuevos ni pendientes."""
    t = _taller_con_bajas("ninguna", cambio_tardio=True)
    assert [c for c in t.cilindros.values() if c.id.startswith("NUEVO-")] == []
    assert t._repo_pendientes_fuera == 0


def test_registry_expone_ambas_estrategias():
    assert set(ESTRATEGIAS_REPOSICION) == {"ninguna", "lote_4_mensual"}


def test_reposicion_no_pisa_id_existente():
    """Un cilindro de stock llamado NUEVO-001 no es sobrescrito por la reposición.

    El guard de _nuevo_id_reposicion salta los ids ya presentes, así que los
    nuevos arrancan en NUEVO-002 y el NUEVO-001 cargado queda intacto.
    """
    t = TallerCilindros()
    t.configurar(_cfg_con_bajas("lote_4_mensual"))
    # Stock estándar + un cilindro inerte (BAJA) que ya ocupa el id "NUEVO-001".
    stock = pd.concat([
        _stock_con_bajas(),
        pd.DataFrame([{"ID_Cilindro": "NUEVO-001", "Diámetro_mm": 500.0, "Estado": "Baja",
                       "Jaula_Asignada": None, "Posición": None}]),
    ], ignore_index=True)
    rows = list(_CAMBIOS_BAJAS) + [_CAMBIO_TARDIO]  # entrega dentro de ventana
    t.cargar_datos_desde_dataframes(stock, _df_cambios(rows))
    t.simular(callback_log=None)

    preexistente = t.cilindros["NUEVO-001"]
    assert preexistente.estado == EstadoCilindro.BAJA
    assert preexistente.diametro == 500.0                      # intacto, no pisado
    nuevos = [c for c in t.cilindros.values()
              if c.id.startswith("NUEVO-") and c.id != "NUEVO-001"]
    assert len(nuevos) == 4
    assert "NUEVO-002" in t.cilindros                          # el guard saltó NUEVO-001
    assert len({c.id for c in nuevos}) == 4                    # ids únicos


def test_kpis_exponen_reposicion():
    """calcular_kpis expone entregados/pendientes como métricas escalares."""
    from modelos.kpis import calcular_kpis

    k_in = calcular_kpis(_taller_con_bajas("lote_4_mensual", cambio_tardio=True))
    assert k_in["reposicion_entregados"] == 4
    assert k_in["reposicion_pendientes"] == 0
    assert "reposicion_pendientes" in k_in["metric_order"]

    k_out = calcular_kpis(_taller_con_bajas("lote_4_mensual", cambio_tardio=False))
    assert k_out["reposicion_entregados"] == 0
    assert k_out["reposicion_pendientes"] == 4


# ── 4. Ejecución en paralelo (batch_simular) ─────────────────────────────────

def test_batch_simular_con_reposicion_es_determinista_y_paralelizable():
    """batch_simular corre N sims en paralelo con la reposición activa.

    Fija la invariante de paralelismo: el resultado por corrida es idéntico al
    secuencial (estrategia stateless, estado de corrida por instancia, taller
    picklable) y respeta el orden de la lista de cambios.
    """
    from cli import batch_simular, simular_desde_dataframes

    cfg = _cfg_con_bajas("lote_4_mensual")
    stock = _stock_con_bajas()
    # Dos corridas: una dentro de ventana (con cambio tardío) y otra fuera.
    cambios_in = _df_cambios(list(_CAMBIOS_BAJAS) + [_CAMBIO_TARDIO])
    cambios_out = _df_cambios(list(_CAMBIOS_BAJAS))
    lista = [cambios_in, cambios_out]

    tallers = batch_simular(cfg, stock, lista, max_workers=2)
    assert len(tallers) == 2

    # Mismo orden que la lista de entrada y mismo resultado que el secuencial.
    def _resumen(t):
        return (sorted(c.id for c in t.cilindros.values() if c.id.startswith("NUEVO-")),
                t._repo_pendientes_fuera)

    for taller_par, cambios in zip(tallers, lista):
        taller_seq = simular_desde_dataframes(cfg, stock, cambios, "mayor_diametro")
        assert _resumen(taller_par) == _resumen(taller_seq)

    # La corrida in-window entrega 4; la out-of-window deja 4 pendientes.
    assert _resumen(tallers[0]) == ([f"NUEVO-{i:03d}" for i in range(1, 5)], 0)
    assert _resumen(tallers[1]) == ([], 4)
