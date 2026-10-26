#!/usr/bin/env python3
"""Builds the Estratega's golden set: frozen topic selections (same shape as the
Investigador's seleccion.json), so every eval run receives exactly the same input.

The topics come from the Investigador's Gemini v7 eval (the configuration that
closed Fase 2). Each selection simulates what Dani would approve: the
recommended topics, plus extra cases that test specific rules. Source types are
recomputed with the current search tool (v4), so a competitor blog that was
"web" at the time is now "competidor".

Usage (from agents_dopa_final_project/):
  python agents/estratega/build_eval_cases.py
Run it again only if the Investigador changes in an important way (new prompt or
output shape); write the reason in prompts/README.md, because it changes the eval.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agents" / "investigador"))
from tools import classify_source  # noqa: E402  (Investigador's search tool, v4)

CASES_DIR = HERE / "eval_cases"
BRIEFS = PROJECT_ROOT / "baseline" / "briefs"
EVALS = PROJECT_ROOT / "agents" / "investigador" / "evals"
SOURCE_RUNS = {  # Investigador Gemini v7 eval runs, one per brief
    "op1": EVALS / "2026-10-16_024506" / "brief_2026-11_op1_captar-socios_r1",
    "op2": EVALS / "2026-10-16_024506" / "brief_2026-11_op2_convertir-agregadores_r1",
    "op3": EVALS / "2026-10-16_024506" / "brief_2026-11_op3_reactivar-socios_r1",
    "op4": EVALS / "2026-10-20_180430" / "brief_2026-11_op4_llenar-pilates_r1",
    "op5": EVALS / "2026-10-20_180430" / "brief_2026-11_op5_simulacro-deka_r1",
}
BRIEF_FILES = {
    "op1": "brief_2026-11_op1_captar-socios.md", "op2": "brief_2026-11_op2_convertir-agregadores.md",
    "op3": "brief_2026-11_op3_reactivar-socios.md", "op4": "brief_2026-11_op4_llenar-pilates.md",
    "op5": "brief_2026-11_op5_simulacro-deka.md",
}

# case id -> (brief, Investigador topic ids that Dani "approves", Dani's own topics, what it tests)
CASES = {
    "op1_base": ("op1", [1, 2, 3, 4], [], "Captar socios: los 4 recomendados"),
    "op2_base": ("op2", [1, 2, 4], [], "Convertir agregadores: 2 recomendados + 1 alternativa"),
    "op3_base": ("op3", [1, 2, 3, 4], [], "Reactivar socios: incluye un tema con fuente de competidor (Orangetheory)"),
    "op4_base": ("op4", [2, 3, 4], [], "Llenar Pilates: los 3 recomendados"),
    "op5_base": ("op5", [1, 2, 3, 4], [], "Llenar un evento (simulacro Deka): los 4 recomendados"),
    "op2_tema_dani": ("op2", [2, 4], ["Qué cambió para una socia al pasarse de TotalPass a la membresía directa: "
                                      "seguimiento del coach, horarios y comunidad"],
                      "Un tema propio de Dani, sin fuente"),
    "op3_pocos_temas": ("op3", [1, 3], [], "Solo 2 temas aprobados: el volumen debe salir de la estrategia"),
    "op1_muchos_temas": ("op1", [1, 2, 3, 4, 5, 6], ["Tu primera clase en DOPA: qué esperar desde que llegas hasta que terminas",
                                                    "Cómo acomodar 4 entrenamientos a la semana con una agenda de oficina"],
                         "8 temas aprobados (6 del Investigador + 2 de Dani): variedad y volumen razonable"),
}

KEEP = ("tema", "que_dice_la_fuente", "fuente", "responde_a")


def build_case(brief_key: str, ids: list[int], dani_topics: list[str], note: str) -> dict:
    output = json.loads((SOURCE_RUNS[brief_key] / "output.json").read_text(encoding="utf-8"))
    by_id = {h["id"]: h for h in output["hallazgos"]}
    selection = []
    for i in ids:
        h = by_id[i]
        item = {k: h[k] for k in KEEP if k in h}
        item.update({"tipo_fuente": classify_source(h.get("fuente", "")), "origen": "investigador", "ronda": 1})
        selection.append(item)
    selection += [{"tema": t, "origen": "dani", "ronda": 1} for t in dani_topics]
    return {"status": "aprobado", "brief": BRIEF_FILES[brief_key], "nota": note,
            "fuente_temas": str(SOURCE_RUNS[brief_key].relative_to(PROJECT_ROOT)), "seleccion": selection}


def main() -> None:
    CASES_DIR.mkdir(exist_ok=True)
    manifest = []
    for case_id, (brief_key, ids, dani, note) in CASES.items():
        data = build_case(brief_key, ids, dani, note)
        (CASES_DIR / f"{case_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({"case": case_id, "brief": f"baseline/briefs/{data['brief']}",
                         "seleccion": f"agents/estratega/eval_cases/{case_id}.json", "nota": note,
                         "n_temas": len(data["seleccion"]),
                         "tipos_fuente": sorted({s.get('tipo_fuente', 'dani') for s in data["seleccion"]})})
        print(f"{case_id:<18} {len(data['seleccion'])} temas · {note}")
    (CASES_DIR / "cases.json").write_text(json.dumps({"version": "v1", "cases": manifest}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"\n{len(manifest)} casos → {CASES_DIR / 'cases.json'}")


if __name__ == "__main__":
    main()
