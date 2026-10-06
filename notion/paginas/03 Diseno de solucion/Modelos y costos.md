# 🤖 Modelos y costos (D-67)

Lo que exige la sección 8: modelo/proveedor, versión, prompts, parámetros, costo medido y limitaciones.

| Modelo | Uso | Proveedor | Versión / tag | Parámetros | Costo medido | Memoria | Limitaciones observadas |
|---|---|---|---|---|---|---|---|
| Embeddings | Clasificación, agrupación, búsqueda, ruido | Local (sentence-transformers) | _por confirmar (D-20)_ | Prefijos `query:`/`passage:` | USD 0 · _tiempo de cómputo_ | | |
| LLM principal | Afirmaciones, redacción, contradicciones | Local (Ollama) | _por definir (E0-07)_ | Temperatura 0 · salida JSON · 1 reintento | USD 0 · _tiempo de cómputo_ | | |
| LLM alterno | Solo si se cumple el criterio de D-02 | DeepSeek (API) | _si se usa_ | Igual + tope de costo | _USD y tokens medidos_ | — | |

**Prompts:** base *Prompts* (versión, modelo, parámetros, tokens promedio, costo).
**Tope de costo:** presupuesto máximo de tokens y USD para el proveedor de pago; al alcanzarlo, se vuelve al modelo local.
**Detalle completo:** `docs/modelos.md` en el repositorio, generado al correr el benchmark (E1-18).

## IA frente a baseline (D-66)

| Tarea | IA | Baseline | Métrica |
|---|---|---|---|
| Clasificación temática | Embeddings (opción A/B) | Palabras clave | Macro-F1 con IC |
| Agrupación por evento | Clustering aglomerativo | Jaccard de tokens | Precisión / recall de pares |
| Búsqueda en consultas | Recuperación semántica | BM25 | Recall@5 y abstención correcta |
| Priorización | Puntaje v1.3 | Ranking por fecha | Precision@5 |

Para cada tarea, `docs/ia_vs_baseline.md` documenta **dónde gana la IA y dónde no**, con ejemplos.
