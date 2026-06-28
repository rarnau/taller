"""
Generates a dataset to exercise **stand assignment by profile** with
**overlapping diameter bands**.

Scenario (user base case): stands 2 and 3 share profile "2" with overlapping
ranges, so a ground cylinder can be admissible for several stands and the
assignment strategy ("most needed stand") must pick the destination. The
configuration (ranges + profiles + strategy) does NOT live in the Excel; for the
regression test it is built in ``tests/_escenarios.py``.

Bands (defined in the test, here only for reference):
  Stand 1: 520 < d ≤ 540  profile 4
  Stand 2: 530 < d ≤ 555  profile 2   ─┐ overlap (540–555) and share profile
  Stand 3: 540 < d ≤ 565  profile 2   ─┘
  Stand 4: 555 < d ≤ 575  profile 3
"""
import os
import pandas as pd

OUTPUT = os.path.join(os.path.dirname(__file__), "simulacion_caso_perfiles.xlsx")

stock = []


def add(cid, diam, state, stand=None, pos=None, profile=None):
    stock.append({
        "ID_Cilindro": cid, "Diámetro_mm": diam, "Estado": state,
        "Jaula_Asignada": stand, "Posición": pos,
        "mm_a_Rectificar": None, "Tipo_Rectificado": None, "Perfil": profile,
    })


# Stand 1 (520-540, profile 4): pair + CRC + available
add("CIL-101", 538.0, "Trabajando", 1, 1)
add("CIL-102", 537.0, "Trabajando", 1, 2)
add("CIL-103", 535.0, "CRC", 1)
add("CIL-104", 534.0, "CRC", 1)
add("CIL-105", 536.0, "Disponible", profile="4")

# Stand 2 (530-555, profile 2): pair + CRC (diameters in the overlap zone with S3)
add("CIL-201", 550.0, "Trabajando", 2, 1)
add("CIL-202", 549.0, "Trabajando", 2, 2)
add("CIL-203", 545.0, "CRC", 2)
add("CIL-204", 544.0, "CRC", 2)

# Stand 3 (540-565, profile 2): pair + CRC
add("CIL-301", 560.0, "Trabajando", 3, 1)
add("CIL-302", 559.0, "Trabajando", 3, 2)
add("CIL-303", 552.0, "CRC", 3)
add("CIL-304", 551.0, "CRC", 3)

# Stand 4 (555-575, profile 3): pair + CRC
add("CIL-401", 570.0, "Trabajando", 4, 1)
add("CIL-402", 568.0, "Trabajando", 4, 2)
add("CIL-403", 566.0, "CRC", 4)
add("CIL-404", 564.0, "CRC", 4)

stock_df = pd.DataFrame(stock)

# Changes in stands 2 and 3 (both profile 2, overlapping bands): the retired
# pairs are ground and the assignment strategy decides their target stand among
# the diameter-admissible candidates.
changes_df = pd.DataFrame([
    {"ID_Cambio": "P1", "Fecha_Hora": "2026-06-15 06:00:00", "Jaula": 2,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio jaula 2 (perfil 2, solape con jaula 3)"},
    {"ID_Cambio": "P2", "Fecha_Hora": "2026-06-15 08:00:00", "Jaula": 3,
     "Tipo_Rectificado": "produccion", "mm_a_Rectificar": 0.8,
     "Observación": "Cambio jaula 3 (perfil 2, solape con jaula 2)"},
])

with pd.ExcelWriter(OUTPUT, engine="openpyxl") as xl:
    stock_df.to_excel(xl, sheet_name="Stock_Inicial", index=False)
    changes_df.to_excel(xl, sheet_name="Programa_Cambios", index=False)

print(f"Generado: {OUTPUT}")
