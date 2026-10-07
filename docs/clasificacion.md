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
poetry run python -m eval.diagnostico_temas        # E1-07b: errores de tema vs. etiquetas humanas, por evento (outputs/diagnostico_temas.json)
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
| | `similitud_panama`, `ruido_similitud` | Señal del filtro de ruido por prototipo (revisión X14 de E1-03b) y marca si lo aplicó |
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
a 0.56** (`fuga_semantica.umbral_coseno`). Ese umbral es un **supuesto elegido después de ver los pares**.

- Se reescribieron 14 ejemplos y prototipos de `config/temas.yaml` por otros ejemplos del mismo subtema: los 5 que señaló la
  revisión, los que superaban el umbral y, en la ronda final, el ejemplo de los maestros (0.569 con CD-12), `operacion_canal`
  (ahora trata de la **operación del Canal**: esperas de buques en el fondeo antes de las esclusas; las reglas de la ACP son
  Regulación por la regla 2), `agua_potable` (ahora dice explícitamente «suministro de agua potable») y los dos que nombraban
  aerolíneas reales (ahora redacción genérica).
- **Queda un par sobre 0.56, aceptado de forma explícita:** CD-02 («Lluvias dejan sin agua a sectores de San Miguelito») con
  el ejemplo **real** del snapshot «Clima en Panamá: Martes con lluvias y tormentas eléctricas…» (0.566). Es un titular real,
  su `id_noticia` está en `ejemplos_excluidos.txt` y no se puede reescribir; la coincidencia es de tema (lluvias), no una
  paráfrasis. Está en `fuga_semantica.excepciones_aceptadas`, y un test exige que toda excepción sea un ejemplo real y siga
  sobre el umbral (si deja de estarlo, hay que quitarla).
- Límite del detector: es una medida con un solo modelo y un umbral supuesto; no prueba que no haya otras paráfrasis.

Pares más cercanos entre un caso difícil y un ejemplo o prototipo (MiniLM, sin «Panamá»), con las referencias actuales:

| # | Caso | Referencia (`temas.yaml`) | Coseno | Estado |
|---|---|---|---|---|
| 1 | CD-02 | `eventos_naturales.ejemplo[0]` (**real**, snapshot) | 0.566 | sobre el umbral; excepción aceptada |
| 2 | CD-07 | `logistica.ejemplo[5]` | 0.543 | bajo el umbral |
| 3 | CD-08 | `turismo.ejemplo[0]` (real) | 0.537 | bajo el umbral |
| 4 | CD-07 | `turismo.ejemplo[0]` (real) | 0.535 | bajo el umbral |
| 5 | CD-04 | `economia.inflacion_precios` | 0.531 | bajo el umbral |
| 6 | CD-10 | `regulacion.ejemplo[6]` | 0.521 | bajo el umbral |
| 7 | CD-03 | `eventos_naturales.deslizamientos` | 0.519 | bajo el umbral |
| 8 | CD-02 | `eventos_naturales.ejemplo[9]` | 0.515 | bajo el umbral |
| 9 | CD-02 | `servicios_publicos.agua_potable` | 0.506 | bajo el umbral |
| 10 | CD-10 | `regulacion.reformas` | 0.506 | bajo el umbral |

Para reproducirla: `eval.clasificacion.pares_mas_parecidos(...)`.

## Resultados sobre los casos difíciles (n = 15) · 2026-10-06, versión final

n = 15 y 7 clases: los IC son muy anchos y **no alcanzan para elegir modelo (D-20) ni método (D-21)**. El macro-F1 incluye
`sin_tema`, que tiene un solo caso (CD-15): ese único acierto o fallo mueve mucho la cifra.

