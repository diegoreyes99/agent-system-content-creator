# RAG — conocimiento de DOPA (Fase 3, adelantada para el Estratega)

Una sola base de conocimiento para el Estratega, el Copywriter y el Diseñador.
Cada fragmento lleva una etiqueta (`negocio`, `audiencia`, `voz`, `visual`) y
cada agente busca con las suyas (`config.AGENT_TAGS`).

| Archivo | Qué hace |
|---|---|
| `ingest.py` | Lee los `.docx` de `llms/RAG/` y los parte por sección (un fragmento por subsección, con su ruta al inicio; tablas fila por fila) |
| `build_index.py` | Calcula los embeddings con el modelo local y guarda el índice en ChromaDB (`rag/index/`) |
| `retriever.py` | La búsqueda que usarán los agentes: `search(pregunta, k, tags)` |
| `eval_set.json` | 23 preguntas típicas de cada agente con sus fragmentos esperados |
| `eval_rag.py` | Mide hit@k, recall@k, precision@k y MRR, y lo registra en MLflow (`dopa-rag`) |
| `embeddings.py` | Proveedor de embeddings: `local` (sentence-transformers, default) u `openai_compatible` (LM Studio o un proveedor en la nube), con `RAG_EMBEDDING_BACKEND` |
| `config.py` | Modelo de embeddings, colección, etiquetas por agente, versión del buscador |

**Privacidad:** los documentos se quedan en `llms/RAG/`, fuera del repositorio.
`rag/data/` (fragmentos) y `rag/index/` (vectores) están en `.gitignore`: se
reconstruyen con un comando. El modelo de embeddings es local
(`intfloat/multilingual-e5-base`, decisión 2026-10-22): los documentos nunca
salen de la Mac. En producción se evaluará otro modelo con el mismo eval.

## Uso (desde `agents_dopa_final_project/`, con el entorno activo)

```bash
pip install -r rag/requirements.txt          # una vez (instala PyTorch: tarda unos minutos)
python rag/build_index.py                    # cada vez que cambie un documento
python rag/retriever.py "¿Qué frena a Rosa para inscribirse?" --agent estratega
python rag/eval_rag.py                       # eval filtrado por agente
python rag/eval_rag.py --no-filter           # eval sobre toda la base
```

Para agregar un documento: ponlo en `llms/RAG/`, regístralo en
`DOCUMENTS` de `ingest.py` (título, etiqueta por defecto y reglas por
sección), reconstruye el índice y agrega preguntas al eval.

## Versiones del buscador

| Versión | Cambio | Resultado |
|---|---|---|
| `v01` | Búsqueda semántica, top-k, filtro por etiqueta | Eval 2026-10-24 (k=4, filtrado): hit 0.96 · MRR 0.74. Estratega MRR 0.60 (no encontró "Recursos y limitaciones") |
| `v02` | Híbrida: semántica + BM25 (palabras exactas), fusionadas con Reciprocal Rank Fusion | Eval 2026-10-24: hit 0.87 · MRR 0.72. Mejora al Estratega (MRR 0.67, encuentra "Recursos y limitaciones") pero empeora al Copywriter (hit 0.86) y al Diseñador (hit 0.83). **Descartada: se queda v01** (decisión 2026-10-24) |
