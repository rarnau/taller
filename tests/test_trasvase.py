"""Trasvase proactivo de cilindros entre jaulas (cascada superior → inferior).

Cuando el stock útil de una jaula (perfil incluido) cae bajo ``trasvase_umbral``,
la estrategia "cascada_umbral" re-perfila Disponibles de bandas SUPERIORES hacia
ella (pase de producción de 0.8 mm que le talla el perfil receptor) hasta
dejarla en ``trasvase_objetivo`` — o lo que se pueda (mejor esfuerzo). Reglas
fijadas por estos tests: dirección solo descendente, piso del donante = umbral,
efecto cascada en una misma ronda (J3 rellena a J2 que donó a J1), y la
estrategia por defecto ("ninguno") no toca nada (golden master intacto).
"""
from datetime import datetime

import pandas as pd
import pytest

from config.persistencia import (
    cargar_config,
    obtener_estrategia_trasvase,
    obtener_trasvase_objetivo,
    obtener_trasvase_umbral,
    set_sim,
)
from modelos.enums import EstadoCilindro
from modelos.estrategias import (
    ESTRATEGIAS_TRASVASE,
    FAMILIAS_ESTRATEGIA,
    MM_REPERFILADO,
)
from modelos.taller import TallerCilindros

_COLS_CAMBIOS = ["ID_Cambio", "Fecha_Hora", "Jaula", "Tipo_Rectificado",
                 "mm_a_Rectificar", "Observación"]
_MAQ = [{"nombre": "G", "prioridad": "produccion",
         "tasas": {"produccion": {"mm": 1.0, "tiempo_min": 10.0},
                   "desbaste": {"mm": 1.0, "tiempo_min": 10.0}}}]


def _df_cambios(rows):
    return pd.DataFrame(rows, columns=_COLS_CAMBIOS)


def _cambio(jaula: int, hora=datetime(2026, 6, 15, 8, 0), mm=1.0):
    return {"ID_Cambio": f"C-J{jaula}", "Fecha_Hora": hora, "Jaula": jaula,
            "Tipo_Rectificado": "produccion", "mm_a_Rectificar": mm,
            "Observación": ""}


def _fila(cid, diam, estado="Disponible", jaula=None, pos=None, perfil=None):
    return {"ID_Cilindro": cid, "Diámetro_mm": diam, "Estado": estado,
            "Jaula_Asignada": jaula, "Posición": pos, "Perfil": perfil}


def _cfg_base(rangos, jaulas, *, estrategia="cascada_umbral", umbral=3, objetivo=4):
    return {
        "config_global": {"diametro_maximo": 575.0, "diametro_minimo": 520.0,
                          "tiempo_traslado_crc_min": 10.0, "cantidad_jaulas": jaulas},
        "rangos": rangos,
        "maquinas": _MAQ,
        "estrategia_trasvase": estrategia,
        "trasvase_umbral": umbral,
        "trasvase_objetivo": objetivo,
    }


def _simular(cfg, stock_rows, cambios_rows) -> TallerCilindros:
    t = TallerCilindros()
    t.configurar(cfg)
    t.cargar_datos_desde_dataframes(pd.DataFrame(stock_rows), _df_cambios(cambios_rows))
    t.simular(callback_log=None)
    return t


# ── Escenario base: 2 jaulas contiguas con perfiles distintos ────────────────
#
# J1 (520-540, perfil A) queda sin stock útil tras su cambio; J2 (540-575,
# perfil B) tiene 4 Disponibles al borde inferior de su banda (Ø 540.2-540.5,
# a un pase de 0.8 mm de entrar en la banda de J1).

_RANGOS_2J = [
    {"jaula": 1, "desde": 540.0, "hasta": 520.0, "perfil": "A"},
    {"jaula": 2, "desde": 575.0, "hasta": 540.0, "perfil": "B"},
]


def _stock_2j(n_disponibles_b=4):
    return (
        [_fila("W1", 530.0, "Trabajando", 1, 1), _fila("W2", 530.0, "Trabajando", 1, 2),
         _fila("W3", 550.0, "Trabajando", 2, 1), _fila("W4", 550.0, "Trabajando", 2, 2)]
        + [_fila(f"D{i}", 540.5 - i * 0.1, perfil="B") for i in range(n_disponibles_b)]
    )


# ── 1. Métrica de stock útil ─────────────────────────────────────────────────