| Configuración | Tema principal (k/15, IC 95 % Wilson) | Macro-F1 (IC 95 % bootstrap) | Primera versión (antes de X15) |
|---|---|---|---|
| **Baseline (guía)** | 12/15 = 80.0 % [54.8–93.0] | 0.821 [0.515–1.000] | 14/15 (con vocabulario agregado) |
| Baseline ampliado (guía + extensión) | **14/15 = 93.3 %** [70.2–98.8] | **0.924** [0.680–1.000] | 14/15 |
| e5 · A (**activo**) | 10/15 = 66.7 % [41.7–84.8] | 0.614 [0.328–0.881] | 11/15 |
| e5 · B | 9/15 = 60.0 % [35.8–80.2] | 0.432 [0.216–0.725] | 12/15 |
| MiniLM · A | 9/15 = 60.0 % [35.8–80.2] | 0.600 [0.267–0.815] | 8/15 |
| MiniLM · B | 6/15 = 40.0 % [19.8–64.2] | 0.343 [0.122–0.561] | 13/15 |

**B cayó tras reescribir las referencias; no se separó cuánto es fuga y cuánto representatividad** (e5: 12 → 9; MiniLM: 13 → 6).
Con las referencias corregidas B no supera a A en ningún modelo. También cambió e5 · A (11 → 10): CD-12 pasó a fallar al
reescribir el ejemplo de los docentes.

Diferencias de macro-F1 (bootstrap pareado, IC 95 %):

| Comparación | Diferencia | IC 95 % | Lectura |
|---|---|---|---|
| e5: B − A | −0.182 | [−0.495, 0.265] | incluye el cero y Turismo empeora → criterio elige **A** |
| MiniLM: B − A | −0.257 | [−0.533, 0.129] | incluye el cero y Turismo empeora → criterio elige **A** |
| e5 · A − baseline (guía) | −0.208 | [−0.449, 0.144] | incluye el cero |
| e5 · B − baseline (guía) | −0.390 | [−0.625, 0.049] | incluye el cero |
| MiniLM · A − baseline (guía) | −0.221 | [−0.494, 0.043] | incluye el cero |
| MiniLM · B − baseline (guía) | −0.479 | [−0.673, −0.192] | el baseline es mejor |

Lectura honesta (D-66, «cuándo la IA no ayuda»):

- **En estos 15 casos los dos baselines le ganan o igualan al modelo activo (guía 12/15, ampliado 14/15, e5 · A 10/15)**, con
  IC que se solapan casi por completo. Los casos están escritos con el vocabulario de la propia guía («tránsitos», «sismo»,
  «GAFI», «carga aérea»), que es lo que las palabras clave detectan; **no es evidencia de que el baseline sea mejor en titulares
  reales**, donde 44 de los 79 titulares útiles no activan ningún término de la variante `guia`. Con etiquetas humanas (abajo)
  la comparación es otra.
- **Elección de modelo y método: no decidible con los casos difíciles.** Se mantienen `e5` (propuesta D-20) y `A` (D-57).
- Tema secundario esperado (7 casos): con el margen provisional se acierta **1/7** (e5 · A: solo CD-05; lo fija
  `test_el_tema_secundario_guardado_de_cada_caso_esta_fijado`); el 2.º mejor coincide en 4/7: el problema es sobre todo el
  margen, no el orden.

## Limitaciones conocidas (los fallos no se ocultan)

Con el modelo y método activos (e5 · A). `tests/test_casos_dificiles.py` los declara `xfail(strict=True)`: si cambian, el test
obliga a actualizar esta tabla.

| Caso | Titular | Esperado | Predicho | Observación (solo lo observado, sin causa comprobada) |
|---|---|---|---|---|
| CD-02 | Lluvias dejan sin agua a sectores de San Miguelito | Servicios públicos (secundario Eventos naturales) | Eventos naturales | La regla 4 (falla de un servicio) no se cumple. El baseline de la guía también falla; el ampliado acierta |
| CD-04 | ASEP aprueba aumento de la tarifa eléctrica | Regulación (secundario Servicios públicos) | Servicios públicos | La regla 2 (norma nueva) no se cumple. El baseline de la guía da `sin_tema`; el ampliado acierta (por `asep`, que no está en la guía) |
| CD-08 | Aumenta la carga aérea en Tocumen | Logística/Canal | Turismo | La regla 6 (carga ≠ pasajeros) no se cumple; los dos baselines aciertan |
| CD-12 | Paro docente deja sin clases a escuelas | Servicios públicos | Eventos naturales | Apareció al reescribir las referencias (con el ejemplo anterior de los docentes acertaba); los dos baselines aciertan |
| CD-15 | Selección de fútbol clasifica al Mundial | `sin_tema` | Eventos naturales | Similitud máxima 0.844, sobre el umbral 0.824 de e5. **En el pipeline no llega al clasificador:** el filtro de ruido (E1-03b) lo marca `fuera_de_temas` (`test_el_futbol_se_descarta_antes_por_el_filtro_de_ruido`) |
| CD-02, CD-04, CD-14 (secundario, 2.º mejor) | (los anteriores) · Gobierno firma nuevo contrato minero | secundario Eventos naturales · Servicios públicos · Economía | 2.º mejor: Servicios públicos · Economía · Logística/Canal | CD-02 y CD-04 ya tenían mal el principal; en CD-14 el principal es correcto y el secundario no |

