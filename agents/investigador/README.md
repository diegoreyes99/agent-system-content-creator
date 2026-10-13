# Investigador — agente ADK (Fase 2)

Primer agente real del sistema. Corre solo, fuera del baseline. Spec:
`specs/investigador.md`.

| Archivo | Qué es |
|---|---|
| `agent.py` | El `Agent()` de ADK: prompt `prompts/investigador_<versión>.md` como `instruction`, herramienta `search_web` y guardrail `before_tool_callback` |
| `tools.py` | `search_web` con búsqueda real en **Tavily** (default) o **stub** (resultados de ejemplo en `stub.invalid`, sin internet) |
| `output_checks.py` | Parseo del JSON, validación contra el esquema del prompt y métricas proxy |
| `tracking.py` | Configuración de MLflow (todo local en `agents_dopa_final_project/mlruns/`) |
| `run_investigador.py` | Corre el agente, guarda la salida en `runs/<fecha>/` y la registra en MLflow |
| `compare_with_baseline.py` | Pone lado a lado el baseline de Fase 1 y una corrida del agente nuevo |

Todos los comandos se corren **desde `agents_dopa_final_project/`**, con
el `.venv` activo.

## 1. Instala dependencias y configura Tavily (una sola vez)

```bash
source .venv/bin/activate
pip install -r agents/investigador/requirements.txt
mlflow --version
```

Crea una cuenta gratis en https://app.tavily.com (1,000 créditos al mes; cada
búsqueda básica cuesta 1) y copia tu API key:

```bash
cp agents/investigador/.env.example agents/investigador/.env
# edita agents/investigador/.env y pon tu TAVILY_API_KEY
```

El `.env` está en `.gitignore`: la key nunca se sube a GitHub.

## 2. Corre el agente

Con LM Studio abierto y el servidor local encendido (el mismo modelo del
baseline). El script toma `TAVILY_API_KEY` de `agents/investigador/.env` y
`LM_STUDIO_MODEL_ID` del `baseline/.env` que ya tienes.

```bash
python agents/investigador/run_investigador.py --brief baseline/briefs/ciclo-1-brief.md
```

Esto corre el prompt v1 (default). Para el v2, que ya trae las reglas de
uso de `search_web`:

```bash
python agents/investigador/run_investigador.py --brief baseline/briefs/ciclo-1-brief.md --prompt-version v2
```

Para probar sin internet ni gastar créditos, agrega `--search-backend stub`.

Al final imprime cuántas búsquedas hizo, cuántos hallazgos hay, si el
esquema es válido y dónde quedó todo (`agents/investigador/runs/<fecha>/`).

## 3. Compara contra el baseline

```bash
python agents/investigador/compare_with_baseline.py \
    --baseline baseline/cycles/2026-10-13_0019/01_investigador.json \
    --run agents/investigador/runs/<fecha> \
    --log-baseline
```

Usa `--log-baseline` solo la primera vez. Con eso el baseline también
queda como corrida en MLflow (`E00-baseline-sin-herramientas`).

## 4. Abre la UI de MLflow

```bash
mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db --port 5001
```

Abre http://localhost:5001 → experimento `dopa-investigador`. Selecciona
dos corridas → **Compare**. Se usa el puerto 5001 porque en macOS el 5000
lo ocupa el AirPlay Receiver.

## Qué buscar en la primera corrida

- **`n_tool_calls` = 0 con v1:** es esperable, porque el prompt v1 no le
  dice cuándo buscar. El v2 agrega esas reglas; compara `n_tool_calls` y
  `pct_fuentes_url` entre las dos corridas (Clase 4: "un cambio por
  versión").
- **`schema_valid` = 0:** revisa `validation.json`. Los prompts v1 a v3
  definen `formato_sugerido` como `post | historia | carrusel`, pero su
  ejemplo few-shot usa `"reel"`; si el modelo lo copia, el validador lo
  marca. El v4 corrige el ejemplo: el sistema no produce reels ni video.
- **`pct_fuentes_stub`:** qué tanto de lo que reporta viene del stub. Con
  Tavily debe ser 0.
- **Errores de búsqueda:** si Tavily falla (key inválida, sin créditos, sin
  red), la herramienta no truena: le regresa al modelo un error
  estructurado (`MISSING_API_KEY`, `SEARCH_FAILED`, `NO_RESULTS`) y queda en
  `trace.json`.
