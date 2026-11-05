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
   | Un tema del Investigador (`tema_ref`) | Lo que dice la fuente, la URL, el tipo de fuente y el **texto del artículo guardado en `seleccion.json`** (`texto_fuente`, o `fragmento_busqueda` si no se pudo extraer) |
   | El brief (`elemento_del_brief`) | Solo la sección del brief que corresponde: condiciones de la oferta, fecha y horario del evento, cupo, costo, cómo apartar lugar |
   | Un contenido green (`green_ref`) | La ficha del tema green, con su regla de no usar cifras |

3. **Reglas de texto de Instagram:** la sección 10 de `agents/shared/instagram_standards.md` (largo del caption, primera línea, copy in por formato, CTA por etapa, hashtags).
4. **Herramienta `search_dopa_knowledge`** (RAG, etiquetas `voz`, `audiencia`, `negocio`): la personalidad y el manifiesto de la marca, las frases reales de Ana y Rosa y datos del negocio que necesite. Con tope de llamadas, igual que el Estratega.

## Salida (JSON por pieza)

- `id` de la pieza.
- `copy_in`: lista de textos, uno por lámina (carrusel) o pantalla (historia); en post único, uno (o vacío si la imagen habla sola).
- `imagen_por_lamina`: lista con la descripción de la imagen de cada lámina o pantalla, en el mismo orden que `copy_in` (en post, una). **Decisión de Diego, 2026-11-05:** el número de láminas o pantallas depende de cómo el Copywriter reparte el texto, así que él describe la imagen de cada una, en todos los formatos. Parte de la **idea visual** del Estratega (la dirección y el tipo: imagen o gráfico) y de la dirección fotográfica del Manual de Identidad (sección 5.3: luz cálida, esfuerzo y comunidad, diversidad real; se permiten fotos de stock o generadas, sin hacerse pasar por DOPA). Describe qué se ve, no encuadres ni técnica: la ejecución es del Diseñador.
- `copy_out`: el caption completo con el CTA dentro y los hashtags al final. Las historias no llevan copy out (decisión de Diego, 2026-11-05): su CTA va en el copy in.
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
- **Rúbrica humana:** 7 criterios de 1 a 3, cada uno anclado en los documentos de negocio del RAG (ver sección "Rúbrica").
- **Métrica automática extra:** `copy_in` e `imagen_por_lamina` con el mismo número de elementos.

## Rúbrica (borrador 2026-11-05, decisión de Diego: cada criterio se apega a los documentos de negocio)

Cada criterio dice de qué documento sale. El Copywriter recibe esos mismos documentos (por el RAG), así que se le califica con lo que tuvo a la mano. 3 = cumple, 2 = cumple a medias, 1 = no cumple.

| # | Criterio | Fuente | Qué se pregunta |
|---|---|---|---|
| 1 | **Personalidad de marca** | Manual §1 *Personalidad de marca*; Brief §10 *Percepción de marca* | ¿Suena **fuerte, enérgica, segura y profesional**? ¿Retadora y aspiracional pero accesible: intensa sin ser agresiva, premium sin intimidar, cálida sin ser casual o desordenada? |
| 2 | **Valores y manifiesto** | Brief §2 *Valores rectores* y *Manifiesto*; Manual §1 *Valores*, *Manifiesto* y *Diferenciadores* | ¿Transmite disciplina, comunidad, compromiso y entrenar con propósito ("entrenamiento con estructura y comunidad con propósito")? ¿Nada de moda o entretenimiento superficial? |
| 3 | **Le habla a su público** | Fichas de Ana y Rosa: *D. Objetivos*, *E. Dolores*, *I. Lenguaje y frases textuales*; Manual §1 *A quién le hablamos* | ¿Toca lo que le importa a esa persona (Ana: eficiencia, reto, espacio seguro sin sentirse observada; Rosa: salud, no lastimarse, acompañamiento, sentirse en familia)? ¿Suena a como ellas hablan, sin copiar sus frases? |
| 4 | **Fidelidad al negocio** | Brief §5 *Servicios y tarifas*, §13 y el brief del mes; Fichas *F. Objeciones* (respuesta de DOPA); fuente del tema | ¿Cada dato (precio, horario, cupo, fecha, condición) es correcto? ¿Las objeciones se responden con lo que DOPA de verdad ofrece (aforo de 15–20, estación asignada, coach presente, regresiones y progresiones)? ¿Sin promesas de resultados que no se pueden cumplir? |
| 5 | **Acción alineada al objetivo** | Fichas *G. Triggers de conversión*; estándares §10.3 (CTA por etapa) | ¿El CTA corresponde a la etapa y al objetivo de la pieza, y apela a lo que mueve a ese público a actuar? |
| 6 | **Gancho y concisión** | Brief §9 *Qué ha funcionado y qué no* (sin gancho se pierde a la audiencia); estándares §10 (conciso y con impacto) | ¿La primera línea y la portada enganchan? ¿Cada frase aporta, sin relleno? |
| 7 | **Imagen por lámina** | Manual §5.3 *Fotografía* y §1 *A quién le hablamos*; idea visual del Estratega | ¿Cada imagen va con su texto, sigue la idea visual aprobada y la dirección fotográfica (luz cálida, esfuerzo y comunidad, diversidad real), y se ve intensa para Ana sin dejar de ser cercana para Rosa? |

Las reglas de forma (hashtags, largos, primera línea de 125 caracteres, copy in e imágenes con el mismo número, ningún competidor, ningún dato sin respaldo) las revisa el código, no la rúbrica.

## Decisiones abiertas (para Diego)

1. ~~Historias sin caption~~ **Decidido (Diego, 2026-11-05):** las historias no llevan copy out; todo su texto va en el copy in, por pantalla.
2. ~~Largos de referencia~~ **Decidido (Diego, 2026-11-05):** se usan como reglas los límites que vienen de las fuentes; los demás son criterio interno provisional y funcionan como **máximos, no metas**: el texto es conciso, al punto y con impacto, nunca largo solo por llenar.
3. **Rúbrica:** propuesta anclada en los documentos de negocio (sección "Rúbrica"); pendiente de confirmar.

## Pendientes antes de construir

- ~~Guardar el texto de la fuente al aprobar el tema~~ **Hecho (2026-11-05):** `seleccion.json` trae `fragmento_busqueda` y `texto_fuente` por tema (ver spec del Investigador).
- Revisar `prompts/copywriter_v2.md` (MVP) como punto de partida del prompt v3.
