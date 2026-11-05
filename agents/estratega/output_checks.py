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
AUDIENCES = {"Ana", "Rosa", "Ambas", "Hija de Rosa"}  # "Hija de Rosa" only existed in prompts v6-v7
AUDIENCES_V8 = {"Ana", "Rosa", "Ambas"}  # from v8 the daughter is "Ana" (decision 2026-11-05)
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
PIECE_KEYS_V7 = ("angulo", "puntos_clave", "cta", "foto_sugerida")  # required from prompt v7 on


def vnum(version: str) -> int:
    """Prompt version as a number, so "v10" comes after "v9" (as strings it would not)."""
    digits = re.sub(r"\D", "", str(version))
    return int(digits) if digits else 0


def required_piece_keys(version: str) -> tuple:
    """v6 added green_ref and recursos_visuales; v7 angle, key points, CTA and suggested photo;
    v8 merged the visual fields into one structured foto_sugerida (no recursos_visuales)."""
    keys, v = PIECE_KEYS, vnum(version)
    if v >= 6:
        keys += ("green_ref",) + (("recursos_visuales",) if v < 8 else ())
    if v >= 7:
        keys += PIECE_KEYS_V7 if v < 8 else tuple(k for k in PIECE_KEYS_V7 if k != "cta")
    return keys


PHOTO_TYPES = {"foto", "grafico"}
PHOTO_STATUSES = {"existe", "pendiente", "no_existe"}
# From v9 the Estratega only says what kind of visual the piece needs; Dani decides which real photo to use
# (decision 2026-11-05). "foto_dopa": Dani uploads it; the others are created by the Diseñador.
VISUAL_TYPES_V9 = {"foto_dopa", "imagen_generica", "grafico"}
# From v10 the Diseñador creates every visual from scratch, assuming no DOPA photos exist;
# Dani may upload a real photo, optionally (decision 2026-11-05).
VISUAL_TYPES_V10 = {"imagen", "grafico"}
# Words that mean a photo that does not exist yet: from v7 on it belongs in foto_sugerida, not in recursos_visuales.
PHOTO_REQUEST_MARKERS = ("pendiente", "por tomar", "sesión nueva", "nueva sesión", "agendar", "tomar foto")


def _scan(line: str, stack: list, in_string: bool) -> bool:
    """Updates the open containers after reading one line; returns whether a string is still open."""
    escaped = False
    for ch in line:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    return in_string


def repair_json(text: str) -> str:
    """Fixes the mechanical slips the light model makes in long JSON outputs
    (eval 2026-10-26): a key without its opening quote (`puntos_clave": [`, `$tema: "…"`),
    a list without its key (only puntos_clave is a list inside a piece) and a stray
    string alone on a line inside an object (`"post",`) and a markdown bullet before a
    list item (`- "texto",`) and a missing comma between two fields. Each line is fixed before it
    is scanned, so a broken quote never confuses what comes after it."""
    stack: list = []
    in_string = False
    fixed = []
    for line in text.split("\n"):
        if not in_string and stack and stack[-1] == "{":
            # Key without quotes or with junk before it: puntos_clave": / $tema: / 'tema':
            match = re.match(r'^(\s*)[$\']?([A-Za-z_][A-Za-z0-9_]*)["\']?\s*:(.*)$', line)
            if match and not line.lstrip().startswith('"'):
                line = f'{match.group(1)}"{match.group(2)}":{match.group(3)}'
            # A list with no key inside a piece: puntos_clave is the only list field of a piece.
            if re.match(r'^\s*\[\s*$', line):
                line = line.replace("[", '"puntos_clave": [', 1)
            # A bare string inside an object is not valid JSON: drop it.
            if re.match(r'^\s*"[^"]*"\s*,?\s*$', line):
                continue
            # A missing comma between two fields: "tipo_objetivo": "x"  /  "objetivo": … (eval 2026-11-05, 3.8 Flash).
            if re.match(r'^\s*"[^"]+"\s*:', line) and fixed:
                prev = fixed[-1].rstrip()
                if prev and prev[-1] not in ",{[" and re.search(r'("|\d|true|false|null|\]|\})$', prev):
                    fixed[-1] = prev + ","
        # A markdown bullet before a list item: - "texto", (eval 2026-11-05, prompt v9).
        if not in_string and stack and stack[-1] == "[":
            line = re.sub(r'^(\s*)[-*•]\s+(?=")', r"\1", line)
        in_string = _scan(line, stack, in_string)
        fixed.append(line)
    return "\n".join(fixed)