Limitaciones generales:

- e5 comprime las similitudes (0.81–0.91 en el snapshot): una diferencia de 0.003 decide el tema secundario. MiniLM tiene una
  escala más amplia (0.17–0.75).
- La regla de frontera «hecho central, no consecuencias» no está codificada: A y B comparan similitud, no razonan.
- Con n = 15 no se puede decir que e5 sea peor o mejor que MiniLM; los IC se solapan casi por completo.
- El umbral de fuga semántica (0.58) y los umbrales de «sin tema» son supuestos (ver abajo).

## Datos reales sin etiquetas: distribución (79 titulares útiles; no es exactitud)

Snapshot del 2026-10-06: 186 noticias, 107 marcadas como ruido por palabras clave, **79 útiles** (**52 titulares únicos**: varias
URL repiten el mismo titular, p. ej. 14 veces «Intensifying El Niño…», que pesan en los conteos y E1-08 agrupará). Distribución de
e5 · A (activo), con IC de Wilson al 95 % **descriptivo** (el snapshot no es una muestra aleatoria):

| Tema | Registros (de 79) | IC 95 % | Titulares únicos (de 52) |
|---|---|---|---|
| Eventos naturales | 25 (31.6 %) | [22.5, 42.6] | 7 |
| Servicios públicos | 18 (22.8 %) | [14.9, 33.2] | 18 |
| `sin_tema` | 12 (15.2 %) | [8.9, 24.7] | 3 |
| Economía | 10 (12.7 %) | [7.0, 21.8] | 10 |
| Regulación | 6 (7.6 %) | [3.5, 15.6] | 6 |
| Logística/Canal | 5 (6.3 %) | [2.7, 14.0] | 5 |
| Turismo | 3 (3.8 %) | [1.3, 10.6] | 3 |

Acuerdo (no exactitud) sobre los mismos 79: e5·A coincide con el baseline de la guía en 39/79, con e5·B en 35/79 y con MiniLM·A
en 51/79. El baseline de la guía deja 44/79 sin tema (ningún término).

## Evaluación con etiquetas humanas (`eval/etiquetas.csv`, D-85)

100 titulares etiquetados por una persona (E1-06), muestra estratificada: 63 pasaron el filtro de ruido y 37 los descartó. Ningún
etiquetado es ejemplo excluido ni falta en la base. Una persona que marcó ruido cuenta como `sin_tema` (abstención correcta).
**Limitaciones de estos números:** una sola persona etiquetó (el acuerdo entre etiquetadores no se puede estimar aquí); la muestra
repite titulares (71 titulares distintos en 100: 20 veces «Intensifying El Niño…» con sus variantes y 10 «Trump streicht Europa…»), así que el n efectivo es menor;
y hay clases con soporte 1 (Logística/Canal, Turismo, Regulación) que mueven mucho el macro-F1. Comando:
`HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion` (detalle completo en `outputs/clasificacion.json`).

**Vista 1: clasificador solo** (n = 63, los que pasaron el filtro; todos del mismo estrato, por eso ponderar no cambia nada).
Exactitud con IC de Wilson 95 %; macro-F1 con IC de bootstrap (1.000 remuestreos, semilla 42):