def test_stock_util_cuenta_por_perfil_y_destino():
    """El stock útil es perfil-aware: los Disponibles B no cuentan para J1."""
    t = TallerCilindros()
    t.configurar(_cfg_base(_RANGOS_2J, 2))
    t.cargar_datos_desde_dataframes(
        pd.DataFrame(_stock_2j()), _df_cambios([_cambio(1)]))
    assert t.stock_util_por_jaula() == {1: 2, 2: 6}

    # Un Disponible reservado (jaula_destino) cuenta solo en su destino.
    t.cilindros["D0"].jaula_destino = 1
    assert t.stock_util_por_jaula() == {1: 3, 2: 5}


# ── 2. Trasvase simple + mejor esfuerzo + piso del donante ──────────────────

def test_trasvase_reperfila_hacia_jaula_bajo_umbral():
    """J1 pierde su pareja en el cambio ⇒ 3 trasvases desde J2 (el 4º violaría
    el piso del donante) y la jaula se reactiva con el nuevo perfil A."""
    t = _simular(_cfg_base(_RANGOS_2J, 2), _stock_2j(), [_cambio(1)])

    assert t._trasvases == 3
    trasvasados = [c for c in t.cilindros.values()
                   if any("Trasvase" in h["evento"] for h in c.historial)]
    assert len(trasvasados) == 3
    # El pase les talló el perfil de la jaula receptora y entran en su banda.
    assert all(c.perfil == "A" for c in trasvasados)
    assert all(520.0 < c.diametro <= 540.0 for c in trasvasados)
    # La jaula parada se reactivó con el stock trasvasado.
    assert not t.jaulas[1].parada
    assert any(a.mensaje.startswith("TRASVASE") for a in t.alertas)
    assert any("Trasvase" in linea for linea in t.log_simulacion)
    # Piso del donante: J2 conserva al menos el umbral de stock útil.
    assert t.stock_util_por_jaula()[2] >= 3


def test_donante_sin_holgura_no_dona():
    """Con J2 exactamente en el umbral (2 trabajando + 1 disponible), donar la
    dejaría por debajo: no hay trasvase y el Disponible B queda intacto (J1 se
    reactiva recién cuando sus propios retirados vuelven del rectificado)."""
    t = _simular(_cfg_base(_RANGOS_2J, 2), _stock_2j(n_disponibles_b=1), [_cambio(1)])
    assert t._trasvases == 0
    assert t.cilindros["D0"].perfil == "B"
    assert t.cilindros["D0"].diametro == 540.5  # sin pase de re-perfilado
    # Hubo un episodio de PARADA (nadie pudo rearmar la jaula al instante).
    assert any(1 in s.jaulas_paradas for s in t.snapshots)


def test_estrategia_ninguno_no_trasvasa():
    """La estrategia por defecto no mueve nada (comportamiento histórico)."""
    t = _simular(_cfg_base(_RANGOS_2J, 2, estrategia="ninguno"),
                 _stock_2j(), [_cambio(1)])
    assert t._trasvases == 0
    assert not any(a.mensaje.startswith("TRASVASE") for a in t.alertas)
    # Los Disponibles B quedan intactos: mismo perfil y diámetro de carga.
    assert all(t.cilindros[f"D{i}"].perfil == "B" for i in range(4))
    assert all(t.cilindros[f"D{i}"].diametro == pytest.approx(540.5 - i * 0.1)
               for i in range(4))


# ── 3. Cascada: J2 dona a J1 y J3 rellena a J2 en la misma ronda ─────────────

def test_cascada_rellena_al_donante_desde_su_superior():
    rangos = [
        {"jaula": 1, "desde": 540.0, "hasta": 520.0, "perfil": "A"},
        {"jaula": 2, "desde": 558.0, "hasta": 540.0, "perfil": "B"},
        {"jaula": 3, "desde": 575.0, "hasta": 558.0, "perfil": "C"},
    ]
    stock = [
        _fila("W1", 530.0, "Trabajando", 1, 1), _fila("W2", 530.0, "Trabajando", 1, 2),
        _fila("W3", 550.0, "Trabajando", 2, 1), _fila("W4", 550.0, "Trabajando", 2, 2),
        _fila("W5", 565.0, "Trabajando", 3, 1), _fila("W6", 565.0, "Trabajando", 3, 2),
        _fila("DB1", 540.5, perfil="B"),   # único candidato J2 → J1
        _fila("DC1", 558.5, perfil="C"),   # candidatos J3 → J2
        _fila("DC2", 558.4, perfil="C"),
        _fila("DC3", 558.3, perfil="C"),
    ]
    t = _simular(_cfg_base(rangos, 3, umbral=2, objetivo=3), stock, [_cambio(1)])

    assert t._trasvases == 2
    # DB1 bajó a la banda de J1 con su perfil; al donar, J2 quedó bajo el
    # objetivo y la cascada la rellenó con DC1 (perfil B) desde J3.
    assert t.cilindros["DB1"].perfil == "A"
    assert 520.0 < t.cilindros["DB1"].diametro <= 540.0
    assert t.cilindros["DC1"].perfil == "B"
    assert 540.0 < t.cilindros["DC1"].diametro <= 558.0
    # DC2/DC3 no se tocaron (J3 quedó en 4 ≥ objetivo tras donar una vez).
    assert t.cilindros["DC2"].perfil == "C"
    assert t.cilindros["DC3"].perfil == "C"


