"""How the suggested photo of a piece reads in the Sheet and in the rating Excel (prompt v8).

One column, one clear sentence, so Dani sees at a glance whether the photo
exists, will be taken before publishing, or the Diseñador has to create it
(decision 2026-11-05: a photo that does not exist is always created by the Diseñador).
"""

from __future__ import annotations

from datetime import date

MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
             "octubre", "noviembre", "diciembre"]


def _date_es(value) -> str:
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return f"{d.day} de {MONTHS_ES[d.month - 1]}"


def photo_text(photo) -> str:
    """Readable text for foto_sugerida. Older prompts used a plain string: shown as is."""
    if not photo:
        return ""
    if not isinstance(photo, dict):
        return str(photo)
    idea = str(photo.get("idea") or "").strip()
    if photo.get("tipo") == "imagen":  # v10
        return f"🖼️ Imagen por crear (lo hace el Diseñador; si Dani tiene una foto real que sirva, puede subirla). Idea: {idea}"
    if photo.get("tipo") == "foto_dopa":  # v9
        return f"📷 Foto real de DOPA: la sube Dani al aprobar (si no la sube, la pieza pasa a gráfico). Idea: {idea}"
    if photo.get("tipo") == "imagen_generica":  # v9
        return f"🖼️ Imagen genérica: la crea el Diseñador, sin hacerse pasar por DOPA. Idea: {idea}"
    if photo.get("tipo") == "grafico":
        return f"🎨 Gráfico por crear (lo hace el Diseñador). Idea: {idea}"
    support = photo.get("respaldo_brief")
    status = photo.get("disponibilidad")
    if status == "existe":
        return f"✅ Ya existe. Según el brief: «{support}». Buscar: {idea}"
    if status == "pendiente":
        return (f"⏳ Pendiente: se tomará el {_date_es(photo.get('fecha_toma'))}, antes de publicar "
                f"(según el brief: «{support}»). Toma: {idea}")
    return f"⚠️ Esta foto aún no existe: la creará el Diseñador. Idea: {idea}"


def photo_short(photo) -> str:
    """Short version for Dani's main view: status icon and the idea, no brief quote."""
    if not photo:
        return ""
    if not isinstance(photo, dict):
        return str(photo)
    idea = str(photo.get("idea") or "").strip()
    if photo.get("tipo") == "imagen":
        return f"🖼️ Imagen: {idea}"
    if photo.get("tipo") == "foto_dopa":
        return f"📷 Foto de DOPA (la sube Dani): {idea}"
    if photo.get("tipo") == "imagen_generica":
        return f"🖼️ Imagen genérica: {idea}"
    if photo.get("tipo") == "grafico":
        return f"🎨 Gráfico: {idea}"
    status = photo.get("disponibilidad")
    if status == "existe":
        return f"✅ Ya existe: {idea}"
    if status == "pendiente":
        return f"⏳ Se toma el {_date_es(photo.get('fecha_toma'))}: {idea}"
    return f"⚠️ Por crear: {idea}"
