# Informe del Proyecto: Simulador de Cilindros Pro v4

## 1. Descripción del Sistema Actual

El sistema es una herramienta avanzada de simulación y planificación para talleres de laminación, diseñada para optimizar el ciclo de vida de los cilindros y garantizar la continuidad operativa de las jaulas.

### Funcionalidades Implementadas:
*   **Motor de Simulación Discreta**: Calcula el desgaste, los tiempos de rectificado y los traslados de cilindros entre los estados de: *Trabajando, CRC (Buffer), Disponible, A Rectificar, Rectificando y Baja*.
*   **Gestión de Inventario Inteligente**: Clasifica los cilindros en "SubStocks" basados en rangos de diámetro específicos para cada jaula.
*   **Reproducción en Tiempo Real**: Permite visualizar la evolución del taller segundo a segundo con controles de Reproducción, Pausa y una barra de desplazamiento temporal (Seekbar).
*   **Visualización Gráfica Interactiva**:
    *   Panel dinámico que muestra qué cilindro está en cada jaula y en qué estado se encuentra el buffer CRC.
    *   Indicadores visuales de progreso en las máquinas rectificadoras.
    *   Interactividad: Al hacer clic en cualquier cilindro gráfico, se despliega su detalle técnico e historial.
*   **Análisis y KPIs**:
    *   **Dashboard de Estados**: Gráficos de área apilada para ver la evolución del inventario.
    *   **Cronograma (Gantt)**: Visualización del uso de las máquinas rectificadoras en el tiempo.
    *   **KPIs Críticos**: Seguimiento de alertas, utilización de máquinas, diámetro promedio y tasa de bajas.
*   **Calidad de Software**:
    *   Refactorización completa bajo estándar **PEP8**.
    *   Código documentado íntegramente en español.
    *   Interfaz moderna basada en **CustomTkinter** con soporte para modo oscuro.

---

## 2. Funcionalidades Sugeridas para el Futuro

Para elevar el simulador a un nivel de herramienta de soporte de decisiones (DSS) de clase industrial, sugeriría las siguientes mejoras:

### A. Inteligencia Artificial y Predicción
*   **Predicción de Desgaste**: Implementar un modelo de Machine Learning que aprenda del historial real (Excel) para predecir con mayor exactitud el desgaste por campaña, en lugar de usar valores fijos.
*   **Optimización Automática**: Un asistente que sugiera la mejor "Estrategia de Selección" (mayor diámetro, FIFO, etc.) dependiendo del programa de cambios de la semana para minimizar las alertas críticas.

### B. Mejoras en la Gestión de Datos
*   **Base de Datos Centralizada**: Migrar del archivo Excel a una base de Datos (PostgreSQL o SQLite) para mantener un histórico real de todos los cilindros y no solo de una semana.
*   **Edición Dinámica**: Permitir agregar o quitar máquinas y jaulas directamente desde la interfaz de "Configuración" sin depender de la estructura del archivo Excel.

### C. Visualización Avanzada
*   **Gemelo Digital (3D)**: Evolucionar la vista 2D actual a una representación 3D simplificada para una mejor comprensión visual por parte de los operadores del taller.
*   **Comparativa de Escenarios**: Poder ejecutar dos simulaciones con distintos parámetros y verlas en pantalla dividida para comparar cuál genera menos bajas o menos alertas.

### D. Conectividad y Alertas
*   **Exportación de Reportes en PDF**: Generar automáticamente un informe ejecutivo con los gráficos de la simulación listos para imprimir o enviar por correo.
*   **Integración con Planta**: Conectar el simulador a los sensores de medición de diámetros de la planta para que la "Simulación Inicial" se cargue con datos capturados en tiempo real.
