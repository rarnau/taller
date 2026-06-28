"""Configuración común de los tests."""
import logging


def pytest_configure(config):
    # Los avisos de carga (cilindros BAJA, hojas viejas ignoradas) se emiten por
    # logging.warning; se silencian para que la salida de los tests sea limpia.
    logging.getLogger("models.workshop").setLevel(logging.ERROR)
