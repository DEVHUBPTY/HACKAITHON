# Modelos usados (E1-18 · D-67)

Una ficha por modelo. Cifras medidas, con su origen: `outputs/medicion_embeddings.json` (`poetry run python -m scripts.medir_embeddings`), `outputs/latencia_generacion_deepseek.json` (`scripts.medir_generacion --proveedor deepseek`) y `outputs/metricas.json` (`eval.run_benchmark --split dev --medir-llm`). Los tiempos son de pared en un Mac con Apple Silicon (macOS 26, Python 3.11.14); no son de otro equipo ni de un servidor.

| Modelo | Para qué | Dónde corre | Costo medido |
|---|---|---|---|
| `intfloat/multilingual-e5-small` (`e5`) | Clasificación de tema y búsqueda de la consulta | Local, CPU | USD 0 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (`minilm`) | Agrupación de titulares en eventos | Local, CPU | USD 0 |
| `deepseek-flash` (DeepSeek) | Generación del borrador (afirmaciones citadas y secciones) | API remota | ≈ USD 0.0031 por paquete (cota superior) |

Qué NO usa un LLM: el puntaje, el estado de evidencia, la ficha, el validador y la consulta con abstención son código determinista (CLAUDE.md). La consulta del benchmark usa solo embeddings.

## 1 · `intfloat/multilingual-e5-small`

- **Proveedor:** Hugging Face (`sentence-transformers`, local). **Versión:** commit `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- **Uso:** modelo activo de `config/clasificacion.yaml` (`modelo_activo: e5`) para la clasificación por similitud con los temas y para la búsqueda semántica de `src/consulta.py` (umbral de abstención 0.874 solo vale para este modelo).
- **Parámetros:** 117 653 760; dimensión 384; `max_seq_length` 512; CPU, lote de 32. Prefijo `query: ` en el titular y `passage: ` en los temas (`config/clasificacion.yaml`).
- **Costo medido:** USD 0 (local, sin API). **Tiempo de cómputo:** carga 3.36 s; 94 textos en 0.119 s (788.5 textos/s).
- **Memoria:** RSS máximo del proceso 1.15 GB (1 146 830 848 bytes); 493 MB en disco.
- **Limitaciones observadas:**
  - La similitud entre un titular y su propio tema está comprimida: casi todo cae entre 0.80 y 0.91, por lo que no separa bien paráfrasis de no paráfrasis (`config/clasificacion.yaml`).
  - Clasificación de tema con las etiquetas humanas: macro-F1 0.401 (IC 0.244–0.516, n = 63), sin diferencia demostrable frente a las palabras clave (`docs/ia_vs_baseline.md`).
  - Consultas cortas y genéricas puntúan 0.85 contra su documento correcto y se abstienen con el umbral 0.874 (`docs/ia_vs_baseline.md`, sección 5).

## 2 · `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`

- **Proveedor:** Hugging Face (`sentence-transformers`, local). **Versión:** commit `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
- **Uso:** agrupación de titulares en grupos `GRP-` (`config/reglas_v1.3.yaml`, umbral coseno 0.69, calibrado con `eval.agrupacion`; vale solo para este modelo).
- **Parámetros:** 117 653 760; dimensión 384; `max_seq_length` 128 (trunca titulares largos); CPU, lote de 32.
- **Costo medido:** USD 0. **Tiempo de cómputo:** carga 3.17 s; 94 textos en 0.123 s (762.8 textos/s).
- **Memoria:** RSS máximo 1.31 GB (1 311 490 048 bytes); 480 MB en disco.
- **Limitaciones observadas:** en validación cruzada agrupada, precisión de pares 0.880 (125/142) con 17 falsos positivos, recall 0.954 (125/131). Une titulares de idiomas distintos y a veces titulares de eventos distintos (`docs/ia_vs_baseline.md`, sección 2). Los grupos pequeños casi no se pueden medir.

Nota de medición: el RSS es el del proceso completo (PyTorch incluido), un proceso por modelo, medido con 94 textos. No incluye el modelo de otro proceso.

## 3 · `deepseek-flash` (DeepSeek)

