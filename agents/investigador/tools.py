"""Herramientas del Investigador.

Una sola herramienta, `search_web`, con dos backends:

  - "tavily" (default): búsqueda real con Tavily (decisión 2026-10-12).
    Necesita TAVILY_API_KEY en el .env.
  - "stub": resultados de ejemplo, sin internet ni API key. Sirve para
    probar la estructura del agente. Sus resultados usan el dominio
    reservado `stub.invalid`, así que se distinguen con certeza en la salida.

Se elige con la variable de entorno SEARCH_BACKEND (o con
`--search-backend` en run_investigador.py). El backend queda registrado
en MLflow en cada corrida.

Contrato de la herramienta (Clase 4, Bloque A · "la herramienta es un
contrato"): el modelo solo ve el nombre, el docstring y los type hints de
`search_web`. Por eso el docstring está escrito para el modelo, y la firma
y el formato de respuesta son los mismos con cualquier backend.
"""

from __future__ import annotations

import os

VALID_BACKENDS = {"tavily", "stub"}
DEFAULT_BACKEND = "tavily"
SNIPPET_MAX_CHARS = 600  # el modelo local es de 4B: resultados cortos para no llenar su contexto


def get_backend() -> str:
    backend = os.environ.get("SEARCH_BACKEND", DEFAULT_BACKEND).strip().lower()
    if backend not in VALID_BACKENDS:
        raise ValueError(f"SEARCH_BACKEND='{backend}' no es válido. Opciones: {sorted(VALID_BACKENDS)}")
    return backend


def search_web(query: str, max_results: int = 5) -> dict:
    """Busca en la web publicaciones, artículos y tendencias recientes de fitness y bienestar.

    Úsala antes de reportar un hallazgo, para respaldarlo con una fuente. Es
    una herramienta de solo lectura: no publica ni modifica nada. Haz
    consultas concretas, en español, con tema y fecha (por ejemplo
    "retos de 21 días gimnasios Instagram noviembre 2026").

    Args:
        query: La consulta de búsqueda, concreta y en español.
        max_results: Número máximo de resultados a devolver, entre 1 y 10.

    Returns:
        Un dict con "status" ("success" o "error"), "backend" y "results":
        una lista de resultados con "title", "url", "snippet" y "published".
        Si hay error, incluye "error_code" en vez de "results".
    """
    backend = get_backend()
    if not query or not query.strip():
        return {"status": "error", "error_code": "EMPTY_QUERY", "backend": backend}

    max_results = max(1, min(int(max_results), 10))

    if backend == "stub":
        return {"status": "success", "backend": backend, "query": query, "results": _STUB_RESULTS[:max_results]}
    return _search_tavily(query, max_results)


# --------------------------------------------------------------------------
# Tavily (búsqueda real)
# --------------------------------------------------------------------------
def _search_tavily(query: str, max_results: int) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {"status": "error", "error_code": "MISSING_API_KEY", "backend": "tavily",
                "detail": "Falta TAVILY_API_KEY en el .env."}

    try:
        from tavily import TavilyClient
    except ImportError:
        return {"status": "error", "error_code": "TAVILY_NOT_INSTALLED", "backend": "tavily",
                "detail": "pip install -r agents/investigador/requirements.txt"}

    try:
        # search_depth="basic" cuesta 1 crédito por búsqueda (1,000 gratis al mes).
        response = TavilyClient(api_key=api_key).search(
            query=query, max_results=max_results, search_depth="basic"
        )
    except Exception as exc:  # errores de red, key inválida, límite de uso, etc.
        # Error estructurado, nunca una excepción cruda (Clase 4, Bloque A).
        return {"status": "error", "error_code": "SEARCH_FAILED", "backend": "tavily",
                "detail": f"{type(exc).__name__}: {exc}"[:300]}

    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:SNIPPET_MAX_CHARS],
            "published": r.get("published_date", ""),
        }
        for r in response.get("results", [])
    ]
    if not results:
        return {"status": "error", "error_code": "NO_RESULTS", "backend": "tavily", "query": query}
    return {"status": "success", "backend": "tavily", "query": query, "results": results}


# --------------------------------------------------------------------------
# Stub (sin internet) — solo para probar la estructura del agente
# --------------------------------------------------------------------------
_STUB_RESULTS = [
    {
        "title": "[STUB] Gimnasios híbridos publican retos de 21 días con progreso diario en Reels",
        "url": "https://stub.invalid/resultado-1",
        "snippet": (
            "Resultado simulado. Cuentas de gimnasios boutique muestran retos de 21 días "
            "con un video corto diario del progreso de los socios y un carrusel de cierre."
        ),
        "published": "2026-10",
    },
    {
        "title": "[STUB] Contenido educativo sobre Hyrox y Deka antes de competir",
        "url": "https://stub.invalid/resultado-2",
        "snippet": (
            "Resultado simulado. Carruseles que explican las estaciones de una carrera "
            "Deka/Hyrox y cómo prepararse tienen más guardados que las publicaciones de resultados."
        ),
        "published": "2026-10",
    },
    {
        "title": "[STUB] Testimonios de socios principiantes de más de 45 años",
        "url": "https://stub.invalid/resultado-3",
        "snippet": (
            "Resultado simulado. Historias con testimonios de socios mayores enfocados en "
            "movilidad y salud articular generan respuestas por mensaje directo."
        ),
        "published": "2026-09",
    },
]