| Configuración | Tema principal (k/63) | Macro-F1 |
|---|---|---|
| Baseline (guía) | 29/63 = 46.0 % [34.3–58.2] | 0.515 [0.277–0.607] |
| Baseline ampliado | 30/63 = 47.6 % [35.8–59.7] | 0.525 [0.291–0.616] |
| **e5 · A (activo)** | **33/63 = 52.4 %** [40.3–64.2] | 0.401 [0.245–0.510] |
| e5 · B | 14/63 = 22.2 % [13.7–33.9] | 0.173 [0.091–0.261] |
| MiniLM · A | 31/63 = 49.2 % [37.3–61.2] | 0.357 [0.214–0.458] |
| MiniLM · B | 26/63 = 41.3 % [30.0–53.6] | 0.237 [0.149–0.318] |

**Vista 2: pipeline completo** (n = 100: el filtro de ruido cuenta como `sin_tema` predicho), sin ponderar y ponderado por
`peso_muestreo` (la proporción ponderada no lleva IC: el peso no es un conteo):

| Configuración | Exactitud sin ponderar (k/100) | Exactitud ponderada | Macro-F1 sin ponderar | Macro-F1 ponderado |
|---|---|---|---|---|
| Baseline (guía) | 65/100 = 65.0 % [55.2–73.6] | 0.783 | 0.545 [0.338–0.666] | 0.531 [0.369–0.683] |
| Baseline ampliado | 66/100 = 66.0 % [56.3–74.5] | 0.789 | 0.555 [0.350–0.679] | 0.541 [0.378–0.689] |
| **e5 · A (activo)** | **69/100 = 69.0 %** [59.4–77.2] | **0.807** | 0.491 [0.336–0.621] | 0.484 [0.353–0.624] |
| e5 · B | 50/100 = 50.0 % [40.4–59.6] | 0.695 | 0.288 [0.206–0.388] | 0.304 [0.225–0.406] |
| MiniLM · A | 67/100 = 67.0 % [57.3–75.4] | 0.795 | 0.460 [0.335–0.564] | 0.446 [0.340–0.561] |
| MiniLM · B | 62/100 = 62.0 % [52.2–70.9] | 0.765 | 0.366 [0.280–0.447] | 0.374 [0.289–0.452] |

**Criterio A vs. B (D-57), sobre la vista 1:**

| Modelo | B − A macro-F1 | IC 95 % | Decisión |
|---|---|---|---|
| e5 | −0.227 | [−0.372, −0.036] | **A** (el IC excluye el cero **a favor de A**; además Eventos naturales empeora con B) |
| MiniLM | −0.119 | [−0.256, 0.032] | **A** (el IC incluye el cero: no hay evidencia de que B mejore) |

Frente al baseline (macro-F1, vista 1): e5 · A − baseline guía = −0.114 [−0.293, 0.106] (incluye el cero); e5 · B − baseline
guía = −0.342 [−0.418, −0.137] (el baseline es mejor); MiniLM · A = −0.158 [−0.277, 0.011]; MiniLM · B = −0.278 [−0.423, −0.047].

Lectura honesta:

- **A gana a B con claridad y B queda descartado**; el criterio elige A con los dos modelos.
- **Sobre exactitud, e5 · A es la mejor configuración** (52.4 % frente a 46.0 % del baseline de la guía en la vista 1; 69.0 % frente a
  65.0 % en el pipeline), **pero los IC se solapan casi por completo: no hay diferencia demostrada.**
- **Sobre macro-F1, los dos baselines quedan por encima de e5 · A** (0.515 y 0.525 frente a 0.401), también con IC solapados. La
  razón visible en los datos: casi todo el soporte es Economía (26) y Eventos naturales (20) y el baseline acierta casi todo
  Eventos naturales (F1 0.98 frente a 0.93) y las clases de soporte 1 (Logística y Turismo: F1 1.0 el baseline; 0.67 y 0.0 e5 · A).
  Estas clases con un solo titular pesan igual que Economía en el macro-F1.
