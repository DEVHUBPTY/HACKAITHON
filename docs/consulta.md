# Consulta en español con abstención (E1-11)

`poetry run python -m src.consulta "pregunta" [--metodo semantica|bm25] [--json]`. Parámetros: `config/consulta.yaml`
(origen de cada valor en `docs/parametros.md`).

## Cómo decide

Todo lo siguiente ocurre **antes** de cualquier LLM (esta tarea no llama a ninguno; el único modelo es el de embeddings, local):

1. **Saneo:** un fragmento `<evidencia>…</evidencia>` en la consulta es dato pegado: se descarta, se marca la entrada como sospechosa y nunca se obedece.
2. **Reglas por patrón:** instrucciones dirigidas al sistema (patrones de inyección de `restricciones.yaml`), pedir el cuerpo del artículo (D-51), autoría o perfiles de personas (D-32, D-68) y cifras de un periodo relativo reciente (esta semana, esta quincena).
3. **Cifra oficial exacta:** si pide un indicador del Banco Mundial, se resuelven país, indicador y año. Si falta alguno, se abstiene y **ofrece el último dato disponible** con su cita. Un nulo es nulo: no se rellena. Sismos de un año fuera de la cobertura de USGS también se rechazan.
4. **Similitud máxima** (semántica o BM25) bajo el umbral de su método.

La respuesta con contenido es **extractiva y determinista**: cada oración es una `Afirmacion` con cita ID + campo. Un titular es una *declaración* atribuida al medio (`<medio> titula: «…»`); solo los datos oficiales son *hechos*. Toda salida lleva la leyenda de alcance de D-51 y es un BORRADOR. El validador completo es de E1-13; aquí `responder(..., validador=...)` recibe uno cualquiera y, si devuelve problemas, la respuesta no se emite. El validador por defecto (`validar_citas`) solo comprueba que la cita exista, que el campo sea citable, que el tipo sea coherente y que el titular sea literal.

## Resultados en el benchmark de desarrollo

`poetry run python -m eval.recuperacion` → `outputs/recuperacion.json`. 40 consultas aprobadas por una persona; mitades de 20 por paridad del id (pares calibran el umbral, impares evalúan). IC de Wilson al 95 %.

**Recall@5** (20 `respuesta_sustentada`, 50 IDs esperados; búsqueda sobre todo el corpus):

| Método | IDs hallados | IC95 | Acotado a min(5, esperados) |
|---|---|---|---|
| BM25 (baseline, D-66) | 24/50 = 0.48 | [0.35, 0.61] | 24/35 = 0.69 |
| Semántica (e5) | 32/50 = 0.64 | [0.50, 0.76] | 32/35 = 0.91 |
| Sistema (semántica + cifra oficial exacta) | 32/50 = 0.64 | [0.50, 0.76] | 32/35 = 0.91 |

En titulares los dos empatan (22/38); la diferencia está en los datos oficiales (semántica 10/12, BM25 2/12). Sin cumplir: BDEV-009 (19 IDs esperados: ningún top-5 los cubre), BDEV-004 (un titular de opinión que no nombra la mina) y BDEV-015 (sismos «de mayor magnitud»: la búsqueda no ordena por magnitud).

**Abstención** (semántica; BM25 también rechaza 7/7 `sin_respuesta`, pero rechaza 3/30 respondibles: BDEV-015, 019 y 021):

| Medida | Calibración (n=20) | Evaluación (n=20) | Total (n=40) |
|---|---|---|---|
| `sin_respuesta` rechazadas (meta ≥ 80 %) | 4/4 | 3/3 | **7/7 = 1.00, IC95 [0.65, 1.00]** |
| Todas las que debían rechazarse | 5/5 | 5/5 | 10/10, IC95 [0.72, 1.00] |
| Abstenciones incorrectas (respondibles rechazadas) | 1/15 | 1/15 | 2/30 = 0.07, IC95 [0.02, 0.21] |

## Límites (leer antes de citar estos números)

