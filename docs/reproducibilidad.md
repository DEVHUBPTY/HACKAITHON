# Reproducibilidad de punta a punta (E1-20, D-65)

Un solo comando reconstruye todo desde `data/raw/` y comprueba que el resultado es idéntico al registrado en `data/manifest.json`.

```bash
poetry install
poetry run python -m scripts.reproducir --verificar     # reconstruye y compara; sale con 1 si algo difiere
poetry run python -m scripts.reproducir                 # reconstruye y REGISTRA los hashes en el manifest (lo hace el equipo, no el jurado)
poetry run python -m scripts.reproducir --dos-veces     # dos reconstrucciones seguidas, comparadas entre sí
```

Tarda ≈ 1 minuto con el modelo de embeddings ya descargado. La primera vez, con red, `sentence-transformers` baja los dos modelos locales a `models/`; después no hace falta red.

## Qué hace

Corre, en este orden (`config/reproducibilidad.yaml`, `pasos`), y se detiene en el primer paso que falla:

| Paso | Qué ejecuta |
|---|---|
| `conversion` | Reconstruye `processed/` desde `raw/` en una carpeta temporal (no pisa el versionado) y guarda el hash de cada archivo |
| `validacion_configuracion` · `validacion_snapshot` · `validacion_datos` | `src.config --validar` · `scripts.validar_snapshot` · `src.carga` |
| `normalizacion` · `limpieza` · `clasificacion` · `agrupacion` · `contexto` | `src.normalizacion` … `src.contexto` |
| `puntaje` | `src.puntaje --sin-llm` |
| `fichas` | La ficha de cada grupo de la bandeja (los mismos que usa el benchmark) → `outputs/reproduccion/fichas.jsonl` |
| `benchmark` | `eval.run_benchmark --split dev` → `outputs/metricas.json` |

Antes de empezar borra `.cache/embeddings/` (vectores regenerables): es el estado de una máquina nueva (ver «No determinismos»).

## Qué se compara (30 hashes)

| Clave en el manifest | Qué es | Cómo se hashea |
|---|---|---|
| `archivo:data/processed/*` y `archivo:data/processed/validos/*` | El snapshot y las filas válidas | SHA-256 de los bytes |
| `reconstruido:data/processed/*` | `processed/` rehecho desde `raw/` | SHA-256 de los bytes (debe ser igual al versionado) |
| `tabla:<nombre>` | Filas de `data/senales.duckdb` (noticias, grupos, procedencias, vinculos, puntajes, evidencia, contradicciones, sismos, fuentes, indicadores) | JSON canónico de las filas ordenadas (un `.duckdb` no es igual byte a byte entre corridas) |
| `informe:outputs/*.json` | Informes de calidad, vínculos, prioridad y validación del snapshot | JSON canónico |
| `fichas` | Las 12 fichas. **La ficha no contiene el texto del borrador** (`borrador` es solo la marca `true`): ese texto se compara aparte | JSON canónico |
| `metricas` | `outputs/metricas.json` sin las claves excluidas (abajo) | JSON canónico |
| `muestra_sustento` | Las columnas de **muestra** de `outputs/revision_sustento.csv` (qué afirmaciones se juzgan). No entran `veredicto`, `comentario`, `revisor` ni `origen_juicio` (D-101): los completa quien revisa y cambian a propósito en C-09 (X46: antes solo se miraban los conteos y otra muestra pasaba inadvertida) | JSON canónico |

JSON canónico = claves ordenadas, UTF-8 y flotantes redondeados a 4 decimales (`decimales`). Los nulos no se confunden con cero ni los enteros se tocan.

## Los borradores del LLM: desde la caché, nunca regenerados

El texto del LLM no es una salida determinista. Por eso:

- `scripts.reproducir` **nunca** crea un proveedor ni abre una conexión. Rearma cada paquete desde `data/cache_llm/` con `solo_cache=True` y guarda su estado (`completo`, `con_vacios`, `parcial`, `sin_cache`, `no_genera`) y el hash del paquete (`borradores_cache` en el manifest).
- La validación se repite sobre la respuesta guardada, así que un validador distinto sí cambia el hash: es una diferencia real.
- Si un grupo estaba completo y ahora no sale de la caché (cambió la ficha, un prompt o el modelo, que entran en la clave), es una **diferencia** y la salida lo dice. Si no tiene caché ni en el registro ni ahora, se declara como **limitación** (sin caché el texto puede variar) y no cuenta como coincidencia.
- Re-calentar la caché es una acción explícita y con costo (`poetry run python -m scripts.calentar_cache`), no un efecto de reproducir.
- Aun con temperatura 0 y semilla 0, DeepSeek no es bit a bit estable entre llamadas: al recalentar la caché (E1-20) 6 de 12 paquetes quedaron con secciones vacías por la validación, contra 1 de 12 en la corrida anterior. Es la razón por la que el texto se congela en la caché en vez de regenerarse.

## Qué se registra en cada ejecución (`reproducibilidad.ejecucion`)

Commit de partida y si el árbol tenía cambios sin commitear al empezar (`arbol_con_cambios`; ninguno de los dos se compara porque cambian en cada ejecución) · versión de Python y sistema · modelo de embeddings de agrupación y de clasificación (id y revisión exacta) · proveedor, modelo, temperatura y semilla del LLM · versión y SHA-256 de las reglas · SHA-256 de cada prompt · todas las semillas de `config/*.yaml`. Si en una verificación difiere alguna, sale como `AVISO` (explica por qué podrían cambiar los hashes); no es un fallo por sí misma.

Semillas (todas en `config/`, documentadas en `docs/parametros.md`): `clasificacion.yaml:semilla`, `clasificacion.yaml:criterio_ab.semilla`, `etiquetado.yaml:muestra.semilla`, `benchmark.yaml:intervalos.semilla`, `benchmark.yaml:sustento.semilla`, `precision.yaml:hoja_ciega.semilla` y `llm.yaml:generacion.semilla`. `tests/test_e1_20_reproducibilidad.py` falla si aparece una semilla nueva sin documentar.

## Lo que se excluye del hash, y por qué

Solo lo que cambia por **el reloj o por la máquina**, nunca un resultado:

| Dónde | Clave | Motivo |
|---|---|---|
| `outputs/reporte_calidad.json` | `generado_utc`, `ruido.generado_utc` | Marca de tiempo de cuándo se generó el informe |
| `outputs/metricas.json` | `fecha_utc` | Marca de tiempo de la corrida |
| | `entorno` | Versión de Python y sistema operativo: no son un resultado, se registran en `ejecucion` |
| | `latencia.consulta` | Tiempo de pared de la consulta en esta máquina (p50, p95 y arranque en frío del modelo; este último se mide desde que se crea el consultor hasta el primer vector, incluye la carga del modelo) |
| | `latencia.meta_sugerida.consulta_cumple` | Se deriva del tiempo de pared anterior |

La latencia y el costo del **borrador completo** sí entran en el hash: salen de `outputs/benchmark/medicion_llm.json`, que está versionado (una medición real hecha una vez, no un reloj).

## No determinismos encontrados

1. **Marcas de reloj** (`generado_utc`, `fecha_utc`, latencias de la consulta): ver arriba; se excluyen con su motivo.
2. **Ruido de ~1e-7 en las similitudes según el estado de la caché de embeddings.** El mismo texto, codificado en otro lote (otro relleno), da un vector que difiere en el séptimo decimal. La caché `.cache/embeddings/` guarda cada vector tal cual se calculó, así que dos bases construidas con cachés en distinto estado difieren en `noticias.similitud_panama`, `noticias.tema_similitud` y `puntajes.componentes` (6 filas de `noticias` y 9 de `puntajes` en la comparación). Con la caché vacía al empezar dos corridas dan exactamente lo mismo. Por eso `reiniciar_cache_embeddings` es `true` y el hash redondea a 4 decimales (con 6 decimales una diferencia de 2e-7 cruzaría el redondeo en ~20 % de los valores; con 4, en ~0,2 %). Es una tolerancia numérica declarada, no una exclusión.
3. **La base `data/senales.duckdb` que había en las máquinas del equipo estaba desactualizada** respecto del código (`evidencia.vacios` conservaba el texto anterior «procedencia(s) independiente(s)»). Como la clave de la caché del LLM incluye la evidencia, reconstruir desde `raw/` dejaba **0 de 12** grupos con borrador en la caché versionada, y el `outputs/metricas.json` versionado se había calculado sobre esa base vieja. Se recalentó la caché con la base reconstruida (42 respuestas nuevas, 33 sin uso podadas, USD 0.0417) y se regeneró `outputs/metricas.json`. Es justo el defecto que `--verificar` existe para detectar.

