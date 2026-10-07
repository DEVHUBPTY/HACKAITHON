# La IA contra su línea base (E1-18 · D-66)

Cada número de este documento sale de `outputs/ia_vs_baseline.json`, que escribe `poetry run python -m eval.ia_vs_baseline` (sin red y sin LLM; modelos de embeddings locales). Nada se tecleó a mano, salvo las similitudes de las consultas de la demo de la sección 5, que salen de correr `src.consulta` (el comando está ahí). Toda proporción lleva su n y su intervalo de confianza del 95 % (bootstrap percentil, 2.000 remuestreos, semilla 42; en agrupación se remuestrean **titulares**, no pares, porque los pares comparten titulares).

**Regla de veredicto (D-21, D-57, fijada antes de medir):** una diferencia está «demostrada» solo si el IC 95 % de la diferencia pareada (IA − base) **excluye el cero**. Si lo incluye, el veredicto es «sin diferencia demostrable»; no es «empate», es que los datos no alcanzan.

**Qué no es esto:** los datos son decenas de registros etiquetados por el propio equipo. Los intervalos son anchos y ninguna cifra es una medida independiente.

## Resumen

| Tarea | IA | Línea base | Diferencia (IA − base), IC 95 % | Veredicto |
|---|---|---|---|---|
| Clasificación de tema (macro-F1, n = 63 titulares) | 0.401 (IC 0.244–0.516) | 0.515 (IC 0.281–0.608) | −0.114 (−0.286 a 0.113) | **Sin diferencia demostrable** (la base tiene el punto estimado más alto) |
| Agrupación (F1 de pares, validación cruzada, 100 titulares) | 0.916 (IC 0.779–0.995) | 0.793 (IC 0.614–0.930) | +0.123 (−0.039 a 0.308) | **Sin diferencia demostrable** en F1; la IA **gana en recall** |
| Búsqueda (Recall@5 por IDs, 20 consultas, 50 IDs esperados) | 0.640 (32/50; IC 0.426–1.000) | 0.480 (24/50; IC 0.321–0.800) | +0.160 (0.038 a 0.429) | **Gana la IA** |
| Ranking (Precision@5) | — | — | — | **No medible todavía** (falta la selección de un editor, E1-19) |

## 1 · Clasificación de tema

- **IA:** embeddings multilingües (`intfloat/multilingual-e5-small`, método A de `config/clasificacion.yaml`). **Base:** palabras clave de `src/baseline.py` (variante `guia`). Mismos 63 titulares con etiqueta humana (`eval/etiquetas.csv`), comparación pareada.
- Exactitud: IA 33/63 = 0.524 (IC 0.403–0.642); base 29/63 = 0.460 (IC 0.343–0.582). Con macro-F1, la base queda arriba, pero el IC de la diferencia incluye el cero.
- Discordantes (los mismos titulares): solo la IA acierta 10, solo la base acierta 6, ambos aciertan 23, ambos fallan 24. McNemar exacto p = 0.455.
- **Por tema** (F1 IA / F1 base; n = titulares humanos del tema): `eventos_naturales` 0.930 / 0.976 (n = 20), `economia` 0.303 / 0.143 (n = 26), `servicios_publicos` 0.571 / 0.333 (n = 9), `sin_tema` 0.000 / 0.154 (n = 5). `logistica`, `turismo` y `regulacion` tienen n = 1: **soporte insuficiente**, sin veredicto. Ningún tema con soporte tiene una diferencia cuyo IC excluya el cero.

**Dónde gana la IA (punto estimado):** entiende titulares sin la palabra clave. La base los deja en `sin_tema`; la IA los ubica:

| ID | Titular | Humano | Base | IA |
|---|---|---|---|---|
| `NOT-4e1754a3f9` | Tres hombres asaltan casino y despojan a clientes… en San Miguelito | servicios_publicos | sin_tema | servicios_publicos |
| `NOT-549c8211e8` | Veraguas: Preocupación por aumento de muertes por enfermedades transmisibles y respiratorias | servicios_publicos | sin_tema | servicios_publicos |
| `NOT-613e8bdf24` | Aeropuerto panameño suscribe convenio con empresa asiática | regulacion | sin_tema | regulacion |
| `NOT-96d1ecac7d` | ¿Cómo se fija el precio del combustible en Panamá? El MEF explica la fórmula… | economia | sin_tema | economia |
| `NOT-a71293e7e8` | The Duality of Latin America FDI | economia | sin_tema | economia |

**Dónde no gana (y pierde en el punto estimado):** la IA asigna un tema a titulares que las personas dejaron en `sin_tema` (precisión y recall 0 en esa clase: 12 predichos, 5 reales) y confunde con `servicios_publicos` titulares cuyo tema de fondo es otro:

| ID | Titular | Humano | Base | IA |
|---|---|---|---|---|
| `NOT-14dcb8e259` | Contenido Exclusivo: Turismo en transporte público | turismo | turismo | servicios_publicos |
| `NOT-38702b3c42` | Profesor Angel Dust, el rey de la noche de Barcelona que acabó en una prisión de Panamá… | sin_tema | sin_tema | servicios_publicos |
| `NOT-aacff154c6` | La Chorrera proyecta renovar el parque Tomás Martín Feuillet con una inversión de 620 mil dólares | economia | economia | servicios_publicos |
| `NOT-d6cc7acc03` | Semana de la RSE busca impulsar la sostenibilidad en las empresas | sin_tema | sin_tema | turismo |
| `NOT-e4f8660e0d` | Negocios de Gilinski y de Ecopetrol son claves para Colombia en América Latina | sin_tema | sin_tema | regulacion |

**Lectura honesta:** con estas etiquetas no se puede decir que la IA clasifique mejor que las palabras clave. Se puede decir que son errores distintos (10 titulares que solo la IA acierta frente a 6 que solo acierta la base), y que ninguno de los dos supera a las personas. El diagnóstico detallado está en `docs/clasificacion.md`.

## 2 · Agrupación de titulares (eventos)

- **IA:** embeddings `paraphrase-multilingual-MiniLM-L12-v2` con umbral coseno calibrado. **Base:** unir solo titulares idénticos (tras normalizar). Etiquetas: 100 titulares agrupados por personas en `eval/etiquetas.csv`.
- La cifra honesta de la IA es la de **validación cruzada agrupada** (el umbral de cada pliegue no vio los pares de prueba: 0.535 y 0.725). La del umbral elegido con todas las etiquetas (0.69) es optimista porque las mismas etiquetas calibran y evalúan; se muestra aparte en el JSON.
- Pares en alcance: 2.466 (131 positivos).

| Métrica | IA (CV) | Base | IA − base, IC 95 % | Veredicto |
|---|---|---|---|---|
| Precisión | 0.880 (125/142; IC 0.68–1.00) | 1.000 (86/86) | −0.120 (−0.32 a 0.00) | Sin diferencia demostrable |
| Recall | 0.954 (125/131; IC 0.830–1.000) | 0.657 (86/131; IC 0.443–0.868) | +0.298 (0.091 a 0.504) | **Gana la IA** |
| F1 | 0.916 | 0.793 | +0.123 (−0.039 a 0.308) | Sin diferencia demostrable |

**Dónde gana la IA:** une titulares de un mismo evento aunque no sean idénticos (39 pares que la IA une y la base no; la base nunca une un par que la IA no una):

