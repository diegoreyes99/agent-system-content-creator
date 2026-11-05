# Spec — Copywriter (Fase 2, tercer agente)

*Borrador 2026-11-05, para revisión de Diego antes de construir.*

- **Qué hace:** escribe los textos de cada pieza que Dani aprobó en la parrilla: el **copy in** (texto sobre la imagen, por lámina o pantalla), la **imagen de cada lámina o pantalla** y el **copy out** (caption con su CTA y hashtags). No cambia la estrategia: el qué decir ya viene en la pieza (mensaje clave, ángulo, puntos clave, objetivo); el Copywriter decide **cómo decirlo** con la voz de DOPA. Entrega los textos para el punto de aprobación 3.
- **Unidad de trabajo:** una pieza por llamada al modelo, no la parrilla entera. El paquete es chico, cada pieza se puede rehacer sola cuando Dani pide cambios y un error en una pieza no tira las demás.

## Entrada: el paquete de cada pieza (lo arma el código)

1. **La pieza aprobada** de `parrilla.json`: tema, público, formato, fecha, etapa y objetivo, mensaje clave, ángulo, puntos clave, **idea visual** (tipo e idea principal) y los **comentarios de Dani**.
   Además, las secciones del Manual de Identidad que guían la imagen (3.3 y 5.3), leídas del RAG como en el Estratega.
2. **El origen de la pieza**, que el código adjunta según la referencia que ya trae:

   | La pieza viene de… | Se adjunta |
   |---|---|
   | Un tema del Investigador (`tema_ref`) | Lo que dice la fuente, la URL, el tipo de fuente y el **texto del artículo guardado en `seleccion.json`** (ver Pendientes) |
   | El brief (`elemento_del_brief`) | Solo la sección del brief que corresponde: condiciones de la oferta, fecha y horario del evento, cupo, costo, cómo apartar lugar |
   | Un contenido green (`green_ref`) | La ficha del tema green, con su regla de no usar cifras |

3. **Reglas de texto de Instagram:** la sección 10 de `instagram_standards.md` (largo del caption, primera línea, copy in por formato, CTA por etapa, hashtags).
4. **Herramienta `search_dopa_knowledge`** (RAG, etiquetas `voz`, `audiencia`, `negocio`): la personalidad y el manifiesto de la marca, las frases reales de Ana y Rosa y datos del negocio que necesite. Con tope de llamadas, igual que el Estratega.

## Salida (JSON por pieza)

- `id` de la pieza.
- `copy_in`: lista de textos, uno por lámina (carrusel) o pantalla (historia); en post único, uno (o vacío si la imagen habla sola).
- `imagen_por_lamina`: lista con la descripción de la imagen de cada lámina o pantalla, en el mismo orden que `copy_in` (en post, una). **Decisión de Diego, 2026-11-05:** el número de láminas o pantallas depende de cómo el Copywriter reparte el texto, así que él describe la imagen de cada una, en todos los formatos. Parte de la **idea visual** del Estratega (la dirección y el tipo: imagen o gráfico) y de la dirección fotográfica del Manual de Identidad (sección 5.3: luz cálida, esfuerzo y comunidad, diversidad real; se permiten fotos de stock o generadas, sin hacerse pasar por DOPA). Describe qué se ve, no encuadres ni técnica: la ejecución es del Diseñador.
- `copy_out`: el caption completo con el CTA dentro y los hashtags al final (vacío en historias; ver Decisiones abiertas).
- `cta`: el CTA por separado, para que el código lo revise contra la etapa.
- `hashtags`: lista de 3 a 5.
- `datos_usados`: cada cifra, precio, fecha o cupo del texto y de dónde salió (fuente del tema, brief o RAG), para que el código lo verifique.
- `supuestos`: lo que el Copywriter tuvo que suponer.

En la hoja de Dani se llenan tres columnas separadas del bloque de detalle: **Copy in** e **Imagen por lámina** (numeradas igual: la lámina 2 del Copy in va con la imagen 2) y **Copy out**. En la ronda de aprobación de textos (punto 3) esas columnas pasan a la vista principal.