- **e5 · A nunca acierta `sin_tema`** (0/12 predichos, 0/5 reales, F1 0.0): el umbral provisional no abstiene donde debe. El
  baseline predice `sin_tema` 34 veces con 3 aciertos (F1 0.16). Economía es la clase de mayor soporte y la peor resuelta:
  F1 0.30 con e5 · A y 0.14 con el baseline (varias notas regionales sobre América Latina que una persona etiquetó Economía).
- **No se cambia el modelo ni el método:** se mantienen `e5` y `A` (D-20 sigue «propuesta»; MiniLM · A queda a 2 aciertos de e5 · A
  en las dos vistas). Decidir D-20 con más etiquetas y más de una persona. La elección se registra en Notion
  con estos números (no se registró desde este entorno).

## Umbrales provisionales (supuesto, no calibrados con etiquetas)

`umbral_sin_tema` y `margen_secundario` salen de `python -m eval.calibrar_clasificacion` con una regla fija: percentil 5 de la
similitud máxima y percentil 25 de la brecha entre la mejor y la segunda, sobre los 52 titulares únicos útiles. Se recalcularon
tras corregir las referencias (e5 · A 0.824 / 0.002, e5 · B 0.797 / 0.004, MiniLM · A 0.213 / 0.030, MiniLM · B 0.283 / 0.019).
**Es un supuesto** (se abstiene el 5 % menos parecido; el 25 % de brecha más corta recibe secundario), no una medición de qué es
«sin tema». Diagnóstico descriptivo: separando los titulares que el filtro de palabras clave marcó `fuera_de_temas` (n = 16) de
los útiles, la similitud máxima de e5·A da AUC 0.79 y la de MiniLM·A 0.73, con marcas que **no son etiquetas humanas**. La recalibración con `eval/etiquetas.csv` se intentó en E1-07b y **no respalda ningún
valor** (sección siguiente).

## Filtro de ruido por similitud con un prototipo de Panamá (diferido desde E1-03b en la revisión X14)

**Implementado, pero `activo: false` en `config/ruido.yaml`.** Con él activo, un titular no marcado como ruido ni como alcance
regional y cuya similitud máxima con los prototipos de Panamá es menor que `umbral` se marca `no_es_panama` (`ruido_similitud =
true`, reversible al volver a correr); una nota regional no se marca nunca. Medición disponible sin etiquetas humanas:

- Con el umbral sugerido para e5 (0.774) marcaría **2 de los 79 útiles**: una es de alcance regional (no se marcaría) y la
  otra es «Tres hombres asaltan casino… en San Miguelito», una noticia sobre Panamá: **un falso positivo evidente**.
- Dejaría pasar **80 de los 107** registros que el filtro de palabras clave ya marcó como ruido (similitud ≥ umbral).
- AUC descriptivo 0.78 contra las marcas `no_es_panama` de palabras clave (no son etiquetas humanas).

Conclusión: con estos números la señal **no se activa**. La precisión y el recall reales se miden con `python -m eval.ruido`
sobre `eval/etiquetas.csv`; mientras tanto `ruido.yaml` conserva el hook y se guarda `similitud_panama` por noticia.

## Diagnóstico de los errores de tema con etiquetas humanas (E1-07b, 2026-10-07)

**Resultado: no hay una corrección respaldada por las etiquetas y no se cambió ni el modelo, ni el método, ni un umbral, ni
una referencia.** Lo que sí queda es el diagnóstico, su causa raíz y la herramienta que lo reproduce:
`HF_HUB_OFFLINE=1 poetry run python -m eval.diagnostico_temas` (salida: `outputs/diagnostico_temas.json`; sin tocar la base
ni `config/`). Los pasos 1–5 de abajo usan **solo etiquetas humanas** (D-85); el juicio previo del asistente sobre los grupos
(~25 de 57 con tema equivocado) no se usa como dato.