| Par | Titulares | Grupo humano |
|---|---|---|
| `NOT-0969f86532` · `NOT-2ece201ac9` | «World Insights: Intensifying El Nino deepens economic risks across LatAm» · «Intensifying El Nino deepens economic risks across LatAm» | el-nino-latam |
| `NOT-1819a7014e` · `NOT-fbc3efaa5d` | «Presidente panameño visitará Singapur y Vietnam» · «Presidente de Panamá visita Singapur y Vietnam en busca de inversiones» | mulino-gira-asia |
| `NOT-213eb698b8` · `NOT-26fd75f865` | Titular en ucraniano · «Trump streicht Europa - Hilfe, lenkt Millionen nach Lateinamerika» | trump-ayuda-europa-latam |
| `NOT-364916b1e1` · `NOT-7170117798` | «Intensifying El Nino…» · «World Insights: Intensifying El Nino…» | el-nino-latam |
| `NOT-5d839301a6` · `NOT-fb0597e7e5` | «Trump streicht Europa…» · titular en checo sobre la misma ayuda | trump-ayuda-europa-latam |

Entre idiomas, la base no puede hacerlo.

**Dónde no gana:** la IA introduce falsos positivos (17 en la validación cruzada; la base tiene 0) y se le escapan pares con poca superposición léxica:

| Tipo | Par | Titulares |
|---|---|---|
| Falso positivo (CV) | `NOT-05ae3da7e3` · `NOT-213eb698b8` | «El BID moviliza proyectos por US$84.000 millones…» · titular en ucraniano sobre ayuda de EE. UU. (grupos humanos distintos) |
| Falso positivo (CV) | `NOT-26fd75f865` · `NOT-a71293e7e8` | «Trump streicht Europa…» · «The Duality of Latin America FDI» |
| Falso negativo (umbral elegido) | `NOT-1ba5a41e46` · `NOT-c712a8d7e4` | «Trump streicht Europa…» · titular en ruso sobre los mismos USD 52 M |
| Falso negativo (umbral elegido) | `NOT-8206bf1857` · `NOT-f1f1f6e600` | «El abrir para cerrar de la mina de cobre…» · «Cobre Panamá volvería a producir…» (mina-cobre-panama: 0 de 1 par recuperado) |

**Lectura honesta:** el beneficio es de recall, no de precisión. La mayor parte del recall sale de dos grupos grandes (`el-nino-latam`, 20 titulares, 190 de 190 pares; `trump-ayuda-europa-latam`, 13 titulares, 66 de 78 pares); en grupos pequeños el efecto no se puede medir (`mina-cobre-panama`: 0 de 1).

## 3 · Búsqueda (consultas del benchmark de desarrollo)

- **IA:** búsqueda semántica (`e5`). **Base:** BM25 sobre el mismo corpus e índice. Recall@5 por IDs esperados, 20 consultas con evidencia en el corpus. Bootstrap pareado sobre **consultas**.
- Sistema (semántica): 32/50 IDs (0.640); consultas completas 17/20 = 0.850 (IC 0.65–1.00). BM25: 24/50 IDs (0.480); consultas completas 12/20 = 0.600 (IC 0.399–0.800).
- Diferencia +0.160, IC 95 % 0.038 a 0.429: **la IA gana, y es la única diferencia de este documento que el criterio da por demostrada**.
- **Aviso:** las reglas por patrón de la consulta se escribieron viendo estas 20 consultas. El Recall@5 es optimista; el IC es el de un conjunto pequeño.

**Dónde gana la IA:** consultas sobre datos oficiales. BM25 no encuentra el indicador porque el texto del registro («Inflación (precios al consumidor)») no comparte palabras con la pregunta («inflación anual»):

| ID | Consulta | IA halla | BM25 halla |
|---|---|---|---|
| `BDEV-010` | ¿Cuál fue la inflación anual de Panamá en 2024 según el Banco Mundial? | `IND-PAN-FP.CPI.TOTL.ZG-2024` | nada |
| `BDEV-011` | ¿Cómo cambió la tasa de desempleo de Panamá entre 2023 y 2024? | `IND-PAN-SL.UEM.TOTL.ZS-2023`, `-2024` | nada |
| `BDEV-012` | ¿Cuánto creció el PIB de Panamá en 2023 y 2024? | `IND-PAN-NY.GDP.MKTP.KD.ZG-2023`, `-2024` | nada |
| `BDEV-013` | ¿Cuál era la población de Panamá en 2024 según el Banco Mundial? | `IND-PAN-SP.POP.TOTL-2024` | nada |
| `BDEV-014` | ¿Qué porcentaje de la población panameña usaba internet…? | `IND-PAN-IT.NET.USER.ZS-2023`, `-2024` | nada |

