# Clasificación temática: embeddings, método A/B y baseline (E1-07)

Estado al **2026-10-06** (con las correcciones de la revisión X15): implementado y medido sobre los **casos difíciles** de
`docs/guia_temas.md` (n = 15). **La exactitud y el macro-F1 sobre datos reales están pendientes de `eval/etiquetas.csv`**
(E1-06 ya entregó la herramienta; las etiquetas todavía no existen en el repo): no se inventa ningún número. Todo lo que
sigue distingue lo medido de lo supuesto.

## Cómo correrlo

```bash
poetry run python -m src.carga && poetry run python -m src.normalizacion && poetry run python -m src.limpieza
poetry run python -m src.clasificacion          # llena la clasificación en data/senales.duckdb (+ sección en reporte_calidad.json)
poetry run python -m eval.clasificacion         # casos difíciles; datos reales solo si existe eval/etiquetas.csv
poetry run python -m eval.calibrar_clasificacion  # imprime los umbrales provisionales (no escribe config/)
poetry run pytest tests/test_casos_dificiles.py   # los casos difíciles contra el clasificador real
```

`eval.clasificacion` termina con código 2 si falta `eval/etiquetas.csv` (como `eval.ruido`) y deja igualmente los casos
difíciles en `outputs/clasificacion.json`. Con el CSV consolidado de E1-06 (`tema_principal`, `ruido`, `estrato`,
`peso_muestreo`, ...) reporta, **sin ponderar y ponderado por `peso_muestreo`**, dos vistas: el clasificador solo (titulares que
el filtro de ruido dejó pasar) y el pipeline completo (el filtro cuenta como `sin_tema` predicho).

## Qué se guarda en DuckDB

La spec escribe «llena `tema`, `tema_similitud` y `tema_baseline`». **Se llenan `tema_clasificado`, `tema_similitud` y
`tema_baseline`**: `tema` es el tema de **origen** del contrato y no se toca (D-62, CLAUDE.md); sobrescribirlo sería una
fuga de información. La corrida es transaccional: si falla a mitad de camino (o faltan requisitos), la corrida anterior queda
intacta.

| Dónde | Campo | Contenido |
|---|---|---|
| `noticias` | `tema_clasificado` | Uno de los 6 temas o `sin_tema` (la mayor similitud no llega al umbral). Nulo en el ruido |
| | `tema_similitud` | Mayor similitud coseno (también cuando es `sin_tema`, para explicar la abstención) |
| | `subtema_clasificado` | Solo con el método B: el subtema más parecido dentro del tema |
| | `tema_secundario`, `tema_secundario_similitud` | Segundo tema, solo si está a menos de `margen_secundario` y supera el umbral |
| | `tema_baseline` | Tema del baseline de palabras clave de la variante `guia` (las mismas categorías) |
| | `similitud_panama`, `ruido_similitud` | Señal del filtro de ruido por prototipo (D-84) y marca si lo aplicó |
| `similitud_tema` | `id_noticia, metodo, tema, similitud, subtema` | Similitud con **cada** tema, por método A y B (explicabilidad) |

Solo se clasifica `titulo_limpio` de los registros con `es_ruido = false` (más la descripción del RSS como texto interno si
existiera; el snapshot actual no la trae). Los embeddings se cachean en disco por modelo y revisión (`.cache/embeddings/`,
ignorada por git); la caché guarda el hash del texto, **nunca el texto**.

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
- **Baseline por palabras clave (D-66), en dos variantes** (revisión X15). Ambas usan las mismas categorías y el mismo
  puntaje (términos distintos que coinciden; empate = el primero de `temas.yaml`; sin coincidencias = `sin_tema`):
  - **`baseline` (variante `guia`, la principal):** solo términos que aparecen literalmente en `docs/guia_temas.md` fuera de los
    casos difíciles (columnas «Incluye» / «No incluye» y reglas de frontera); un test lo comprueba término por término.
  - **`baseline_ampliado`:** además la `extension`, vocabulario que agregó quien escribió el baseline (siglas, sinónimos,
    formas léxicas). **Esa persona ya había leído los casos difíciles** al escribirlo, y varios términos (`asep`,
    `asamblea`, `homicidio`, `aerolinea`) coinciden con ellos; por eso **no es independiente de los casos difíciles** y se reporta
    aparte. Una versión anterior de este documento afirmaba que el baseline era independiente de los casos difíciles:
    no era demostrable y se retiró.
