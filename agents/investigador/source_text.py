"""Keeps the text behind each approved topic, so later agents can check facts.

When Dani approves topics, the code (not an agent) stores for each topic that has a
source URL:
  - fragmento_busqueda: the snippet the search returned (already in the run's trace);
  - texto_fuente: the article text, extracted once with Tavily Extract.

The text is frozen in seleccion.json: the Copywriter, the eval and any later review
read the same thing, even if the page changes or goes offline. It is for checking
facts, never for copying (decision 2026-11-05, specs/copywriter.md).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

MAX_SOURCE_CHARS = 6000  # ~1,500 tokens per source: enough backing without flooding the Copywriter's input


def _iter_results(node):
    """Every search result (a dict with a url) inside a tool response, however it is nested."""
    if isinstance(node, dict):
        if "url" in node and ("snippet" in node or "content" in node):
            yield node
        for value in node.values():
            yield from _iter_results(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_results(item)


def snippet_from_trace(url: str, trace: list[dict]) -> str:
    """The longest snippet the search returned for this URL in the run, or ''."""
    best = ""
    for step in trace:
        if step.get("type") != "tool_result":
            continue
        for result in _iter_results(step.get("response")):
            if result.get("url") == url:
                text = str(result.get("snippet") or result.get("content") or "")
                best = text if len(text) > len(best) else best
    return best.strip()


def attach_snippets(topics: list[dict], trace: list[dict]) -> None:
    """Adds fragmento_busqueda to each topic with a source, from the round where it was found."""
    for topic in topics:
        url = str(topic.get("fuente") or "").strip()
        if url.startswith("http") and "fragmento_busqueda" not in topic:
            topic["fragmento_busqueda"] = snippet_from_trace(url, trace)


MIN_WORDS_PER_LINE = 8  # menus, buttons and footers are short lines; article paragraphs are not


def _clean(text: str) -> str:
    """Article text without page chrome: drops images, link targets, bare URLs and short
    lines (navigation, menus, buttons), keeping headings that open a paragraph.
    Tavily returns the whole page as markdown (eval 2026-11-05: the first 6,000 characters
    were mostly menus and image links)."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")       # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)            # links -> their text
    text = re.sub(r"(https?://|data:)\S+", " ", text)                 # bare URLs, data URIs
    kept: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        plain = line.lstrip("#*->|· ").strip()
        if not plain:
            continue
        if len(plain.split()) >= MIN_WORDS_PER_LINE:
            kept.append(plain)
        elif line.startswith("#") and len(plain.split()) >= 2:
            kept.append(f"\n{plain}:")  # a heading: keep it as context for the next paragraph
    # A heading with no paragraph after it is noise.
    lines = [l for i, l in enumerate(kept) if not (l.endswith(":") and (i + 1 == len(kept) or kept[i + 1].endswith(":")))]
    return "\n".join(lines).strip()


def extract_texts(urls: list[str]) -> dict[str, dict]:
    """{url: {"texto": str, "estado": "ok" | "error: …"}} using Tavily Extract (one batch call)."""
    if not urls:
        return {}
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {u: {"texto": "", "estado": "error: falta TAVILY_API_KEY"} for u in urls}
    try:
        from tavily import TavilyClient
        # Basic extraction: 1 credit per 5 URLs.
        response = TavilyClient(api_key=api_key).extract(urls=urls, extract_depth="basic")
    except Exception as exc:  # network, quota, bad key: never break the approval
        return {u: {"texto": "", "estado": f"error: {type(exc).__name__}: {exc}"[:200]} for u in urls}
    found = {}
    for item in response.get("results", []) or []:
        text = _clean(item.get("raw_content") or "")
        if len(text) > MAX_SOURCE_CHARS:
            text = text[:MAX_SOURCE_CHARS].rsplit(" ", 1)[0] + " […]"
        found[item.get("url")] = {"texto": text, "estado": "ok" if text else "error: página sin texto"}
    for item in response.get("failed_results", []) or []:
        found[item.get("url")] = {"texto": "", "estado": f"error: {item.get('error', 'no se pudo leer')}"[:200]}
    return {u: found.get(u, {"texto": "", "estado": "error: Tavily no regresó esta URL"}) for u in urls}


def attach_source_texts(topics: list[dict], backend: str) -> dict[str, int]:
    """Adds texto_fuente, texto_fuente_estado and texto_fuente_fecha to topics with a source.
    Returns counts for the summary: {"ok": n, "error": n}."""
    with_source = [t for t in topics if str(t.get("fuente") or "").startswith("http")]
    if backend != "tavily":
        for t in with_source:
            t.update({"texto_fuente": "", "texto_fuente_estado": f"omitido (búsqueda {backend})"})
        return {"ok": 0, "error": 0}
    texts = extract_texts(list(dict.fromkeys(t["fuente"] for t in with_source)))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counts = {"ok": 0, "error": 0}
    for t in with_source:
        result = texts.get(t["fuente"], {"texto": "", "estado": "error"})
        t.update({"texto_fuente": result["texto"], "texto_fuente_estado": result["estado"], "texto_fuente_fecha": stamp})
        counts["ok" if result["estado"] == "ok" else "error"] += 1
    return counts


if __name__ == "__main__":
    # Test on an existing run without the agent and without writing anything:
    #   python agents/investigador/source_text.py agents/investigador/runs/<fecha>
    import json
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    run_dir = Path(sys.argv[1])
    topics = json.loads((run_dir / "seleccion.json").read_text(encoding="utf-8"))["seleccion"]
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))["trace"]
    attach_snippets(topics, trace)
    print(attach_source_texts(topics, "tavily"))
    for t in topics:
        if t.get("fuente"):
            print(f"\n· {t['tema'][:80]}\n  {t['fuente']}\n  fragmento: {len(t.get('fragmento_busqueda', ''))} caracteres"
                  f" · texto: {len(t.get('texto_fuente', ''))} caracteres · {t.get('texto_fuente_estado')}"
                  f"\n  inicio: {t.get('texto_fuente', '')[:400]!r}")