Por tipo de fuente: solo oficiales (7 consultas) IA 10/12 vs BM25 2/12, diferencia +0.667 (IC 0.273–1.000, gana la IA); solo titulares (13 consultas) IA 22/38 = BM25 22/38, diferencia 0.000: **en noticias no hay ventaja demostrable**.

**Dónde la IA no gana (empate o fallo compartido):** 12 consultas empatan completas (por ejemplo `BDEV-001`, `BDEV-002`, `BDEV-003`, `BDEV-005`, `BDEV-006`: ambos encuentran todos los IDs) y 3 quedan incompletas para ambos métodos:

| ID | Qué pasa |
|---|---|
| `BDEV-004` | Ambos pierden `NOT-ba54c3921d`: una columna de opinión cuyo titular no nombra la mina. Es un límite del indexado por titular, no del modelo. |
| `BDEV-009` | «¿Cuántos medios replicaron…?»: hay 20 titulares casi idénticos y solo caben 5 en el top-5. Fallo estructural de k = 5 para una pregunta de conteo. |
| `BDEV-015` | Sismos de la caja de USGS: ninguno de los dos devuelve los dos `SIS-` esperados. |

## 4 · Ranking de la bandeja

El ranking (puntaje P con R, I, U, N, E) es **código determinista de reglas v1.3, no un modelo**; no hay «IA» que comparar. La pregunta útil es si la bandeja prioriza lo que prioriza un editor, que es Precision@5 contra una selección independiente. **Esa selección todavía no existe** (`eval/seleccion_editor.csv`, E1-19, requiere a una persona), así que **no se reporta ninguna utilidad** y no se inventó ninguna.

Lo que sí se puede decir, descriptivo (58 grupos): el top 5 de la bandeja y el top 5 de «más reciente primero» (la línea base del PDF, sección 8) **no comparten ningún grupo** (0/5). Ejemplos de grupos que solo el sistema sube (posición del sistema frente a la de la fecha): `GRP-84a6b3a04b` (colegios particulares y matrícula; 1.º frente a 18.º), `GRP-ef3acec21e` (vacunación contra el VSR; 2.º frente a 34.º), `GRP-65d565abd0` (MiBus y filtraciones; 3.º frente a 29.º), `GRP-8af4196527` (traslado a Coiba; 4.º frente a 35.º).

**Advertencia:** los cinco grupos del top tienen estado de evidencia `insuficiente` y un solo titular de un solo medio. Que el ranking difiera del orden por fecha no dice que sea mejor.

## 5 · Análisis de abstención: ¿abstención correcta o fallo de recall?

El umbral de similitud de la consulta es **0.874** (`config/consulta.yaml`; percentil 5 de las consultas respondibles de la mitad de calibración, E1-11). Reproducible con `poetry run python -m src.consulta "<pregunta>"` y con el análisis del umbral de `outputs/metricas.json` (`analisis_umbral`).

**Caso de las consultas de la demo** (`docs/demo.md`, «Riesgos»): «¿Qué se reporta sobre la vacunación contra el VSR?» y «¿Qué pasó con MiBus?» se abstienen. Medido ahora, con el índice del snapshot:

| Consulta | Resultado 1 (correcto) | Similitud | Segundo resultado | Estado |
|---|---|---|---|---|
| ¿Qué se reporta sobre la vacunación contra el VSR? | `NOT-3175aafec0` «Minsa: Adelantan vacunación contra VSR en embarazadas» | 0.850 | 0.818 (`NOT-549c8211e8`) | **abstención** (`similitud_baja`) |
| ¿Qué pasó con MiBus? | `NOT-ff1b1ed15c` «MiBus responde por filtraciones…» | 0.851 | 0.797 (`NOT-33032542b7`) | **abstención** (`similitud_baja`) |
| ¿Qué anunció el Minsa sobre la vacunación contra el VSR en embarazadas? (`BDEV-020`) | `NOT-3175aafec0` | 0.891 | 0.833 | responde |
| ¿Qué dice la prensa sobre las filtraciones de MiBus? | `NOT-ff1b1ed15c` | 0.891 | 0.836 | responde |

