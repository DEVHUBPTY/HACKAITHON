# Métricas del sistema

> **BORRADOR — métricas provisionales** · JUICIO PROVISIONAL DEL ASISTENTE, NO HUMANO (D-101): se rehace a mano en C-09; no reportar como juicio de una persona.

Generada el 2026-10-07T21:55:31Z desde el commit `47e956c` con `poetry run python -m scripts.pagina_metricas`. Ninguna cifra está escrita a mano: cada una sale del archivo que se indica. Toda proporción lleva numerador, denominador e IC 95 %.

**Origen del juicio:** `humano` = lo decidió una persona (las etiquetas de clasificación y agrupación las propone el asistente y una persona las revisa y aprueba una por una, D-85) · **PROVISIONAL** = lo decidió el asistente (D-101) y se rehace en C-09 · `automático` = automático (sin juicio humano: lo calcula el código contra una referencia).

## Resumen

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Abstención correcta (consultas sin respuesta) | 100.0 % | 7 de 7 | 100.0 % – 100.0 % (Wilson 64.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 80.0 % |
| Abstenciones incorrectas (respondibles rechazadas) | 6.7 % | 2 de 30 | 0.0 % – 16.7 % (Wilson 1.8 % – 21.3 %) | automático | `metricas.json` | fallos: BDEV-004, BDEV-017 · sin meta; se reporta |
| Cobertura de citas (respuestas de la consulta) | 100.0 % | 56 de 56 | 100.0 % – 100.0 % (Wilson 93.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 100 % |
| Recall@5 por evidencias esperadas · semántica (IA) | 64.0 % | 32 de 50 | 42.6 % – 100.0 % | automático | `metricas.json` | — |
| Recall@5 por evidencias esperadas · BM25 (baseline) | 48.0 % | 24 de 50 | 32.1 % – 80.0 % | automático | `metricas.json` | — |
| Afirmaciones sustentadas | 96.7 % | 29 de 30 | 90.0 % – 100.0 % (Wilson 83.3 % – 99.4 %) | **PROVISIONAL** · asistente_provisional (D-101) | `metricas.json` | fallos: GRP-39773bed5a/A4 · meta 90 % sobre la estimación puntual |
| Macro-F1 de clasificación · IA | 0.545 | n = 100 | 0.380 – 0.669 | humano | `ia_vs_baseline.json` | — |
| Macro-F1 de clasificación · baseline | 0.545 | n = 100 | 0.338 – 0.666 | humano | `ia_vs_baseline.json` | — |
| Precision@5 · sistema | 20.0 % | 1 de 5 | 3.6 % – 62.5 % | **PROVISIONAL** · asistente_provisional (D-101) | `precision_at_5.json` | fallos: GRP-21ad932d54, GRP-038c4f0643, GRP-84a6b3a04b, GRP-39dfe8d714 |
| Precision@5 · baseline por fecha de publicación | 0.0 % | 0 de 5 | 0.0 % – 43.5 % | **PROVISIONAL** · asistente_provisional (D-101) | `precision_at_5.json` | fallos: GRP-f9e3ba0bd2, GRP-87e128925b, GRP-0c210ad795, GRP-1df3ab1e22, GRP-0f8fb5a5bb |
| Variantes cuyo top 5 no cambia de temas | 60.5 % | 26 de 43 | 45.6 % – 73.6 % | automático | `sensibilidad.json` | cada peso ±5 puntos y cada supuesto ±20 % |
| Latencia p50 · Consulta (punta a punta, local, sin LLM) | 0.0068 s | n = 40 | 0.0003 – 0.0071 s | automático | `metricas.json` | — |
| Latencia p50 · Paquete completo de borrador | 6.3615 s | n = 12 | 5.0380 – 7.6900 s | automático | `metricas.json` | — |
| Costo por paquete (mediana, cota superior) | 0.0031 USD | n = 12 | 0.0024 – 0.0038 USD | automático | `metricas.json` | deepseek/deepseek-flash, medido 2026-10-07T04:20:13Z |
| Unidades rechazadas · deepseek/deepseek-flash | 26.7 % | 12 de 45 | 16.0 % – 41.0 % | automático | `metricas.json` | afirmaciones y secciones, re-validadas con el validador actual |

## Pruebas de aceptación

Pruebas de aceptación T01–T10: Pasa 8, Pendiente 2 (de 10). Es una matriz de aceptación, no una muestra: no lleva IC.

| Prueba | Estado | Resultado observado |
|---|---|---|
| T01 · Archivo con fechas inválidas y nulos | Pasa | 58 de 58 pruebas pasan |
| T02 · Tres registros del mismo evento | Pasa | 7 de 7 pruebas pasan |
| T03 · Noticia antigua recirculada | Pasa | 14 de 14 pruebas pasan |
| T04 · Cifra anual del Banco Mundial | Pasa | 73 de 73 pruebas pasan |
| T05 · Dos afirmaciones incompatibles | Pasa | 28 de 28 pruebas pasan |
| T06 · Consulta sin respuesta en el corpus | Pasa | 7 de 7 pruebas pasan |
| T07 · Fuente que exige ignorar instrucciones | Pasa | 25 de 25 pruebas pasan |
| T08 · Caso de prioridad alta | Pasa | 49 de 49 pruebas pasan |
| T09 · Brief editorial o boletín bancario | Pendiente | 23 de 23 pruebas pasan; pendiente la parte del boletín bancario (E2-02); el test cubre solo el brief editorial |
| T10 · Sin internet durante la demo | Pendiente | 9 de 9 pruebas pasan; pendiente el ensayo C-04 con Wi-Fi apagado y su evidencia en Notion; el test cubre el recorrido con snapshot y caché |

## Benchmark de desarrollo: citas y abstención

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Abstención correcta (consultas sin respuesta) | 100.0 % | 7 de 7 | 100.0 % – 100.0 % (Wilson 64.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 80.0 % |
| Abstención correcta (incluye adversariales que debían abstenerse) | 100.0 % | 10 de 10 | 100.0 % – 100.0 % (Wilson 72.2 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Abstenciones incorrectas (respondibles rechazadas) | 6.7 % | 2 de 30 | 0.0 % – 16.7 % (Wilson 1.8 % – 21.3 %) | automático | `metricas.json` | fallos: BDEV-004, BDEV-017 · sin meta; se reporta |
| Cobertura de citas (respuestas de la consulta) | 100.0 % | 56 de 56 | 100.0 % – 100.0 % (Wilson 93.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 100 % |
| Cobertura de citas (con validador de citas) | 100.0 % | 56 de 56 | 100.0 % – 100.0 % (Wilson 93.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Borradores: afirmaciones factuales con cita válida | 100.0 % | 11 de 11 | 100.0 % – 100.0 % (Wilson 74.1 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Borradores: afirmaciones factuales que pasan el validador | 100.0 % | 11 de 11 | 100.0 % – 100.0 % (Wilson 74.1 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Borradores: inferencias e hipótesis con base válida | 100.0 % | 3 de 3 | 100.0 % – 100.0 % (Wilson 43.9 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |

## Búsqueda: semántica contra BM25

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Recall@5 por evidencias esperadas · semántica (IA) | 64.0 % | 32 de 50 | 42.6 % – 100.0 % | automático | `metricas.json` | — |
| Consultas con todas sus evidencias en el top 5 · semántica (IA) | 85.0 % | 17 de 20 | 65.0 % – 100.0 % (Wilson 64.0 % – 94.8 %) | automático | `metricas.json` | fallos: BDEV-004 (1), BDEV-009 (15), BDEV-015 (2) |
| Recall@5 por evidencias esperadas · BM25 (baseline) | 48.0 % | 24 de 50 | 32.1 % – 80.0 % | automático | `metricas.json` | — |
| Consultas con todas sus evidencias en el top 5 · BM25 (baseline) | 60.0 % | 12 de 20 | 39.9 % – 80.0 % (Wilson 38.7 % – 78.1 %) | automático | `metricas.json` | fallos: BDEV-004 (1), BDEV-009 (15), BDEV-010 (1), BDEV-011 (2), BDEV-012 (2), BDEV-013 (1), BDEV-014 (2), BDEV-015 (2) |

- Diferencia semántica − BM25 en la fracción de evidencias recuperadas: 0.160 (n = 20 consultas, IC 95 % 0.038 – 0.429); veredicto de la fuente: **gana la IA**.

## Validez de sustento (revisión de afirmaciones)

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Afirmaciones sustentadas | 96.7 % | 29 de 30 | 90.0 % – 100.0 % (Wilson 83.3 % – 99.4 %) | **PROVISIONAL** · asistente_provisional (D-101) | `metricas.json` | fallos: GRP-39773bed5a/A4 · meta 90 % sobre la estimación puntual |
| Afirmaciones parcialmente sustentadas | 3.3 % | 1 de 30 | 0.0 % – 10.0 % (Wilson 0.6 % – 16.7 %) | **PROVISIONAL** · asistente_provisional (D-101) | `metricas.json` | — |
| Afirmaciones con tipo incorrecto | 0.0 % | 0 de 30 | 0.0 % – 0.0 % (Wilson 0.0 % – 11.3 %) | **PROVISIONAL** · asistente_provisional (D-101) | `metricas.json` | — |

- Meta de 90.0 %: cumple con la estimación puntual (96.7 %), no cumple con el límite inferior de Wilson (83.3 %). El criterio oficial es la estimación puntual (protocolo, sección 4); el resultado es **provisional** mientras los veredictos los haya dado el asistente.

## Clasificación y agrupación: IA contra baseline

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Macro-F1 de clasificación · IA | 0.545 | n = 100 | 0.380 – 0.669 | humano | `ia_vs_baseline.json` | — |
| Macro-F1 de clasificación · baseline | 0.545 | n = 100 | 0.338 – 0.666 | humano | `ia_vs_baseline.json` | — |
| Macro-F1: diferencia IA − baseline | 0.000 | n = 100 | -0.214 – 0.267 | humano | `ia_vs_baseline.json` | — |
| Exactitud del clasificador · IA | 54.7 % | 35 de 64 | 42.6 % – 66.3 % | humano | `ia_vs_baseline.json` | — |
| Exactitud del clasificador · baseline | 45.3 % | 29 de 64 | 33.7 % – 57.4 % | humano | `ia_vs_baseline.json` | — |
| Precisión de pares (validación cruzada) · IA | 88.0 % | 125 de 142 | 68.0 % – 100.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |
| Recall de pares (validación cruzada) · IA | 95.4 % | 125 de 131 | 83.0 % – 100.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |
| Precisión de pares (validación cruzada) · baseline | 100.0 % | 86 de 86 | 100.0 % – 100.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |
| Recall de pares (validación cruzada) · baseline | 65.6 % | 86 de 131 | 44.3 % – 86.8 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |

- Clasificación (macro-F1): **sin diferencia demostrable**; discordantes: solo IA 12, solo baseline 6 (n = 100).
- Agrupación, diferencia IA − baseline en precision (n = 100 titulares): -0.120, IC 95 % -0.320 – 0.000 → **sin diferencia demostrable**.
- Agrupación, diferencia IA − baseline en recall (n = 100 titulares): 0.298, IC 95 % 0.091 – 0.504 → **gana la IA**.
- Agrupación, diferencia IA − baseline en f1 (n = 100 titulares): 0.123, IC 95 % -0.038 – 0.308 → **sin diferencia demostrable**.

## Ranking: Precision@5, estabilidad y distribución

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Precision@5 · sistema | 20.0 % | 1 de 5 | 3.6 % – 62.5 % | **PROVISIONAL** · asistente_provisional (D-101) | `precision_at_5.json` | fallos: GRP-21ad932d54, GRP-038c4f0643, GRP-84a6b3a04b, GRP-39dfe8d714 |
| Precision@5 · baseline por fecha de publicación | 0.0 % | 0 de 5 | 0.0 % – 43.5 % | **PROVISIONAL** · asistente_provisional (D-101) | `precision_at_5.json` | fallos: GRP-f9e3ba0bd2, GRP-87e128925b, GRP-0c210ad795, GRP-1df3ab1e22, GRP-0f8fb5a5bb |
| Variantes cuyo top 5 no cambia de temas | 60.5 % | 26 de 43 | 45.6 % – 73.6 % | automático | `sensibilidad.json` | cada peso ±5 puntos y cada supuesto ±20 % |
| Variantes que conservan el mismo orden | 41.9 % | 18 de 43 | 28.4 % – 56.7 % | automático | `sensibilidad.json` | — |
| Temas del top 5 que se conservan (sobre todas las variantes) | 90.7 % | 195 de 215 | 86.1 % – 93.9 % | automático | `sensibilidad.json` | — |
| Grupos con rango de prioridad «alto» | 70.0 % | 42 de 60 | 57.5 % – 80.1 % | automático | `puntaje.json` | — |
| Grupos con rango de prioridad «medio» | 30.0 % | 18 de 60 | 19.9 % – 42.5 % | automático | `puntaje.json` | — |
| Grupos con rango de prioridad «bajo» | 0.0 % | 0 de 60 | 0.0 % – 6.0 % | automático | `puntaje.json` | — |

- Precision@5: sistema 1 de 5, baseline 0 de 5; los IC se solapan: **sin diferencia demostrable**. Pruebas: 1 (fecha de corte 2026-10-07T00:41:03Z, 60 candidatos); exploratoria; especialista: no.
- Distribución del puntaje P (n = 60 grupos): mínimo 46.645, mediana 77.215, máximo 90.448, desviación 11.476. Componentes casi constantes: N.

## Eficiencia, tokens y costo

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Latencia p50 · Consulta (punta a punta, local, sin LLM) | 0.0068 s | n = 40 | 0.0003 – 0.0071 s | automático | `metricas.json` | — |
| Latencia p95 · Consulta (punta a punta, local, sin LLM) | 0.0078 s | n = 40 | 0.0073 – 0.0083 s | automático | `metricas.json` | — |
| Latencia p50 · Primera respuesta del borrador | 4.0940 s | n = 12 | 3.0615 – 4.5160 s | automático | `metricas.json` | — |
| Latencia p95 · Primera respuesta del borrador | 5.6663 s | n = 12 | 4.2930 – 6.0480 s | automático | `metricas.json` | — |
| Latencia p50 · Paquete completo de borrador | 6.3615 s | n = 12 | 5.0380 – 7.6900 s | automático | `metricas.json` | — |
| Latencia p95 · Paquete completo de borrador | 12.4079 s | n = 12 | 7.2316 – 17.1550 s | automático | `metricas.json` | — |
| Latencia p50 · Llamada al LLM | 1.9410 s | n = 41 | 1.8600 – 2.0510 s | automático | `metricas.json` | — |
| Latencia p95 · Llamada al LLM | 2.8490 s | n = 41 | 2.3000 – 2.9410 s | automático | `metricas.json` | — |
| Latencia p50 del paquete editorial (n pequeño) | 17.1550 s | n = 1 | 17.1550 – 17.1550 s | automático | `metricas.json` | — |
| Latencia p50 del paquete investigacion (n pequeño) | 5.9920 s | n = 11 | 4.2340 – 7.5820 s | automático | `metricas.json` | — |
| Tokens de entrada por paquete (mediana) | 5528.5 | n = 12 | 4559.0 – 7392.5 | automático | `metricas.json` | — |
| Tokens de salida por paquete (mediana) | 1066.5 | n = 12 | 834.5 – 1365.0 | automático | `metricas.json` | — |
| Costo por paquete (mediana, cota superior) | 0.0031 USD | n = 12 | 0.0024 – 0.0038 USD | automático | `metricas.json` | deepseek/deepseek-flash, medido 2026-10-07T04:20:13Z |

- Meta sugerida: mediana ≤ 15 s. Consulta: cumple; paquete por tipo: editorial no cumple, investigacion cumple.
- Costo total estimado de la corrida de 12 paquetes: USD 0.0408; tokens totales 76825 de entrada y 14759 de salida.
- **Supuesto del proyecto (D-97):** el contador de costo sobreestima ≈ 2.6 × respecto de la consola del proveedor (una comparación puntual); las cifras de USD son una cota superior conservadora, no la factura.
- Contador acumulado del proyecto: 1603871 tokens y USD 0.7552 (local, ignorado por git).

## Rechazos del validador

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Unidades rechazadas · deepseek/deepseek-flash | 26.7 % | 12 de 45 | 16.0 % – 41.0 % | automático | `metricas.json` | afirmaciones y secciones, re-validadas con el validador actual |
| Regla «causalidad» · afirmacion · deepseek/deepseek-flash | 11.1 % | 3 de 27 | 3.9 % – 28.1 % | automático | `metricas.json` | — |
| Regla «causalidad» · seccion:enfoque · deepseek/deepseek-flash | 25.0 % | 1 de 4 | 4.6 % – 69.9 % | automático | `metricas.json` | — |
| Regla «cifra_no_coincide» · seccion:guion · deepseek/deepseek-flash | 50.0 % | 1 de 2 | 9.4 % – 90.5 % | automático | `metricas.json` | — |
| Regla «enfoque_como_hecho» · seccion:enfoque · deepseek/deepseek-flash | 50.0 % | 2 de 4 | 15.0 % – 85.0 % | automático | `metricas.json` | — |
| Regla «hipotesis_sin_condicional» · afirmacion · deepseek/deepseek-flash | 3.7 % | 1 de 27 | 0.7 % – 18.3 % | automático | `metricas.json` | — |
| Regla «limite_palabras» · seccion:guion · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |
| Regla «nombre_nuevo» · seccion:copy_digital · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |
| Regla «nombre_nuevo» · seccion:titulares · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |

- Borradores del benchmark: modo cache, 12 grupos; estados con_vacios 2, sin_cache 9, completo 1. Grupos con fallo: GRP-79f3183472, GRP-21ad932d54, GRP-038c4f0643, GRP-5e6531917f, GRP-39dfe8d714, GRP-1b52bb958d, GRP-87e128925b, GRP-39773bed5a, GRP-5ab17b45cd.

## Revisión humana: personas y revisor provisional

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Tasa de aceptación (aprobados como borrador) · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Tasa de corrección · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Tasa de descarte · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Afirmaciones editadas · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Tasa de aceptación (aprobados como borrador) · PROVISIONAL (asistente) | 100.0 % | 1 de 1 | 20.7 % – 100.0 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |
| Tasa de corrección · PROVISIONAL (asistente) | 100.0 % | 1 de 1 | 20.7 % – 100.0 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |
| Tasa de descarte · PROVISIONAL (asistente) | 0.0 % | 0 de 1 | 0.0 % – 79.3 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |
| Afirmaciones editadas · PROVISIONAL (asistente) | 0.0 % | 0 de 6 | 0.0 % – 39.0 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |

- Casos abiertos: 1. Decididos por una persona: 0. Decididos por el revisor provisional: 1.
- **JUICIO PROVISIONAL DEL ASISTENTE, NO HUMANO (D-101): se rehace a mano en C-09; no reportar como juicio de una persona.**

## Reproducibilidad

- Registro del manifest: commit `3df0978`, árbol con cambios al registrar: **sí**; corte del snapshot 2026-10-07T00:41:03Z; hash del snapshot `d0ae54537df7`.
- Commit actual del repo: `47e956c`. El registro es de otro commit: confirmar con `--verificar` antes de afirmar que se reproduce.
- LLM: deepseek/deepseek-flash, temperatura 0.0, semilla 0; embeddings minilm y e5 con revisión fijada.
- Salidas deterministas con hash: 33. Borradores en caché: sin_cache 9, completo 1, con_vacios 2.
- Comprobación: `HF_HUB_OFFLINE=1 poetry run python -m scripts.reproducir --verificar` (sale con 1 si algo difiere).
- Limitación declarada: el texto de los borradores del LLM se reproduce solo desde data/cache_llm/; sin caché puede variar

## Coherencia entre fuentes

- Sin discrepancias entre las fuentes revisadas.

## Fuentes

| Archivo | Commit | Fecha del commit | Fecha dentro del archivo |
|---|---|---|---|
| `outputs/metricas.json` | 3df0978 | 2026-10-07T15:37:09-05:00 | 2026-10-07T20:31:59Z |
| `outputs/ia_vs_baseline.json` | 260a72d | 2026-10-07T16:55:30-05:00 | — |
| `outputs/precision_at_5.json` | 40253af | 2026-10-07T15:16:18-05:00 | 2026-10-07T00:41:03Z |
| `outputs/clasificacion.json` | aca0356 | 2026-10-07T14:00:52-05:00 | — |
| `outputs/agrupacion.json` | a479628 | 2026-10-06T19:49:01-05:00 | — |
| `outputs/sensibilidad.json` | 40253af | 2026-10-07T15:16:18-05:00 | 2026-10-07T00:41:03Z |
| `outputs/puntaje.json` | 40253af | 2026-10-07T15:16:18-05:00 | — |
| `outputs/pruebas.csv` | e9bf8a3 | 2026-10-07T06:46:06-05:00 | — |
| `data/manifest.json` | 15b86f1 | 2026-10-07T15:50:44-05:00 | 2026-10-07T00:41:03Z |
| `eval/etiquetas.csv` | 993beaa | 2026-10-07T07:35:27-05:00 | — |
| `docs/prueba_tiempo.md` | 0f9accb | 2026-10-07T07:09:49-05:00 | — |
| `outputs/revision.json` | 9311df2 | 2026-10-07T16:45:15-05:00 | — |
| `outputs/costo_llm.json` | sin versionar (generado en local) | — | — |

## Limitaciones

- **Precision@5 con n = 5 temas** en 1 fecha de corte, sin especialista editorial: es exploratoria. Los IC (sistema 0.036–0.625; baseline 0.000–0.434) se solapan: no hay diferencia demostrable. Los temas de un mismo corte no son independientes (nota de la fuente).
- **Selección ciega solo a medias:** quien eligió los temas conocía la selección y el resultado anteriores (revisión D-78 de E1-19). No es la selección independiente de un editor.
- **Juicios provisionales del asistente (D-101), pendientes de C-09:** secciones: Ranking: Precision@5, estabilidad y distribución, Revisión humana: personas y revisor provisional, Validez de sustento (revisión de afirmaciones). Se rehacen a mano; hasta entonces no se reportan como juicio de una persona.
- **Recalcular tras C-10:** cualquier mejora de ranking, clasificación o generación cambia estas cifras; hay que volver a correr los módulos de `eval/` y regenerar esta página (nueva corrida).
- **Benchmark de desarrollo (n = 40 consultas):** El benchmark de desarrollo se construyó con el equipo y las reglas por patrón de la consulta se redactaron viendo esas mismas consultas: las cifras de abstención son optimistas, no independientes. n es pequeño (decenas de consultas): los intervalos son anchos y las metas son orientativas.
- **Baselines:** el veredicto «sin diferencia demostrable» significa que los IC se solapan, no que los métodos sean iguales.
- **Ahorro de tiempo: no medido.** Pruebas realizadas: 0 (`docs/prueba_tiempo.md`); mide a una persona y queda para C-09.
- **Costo:** el contador sobreestima ≈ 2.6 × (supuesto del proyecto, D-97); las cifras de USD son cota superior.
- **Revisión humana:** sin casos decididos por una persona; las tasas humanas están en «sin datos».
- **SBP (D-116):** la fuente D se versiona con riesgo aceptado (el aviso legal de la SBP restringe la reproducción y la redistribución sin autorización escrita). Esta página no usa cifras de la SBP, pero si el repositorio o el paquete de entrega se hacen públicos hay que pedir la autorización o retirar esos valores.
- No se infiere audiencia, rentabilidad ni reducción de riesgo; un titular es lo que un medio reporta, no un hecho.

## Preguntas abiertas

1. **¿Se publica ya en Notion como borrador o se espera a C-09 y C-10?** Recomendación: publicarla una vez ahora marcada «BORRADOR — métricas provisionales» y actualizar esa misma página al regenerarla; así el equipo ve el estado real y nada provisional se presenta como humano.
2. **¿Qué hacer si una salida de `eval/` es anterior a un cambio de la base?** La sección «Coherencia entre fuentes» lo avisa pero no lo corrige. Recomendación: antes de la entrega, volver a correr los módulos de `eval/` y regenerar la página en una sola pasada (condición de C-02 tras C-10).
