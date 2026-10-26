"""Validation and metrics of the Estratega's grid (computed in code, never by the model)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import tools

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FORMATS = {"post", "carrusel", "historia"}
FEED_FORMATS = {"post", "carrusel"}
AUDIENCES = {"Ana", "Rosa", "Ambas", "Hija de Rosa"}
ORIGINS = {"tema_aprobado", "brief", "green"}
STATES = {"pendiente_aprobacion", "aprobado", "descartado"}

# Funnel stages and the objective types that belong to each (instagram_standards.md, sections 8-9).
STAGE_OBJECTIVES = {
    "descubrimiento": {"Reconocimiento de marca", "Crecimiento de audiencia"},
    "consideracion": {"Interacción y comunidad", "Tráfico", "Atención y confianza"},
    "conversion": {"Generación de leads", "Conversión"},
    "fidelizacion": {"Retención y lealtad"},
}
OBJECTIVE_TYPES = set().union(*STAGE_OBJECTIVES.values())

# Reference mix by main priority (instagram_standards.md, section 9). Keys are
# matched against the marked priority in the brief.
REFERENCE_MIX = {
    "captar socios": {"descubrimiento": 0.40, "consideracion": 0.30, "conversion": 0.25, "fidelizacion": 0.05},
    "llenar un evento": {"descubrimiento": 0.30, "consideracion": 0.30, "conversion": 0.30, "fidelizacion": 0.10},
    "llenar clases": {"descubrimiento": 0.30, "consideracion": 0.35, "conversion": 0.25, "fidelizacion": 0.10},
    "convertir usuarios": {"descubrimiento": 0.10, "consideracion": 0.35, "conversion": 0.30, "fidelizacion": 0.25},
    "retener": {"descubrimiento": 0.15, "consideracion": 0.25, "conversion": 0.15, "fidelizacion": 0.45},
}

TOP_KEYS = ("mes", "objetivo_del_mes", "estrategia_del_mes", "mezcla_por_etapa", "mezcla_de_objetivos",
            "criterio_de_volumen", "supuestos", "fuentes_de_conocimiento", "piezas")
PIECE_KEYS = ("id", "fecha_sugerida", "canal", "formato", "origen_pieza", "tema_ref", "elemento_del_brief",
              "tema", "publico", "etapa_embudo", "tipo_objetivo", "objetivo", "mensaje_clave",
              "responsable_aprobacion", "estado")
PIECE_KEYS_V6 = ("green_ref", "recursos_visuales")  # required from prompt v6 on


def extract_json(raw: str) -> dict:
    """The JSON object in the model's answer, even inside ```json fences or with text around it."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.S)
    text = fenced.group(1) if fenced else raw[raw.find("{"): raw.rfind("}") + 1]
    if not text.strip():
        raise ValueError("no hay un objeto JSON en la respuesta")
    return json.loads(text)


def _competitor_names() -> list[str]:
    """Competitor names to look for in the grid: brand part of each domain in
    competitor_sources.txt, plus the competitors named in the business brief."""
    names = set()
    sources = PROJECT_ROOT / "agents" / "investigador" / "competitor_sources.txt"
    if sources.exists():
        for line in sources.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                brand = line.lstrip(".").split(".")[0]
                if len(brand) >= 4:
                    names.add(brand)
    chunks = PROJECT_ROOT / "rag" / "data" / "chunks.jsonl"
    if chunks.exists():
        for raw in chunks.read_text(encoding="utf-8").splitlines():
            for match in re.finditer(r"Competidor: ([^·\n]+)", json.loads(raw)["text"]):
                for name in re.sub(r"\(.*?\)", "", match.group(1)).split("/"):  # "Sport City / Sports World"
                    name = name.strip().lower()
                    if len(name) >= 4:
                        names.add(name)
    return sorted(names)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9áéíóúñü ]", " ", text.lower())).strip()


def _mentions(text: str, name: str) -> bool:
    """Whole-word match ("Smart Fit"), plus a match without spaces ("smartfit")
    for long names only, so short names do not match inside other words."""
    name = _norm(name)
    if re.search(rf"\b{re.escape(name)}\b", text):
        return True
    joined = name.replace(" ", "")
    return len(joined) >= 7 and joined in text.replace(" ", "")


