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
from pathlib import Path
from urllib.parse import urlparse

# Versión del contrato/comportamiento de la herramienta. Se registra en MLflow
# (Clase 4: tools v1 → v2 es un experimento propio, igual que prompt v1 → v2).
#   v1: resultados de Tavily tal cual.
#   v2: descarta resultados con puntaje de relevancia bajo y le pasa el
#       puntaje al modelo (corrida 2026-10-12: 8 de 15 resultados eran ruido).
#   v3: clasifica cada resultado por su dominio (certificada / web / red social,
#       según trusted_sources.txt), marca si tiene contenido suficiente y
#       ordena primero las certificadas (calificación humana del v6, 2026-10-15).
#   v4: also marks results from other gyms and studios as "competidor"
#       (competitor_sources.txt) and puts them last (human rating of Gemini v7,
#       2026-10-15: 2 of 10 topics came from competitor blogs).
TOOLS_VERSION = "v4"

VALID_BACKENDS = {"tavily", "stub"}
DEFAULT_BACKEND = "tavily"
SNIPPET_MAX_CHARS = 600  # el modelo local es de 4B: resultados cortos para no llenar su contexto
# Puntaje mínimo de relevancia de Tavily (0 a 1) para pasarle un resultado al
# modelo. Valor inicial: se calibra con los puntajes que quedan en trace.json.
DEFAULT_MIN_SCORE = 0.4


# Menos de esto (en caracteres) = la fuente casi no tiene contenido que respalde
# un tema; típico de publicaciones de redes con solo un texto corto.
MIN_CONTENT_CHARS = 250
SOCIAL_DOMAINS = ("instagram.com", "facebook.com", "tiktok.com", "youtube.com", "x.com",
                  "twitter.com", "threads.net", "linkedin.com", "pinterest.com")
TRUSTED_SOURCES_FILE = Path(__file__).resolve().parent / "trusted_sources.txt"
COMPETITOR_SOURCES_FILE = Path(__file__).resolve().parent / "competitor_sources.txt"
_TYPE_ORDER = {"certificada": 0, "web": 1, "red_social": 2, "competidor": 3}


def _load_domains(path: Path) -> list[str]:
    """Reads a domain list (one per line, # for comments)."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [l.strip().lower() for l in lines if l.strip() and not l.strip().startswith("#")]


def _trusted_domains() -> list[str]:
    return _load_domains(TRUSTED_SOURCES_FILE)


def _competitor_domains() -> list[str]:
    return _load_domains(COMPETITOR_SOURCES_FILE)


def _domain_matches(host: str, entry: str) -> bool:
    if entry.startswith("."):
        return host.endswith(entry)
    return host == entry or host.endswith("." + entry)


def classify_source(url: str) -> str:
    """certificada (lista de fuentes confiables), competidor (otro gimnasio o estudio),
    red_social o web. Solo por dominio."""
    host = (urlparse(url).hostname or "").lower()
    if any(_domain_matches(host, d) for d in _trusted_domains()):
        return "certificada"
    if any(_domain_matches(host, d) for d in _competitor_domains()):
        return "competidor"
    if any(_domain_matches(host, d) for d in SOCIAL_DOMAINS):
        return "red_social"
    return "web"


def describe_result(url: str, content: str) -> dict:
    return {"tipo_fuente": classify_source(url),
            "contenido_suficiente": len((content or "").strip()) >= MIN_CONTENT_CHARS}


def get_min_score() -> float:
    return float(os.environ.get("SEARCH_MIN_SCORE", DEFAULT_MIN_SCORE))


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
        una lista de resultados con "title", "url", "snippet", "published",
        "relevance" (0 a 1; solo llegan los relevantes), "tipo_fuente"
        ("certificada", "web" o "red_social") y "contenido_suficiente"
        (false si la fuente casi no tiene texto). Vienen ordenados: primero
        las fuentes certificadas.
        Si hay error, incluye "error_code" en vez de "results".
    """
    backend = get_backend()
    if not query or not query.strip():
        return {"status": "error", "error_code": "EMPTY_QUERY", "backend": backend}

    max_results = max(1, min(int(max_results), 10))

    if backend == "stub":
        results = [{**r, **describe_result(r["url"], r["snippet"])} for r in _STUB_RESULTS[:max_results]]
        return {"status": "success", "backend": backend, "query": query, "results": results}
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

    raw_results = response.get("results", [])
    min_score = get_min_score()
    # Filtro en código, no en el prompt: el modelo nunca ve el ruido.
    relevant = [r for r in raw_results if (r.get("score") or 0) >= min_score]
    discarded_scores = [round(r.get("score") or 0, 3) for r in raw_results if r not in relevant]

    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:SNIPPET_MAX_CHARS],
            "published": r.get("published_date", ""),
            "relevance": round(r.get("score") or 0, 2),
            **describe_result(r.get("url", ""), r.get("content") or ""),
        }
        for r in relevant
    ]
    # Primero las fuentes certificadas, luego web, al final redes sociales;
    # dentro de cada grupo, por relevancia.
    results.sort(key=lambda x: (_TYPE_ORDER[x["tipo_fuente"]], -x["relevance"]))
    base = {"backend": "tavily", "query": query, "min_score": min_score,
            "discarded": len(discarded_scores), "discarded_scores": discarded_scores}
    if not results:
        return {"status": "error", "error_code": "NO_RELEVANT_RESULTS", **base}
    return {"status": "success", "results": results, **base}


# --------------------------------------------------------------------------
# Stub (sin internet) — solo para probar la estructura del agente
# --------------------------------------------------------------------------
_STUB_RESULTS = [
    {
        "title": "[STUB] Gimnasios híbridos publican retos de 21 días con carruseles de progreso",
        "url": "https://stub.invalid/resultado-1",
        "snippet": (
            "Resultado simulado. Cuentas de gimnasios boutique muestran retos de 21 días "
            "con una historia diaria del progreso de los socios y un carrusel de cierre."
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
