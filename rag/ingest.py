"""Reads DOPA's knowledge documents (.docx) and splits them into chunks.

One chunk per subsection, so a search returns a complete idea. Each chunk
starts with its "route" (document › section › subsection), which helps the
search find it even when the text does not repeat the section name. Tables
are turned into text row by row and stay inside their section. Images are
skipped. Only the standard library is used (zipfile + XML).

Usage (from agents_dopa_final_project/):
  python rag/ingest.py            # writes rag/data/chunks.jsonl and prints a summary
  python rag/ingest.py --show 5   # also prints the first 5 chunks
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent                      # agents_dopa_final_project/
DEFAULT_DOCS_DIR = PROJECT_ROOT.parents[1] / "RAG"   # llms/RAG, outside the repo
CHUNKS_FILE = HERE / "data" / "chunks.jsonl"

CHUNKER_VERSION = "v2"  # v2: can also read Markdown (.md) documents
MAX_WORDS = 250  # multilingual-e5-base reads up to 512 tokens; ~250 Spanish words stays below that

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Per document: a short title for the route, the default tag, and tag rules by section title.
DOCUMENTS = {
    "Brief_Inicial_Conocimiento_Negocio_Guia.docx": {
        "title": "Brief de negocio", "default_tag": "negocio",
        "tag_rules": [("público", "audiencia")],
    },
    "Fichas_Buyer_Persona_Guia.docx": {
        "title": "Buyer personas", "default_tag": "audiencia", "tag_rules": [],
    },
    "Manual_de_Identidad_DOPA.docx": {
        "title": "Manual de identidad", "default_tag": "visual",
        "tag_rules": [("a quién le hablamos", "audiencia"), ("fundamentos de marca", "voz")],
        "skip_preamble": True,  # before the first heading there is only the table of contents
    },
}
# Sections that only explain how to fill in a template: not knowledge about DOPA.
SKIP_SECTIONS = ("cómo usar esta guía",)


def docs_dir() -> Path:
    return Path(os.environ.get("RAG_DOCS_DIR", DEFAULT_DOCS_DIR)).expanduser()


def _text(el) -> str:
    parts = []
    for node in el.iter():
        if node.tag == W + "t" and node.text:
            parts.append(node.text)
        elif node.tag in (W + "tab", W + "br"):
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _heading_level(p) -> int:
    """0 = normal text, 1 = section, 2 = subsection. Uses Word heading styles
    when they exist (Manual) and bold + font size otherwise (Brief, Fichas)."""
    style = p.find(f"{W}pPr/{W}pStyle")
    name = (style.get(W + "val") if style is not None else "") or ""
    if name in ("Ttulo1", "Heading1"):
        return 1
    if name in ("Ttulo2", "Heading2"):
        return 2
    if name in ("Ttulo", "Title"):
        return -1  # document title: not part of any route
    bold = any(b.get(W + "val", "true") not in ("0", "false") for b in p.iter(W + "b"))
    sizes = [int(s.get(W + "val")) for s in p.iter(W + "sz") if s.get(W + "val", "").isdigit()]
    if bold and sizes:
        size = max(sizes)
        if size >= 36:
            return -1
        if size >= 26:
            return 1
        if size >= 22:
            return 2
    return 0


def _table_lines(tbl) -> list[str]:
    """A table as text: each data row becomes "Header: value · Header: value"."""
    rows = []
    for tr in tbl.findall(f"{W}tr"):
        # A cell may hold several paragraphs: join them with a space so words do not stick together.
        rows.append([" ".join(t for t in (_text(p) for p in tc.iter(W + "p")) if t) for tc in tr.findall(f"{W}tc")])
    if not rows:
        return []
    header, lines = rows[0], []
    for row in rows[1:]:
        if len(header) == len(row) and len(header) > 1:
            pairs = [f"{h}: {v}" for h, v in zip(header, row) if v]
            lines.append(" · ".join(pairs))
        else:
            lines.append(" · ".join(v for v in row if v))
    if len(rows) == 1:  # single-row table (e.g. a quote box)
        lines = [" · ".join(v for v in header if v)]
    return [l for l in lines if l]


def _blocks(docx_path: Path):
    """Yields ("heading", level, text) or ("text", 0, text) in document order."""
    root = ET.fromstring(zipfile.ZipFile(docx_path).read("word/document.xml"))
    body = root.find(f"{W}body")
    for el in body:
        if el.tag == W + "p":
            text = _text(el)
            if text:
                level = _heading_level(el)
                yield ("heading", level, text) if level != 0 else ("text", 0, text)
        elif el.tag == W + "tbl":
            for line in _table_lines(el):
                yield ("text", 0, line)


def _markdown_blocks(md_path: Path):
    """Same blocks as _blocks(), for Markdown notes: '##' = section, '###' = subsection."""
    for line in md_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("# "):
            continue  # blank lines and the document title
        if stripped.startswith("### "):
            yield ("heading", 2, stripped[4:].strip())
        elif stripped.startswith("## "):
            yield ("heading", 1, stripped[3:].strip())
        else:
            yield ("text", 0, stripped)


def _tag_for(route: list[str], cfg: dict) -> str:
    joined = " › ".join(route).lower()
    for needle, tag in cfg["tag_rules"]:
        if needle in joined:
            return tag
    return cfg["default_tag"]


def _split(lines: list[str]) -> list[list[str]]:
    """Splits a long section into pieces of up to MAX_WORDS, never cutting a line."""
    pieces, current, words = [], [], 0
    for line in lines:
        n = len(line.split())
        if current and words + n > MAX_WORDS:
            pieces.append(current)
            current, words = [], 0
        current.append(line)
        words += n
    if current:
        pieces.append(current)
    return pieces


def chunk_document(docx_path: Path) -> list[dict]:
    cfg = DOCUMENTS[docx_path.name]
    chunks, section, subsection, lines = [], "", "", []

    def flush():
        route = [r for r in (section, subsection) if r]
        if not lines or any(s in r.lower() for r in route for s in SKIP_SECTIONS):
            return
        if not route and cfg.get("skip_preamble"):
            return
        pieces = _split(lines)
        for i, piece in enumerate(pieces, start=1):
            header = " › ".join([cfg["title"], *route]) + (f" (parte {i} de {len(pieces)})" if len(pieces) > 1 else "")
            text = header + "\n" + "\n".join(piece)
            chunk_id = hashlib.sha1(f"{docx_path.name}|{header}".encode()).hexdigest()[:12]
            chunks.append({
                "id": chunk_id, "text": text, "document": docx_path.name, "doc_title": cfg["title"],
                "section": section, "subsection": subsection, "tag": _tag_for([cfg["title"], *route], cfg),
                "n_words": len(text.split()), "chunker_version": CHUNKER_VERSION,
            })

    blocks = _markdown_blocks(docx_path) if docx_path.suffix == ".md" else _blocks(docx_path)
    for kind, level, text in blocks:
        if kind == "heading" and level in (1, 2):
            flush()
            lines = []
            if level == 1:
                section, subsection = text, ""
            else:
                subsection = text
        elif kind == "text":
            lines.append(text)
    flush()
    return chunks


def build_chunks() -> list[dict]:
    folder = docs_dir()
    missing = [name for name in DOCUMENTS if not (folder / name).exists()]
    if missing:
        raise SystemExit(f"No se encontraron en {folder}: {missing}")
    extra = sorted(p.name for p in [*folder.glob("*.docx"), *folder.glob("*.md")] if p.name not in DOCUMENTS)
    if extra:
        print(f"Aviso: estos documentos de {folder} no están configurados y se ignoran: {extra}")
    return [c for name in DOCUMENTS for c in chunk_document(folder / name)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show", type=int, default=0, help="print the first N chunks")
    args = parser.parse_args()

    chunks = build_chunks()
    CHUNKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_FILE.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"{len(chunks)} fragmentos → {CHUNKS_FILE}")
    by_doc, by_tag = {}, {}
    for c in chunks:
        by_doc[c["doc_title"]] = by_doc.get(c["doc_title"], 0) + 1
        by_tag[c["tag"]] = by_tag.get(c["tag"], 0) + 1
    print("  por documento:", by_doc)
    print("  por etiqueta: ", by_tag)
    sizes = sorted(c["n_words"] for c in chunks)
    print(f"  palabras por fragmento: mín {sizes[0]} · mediana {sizes[len(sizes) // 2]} · máx {sizes[-1]}")
    for c in chunks[: args.show]:
        print("\n" + "-" * 70 + f"\n[{c['tag']}] {c['text'][:600]}")


if __name__ == "__main__":
    main()
