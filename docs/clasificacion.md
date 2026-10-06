# Clasificación temática: embeddings, método A/B y baseline (E1-07)

Estado al **2026-10-06**: implementado y medido sobre los **casos difíciles** de `docs/guia_temas.md` (n = 15). **La
exactitud y el macro-F1 sobre datos reales están pendientes de `eval/etiquetas.csv` (E1-06)**: hoy no existe y no se
inventa ningún número. Todo lo que sigue distingue lo medido de lo supuesto.

## Cómo correrlo

```bash
poetry run python -m src.carga && poetry run python -m src.normalizacion && poetry run python -m src.limpieza
poetry run python -m src.clasificacion          # llena la clasificación en data/senales.duckdb (+ sección en reporte_calidad.json)
poetry run python -m eval.clasificacion         # casos difíciles; datos reales solo si existe eval/etiquetas.csv
poetry run python -m eval.calibrar_clasificacion  # imprime los umbrales provisionales (no escribe config/)
poetry run pytest tests/test_casos_dificiles.py   # los casos difíciles contra el clasificador real
```

`eval.clasificacion` termina con código 2 si falta `eval/etiquetas.csv` (como `eval.ruido`) y deja igualmente los casos
difíciles en `outputs/clasificacion.json`.

## Qué se guarda en DuckDB

La spec escribe «llena `tema`, `tema_similitud` y `tema_baseline`». **Se llenan `tema_clasificado`, `tema_similitud` y
`tema_baseline`**: `tema` es el tema de **origen** del contrato y no se toca (D-62, CLAUDE.md); sobrescribirlo sería una
fuga de información.

| Dónde | Campo | Contenido |
|---|---|---|
| `noticias` | `tema_clasificado` | Uno de los 6 temas o `sin_tema` (la mayor similitud no llega al umbral). Nulo en el ruido |
| | `tema_similitud` | Mayor similitud coseno (también cuando es `sin_tema`, para explicar la abstención) |
| | `subtema_clasificado` | Solo con el método B: el subtema más parecido dentro del tema |
| | `tema_secundario`, `tema_secundario_similitud` | Segundo tema, solo si está a menos de `margen_secundario` y supera el umbral |
| | `tema_baseline` | Tema del baseline de palabras clave (las mismas categorías) |
| | `similitud_panama`, `ruido_similitud` | Señal del filtro de ruido por prototipo (D-84) y marca si lo aplicó |
| `similitud_tema` | `id_noticia, metodo, tema, similitud, subtema` | Similitud con **cada** tema, por método A y B (explicabilidad) |

Solo se clasifica `titulo_limpio` de los registros con `es_ruido = false` (más la descripción del RSS como texto
interno si existiera; el snapshot actual no la trae). Los embeddings se cachean en disco por modelo y revisión
(`.cache/embeddings/`, ignorada por git); la caché guarda el hash del texto, **nunca el texto**.

## Modelos (fijados en `config/clasificacion.yaml`)

| Nombre | Id de Hugging Face | Revisión (commit) | Prefijos titular / tema |
|---|---|---|---|
| `e5` (activo, D-20 propuesta) | `intfloat/multilingual-e5-small` | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | `query: ` / `passage: ` |
| `minilm` (comparación) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | ninguno |

- **Locales siempre** (D-03): `sentence-transformers` en CPU, sin API. Primera descarga con internet a `models/` (ignorada
  por git, ≈ 930 MB las dos); después funciona **sin internet** (`local_files_only`; con `HF_HUB_OFFLINE=1` nunca
  descarga). Lo verifica `test_el_modelo_funciona_sin_internet_despues_de_la_primera_descarga`.
