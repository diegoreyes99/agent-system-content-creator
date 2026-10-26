# Rúbrica humana — Estratega

Las métricas automáticas revisan la forma (esquema, fechas, formatos, temas
cubiertos, embudo coherente, competidores). Esta rúbrica mide lo que solo una
persona puede juzgar: si la parrilla es una buena estrategia para DOPA.

Se califica **la parrilla completa**, no cada pieza, en Excel:
`rate_estratega.py export <carpeta del eval>` crea `calificacion.xlsx` con una
pestaña por parrilla (estrategia, volumen, mezcla, fechas clave del brief y
todas las piezas) y una pestaña "Calificaciones"; después
`rate_estratega.py import <carpeta>` registra las calificaciones. Para cada
versión basta una muestra de unas 6 parrillas.

## Criterios (1 a 3)

### 1. Coherencia con el negocio
- **3**: Toda la parrilla empuja la prioridad y la meta del mes; la prioridad secundaria tiene su lugar.
- **2**: En general sí, pero hay piezas que no aportan a la prioridad.
- **1**: La parrilla no responde a lo que pide el brief.

### 2. Calendario
- **3**: Eventos, ofertas y cierres bien ubicados (con anticipación), ritmo parejo y nada fuerte en las fechas a evitar.
- **2**: Uno o dos detalles de fechas (una pieza tarde, algo en una fecha a evitar).
- **1**: Las fechas no tienen lógica o contradicen al brief.

### 3. Volumen y mezcla del embudo
- **3**: El número de piezas y la mezcla (descubrimiento, consideración, conversión, fidelización) tienen sentido para la prioridad y están bien justificados; se calienta al público antes de pedirle la acción.
- **2**: Razonable, pero con una etapa claramente de más o de menos, o una justificación débil.
- **1**: Demasiado o muy poco, o casi todo en una sola etapa sin razón.

### 4. Temas descriptivos y variados
- **3**: Cada tema se entiende (qué cubre, desde qué ángulo, para quién) y la parrilla no se siente repetitiva: los temas que se repiten tienen ángulos distintos.
- **2**: Temas claros pero repetitivos, o variados pero vagos.
- **1**: Temas genéricos o la misma idea una y otra vez.

### 5. Accionabilidad
- **3**: El Copywriter y el Diseñador podrían trabajar cada pieza con lo que dice.
- **2**: La mayoría sí; algunas piezas necesitan más contexto.
- **1**: Hay que volver a pensar las piezas.

### 6. Fidelidad al conocimiento de DOPA
- **3**: Todo dato de DOPA (ofertas, fechas, horarios, cupos, clases, público) sale del brief o del conocimiento; los supuestos están marcados como supuestos.
- **2**: Exagera o mezcla algo.
- **1**: Inventa ofertas, eventos, clases o datos.

## Cómo se usa el resultado
- Las calificaciones quedan en `ratings.csv` dentro de la carpeta del eval y en MLflow como `human_<criterio>_mean`.
- Un modelo o un prompt nuevo se adopta solo si no baja en **fidelidad** ni en **coherencia con el negocio**, y sube o se mantiene en el resto.
