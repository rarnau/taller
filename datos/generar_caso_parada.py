"""
Genera un dataset de simulación que lleva a una jaula a la condición PARADA
(sin CRC ni disponibles para formar pareja en un cambio) y su posterior
reactivación cuando el par retirado termina de rectificarse.

Escenario:
  - Jaula 4 (rango 561-575) arranca solo con su pareja de trabajo, sin CRC
    ni disponibles en su rango.
  - Se programa un cambio para la jaula 4: la pareja sale a rectificado y,
    al no haber reemplazo, la jaula queda PARADA.
  - El par retirado se rectifica 0.8 mm (sigue dentro de 561-575) y al
    terminar vuelve como DISPONIBLE, reactivando la jaula 4.

El Excel solo contiene datos (Stock_Inicial + Programa_Cambios). La
configuración del taller (parámetros globales, máquinas y rangos) vive en
config/user_config.json y se gestiona desde la pantalla Configuración o el CLI.
"""
import os

import pandas as pd

SALIDA = os.path.join(os.path.dirname(__file__), "simulacion_caso_parada.xlsx")

stock = []

def add(cid, diam, estado, jaula=None, pos=None, perfil=None):
    # "Perfil" es opcional: si se omite, el motor lo deriva del perfil de la
    # jaula asignada (config/user_config.json). Se incluye aquí por completitud.
    stock.append({
        "ID_Cilindro": cid, "Diámetro_mm": diam, "Estado": estado,
        "Jaula_Asignada": jaula, "Posición": pos,
        "mm_a_Rectificar": None, "Tipo_Rectificado": None, "Perfil": perfil,
    })

# Jaula 1 (520-533): pareja + CRC + disponibles -> cambia normal
add("CIL-001", 530.0, "Trabajando", 1, 1)
add("CIL-002", 529.0, "Trabajando", 1, 2)
add("CIL-003", 528.0, "CRC", 1)
add("CIL-004", 527.0, "CRC", 1)
add("CIL-005", 531.0, "Disponible")
add("CIL-006", 526.0, "Disponible")

# Jaula 2 (533-547): pareja + CRC
add("CIL-011", 545.0, "Trabajando", 2, 1)
add("CIL-012", 544.0, "Trabajando", 2, 2)
add("CIL-013", 540.0, "CRC", 2)
add("CIL-014", 539.0, "CRC", 2)

# Jaula 3 (547-561): pareja + CRC
add("CIL-021", 559.0, "Trabajando", 3, 1)
add("CIL-022", 558.0, "Trabajando", 3, 2)
add("CIL-023", 552.0, "CRC", 3)
add("CIL-024", 551.0, "CRC", 3)

# Jaula 4 (561-575): SOLO la pareja de trabajo, sin CRC ni disponibles -> PARADA
add("CIL-031", 570.0, "Trabajando", 4, 1)
add("CIL-032", 568.0, "Trabajando", 4, 2)

stock_inicial = pd.DataFrame(stock)

cambios = pd.DataFrame([
    {"ID_Cambio": "C1", "Fecha_Hora": "2026-06-15 06:00:00", "Jaula": 4,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio jaula 4 sin stock -> PARADA"},
    {"ID_Cambio": "C2", "Fecha_Hora": "2026-06-15 06:30:00", "Jaula": 1,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio normal jaula 1"},
])

with pd.ExcelWriter(SALIDA, engine="openpyxl") as xl:
    stock_inicial.to_excel(xl, sheet_name="Stock_Inicial", index=False)
    cambios.to_excel(xl, sheet_name="Programa_Cambios", index=False)

print(f"Generado: {SALIDA}")