## Regresión de calidad al recalentar la caché (X45)

Recalentar la caché para que coincidiera con la base reconstruida (hallazgo 3 de arriba) **empeoró** los borradores, y se deja a la vista en vez de arreglarlo a medias:

| | Caché anterior (`64ba952`) | Caché recalentada (E1-20) |
|---|---|---|
| Paquetes completos | 11 de 12 | **6 de 12** |
| Rechazo del validador (unidades evaluadas) | 13/119 = 0.109 (IC 95 % 0.065–0.178) | **39/151 = 0.258 (IC 95 % 0.195–0.334)** |
| Secciones perdidas | 1: `enfoque` de `GRP-79f3183472` | 8: `enfoque` de `GRP-84a6b3a04b`, `GRP-79f3183472`, `GRP-65d565abd0`, `GRP-8af4196527` y `GRP-45aebb27b2`; y `titulares`, `copy_digital` y `guion` de `GRP-da35c3dead` (el grupo de la demo) |

Causa probable: variabilidad entre corridas de DeepSeek. Las dos cifras de rechazo son el **validador vigente** aplicado a las respuestas guardadas en cada caché (`rechazos_previos` re-valida lo guardado), y entre `64ba952` y esta rama no cambió ningún prompt, ni `src/generacion.py`, ni el validador, ni su configuración (`git diff 64ba952 -- prompts src/generacion.py src/validador.py config/generacion.yaml config/validador.yaml` está vacío): lo que cambió son las respuestas. La petición sí cambió en un punto: la evidencia que se envía incluye el texto de los vacíos de la ficha, que la caché vieja tenía desactualizado (hallazgo 3), así que no son las mismas peticiones. Con temperatura 0 y semilla 0 DeepSeek no es estable. No se midió con una segunda corrida independiente: es una hipótesis, no una conclusión.

**No se recalentaron solo los grupos de la demo** para recuperar la corrida buena: eso dejaría una caché que pasa y sesgaría a la baja la métrica de rechazo, que es justo lo que este cambio de caché hizo visible. La tarea nueva **E1-12b (robustez de la generación)** corregirá la causa y recalentará **toda** la caché una sola vez al final; entonces se vuelve a registrar el manifest (`poetry run python -m scripts.reproducir`) y se verifica. Hasta entonces las cifras de `outputs/metricas.json` (`borradores`, `rechazos_previos`) son las de la caché recalentada.

## Limitaciones

- **RSS y GDELT no se versionan** (redistribución restringida, D-72). En un clon sin esos crudos `scripts.reproducir` no puede reconstruir `processed/`: lo declara como limitación, omite los hashes `reconstruido:*` y sigue desde el `processed/` versionado. Para reconstruirlos, `scripts.extraer` (receta en `data/README.md`). Si un crudo presente no coincide con el SHA-256 del manifest, se detiene: `raw/` es inmutable.
- El texto del LLM solo se reproduce desde la caché; sin ella puede variar.
- La nota del LLM sobre un par de contradicciones no se reproduce: el paso `puntaje` corre con `--sin-llm`. Hoy no hay pares candidatos, así que no cambia nada.
- Entre máquinas con otro hardware o librerías numéricas el ruido de flotantes puede ser distinto: el redondeo a 4 decimales lo absorbe en la práctica, pero no está medido fuera de esta máquina (macOS, Python 3.11).
- La validez de sustento la completa una persona (`outputs/revision_sustento.csv`) y no es un resultado del pipeline: si la persona ya la revisó, `metricas.json` la conserva.
- Las revisiones humanas (`data/revision.duckdb`) son un insumo: este script no las lee ni las regenera.
