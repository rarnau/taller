"""Reprogramación de cambios tras una PARADA en tiempo laborable de la línea.

Verifica la opción B: con un régimen de turnos de línea (``grilla_cambios``)
configurado, ``_reanudar_linea`` atrasa los CAMBIO pendientes por el tiempo
**laborable** perdido (no de reloj), de modo que (a) ningún cambio queda agendado
fuera de turno y (b) una parada que abarca horas no laborables casi no atrasa el
programa. Con ``grilla_cambios is None`` (24/7) el desplazamiento es de reloj
(idéntico al histórico; cubierto por el golden de los escenarios PARADA).
"""
import itertools
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modelos import turnos as T
from modelos.enums import TipoRectificado
from modelos.eventos import EventoCambio
from modelos.taller import TallerCilindros, _EventoSim

# Régimen de línea L–V (fin de semana sin trabajar).
_REGIMEN_LV = {d: ([True, True, True] if i < 5 else [False, False, False])
               for i, d in enumerate(T.DIAS)}
_GRID_LV = T.expandir(_REGIMEN_LV)


def _cambio(t: datetime, jaula: int = 1) -> _EventoSim:
    ev = EventoCambio(id_evento=f"C{jaula}-{t:%m%d%H%M}", tiempo=t, jaula=jaula,
                      tipo=TipoRectificado.PRODUCCION, mm_a_rectificar=0.8)
    return _EventoSim("CAMBIO", t, ev)


def _taller_para_reanudar(grilla):
    t = TallerCilindros()
    t.grilla_cambios = grilla
    t._seq_cola = itertools.count()
    t.alertas = []
    t._cambios_diferidos = []
    return t


def test_reanudar_con_regimen_reprograma_en_turno_y_tiempo_laborable():
    taller = _taller_para_reanudar(_GRID_LV)
    inicio = datetime(2024, 1, 5, 10, 0)        # viernes 10:00 (operativo)
    taller._linea_parada_desde = inicio
    reanuda = datetime(2024, 1, 8, 10, 0)       # lunes 10:00 (parada abarca el finde)
    wall = reanuda - inicio                      # 72 h de reloj

    # Un cambio diferido (cayó dentro del finde) y otro aún en cola, + un FIN_RECT
    # que NO debe desplazarse.
    dif = _cambio(datetime(2024, 1, 6, 2, 0), jaula=2)   # sábado 02:00
    taller._cambios_diferidos = [dif]
    cola = []
    taller._push_evento(cola, _cambio(datetime(2024, 1, 8, 12, 0), jaula=3))  # lunes 12:00
    fin_rect = _EventoSim("FIN_RECT", datetime(2024, 1, 8, 9, 0), "G36")
    taller._push_evento(cola, fin_rect)

    taller._reanudar_linea(reanuda, log=lambda *_: None, cola=cola)

    eventos = [ev for _, _, ev in sorted(cola)]
    cambios = [e for e in eventos if e.tipo == "CAMBIO"]
    assert len(cambios) == 2                                   # el diferido se reintegró
    # (a) Todo cambio reprogramado cae en una hora OPERATIVA de la línea.
    for e in cambios:
        assert _GRID_LV[e.tiempo.weekday()][e.tiempo.hour], f"{e.tiempo} fuera de turno"
    # (b) El atraso es laborable, no de reloj: el tiempo laborable es <= reloj
    #     siempre, y para al menos un cambio es estrictamente menor (la parada
    #     abarcó el finde no laborable, que no penaliza el programa).
    assert all(e.tiempo <= e.datos.tiempo + wall for e in cambios)
    assert any(e.tiempo < e.datos.tiempo + wall for e in cambios)
    # (c) FIN_RECT no se desplaza (sigue siendo de reloj/exógeno).
    assert any(e.tipo == "FIN_RECT" and e.tiempo == fin_rect.tiempo for e in eventos)
    # (d) Alerta de reanudación: el programa se desplazó MENOS que la parada de reloj.
    msg = next(a.mensaje for a in taller.alertas if "REANUDADA" in a.mensaje)
    assert "REANUDADA" in msg


def test_reanudar_sin_regimen_es_desplazamiento_de_reloj():
    """Con grilla_cambios None el atraso es de reloj puro (comportamiento histórico)."""
    taller = _taller_para_reanudar(None)
    inicio = datetime(2024, 1, 5, 10, 0)
    taller._linea_parada_desde = inicio
    reanuda = datetime(2024, 1, 5, 13, 0)        # 3 h de parada
    retraso = reanuda - inicio
    orig = datetime(2024, 1, 5, 20, 0)
    cola = []
    taller._push_evento(cola, _cambio(orig, jaula=1))
    taller._reanudar_linea(reanuda, log=lambda *_: None, cola=cola)
    eventos = [ev for _, _, ev in sorted(cola)]
    cambio = next(e for e in eventos if e.tipo == "CAMBIO")
    assert cambio.tiempo == orig + retraso       # desplazamiento de reloj exacto
