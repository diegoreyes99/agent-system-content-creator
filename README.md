# agents_dopa_final_project

Esta es la carpeta de **construcción real** del sistema de agentes de
marketing de DOPA — solo lo que es parte del sistema en sí (prompts,
código, specs). No hay aquí material de referencia (manual de marca,
briefs del negocio, guías del curso) — eso vive un nivel arriba, en
`sistema_agentes_mkt/`.

Todas las carpetas dentro de este directorio se nombran en inglés.

Pensada para poder subirse a GitHub como repo propio en cualquier momento
(de ahí el `.gitignore` y que ningún archivo aquí tenga secretos reales —
usa `.env`, que está ignorado, nunca lo escribas directo en el código).

## Contenido

- `prompts/` — los 6 prompts de sistema de los agentes (v1), con esquema
  JSON de salida para encadenarse entre sí.
- `specs/` — especificación corta de cada agente (paso "Especificación" de SDD).
- `agents/` — código de cada agente ADK, una carpeta por agente. Hoy: `agents/investigador/`
  (Fase 2; ver su README para correrlo y registrarlo en MLflow).
- `mlruns/` — registro local de MLflow (no se sube a GitHub).
- `baseline/` — Fase 1 de `GUIA_DE_IMPLEMENTACION.md`: script que corre
  los 6 prompts en secuencia contra un modelo local (LM Studio) usando
  Google ADK, como ejercicio puntual de referencia antes de construir el
  primer agente real en Fase 2. Ver `baseline/README.md` para instrucciones.
