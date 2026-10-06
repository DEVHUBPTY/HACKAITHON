# Elección del modelo local (E0-07)

Aplica el criterio de la decisión **D-02** antes de construir: Ollama es el proveedor primario salvo que la **mediana supere 15 s**, el **validador rechace más del 20 %** o haya **JSON inválido en más de 1 de cada 10 llamadas**. En ese caso DeepSeek pasa a primario (D-80).

## Modelo elegido

**`qwen3.5:9b`** (digest `56671c2ab938…`, Q4_K_M, 9.0 B parámetros). Cumple el criterio D-02 y el indicador de calidad de tipos es claramente mejor que el de `gemma4:12b`. Se escribe como `OLLAMA_MODEL` en `local.env`.

## Cómo se midió

Comando: `poetry run python -m scripts.probar_llm --modelo <tag>` (detalle por llamada en `outputs/probar_llm_<tag>.json`).

- **Muestra:** 5 titulares reales de TVN Panamá del snapshot (`data/processed/noticias.csv`), elegidos de forma determinista (2 nacionales, 1 mundo, 1 tvmax, 1 entretenimiento; los `id_noticia` más bajos de cada tema). Ids: `NOT-0d91fa48b0`, `NOT-220be165b5`, `NOT-19d534ddba`, `NOT-099a437ecb`, `NOT-50c2fa1e7c`.
- **Tarea:** paso 1 de la generación (afirmaciones citadas), con el esquema BORRADOR de `src/esquemas.py` (`AfirmacionesCitadas`; E1-12 lo completa). Reglas en el *system prompt* (`prompts/afirmaciones_citadas.txt`); la evidencia va en `<evidencia>…</evidencia>` en el mensaje de usuario (CLAUDE.md).
- **Llamadas:** 1 de calentamiento (carga en frío, fuera de las estadísticas) + 5 titulares × 4 repeticiones = **n = 20** por modelo. Temperatura 0, semilla 0, `num_ctx` 4096, `num_predict` 1024, pensamiento desactivado, un modelo a la vez y descargado al terminar (`keep_alive` 0).
- **JSON válido:** el texto se parsea y valida con pydantic (tipos, citas obligatorias por tipo, claves desconocidas prohibidas). Además se verifica que cada cita apunte al ID y campo entregados en la evidencia.
- **Latencia:** tiempo de pared de cada llamada (`time.perf_counter`), mediana y p95 por interpolación lineal.
- **IC 95 %:** Wilson para la proporción de JSON válido.
- **Hardware:** un solo Mac con 24 GB de RAM, Ollama 0.34.1, API en `http://localhost:11434`.

## Resultados (n = 20 llamadas por modelo)

| | `qwen3.5:9b` | `gemma4:12b` |
|---|---|---|
| Digest | `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90` | `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b` |
| Parámetros · cuantización | 9.0 B · Q4_K_M | 11.9 B · Q4_K_M |
| JSON válido | 20/20 = 100 % (IC 95 % 83.9–100 %) | 20/20 = 100 % (IC 95 % 83.9–100 %) |
| Citas con ID y campo existentes | 20/20 | 20/20 |
| Latencia mediana | **14.3 s** | **14.5 s** |
| Latencia p95 (mín–máx) | 16.9 s (12.2–18.3) | 16.5 s (12.7–17.2) |
| Velocidad de generación (mediana) | 22.5 tok/s · ≈ 305 tokens por salida | 14.2 tok/s · ≈ 203 tokens por salida |
| Carga en frío (calentamiento) | 16.0 s (carga 1.3 s) | 21.0 s (carga 6.7 s) |
| Memoria, `/api/ps` (`size`) | 6.2 GB | 1.1 GB (*subcuenta*, ver nota) |
| Memoria, RSS del proceso servidor | **7.2 GB** | **9.3 GB** |
| Salidas con tipo `hecho` sobre un titular | 4/20 (20 %; 1 titular de 5) | **20/20 (100 %; 5 de 5)** |
| Pensamiento presente en la respuesta | 0 | 0 |
| Carga del sistema al inicio → fin (1 min) | 3.6 → 12.6 | 12.1 → 4.9 |

Nota sobre la memoria: `/api/ps` de `gemma4:12b` informa 1.1 GB, pero el archivo del modelo pesa 8.0 GB y el proceso servidor tiene 9.3 GB residentes; el valor de `/api/ps` no es confiable para ese modelo (posiblemente parte de los pesos queda mapeada a disco). Por eso el script guarda también el RSS del servidor (`rss_servidor_bytes`) y la comparación usa ese valor.

## Evaluación del criterio D-02

| Criterio | Umbral | `qwen3.5:9b` | `gemma4:12b` |
|---|---|---|---|
| Latencia mediana | ≤ 15 s | 14.3 s: cumple (margen 0.7 s) | 14.5 s: cumple (margen 0.5 s) |
| JSON inválido | ≤ 1 de cada 10 | 0 de 10: cumple | 0 de 10: cumple |
| Rechazo del validador | ≤ 20 % | **No evaluable**: el validador es de E1. Aproximación: salidas con `hecho` sobre un titular, que el validador rechazaría (D-41): 20 % (en el límite) | Aproximación: **100 %** |