- **n es muy pequeño.** El límite inferior del IC de la abstención correcta (0.65) está bajo la meta de 80 %: no se puede afirmar que se cumple.
- **Las reglas por patrón se escribieron viendo las 40 consultas** (también los umbrales se calibraron en la mitad par). La columna «Total» es optimista y no independiente; la mitad de evaluación solo es independiente para el umbral, no para las reglas.
- **Qué hace cada pieza:** el umbral de similitud **solo** rechaza 6/7 `sin_respuesta` (todas menos BDEV-032), pero con márgenes mínimos (BDEV-029: 0.873 contra 0.874) y a costa de rechazar respondibles (BDEV-004 y BDEV-017). Las reglas cubren lo que la similitud no puede ver (el cuerpo del artículo, la autoría, las instrucciones inyectadas).
- **No cubierto:** una consulta sobre un tema que el corpus sí trata, pero cuyo dato concreto no está en los titulares, solo se rechaza si cae bajo el umbral (BDEV-028 «causa de la muerte»: se rechazó por similitud baja, 0.81, sin garantía de que generalice).
- Las consultas adversariales respondibles (BDEV-036, 037) se contestan solo con lo que dicen los titulares, atribuido al medio y con la advertencia de que no se leyó el artículo; no se emite ninguna nota ni confirmación.
- Los 40 de desarrollo también se usan para calibrar; no hay otro conjunto. El conjunto reservado es del jurado y nunca se lee.

## Sesgo hacia abstenerse en consultas genéricas (X16)

**Histórico (antes de D-134):** el umbral de similitud (0.874, semántica) era el **mínimo** de las 9 consultas respondibles de calibración (percentil 5, truncado), y esas consultas son largas y específicas («¿Qué medios reportaron la sanción del presupuesto del Canal…?»). Una consulta corta y genérica del estilo «¿Qué se dice de X?» puntúa más bajo aunque el corpus tenga titulares sobre X, así que **el sistema se abstiene de más** en ellas (medido con el modelo real, semántica):

| Consulta | Similitud máxima | Resultado |
|---|---|---|
| ¿Qué se dice del Canal de Panamá? | 0.855 | abstención (`similitud_baja`) |
| ¿Qué se dice de Cobre Panamá? | 0.866 | abstención |
| ¿Qué se dice del turismo en Panamá? | 0.850 | abstención |
| ¿Qué se dice de Mulino? | 0.839 | abstención |
| ¿Qué medios reportaron la sanción del presupuesto del Canal de Panamá? | 0.896 | responde |

Es un error del lado seguro (no inventa), pero degrada la utilidad de las consultas abiertas. No se corrigió: bajar el umbral sin ejemplos genéricos de calibración sería ajustar a ciegas. Queda como mejora: agregar consultas genéricas respondibles al benchmark de calibración o calibrar por longitud de consulta.

## Cifras oficiales: calificadores e indicadores en nivel (X16)

- Un **calificador** que el indicador no desagrega (edad, sexo, población indígena, provincias o regiones, sector; lista en `datos_oficiales.calificadores`) hace abstenerse, y la cifra nacional se ofrece **solo** como `ultimo_dato_disponible`. Tampoco se asume Panamá si la consulta nombra otro país o región.
- `NY.GDP.MKTP.KD.ZG` es el **crecimiento** anual del PIB: el término suelto «PIB» ya no lo pide. «PIB de Panamá en 2010» se abstiene y ofrece el crecimiento como dato relacionado.
- Los valores se muestran con `respuesta.decimales_valor` decimales; la cita conserva el valor crudo. Las afirmaciones sobre titulares citan también `medio` y `fecha_publicacion` y entrecomillan el titular original literal (`titulo_original`).
- La regla de autoría exige una referencia a la autoría de la nota (o a una persona junto a «otros casos»): «¿Se reportaron otros casos de dengue en Chiriquí?» y «¿Qué dijo el periodista de TVN sobre el Canal?» ya no se rechazan.

## D-134 · Recalibración del umbral de similitud

**Problema.** Con 0.874, la búsqueda semántica se abstenía en temas que el corpus sí trata: «¿Qué se dice sobre la mina de cobre?» (similitud máxima 0.856, el titular de prensa.com está primero) y «¿Qué se reporta sobre el Canal de Panamá?» (0.856), además de BDEV-004 (0.870) y BDEV-017 (0.866). El PDF 9.1 pide abstención correcta en al menos el 80 % de las consultas sin respuesta **y** que se registren las abstenciones incorrectas en las respondibles.

**Qué mide cada cosa.** Solo 1 de las 7 consultas `sin_respuesta` del benchmark de desarrollo llega a la puerta de similitud (BDEV-028, 0.8097); las otras 6 las frenan una regla por patrón o la cobertura de datos antes. Por eso la abstención correcta no depende del umbral (7/7 con 0.874 y con 0.840) y lo que el umbral decide es cuántas respondibles se pierden. «Solo el umbral rechaza» pasa de 6/7 a 1/7: no es un retroceso, es que el 0.874 rechazaba por casualidad consultas que otra pieza ya rechazaba.

