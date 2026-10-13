# Baseline de referencia — Fase 1

Ejercicio puntual (no un sistema en uso continuo): corre los 6 prompts de
agentes en secuencia, contra un modelo abierto servido localmente por
**LM Studio**, usando las clases de **Google ADK** (`Agent` + `LiteLlm`)
como forma uniforme de llamar al modelo. El resultado queda guardado como
texto plano en `cycles/` — es el punto de comparación para cuando en la
Fase 2 construyas el primer agente real.

## 1. Prepara LM Studio

1. Abre LM Studio y descarga un modelo pequeño (recomendado para 8 GB de
   RAM: **Qwen3 4B Instruct**, cuantización Q4, idealmente versión MLX si
   tu máquina es Apple Silicon).
2. Ve a la pestaña **Developer** (o **Local Server**) y arranca el
   servidor local. Por default corre en `http://localhost:1234`.
3. Anota el **identificador exacto del modelo** tal como aparece ahí — lo
   vas a necesitar en el siguiente paso. No siempre coincide con el
   nombre "bonito" que se ve en el catálogo.

## 2. Instala dependencias

```bash
cd baseline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configura las variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y pon el identificador real de tu modelo en
`LM_STUDIO_MODEL_ID` (y el puerto en `OPENAI_API_BASE` si tu LM Studio usa
uno distinto a 1234).

## 4. Escribe el brief del mes

Copia `briefs/brief_template.md` a algo como `briefs/ciclo-1-brief.md` y
llénalo con un brief real (objetivo del mes, novedades, fechas clave,
presupuesto).

## 5. Corre el ciclo

```bash
python run_baseline_cycle.py --brief briefs/ciclo-1-brief.md
```

El script va a parar dos veces a pedir tu aprobación en la terminal —
igual que los dos puntos de aprobación humana del flujo real (parrilla, y
luego copy + dirección visual). Cada paso se guarda en
`cycles/<fecha>/<nombre_del_paso>.json` (y su `.raw.txt` con la respuesta
cruda del modelo, por si el JSON no se pudo parsear limpio).

## Si algo falla

- **"No se encontró un bloque JSON en la respuesta"**: el modelo no siguió
  el formato pedido. Revisa el `.raw.txt` del paso que falló — es común en
  modelos pequeños los primeros intentos. Puedes reintentar ese ciclo.
- **Error de conexión / timeout**: confirma que el servidor local de LM
  Studio sigue corriendo y que el puerto en `.env` es el correcto.
- **El agente no devolvió texto**: normalmente es que
  `LM_STUDIO_MODEL_ID` no coincide exactamente con el id que LM Studio
  tiene cargado — revisa la pestaña Developer de LM Studio.

## Qué no hace este script

- No corre al Analista de Resultados como parte del ciclo — ese agente
  necesita métricas de un ciclo YA publicado, que un baseline no tiene
  todavía. Para correrlo por separado cuando tengas métricas reales de
  Instagram: `python run_baseline_cycle.py --metrics ruta/a/metricas.md`.
- No publica nada de verdad ni llama a ninguna herramienta externa — es
  puramente generación de texto/JSON para comparar contra lo que haga el
  agente real de ADK en Fase 2.
