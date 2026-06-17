"""Consistencia estructural de los snapshots (los datos que consume la GUI).

El fingerprint de ``test_regresion.py`` no comparaba el *interior* de cada
snapshot; el hash ``snapshots_sha256`` cierra esa brecha en cuanto a valores
exactos, y estos tests la cierran en cuanto a invariantes: verifican que cada
snapshot que recibe la GUI está bien formado y es coherente consigo mismo.

Son los tests que habrían atrapado un error en la optimización del snapshot en
una sola pasada (claves de estado faltantes, listas de detalle descuadradas con
sus conteos, KPIs derivados incoherentes, ceros colados en los SubStock), con
mensajes legibles en lugar de un hash que cambia sin más.
"""
import pytest

from modelos.enums import EstadoCilindro
from _escenarios import ESCENARIOS, ejecutar_escenario

# Campos que la GUI lee de cada Snapshot (vista_realtime / dashboards).
_CAMPOS_GUI = {
    "tiempo", "conteo_por_estado", "cantidad_disponibles", "cantidad_crc_total",
    "cantidad_bajas", "maquinas_ocupadas", "conteo_por_substock",
    "disponibles_por_substock", "crc_por_jaula", "jaulas_paradas",
    "detalle_jaulas", "detalle_crc", "detalle_maquinas",
    "detalle_cola_rectificado", "detalle_enfriando",
}

_ESTADOS = [e.value for e in EstadoCilindro]


@pytest.mark.parametrize("nombre", list(ESCENARIOS.keys()))
def test_snapshots_consistentes(nombre):
    """Cada snapshot del escenario es estructuralmente coherente."""
    taller = ejecutar_escenario(ESCENARIOS[nombre])
    total_cils = len(taller.cilindros)
    assert taller.snapshots, f"{nombre}: no se generaron snapshots"

    for i, sn in enumerate(taller.snapshots):
        ctx = f"{nombre}[snapshot {i}]"

        # 1. Están todos los campos que la GUI consume.
        assert _CAMPOS_GUI.issubset(set(sn.__dict__)), f"{ctx}: faltan campos que la GUI consume"

        # 2. conteo_por_estado lleva TODAS las claves del enum (incluso con 0),
        #    invariante explícito de generar_snapshot que la GUI da por hecho.
        assert set(sn.conteo_por_estado) == set(_ESTADOS), f"{ctx}: claves de conteo_por_estado != estados del enum"

        # 3. La suma del conteo por estado == total de cilindros (ninguno se
        #    pierde ni se cuenta dos veces en la pasada única).
        assert sum(sn.conteo_por_estado.values()) == total_cils, f"{ctx}: el conteo por estado no suma el total de cilindros"

        # 4. Las listas de detalle cuadran con sus conteos por estado.
        assert len(sn.detalle_cola_rectificado) == sn.conteo_por_estado[EstadoCilindro.A_RECTIFICAR.value], f"{ctx}: detalle_cola_rectificado no cuadra con el conteo 'A rectificar'"
        assert len(sn.detalle_enfriando) == sn.conteo_por_estado[EstadoCilindro.ENFRIANDO.value], f"{ctx}: detalle_enfriando no cuadra con el conteo 'Enfriando'"

        # 5. KPIs derivados del conteo, coherentes.
        assert sn.cantidad_disponibles == sn.conteo_por_estado[EstadoCilindro.DISPONIBLE.value], f"{ctx}: cantidad_disponibles incoherente"
        assert sn.cantidad_crc_total == sn.conteo_por_estado[EstadoCilindro.CRC.value], f"{ctx}: cantidad_crc_total incoherente"
        assert sn.cantidad_bajas == sn.conteo_por_estado[EstadoCilindro.BAJA.value], f"{ctx}: cantidad_bajas incoherente"

        # 6. conteo_por_substock: solo estados conocidos, sin ceros colados, y
        #    disponibles_por_substock derivado de forma coherente.
        for ss, conteo in sn.conteo_por_substock.items():
            assert set(conteo).issubset(set(_ESTADOS)), f"{ctx}: estado desconocido en SubStock {ss}"
            assert all(v > 0 for v in conteo.values()), f"{ctx}: SubStock {ss} tiene un estado con conteo 0"
            assert sn.disponibles_por_substock[ss] == conteo.get(EstadoCilindro.DISPONIBLE.value, 0), f"{ctx}: disponibles_por_substock incoherente en SubStock {ss}"

        # 7. El detalle de máquinas cubre exactamente el parque de máquinas.
        assert set(sn.detalle_maquinas) == set(taller.maquinas), f"{ctx}: detalle_maquinas no cubre el parque de máquinas"
