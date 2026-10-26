#!/usr/bin/env python3
"""Checks the Google Sheets connection with two sample pieces.

Usage (from agents_dopa_final_project/, with the venv active):
  python agents/shared/check_sheet.py           # writes the test tab
  python agents/shared/check_sheet.py --read    # reads Dani's decisions back
  python agents/shared/check_sheet.py --delete  # removes the test tab
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parrilla_sheet as ps  # noqa: E402

TEST_TAB = "prueba-conexion"
SAMPLE_PIECES = [
    {"id": "2026-11-P01", "fecha_sugerida": "2026-11-03", "canal": "instagram", "formato": "carrusel",
     "tema": "Qué es el entrenamiento híbrido: un carrusel que explica, para quien nunca lo ha probado, cómo se "
             "combinan fuerza y resistencia en una misma sesión y por qué da mejores resultados que hacer solo una",
     "etapa_embudo": "descubrimiento", "tipo_objetivo": "Reconocimiento de marca",
     "objetivo": "Que gente que no conoce DOPA descubra el entrenamiento híbrido y guarde o comparta el carrusel",
     "mensaje_clave": "Fuerza y resistencia en un mismo plan", "estado": "pendiente_aprobacion"},
    {"id": "2026-11-P02", "fecha_sugerida": "2026-11-05", "canal": "instagram", "formato": "post",
     "tema": "Clase de prueba del Reto 21 días: post que invita a principiantes a reservar su primera clase, "
             "respondiendo la objeción de 'necesito estar en forma antes de entrar'",
     "etapa_embudo": "conversion", "tipo_objetivo": "Generación de leads",
     "objetivo": "Que principiantes escriban por DM o WhatsApp para reservar su clase de prueba del Reto 21 días",
     "mensaje_clave": "Empiezas como estás; el reto se adapta a tu nivel", "estado": "pendiente_aprobacion"},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--read", action="store_true", help="read the decisions from the test tab")
    group.add_argument("--delete", action="store_true", help="delete the test tab")
    args = parser.parse_args()

    try:
        if args.read:
            decisions = ps.read_decisions(TEST_TAB)
            for d in decisions:
                print(f"  {d['id']}: {d['estado']}" + (f" · {d['comentario']}" if d["comentario"] else ""))
            summary = ps.summarize_decisions(decisions)
            print(f"\n  ¿Puede avanzar el ciclo? {'sí' if summary['listo'] else 'no'} "
                  f"({', '.join(f'{s}: {summary[s]}' for s in ps.STATUS_OPTIONS)})")
        elif args.delete:
            spreadsheet = ps.open_spreadsheet()
            spreadsheet.del_worksheet(spreadsheet.worksheet(TEST_TAB))
            print(f"Pestaña '{TEST_TAB}' borrada.")
        else:
            url = ps.write_parrilla(TEST_TAB, SAMPLE_PIECES, replace=True)
            print("Conexión correcta: se escribió la pestaña de prueba.")
            print(f"Ábrela aquí: {url}")
            print("Cambia el Estado de una pieza (y escribe un comentario), y luego corre con --read.")
    except ps.SheetConfigError as exc:
        sys.exit(f"Error de configuración: {exc}")


if __name__ == "__main__":
    main()
