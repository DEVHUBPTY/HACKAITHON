# Métricas del sistema

> **BORRADOR — métricas provisionales** · JUICIO PROVISIONAL DEL ASISTENTE, NO HUMANO (D-101): se rehace a mano en C-09; no reportar como juicio de una persona.

Generada el 2026-10-09T03:07:52Z desde el commit `2a7af9d` con `poetry run python -m scripts.pagina_metricas`. Ninguna cifra está escrita a mano: cada una sale del archivo que se indica. Toda proporción lleva numerador, denominador e IC 95 %.

**Origen del juicio:** `humano` = lo decidió una persona (las etiquetas de clasificación y agrupación las propone el asistente y una persona las revisa y aprueba una por una, D-85) · **PROVISIONAL** = lo decidió el asistente (D-101) y se rehace en C-09 · `automático` = automático (sin juicio humano: lo calcula el código contra una referencia).

## Resumen

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Abstención correcta (consultas sin respuesta) | 100.0 % | 7 de 7 | 100.0 % – 100.0 % (Wilson 64.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 80.0 % |
| Abstenciones incorrectas (respondibles rechazadas) | 0.0 % | 0 de 30 | 0.0 % – 0.0 % (Wilson 0.0 % – 11.3 %) | automático | `metricas.json` | fallos: ninguno · sin meta; se reporta |
| Cobertura de citas (respuestas de la consulta) | 100.0 % | 84 de 84 | 100.0 % – 100.0 % (Wilson 95.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 100 % |
| Recall@5 por evidencias esperadas · semántica (IA) | 64.0 % | 32 de 50 | 42.6 % – 100.0 % | automático | `metricas.json` | — |
| Recall@5 por evidencias esperadas · BM25 (baseline) | 48.0 % | 24 de 50 | 32.1 % – 80.0 % | automático | `metricas.json` | — |
| Afirmaciones sustentadas | 96.7 % | 29 de 30 | 90.0 % – 100.0 % (Wilson 83.3 % – 99.4 %) | humano | `metricas.json` | fallos: GRP-39773bed5a/A4 · meta 90 % sobre la estimación puntual |
| Macro-F1 de clasificación · IA (e5/A) | 0.629 | n = 100 | 0.427 – 0.774 | humano | `ia_vs_baseline.json` | — |
| Macro-F1 de clasificación · baseline | 0.601 | n = 100 | 0.399 – 0.749 | humano | `ia_vs_baseline.json` | — |
| Precision@5 · sistema | 0.0 % | 0 de 5 | 0.0 % – 43.5 % | humano | `precision_at_5.json` | fallos: GRP-5e6531917f, GRP-21ad932d54, GRP-4d8b340bd9, GRP-a329f4e91e, GRP-29baaf270e |
| Precision@5 · baseline por fecha de publicación | 20.0 % | 1 de 5 | 3.6 % – 62.5 % | humano | `precision_at_5.json` | fallos: GRP-1dc52c45ff, GRP-50d72e2b04, GRP-a03bab5b02, GRP-1627d09497 |
| Variantes cuyo top 5 no cambia de temas | 86.3 % | 44 de 51 | 74.3 % – 93.2 % | automático | `sensibilidad.json` | cada peso ±5 puntos y cada supuesto ±20 % |
| Latencia p50 · Consulta (punta a punta, local, sin LLM) | 0.0125 s | n = 40 | 0.0004 – 0.0128 s | automático | `metricas.json` | — |
| Latencia p50 · Paquete completo de borrador | 6.36 s | n = 12 | 5.04 – 7.69 s | automático | `metricas.json` | — |
| Costo por paquete (mediana, cota superior) | 0.0031 USD | n = 12 | 0.0024 – 0.0038 USD | automático | `metricas.json` | deepseek/deepseek-flash, medido 2026-10-07T04:20:13Z |
| Unidades rechazadas · deepseek/deepseek-flash | 22.1 % | 33 de 149 | 16.2 % – 29.5 % | automático | `metricas.json` | afirmaciones y secciones, re-validadas con el validador actual |

## Pruebas de aceptación

Pruebas de aceptación T01–T10: Pasa 9, Pendiente 1 (de 10). Es una matriz de aceptación, no una muestra: no lleva IC.

| Prueba | Estado | Resultado observado |
|---|---|---|
| T01 · Archivo con fechas inválidas y nulos | Pasa | 58 de 58 pruebas pasan |
| T02 · Tres registros del mismo evento | Pasa | 7 de 7 pruebas pasan |
| T03 · Noticia antigua recirculada | Pasa | 14 de 14 pruebas pasan |
| T04 · Cifra anual del Banco Mundial | Pasa | 76 de 76 pruebas pasan |
| T05 · Dos afirmaciones incompatibles | Pasa | 28 de 28 pruebas pasan |
| T06 · Consulta sin respuesta en el corpus | Pasa | 7 de 7 pruebas pasan |
| T07 · Fuente que exige ignorar instrucciones | Pasa | 25 de 25 pruebas pasan |
| T08 · Caso de prioridad alta | Pasa | 49 de 49 pruebas pasan |
| T09 · Brief editorial o boletín bancario | Pasa | 37 de 37 pruebas pasan |
| T10 · Sin internet durante la demo | Pendiente | 9 de 9 pruebas pasan; pendiente el ensayo C-04 con Wi-Fi apagado y su evidencia en Notion; el test cubre el recorrido con snapshot y caché |

## Benchmark de desarrollo: citas y abstención

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Abstención correcta (consultas sin respuesta) | 100.0 % | 7 de 7 | 100.0 % – 100.0 % (Wilson 64.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 80.0 % |
| Abstención correcta (incluye adversariales que debían abstenerse) | 100.0 % | 10 de 10 | 100.0 % – 100.0 % (Wilson 72.2 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Abstenciones incorrectas (respondibles rechazadas) | 0.0 % | 0 de 30 | 0.0 % – 0.0 % (Wilson 0.0 % – 11.3 %) | automático | `metricas.json` | fallos: ninguno · sin meta; se reporta |
| Cobertura de citas (respuestas de la consulta) | 100.0 % | 84 de 84 | 100.0 % – 100.0 % (Wilson 95.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno · meta 100 % |
| Cobertura de citas (con validador de citas) | 100.0 % | 84 de 84 | 100.0 % – 100.0 % (Wilson 95.6 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Borradores: afirmaciones factuales con cita válida | 100.0 % | 43 de 43 | 100.0 % – 100.0 % (Wilson 91.8 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Borradores: afirmaciones factuales que pasan el validador | 100.0 % | 43 de 43 | 100.0 % – 100.0 % (Wilson 91.8 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |
| Borradores: inferencias e hipótesis con base válida | 100.0 % | 11 de 11 | 100.0 % – 100.0 % (Wilson 74.1 % – 100.0 %) | automático | `metricas.json` | fallos: ninguno |

- Umbral de Consulta (0.840): con 30 preguntas fuera del corpus escritas por una persona (C-12) la abstención correcta es 24/30 = 80 % (IC95 62.7 %–90.5 %, cumple la meta justo) y la abstención incorrecta 0/10; recalibrar a 0.857 rechaza preguntas legítimas del corpus y no se adoptó (docs/consulta.md, C-12).

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
| Afirmaciones sustentadas | 96.7 % | 29 de 30 | 90.0 % – 100.0 % (Wilson 83.3 % – 99.4 %) | humano | `metricas.json` | fallos: GRP-39773bed5a/A4 · meta 90 % sobre la estimación puntual |
| Afirmaciones parcialmente sustentadas | 3.3 % | 1 de 30 | 0.0 % – 10.0 % (Wilson 0.6 % – 16.7 %) | humano | `metricas.json` | — |
| Afirmaciones con tipo incorrecto | 0.0 % | 0 de 30 | 0.0 % – 0.0 % (Wilson 0.0 % – 11.3 %) | humano | `metricas.json` | — |

- Meta de 90.0 %: cumple con la estimación puntual (96.7 %), no cumple con el límite inferior de Wilson (83.3 %). El criterio oficial es la estimación puntual (protocolo, sección 4).

## Clasificación y agrupación: IA contra baseline

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Macro-F1 de clasificación · IA (e5/A) | 0.629 | n = 100 | 0.427 – 0.774 | humano | `ia_vs_baseline.json` | — |
| Macro-F1 de clasificación · baseline | 0.601 | n = 100 | 0.399 – 0.749 | humano | `ia_vs_baseline.json` | — |
| Macro-F1: diferencia IA − baseline | 0.028 | n = 100 | -0.244 – 0.310 | humano | `ia_vs_baseline.json` | — |
| Exactitud del clasificador · IA (e5/A) | 71.7 % | 33 de 46 | 57.5 % – 82.7 % | humano | `ia_vs_baseline.json` | — |
| Exactitud del clasificador · baseline | 60.9 % | 28 de 46 | 46.5 % – 73.6 % | humano | `ia_vs_baseline.json` | — |
| Precisión de pares (validación cruzada) · IA | 100.0 % | 91 de 91 | 100.0 % – 100.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |
| Recall de pares (validación cruzada) · IA | 97.9 % | 91 de 93 | 86.6 % – 100.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |
| Precisión de pares (validación cruzada) · baseline | 100.0 % | 65 de 65 | 100.0 % – 100.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |
| Recall de pares (validación cruzada) · baseline | 69.9 % | 65 de 93 | 44.6 % – 95.0 % | humano | `ia_vs_baseline.json` | IC por remuestreo de titulares |

- Clasificación (macro-F1): **sin diferencia demostrable**; discordantes: solo IA 10, solo baseline 5 (n = 100).
- Agrupación, diferencia IA − baseline en precision (n = 100 titulares): 0.000, IC 95 % 0.000 – 0.000 → **sin diferencia demostrable**.
- Agrupación, diferencia IA − baseline en recall (n = 100 titulares): 0.280, IC 95 % 0.011 – 0.521 → **gana la IA**.
- Agrupación, diferencia IA − baseline en f1 (n = 100 titulares): 0.166, IC 95 % 0.005 – 0.357 → **gana la IA**.

## Ranking: Precision@5, estabilidad y distribución

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Precision@5 · sistema | 0.0 % | 0 de 5 | 0.0 % – 43.5 % | humano | `precision_at_5.json` | fallos: GRP-5e6531917f, GRP-21ad932d54, GRP-4d8b340bd9, GRP-a329f4e91e, GRP-29baaf270e |
| Precision@5 · baseline por fecha de publicación | 20.0 % | 1 de 5 | 3.6 % – 62.5 % | humano | `precision_at_5.json` | fallos: GRP-1dc52c45ff, GRP-50d72e2b04, GRP-a03bab5b02, GRP-1627d09497 |
| Variantes cuyo top 5 no cambia de temas | 86.3 % | 44 de 51 | 74.3 % – 93.2 % | automático | `sensibilidad.json` | cada peso ±5 puntos y cada supuesto ±20 % |
| Variantes que conservan el mismo orden | 74.5 % | 38 de 51 | 61.1 % – 84.5 % | automático | `sensibilidad.json` | — |
| Temas del top 5 que se conservan (sobre todas las variantes) | 96.9 % | 247 de 255 | 93.9 % – 98.4 % | automático | `sensibilidad.json` | — |
| Grupos con rango de prioridad «alto» | 66.7 % | 46 de 69 | 54.9 % – 76.6 % | automático | `puntaje.json` | — |
| Grupos con rango de prioridad «medio» | 33.3 % | 23 de 69 | 23.4 % – 45.1 % | automático | `puntaje.json` | — |
| Grupos con rango de prioridad «bajo» | 0.0 % | 0 de 69 | 0.0 % – 5.3 % | automático | `puntaje.json` | — |

- Precision@5: sistema 0 de 5, baseline 1 de 5; los IC se solapan: **sin diferencia demostrable**. Pruebas: 1 (fecha de corte 2026-10-08T03:35:18Z, 69 candidatos); exploratoria; especialista: no.
- Distribución del puntaje P (n = 69 grupos): mínimo 46.358, mediana 72.460, máximo 86.079, desviación 8.931. Componentes casi constantes: ninguno.

## Eficiencia, tokens y costo

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Latencia p50 · Consulta (punta a punta, local, sin LLM) | 0.0125 s | n = 40 | 0.0004 – 0.0128 s | automático | `metricas.json` | — |
| Latencia p95 · Consulta (punta a punta, local, sin LLM) | 0.0144 s | n = 40 | 0.0136 – 0.0197 s | automático | `metricas.json` | — |
| Latencia p50 · Primera respuesta del borrador | 4.09 s | n = 12 | 3.06 – 4.52 s | automático | `metricas.json` | — |
| Latencia p95 · Primera respuesta del borrador | 5.67 s | n = 12 | 4.29 – 6.05 s | automático | `metricas.json` | — |
| Latencia p50 · Paquete completo de borrador | 6.36 s | n = 12 | 5.04 – 7.69 s | automático | `metricas.json` | — |
| Latencia p95 · Paquete completo de borrador | 12.41 s | n = 12 | 7.23 – 17.16 s | automático | `metricas.json` | — |
| Latencia p50 · Llamada al LLM | 1.94 s | n = 41 | 1.86 – 2.05 s | automático | `metricas.json` | — |
| Latencia p95 · Llamada al LLM | 2.85 s | n = 41 | 2.30 – 2.94 s | automático | `metricas.json` | — |
| Latencia p50 del paquete editorial (n pequeño) | 17.16 s | n = 1 | 17.16 – 17.16 s | automático | `metricas.json` | — |
| Latencia p50 del paquete investigacion (n pequeño) | 5.99 s | n = 11 | 4.23 – 7.58 s | automático | `metricas.json` | — |
| Tokens de entrada por paquete (mediana) | 5528.5 | n = 12 | 4559.0 – 7392.5 | automático | `metricas.json` | — |
| Tokens de salida por paquete (mediana) | 1066.5 | n = 12 | 834.5 – 1365.0 | automático | `metricas.json` | — |
| Costo por paquete (mediana, cota superior) | 0.0031 USD | n = 12 | 0.0024 – 0.0038 USD | automático | `metricas.json` | deepseek/deepseek-flash, medido 2026-10-07T04:20:13Z |

- Meta sugerida: mediana ≤ 15 s. Consulta: cumple; paquete por tipo: editorial no cumple, investigacion cumple.
- Costo total estimado de la corrida de 12 paquetes: USD 0.0408; tokens totales 76825 de entrada y 14759 de salida.
- **Supuesto del proyecto (D-97):** el contador de costo sobreestima ≈ 2.6 × respecto de la consola del proveedor (una comparación puntual); las cifras de USD son una cota superior conservadora, no la factura.
- Contador acumulado del proyecto: 1846393 tokens y USD 0.8712 (local, ignorado por git).

## Rechazos del validador

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Unidades rechazadas · deepseek/deepseek-flash | 22.1 % | 33 de 149 | 16.2 % – 29.5 % | automático | `metricas.json` | afirmaciones y secciones, re-validadas con el validador actual |
| Regla «afirmacion_desconocida» · seccion:brief · deepseek/deepseek-flash | 50.0 % | 1 de 2 | 9.4 % – 90.5 % | automático | `metricas.json` | — |
| Regla «base_invalida» · afirmacion · deepseek/deepseek-flash | 3.0 % | 3 de 99 | 1.0 % – 8.5 % | automático | `metricas.json` | — |
| Regla «causalidad» · afirmacion · deepseek/deepseek-flash | 13.1 % | 13 de 99 | 7.8 % – 21.2 % | automático | `metricas.json` | — |
| Regla «causalidad» · seccion:enfoque · deepseek/deepseek-flash | 17.6 % | 3 de 17 | 6.2 % – 41.0 % | automático | `metricas.json` | — |
| Regla «cifra_no_coincide» · seccion:brief · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |
| Regla «cifra_no_coincide» · seccion:guion · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |
| Regla «cifra_no_coincide» · seccion:resumen_web · deepseek/deepseek-flash | 50.0 % | 1 de 2 | 9.4 % – 90.5 % | automático | `metricas.json` | — |
| Regla «detalle_sin_cita» · seccion:preguntas · deepseek/deepseek-flash | 7.7 % | 1 de 13 | 1.4 % – 33.3 % | automático | `metricas.json` | — |
| Regla «enfoque_como_hecho» · seccion:enfoque · deepseek/deepseek-flash | 52.9 % | 9 de 17 | 31.0 % – 73.8 % | automático | `metricas.json` | — |
| Regla «hipotesis_sin_condicional» · afirmacion · deepseek/deepseek-flash | 1.0 % | 1 de 99 | 0.2 % – 5.5 % | automático | `metricas.json` | — |
| Regla «limite_palabras» · seccion:guion · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |
| Regla «nombre_nuevo» · seccion:resumen_web · deepseek/deepseek-flash | 50.0 % | 1 de 2 | 9.4 % – 90.5 % | automático | `metricas.json` | — |
| Regla «sin_atribucion» · seccion:enfoque · deepseek/deepseek-flash | 17.6 % | 3 de 17 | 6.2 % – 41.0 % | automático | `metricas.json` | — |
| Regla «sin_atribucion» · seccion:guion · deepseek/deepseek-flash | 100.0 % | 2 de 2 | 34.2 % – 100.0 % | automático | `metricas.json` | — |

- Borradores del benchmark: modo cache, 12 grupos; estados con_vacios 4, completo 8. Grupos con fallo: ninguno.

## Revisión humana: personas y revisor provisional

| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |
|---|---|---|---|---|---|---|
| Tasa de aceptación (aprobados como borrador) · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Tasa de corrección · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Tasa de descarte · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Afirmaciones editadas · personas | sin datos | n = 0 | — | humano | `revision.json` | — |
| Tasa de aceptación (aprobados como borrador) · PROVISIONAL (asistente) | 100.0 % | 1 de 1 | 20.7 % – 100.0 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |
| Tasa de corrección · PROVISIONAL (asistente) | 0.0 % | 0 de 1 | 0.0 % – 79.3 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |
| Tasa de descarte · PROVISIONAL (asistente) | 0.0 % | 0 de 1 | 0.0 % – 79.3 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |
| Afirmaciones editadas · PROVISIONAL (asistente) | 0.0 % | 0 de 8 | 0.0 % – 32.4 % | **PROVISIONAL** · asistente_provisional (D-101) | `revision.json` | — |

- Casos abiertos: 6. Decididos por una persona: 0. Decididos por el revisor provisional: 1.
- **JUICIO PROVISIONAL DEL ASISTENTE, NO HUMANO (D-101): se rehace a mano en C-09; no reportar como juicio de una persona.**

## Reproducibilidad

- Registro del manifest: commit `3df0978`, árbol con cambios al registrar: **sí**; corte del snapshot 2026-10-08T03:35:18Z; hash del snapshot `4503952d97fb`.
- Commit desde el que se generó: `2a7af9d`. El registro es de otro commit: confirmar con `--verificar` antes de afirmar que se reproduce.
- LLM: deepseek/deepseek-flash, temperatura 0.0, semilla 0; embeddings minilm y e5 con revisión fijada.
- Salidas deterministas con hash: 33. Borradores en caché: sin_cache 9, completo 1, con_vacios 2.
- Comprobación: `HF_HUB_OFFLINE=1 poetry run python -m scripts.reproducir --verificar` (sale con 1 si algo difiere).
- Limitación declarada: el texto de los borradores del LLM se reproduce solo desde data/cache_llm/; sin caché puede variar

## Coherencia entre fuentes

- El top 5 del sistema difiere entre precision_at_5.json e ia_vs_baseline.json: una de las dos salidas es anterior a un cambio del ranking.

## Fuentes

| Archivo | Commit | Fecha del commit | Fecha dentro del archivo |
|---|---|---|---|
| `outputs/metricas.json` | bf39099 | 2026-10-08T17:52:00-05:00 | 2026-10-08T22:51:50Z |
| `outputs/ia_vs_baseline.json` | 88de277 | 2026-10-08T15:13:26-05:00 | — |
| `outputs/precision_at_5.json` | e512db2 | 2026-10-08T16:28:48-05:00 | 2026-10-08T03:35:18Z |
| `outputs/clasificacion.json` | 737f8f2 | 2026-10-08T14:21:50-05:00 | — |
| `outputs/agrupacion.json` | a479628 | 2026-10-06T19:49:01-05:00 | — |
| `outputs/sensibilidad.json` | 15e7e31 | 2026-10-08T15:13:45-05:00 | 2026-10-08T03:35:18Z |
| `outputs/puntaje.json` | 15e7e31 | 2026-10-08T15:13:45-05:00 | — |
| `outputs/pruebas.csv` | 81e3946 | 2026-10-08T22:00:48-05:00 | — |
| `data/manifest.json` | ccb2a8e | 2026-10-07T23:07:47-05:00 | 2026-10-08T03:35:18Z |
| `eval/etiquetas.csv` | fdfe422 | 2026-10-08T09:59:37-05:00 | — |
| `docs/prueba_tiempo.md` | bf39099 | 2026-10-08T17:52:00-05:00 | — |
| `outputs/revision.json` | 458f4f0 | 2026-10-08T17:47:45-05:00 | — |
| `outputs/costo_llm.json` | sin versionar (generado en local) | — | — |

## Limitaciones

- **Precision@5 con n = 5 temas** en 1 fecha de corte, sin especialista editorial: es exploratoria. Los IC (sistema 0.000–0.434; baseline 0.036–0.625) se solapan: no hay diferencia demostrable. Los temas de un mismo corte no son independientes (nota de la fuente).
- **Selección ciega solo a medias:** quien eligió los temas conocía la selección y el resultado anteriores (revisión D-78 de E1-19). No es la selección independiente de un editor.
- **Juicios provisionales del asistente (D-101), pendientes de C-09:** secciones: Revisión humana: personas y revisor provisional. Se rehacen a mano; hasta entonces no se reportan como juicio de una persona.
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
