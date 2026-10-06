# 🔢 Registro de parámetros

Todo número que use el sistema está aquí, con su **origen** y **cómo se valida**. Los valores viven en `config/*.yaml`; este documento explica de dónde salen.

**Origen:** `PDF` = lo fija el reto · `Práctica` = práctica reconocida · `Calibrado` = se ajusta con datos etiquetados · `Supuesto` = elección razonable del equipo, todavía no demostrada.

> Un **supuesto** se presenta siempre como supuesto, en el pitch y en Notion.

## Puntaje de atención

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Pesos R · I · U · N · E | 30 · 25 · 20 · 15 · 10 | PDF | X02 (sensibilidad) · Precision@5 |
| Rangos | bajo [0,40) · medio [40,70) · alto [70,100] | PDF | — |
| Desempate | Mayor U, luego menor ID | PDF | Test |
| Partes de R (foco · temática) | 0.5 · 0.5 | Supuesto | X02 |
| Foco (Panamá sujeto · otro país que afecta) | 1 · 0.5 | Supuesto | Revisión editorial |
| Similitudes en percentil | — | Calibrado | X04 (distribución) |
| Partes de I (subtema · geográfico) | 0.5 · 0.5 | Supuesto | X02 |
| Alcance por subtema | Tabla en YAML | Supuesto (criterio editorial) | Precision@5 y revisión editorial |
| Alcance geográfico | nacional 1 · provincial 0.6 · local 0.3 · desconocido 0.5 | Supuesto | X02 |
| Ventana de urgencia U | 1 a < 24 h → 0 a 7 días | Supuesto | X02 |
| Partes de E (procedencias · oficial · identificable) | 0.5 · 0.3 · 0.2 | Supuesto | X02 |
| Tope de procedencias en E | 3 | Supuesto | X02 |

## Estado de evidencia

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Procedencias para "parcial" / "suficiente" | 2 | Práctica (regla periodística de las dos fuentes independientes) | Revisión editorial |
| Dato oficial obligatorio si hay cifras | — | PDF (secciones 7 y 9: toda cifra con evidencia) | Test |

## Organizar y contextualizar

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Umbral de agrupación | Por definir | Calibrado (D-16) | F1 de pares con etiquetas · curva documentada |
| Ventana de agrupación | 7 días | Supuesto | X02 |
| Similitud para "mismo texto" en procedencias | 0.95 | Supuesto | Test CU-03 · etiquetas |
| Umbral "sin tema" | Por definir | Calibrado | Etiquetas humanas |
| Criterio opción A vs. B | IC 95 % de la diferencia de macro-F1 excluye 0 | Práctica estadística | Bootstrap |
| Umbrales de ruido | Por definir | Calibrado | X01 (precisión/recall) |
| Coincidencia de sismos | ± 2 días | Supuesto | Revisión con la exploración (E0-09) |
| Magnitud mínima USGS | 3 | PDF (sección 6) | — |

## Consulta y generación

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Umbral de abstención | Por definir | Calibrado con el benchmark de desarrollo | Abstención correcta vs. abstenciones incorrectas |
| Temperatura | 0 | Práctica (reproducibilidad) | — |
| Reintentos ante JSON inválido | 1 | Supuesto | Tasa de JSON inválido |
| Cambio de proveedor: latencia | Mediana > 15 s | PDF (meta de 9.1) | Métrica de latencia |
| Cambio de proveedor: rechazo · JSON inválido | > 20 % · > 1 de 10 | Supuesto | E0-07 |

## Salidas

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Brief · copy · resumen bancario | ≤ 250 · ≤ 80 · ≤ 250 palabras | PDF | Test |
| Guion | 45–60 s | PDF | X03 |
| Guion en palabras | 110–150 | Calibrado | X03 (cronometrado) |
| Preguntas | Exactamente 3 | PDF | Test |
| Título · titulares · resumen web · hashtags | ≤ 14 · 2–3 · ≤ 120 · ≤ 2 | Supuesto (convención propia) | Tasa de corrección en revisión |
| Transiciones sin cita por sección | Máximo en YAML | Supuesto | Revisión editorial |

## Evaluación

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Titulares etiquetados | ~100 | Supuesto (tiempo disponible) | Se reporta con IC |
| Muestra de validez de sustento | ≥ 30 afirmaciones | PDF | Se reporta con IC |
| Benchmark | 60 (30 · 10 · 10 · 10), 40 desarrollo / 20 reservadas **del jurado** | PDF | — |
| Intervalos de confianza | 95 %, bootstrap de 1.000 remuestreos | Práctica estadística | — |
| Semillas aleatorias | Fijas en `config/` (etiquetado, bootstrap, clustering si aplica) | Práctica (reproducibilidad) | `scripts.reproducir` (D-65) |
| Benchmark del equipo (si la organización no lo entrega) | 40 de desarrollo: 20 · 7 · 7 · 6 | PDF (proporciones de la sección 7) | `eval.validar_benchmark` |
| Sensibilidad X02 | Pesos ± 5; parámetros supuestos ± 20 % | Supuesto | — |
| Precision@5 | 3 fechas de corte si hay editor; si no, n = 1 y exploratoria | PDF (exploratoria sin especialista) | — |
| Duración de la demo | 4 min | PDF | Ensayo cronometrado |