- **Criterio A vs. B (D-21/D-57), fijado en el YAML antes de medir:** B solo si el IC 95 % (bootstrap pareado, 1.000
  remuestreos, semilla 42) de la diferencia de macro-F1 B − A **excluye el cero a favor de B** y **ningún tema con soporte
  empeora de forma significativa** (IC 95 % de su diferencia de F1 enteramente por debajo de cero). Se decide con los límites
  **sin redondear**. Si no, A. `metodo_activo: A`.
- **Macro-F1:** promedia las clases con soporte en las etiquetas; una clase que solo se predice (p. ej. `sin_tema` cuando no hay
  casos `sin_tema`) no entra en el promedio, pero sus falsos positivos restan recall a las clases verdaderas.

## Fuga por paráfrasis (revisión X15, H4)

Los casos difíciles son de prueba y **no pueden estar en `temas.yaml`, ni literales ni parafraseados**. Antes solo se
comprobaba la igualdad literal (o Jaccard de palabras ≥ 0.8). La revisión señaló que varios prototipos eran paráfrasis de un
caso (Gatún/tránsitos ↔ CD-01, agua potable ↔ CD-02, resolución sobre tarifas ↔ CD-04, medicamentos ↔ CD-11, estudiantes
que pierden clases ↔ CD-12). Ahora `eval.clasificacion.fuga_semantica` mide el coseno entre cada caso y cada ejemplo o
prototipo con MiniLM (e5 comprime todo entre 0.80 y 0.91 y no sirve para esto), ignorando «Panamá», y **falla si alguno llega
a 0.58** (`fuga_semantica.umbral_coseno`). Ese umbral es un **supuesto elegido después de ver los pares**: detecta las
paráfrasis de CD-02, CD-11 y CD-12 y pares de vocabulario casi idéntico, pero **no** alcanza a CD-01 (0.56 con el prototipo
original). Se reescribieron 14 ejemplos y prototipos de `config/temas.yaml` (los 5 que señaló la revisión más los que superaban
el umbral) por otros ejemplos del mismo subtema; con las referencias actuales el par más alto es 0.57. Los ejemplos reales
del snapshot no se tocaron.

## Resultados sobre los casos difíciles (n = 15) · 2026-10-06, después de X15

n = 15 y 7 clases: los IC son muy anchos y **no alcanzan para elegir modelo (D-20) ni método (D-21)**. El macro-F1 incluye
`sin_tema`, que tiene un solo caso (CD-15): ese único acierto o fallo mueve mucho la cifra.

| Configuración | Tema principal (k/15, IC 95 % Wilson) | Macro-F1 (IC 95 % bootstrap) | Antes de X15 |
|---|---|---|---|
| **Baseline (guía)** | 12/15 = 80.0 % [54.8–93.0] | 0.821 [0.515–1.000] | 14/15 (versión con vocabulario agregado) |
| Baseline ampliado (guía + extensión) | **14/15 = 93.3 %** [70.2–98.8] | **0.924** [0.680–1.000] | 14/15 |
| e5 · A (**activo**) | 11/15 = 73.3 % [48.0–89.1] | 0.653 [0.362–0.943] | 11/15 |
| e5 · B | 10/15 = 66.7 % [41.7–84.8] | 0.587 [0.318–0.838] | 12/15 |
| MiniLM · A | 9/15 = 60.0 % [35.8–80.2] | 0.600 [0.267–0.815] | 8/15 |
| MiniLM · B | 6/15 = 40.0 % [19.8–64.2] | 0.343 [0.122–0.561] | **13/15** |

**B cayó al quitar las paráfrasis** (e5: 12 → 10; MiniLM: 13 → 6): parte de lo que B «acertaba» antes era fuga, no
generalización. Con las referencias corregidas B no supera a A en ningún modelo.

Diferencias de macro-F1 (bootstrap pareado, IC 95 %):

| Comparación | Diferencia | IC 95 % | Lectura |
|---|---|---|---|
| e5: B − A | −0.067 | [−0.389, 0.298] | incluye el cero → criterio elige **A** |
| MiniLM: B − A | −0.257 | [−0.533, 0.129] | incluye el cero y Turismo empeora → criterio elige **A** (antes elegía B) |
| e5 · A − baseline (guía) | −0.168 | [−0.400, 0.189] | incluye el cero |
| e5 · B − baseline (guía) | −0.235 | [−0.512, 0.142] | incluye el cero |
| MiniLM · A − baseline (guía) | −0.221 | [−0.494, 0.043] | incluye el cero |
| MiniLM · B − baseline (guía) | −0.479 | [−0.673, −0.192] | el baseline es mejor |