**Protocolo.** Evaluación: las 63 filas de `eval/etiquetas.csv` que el filtro de ruido dejó pasar (los 16 titulares de
`ejemplos_excluidos.txt` no entran: 0 de ellos están en las etiquetas). Unidad de análisis: **el evento** (`grupo` de la
etiqueta, o la propia noticia si no tiene), porque las filas se repiten: las 63 son **29 eventos** y uno solo (El Niño) pone 20
filas. IC por fila: Wilson 95 %; IC por evento: bootstrap sobre eventos (1.000 remuestreos, semilla 42). Calibración del umbral:
validación cruzada de 5 pliegues por evento × 20 particiones (semilla 20261007); el umbral se elige en el entrenamiento
(candidatos solo de ahí) y se mide en el pliegue que no vio. Los puntos de corte de las opciones se definen por **percentil
sobre los 94 titulares útiles del snapshot v1.2, sin usar las etiquetas**. Todo esto se declaró antes de medir.

**Limitaciones que condicionan cualquier conclusión.** (1) Una sola persona etiquetó (D-85); no hay kappa. (2) Las etiquetas son
un **censo del estrato «no ruido»** del snapshot anterior: no existen datos de prueba independientes de los que sirvieron para
diagnosticar, así que toda mejora medida aquí es **optimista**. (3) `sin_tema` tiene **5 filas en 5 eventos**: cualquier
proporción o AUC sobre abstención es anecdótico. (4) Los 63 incluyen 15 titulares nuevos de v1.2 sin etiquetar (94 útiles en total).

### 1 · Medición (e5 · A, umbral 0.824)

| Qué | Resultado (n = 63 filas, 29 eventos) |
|---|---|
| Exactitud del tema principal | 33/63 = 52.4 % [IC 95 % Wilson 40.3–64.2] por fila; **0.466 [0.310–0.638] por evento** |
| Macro-F1 (7 clases con soporte) | 0.401 [0.245–0.510] |
| Recall por tema (filas) | Economía 5/26 · Servicios públicos 6/9 · Eventos naturales 20/20 · Logística 1/1 · Regulación 1/1 · Turismo 0/1 · `sin_tema` 0/5 |
| Errores (30 filas) | **abstención falsa 12/63 = 19.0 % [11.2–30.4]** · abstención omitida 5/63 = 7.9 % [3.4–17.3] · **confusión entre temas 13/63 = 20.6 % [12.5–32.2]** |
| Eventos por tema humano | Economía 11 (acierto por evento 0.41) · Servicios públicos 9 (0.67) · Eventos naturales 1 · `sin_tema` 5 (0.0) · otros 3 |

La exactitud por fila **está inflada por un solo evento** (El Niño, 20 filas, todas acertadas): sin él son 13/43 = 30 %.
Los grupos del snapshot v1.2 confirman el cuadro con etiquetas humanas: de los 58 grupos, 31 tienen algún titular etiquetado y
en **13/31 = 41.9 % [26.4–59.2]** el tema del grupo coincide con el tema humano mayoritario (el juicio del asistente, ~25 de 57
equivocados, apuntaba en la misma dirección; no es una medición).

### 2 · Causa raíz

- **La asignación forzada NO es el error dominante** (hipótesis de partida, descartada con datos): solo 5/63 filas (los 5
  `sin_tema` humanos, 5 eventos distintos) se asignan a un tema cuando no correspondía. El error dominante es **otro**.
- **El error dominante recae en Economía:** 21 de los 30 errores (70 %) son filas que una persona etiquetó Economía, y los **12
  de la abstención falsa son todos Economía** (un solo evento, «Trump redirige ayuda a Latinoamérica»: 13 filas en 4 idiomas; se abstienen 10 en alemán, 1 en ucraniano
  y 1 en checo). Economía es 11 de 29 eventos y su recall es 5/26 = 19.2 % [8.5–37.9]; 17 de sus 26 filas son de **alcance regional**
  (D-84).
- **Cobertura de referencias:** `temas.yaml` define Economía solo con titulares **panameños** (2 reales y 5 ilustrativos); la
  regla D-84 (una nota regional o del exterior que afecta a Panamá se etiqueta con su tema) llegó después y no está en la
  descripción ni en los ejemplos. Es la explicación más compatible con los datos, **pero no está demostrada**: la corrección
  que la ataca no se sostiene (punto 4).