**Regla (`abstencion.regla_umbral: margen_maximo`).** Entre todos los umbrales que rechazan al menos `meta_abstencion` (0.8) de las negativas que llegan a la puerta, se queda con los que dejan pasar más respondibles; a igualdad, con el intervalo más ancho, y toma su punto medio truncado a 3 decimales (`eval/recuperacion.py: umbral_margen_maximo`). Con la mitad de calibración: negativa más alta 0.8097, respondible más baja 0.8703, umbral **0.840**. BM25 conserva el percentil 5 (sus puntajes se solapan); su umbral pasa de 10.765 a 10.844 porque el corpus creció.

**Validación.** Dejando una consulta fuera (26 que llegan a la puerta): respondibles respondidas 20/20 (IC95 [0.84, 1.00]); la única negativa no es estimable. Comprobación aparte, no calibración: seis consultas fuera del corpus escritas por el asistente (fútbol, sancocho, clima en Tokio, bitcoin, hospital de Bocas del Toro, dengue en Chiriquí) dan similitud máxima 0.772–0.826 y se rechazan.

**Antes → después (semántica, n e IC95 de Wilson).** Abstención correcta `sin_respuesta`: 7/7 → 7/7 (IC95 [0.65, 1.00]). Abstenciones incorrectas en `respuesta_sustentada`: 2/20 → 0/20 (IC95 [0.00, 0.16]); en todas las respondibles: 2/30 → 0/30 (IC95 [0.00, 0.11]). Recall@5 sin cambio (la recuperación no depende del umbral): 32/50 = 0.64.

**Límites (leer antes de citar).** El margen es estrecho: 0.014 sobre la consulta fuera del corpus más parecida (0.826) y 0.016 bajo «mina de cobre» (0.856). Solo hay 1 negativa del benchmark en la puerta; el IC de la abstención correcta sigue bajo la meta (0.65). Para fijar el umbral con respaldo hacen falta unas 30 consultas negativas que lleguen a la puerta, escritas por una persona y sin haber mirado el corpus.

## C-12 · Preguntas fuera del corpus escritas por una persona

**Qué se hizo.** Una persona del equipo (David Feng) escribió 40 preguntas sin probarlas en el sistema: 30 sobre temas que no están en el corpus y 10 sobre temas que sí están (`benchmark/c12_preguntas.csv` y `benchmark/c12_preguntas.jsonl`, aparte del benchmark de desarrollo). Se midieron con `poetry run python -m eval.recuperacion --benchmark benchmark/c12_preguntas.jsonl --salida outputs/recuperacion_c12.json`.

**Resultado con el umbral vigente (0.840, semántica).** Abstención correcta: **24/30 = 80 %** (IC95 [0.627, 0.905]): cumple la meta de 80 % por la estimación puntual, con el límite inferior por debajo. Abstenciones incorrectas en las 10 respondibles: **0/10** (IC95 [0.000, 0.278]). Cinco de las seis preguntas que respondió cuando debía abstenerse están en el margen (similitud 0.842 a 0.845: matrícula de la UTP, alquiler, encuesta de 2029, canasta básica, precios de alimentos en Colón); la sexta tiene 0.863 (coliformes en playas). Las respuestas citan registros reales del corpus, pero no contestan lo que se preguntó. Las 10 respondibles empiezan en 0.874. BM25 (umbral 10.844): 26/30 = 86.7 %.

**Recalibración probada y no adoptada.** Calibrar con `margen_maximo` sobre el benchmark de desarrollo más estas 40 preguntas (n = 80) sugiere **0.857** (intervalo [0.845, 0.870]; dejando una fuera: respondibles 28/28, negativas rechazadas 29/30). Con 0.857 la abstención correcta de C-12 sube a 29/30 (96.7 %), pero el sistema vuelve a abstenerse en preguntas legítimas sobre temas del corpus: «¿Qué se dice sobre la mina de cobre?» (0.856), «¿Qué se reporta sobre el Canal de Panamá?» (0.856), «¿Qué pasó con MiBus?» (0.851) y «¿qué se reporta sobre la vacunación contra el VSR?» (0.850). El equipo decidió **mantener 0.840**.

**La tensión del diseño.** La similitud de embeddings no separa bien una pregunta sobre un tema ausente que comparte vocabulario con el corpus (precios, Panamá, elecciones) de una pregunta legítima formulada en lenguaje general: ambas caen entre 0.84 y 0.86. Subir el umbral cambia respuestas que no contestan lo pedido por abstenciones en temas que sí están. El umbral 0.840 prefiere responder con citas reales; la validación de citas impide inventar datos, pero no garantiza que la respuesta sea pertinente.
