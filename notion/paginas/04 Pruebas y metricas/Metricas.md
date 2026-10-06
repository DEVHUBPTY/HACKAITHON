# 🧪 Métricas de la ejecución final

Reportar siempre numerador, denominador, **intervalo de confianza del 95 % (bootstrap)** y fallos. No esconder errores tras un promedio (D-57).

| Métrica | Meta | Numerador | Denominador | Resultado | IC 95 % | Fallos (IDs) |
|---|---|---|---|---|---|---|
| Cobertura de citas | 100% | | | | | |
| Validez de sustento (revisión humana) | ≥90% | | | | | |
| Abstención correcta | ≥80% | | | | | |
| Abstenciones incorrectas en preguntas respondibles | — | | | | | |
| Clasificación: macro-F1 IA | — | | | | | |
| Clasificación: macro-F1 baseline | — | | | | | |
| Agrupación: precisión / recall | — | | | | | |
| Precision@5 (vs. editor) | — | | | | | |
| Precision@5 del baseline "ranking por fecha" | — | | | | | |
| Componentes casi constantes en el snapshot | 0 | | | | | |
| Casos alto + insuficiente (tabla rango × estado) | ≥ 1 | | | | | |
| Estabilidad del top 5 (cambios por peso ±5) | — | | | | | |
| Búsqueda: recall@5 semántica | — | | | | | |
| Búsqueda: recall@5 BM25 (baseline) | — | | | | | |
| Latencia mediana · consulta | ≤15 s | | | | | |
| Latencia p95 · consulta | — | | | | | |
| Latencia mediana · paquete completo | — | | | | | |
| Latencia p95 · paquete completo | — | | | | | |
| Tasa de rechazo del validador (por regla y modelo) | — | | | | | |
| Borradores parciales (secciones vacías) | — | | | | | |
| Tipo de afirmación correcto (revisión humana) | — | | | | | |
| Tokens por consulta | — | | | | | |
| Costo por consulta | — | | | | | |
| Tiempo manual vs. asistido (n = …) | — | | | | | |
| Acuerdo entre etiquetadores (kappa, 20 titulares) | — | | | | | |
| Validez: parcial / tipo incorrecto (aparte) | — | | | | | | |
| Tasa de aceptación / corrección / descarte | — | | | | | |
| Motivos de descarte | — | | | | | |
| Tiempo de revisión por caso | — | | | | | |
| % de afirmaciones editadas por la persona | — | | | | | |
| Correcciones con advertencias del validador | — | | | | | |

**Entorno declarado:** _equipo, modelo, versión_
**Etiquetado:** _tamaño de la muestra y método_
**Evaluación de ranking:** _3 cortes con especialista / exploratoria n = 1_
**Parámetros:** origen y validación de cada número en *Registro de parámetros*.


**Cómo se mide cada fila:** ver *Protocolo de evaluación*.

**No se mide ni se infiere:** exactitud de un modelo de fraude, aumento de audiencia, rentabilidad, reducción de riesgo bancario, ni si una noticia es verdadera o falsa.

**Evaluación reservada:** la ejecuta el jurado con `eval.run_benchmark --archivo`; sus resultados se agregan aquí si se comparten.
