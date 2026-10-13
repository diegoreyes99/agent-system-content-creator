# Prompts versionados — Sistema de Agentes de Marketing DOPA

Un archivo por agente, numerado por versión (`_v1`, `_v2`, ...). Cuando se reescriba un prompt, se guarda como una
versión nueva en vez de sobrescribir la anterior — así cualquier cambio de calidad se puede rastrear contra el
golden set de la Fase 4, tal como pide la sección 5.6 ("Versionado y trazabilidad") de la Guía de prompting y
consumo de modelos.

## Estructura de cada prompt

Los 6 prompts siguen la misma plantilla de 8 bloques (Parte I · Fundamentos, sección 1.2 de la guía):

**ROL → CONTEXTO → TAREA → PROCESO → FORMATO DE SALIDA → RESTRICCIONES → EJEMPLOS → DATOS**

- Las restricciones están formuladas en positivo (qué hacer, no solo qué evitar).
- La salida de los 5 agentes especialistas es JSON con esquema fijo, pensada para que un programa la lea
  (`json.loads()`), no para que la lea una persona — así el Orquestador puede encadenar la salida de un agente
  como entrada del siguiente sin texto libre de por medio.
- Cada uno trae un ejemplo (few-shot) de su propia salida.

## Nota sobre la referencia a "Parte V" en `GUIA_DE_IMPLEMENTACION.md`

La Fase 1 de la guía dice reescribir los prompts "con las técnicas de Guía de prompting y consumo de modelos
(Parte V)". Al revisar el PDF fuente, esas técnicas (plantilla de 8 bloques, restricciones en positivo, few-shot,
salida JSON) están en realidad en **Parte I · Fundamentos** (secciones 1.2–1.7); Parte V es la sección de
ingeniería de producción (secretos, reintentos, costos, versionado, seguridad) — también relevante, pero para
cuando estos prompts corran como código (Fase 2 en adelante), no para la redacción del prompt en sí. Vale la
pena corregir esa referencia en `GUIA_DE_IMPLEMENTACION.md` cuando se retome.

## Agentes

**Decisión 2026-10-12: el sistema no produce video ni reels** (no habrá un agente que genere video). Solo piezas estáticas: post cuadrado, post vertical, historia, carrusel y artículo de blog. Las versiones v2 de Estratega, Copywriter, Diseñador y Analista, y la v4 del Investigador, aplican esta decisión; las v1 se conservan sin cambios porque el baseline de Fase 1 las usó.

| Archivo | Entrada principal | Salida (consumida por) |
|---|---|---|
| `orquestador_v1.md` | Brief mensual de Daniela | Coordina a los otros 5; reporte de cierre de ciclo |
| `investigador_v1.md` a `investigador_v4.md` | Brief mensual | Estratega |
| `estratega_v1.md`, `estratega_v2.md` | Hallazgos del Investigador | Copywriter + Diseñador (tras aprobación de Daniela) |
| `copywriter_v1.md`, `copywriter_v2.md` | Pieza de la parrilla aprobada | Punto de aprobación 2 (junto con Diseñador) |
| `disenador_v1.md`, `disenador_v2.md` | Pieza con copy aprobado | Punto de aprobación 2 (junto con Copywriter) |
| `analista_v1.md`, `analista_v2.md` | Métricas del ciclo anterior | Estratega del siguiente ciclo |

`project_description.md` (raíz de `llms/`) sigue siendo la constitución del proyecto — define los 6 roles y
el flujo general. Estos archivos son la implementación detallada de cada prompt, siguiendo la metodología SDD
de la sección 10 de `GUIA_DE_IMPLEMENTACION.md` (Constitución → Especificación).

## Registro de cambios por versión

| Versión | Cambio (uno por versión) | Hipótesis a medir en MLflow |
|---|---|---|
| `investigador_v2.md` | PROCESO pasa a 5 pasos con reglas de uso de `search_web`: cuántas búsquedas hacer, buscar antes de reportar, citar la URL exacta del resultado y qué hacer si la búsqueda falla. El ejemplo few-shot cita una URL en vez de "búsqueda en Instagram". | Sube `n_tool_calls` y `pct_fuentes_url` contra v1, sin romper el esquema. |
| `investigador_v3.md` | PROCESO pasos 3-5 y la última restricción: los resultados de `search_web` (ya filtrados por relevancia) son fuentes válidas; se revisan uno por uno y se convierte en hallazgo cada uno que se conecte con el objetivo; se descartan resultados individuales, no búsquedas completas; `hallazgos` vacío solo si todas las búsquedas fallaron. Motivo: con v2 + tools v2 el modelo recibió 4 resultados relevantes (incl. "HYROX vs DEKA FIT 2026") y aun así entregó 0 hallazgos. | Sube `n_hallazgos` y `pct_fuentes_url` contra v2 (mismo trigger t2 y tools v2). Riesgo esperado: `schema_valid` puede bajar si copia el `"reel"` del ejemplo. |
| `investigador_v4.md` | Ejemplo few-shot: `formato_sugerido` pasa de `"reel"` a `"carrusel"` (decisión de no producir video). El esquema no cambia. | `schema_valid` = 1 con los mismos hallazgos que v3. |
| `estratega_v2.md` | Quita `reel` de los canales, del esquema y del ejemplo (ahora `carrusel`); instruye plantear cada pieza para que funcione sin video. | La parrilla nunca propone reels. |
| `copywriter_v2.md` | El ejemplo pasa de "pieza de reel" a "pieza de carrusel". | — |
| `disenador_v2.md` | `tipo_de_pieza` solo `foto | grafico_de_texto`; quita `reel` de `formato_instagram`; quita la regla del gancho de 3 s en video; ejemplo reescrito como carrusel 1080×1350 (4:5, sección 6.4 del manual). | Ninguna pieza con `tipo_de_pieza` = video. |
| `analista_v2.md` | Comparación por formato sin reels; ejemplo reescrito con carruseles vs. posts de una imagen. | No recomienda formatos que el sistema no produce. |