- **Proveedor:** DeepSeek, API compatible con OpenAI (`https://api.deepseek.com`). **Versión:** el alias `deepseek-flash` (la API no devuelve un identificador inmutable; el alias de `config/generacion.yaml` es el que se usó el 2026-10-07).
- **Uso:** único proveedor de generación durante el evento (D-94, D-95; `LLM_PROVIDER=deepseek`). Dos pasos: afirmaciones citadas y validadas; después, cada sección por separado (E1-12). El validador determinista decide qué se emite.
- **Parámetros:** temperatura 0.0, `max_tokens` 1536, razonamiento desactivado (`thinking: disabled`), salida JSON validada con pydantic, un reintento ante salida inválida. Precios de `config/generacion.yaml`: USD 0.30 por millón de tokens de entrada y 1.20 de salida (tarifa pico, sin descuento por caché).
- **Costo medido:**
  - Benchmark de desarrollo, 12 paquetes reales (`--medir-llm`): 76 825 tokens de entrada y 14 759 de salida; mediana por paquete 5 528.5 de entrada (IC 95 % 4 559–7 392.5) y 1 066.5 de salida (IC 834.5–1 365), 3 llamadas (IC 2.5–4). **Mediana de USD 0.0031 por paquete** (IC 0.0024–0.0038, n = 12); total estimado USD 0.0408.
  - Paquete editorial completo, 5 repeticiones: 11 817 tokens de entrada y 3 355 de salida, 7 llamadas; ≈ USD 0.0076 por paquete a la tarifa pico, ≈ USD 0.038 las cinco.
  - **Estas cifras son una cota superior:** el contador del repositorio multiplica los tokens por el precio pico sin descuento por caché y sobreestima ≈ 2.6 veces frente a la consola de DeepSeek (comparación del 2026-10-06, `docs/parametros.md`, D-97). El contador acumulado del proyecto (`outputs/costo_llm.json`) lleva USD 0.68 y 1 446 983 tokens, muy por debajo del tope de USD 100 (D-98).
- **Tiempo de cómputo (latencia de pared, red incluida):**
  - Una llamada al LLM: mediana 1.94 s (IC 1.86–2.05), p95 2.85 s (IC 2.30–2.94), n = 41.
  - Primera respuesta del borrador: mediana 4.09 s (n = 12). Paquete completo, 12 paquetes: mediana 6.36 s (IC 5.04–7.69), p95 12.41 s (IC 7.23–17.16).
  - Por tipo de paquete: **investigación** mediana 5.99 s (n = 11, IC 4.23–7.58), cumple la meta de 15 s; **editorial** 17.16 s (n = 1 en el benchmark) y, en 5 repeticiones sobre un caso, mediana 16.64 s, p95 17.20 s (mín. 15.60 s, máx. 17.20 s): **no cumple** la meta de ≤ 15 s. Con n tan pequeño es una observación, no una proporción.
- **Memoria:** no aplica; el modelo corre en el servidor del proveedor. En local solo queda el cliente HTTP.
- **Limitaciones observadas:**
  - El validador rechazó 13 de 119 unidades evaluadas de la caché (10.9 %, IC 95 % 6.5–17.8 %): 10 de 76 afirmaciones (13.2 %; la regla más frecuente es causalidad, 7) y 2 de 13 enfoques por presentarse como hecho.
  - En el paquete editorial, `copy_digital` y `resumen_web` se recortaron en las 5 repeticiones (copy en las 5, resumen en 3) por el límite de palabras; de 6 a 7 afirmaciones válidas por paquete.
  - Depende de la red; sin red, los borradores salen **solo de la caché** (`data/cache_llm/`, `docs/fallback.md`). Los embeddings no necesitan red.
  - La validez de sustento de sus afirmaciones **no se midió**: la revisión humana de `outputs/revision_sustento.csv` sigue pendiente (`docs/protocolo_evaluacion.md`, sección 4).

## 4 · Modelos soportados pero apagados

- **Ollama** (`qwen3.5:9b` y `gemma4:12b`, E0-07) sigue soportado por configuración (`LLM_PROVIDER=ollama`) pero **está apagado y no se usa**: era demasiado lento (≈ 2 min por paquete; 14.3 s de mediana solo en el paso 1) y ocupaba 7.2 GB de RSS. No se midió de nuevo en E1-18. Detalle y cifras de entonces: `docs/eleccion_modelo.md`.
