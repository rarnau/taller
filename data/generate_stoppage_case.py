"""
Generates a simulation dataset that drives a stand into the STOPPED condition
(no CRC nor available cylinders to form a pair at a change) and its later
reactivation when the retired pair finishes grinding.

Scenario:
  - Stand 4 (range 561-575) starts with only its working pair, no CRC nor
    available cylinders in its range.
  - A change is scheduled for stand 4: the pair leaves to grinding and, with no
    replacement, the stand becomes STOPPED.
  - The retired pair is ground 0.8 mm (still within 561-575) and on finishing it
    returns as AVAILABLE, reactivating stand 4.

The Excel only holds data (Stock_Inicial + Programa_Cambios). The workshop
configuration (global params, machines and ranges) lives in
config/user_config.json and is managed from the Configuración screen or the CLI.
"""
import os
import pandas as pd

OUTPUT = os.path.join(os.path.dirname(__file__), "simulacion_caso_parada.xlsx")

stock = []

def add(cid, diam, state, stand=None, pos=None, profile=None):
    # "Perfil" is optional: if omitted, the engine derives it from the assigned
    # stand's profile (config/user_config.json). Included here for completeness.
    stock.append({
        "ID_Cilindro": cid, "Diámetro_mm": diam, "Estado": state,
        "Jaula_Asignada": stand, "Posición": pos,
        "mm_a_Rectificar": None, "Tipo_Rectificado": None, "Perfil": profile,
    })

# Stand 1 (520-533): pair + CRC + available -> changes normally
add("CIL-001", 530.0, "Trabajando", 1, 1)
add("CIL-002", 529.0, "Trabajando", 1, 2)
add("CIL-003", 528.0, "CRC", 1)
add("CIL-004", 527.0, "CRC", 1)
add("CIL-005", 531.0, "Disponible")
add("CIL-006", 526.0, "Disponible")

# Stand 2 (533-547): pair + CRC
add("CIL-011", 545.0, "Trabajando", 2, 1)
add("CIL-012", 544.0, "Trabajando", 2, 2)
add("CIL-013", 540.0, "CRC", 2)
add("CIL-014", 539.0, "CRC", 2)

# Stand 3 (547-561): pair + CRC
add("CIL-021", 559.0, "Trabajando", 3, 1)
add("CIL-022", 558.0, "Trabajando", 3, 2)
add("CIL-023", 552.0, "CRC", 3)
add("CIL-024", 551.0, "CRC", 3)

# Stand 4 (561-575): ONLY the working pair, no CRC nor available -> STOPPED
add("CIL-031", 570.0, "Trabajando", 4, 1)
add("CIL-032", 568.0, "Trabajando", 4, 2)

stock_df = pd.DataFrame(stock)

changes_df = pd.DataFrame([
    {"ID_Cambio": "C1", "Fecha_Hora": "2026-06-15 06:00:00", "Jaula": 4,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio jaula 4 sin stock -> PARADA"},
    {"ID_Cambio": "C2", "Fecha_Hora": "2026-06-15 06:30:00", "Jaula": 1,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio normal jaula 1"},
])

with pd.ExcelWriter(OUTPUT, engine="openpyxl") as xl:
    stock_df.to_excel(xl, sheet_name="Stock_Inicial", index=False)
    changes_df.to_excel(xl, sheet_name="Programa_Cambios", index=False)

print(f"Generado: {OUTPUT}")
