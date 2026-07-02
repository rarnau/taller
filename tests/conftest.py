"""Configuración común de los tests."""
import json
import logging

import pytest

import config.persistencia as persistencia


def pytest_configure(config):
    # Los avisos de carga (cilindros BAJA, hojas viejas ignoradas) se emiten por
    # logging.warning; se silencian para que la salida de los tests sea limpia.
    logging.getLogger("modelos.taller").setLevel(logging.ERROR)


@pytest.fixture(scope="session", autouse=True)
def _config_pristina(tmp_path_factory):
    """Aísla la suite del ``config/user_config.json`` vivo del repo.

    Los escenarios golden (``_escenarios.py``) y varios unit tests construyen su
    config con ``cargar_config()``, que lee el archivo apuntado por la constante
    module-level ``persistencia.CONFIG_PATH`` **en runtime**. Si el usuario
    personalizó ese JSON (``turnos`` de máquina, ``tasa_falla``,
    ``tiempo_enfriado_h``, ``turnos_cambios``, otra estrategia, ...) el motor
    simularía otro taller y los fingerprints/asserts no coincidirían aunque el
    código no haya cambiado.

    Se parchea la RUTA (no el atributo de función ``cargar_config``, que no
    alcanzaría: los tests la importan con ``from config.persistencia import
    cargar_config`` en varios módulos) hacia un JSON temporal escrito desde
    ``DEFAULTS``. Así toda lectura devuelve los defaults prístinos y cualquier
    ``guardar_config()`` accidental cae en el tmp de la sesión, nunca en el
    archivo del repo.
    """
    ruta = tmp_path_factory.mktemp("config") / "user_config.json"
    ruta.write_text(
        json.dumps(persistencia.DEFAULTS, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    mp = pytest.MonkeyPatch()
    mp.setattr(persistencia, "CONFIG_PATH", str(ruta))
    yield
    mp.undo()