- **Prefijos de e5:** el titular es la consulta (`query: `) y la descripción, los ejemplos y los prototipos de cada tema son
  los pasajes (`passage: `). La ficha del modelo (README en Hugging Face) pide `query: ` y `passage: ` para tareas asimétricas
  (recuperación) y solo `query: ` para clasificación o clustering con embeddings como características; la spec pide los dos
  prefijos y se tomó la lectura asimétrica. **No se midió la alternativa `query: ` en ambos lados**: es una elección de
  diseño, no un resultado.
- Semilla 42 (torch, numpy y bootstrap), CPU: dos corridas dan los mismos vectores y las mismas decisiones.

## Los dos métodos y el baseline

- **A (descripción + ejemplos):** cada tema es el centroide de los embeddings de su descripción y sus titulares de ejemplo
  (los ejemplos se limpian igual que los titulares reales). Similitud con un tema = coseno con su centroide.
- **B (prototipos por subtema):** cada subtema tiene un prototipo; la similitud con un tema es la del subtema más parecido,
  y el resultado sube a su tema. La salida de A y B son solo los 6 temas.
- **Baseline (D-66):** palabras clave por tema (`baseline.palabras_clave`), escritas **antes de medir** a partir de la
  columna «Incluye» de la guía, sin mirar los casos difíciles, y sin ajustarlas después para ganar o perder. Puntaje de un
  tema = patrones distintos que coinciden; empate = el primero de `temas.yaml`; sin coincidencias = `sin_tema`.
- **Criterio A vs. B (D-21/D-57), fijado en el YAML antes de medir:** B solo si el IC 95 % (bootstrap pareado, 1.000
  remuestreos, semilla 42) de la diferencia de macro-F1 B − A **excluye el cero a favor de B** y **ningún tema empeora de forma
  significativa** (IC 95 % de su diferencia de F1 enteramente por debajo de cero). Si no, A. `metodo_activo: A`.

## Resultados sobre los casos difíciles (n = 15) · 2026-10-06

Los 15 titulares de `docs/guia_temas.md` («Casos difíciles») son un conjunto de **prueba**: un test comprueba que ninguno es
ejemplo, prototipo ni descripción de `temas.yaml`. **n = 15 y 7 clases: los IC son muy anchos y no alcanzan para elegir
modelo (D-20) ni método (D-21).** El macro-F1 incluye `sin_tema`, que tiene un solo caso (CD-15), así que ese único
acierto o fallo mueve mucho la cifra.

| Configuración | Tema principal (k/15, IC 95 % Wilson) | Macro-F1 (IC 95 % bootstrap) |
|---|---|---|
| **Baseline** (palabras clave) | **14/15 = 93.3 %** [70.2–98.8] | **0.924** [0.680–1.000] |
| e5 · A (**activo**) | 11/15 = 73.3 % [48.0–89.1] | 0.621 [0.329–0.921] |
| e5 · B | 12/15 = 80.0 % [54.8–93.0] | 0.689 [0.428–1.000] |
| MiniLM · A | 8/15 = 53.3 % [30.1–75.2] | 0.533 [0.209–0.753] |
| MiniLM · B | 13/15 = 86.7 % [62.1–96.3] | 0.789 [0.578–1.000] |

Diferencias de macro-F1 (bootstrap pareado, IC 95 %):

| Comparación | Diferencia | IC 95 % | Lectura |
|---|---|---|---|
| e5: B − A | +0.068 | [−0.196, 0.372] | incluye el cero → criterio elige **A** |
| MiniLM: B − A | +0.256 | [0.019, 0.656] | excluye el cero a favor de B → el criterio elegiría B **solo con estos 15 casos** |
| e5 · A − baseline | −0.303 | [−0.638, 0.085] | incluye el cero |
| e5 · B − baseline | −0.235 | [−0.389, 0.000] | roza el cero |
| MiniLM · A − baseline | −0.391 | [−0.778, −0.022] | el baseline es mejor |
| MiniLM · B − baseline | −0.135 | [−0.375, 0.240] | incluye el cero |

Lectura honesta (D-66, «cuándo la IA no ayuda»):

