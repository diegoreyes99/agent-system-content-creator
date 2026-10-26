"""Tools of the Estratega. Both are read-only, so they run without confirmation.

  - get_month_calendar(month): every day of the month with its weekday, Mexico's
    official rest days and well-known commercial dates. Computed in code because
    models often get dates and weekdays wrong.
  - search_dopa_knowledge(question): searches DOPA's knowledge base (RAG v01),
    limited to the Estratega's tags (business, audience, voice).

Also get_operational_context(), which is not a tool: the code puts that section
in the prompt every time, because the Estratega always needs it to size the month.
"""

from __future__ import annotations

import calendar
import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "rag"))

TOOLS_VERSION = "v1"
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MAX_RAG_RESULTS = 4
MAX_CHUNK_CHARS = 1500  # keeps each result readable without filling the context

# Section of the business brief with the production capacity (photographer,
# image bank, approval times, budget). Injected in the prompt, not searched:
# the RAG eval showed the search can miss it (question e03).
OPERATIONAL_CONTEXT_ROUTE = "Brief de negocio › 13. Recursos y Limitaciones"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th given weekday of a month (weekday: 0 = Monday)."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def official_rest_days(year: int) -> dict[date, str]:
    """Mandatory rest days in Mexico (Ley Federal del Trabajo, art. 74)."""
    days = {
        date(year, 1, 1): "Año Nuevo",
        _nth_weekday(year, 2, 0, 1): "Día de la Constitución (descanso oficial)",
        _nth_weekday(year, 3, 0, 3): "Natalicio de Benito Juárez (descanso oficial)",
        date(year, 5, 1): "Día del Trabajo",
        date(year, 9, 16): "Día de la Independencia",
        _nth_weekday(year, 11, 0, 3): "Revolución Mexicana (descanso oficial)",
        date(year, 12, 25): "Navidad",
    }
    if (year - 2024) % 6 == 0:
        days[date(year, 10, 1)] = "Transmisión del Poder Ejecutivo Federal"
    return days


def commercial_dates(year: int) -> dict[date, str]:
    """Well-known dates that change how people use social media (not rest days)."""
    return {
        date(year, 2, 14): "San Valentín",
        date(year, 5, 10): "Día de las Madres",
        _nth_weekday(year, 6, 6, 3): "Día del Padre",
        date(year, 11, 1): "Día de Muertos (1 de noviembre)",
        date(year, 11, 2): "Día de Muertos (2 de noviembre)",
        date(year, 12, 12): "Día de la Virgen de Guadalupe",
        date(year, 12, 24): "Nochebuena",
        date(year, 12, 31): "Fin de año",
    }


def get_month_calendar(month: str) -> dict:
    """Regresa el calendario del mes para planear la parrilla.

    Úsala antes de asignar fechas: da cada día con su día de la semana, los
    días de descanso oficiales en México y fechas conocidas que cambian el uso
    de redes. No incluye las fechas del brief (eventos, fechas a evitar): esas
    las tomas del brief.

    Args:
        month: El mes a planear, en formato "AAAA-MM" (por ejemplo "2026-11").

    Returns:
        Un dict con "status", "month", "days" (cada día con "fecha", "dia_semana",
        "semana" del mes y, si aplica, "descanso_oficial" o "fecha_comercial"),
        y "weeks" (cada semana con sus fechas de inicio y fin dentro del mes).
    """
    try:
        year, mon = (int(x) for x in str(month).strip().split("-"))
        days_in_month = calendar.monthrange(year, mon)[1]
    except (ValueError, calendar.IllegalMonthError):
        return {"status": "error", "error_code": "INVALID_MONTH",
                "message": f"'{month}' no es un mes válido; usa el formato AAAA-MM."}

    rest, commercial = official_rest_days(year), commercial_dates(year)
    first = date(year, mon, 1)
    days, weeks = [], {}
    for d in range(1, days_in_month + 1):
        current = date(year, mon, d)
        # Weeks start on Monday; week 1 is the (possibly partial) week of day 1.
        week = (current.toordinal() - (first.toordinal() - first.weekday())) // 7 + 1
        entry = {"fecha": current.isoformat(), "dia_semana": WEEKDAYS_ES[current.weekday()], "semana": week}
        if current in rest:
            entry["descanso_oficial"] = rest[current]
        if current in commercial:
            entry["fecha_comercial"] = commercial[current]
        days.append(entry)
        weeks.setdefault(week, []).append(current.isoformat())
    return {
        "status": "success", "month": f"{year:04d}-{mon:02d}", "days": days,
        "weeks": [{"semana": w, "inicio": dates[0], "fin": dates[-1], "dias": len(dates)} for w, dates in weeks.items()],
    }


def search_dopa_knowledge(question: str) -> dict:
    """Busca en el conocimiento de DOPA: negocio, públicos (Ana y Rosa) y voz de marca.

    Úsala para fundamentar la estrategia con datos reales de DOPA: objeciones y
    detonadores de compra de cada público, servicios, clases y tarifas,
    diferenciadores, competencia, qué ha funcionado en redes, objetivos del
    negocio. Haz preguntas concretas, una idea por búsqueda; si no encuentras
    algo, reformula con otras palabras.

    Args:
        question: La pregunta, concreta y en español.

    Returns:
        Un dict con "status" y "results": cada resultado con "ruta" (documento ›
        sección, para citarla) y "texto".
    """
    if not str(question).strip():
        return {"status": "error", "error_code": "EMPTY_QUERY", "message": "La pregunta está vacía."}
    try:
        import config
        import retriever

        hits = retriever.search(question, MAX_RAG_RESULTS, config.AGENT_TAGS["estratega"])
    except Exception as exc:  # index missing, model not installed, etc.
        return {"status": "error", "error_code": "KNOWLEDGE_UNAVAILABLE", "message": str(exc)}
    results = []
    for h in hits:
        body = h["text"].split("\n", 1)[1] if "\n" in h["text"] else h["text"]
        results.append({"ruta": h["route"], "texto": body[:MAX_CHUNK_CHARS]})
    return {"status": "success", "question": question, "results": results}


def get_operational_context() -> str:
    """Text of the "Recursos y limitaciones" section, read straight from the
    chunks file (not a search). Empty string if the RAG has not been built."""
    chunks_file = PROJECT_ROOT / "rag" / "data" / "chunks.jsonl"
    if not chunks_file.exists():
        return ""
    for line in chunks_file.read_text(encoding="utf-8").splitlines():
        chunk = json.loads(line)
        route, _, body = chunk["text"].partition("\n")
        if route.startswith(OPERATIONAL_CONTEXT_ROUTE):
            return body.strip()
    return ""