Ambos cumplen las dos medidas directas. La tercera no se puede medir todavía; con la aproximación, `gemma4:12b` la incumpliría de forma clara. Su patrón es marcar como `hecho` la fecha de publicación del registro («La noticia fue publicada el 6 de octubre…»), aunque el prompt reserva `hecho` para datos oficiales y conteos. `qwen3.5:9b` lo hizo en 4 de 20 salidas, que son un único titular (`NOT-19d534ddba`) repetido 4 veces con el mismo patrón (fecha); con temperatura 0 las repeticiones no son independientes, así que en realidad es 1 titular de 5 frente a 5 de 5. Es una aproximación a nivel de prompt y no un resultado del validador real.

## Justificación

1. Ambos pasan la latencia y el JSON; la diferencia de 0.2 s en la mediana no es concluyente con n = 20.
2. `qwen3.5:9b` ocupa menos memoria (7.2 GB frente a 9.3 GB de RSS). En un equipo de 24 GB que además corre embeddings locales, DuckDB y Streamlit, esos 2 GB importan.
3. `qwen3.5:9b` respeta mejor la regla «un titular no es un hecho» (4/20 frente a 20/20 con `hecho` mal usado), que es la regla de tipos más delicada del paso 1.
4. `gemma4:12b` genera menos tokens por segundo (14 frente a 22), así que su latencia depende de que sus salidas sean más cortas (2 afirmaciones frente a 3).

## Cómo se desactivó el pensamiento y cómo se pidió JSON estructurado

- **Pensamiento:** parámetro `think: false` de `/api/chat`. Ambos modelos declaran la capacidad `thinking` en `/api/show` y respondieron sin campo `thinking` en las 40 llamadas medidas. Es el control general de Ollama; la documentación no da instrucciones propias para Qwen3.5 y para Gemma 4 indica que se activa con el token `<|think|>` en el *system prompt* (no se usa aquí, y el prompt no lo incluye).
- **Salida estructurada:** el JSON Schema generado desde pydantic (`AfirmacionesCitadas.model_json_schema()`) va en el parámetro `format`; además se incrusta en el *system prompt* y la temperatura es 0, como recomienda la documentación de Ollama, y la respuesta se vuelve a validar con pydantic.
- **Fuentes (consultadas el 2026-10-06):**
  - <https://docs.ollama.com/capabilities/thinking>
  - <https://docs.ollama.com/capabilities/structured-outputs>
  - <https://ollama.com/library/qwen3.5> (etiqueta `qwen3.5:9b`, la `latest`, contexto 256K, capacidad `thinking`)
  - <https://ollama.com/library/gemma4> (variante 12B, control de pensamiento por `<|think|>`)

## Optimizaciones aplicadas

- Pensamiento desactivado (`think: false`) y `num_predict` acotado.
- `num_ctx` 4096 (el prompt usa ≈ 930 tokens), para no reservar el contexto de 256K del modelo.
- `keep_alive` de 10 m durante la prueba y descarga explícita al terminar; la carga en frío se excluye de las estadísticas.
- Sin cuantización propia ni ajuste fino (restricción de la spec): se usan las etiquetas publicadas, ambas Q4_K_M.
- No hizo falta una variante de optimización: ningún modelo falló el criterio.

## Limitaciones

- **n pequeña:** 20 llamadas por modelo sobre 5 titulares. Con temperatura 0 y semilla fija, las 4 repeticiones del mismo titular casi no aportan variación de contenido; aportan variación de latencia. El IC 95 % de 100 % de validez llega solo hasta 83.9 %.
- **Una sola máquina** y con carga ajena variable. Una primera pasada de ambos modelos, hecha con la máquina muy cargada (load average de 1 min cercano a 20, no registrado en esos archivos), dio mediana de **19.0 s para `qwen3.5:9b` (incumplía)** y 14.9 s para `gemma4:12b`; esos resultados se sobrescribieron con la repetición registrada arriba. La latencia de `qwen3.5:9b` es más sensible a la carga del equipo. El margen de ambos (≈ 0.5 s) es estrecho.
- **Un solo tipo de evidencia:** un titular con metadatos. No se probaron indicadores ni varios registros por llamada, que alargan el prompt y la salida.
- **Esquema borrador:** el esquema real (E1-12) añadirá reglas por tipo y longitudes, y puede cambiar los tokens generados y la latencia.
- **Criterio de rechazo del validador no medido** (ver arriba).
- `/api/ps` subcuenta la memoria de `gemma4:12b`; el RSS es una aproximación del consumo real.

## Si ambos fallan o la latencia se degrada

Si en la máquina de la demo la mediana supera 15 s, o el validador real (E1) rechaza más del 20 %, o hay más de 1 JSON inválido de cada 10, se aplica D-02: **DeepSeek pasa a primario** (D-80, provisional), con el tope de costo de D-67 y volviendo al modelo local al alcanzarlo. Antes de eso, probar en este orden: cerrar procesos pesados, reducir `num_ctx` y pedir 2–3 afirmaciones en lugar de 2–4. El adaptador de DeepSeek es de E1 y no se construyó aquí.
