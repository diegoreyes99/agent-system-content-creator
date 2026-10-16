# Rúbrica humana — Investigador

Las métricas automáticas miden forma y trazabilidad (esquema, fuentes reales,
repeticiones). Esta rúbrica mide lo que solo una persona puede juzgar: si el
tema sirve, si es fiel a la fuente y si se puede convertir en una pieza.

Se califica una muestra de temas por versión (10 basta) con
`rate_investigador.py`, que muestra cada tema junto al texto real que regresó
la búsqueda, para comparar sin abrir la página.

## Criterios (1 a 3)

### Relevancia — ¿sirve para este mes?
- **3** — Apoya directamente la prioridad principal del brief.
- **2** — Útil para la prioridad secundaria u otro tema del brief.
- **1** — No sirve para este mes.

### Fidelidad — ¿lo que dice coincide con la fuente?
Compara `que_dice_la_fuente` y `relevancia_dopa` con el texto de la búsqueda.
- **3** — Todo lo que afirma está en la fuente o es una interpretación claramente marcada.
- **2** — Exagera o mezcla algo del brief como si lo dijera la fuente.
- **1** — Afirma algo que la fuente no dice.

### Accionabilidad — ¿se puede convertir en una pieza?
- **3** — Dani podría pedir la pieza mañana con esta información.
- **2** — Hay una idea, pero hay que trabajarla.
- **1** — Demasiado vago o genérico para usarse.

### ¿Es la promoción de otro negocio? (sí / no)
Debe ser "no" siempre: el Investigador propone temas genéricos ("¿Cómo empezar
en Hyrox?"), nunca la promoción de otro gimnasio o negocio.

## Cómo se usa el resultado
- Las calificaciones quedan en `ratings.csv` dentro de la carpeta de la
  corrida o del eval, y se registran en MLflow como `human_relevancia_mean`,
  `human_fidelidad_mean`, `human_accionabilidad_mean` y `human_promocion_rate`.
- Una versión nueva del prompt (o un modelo nuevo) solo se adopta si no baja
  en fidelidad y sube o se mantiene en relevancia y accionabilidad.
- Antes de usar un "LLM como juez", sus calificaciones se comparan contra
  estas: si no coinciden, no se usa.