- **En estos 15 casos el baseline de palabras clave le gana al modelo activo (14/15 frente a 11/15).** Los casos difíciles
  son titulares escritos con el vocabulario de la propia guía («tránsitos», «sismo», «GAFI», «lista gris», «carga aérea»), que
  es justo lo que las palabras clave detectan; **no es evidencia de que el baseline sea mejor en titulares reales**, donde
  35 de los 79 titulares útiles no activan ninguna palabra clave (el baseline dice `sin_tema`).
- Los embeddings ganan donde no hay vocabulario compartido, y eso este conjunto casi no lo mide. La comparación que cuenta
  es la de los datos reales con `eval/etiquetas.csv` (pendiente).
- **Elección de modelo y método: no decidible todavía.** Se mantienen `e5` (propuesta D-20) y `A` (criterio D-57 por defecto).
  Que MiniLM · B salga mejor en n = 15 no basta para cambiarlos; se decide con las ~100 etiquetas humanas.
- El tema secundario esperado (7 casos) se acierta con el margen provisional solo en 1 de 7 (e5 · A), pero el 2.º mejor
  coincide en 3 de 7: el problema es el margen, no el orden (ver «Umbrales provisionales»).

## Limitaciones conocidas (los fallos no se ocultan)

Con el modelo y método activos (e5 · A). `tests/test_casos_dificiles.py` los declara `xfail(strict=True)`: si cambian, el test
obliga a actualizar esta tabla.

| Caso | Titular | Esperado | Predicho | Observación (solo lo observado, sin causa comprobada) |
|---|---|---|---|---|
| CD-02 | Lluvias dejan sin agua a sectores de San Miguelito | Servicios públicos (secundario Eventos naturales) | Eventos naturales | La regla 4 (falla de un servicio) no se cumple; el baseline sí acierta |
| CD-04 | ASEP aprueba aumento de la tarifa eléctrica | Regulación (secundario Servicios públicos) | Economía | La regla 2 (norma nueva) no se cumple; el baseline sí acierta |
| CD-08 | Aumenta la carga aérea en Tocumen | Logística/Canal | Turismo | La regla 6 (carga ≠ pasajeros) no se cumple; el baseline sí acierta |
| CD-15 | Selección de fútbol clasifica al Mundial | `sin_tema` | Eventos naturales | Similitud máxima 0.845, sobre el umbral 0.823 de e5. **En el pipeline no llega al clasificador:** el filtro de ruido (E1-03b) lo marca `fuera_de_temas` (`test_el_futbol_se_descarta_antes_por_el_filtro_de_ruido`) |
| CD-10, CD-14 (secundario) | Asamblea aprueba reforma a la CSS · Gobierno firma nuevo contrato minero | secundario Servicios públicos · Economía | 2.º mejor: Economía · Logística/Canal | El principal es correcto; el secundario no |

Limitaciones generales:

- e5 comprime las similitudes (0.81–0.91 en el snapshot): una diferencia de 0.002 decide el tema secundario. MiniLM tiene una
  escala más amplia (0.17–0.75).
- La regla de frontera «hecho central, no consecuencias» no está codificada: A y B comparan similitud, no razonan.
- Con n = 15 no se puede decir que e5 sea peor o mejor que MiniLM; los IC se solapan casi por completo.

## Datos reales (79 titulares útiles; solo distribución, no exactitud)

Snapshot del 2026-10-06: 186 noticias, 107 marcadas como ruido por palabras clave, **79 útiles** (**52 titulares únicos**: varias
URL repiten el mismo titular, p. ej. 14 veces «Intensifying El Niño…», que pesan en los conteos y E1-08 agrupará). Distribución de
e5 · A (activo), con IC de Wilson al 95 % **descriptivo** (el snapshot no es una muestra aleatoria):