- **Escala de similitud de e5 (abstención):** las similitudes máximas están entre 0.81 y 0.91 y el margen entre el 1.º y el 2.º
  tema tiene mediana de 0.004; con eso el umbral del 5 % más bajo (0.824) abstiene por **idioma**, no por «no corresponde a ningún
  tema»: los 12 titulares abstenidos son el mismo evento en alemán, ucraniano y checo, con similitudes de 0.81–0.82 frente al
  umbral 0.824 (compatible con los datos; no se midió con una traducción).
- **Filtro de ruido (E1-03b):** 5 de 63 filas «útiles» son `sin_tema` para la persona: el filtro de palabras clave dejó pasar lo
  que no cubría su lista (política electoral sin norma, notas sobre otro país, vida privada). Es un falso negativo del filtro,
  no del clasificador.

### 3 · ¿Se puede abstener por similitud? No con estas etiquetas

| Señal | AUC | Lectura |
|---|---|---|
| Similitud máxima baja → `sin_tema` (5 positivos) | 0.483 | no separa (0.5 = azar) |
| Margen bajo → `sin_tema` | 0.566 | casi azar |
| Parecido a una clase «fuera de temas» (10 referencias de la guía) → `sin_tema` | 0.762 | señal débil, **5 positivos: anecdótica** |
| Similitud máxima alta → acierto (por evento) | 0.731 | señal moderada de **error**, no de «fuera de temas» |

Umbral por validación cruzada por evento (objetivo macro-F1, el de la sección 9.1): elige umbrales entre 0.824 y 0.860 y se
abstiene en ~35 filas por corrida (32 falsas); exactitud fuera de muestra **0.324**, peor que el activo (0.524 en la misma
muestra): con 5 positivos el macro-F1 «premia» abstenerse porque da un F1 no nulo a `sin_tema`. Con objetivo exactitud elige no
abstenerse en 87 de 100 decisiones (0.507). **Conclusión: el umbral de «sin tema» no es calibrable con 5 positivos; ningún valor
queda respaldado.** La nota pendiente («recalibrar el umbral») queda cerrada como **no identificable con las etiquetas
actuales**, no como resuelta.

### 4 · Opciones medidas (ninguna adoptada)

Cada fila reemplaza el comportamiento activo en las 63 etiquetadas (n = 63 filas, 29 eventos) y en los 94 titulares útiles de
v1.2. Δ = cambio en la exactitud **por evento** frente al activo (IC bootstrap pareado sobre eventos). Todas se midieron sobre el
mismo conjunto con el que se diagnosticó: son optimistas.

| Opción | Filas acertadas (IC 95 %) | Exactitud por evento [IC] | Δ por evento vs. activo [IC] | Efecto en v1.2 (94 útiles) |
|---|---|---|---|---|
| **Activo** (umbral 0.824) | 33/63 = 52.4 % [40.3–64.2] | 0.466 [0.310–0.638] | — | 12 titulares en `sin_tema` |
| Sin abstención por similitud | 34/63 = 54.0 % [41.8–65.7] | 0.468 [0.310–0.638] | +0.003 [0.000, 0.011] | 12 pasan de `sin_tema` a Regulación/Economía; macro-F1 baja a 0.354 |
| Abstener en el 10 % de menor margen | 30/63 = 47.6 % [35.8–59.7] | 0.362 [0.190–0.535] | −0.103 [−0.207, 0.000] | 9 titulares útiles más a `sin_tema` |
| Abstener en el 20 % de menor margen | 31/63 = 49.2 % [37.3–61.2] | 0.397 [0.241–0.569] | −0.069 [−0.241, 0.070] | 17 más a `sin_tema`; 2/5 abstenciones correctas, 13 falsas |
| Abstener en el 30 % de menor margen | 27/63 = 42.9 % [31.4–55.1] | 0.357 [0.207–0.529] | −0.109 [−0.310, 0.093] | 26 más a `sin_tema`; 3/5 correctas, 20 falsas (Eventos naturales 17/20) |
| Clase «fuera de temas», 1–10 % | 35/63 = 55.6 % [43.3–67.2] | 0.503 [0.333–0.675] | +0.037 [0.000, 0.112] | 1–10 titulares más a `sin_tema`; **1/5** abstenciones correctas, 0–5 falsas |
| Economía regional: solo descripción | 35/63 = 55.6 % [43.3–67.2] | 0.494 [0.333–0.656] | +0.029 [0.000, 0.075] | 5 titulares útiles cambian de tema; Economía 7/26 |
| Economía regional: solo ejemplos | 31/63 = 49.2 % [37.3–61.2] | 0.630 [0.455–0.793] | +0.164 [0.000, 0.311] | **34 de 94 cambian de tema**; Economía 22/26 pero **Eventos naturales 0/20** |
| Economía regional: descripción y ejemplos | 30/63 = 47.6 % [35.8–59.7] | 0.595 [0.411–0.756] | +0.130 [−0.017, 0.282] | 33 de 94 cambian de tema; Economía 22/26, Eventos naturales 0/20 |

