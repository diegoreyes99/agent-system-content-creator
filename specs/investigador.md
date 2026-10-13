# Spec — Investigador (Fase 2)

- **Qué hace:** recibe el brief del mes y devuelve oportunidades de contenido para Instagram orgánico, respaldadas por fuentes externas, para que el Estratega arme la parrilla.
- **Entrada:** el brief del mes (`baseline/briefs/*.md`), insertado en el bloque DATOS del prompt.
- **Prompt:** `prompts/investigador_v2.md` (v1 + reglas de uso de `search_web`). `v1` se conserva sin cambios para comparar contra el baseline.
- **Herramientas:** `search_web(query, max_results)`. Es de **solo lectura**, así que corre sin confirmación (Clase 4, Bloque A: "lectura ≠ escritura"). **Backend: Tavily** (decisión 2026-10-12), búsqueda básica de 1 crédito por consulta, con `TAVILY_API_KEY` en `agents/investigador/.env`. Se conserva un backend **stub** (resultados de ejemplo en `stub.invalid`, sin internet) para probar estructura; se elige con `SEARCH_BACKEND` o `--search-backend`. Por qué Tavily: es función de Python normal (funciona con el modelo local, a diferencia de `google_search` de ADK, que solo corre con Gemini) y 1,000 créditos gratis al mes cubren de sobra ~5 búsquedas por ciclo. Limitación: ninguna API de búsqueda ve publicaciones dentro de Instagram.
- **Guardrails en código:** lista blanca de herramientas (solo `search_web`), un tope de 5 búsquedas por corrida y un tope de llamadas al modelo (`RunConfig.max_llm_calls`). Si no se cumple, la llamada se bloquea: falla cerrada, sin excepción.
- **Salida:** JSON con `hallazgos[]`, `tendencias_de_formato[]` y `resumen_ejecutivo`. Es el esquema del bloque FORMATO DE SALIDA del prompt y se valida en código en cada corrida.
- **Modelo:** Qwen3 4B Instruct vía LM Studio (local, sin costo de API).
- **Aprobación humana:** ninguna propia. El Investigador no escribe nada ni le muestra nada a Daniela. El primer punto de aprobación del flujo es la parrilla del Estratega.
- **Métrica de éxito (negocio):** sus hallazgos de prioridad "alta" son los que el Estratega realmente usa en la parrilla, no los que descarta por poco accionables o inventados.
- **Métricas medibles hoy (proxy, en MLflow):** `schema_valid`, `n_hallazgos`, `n_alta`, `n_tool_calls`, `pct_fuentes_stub`, `pct_fuentes_url`, `latency_s` y tokens. La métrica de negocio se mide hasta que exista el Estratega en ADK.