| Tema | Registros (de 79) | IC 95 % | Titulares únicos (de 52) |
|---|---|---|---|
| Eventos naturales | 25 (31.6 %) | [22.5, 42.6] | 7 |
| Servicios públicos | 15 (19.0 %) | [11.9, 29.0] | 15 |
| `sin_tema` | 12 (15.2 %) | [8.9, 24.7] | 3 |
| Economía | 11 (13.9 %) | [8.0, 23.2] | 11 |
| Regulación | 7 (8.9 %) | [4.4, 17.2] | 7 |
| Logística/Canal | 6 (7.6 %) | [3.5, 15.6] | 6 |
| Turismo | 3 (3.8 %) | [1.3, 10.6] | 3 |

Comparación con otros métodos sobre los mismos 79 (acuerdo, **no exactitud**): e5·A coincide con el baseline en 48/79, con
e5·B en 29/79 y con MiniLM·A en 48/79. Los métodos discrepan mucho en datos reales, otra razón para no elegir con n = 15.
El baseline deja 35/79 sin tema (ninguna palabra clave).

## Umbrales provisionales (supuesto, no calibrados con etiquetas)

`umbral_sin_tema` y `margen_secundario` salen de `python -m eval.calibrar_clasificacion` con una regla fija: percentil 5 de la
similitud máxima y percentil 25 de la brecha entre la mejor y la segunda, sobre los 52 titulares únicos útiles. **Es un
supuesto** (se abstiene el 5 % menos parecido; el 25 % de brecha más corta recibe secundario), no una medición de qué es «sin
tema». Diagnóstico descriptivo: separando los titulares que el filtro de palabras clave marcó `fuera_de_temas` (n = 16) de los
útiles, la similitud máxima de e5·A da AUC 0.79 y la de MiniLM·A 0.75, con marcas que **no son etiquetas humanas**. Se
recalibran con `eval/etiquetas.csv` (E1-06).

## Filtro de ruido por similitud con un prototipo de Panamá (D-84, diferido desde E1-03b)

**Implementado, pero `activo: false` en `config/ruido.yaml`.** Con él activo, un titular no marcado como ruido ni como alcance
regional y cuya similitud máxima con los prototipos de Panamá es menor que `umbral` se marca `no_es_panama` (`ruido_similitud =
true`, reversible al volver a correr); una nota regional no se marca nunca. Medición disponible sin etiquetas humanas:

- Con el umbral sugerido para e5 (0.774) marcaría **2 de los 79 útiles**: una es de alcance regional (no se marcaría) y la
  otra es «Tres hombres asaltan casino… en San Miguelito», una noticia sobre Panamá: **un falso positivo evidente**.
- Dejaría pasar **80 de los 107** registros que el filtro de palabras clave ya marcó como ruido (similitud ≥ umbral).
- AUC descriptivo 0.78 contra las marcas `no_es_panama` de palabras clave (no son etiquetas humanas).

Conclusión: con estos números la señal **no se activa**. La precisión y el recall reales se miden con
`python -m eval.ruido` cuando E1-06 entregue `eval/etiquetas.csv`; hasta entonces `ruido.yaml` conserva el hook y se guarda
`similitud_panama` por noticia para ese análisis.

## Pendiente

1. **E1-06:** correr `poetry run python -m eval.clasificacion` con `eval/etiquetas.csv` (columna `tema_principal`, o la que
   defina esa herramienta con `--columna`): macro-F1, F1/precisión/recall por tema, matriz de confusión y criterio A vs. B con
   n e IC, sobre titulares no ruido y sin los ejemplos de `ejemplos_excluidos.txt`.
2. Con esas métricas: decidir modelo (D-20, de «propuesta» a «aceptada») y método (D-21), recalibrar los umbrales y
   decidir si se activa el filtro por similitud. **La elección se registra en Notion con los números** (no hay números reales
   todavía, así que no se registró nada).
3. `docs/ia_vs_baseline.md` (D-66) lo completan E1-11 y E1-18 con las demás tareas.
