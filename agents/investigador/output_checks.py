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


# Esquemas por versión de prompt. v1-v5 decidían formato (formato_sugerido y
# tendencias_de_formato); desde v6 el Investigador propone temas ordenados con
# recomendados para que Dani elija, y los formatos los decide el Estratega.
LEGACY_VERSIONS = {"v1", "v2", "v3", "v4", "v5"}
V6_HALLAZGO_KEYS = {"id", "tema", "que_dice_la_fuente", "fuente", "relevancia_dopa", "prioridad", "recomendado"}
MAX_RECOMENDADOS = 5


def validate(output: dict, prompt_version: str = "v1") -> list[str]:
    """Regresa la lista de violaciones al esquema de esa versión. Lista vacía = esquema cumplido."""
    legacy = prompt_version in LEGACY_VERSIONS
    root = {"hallazgos": list, "resumen_ejecutivo": str}
    if legacy:
        root["tendencias_de_formato"] = list
    errors: list[str] = []
    for key, expected in root.items():
        if key not in output:
            errors.append(f"falta el campo '{key}'")
        elif not isinstance(output[key], expected):
            errors.append(f"'{key}' debe ser {expected.__name__}")

    extra = set(output) - set(root)
    if extra:
        errors.append(f"campos inventados en la raíz: {sorted(extra)}")

    if isinstance(output.get("resumen_ejecutivo"), str):
        words = len(output["resumen_ejecutivo"].split())
        if words > 100:
            errors.append(f"resumen_ejecutivo tiene {words} palabras (máximo 100)")

    hallazgos = output.get("hallazgos") or []
    for i, h in enumerate(hallazgos):
        if not isinstance(h, dict):
            errors.append(f"hallazgos[{i}] no es un objeto")
            continue
        required = REQUIRED_HALLAZGO_KEYS if legacy else V6_HALLAZGO_KEYS
        missing = required - set(h)
        if missing:
            errors.append(f"hallazgos[{i}] le faltan {sorted(missing)}")
        if legacy:
            if h.get("formato_sugerido") not in ALLOWED_FORMATOS:
                errors.append(f"hallazgos[{i}].formato_sugerido='{h.get('formato_sugerido')}' fuera del esquema")
        else:
            extra_keys = set(h) - V6_HALLAZGO_KEYS
            if extra_keys:
                errors.append(f"hallazgos[{i}] tiene campos fuera del esquema: {sorted(extra_keys)}")
            if not isinstance(h.get("recomendado"), bool):
                errors.append(f"hallazgos[{i}].recomendado debe ser true o false")
            if not isinstance(h.get("id"), int) or isinstance(h.get("id"), bool):
                errors.append(f"hallazgos[{i}].id debe ser un número entero")
        if h.get("prioridad") not in ALLOWED_PRIORIDADES:
            errors.append(f"hallazgos[{i}].prioridad='{h.get('prioridad')}' fuera del esquema")
        if not str(h.get("fuente", "")).strip():
            errors.append(f"hallazgos[{i}] sin fuente")

    if not legacy:
        dicts = [h for h in hallazgos if isinstance(h, dict)]
        ids = [h.get("id") for h in dicts]
        if ids != list(range(1, len(ids) + 1)):
            errors.append(f"los id deben ir 1, 2, 3... en orden (vienen {ids})")
        n_rec = sum(1 for h in dicts if h.get("recomendado") is True)
        if n_rec > MAX_RECOMENDADOS:
            errors.append(f"{n_rec} temas recomendados (máximo {MAX_RECOMENDADOS})")
    return errors


def compute_metrics(output: dict | None, errors: list[str]) -> dict[str, float]:
    """Métricas proxy de la spec (specs/investigador.md)."""
    if output is None:
        return {"json_parsed": 0.0, "schema_valid": 0.0, "n_hallazgos": 0.0, "n_alta": 0.0, "n_recomendados": 0.0,
                "pct_fuentes_stub": 0.0, "pct_fuentes_url": 0.0}
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
        "n_recomendados": float(sum(1 for h in hallazgos if h.get("recomendado") is True)),
        "n_tendencias": float(len(output.get("tendencias_de_formato") or [])),
        "pct_fuentes_stub": (n_stub / n) if n else 0.0,
        "pct_fuentes_url": (n_url / n) if n else 0.0,
    }


def trace_metrics(output: dict | None, trace: list[dict]) -> dict[str, float]:
    """Métricas que cruzan la salida con lo que de verdad regresó search_web.

    - pct_fuentes_verificadas: hallazgos cuya fuente es una URL que regresó una
      búsqueda. Es el control principal contra fuentes inventadas.
    - search_pass_rate: de todos los resultados de Tavily, qué parte pasó el
      filtro de relevancia (mide qué tan buenas fueron las búsquedas).
    - avg_relevance: relevancia promedio de los resultados que sí pasaron.
    """
    calls = [t for t in trace if t.get("type") == "tool_call"]
    responses = [t.get("response") or {} for t in trace if t.get("type") == "tool_result"]
    returned_urls, relevances, n_discarded, n_errors = set(), [], 0, 0
    for r in responses:
        if r.get("status") != "success":
            n_errors += 1
        for x in r.get("results", []) or []:
            returned_urls.add(str(x.get("url", "")).strip())
            if "relevance" in x:
                relevances.append(float(x["relevance"]))
        n_discarded += int(r.get("discarded", 0) or 0)

    hallazgos = [h for h in (output or {}).get("hallazgos") or [] if isinstance(h, dict)]
    n_verified = sum(1 for h in hallazgos if str(h.get("fuente", "")).strip() in returned_urls)
    n_returned = len(relevances)
    total = n_returned + n_discarded
    return {
        "n_tool_calls": float(len(calls)),
        "n_search_errors": float(n_errors),
        "pct_fuentes_verificadas": (n_verified / len(hallazgos)) if hallazgos else 0.0,
        "search_pass_rate": (n_returned / total) if total else 0.0,
        "avg_relevance": (sum(relevances) / n_returned) if n_returned else 0.0,
    }

