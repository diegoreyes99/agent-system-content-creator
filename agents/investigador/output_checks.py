"""Parseo y validación de la salida del Investigador.

Lo usan run_investigador.py y compare_with_baseline.py, así el baseline y
el agente nuevo se miden exactamente con las mismas reglas.

El esquema sale del bloque FORMATO DE SALIDA de prompts/investigador_v1.md.
"""

from __future__ import annotations

import json
import re

ALLOWED_FORMATOS = {"post", "historia", "carrusel"}
ALLOWED_PRIORIDADES = {"alta", "media", "baja"}
REQUIRED_HALLAZGO_KEYS = {"tema", "fuente", "relevancia_dopa", "formato_sugerido", "prioridad"}
STUB_MARKER = "stub.invalid"


def extract_json(raw_text: str) -> dict:
    """Extrae el primer bloque JSON de la respuesta del modelo (igual que en el baseline)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw_text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No se encontró un bloque JSON en la respuesta del modelo.")
    return json.loads(candidate[start : end + 1])


def validate(output: dict) -> list[str]:
    """Regresa la lista de violaciones al esquema. Lista vacía = esquema cumplido."""
    errors: list[str] = []
    for key, expected in (("hallazgos", list), ("tendencias_de_formato", list), ("resumen_ejecutivo", str)):
        if key not in output:
            errors.append(f"falta el campo '{key}'")
        elif not isinstance(output[key], expected):
            errors.append(f"'{key}' debe ser {expected.__name__}")

    extra = set(output) - {"hallazgos", "tendencias_de_formato", "resumen_ejecutivo"}
    if extra:
        errors.append(f"campos inventados en la raíz: {sorted(extra)}")

    if isinstance(output.get("resumen_ejecutivo"), str):
        words = len(output["resumen_ejecutivo"].split())
        if words > 100:
            errors.append(f"resumen_ejecutivo tiene {words} palabras (máximo 100)")

    for i, h in enumerate(output.get("hallazgos") or []):
        if not isinstance(h, dict):
            errors.append(f"hallazgos[{i}] no es un objeto")
            continue
        missing = REQUIRED_HALLAZGO_KEYS - set(h)
        if missing:
            errors.append(f"hallazgos[{i}] le faltan {sorted(missing)}")
        if h.get("formato_sugerido") not in ALLOWED_FORMATOS:
            errors.append(f"hallazgos[{i}].formato_sugerido='{h.get('formato_sugerido')}' fuera del esquema")
        if h.get("prioridad") not in ALLOWED_PRIORIDADES:
            errors.append(f"hallazgos[{i}].prioridad='{h.get('prioridad')}' fuera del esquema")
        if not str(h.get("fuente", "")).strip():
            errors.append(f"hallazgos[{i}] sin fuente")
    return errors


def compute_metrics(output: dict | None, errors: list[str]) -> dict[str, float]:
    """Métricas proxy de la spec (specs/investigador.md)."""
    if output is None:
        return {"json_parsed": 0.0, "schema_valid": 0.0, "n_hallazgos": 0.0, "n_alta": 0.0, "pct_fuentes_stub": 0.0, "pct_fuentes_url": 0.0}
    hallazgos = [h for h in output.get("hallazgos") or [] if isinstance(h, dict)]
    n = len(hallazgos)
    n_stub = sum(1 for h in hallazgos if STUB_MARKER in str(h.get("fuente", "")))
    n_url = sum(1 for h in hallazgos if str(h.get("fuente", "")).strip().startswith(("http://", "https://")))
    return {
        "json_parsed": 1.0,
        "schema_valid": 0.0 if errors else 1.0,
        "n_schema_errors": float(len(errors)),
        "n_hallazgos": float(n),
        "n_alta": float(sum(1 for h in hallazgos if h.get("prioridad") == "alta")),
        "n_tendencias": float(len(output.get("tendencias_de_formato") or [])),
        "pct_fuentes_stub": (n_stub / n) if n else 0.0,
        "pct_fuentes_url": (n_url / n) if n else 0.0,
    }