def validate(output: dict, inputs: dict) -> list[str]:
    """Hard rules. Each problem is one readable message (also logged in model_errors.csv)."""
    errors: list[str] = []
    for key in TOP_KEYS:
        if key not in output:
            errors.append(f"falta el campo '{key}'")
    pieces = output.get("piezas")
    if not isinstance(pieces, list) or not pieces:
        return errors + ["'piezas' está vacío o no es una lista"]

    month = inputs["mes"]
    refs = {t["ref"] for t in inputs["temas_aprobados"]}
    seen_ids = set()
    for i, p in enumerate(pieces, start=1):
        if not isinstance(p, dict):
            errors.append(f"pieza {i}: no es un objeto")
            continue
        pid = p.get("id", f"#{i}")
        required = PIECE_KEYS + (PIECE_KEYS_V6 if inputs.get("prompt_version", "v5") >= "v6" else ())
        missing = [k for k in required if k not in p]
        if missing:
            errors.append(f"{pid}: faltan {missing}")
        if pid in seen_ids:
            errors.append(f"{pid}: id repetido")
        seen_ids.add(pid)
        try:
            d = date.fromisoformat(str(p.get("fecha_sugerida", "")))
            if d.strftime("%Y-%m") != month:
                errors.append(f"{pid}: la fecha {d} no es de {month}")
        except ValueError:
            errors.append(f"{pid}: fecha inválida '{p.get('fecha_sugerida')}'")
        if p.get("canal") != "instagram":
            errors.append(f"{pid}: canal '{p.get('canal')}' (solo instagram)")
        if p.get("formato") not in FORMATS:
            errors.append(f"{pid}: formato '{p.get('formato')}' no permitido")
        origin = p.get("origen_pieza")
        if origin not in ORIGINS:
            errors.append(f"{pid}: origen_pieza '{origin}' inválido")
        elif origin == "tema_aprobado" and p.get("tema_ref") not in refs:
            errors.append(f"{pid}: tema_ref '{p.get('tema_ref')}' no es un tema aprobado")
        elif origin == "brief" and not str(p.get("elemento_del_brief") or "").strip():
            errors.append(f"{pid}: pieza del negocio sin elemento_del_brief")
        elif origin == "green" and p.get("green_ref") not in inputs.get("green_refs", []):
            errors.append(f"{pid}: green_ref '{p.get('green_ref')}' no es un contenido green")
        if p.get("publico") not in AUDIENCES:
            errors.append(f"{pid}: público '{p.get('publico')}' inválido")
        stage, kind = p.get("etapa_embudo"), p.get("tipo_objetivo")
        if stage not in STAGE_OBJECTIVES:
            errors.append(f"{pid}: etapa_embudo '{stage}' inválida")
        if kind not in OBJECTIVE_TYPES:
            errors.append(f"{pid}: tipo_objetivo '{kind}' no está en la lista de referencia")
        elif stage in STAGE_OBJECTIVES and kind not in STAGE_OBJECTIVES[stage]:
            errors.append(f"{pid}: '{kind}' no corresponde a la etapa '{stage}'")
        if p.get("estado") not in STATES:
            errors.append(f"{pid}: estado '{p.get('estado')}' inválido")
        if p.get("estado") == "aprobado" and not p.get("_aprobado_por_dani"):
            errors.append(f"{pid}: el modelo marcó la pieza como aprobada (solo Dani aprueba)")

    # No full week (Monday to Sunday inside the month) without a feed piece.
    cal = tools.get_month_calendar(month)
    feed_dates = {p.get("fecha_sugerida") for p in pieces if isinstance(p, dict) and p.get("formato") in FEED_FORMATS}
    for week in cal.get("weeks", []):
        if week["dias"] == 7:
            days = {d["fecha"] for d in cal["days"] if d["semana"] == week["semana"]}
            if not days & feed_dates:
                errors.append(f"semana del {week['inicio']} al {week['fin']} sin publicaciones de feed")

    covered = {p.get("tema_ref") for p in pieces if isinstance(p, dict) and p.get("origen_pieza") == "tema_aprobado"}
    for ref in sorted(refs - covered):
        errors.append(f"tema aprobado {ref} sin ninguna pieza")

    names = _competitor_names()
    for p in pieces:
        if isinstance(p, dict):
            text = _norm(" ".join(str(p.get(k, "")) for k in ("tema", "objetivo", "mensaje_clave", "elemento_del_brief")))
            for name in names:
                if _mentions(text, name):
                    errors.append(f"{p.get('id')}: menciona a un competidor ('{name}')")
    return errors


# Errors about the strategy itself. Everything else (JSON, missing fields, a
# value outside the allowed lists, a type that does not match its funnel
# stage) is a format error: it breaks the chaining, but not the proposal.
CONTENT_ERROR_MARKERS = ("no es de", "sin ninguna pieza", "competidor", "sin publicaciones de feed",
                         "no es un tema aprobado", "sin elemento_del_brief", "no es un contenido green",
                         "marcó la pieza como aprobada")


def split_errors(errors: list[str]) -> tuple[list[str], list[str]]:
    content = [e for e in errors if any(m in e for m in CONTENT_ERROR_MARKERS)]
    return [e for e in errors if e not in content], content