Lectura honesta (D-66, «cuándo la IA no ayuda»):

- **En estos 15 casos los dos baselines le ganan o igualan al modelo activo (guía 12/15, ampliado 14/15, e5 · A 11/15)**, pero
  con IC que se solapan casi por completo. Los casos están escritos con el vocabulario de la propia guía («tránsitos», «sismo»,
  «GAFI», «carga aérea»), que es lo que las palabras clave detectan; **no es evidencia de que el baseline sea mejor en titulares
  reales**, donde 44 de los 79 titulares útiles no activan ningún término de la variante `guia` (la ampliada no se midió sobre los datos reales).
- Los embeddings deberían ganar donde no hay vocabulario compartido, y eso este conjunto casi no lo mide. La comparación que
  cuenta es la de los datos reales con `eval/etiquetas.csv` (pendiente).
- **Elección de modelo y método: no decidible todavía.** Se mantienen `e5` (propuesta D-20) y `A` (criterio D-57 por defecto).
- Tema secundario esperado (7 casos): con el margen provisional se acierta 2/7 (e5 · A); el 2.º mejor coincide en 4/7: el
  problema es sobre todo el margen, no el orden (ver «Umbrales provisionales»).

## Limitaciones conocidas (los fallos no se ocultan)

Con el modelo y método activos (e5 · A). `tests/test_casos_dificiles.py` los declara `xfail(strict=True)`: si cambian, el test
obliga a actualizar esta tabla.

| Caso | Titular | Esperado | Predicho | Observación (solo lo observado, sin causa comprobada) |
|---|---|---|---|---|
| CD-02 | Lluvias dejan sin agua a sectores de San Miguelito | Servicios públicos (secundario Eventos naturales) | Eventos naturales | La regla 4 (falla de un servicio) no se cumple. El baseline de la guía también falla; el ampliado acierta |
| CD-04 | ASEP aprueba aumento de la tarifa eléctrica | Regulación (secundario Servicios públicos) | Servicios públicos | La regla 2 (norma nueva) no se cumple. El baseline de la guía da `sin_tema`; el ampliado acierta (por `asep`, que no está en la guía) |
| CD-08 | Aumenta la carga aérea en Tocumen | Logística/Canal | Turismo | La regla 6 (carga ≠ pasajeros) no se cumple; los dos baselines aciertan |
| CD-15 | Selección de fútbol clasifica al Mundial | `sin_tema` | Eventos naturales | Similitud máxima 0.844, sobre el umbral 0.825 de e5. **En el pipeline no llega al clasificador:** el filtro de ruido (E1-03b) lo marca `fuera_de_temas` (`test_el_futbol_se_descarta_antes_por_el_filtro_de_ruido`) |
| CD-02, CD-04, CD-14 (secundario) | (los anteriores) · Gobierno firma nuevo contrato minero | secundario Eventos naturales · Servicios públicos · Economía | 2.º mejor: Servicios públicos · Economía · Logística/Canal | CD-02 y CD-04 ya tenían mal el principal; en CD-14 el principal es correcto y el secundario no |

Limitaciones generales:

- e5 comprime las similitudes (0.81–0.91 en el snapshot): una diferencia de 0.003 decide el tema secundario. MiniLM tiene una
  escala más amplia (0.17–0.75).
- La regla de frontera «hecho central, no consecuencias» no está codificada: A y B comparan similitud, no razonan.
- Con n = 15 no se puede decir que e5 sea peor o mejor que MiniLM; los IC se solapan casi por completo.
- El umbral de fuga semántica (0.58) y los umbrales de «sin tema» son supuestos (ver abajo).

## Datos reales (79 titulares útiles; solo distribución, no exactitud)

Snapshot del 2026-10-06: 186 noticias, 107 marcadas como ruido por palabras clave, **79 útiles** (**52 titulares únicos**: varias
URL repiten el mismo titular, p. ej. 14 veces «Intensifying El Niño…», que pesan en los conteos y E1-08 agrupará). Distribución de
e5 · A (activo, con las referencias de `temas.yaml` corregidas), con IC de Wilson al 95 % **descriptivo** (el snapshot no es una
muestra aleatoria):