# ── 4. Dirección: nunca de bandas inferiores a superiores ────────────────────

def test_jaula_superior_no_roba_de_inferiores():
    """Con bandas solapadas, un Disponible de la jaula INFERIOR cuyo diámetro
    entra (post-pase) en la banda superior NO se trasvasa hacia arriba."""
    rangos = [
        {"jaula": 1, "desde": 560.0, "hasta": 520.0, "perfil": "A"},
        {"jaula": 2, "desde": 575.0, "hasta": 558.0, "perfil": "B"},  # solape 558-560
    ]
    stock = [
        _fila("W1", 530.0, "Trabajando", 1, 1), _fila("W2", 530.0, "Trabajando", 1, 2),
        _fila("W3", 565.0, "Trabajando", 2, 1), _fila("W4", 565.0, "Trabajando", 2, 2),
        # Disponibles de J1 en la zona de solape: post-pase entrarían en J2,
        # pero su dueña (J1) es inferior ⇒ dirección prohibida.
        _fila("DA1", 559.5, perfil="A"),
        _fila("DA2", 559.6, perfil="A"),
        _fila("DA3", 559.7, perfil="A"),
    ]
    t = _simular(_cfg_base(rangos, 2, umbral=2, objetivo=3), stock, [_cambio(2)])
    assert t._trasvases == 0
    assert all(t.cilindros[f"DA{i}"].perfil == "A" for i in (1, 2, 3))


# ── 5. Donantes reservados y reasignación sin pase ──────────────────────────
#
# Tras un rectificado, TODO cilindro queda Disponible con jaula_destino
# reservado (solo se limpia al instalarse). El trasvase debe poder donar
# también ese stock reservado — su "dueña" es la jaula de la reserva — o el
# pool de candidatos queda vacío a mitad de corrida.


def _simular_con_reservas(cfg, stock_rows, cambios_rows, reservas):
    """Como _simular pero estampando jaula_destino antes de correr (estado
    idéntico al de un Disponible recién salido del rectificado)."""
    t = TallerCilindros()
    t.configurar(cfg)
    t.cargar_datos_desde_dataframes(pd.DataFrame(stock_rows), _df_cambios(cambios_rows))
    for cid, j in reservas.items():
        t.cilindros[cid].jaula_destino = j
    t.simular(callback_log=None)
    return t


def test_donante_reservado_se_reperfila():
    """Disponibles B reservados a J2 (caso normal post-rectificado) siguen
    siendo donables hacia J1: la reserva no los saca del pool del trasvase."""
    t = _simular_con_reservas(
        _cfg_base(_RANGOS_2J, 2), _stock_2j(),
        [_cambio(1)], reservas={f"D{i}": 2 for i in range(4)})
    assert t._trasvases == 3  # el 4º violaría el piso del donante (J2)
    trasvasados = [c for c in t.cilindros.values()
                   if any("Trasvase" in h["evento"] for h in c.historial)]
    assert all(c.perfil == "A" for c in trasvasados)
    assert not t.jaulas[1].parada


def test_reasignacion_sin_pase_cuando_perfil_y_banda_coinciden():
    """Solape con MISMO perfil: el trasvase reasigna la reserva (0 mm, sin
    rectificado) y la jaula se reactiva en el mismo instante del cambio."""
    rangos = [
        {"jaula": 1, "desde": 552.0, "hasta": 520.0, "perfil": "A"},
        {"jaula": 2, "desde": 575.0, "hasta": 548.0, "perfil": "A"},  # solape 548-552
    ]
    stock = [
        _fila("W1", 530.0, "Trabajando", 1, 1), _fila("W2", 530.0, "Trabajando", 1, 2),
        _fila("W3", 565.0, "Trabajando", 2, 1), _fila("W4", 565.0, "Trabajando", 2, 2),
        # En la zona de solape, perfil A: entran en J1 tal cual, pero la
        # reserva a J2 los retiene.
        _fila("DR1", 550.0, perfil="A"), _fila("DR2", 550.1, perfil="A"),
        _fila("DR3", 550.2, perfil="A"), _fila("DR4", 550.3, perfil="A"),
    ]
    t = _simular_con_reservas(
        _cfg_base(rangos, 2, umbral=2, objetivo=3), stock,
        [_cambio(1)], reservas={f"DR{i}": 2 for i in (1, 2, 3, 4)})

    assert t._trasvases == 3  # déficit 3 (objetivo 3, usable 0); piso J2 ok
    reasignados = [c for c in t.cilindros.values()
                   if any("reasignado" in h["evento"] for h in c.historial)]
    assert len(reasignados) == 3
    # Sin pase: el diámetro NO cambió en la reasignación (pudo cambiar después
    # solo si la jaula lo retiró en otro cambio — acá no hay más cambios de J1).
    assert all(c.diametro in (550.0, 550.1, 550.2, 550.3) for c in reasignados)
    assert any("sin pase" in a.mensaje for a in t.alertas)
    # La jaula se reactivó en el instante del cambio (reactivación inmediata
    # tras la reasignación, sin esperar a un FIN_RECT).
    assert not t.jaulas[1].parada
    assert any("reactivada tras 0" in a.mensaje for a in t.alertas)