def compute_metrics(output: dict | None, errors: list[str], inputs: dict) -> dict[str, float]:
    format_errors, content_errors = split_errors(errors)
    if not output or not isinstance(output.get("piezas"), list):
        return {"json_parsed": 0.0, "schema_valid": 0.0, "n_errors": float(len(errors)),
                "n_errores_forma": float(len(format_errors)), "n_errores_contenido": float(len(content_errors)),
                "n_piezas": 0.0}
    pieces = [p for p in output["piezas"] if isinstance(p, dict)]
    n = len(pieces) or 1
    refs = {t["ref"] for t in inputs["temas_aprobados"]}
    covered = {p.get("tema_ref") for p in pieces if p.get("origen_pieza") == "tema_aprobado"}

    # Weeks of the month (Monday to Sunday). Only full weeks count for "empty week".
    cal = tools.get_month_calendar(inputs["mes"])
    week_of = {d["fecha"]: d["semana"] for d in cal.get("days", [])}
    full_weeks = [w["semana"] for w in cal.get("weeks", []) if w["dias"] == 7]
    feed_by_week = {w["semana"]: 0 for w in cal.get("weeks", [])}
    for p in pieces:
        if p.get("formato") in FEED_FORMATS and p.get("fecha_sugerida") in week_of:
            feed_by_week[week_of[p["fecha_sugerida"]]] += 1
    full_counts = [feed_by_week[w] for w in full_weeks] or [0]

    stage_share = {s: sum(1 for p in pieces if p.get("etapa_embudo") == s) / n for s in STAGE_OBJECTIVES}
    priority = inputs.get("prioridad_principal", "").lower()
    reference = next((mix for key, mix in REFERENCE_MIX.items() if key in priority), None)
    deviation = (sum(abs(stage_share[s] - reference[s]) for s in STAGE_OBJECTIVES) / 2) if reference else -1.0

    consistent = sum(1 for p in pieces if p.get("tipo_objetivo") in STAGE_OBJECTIVES.get(p.get("etapa_embudo"), set()))
    competitor_errors = sum(1 for e in errors if "competidor" in e)
    metrics = {
        "json_parsed": 1.0,
        "schema_valid": 1.0 if not errors else 0.0,
        "n_errors": float(len(errors)),
        "n_errores_forma": float(len(format_errors)),
        "n_errores_contenido": float(len(content_errors)),
        "n_piezas": float(len(pieces)),
        "n_feed": float(sum(1 for p in pieces if p.get("formato") in FEED_FORMATS)),
        "n_historias": float(sum(1 for p in pieces if p.get("formato") == "historia")),
        "n_carruseles": float(sum(1 for p in pieces if p.get("formato") == "carrusel")),
        "feed_por_semana_min": float(min(full_counts)),
        "feed_por_semana_max": float(max(full_counts)),
        "feed_por_semana_mean": sum(full_counts) / len(full_counts),
        "n_semanas_sin_feed": float(sum(1 for c in full_counts if c == 0)),
        "pct_temas_cubiertos": len(refs & covered) / len(refs) if refs else 1.0,
        "pct_piezas_brief": sum(1 for p in pieces if p.get("origen_pieza") == "brief") / n,
        "pct_piezas_green": sum(1 for p in pieces if p.get("origen_pieza") == "green") / n,
        "pct_etapa_coherente": consistent / n,
        "desviacion_mezcla": deviation,  # 0 = same as the reference mix, 1 = completely different; -1 = no reference
        "n_menciones_competidor": float(competitor_errors),
        "n_fuentes_conocimiento": float(len(output.get("fuentes_de_conocimiento") or [])),
    }
    for stage, share in stage_share.items():
        metrics[f"pct_{stage}"] = share
    return metrics


def trace_metrics(trace: list[dict]) -> dict[str, float]:
    calls = [t for t in trace if t.get("type") == "tool_call"]
    return {
        "n_tool_calls": float(len(calls)),
        "n_calendar_calls": float(sum(1 for t in calls if t.get("tool") == "get_month_calendar")),
        "n_rag_calls": float(sum(1 for t in calls if t.get("tool") == "search_dopa_knowledge")),
    }


ERROR_LOG_FIELDS = ["fecha", "origen", "carpeta", "prompt_version", "modelo", "brief", "detalle"]


def append_error_log(log_path, context: dict, errors: list[str]) -> int:
    import csv
    from datetime import datetime

    if not errors:
        return 0
    log_path = Path(log_path)
    new_file = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ERROR_LOG_FIELDS)
        if new_file:
            writer.writeheader()
        for e in errors:
            writer.writerow({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), **context, "detalle": e})
    return len(errors)