## Reglas de fidelidad

- **Ningún dato sin respaldo:** cifras, precios, horarios, beneficios de salud o afirmaciones salen del paquete de la pieza o del RAG. Si falta un dato, va en `supuestos`, no en el texto.
- **La fuente es para verificar, no para copiar:** nunca reproduce frases del artículo; escribe con sus palabras y con la voz de DOPA.
- **Competidores:** puede usar la información de una fuente de competidor, pero nunca menciona ni enlaza a ese negocio, ni usa sus hashtags.
- **Contenidos green:** sin cifras ni estudios.
- **Sin promesas de resultados** ("baja 5 kilos en un mes") ni lenguaje que excluya o intimide.
- **CTA acorde a la etapa** (sección 10.3) y solo con canales y condiciones que existen.

## Aprobación (punto 3)

Dani revisa los textos en la misma hoja, pieza por pieza, con el mismo `Estado` y `Comentarios de Dani`. Las piezas en *Cambios* regresan solas al Copywriter con su comentario; solo se rehace lo que Dani pidió.

## Modelo

El Copywriter necesita sobre todo **redactar bien en español de México y sostener la voz de marca**, y ser disciplinado con las reglas; razonar mucho no le hace falta. El costo casi no pesa (unas 16 piezas al mes, centavos de dólar), así que se compara calidad:

- **Base:** Gemini 3.8 Flash (ya configurado), con razonamiento bajo.
- **Retador:** Claude Sonnet 5.5 (requiere cuenta en la Claude Console y conectarlo a ADK con LiteLLM). Precios de referencia por millón de tokens: 3.8 Flash $0.75 / $3.75, Sonnet 5.5 $2.00 / $10.00 (confirmar en la página oficial).
- Mismo eval, misma rúbrica; **la calificación humana decide**, porque la voz y la naturalidad no se miden con código.

## Eval

- **Casos fijos:** piezas reales tomadas de parrillas aprobadas de los evals del Estratega, cubriendo los tres formatos, los dos públicos, las cuatro etapas y los tres orígenes (tema del Investigador, brief y green), más casos difíciles: fuente de competidor, oferta con condiciones y pieza con comentario de Dani.
- **Métricas automáticas** (sección 10.4): hashtags, CTA presente, primera línea, largos, datos sin respaldo, menciones a competidores, JSON válido, costo.
- **Rúbrica humana (borrador, 1 a 3):** voz de marca, naturalidad (suena a CDMX), tono adecuado al público, fidelidad a los datos, CTA acorde al objetivo, gancho de la primera línea, e imágenes por lámina coherentes con el texto y con la idea visual del Estratega.
- **Métrica automática extra:** `copy_in` e `imagen_por_lamina` con el mismo número de elementos.

## Decisiones abiertas (para Diego)

1. **Historias sin caption:** en Instagram las historias no llevan caption. Propuesta: en historias el copy out va vacío y todo el texto va en el copy in (hoy la spec del Estratega dice que el Copy out "siempre tiene texto").
2. **Largos de referencia:** los rangos de caption y de copy in de la sección 10 son criterio interno; revisar si te hacen sentido.
3. **Rúbrica:** confirmar los 6 criterios.

## Pendientes antes de construir

- **Guardar el texto de la fuente al aprobar el tema (cambio en el Investigador):** cuando Dani aprueba un tema, el código descarga el artículo una sola vez y guarda el texto relevante en `seleccion.json`. Así el respaldo queda congelado (igual para el Copywriter, el eval y cualquier revisión) y no depende de que la página siga en línea.
- Mover `instagram_standards.md` a `agents/shared/` e integrar la sección 10 (hoy en `agents/shared/instagram_standards_copy_draft.md`).
- Revisar `prompts/copywriter_v2.md` (MVP) como punto de partida del prompt v3.
