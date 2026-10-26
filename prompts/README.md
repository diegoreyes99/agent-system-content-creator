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
| `orquestador_v1.md`, `orquestador_v2.md` | Brief mensual de Daniela | Coordina a los otros 5; reporte de cierre de ciclo |
| `investigador_v1.md` a `investigador_v7.md` | Brief mensual | Dani elige los temas; su selección va al Estratega |
| `estratega_v1.md` a `estratega_v5.md` | Temas aprobados por Dani (`seleccion.json`) y brief | Copywriter + Diseñador (tras aprobación de Daniela) |
| `copywriter_v1.md`, `copywriter_v2.md` | Pieza de la parrilla aprobada | Punto de aprobación 3 (junto con Diseñador) |
| `disenador_v1.md`, `disenador_v2.md` | Pieza con copy aprobado | Punto de aprobación 3 (junto con Copywriter) |
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
| `investigador_v5.md` | PROCESO reescrito (excepción a "un cambio por versión", decidida a propósito): (1) búsquedas por ángulo, cortas, sin año ni nombres de gimnasios; (2) regla mecánica: cada resultado que pasó el filtro se convierte en hallazgo (máx. 6), el modelo ya no decide si "aplica a DOPA"; (3) `tema` describe el resultado, no copia la búsqueda; prioridad definida contra la prioridad principal/secundaria del brief; (4) `tendencias_de_formato` solo con formatos vistos en los resultados; (5) ejemplos sin relación con ningún brief del golden set; restricción explícita sin reels ni video. Motivo: eval de v4 (2026-10-14) con 0 hallazgos en 10 de 10 corridas aun con resultados relevantes; los ejemplos del v3/v4 (Hyrox vs Deka, reto 21 días) solo funcionaban en briefs sobre Deka. | Sube `useful_run_rate` y `n_hallazgos` manteniendo `pct_fuentes_verificadas` en 100%; sube `search_pass_rate`. |
| `investigador_v6.md` | Cambio de rol (decisiones de Diego, 2026-10-14): el Investigador ya no decide formatos (se quitan `formato_sugerido` y `tendencias_de_formato`, los decide el Estratega); propone una lista de temas ordenada con `id`, `que_dice_la_fuente` y hasta 5 `recomendado` para que Dani elija (punto de aprobación nuevo); temas genéricos e informativos, nunca promociones de otros negocios (se vale buscar en Instagram); busca el tema detrás de cada evento de DOPA, nunca su nombre. | Esquema v6 válido; `pct_fuentes_verificadas` en 100%; ningún tema que sea promoción de un negocio; ninguna búsqueda con nombres de eventos de DOPA. |
| `investigador_v7.md` | A partir de la calificación humana del v6 (2026-10-15: relevancia 2.6, fidelidad 2.4, accionabilidad 2.4, 2 de 10 promociones). (1) Separación de roles: el Investigador solo investiga; `relevancia_dopa` pasa a `responde_a` (a qué parte del brief responde, sin proponer cómo usarlo ni conectarlo con eventos u ofertas); no investiga temas operativos de DOPA (cómo llegar, horarios, precios). (2) Fuentes: usa `tipo_fuente` (certificada / web / red social, calculado en código) para ordenar, y nunca recomienda temas de redes sociales. (3) Fuentes débiles: nunca recomienda temas con `contenido_suficiente: false`. Un tema por fuente. Va con la herramienta v3. | Sube la fidelidad y baja el % de promociones en la rúbrica; ningún recomendado de red social o con poco contenido (`n_recomendados_corregidos` debería ir a 0). |
| `estratega_v3.md` | Tres puntos de aprobación (temas, parrilla, textos y diseño): recibe los temas que Dani aprobó (`seleccion.json`, con `origen` investigador o dani) en vez de todos los hallazgos; no agrega ni descarta temas sin explicarlo; con fuente `competidor` usa solo la información general sin citar al negocio; él conecta los temas con eventos, ofertas y fechas del brief. | Cada tema aprobado aparece en la parrilla; ninguna pieza menciona a un competidor. |
| `orquestador_v2.md` | Tres puntos de aprobación: agrega el de los temas del Investigador (paso 3) y pasa al Estratega solo los temas aprobados. | Nunca activa al Estratega sin una selección de Dani. |
| `estratega_v4.md` | Rediseño para el agente ADK (excepción a "un cambio por versión": es la primera versión que corre como agente, así que es la línea base de su eval). Rol de experto en marketing digital de corto y largo plazo; solo Instagram (post, carrusel, historia); el volumen lo decide y lo justifica (`criterio_de_volumen`) con `instagram_standards.md` y el contexto operativo; objetivos de negocio de la lista de referencia (`tipo_objetivo` + `objetivo` medible); temas descriptivos; herramientas `get_month_calendar` y `search_dopa_knowledge` (RAG v01); dos tipos de pieza: de temas aprobados (todos deben aparecer, `tema_ref`) y del negocio, que salen del brief aunque no vengan de un tema (ofertas, promociones, eventos, retos, clases especiales; `elemento_del_brief`), decisión de Diego 2026-10-26; embudo de marketing (etapa por pieza, mezcla de referencia por prioridad y secuencia, sección 9 de los estándares); ejemplo de un mes inventado para no sesgar el golden set. | Línea base del eval del Estratega. |
| `estratega_v5.md` | Variedad (revisión de Diego de la primera parrilla, 2026-10-26: más de 3 piezas sobre fuerza, se sentía repetitiva). Cada pieza lleva `tema_central`; si un tema central da 3 piezas o más, de cada 3, 2 lo tratan de frente y al menos 1 desde un ángulo distinto o un tema relacionado (recuperación, mitos, técnica, alimentación, historia de una socia, el coach), sin inventar datos. | La parrilla se siente menos repetitiva en la revisión humana, sin bajar la cobertura de temas ni la coherencia del embudo. |
