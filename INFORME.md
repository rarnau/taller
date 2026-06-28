# Informe del Proyecto: Simulador de Cilindros Pro

## 1. Descripción del Sistema Actual

El sistema es una herramienta avanzada de **simulación de eventos discretos (DES)** y
planificación para talleres de laminación, diseñada para optimizar el ciclo de vida de
los cilindros y garantizar la continuidad operativa de las jaulas.

### Arquitectura

El proyecto separa estrictamente el **modelo** (motor de simulación) de la **interfaz**:

* **Motor (`modelos/`)** — `TallerCilindros` (`modelos/taller.py`) concentra toda la
  lógica de simulación y **no importa nada de la GUI**. Es picklable, sin estado de
  módulo mutable, de modo que puede ejecutarse en procesos paralelos.
* **Configuración persistente (`config/`)** — la configuración estructural del taller
  (parámetros globales, parque de máquinas, rangos de SubStock por jaula, parámetros de
  simulación, generador de cambios) vive en `config/user_config.json`, **separada de los
  datos variables**. El Excel cargado solo trae las hojas `Stock_Inicial` y
  `Programa_Cambios`.
* **GUI (`gui_qt/`)** — front-end en **PySide6 (Qt)**, tema oscuro. Reutiliza dos
  renderizadores Matplotlib puros heredados (`gui/dashboard_*.py`). La simulación corre
  en un **proceso aparte** (`ProcessPoolExecutor`) para no congelar el event loop.
* **CLI (`cli.py`)** — modo headless completo (simular + gestión de configuración +
  generación de cambios), sin dependencias de display; reutilizable de forma programática.

### Funcionalidades Implementadas

* **Motor de Simulación Discreta** con cola de prioridad (`heapq`): modela el ciclo
  *Trabajando → (Enfriando) → A rectificar → Rectificando → Disponible → CRC →
  Trabajando*, además de *Baja*. El paso de enfriado es opt-in (`tiempo_enfriado_h`).
* **Parada de línea (PARADA)**: si una jaula se queda sin stock para formar una pareja
  completa, la línea entera se detiene, los cambios posteriores se difieren y se
  reprograman al reanudar; las máquinas y la reposición del CRC nunca se detienen.
* **Esquema de trabajo por turnos**: cada máquina puede tener un calendario semanal
  (grilla 7×24). El rectificado se interrumpe fuera de turno y retoma al reabrir, sin
  detener la línea de laminación. Ausencia de calendario ⇒ 24/7.
* **Perfiles (bombatura) y asignación de jaula destino**: cada cilindro lleva un perfil
  físico; al iniciar el rectificado el motor decide la jaula destino (pre-filtro por
  diámetro proyectado + estrategia de asignación), y re-perfila el stock no colocable.
* **Estrategias configurables** de selección de cola y de asignación de jaula
  (registros extensibles en `modelos/estrategias.py`).
* **Generador sintético de cambios** (`modelos/generador_cambios.py`): aprende de un
  histórico real (empírico o cadena de Markov por jaula) y genera un `Programa_Cambios`
  reproducible por *seed*, alineado al régimen de turnos del laminador.
* **Ejecución en paralelo**: `cli.batch_simular` corre N simulaciones en procesos,
  compartiendo stock+config+estrategia y variando solo el `Programa_Cambios`.
* **Reproducción y Visualización (GUI Qt)**:
  * **Vista Real**: reproducción snapshot a snapshot con controles Play/Pausa/Stop y
    seekbar; jaulas, CRC, cola de rectificado, enfriamiento y estado de cada máquina
    (rectificando / libre operativa / fuera de turno).
  * **Dashboard**: área apilada de estados, buffer de seguridad, utilización por máquina
    y cronograma (Gantt) con sombreado de turnos cerrados.
  * **Análisis**: mapa de cilindros, distribución de diámetros y evolución por SubStock.
  * **Inventario**, **KPIs**, **Generación**, **Configuración** y **Consola**.
* **KPIs (`modelos/kpis.py`)** — fuente única consumida por GUI y CLI. Descomposición
  tipo OEE de la utilización: *disponible* (tiempo operativo / calendario) × *neta*
  (ocupada / tiempo operativo).
* **Calidad de Software**:
  * Código documentado en español, bajo estándar **PEP8**.
  * **Suite de regresión golden-master** (`tests/`, pytest): fija KPIs, snapshots,
    alertas y estado final por escenario; regenerable a propósito.

---

## 2. Funcionalidades Sugeridas para el Futuro

Para elevar el simulador a una herramienta de soporte de decisiones (DSS) de clase
industrial, se sugieren las siguientes mejoras:

### A. Inteligencia Artificial y Predicción
* **Predicción de Desgaste**: ya existe la base con el generador empírico/Markov; el
  siguiente paso es un modelo de Machine Learning que prediga el desgaste por campaña a
  partir de variables del proceso, no solo del histórico de duraciones.
* **Optimización Automática**: un asistente que, dado un programa de cambios, recorra en
  paralelo (`batch_simular`) las estrategias de selección/asignación y recomiende la que
  minimiza alertas críticas y bajas.
* **Modelado de fallas de máquina**: la grilla de turnos 7×24 ya es el punto de enganche
  para apagar un porcentaje aleatorio de horas y modelar la tasa de falla.

### B. Mejoras en la Gestión de Datos
* **Base de Datos Centralizada**: migrar del Excel a una base (PostgreSQL/SQLite) para
  mantener un histórico real de todos los cilindros.
* **Edición Dinámica** *(implementado)*: el Excel solo contiene datos variables
  (`Stock_Inicial` y `Programa_Cambios`); la configuración del taller es persistente en
  `config/user_config.json` y se edita desde la pestaña **Configuración** o el CLI
  (`python cli.py config ...`).

### C. Visualización Avanzada
* **Gemelo Digital (3D)**: evolucionar la vista 2D a una representación 3D simplificada.
* **Comparativa de Escenarios**: ejecutar dos simulaciones con parámetros distintos y
  verlas en pantalla dividida (apoyándose en `batch_simular`).

### D. Conectividad y Alertas
* **Exportación de Reportes en PDF**: informe ejecutivo con los gráficos listos para
  imprimir o enviar por correo.
* **Integración con Planta**: alimentar el `Stock_Inicial` con datos capturados en
  tiempo real desde los sensores de medición de diámetros.