| Tema | Registros (de 79) | IC 95 % | Titulares únicos (de 52) |
|---|---|---|---|
| Eventos naturales | 24 (30.4 %) | [21.3, 41.2] | 6 |
| Servicios públicos | 19 (24.1 %) | [16.0, 34.5] | 19 |
| `sin_tema` | 12 (15.2 %) | [8.9, 24.7] | 3 |
| Economía | 10 (12.7 %) | [7.0, 21.8] | 10 |
| Regulación | 6 (7.6 %) | [3.5, 15.6] | 6 |
| Logística/Canal | 5 (6.3 %) | [2.7, 14.0] | 5 |
| Turismo | 3 (3.8 %) | [1.3, 10.6] | 3 |

Acuerdo (no exactitud) sobre los mismos 79: e5·A coincide con el baseline de la guía en 40/79, con e5·B en 31/79 y con MiniLM·A
en 50/79. Los métodos discrepan mucho en datos reales, otra razón para no elegir con n = 15. El baseline de la guía deja 44/79
sin tema (ningún término).

## Umbrales provisionales (supuesto, no calibrados con etiquetas)

`umbral_sin_tema` y `margen_secundario` salen de `python -m eval.calibrar_clasificacion` con una regla fija: percentil 5 de la
similitud máxima y percentil 25 de la brecha entre la mejor y la segunda, sobre los 52 titulares únicos útiles. Se recalcularon
tras corregir las referencias (e5 · A 0.825 / 0.003, e5 · B 0.797 / 0.003, MiniLM · A 0.224 / 0.038, MiniLM · B 0.283 / 0.016).
**Es un supuesto** (se abstiene el 5 % menos parecido; el 25 % de brecha más corta recibe secundario), no una medición de qué es
«sin tema». Diagnóstico descriptivo: separando los titulares que el filtro de palabras clave marcó `fuera_de_temas` (n = 16) de
los útiles, la similitud máxima de e5·A da AUC 0.79 y la de MiniLM·A 0.74, con marcas que **no son etiquetas humanas**. Se
recalibran con `eval/etiquetas.csv`.

## Filtro de ruido por similitud con un prototipo de Panamá (D-84, diferido desde E1-03b)

**Implementado, pero `activo: false` en `config/ruido.yaml`.** Con él activo, un titular no marcado como ruido ni como alcance
regional y cuya similitud máxima con los prototipos de Panamá es menor que `umbral` se marca `no_es_panama` (`ruido_similitud =
true`, reversible al volver a correr); una nota regional no se marca nunca. Medición disponible sin etiquetas humanas:

- Con el umbral sugerido para e5 (0.774) marcaría **2 de los 79 útiles**: una es de alcance regional (no se marcaría) y la
  otra es «Tres hombres asaltan casino… en San Miguelito», una noticia sobre Panamá: **un falso positivo evidente**.
- Dejaría pasar **80 de los 107** registros que el filtro de palabras clave ya marcó como ruido (similitud ≥ umbral).
- AUC descriptivo 0.78 contra las marcas `no_es_panama` de palabras clave (no son etiquetas humanas).

Conclusión: con estos números la señal **no se activa**. La precisión y el recall reales se miden con `python -m eval.ruido`
sobre `eval/etiquetas.csv`; mientras tanto `ruido.yaml` conserva el hook y se guarda `similitud_panama` por noticia.

## Pendiente

1. **Etiquetas humanas:** cuando exista `eval/etiquetas.csv` (herramienta de E1-06), correr `poetry run python -m
   eval.clasificacion`: macro-F1, F1/precisión/recall por tema, matriz de confusión y criterio A vs. B con n e IC, sin
   ponderar y ponderado, sobre titulares sin los ejemplos de `ejemplos_excluidos.txt`. Un titular que una persona marcó como
   ruido cuenta como abstención correcta (`sin_tema`).
2. Con esas métricas: decidir modelo (D-20, de «propuesta» a «aceptada») y método (D-21), recalibrar los umbrales (incluido el
   de fuga semántica) y decidir si se activa el filtro por similitud. **La elección se registra en Notion con los números** (no
   hay números reales todavía, así que no se registró nada).
3. `docs/ia_vs_baseline.md` (D-66) lo completan E1-11 y E1-18 con las demás tareas.