def test_barras_disponibles_sin_duplicados_con_solape():
    """Con bandas solapadas (incl. dos jaulas con banda idéntica), la suma de
    disponibles_por_substock coincide con el total de Disponibles en TODOS los
    snapshots (atribución única: reserva o banda de menor jaula)."""
    rangos = [
        {"jaula": 1, "desde": 547.0, "hasta": 520.0, "perfil": "4"},
        {"jaula": 2, "desde": 563.0, "hasta": 539.0, "perfil": "2"},
        {"jaula": 3, "desde": 575.0, "hasta": 551.0, "perfil": "2"},
        {"jaula": 4, "desde": 575.0, "hasta": 551.0, "perfil": "3"},  # = banda J3
    ]
    stock = [_fila(f"W{j}{p}", d, "Trabajando", j, p)
             for j, d in ((1, 545.0), (2, 555.0), (3, 570.0), (4, 570.0))
             for p in (1, 2)] + [
        _fila("DA", 545.0, perfil="4"), _fila("DB", 545.0, perfil="2"),  # solape J1/J2
        _fila("DC", 555.0, perfil="2"), _fila("DD", 555.0, perfil="3"),  # solape J2/J3/J4
        _fila("DE", 570.0, perfil="2"), _fila("DF", 570.0, perfil="3"),  # banda J3=J4
    ]
    t = _simular(_cfg_base(rangos, 4, umbral=1, objetivo=2), stock, [_cambio(1)])
    for i, sn in enumerate(t.snapshots):
        assert sum(sn.disponibles_por_substock.values()) == sn.cantidad_disponibles, \
            f"snapshot {i}: las barras duplican Disponibles"


# ── 6. KPI y configuración ───────────────────────────────────────────────────

def test_kpi_trasvases_expuesto():
    from modelos.kpis import calcular_kpis

    k = calcular_kpis(_simular(_cfg_base(_RANGOS_2J, 2), _stock_2j(), [_cambio(1)]))
    assert k["trasvases"] == 3
    assert "trasvases" in k["metric_order"]

    k0 = calcular_kpis(_simular(_cfg_base(_RANGOS_2J, 2, estrategia="ninguno"),
                                _stock_2j(), [_cambio(1)]))
    assert k0["trasvases"] == 0


def test_registry_y_familia():
    assert set(ESTRATEGIAS_TRASVASE) == {"ninguno", "cascada_umbral"}
    assert any(f.clave_cfg == "estrategia_trasvase" for f in FAMILIAS_ESTRATEGIA)
    assert MM_REPERFILADO == 0.8


def test_config_roundtrip_y_defaults():
    cfg = cargar_config()
    assert obtener_estrategia_trasvase(cfg) == "ninguno"
    assert obtener_trasvase_umbral(cfg) == 8
    assert obtener_trasvase_objetivo(cfg) == 12

    set_sim(cfg, trasvase_umbral=5, trasvase_objetivo=9,
            estrategia_trasvase="cascada_umbral")
    assert obtener_trasvase_umbral(cfg) == 5
    assert obtener_trasvase_objetivo(cfg) == 9
    assert obtener_estrategia_trasvase(cfg) == "cascada_umbral"

    t = TallerCilindros()
    t.configurar(cfg)
    assert (t.trasvase_umbral, t.trasvase_objetivo) == (5, 9)
    assert t.estrategia_trasvase == "cascada_umbral"

    with pytest.raises(ValueError):
        set_sim(cfg, trasvase_umbral=0)
    with pytest.raises(ValueError):
        set_sim(cfg, trasvase_objetivo=-1)