**Veredicto: es un fallo de recall, no una abstención correcta.** En ambos casos el documento que mejor puntúa es exactamente el titular que responde la pregunta, y existe en el corpus. El sistema se abstuvo con la respuesta correcta en el primer lugar y con un margen de 0.03 a 0.05 sobre el segundo. Lo que baja la similitud es la forma de la pregunta: una consulta corta y genérica («¿Qué pasó con MiBus?») se parece menos a un titular largo que una consulta que repite sus palabras. La misma evidencia pasa de 0.851 a 0.891 solo con reformular.

**No es un caso aislado en el benchmark de desarrollo.** `BDEV-004` (similitud 0.870) y `BDEV-017` (0.866) son respondibles, el documento correcto está en el top-5 y también se rechazan por `similitud_baja`: **2 de 20 sustentadas = 10 % (IC 0.0–25 %, Wilson 2.8–30.1 %)**, o 2 de 30 respondibles = 6.7 %. En total, 4 casos de abstención incorrecta con el documento correcto en primer lugar y similitud entre 0.850 y 0.870, todos por debajo del umbral por poco.

**Por qué no se movió el umbral.** La tabla de sensibilidad (`analisis_umbral`) muestra que con 0.85 las respondibles rechazadas bajarían de 2 a 0 y las 7 «sin respuesta» se seguirían rechazando. Eso **no es evidencia suficiente para bajarlo**: de las 7 consultas sin respuesta, solo 1 (`BDEV-028`, similitud máxima 0.810) llega a la puerta de similitud; las otras 6 las frena una regla o la cobertura de datos antes. Es decir, el umbral se defiende contra **una** consulta negativa. Bajarlo a 0.85 se vería mejor en este conjunto y no se sabe si es mejor en general, y además las reglas por patrón se escribieron viendo estas consultas.

| Umbral | Sin respuesta rechazadas | Respondibles rechazadas (de 20) | IDs |
|---|---|---|---|
| 0.85 | 7/7 | 0 | — |
| 0.86 | 7/7 | 0 | — |
| 0.87 | 7/7 | 1 | `BDEV-017` |
| **0.874 (actual)** | 7/7 | 2 | `BDEV-004`, `BDEV-017` |
| 0.88 | 7/7 | 3 | `BDEV-004`, `BDEV-015`, `BDEV-017` |
| 0.90 | 7/7 | 9 | 9 consultas |

**Conclusión y qué falta:** el umbral prioriza no responder mal (abstención correcta 7/7 = 100 %, Wilson 64.6–100 %, n pequeño) a costa de rechazar algo de lo respondible. Para el pitch: «el sistema prefiere abstenerse a responder mal»; ante una consulta libre y corta sobre un tema de la bandeja, reformular con las palabras del titular lo resuelve. Para mejorarlo de verdad hacen falta **al menos unas 30 consultas negativas que lleguen a la puerta de similitud** (hoy hay 1) y datos de evaluación que nadie haya mirado al redactar las reglas. Hasta entonces se mantiene 0.874 y se reporta el costo.

## 6 · Lo que este análisis no demuestra

- No hay veredicto para clasificación ni para el F1 de agrupación: los IC incluyen el cero.
- La ventaja de la búsqueda es en datos oficiales; en titulares no hay diferencia (22/38 = 22/38).
- El ranking no tiene métrica de utilidad hasta que exista la selección de un editor (E1-19).
- Los temas con n < 5 (`logistica`, `turismo`, `regulacion`) no permiten veredicto por tema.
