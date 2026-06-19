"""
Genera un dataset para ejercitar la **asignación de jaula por perfil** con
**bandas de diámetro solapadas**.

Escenario (caso base del usuario): jaulas 2 y 3 comparten el perfil "2" con
rangos que se solapan, de modo que un cilindro rectificado puede ser admisible
para varias jaulas y la estrategia de asignación ("jaula más necesitada") debe
elegir el destino. La configuración (rangos + perfiles + estrategia) NO vive en
el Excel; para el test de regresión se arma en ``tests/_escenarios.py``.

Bandas (definidas en el test, aquí solo de referencia):
  Jaula 1: 520 < d ≤ 540  perfil 4
  Jaula 2: 530 < d ≤ 555  perfil 2   ─┐ se solapan (540–555) y comparten perfil
  Jaula 3: 540 < d ≤ 565  perfil 2   ─┘
  Jaula 4: 555 < d ≤ 575  perfil 3
"""
import os
import pandas as pd

SALIDA = os.path.join(os.path.dirname(__file__), "simulacion_caso_perfiles.xlsx")

stock = []


def add(cid, diam, estado, jaula=None, pos=None, perfil=None):
    stock.append({
        "ID_Cilindro": cid, "Diámetro_mm": diam, "Estado": estado,
        "Jaula_Asignada": jaula, "Posición": pos,
        "mm_a_Rectificar": None, "Tipo_Rectificado": None, "Perfil": perfil,
    })


# Jaula 1 (520-540, perfil 4): pareja + CRC + disponible
add("CIL-101", 538.0, "Trabajando", 1, 1)
add("CIL-102", 537.0, "Trabajando", 1, 2)
add("CIL-103", 535.0, "CRC", 1)
add("CIL-104", 534.0, "CRC", 1)
add("CIL-105", 536.0, "Disponible", perfil="4")

# Jaula 2 (530-555, perfil 2): pareja + CRC (diámetros en zona de solape con J3)
add("CIL-201", 550.0, "Trabajando", 2, 1)
add("CIL-202", 549.0, "Trabajando", 2, 2)
add("CIL-203", 545.0, "CRC", 2)
add("CIL-204", 544.0, "CRC", 2)

# Jaula 3 (540-565, perfil 2): pareja + CRC
add("CIL-301", 560.0, "Trabajando", 3, 1)
add("CIL-302", 559.0, "Trabajando", 3, 2)
add("CIL-303", 552.0, "CRC", 3)
add("CIL-304", 551.0, "CRC", 3)

# Jaula 4 (555-575, perfil 3): pareja + CRC
add("CIL-401", 570.0, "Trabajando", 4, 1)
add("CIL-402", 568.0, "Trabajando", 4, 2)
add("CIL-403", 566.0, "CRC", 4)
add("CIL-404", 564.0, "CRC", 4)

stock_inicial = pd.DataFrame(stock)

# Cambios en jaulas 2 y 3 (ambas perfil 2, bandas solapadas): los pares retirados
# se rectifican y la estrategia de asignación decide su jaula destino entre las
# candidatas admisibles por diámetro.
cambios = pd.DataFrame([
    {"ID_Cambio": "P1", "Fecha_Hora": "2026-06-15 06:00:00", "Jaula": 2,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio jaula 2 (perfil 2, solape con jaula 3)"},
    {"ID_Cambio": "P2", "Fecha_Hora": "2026-06-15 08:00:00", "Jaula": 3,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio jaula 3 (perfil 2, solape con jaula 2)"},
])

with pd.ExcelWriter(SALIDA, engine="openpyxl") as xl:
    stock_inicial.to_excel(xl, sheet_name="Stock_Inicial", index=False)
    cambios.to_excel(xl, sheet_name="Programa_Cambios", index=False)

print(f"Generado: {SALIDA}")
