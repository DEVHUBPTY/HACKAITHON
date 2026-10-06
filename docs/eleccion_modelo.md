# Elección del modelo local (E0-07)

Aplica el criterio de la decisión **D-02** antes de construir: Ollama es el proveedor primario salvo que la **mediana supere 15 s**, el **validador rechace más del 20 %** o haya **JSON inválido en más de 1 de cada 10 llamadas**. En ese caso DeepSeek pasa a primario (D-80).

## Modelo elegido (provisional)

**`qwen3.5:9b`** (digest `56671c2ab938…`, Q4_K_M, 9.0 B parámetros) se mantiene **de forma provisional** como `OLLAMA_MODEL`. Ningún modelo es claramente superior (ver «Justificación»); la elección se vuelve a medir con el validador real (E1-13) y con una instrucción explícita de atribución en el prompt.

## Cómo se midió

Comando: `poetry run python -m scripts.probar_llm --modelo <tag>` (detalle por llamada en `outputs/probar_llm_<tag>.json`).

- **Muestra:** 5 titulares reales de TVN Panamá del snapshot (`data/processed/noticias.csv`), elegidos de forma determinista (2 nacionales, 1 mundo, 1 tvmax, 1 entretenimiento; los `id_noticia` más bajos de cada tema). Ids: `NOT-0d91fa48b0`, `NOT-220be165b5`, `NOT-19d534ddba`, `NOT-099a437ecb`, `NOT-50c2fa1e7c`.
- **Tarea:** paso 1 de la generación (afirmaciones citadas), con el esquema BORRADOR de `src/esquemas.py` (`AfirmacionesCitadas`; E1-12 lo completa). Reglas en el *system prompt* (`prompts/afirmaciones_citadas.txt`); la evidencia va en `<evidencia>…</evidencia>` en el mensaje de usuario (CLAUDE.md).
- **Llamadas:** 1 de calentamiento (carga en frío, fuera de las estadísticas) + 5 titulares × 4 repeticiones = **20 llamadas** por modelo. **n = 20 solo vale para la latencia.** Con temperatura 0 y semilla fija las 4 repeticiones de un titular son idénticas byte a byte, así que la validez del JSON se evalúa sobre **5 salidas distintas** (n efectivo = 5). Temperatura 0, semilla 0, `num_ctx` 4096, `num_predict` 1024, pensamiento desactivado, un modelo a la vez y descargado al terminar (`keep_alive` 0).
- **JSON válido:** el texto se parsea y valida con pydantic (tipos, citas obligatorias por tipo, claves desconocidas prohibidas). Además se verifica que cada cita apunte al ID y campo entregados en la evidencia.
- **Latencia:** tiempo de pared de cada llamada (`time.perf_counter`), mediana y p95 por interpolación lineal.
- **IC 95 %:** Wilson para la proporción de JSON válido, calculado sobre las llamadas y sobre las salidas distintas.
- **Atribución:** `scripts.probar_llm` cuenta las declaraciones cuyo texto no contiene un verbo de reporte (`config/llm.yaml`, `marcadores_atribucion`) ni el nombre del medio. Se recalcula desde las salidas guardadas (`--reanalizar`).
- **Hardware:** un solo Mac con 24 GB de RAM, Ollama 0.34.1, API en `http://localhost:11434`.

## Resultados (20 llamadas por modelo; 5 salidas distintas)

| | `qwen3.5:9b` | `gemma4:12b` |
|---|---|---|
| Digest | `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90` | `6114515d63c17436a7c0417d82820ac65ad643e2806c5a3c89cb62846436ed0b` |
| Parámetros · cuantización | 9.0 B · Q4_K_M | 11.9 B · Q4_K_M |
| JSON válido, salidas distintas (n efectivo) | **5/5 = 100 % (IC 95 % 56.6–100 %)** | **5/5 = 100 % (IC 95 % 56.6–100 %)** |
| JSON válido, por llamada (n = 20, no independientes) | 20/20 (IC 95 % 83.9–100 %) | 20/20 (IC 95 % 83.9–100 %) |
| Citas con ID y campo existentes | 20/20 | 20/20 |
| Latencia mediana | **14.3 s** | **14.5 s** |
| Latencia p95 (mín–máx) | 16.9 s (12.2–18.3) | 16.5 s (12.7–17.2) |
| Velocidad de generación (mediana) | 22.5 tok/s · ≈ 305 tokens por salida | 14.2 tok/s · ≈ 203 tokens por salida |
| Carga en frío (calentamiento) | 16.0 s (carga 1.3 s) | 21.0 s (carga 6.7 s) |
| Memoria, `/api/ps` (`size`) | 6.2 GB | 1.1 GB (*subcuenta*, ver nota) |
| Memoria, RSS del proceso servidor | **7.2 GB** | **9.3 GB** |
| Salidas con tipo `hecho` sobre un titular | 4/20 (20 %; 1 titular de 5) | **20/20 (100 %; 5 de 5)** |
| Declaraciones sin atribución al medio (todas las llamadas) | **12/56** | 0/20 |
| Declaraciones sin atribución (salidas distintas) | 3/14 | 0/5 |
| Pensamiento presente en la respuesta | 0 | 0 |
| Carga del sistema al inicio → fin (1 min) | 3.6 → 12.6 | 12.1 → 4.9 |

