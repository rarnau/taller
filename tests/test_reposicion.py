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

def _taller_con_bajas(estrategia_reposicion: str) -> TallerCilindros:
    """Taller mínimo que muele 4 cilindros por debajo del mínimo (4 BAJAs)."""
    cfg = {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": 1},
        "rangos": [{"jaula": 1, "desde": 575.0, "hasta": 519.0}],
        "maquinas": _MAQ,
        "estrategia_reposicion": estrategia_reposicion,
    }
    t = TallerCilindros()
    t.configurar(cfg)
    # 2 trabajando + 4 disponibles, todos a 522 (un pase de 5 mm ⇒ 517 < 520 ⇒ BAJA).
    stock = pd.DataFrame(
        [{"ID_Cilindro": "W1", "Diámetro_mm": 522.0, "Estado": "Trabajando",
          "Jaula_Asignada": 1, "Posición": 1},
         {"ID_Cilindro": "W2", "Diámetro_mm": 522.0, "Estado": "Trabajando",
          "Jaula_Asignada": 1, "Posición": 2}]
        + [{"ID_Cilindro": f"D{i}", "Diámetro_mm": 522.0, "Estado": "Disponible",
            "Jaula_Asignada": None, "Posición": None} for i in range(4)]
    )
    cambios = pd.DataFrame(
        [{"ID_Cambio": "C1", "Fecha_Hora": datetime(2026, 6, 15, 8, 0), "Jaula": 1,
          "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 5.0, "Observación": ""},
         {"ID_Cambio": "C2", "Fecha_Hora": datetime(2026, 6, 15, 12, 0), "Jaula": 1,
          "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 5.0, "Observación": ""}],
        columns=_COLS_CAMBIOS,
    )
    t.cargar_datos_desde_dataframes(stock, cambios)
    t.simular(callback_log=None)
    return t


def test_reposicion_inyecta_cilindros_nuevos():
    """Con la estrategia de lote, las 4 BAJAs disparan 4 cilindros NUEVO-*."""
    t = _taller_con_bajas("lote_4_mensual")
    bajas = [c for c in t.cilindros.values() if c.estado == EstadoCilindro.BAJA]
    nuevos = [c for c in t.cilindros.values() if c.id.startswith("NUEVO-")]
    assert len(bajas) >= 4
    assert len(nuevos) == 4
    # Llegan al diámetro máximo y reciben un único pase de preparación (el motor
    # eleva un mm 0 al pase mínimo), así que quedan a máximo − _MM_RECTIFICAR_DEFECTO.
    assert all(
        t.diametro_maximo - _MM_RECTIFICAR_DEFECTO - 0.01 <= c.diametro <= t.diametro_maximo
        for c in nuevos)
    # Un snapshot posterior a la llegada cuenta los nuevos como stock.
    assert t.snapshots[-1].tiempo >= datetime(2026, 7, 1, 0, 0)


def test_sin_reposicion_no_inyecta_nada():
    """La estrategia por defecto ('ninguna') no crea cilindros nuevos."""
    t = _taller_con_bajas("ninguna")
    assert [c for c in t.cilindros.values() if c.id.startswith("NUEVO-")] == []


def test_registry_expone_ambas_estrategias():
    assert set(ESTRATEGIAS_REPOSICION) == {"ninguna", "lote_4_mensual"}
