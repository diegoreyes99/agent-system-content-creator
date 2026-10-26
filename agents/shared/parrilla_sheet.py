"""Content grid ("parrilla") in Google Sheets: the view Dani uses to approve.

The JSON produced by the agents is the source of truth (validated, chained
between agents). This module only renders it as one tab per cycle ("2026-11")
inside the shared "Parrilla DOPA" spreadsheet, and reads back Dani's decisions.

Approval is explicit and per piece: the "Estado" column (dropdown) is the
approval; "Comentarios de Dani" only explains what to change.

The service account cannot create files (it has no Drive storage), so the
spreadsheet is created by a person and shared with it as Editor; this module
only adds and edits tabs inside it.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_KEY_FILE = "~/.config/dopa/google_service_account.json"

# Columns of the grid, in order, and which agent fills each one.
COLUMNS = [
    "ID",                   # Estratega
    "Fecha de publicación", # Estratega
    "Día de publicación",   # computed from the publication date
    "Canal",                # Estratega (always Instagram for now)
    "Formato",              # Estratega
    "Tema",                 # Estratega (descriptive: what the piece covers and from which angle)
    "Etapa del embudo",     # Estratega: descubrimiento, consideración, conversión o fidelización
    "Objetivo",             # Estratega: "<objective type> — <specific, measurable objective>"
    "Mensaje clave",        # Estratega
    "Recursos visuales",    # Estratega: which photos or graphics the piece uses
    "Copy in",              # Copywriter (text on the image; may be empty)
    "Copy out",             # Copywriter (caption; always has text)
    "Diseño",               # Diseñador
    "Estado",               # Dani (dropdown)
    "Comentarios de Dani",  # Dani
]
COLUMN_WIDTHS = [90, 110, 100, 85, 95, 340, 130, 280, 260, 220, 220, 320, 200, 115, 260]

STATUS_PENDING, STATUS_APPROVED, STATUS_CHANGES, STATUS_DISCARDED = "Pendiente", "Aprobado", "Cambios", "Descartado"
STATUS_OPTIONS = [STATUS_PENDING, STATUS_APPROVED, STATUS_CHANGES, STATUS_DISCARDED]
STATUS_COLORS = {  # light background per status, so Dani sees progress at a glance
    STATUS_PENDING: (1.00, 0.95, 0.80),
    STATUS_APPROVED: (0.85, 0.94, 0.83),
    STATUS_CHANGES: (0.99, 0.88, 0.80),
    STATUS_DISCARDED: (0.90, 0.90, 0.90),
}
# Funnel stage of each piece: JSON value -> label shown to Dani.
FUNNEL_STAGES = {"descubrimiento": "Descubrimiento", "consideracion": "Consideración",
                 "conversion": "Conversión", "fidelizacion": "Fidelización"}

WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Agent-side status values mapped to the sheet's dropdown.
_STATUS_FROM_JSON = {"pendiente_aprobacion": STATUS_PENDING, "aprobado": STATUS_APPROVED,
                     "cambios": STATUS_CHANGES, "descartado": STATUS_DISCARDED}


class SheetConfigError(RuntimeError):
    """Missing or wrong configuration (key file, spreadsheet id, sharing)."""


def _key_file() -> Path:
    return Path(os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_KEY_FILE)).expanduser()


def open_spreadsheet():
    """Opens the "Parrilla DOPA" spreadsheet with the service account."""
    try:
        import gspread
    except ImportError as exc:
        raise SheetConfigError("Falta gspread: pip install -r agents/shared/requirements.txt") from exc
    key_file = _key_file()
    if not key_file.exists():
        raise SheetConfigError(f"No existe la llave de la cuenta de servicio: {key_file}")
    spreadsheet_id = os.environ.get("PARRILLA_SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or spreadsheet_id == "your-spreadsheet-id":
        raise SheetConfigError("Falta PARRILLA_SPREADSHEET_ID en agents/shared/.env")
    client = gspread.service_account(filename=str(key_file))
    try:
        return client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise SheetConfigError("No se encontró la hoja: revisa el ID y que esté compartida como Editor con "
                               f"{client.auth.service_account_email}") from exc
    except gspread.exceptions.APIError as exc:
        raise SheetConfigError(f"Google rechazó el acceso a la hoja ({exc}). Revisa que las APIs de Sheets y "
                               "Drive estén habilitadas y que la hoja esté compartida como Editor.") from exc


def weekday_es(iso_date: str) -> str:
    try:
        return WEEKDAYS_ES[date.fromisoformat(str(iso_date)).weekday()]
    except ValueError:
        return ""


def _objective_text(piece: dict) -> str:
    """The Estratega writes the objective type (from the reference list in
    instagram_standards.md) and a specific objective; the sheet shows both."""
    kind, detail = str(piece.get("tipo_objetivo", "")).strip(), str(piece.get("objetivo", "")).strip()
    return f"{kind} — {detail}" if kind and detail else kind or detail


def piece_to_row(piece: dict) -> list[str]:
    """One grid piece (agent JSON) to one sheet row, in COLUMNS order."""
    status = str(piece.get("estado", "pendiente_aprobacion"))
    fecha = str(piece.get("fecha_sugerida", ""))
    return [
        str(piece.get("id", "")), fecha, weekday_es(fecha),
        str(piece.get("canal", "")), str(piece.get("formato", "")), str(piece.get("tema", "")),
        FUNNEL_STAGES.get(str(piece.get("etapa_embudo", "")).strip().lower(), str(piece.get("etapa_embudo", ""))),
        _objective_text(piece),
        str(piece.get("mensaje_clave", "")),
        str(piece.get("recursos_visuales", "")),
        str(piece.get("copy_in", "")), str(piece.get("copy_out", "")), str(piece.get("diseno", "")),
        _STATUS_FROM_JSON.get(status, status if status in STATUS_OPTIONS else STATUS_PENDING),
        str(piece.get("comentarios_dani", "")),
    ]


def tab_url(spreadsheet, worksheet) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit#gid={worksheet.id}"


def write_parrilla(tab_name: str, pieces: list[dict], replace: bool = False) -> str:
    """Writes the grid as its own tab and returns the tab's URL.

    With replace=False an existing tab is never overwritten (it may hold Dani's
    decisions). To rewrite it in a new round, read the decisions first with
    read_decisions() and carry them into `pieces`, then call with replace=True.
    """
    import gspread

    spreadsheet = open_spreadsheet()
    try:
        existing = spreadsheet.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        existing = None
    if existing is not None:
        if not replace:
            raise SheetConfigError(f"La pestaña '{tab_name}' ya existe. Lee primero las decisiones de Dani "
                                   "(read_decisions) y vuelve a escribirla con replace=True.")
        spreadsheet.del_worksheet(existing)

    rows = [COLUMNS] + [piece_to_row(p) for p in pieces]
    worksheet = spreadsheet.add_worksheet(title=tab_name, rows=max(len(rows) + 20, 50), cols=len(COLUMNS))
    worksheet.update(values=rows, range_name="A1")
    _format(spreadsheet, worksheet, n_pieces=len(pieces))
    return tab_url(spreadsheet, worksheet)


def _format(spreadsheet, worksheet, n_pieces: int) -> None:
    sid, n_cols = worksheet.id, len(COLUMNS)
    status_col = COLUMNS.index("Estado")
    last_row = max(n_pieces + 1, 2)
    body_range = {"sheetId": sid, "startRowIndex": 1, "endRowIndex": last_row, "startColumnIndex": 0, "endColumnIndex": n_cols}
    status_range = {"sheetId": sid, "startRowIndex": 1, "endRowIndex": last_row,
                    "startColumnIndex": status_col, "endColumnIndex": status_col + 1}
    requests = [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
                                   "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": n_cols},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                                                       "backgroundColor": {"red": 0.13, "green": 0.13, "blue": 0.13},
                                                       "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(textFormat,backgroundColor,verticalAlignment,wrapStrategy)"}},
        {"repeatCell": {"range": body_range,
                        "cell": {"userEnteredFormat": {"verticalAlignment": "TOP", "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)"}},
        {"setDataValidation": {"range": status_range,
                               "rule": {"condition": {"type": "ONE_OF_LIST",
                                                      "values": [{"userEnteredValue": s} for s in STATUS_OPTIONS]},
                                        "showCustomUi": True, "strict": True}}},
    ]
    for i, width in enumerate(COLUMN_WIDTHS):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    for status, (r, g, b) in STATUS_COLORS.items():
        requests.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [status_range],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": status}]},
                            "format": {"backgroundColor": {"red": r, "green": g, "blue": b}}}}}})
    spreadsheet.batch_update({"requests": requests})


def read_decisions(tab_name: str) -> list[dict]:
    """Dani's decision per piece: [{"id", "estado", "comentario"}], in sheet order."""
    worksheet = open_spreadsheet().worksheet(tab_name)
    values = worksheet.get_all_values()
    if not values:
        return []
    header = values[0]
    try:
        i_id, i_status, i_comment = header.index("ID"), header.index("Estado"), header.index("Comentarios de Dani")
    except ValueError as exc:
        raise SheetConfigError(f"La pestaña '{tab_name}' no tiene las columnas esperadas: {header}") from exc
    decisions = []
    for row in values[1:]:
        row = row + [""] * (len(header) - len(row))
        if not row[i_id].strip():
            continue
        decisions.append({"id": row[i_id].strip(), "estado": row[i_status].strip() or STATUS_PENDING,
                          "comentario": row[i_comment].strip()})
    return decisions


def summarize_decisions(decisions: list[dict]) -> dict:
    """Counts per status and whether the cycle can move on (nothing pending or with changes)."""
    counts = {s: sum(1 for d in decisions if d["estado"] == s) for s in STATUS_OPTIONS}
    counts["listo"] = bool(decisions) and counts[STATUS_PENDING] == 0 and counts[STATUS_CHANGES] == 0
    return counts