Nota sobre la memoria: `/api/ps` de `gemma4:12b` informa 1.1 GB, pero el archivo del modelo pesa 8.0 GB y el proceso servidor tiene 9.3 GB residentes; el valor de `/api/ps` no es confiable para ese modelo (posiblemente parte de los pesos queda mapeada a disco). Por eso el script guarda también el RSS del servidor (`rss_servidor_bytes`) y la comparación usa ese valor.

## Evaluación del criterio D-02

| Criterio | Umbral | `qwen3.5:9b` | `gemma4:12b` |
|---|---|---|---|
| Latencia mediana (n = 20 llamadas) | ≤ 15 s | 14.3 s: cumple (margen 0.7 s) con carga baja; **19.0 s en una pasada con carga alta** | 14.5 s: cumple (margen 0.5 s); 14.9 s en la pasada con carga alta |
| JSON inválido | ≤ 1 de cada 10 | 0 de 5 salidas distintas: cumple | 0 de 5 salidas distintas: cumple |
| Rechazo del validador | ≤ 20 % | **No evaluable**: el validador es de E1. Aproximación (`hecho` sobre un titular): 1 titular de 5 (20 %, en el límite) | Aproximación: 5 titulares de 5 (**100 %**) |

El criterio «≤ 1 inválido de cada 10» se evalúa sobre **5 salidas distintas**, no sobre 20: es una evidencia débil (el IC 95 % de 5/5 llega solo hasta 56.6 %). La aproximación del validador no es el validador real: gemma marca como `hecho` la fecha de publicación del registro («La noticia fue publicada el 6 de octubre…») aunque el prompt reserva `hecho` para datos oficiales y conteos; qwen lo hizo solo en un titular (`NOT-19d534ddba`, 4 de 20 llamadas idénticas).

## Justificación

Ningún modelo es claramente superior; cada uno falla en algo distinto.

| | A favor | En contra |
|---|---|---|
| `qwen3.5:9b` | Menos memoria (7.2 GB de RSS frente a 9.3 GB), más rápido por token (22.5 frente a 14.2 tok/s); cumple la latencia con carga baja; solo 1 titular de 5 con `hecho` mal usado | **12 de 56 declaraciones sin atribución al medio** (3 de 14 en salidas distintas); **con la máquina muy cargada la mediana fue 19.0 s y incumplió D-02** (esa pasada se sobrescribió y su archivo crudo se perdió; solo queda la cifra de la consola) |
| `gemma4:12b` | Atribuye siempre al medio (0 de 20 sin atribución); latencia más estable (14.9 s con carga alta, 14.5 s con carga baja) | Marca metadatos (la fecha de publicación) como `hecho` en los 5 titulares; más memoria; arranque en frío más lento (21.0 s) |

Las dos pasadas con resultados guardados tuvieron **carga del sistema distinta** (carga de 1 min: 3.6 → 12.6 con qwen y 12.1 → 4.9 con gemma), así que la diferencia de 0.2 s entre medianas no es concluyente y la comparación de latencia no es limpia.

Por qué se mantiene `qwen3.5:9b` de forma **provisional**: menor memoria en un equipo de 24 GB que además corre embeddings, DuckDB y Streamlit, y cumple la latencia de D-02 con carga baja. No es una elección fundada en calidad: gemma atribuye mejor. Antes de fijarla, se repite la comparación con (a) el validador real (E1-13), que mide el rechazo por tipo y por atribución, y (b) una instrucción de atribución explícita en el prompt («cada declaración nombra al medio con un verbo de reporte»), que puede cerrar la brecha de qwen. Si en la demo la mediana de qwen supera 15 s, se cambia a `gemma4:12b` o se aplica D-02.

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
- No se midió una variante de optimización: con carga baja ningún modelo falló el criterio. La pasada con carga alta de qwen (19.0 s) no se repitió con una variante.

## Limitaciones

- **n pequeña:** 5 titulares. Con temperatura 0 y semilla fija las 4 repeticiones son idénticas byte a byte: aportan variación de latencia, no de contenido. La validez se evalúa con n efectivo = 5 (IC 95 % 56.6–100 %).
- **Una sola máquina** y con carga ajena variable, distinta entre las dos pasadas guardadas (ver «Justificación»). El margen de ambos modelos sobre el umbral de 15 s es de ≈ 0.5 s.
- **Un solo tipo de evidencia:** un titular con metadatos. No se probaron indicadores ni varios registros por llamada, que alargan el prompt y la salida.
- **Esquema borrador:** el esquema real (E1-12) añadirá reglas por tipo y longitudes, y puede cambiar los tokens generados y la latencia.
- **Criterio de rechazo del validador no medido** (ver arriba).
- `/api/ps` subcuenta la memoria de `gemma4:12b`; el RSS es una aproximación del consumo real.

## Si ambos fallan o la latencia se degrada

Si en la máquina de la demo la mediana supera 15 s, o el validador real (E1) rechaza más del 20 %, o hay más de 1 JSON inválido de cada 10, se aplica D-02: **DeepSeek pasa a primario** (D-80, provisional), con el tope de costo de D-67 y volviendo al modelo local al alcanzarlo. Antes de eso, probar en este orden: cerrar procesos pesados, reducir `num_ctx` y pedir 2–3 afirmaciones en lugar de 2–4. El adaptador de DeepSeek es de E1 y no se construyó aquí.
