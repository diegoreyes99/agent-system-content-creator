#!/usr/bin/env python3
"""Rates Estratega grids by hand with the rubric (estratega_rubric.md), in Excel.

Two steps (from agents_dopa_final_project/):
  1) python agents/estratega/rate_estratega.py export agents/estratega/evals/<fecha>
     Creates calificacion.xlsx in that folder: one tab per grid of the sample
     (default 6, --sample N to change it) and a "Calificaciones" tab.
  2) Open the Excel file, review each grid and fill in the scores (1 to 3) in
     "Calificaciones". Save it.
  3) python agents/estratega/rate_estratega.py import agents/estratega/evals/<fecha>
     Reads your scores, saves ratings.csv and logs the means to MLflow (human_*).
No model is called in either step.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
from datetime import date
from pathlib import Path

CRITERIA = [
    ("coherencia", "Coherencia con el negocio", "¿Toda la parrilla empuja la prioridad y la meta del mes?"),
    ("calendario", "Calendario", "¿Eventos y ofertas con anticipación, ritmo parejo, nada fuerte en fechas a evitar?"),
    ("volumen_mezcla", "Volumen y mezcla del embudo", "¿Número de piezas y mezcla de etapas con sentido y bien justificados?"),
    ("temas", "Temas descriptivos y variados", "¿Se entiende cada tema y la parrilla no se siente repetitiva?"),
    ("accionabilidad", "Accionabilidad", "¿El Copywriter y el Diseñador podrían trabajar cada pieza?"),
    ("fidelidad", "Fidelidad al conocimiento de DOPA", "¿Todo dato sale del brief o del conocimiento? ¿Supuestos marcados?"),
]
XLSX_NAME = "calificacion.xlsx"
RATINGS_SHEET = "Calificaciones"
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
STAGES = {"descubrimiento": "Descubrimiento", "consideracion": "Consideración", "conversion": "Conversión",
          "fidelizacion": "Fidelización"}


def brief_dates(brief: str) -> str:
    match = re.search(r"## 4\..*?(?=\n## |\Z)", brief, flags=re.S)
    text = match.group(0) if match else ""
    text = re.sub(r"^## .*\n", "", text).replace("**", "").replace("---", "")
    return re.sub(r"\n{2,}", "\n", text).strip() or "(el brief no tiene sección de fechas)"


def grid_dirs(folder: Path) -> list[Path]:
    if (folder / "output.json").exists():
        return [folder]
    return sorted(d for d in folder.iterdir() if d.is_dir() and (d / "output.json").exists())


def export(folder: Path, sample: int, seed: int) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    dirs = grid_dirs(folder)
    if not dirs:
        raise SystemExit("No hay parrillas con JSON válido en esa carpeta.")
    if len(dirs) > sample:
        dirs = sorted(random.Random(seed).sample(dirs, sample))

    bold, wrap = Font(bold=True), Alignment(wrap_text=True, vertical="top")
    header_fill = PatternFill("solid", fgColor="222222")
    header_font = Font(bold=True, color="FFFFFF")
    label_fill = PatternFill("solid", fgColor="EDEDED")
    wb = Workbook()

    # --- Ratings tab (first, so it opens there) ---
    ws = wb.active
    ws.title = RATINGS_SHEET
    headers = ["Parrilla", "Caso", "Piezas", "Errores del código"] + [label for _, label, _ in CRITERIA] + ["Nota"]
    ws.append(headers)
    ws.append(["", "Pregunta guía →", "", ""] + [q for _, _, q in CRITERIA] + ["(opcional)"])
    for cell in ws[1]:
        cell.font, cell.fill, cell.alignment = header_font, header_fill, wrap
    for cell in ws[2]:
        cell.font, cell.alignment = Font(italic=True, color="666666"), wrap
    scores = DataValidation(type="whole", operator="between", formula1="1", formula2="3", allow_blank=True,
                            showErrorMessage=True, errorTitle="Calificación", error="Escribe 1, 2 o 3.")
    ws.add_data_validation(scores)

    for case_dir in dirs:
        output = json.loads((case_dir / "output.json").read_text(encoding="utf-8"))
        inputs = json.loads((case_dir / "inputs.json").read_text(encoding="utf-8"))
        errors = json.loads((case_dir / "validation.json").read_text(encoding="utf-8")).get("errors", [])
        pieces = sorted(output.get("piezas", []), key=lambda p: str(p.get("fecha_sugerida", "")))
        tab = case_dir.name[:31]

        # --- One tab per grid ---
        g = wb.create_sheet(tab)
        g.append(["", "", "", "", "", "← Regresar a Calificaciones"])
        g["F1"].hyperlink, g["F1"].font = f"#'{RATINGS_SHEET}'!A1", Font(color="0563C1", underline="single")
        context = [
            ("Caso", case_dir.name),
            ("Prioridad del mes", inputs.get("prioridad_principal", "")),
            ("Temas aprobados", "\n".join(f"{t['ref']} ({t.get('origen')}{', ' + t['tipo_fuente'] if t.get('tipo_fuente') else ''}): {t['tema']}"
                                          for t in inputs.get("temas_aprobados", []))),
            ("Fechas del brief", brief_dates(inputs.get("brief_del_mes", ""))),
            ("Estrategia del mes", output.get("estrategia_del_mes", "")),
            ("Criterio de volumen", output.get("criterio_de_volumen", "")),
            ("Mezcla por etapa", ", ".join(f"{STAGES.get(k, k)}: {v}" for k, v in (output.get("mezcla_por_etapa") or {}).items())),
            ("Supuestos", "\n".join(output.get("supuestos") or [])),
            ("Errores del código", "\n".join(errors) or "ninguno"),
        ]
        for label, value in context:
            g.append([label, value])
            row = g.max_row
            g.cell(row, 1).font, g.cell(row, 1).fill = bold, label_fill
            g.merge_cells(start_row=row, start_column=2, end_row=row, end_column=11)
            g.cell(row, 2).alignment = wrap
            g.row_dimensions[row].height = max(18, 15 * (1 + len(str(value)) // 150 + str(value).count("\n")))
        g.append([])
        cols = ["Fecha", "Día", "Formato", "Etapa del embudo", "Origen", "Tema central", "Tema", "Público",
                "Tipo de objetivo", "Objetivo", "Mensaje clave", "Recursos visuales"]
        g.append(cols)
        for cell in g[g.max_row]:
            cell.font, cell.fill = header_font, header_fill
        for p in pieces:
            try:
                day = WEEKDAYS[date.fromisoformat(p["fecha_sugerida"]).weekday()]
            except (KeyError, ValueError):
                day = ""
            origin = {"tema_aprobado": p.get("tema_ref") or "", "green": f"Green: {p.get('green_ref') or ''}"}.get(
                p.get("origen_pieza"), f"Brief: {p.get('elemento_del_brief') or ''}")
            g.append([p.get("fecha_sugerida", ""), day, p.get("formato", ""), STAGES.get(p.get("etapa_embudo"), p.get("etapa_embudo", "")),
                      origin, p.get("tema_central", ""), p.get("tema", ""), p.get("publico", ""), p.get("tipo_objetivo", ""),
                      p.get("objetivo", ""), p.get("mensaje_clave", ""), p.get("recursos_visuales", "")])
            for cell in g[g.max_row]:
                cell.alignment = wrap
        for col, width in zip("ABCDEFGHIJKL", [12, 10, 10, 15, 28, 18, 60, 9, 22, 45, 40, 35]):
            g.column_dimensions[col].width = width

        # --- Row in the ratings tab ---
        ws.append([tab, inputs.get("prioridad_principal", ""), len(pieces), len(errors)] + [None] * len(CRITERIA) + [""])
        row = ws.max_row
        ws.cell(row, 1).hyperlink, ws.cell(row, 1).font = f"#'{tab}'!A1", Font(color="0563C1", underline="single")
        for col in range(5, 5 + len(CRITERIA)):
            scores.add(ws.cell(row, col))
            ws.cell(row, col).fill = PatternFill("solid", fgColor="FFF4CC")

    for col, width in zip("ABCDEFGHIJK", [22, 26, 8, 10, 18, 18, 18, 18, 18, 18, 40]):
        ws.column_dimensions[col].width = width
    ws.row_dimensions[2].height = 60
    ws.freeze_panes = "A3"

    out = folder / XLSX_NAME
    wb.save(out)
    print(f"{len(dirs)} parrillas → {out}")
    print("Ábrelo, revisa cada pestaña y llena las celdas amarillas de 'Calificaciones' (1 a 3). Guarda y corre:")
    print(f"  python agents/estratega/rate_estratega.py import {folder}")


def import_ratings(folder: Path) -> None:
    from openpyxl import load_workbook

    path = folder / XLSX_NAME
    if not path.exists():
        raise SystemExit(f"No existe {path}: corre primero 'export'.")
    ws = load_workbook(path, data_only=True)[RATINGS_SHEET]
    rows, incomplete = [], []
    for values in ws.iter_rows(min_row=3, values_only=True):
        if not values or not values[0]:
            continue
        scores = values[4:4 + len(CRITERIA)]
        if any(s not in (1, 2, 3) for s in scores):
            if any(s is not None for s in scores):
                incomplete.append(values[0])
            continue
        row = {"case": values[0], "n_piezas": values[2]}
        row.update({key: int(s) for (key, _, _), s in zip(CRITERIA, scores)})
        row["nota"] = values[4 + len(CRITERIA)] or ""
        rows.append(row)
    if incomplete:
        print(f"Ojo: estas parrillas tienen calificaciones incompletas y no se cuentan: {incomplete}")
    if not rows:
        raise SystemExit("No hay ninguna parrilla con las 6 calificaciones completas.")

    out = folder / "ratings.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["case", "n_piezas"] + [k for k, _, _ in CRITERIA] + ["nota"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"=== {len(rows)} parrillas calificadas ===")
    for key, label, _ in CRITERIA:
        print(f"  {label:<36}{statistics.mean(r[key] for r in rows):.2f} / 3")
    print(f"Guardado en {out}")

    run_file = folder / "mlflow_run.json"
    if run_file.exists():
        import mlflow

        project_root = Path(__file__).resolve().parents[2]
        mlflow.set_tracking_uri(f"sqlite:///{project_root / 'mlruns' / 'mlflow.db'}")
        client = mlflow.tracking.MlflowClient()
        run_id = json.loads(run_file.read_text(encoding="utf-8"))["run_id"]
        for key, _, _ in CRITERIA:
            client.log_metric(run_id, f"human_{key}_mean", statistics.mean(r[key] for r in rows))
        client.log_metric(run_id, "human_n_rated", float(len(rows)))
        client.log_artifact(run_id, str(path))
        print(f"Registrado en MLflow (corrida {run_id[:8]}…).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["export", "import"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--sample", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.step == "export":
        export(args.folder, args.sample, args.seed)
    else:
        import_ratings(args.folder)


if __name__ == "__main__":
    main()