def extract_json(raw: str, repaired: list | None = None) -> dict:
    """The JSON object in the model's answer, even inside ```json fences or with text around it.
    If it does not parse, tries repair_json() once; pass a list as `repaired` to learn if it was needed."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.S)
    text = fenced.group(1) if fenced else raw[raw.find("{"): raw.rfind("}") + 1]
    if not text.strip():
        raise ValueError("no hay un objeto JSON en la respuesta")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        result = json.loads(repair_json(text))  # if this also fails, the original error is reported upstream
        if repaired is not None:
            repaired.append(True)
        return result


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
        version = inputs.get("prompt_version", "v5")
        v = vnum(version)
        required = required_piece_keys(version)
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
        if p.get("publico") not in (AUDIENCES_V8 if v >= 8 else AUDIENCES):
            errors.append(f"{pid}: público '{p.get('publico')}' inválido")
        stage, kind = p.get("etapa_embudo"), p.get("tipo_objetivo")
        if stage not in STAGE_OBJECTIVES:
            errors.append(f"{pid}: etapa_embudo '{stage}' inválida")
        if kind not in OBJECTIVE_TYPES:
            errors.append(f"{pid}: tipo_objetivo '{kind}' no está en la lista de referencia")
        elif stage in STAGE_OBJECTIVES and kind not in STAGE_OBJECTIVES[stage]:
            errors.append(f"{pid}: '{kind}' no corresponde a la etapa '{stage}'")
        if v >= 10:
            photo = p.get("foto_sugerida")
            if not isinstance(photo, dict) or photo.get("tipo") not in VISUAL_TYPES_V10 or not str(photo.get("idea") or "").strip():
                errors.append(f"{pid}: foto_sugerida debe traer tipo (imagen o grafico) e idea")
        elif v == 9:
            photo = p.get("foto_sugerida")
            if not isinstance(photo, dict) or photo.get("tipo") not in VISUAL_TYPES_V9 or not str(photo.get("idea") or "").strip():
                errors.append(f"{pid}: foto_sugerida debe traer tipo (foto_dopa, imagen_generica o grafico) e idea")
        elif v == 8:
            photo = p.get("foto_sugerida")
            if not isinstance(photo, dict) or photo.get("tipo") not in PHOTO_TYPES or not str(photo.get("idea") or "").strip():
                errors.append(f"{pid}: foto_sugerida debe traer tipo (foto o grafico) e idea")
            elif photo.get("tipo") == "foto" and photo.get("disponibilidad") not in PHOTO_STATUSES:
                errors.append(f"{pid}: disponibilidad de la foto '{photo.get('disponibilidad')}' inválida")
        if v == 7:
            visuals = str(p.get("recursos_visuales") or "").lower()
            if any(m in visuals for m in PHOTO_REQUEST_MARKERS):
                errors.append(f"{pid}: recursos_visuales incluye una foto que no existe; va en foto_sugerida ('{p.get('recursos_visuales')}')")

        if v >= 7:
            points = p.get("puntos_clave")
            if "puntos_clave" in p and (not isinstance(points, list) or not 2 <= len(points) <= 4):
                errors.append(f"{pid}: puntos_clave debe ser una lista de 2 a 4")
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


def _plain(text: str) -> str:
    """Lowercase, no accents, no quotes or markdown, single spaces: to find a quote inside the brief."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[*_`«»\"“”'‘’]", "", text)
    return re.sub(r"\s+", " ", text).strip(" .")


# Small words that say nothing about the photo itself.
_SUPPORT_STOPWORDS = set("""a al con de del el en la las lo los para por que se su sus un una y o
este esta mes fotos foto banco disponibles""".split())
# A brief sentence with these words says the photo is missing, not ready or only scheduled.
_NOT_READY = ("falta", "faltan", "no estan listas", "no esta lista", "todavia no", "por confirmar", "se agenda",
              "se agendan", "por tomar", "pendiente")


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _plain(text)) if w not in _SUPPORT_STOPWORDS and len(w) > 2}


