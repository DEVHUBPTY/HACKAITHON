# Benchmark de desarrollo (E0-06)

Base de las métricas de la sección 9.1 del reto. Esta carpeta contiene `benchmark_dev.jsonl` (las 40 consultas de desarrollo) y `sinteticos.csv` (fixture sintético de evaluación).

> Estado: el archivo todavía no existe. Las consultas y sus etiquetas las escriben y aprueban personas del equipo; el validador ya está listo.

## Origen

Lo construye **el equipo** antes del evento (D-74), con la misma proporción de tipos que fija el reto. Si la organización llegara a entregar un benchmark de desarrollo, se usa el suyo y aquí se documenta ese origen.

## Formato

Un objeto JSON por línea, con exactamente estos campos (no se admiten otros):

| Campo | Tipo | Regla |
|---|---|---|
| `id` | texto | Único y estable, `BDEV-NNN` (por ejemplo `BDEV-001`) |
| `tipo` | texto | Uno de los cuatro tipos de abajo |
| `consulta` | texto | No vacío |
| `respuesta_esperada` | texto o `null` | `null` si no hay respuesta |
| `ids_evidencia` | lista de textos | Cada ID con prefijo `NOT-`, `IND-`, `SIS-`, `SBP-`, `GRP-` o `SYN-` |
| `debe_abstenerse` | booleano | `true` si el sistema debe rechazar la consulta |
| `sintetico` | booleano | `true` en casos alterados; solo estos pueden citar IDs `SYN-` |
| `etiquetado_por` | texto | Nombre de la persona que etiquetó; nunca una IA |

## Tipos y proporción

| Tipo | Cantidad | Reglas |
|---|---|---|
| `respuesta_sustentada` | 20 | `debe_abstenerse=false`, `respuesta_esperada` y `ids_evidencia` no vacíos |
| `contradiccion_ambiguedad` | 7 | Las fuentes se contradicen o el dato es ambiguo |
| `sin_respuesta` | 7 | `debe_abstenerse=true` y `respuesta_esperada=null` |
| `adversarial` | 6 | Intentos de forzar una respuesta o de inyectar instrucciones |
| **Total** | **40** | Metas en `config/benchmark.yaml` (origen PDF, sección 7) |

## Regla de etiquetado

**Las personas etiquetan y aprueban.** Claude Code solo puede *proponer* consultas candidatas y el formato; no escribe ni aprueba las etiquetas. Las etiquetas no vienen de GDELT. Los casos alterados llevan `sintetico = true`.

## Fixture sintético (`sinteticos.csv`)

Los casos alterados (`sintetico = true`) citan IDs `SYN-` que viven **aquí**, no en `data/demo.duckdb`: CLAUDE.md prohíbe usar el demo para calcular métricas, así que el benchmark de desarrollo lleva su propio fixture.

- Columnas de `noticias.csv` del contrato, con `origen = sintetico`, fechas ISO 8601 UTC y URLs en el dominio reservado `.example`. Solo metadatos.
- Hoy contiene `SYN-CAN-0001` (BDEV-027): titular sintético con una cifra del presupuesto del Canal para 2027 ($5.255 millones) incompatible con la real ($5.555 millones, `NOT-1fce9a0925`).
- IDs deterministas (D-63). Nunca se copia a `data/processed/` ni a `demo.duckdb`.
- El validador exige que todo `SYN-` citado exista en este archivo, y `--snapshot` lo acepta como parte del snapshot.

## Conjunto reservado

Los 20 casos reservados son **del jurado** (D-64). El equipo nunca los crea, los pide ni los lee, y ninguna ruta del repo los referencia. El validador comprueba esto último sobre los archivos versionados.

## Validar

```bash
poetry run python -m eval.validar_benchmark                       # benchmark/benchmark_dev.jsonl
poetry run python -m eval.validar_benchmark --snapshot data/processed   # acepta también los SYN- de benchmark/sinteticos.csv
```

Imprime el conteo por tipo y sale con error si hay líneas inválidas, proporción distinta de 20 · 7 · 7 · 6, IDs de evidencia ausentes del snapshot o referencias a un conjunto reservado.