Lectura:

- **Abstener por margen** reduce los aciertos desde el primer porcentaje y solo alcanza 2–3 de las 5 abstenciones correctas a
  costa de 13–20 falsas: **sacaría de la bandeja entre 9 y 26 de 94 titulares útiles** para acertar, como mucho, 3.
- **La clase «fuera de temas»** atrapa 1 de 5; su mejora (+1 fila) viene de quitar las 12 abstenciones falsas del umbral
  actual, no de la clase.
- **Cobertura de Economía regional:** con ejemplos sube Economía de 5/26 a 22/26 y la exactitud por evento (+0.16), pero el evento
  de El Niño (20 filas; la persona puso Economía como alternativa razonable) pasa a Economía: Eventos naturales 0/20, Economía
  se vuelve el sumidero (45 de 63 predicciones) y 34 de 94 titulares del snapshot cambian de tema. **Cambia un evento grande por
  otro**; con 29 eventos eso no distingue una mejora real de un reacomodo. La variante «solo descripción» no pierde recall en
  ninguna clase pero gana 2 filas (IC por evento [0.000, 0.075]): indistinguible de cero.

### 5 · Qué hace falta para decidir (y no se pudo hacer aquí)

1. **Más etiquetas humanas, de más de una persona:** los 15 titulares útiles de v1.2 sin etiquetar y, sobre todo, nuevos eventos
   con tema Economía (regional y panameño) y con `sin_tema`. Con ≥ 30 positivos de `sin_tema` (hoy 5) el umbral sería
   calibrable. Sin datos independientes, cualquier cambio de referencias queda sin validar.
2. **Decisión de producto sobre la abstención:** abstenerse saca titulares útiles de la bandeja (entre 9 y 26 de 94 en las
   opciones medidas) a cambio de pocas abstenciones correctas; el umbral actual abstiene 12 titulares (1 grupo) y en las etiquetas
   los 12 son Economía. Dejarlo, quitarlo o sustituirlo son decisiones del equipo, no de la calibración.
3. **Alcance regional en Economía** (D-84): decidir si la descripción de Economía debe mencionarlo (cambio mínimo de redacción,
   efecto medido +2 filas sin significancia) y si el evento de El Niño es Eventos naturales (criterio actual) o Economía.
4. **Filtro de ruido:** 5 filas «útiles» que la persona marcó `sin_tema` indican reglas faltantes (política electoral sin norma,
   notas sobre otro país); es un cambio de `config/ruido.yaml` que necesita más ejemplos para no sobreajustar.

## Pendiente

1. **Más etiquetas y más personas:** las 100 etiquetas actuales son de una sola persona y repiten titulares. Reetiquetar con
   un segundo etiquetador (kappa) y ampliar la muestra antes de decidir D-20 y recalibrar umbrales. **E1-07b mostró que sin
   al menos ~30 titulares `sin_tema` el umbral de abstención no es calibrable** (hoy hay 5) y que el n efectivo son 29 eventos.
2. Con esas métricas: decidir modelo (D-20, de «propuesta» a «aceptada») y método (D-21), recalibrar los umbrales (incluido el
   de fuga semántica) y decidir si se activa el filtro por similitud. **La elección se registra en Notion con los números** (no
   hay números reales todavía, así que no se registró nada).
3. `docs/ia_vs_baseline.md` (D-66) lo completan E1-11 y E1-18 con las demás tareas.