def _support_problem(quote: str, brief_text: str, status: str) -> str | None:
    """None if the brief backs the photo; otherwise the reason. The model often paraphrases
    a little ("Banco de Mike: clases y coaches" for "banco de Mike con clases y coaches"),
    so the check compares key words against the most similar sentence of the brief
    instead of demanding the exact phrase (fix after the v8 eval, 2026-11-05)."""
    words = _content_words(quote)
    if len(words) < 2:
        return "el respaldo no dice qué foto es"
    # Sentences of the brief (split on periods, semicolons and line breaks, not on colons:
    # "Banco de Mike: clases y coaches" is one idea).
    sentences = [s for s in re.split(r"(?<=[.;])\s+|\n+", brief_text) if s.strip()]
    # A quote may join two consecutive sentences ("Banco de Mike: clases y coaches. Fotos del Cosmic Run…").
    sentences += [f"{a} {b}" for a, b in zip(sentences, sentences[1:])]
    best, overlap = "", 0.0
    for sentence in sentences:
        share = len(words & _content_words(sentence)) / len(words)
        if share > overlap:
            best, overlap = sentence, share
    if overlap < 0.75:
        return "la frase de respaldo no está en el brief"
    plain_best = _plain(best)
    not_ready = any(m in plain_best for m in _NOT_READY)
    if status == "existe" and not_ready:
        return "el brief dice que esa foto falta o todavía no está lista"
    if status == "pendiente" and not not_ready and not re.search(r"\b(sesion|se tom|se agend)", plain_best):
        return "el brief no dice que esa foto se vaya a tomar"
    return None


def apply_photo_rules(output: dict | None, brief_text: str) -> list[dict]:
    """Code rule (prompt v8): a photo is "existe" or "pendiente" only if the brief backs it
    (see _support_problem) and, if pending, the shoot is before the piece is published.
    Otherwise it becomes "no_existe" (Dani decides). Changes `output` in place and
    returns one correction per change, to log every time the model got it wrong."""
    if not output:
        return []
    corrections = []
    for p in output.get("piezas") or []:
        photo = p.get("foto_sugerida") if isinstance(p, dict) else None
        if not isinstance(photo, dict) or photo.get("tipo") != "foto" or photo.get("disponibilidad") not in ("existe", "pendiente"):
            continue
        reason = _support_problem(photo.get("respaldo_brief") or "", brief_text, photo["disponibilidad"])
        if reason is None and photo["disponibilidad"] == "pendiente":
            try:
                if date.fromisoformat(str(photo.get("fecha_toma"))) >= date.fromisoformat(str(p.get("fecha_sugerida"))):
                    reason = "la sesión de fotos es el mismo día o después de la publicación"
            except ValueError:
                reason = "la foto pendiente no tiene una fecha de sesión válida"
        if reason:
            corrections.append({"id": p.get("id"), "antes": photo["disponibilidad"], "motivo": reason,
                                "respaldo": photo.get("respaldo_brief")})
            photo.update({"disponibilidad": "no_existe", "respaldo_brief": None, "fecha_toma": None,
                          "corregido_por_codigo": reason})
    return corrections


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
    photos = [p.get("foto_sugerida") for p in pieces if isinstance(p.get("foto_sugerida"), dict)]
    if photos:
        metrics["n_fotos_existen"] = float(sum(1 for f in photos if f.get("tipo") == "foto" and f.get("disponibilidad") == "existe"))
        metrics["n_fotos_pendientes"] = float(sum(1 for f in photos if f.get("tipo") == "foto" and f.get("disponibilidad") == "pendiente"))
        metrics["n_fotos_no_existen"] = float(sum(1 for f in photos if f.get("tipo") == "foto" and f.get("disponibilidad") == "no_existe"))
        metrics["n_graficos"] = float(sum(1 for f in photos if f.get("tipo") == "grafico"))
        metrics["n_fotos_dopa"] = float(sum(1 for f in photos if f.get("tipo") == "foto_dopa"))
        metrics["n_imagenes_genericas"] = float(sum(1 for f in photos if f.get("tipo") == "imagen_generica"))
        metrics["n_imagenes"] = float(sum(1 for f in photos if f.get("tipo") == "imagen"))
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
