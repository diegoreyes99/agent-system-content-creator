"""Builds what the Estratega receives: month, brief, approved topics, operational
context and the Instagram standards. Pure Python (no ADK), so the eval can use it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import tools

HERE = Path(__file__).resolve().parent
STANDARDS_FILE = HERE.parent / "shared" / "instagram_standards.md"  # shared with the Copywriter and the Diseñador
GREEN_FILE = HERE / "green_content.md"

# Fields of each approved topic that the Estratega needs (the rest is Investigador bookkeeping).
TOPIC_FIELDS = ("tema", "que_dice_la_fuente", "fuente", "responde_a", "tipo_fuente", "contenido_suficiente")


def month_from_brief(brief_text: str) -> str:
    match = re.search(r"Mes a planear:\**\s*(\d{4}-\d{2})", brief_text)
    if not match:
        raise ValueError("El brief no dice el mes a planear (línea 'Mes a planear: AAAA-MM').")
    return match.group(1)


def main_priority(brief_text: str) -> str:
    """The marked option under '### Prioridad principal' (the brief is already cleaned)."""
    block = brief_text.split("### Prioridad principal", 1)[-1]
    match = re.search(r"^\s*-\s*\*\*(.+?)\*\*", block, flags=re.M)
    return match.group(1).strip() if match else ""


def load_approved_topics(selection_path: Path) -> list[dict]:
    """Approved topics from the Investigador's seleccion.json (or an eval fixture
    with the same shape), each with a reference T1, T2... in order."""
    data = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    if data.get("status") not in (None, "aprobado"):
        raise ValueError(f"{selection_path}: la selección no está aprobada (status '{data.get('status')}').")
    topics = []
    for item in data.get("seleccion", []):
        tema = str(item.get("tema", "")).strip()
        if not tema or tema.lower() in ("no", "ninguno", "nada"):
            continue  # an answer saved as a topic by mistake (fixed in run_investigador 2026-10-26)
        origin = item.get("origen", "investigador")
        topic = {"ref": f"T{len(topics) + 1}", "origen": origin}
        topic.update({k: item[k] for k in TOPIC_FIELDS if k in item and origin == "investigador"})
        topic["tema"] = tema
        topics.append(topic)
    if not topics:
        raise ValueError(f"{selection_path}: no hay temas aprobados.")
    return topics


def build_inputs(brief_text: str, selection_path: Path) -> dict:
    topics = load_approved_topics(selection_path)
    context = tools.get_operational_context()
    visual = tools.get_visual_guidelines()
    return {
        "mes": month_from_brief(brief_text),
        "prioridad_principal": main_priority(brief_text),
        "brief_del_mes": brief_text,
        "temas_aprobados": topics,
        "contexto_operativo": context or "(No disponible: construye el RAG con python rag/build_index.py.)",
        "estandares_instagram": estratega_standards(),
        "lineamientos_visuales": visual or "(No disponible: construye el RAG con python rag/build_index.py.)",
        "contenidos_green": GREEN_FILE.read_text(encoding="utf-8") if GREEN_FILE.exists() else "(sin contenidos green)",
        "green_refs": green_refs(),
    }


def estratega_standards() -> str:
    """Sections 1-9 and the sources of instagram_standards.md. Section 10 (text: copy in and
    copy out) is for the Copywriter; leaving it out (with its sources) keeps the Estratega's
    input as it was when v11 was evaluated and closed (2026-11-05); only the version line differs."""
    text = STANDARDS_FILE.read_text(encoding="utf-8")
    start, end = text.find("## 10. "), text.find("## Fuentes")
    if not 0 <= start < end:
        return text
    sources = [line for line in text[end:].splitlines()
               if not re.match(r"^(1[2-9]|[2-9]\d)\. ", line)]  # sources 12+ belong to section 10
    return text[:start] + "\n".join(sources) + "\n"


def green_refs() -> list[str]:
    """G1, G2... as defined in green_content.md (headings "## G1 · ...")."""
    if not GREEN_FILE.exists():
        return []
    return re.findall(r"^## (G\d+)\b", GREEN_FILE.read_text(encoding="utf-8"), flags=re.M)


def fill_prompt(template: str, inputs: dict) -> str:
    values = {
        "mes": inputs["mes"],
        "brief_del_mes": inputs["brief_del_mes"],
        "temas_aprobados": json.dumps(inputs["temas_aprobados"], ensure_ascii=False, indent=2),
        "contexto_operativo": inputs["contexto_operativo"],
        "estandares_instagram": inputs["estandares_instagram"],
        "contenidos_green": inputs.get("contenidos_green", ""),
        "lineamientos_visuales": inputs.get("lineamientos_visuales", ""),
    }
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template
