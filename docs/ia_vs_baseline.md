# La IA contra su línea base (E1-18 · D-66)

Cada número de este documento sale de `outputs/ia_vs_baseline.json`, que escribe `poetry run python -m eval.ia_vs_baseline` (sin red y sin LLM; modelos de embeddings locales). Nada se tecleó a mano, salvo las similitudes de las consultas de la demo de la sección 5, que salen de correr `src.consulta` (el comando está ahí). Toda proporción lleva su n y su intervalo de confianza del 95 % (bootstrap percentil, 2.000 remuestreos, semilla 42; en agrupación se remuestrean **titulares**, no pares, porque los pares comparten titulares).

**Regla de veredicto (D-21, D-57, fijada antes de medir):** una diferencia está «demostrada» solo si el IC 95 % de la diferencia pareada (IA − base) **excluye el cero**. Si lo incluye, el veredicto es «sin diferencia demostrable»; no es «empate», es que los datos no alcanzan.

**Qué no es esto:** los datos son decenas de registros etiquetados por el propio equipo. Los intervalos son anchos y ninguna cifra es una medida independiente.

## Resumen

| Tarea | IA | Línea base | Diferencia (IA − base), IC 95 % | Veredicto |
|---|---|---|---|---|
| Clasificación de tema (macro-F1, n = 100 titulares) | 0.629 (IC 0.427–0.774) | 0.601 (IC 0.399–0.749) | +0.028 (−0.244 a 0.310) | **Sin diferencia demostrable** (la IA tiene el punto estimado más alto) |
| Agrupación (F1 de pares, validación cruzada, 100 titulares) | 0.989 (IC 0.928–1.000) | 0.823 (IC 0.617–0.974) | +0.166 (0.005 a 0.358) | **Gana la IA** en F1 y en recall; en precisión, sin diferencia demostrable |
| Búsqueda (Recall@5 por IDs, 20 consultas, 50 IDs esperados) | 0.640 (32/50; IC 0.426–1.000) | 0.480 (24/50; IC 0.321–0.800) | +0.160 (0.038 a 0.429) | **Gana la IA** |
| Ranking (Precision@5, 5 temas, 1 corte, exploratoria) | 0/5 = 0.000 (IC 0.000–0.434) | 1/5 = 0.200 (IC 0.036–0.625) | — (los IC se solapan) | **Sin diferencia demostrable** (la base tiene el punto estimado más alto; `outputs/precision_at_5.json`) |

## 1 · Clasificación de tema

- **IA:** embeddings multilingües (`intfloat/multilingual-e5-small`, método A de `config/clasificacion.yaml`). **Base:** palabras clave de `src/baseline.py` (variante `guia`). Dos vistas sobre las mismas etiquetas humanas (`eval/etiquetas.csv`), comparación pareada: la del **pipeline** (macro-F1 de la tabla, n = 100 titulares) y la del **clasificador** sobre los 46 titulares con tema humano (exactitud, discordantes y detalle por tema).
- Macro-F1 (n = 100): IA 0.629, base 0.601; la IA queda apenas arriba, pero el IC de la diferencia (−0.244 a 0.310) incluye el cero. En la vista del clasificador (n = 46) es 0.492 contra 0.504, diferencia −0.013 (−0.247 a 0.272), también sin diferencia demostrable.
- Exactitud (n = 46): IA 33/46 = 0.717 (IC 0.575–0.827); base 28/46 = 0.609 (IC 0.465–0.736).
- Discordantes (n = 46, los mismos titulares): solo la IA acierta 10, solo la base acierta 5, ambos aciertan 23, ambos fallan 8. McNemar exacto p = 0.302. En los 100 titulares: 10, 5, 77 y 8.
- **Por tema** (F1 IA / F1 base; n = titulares humanos del tema): `eventos_naturales` 0.976 / 0.976 (n = 20), `economia` 0.333 / 0.364 (n = 9), `servicios_publicos` 0.667 / 0.333 (n = 9), `sin_tema` 0.000 / 0.190 (n = 4). `logistica` (n = 2), `turismo` (n = 1), `regulacion` (n = 1) y `sin_tema` (n = 4) tienen **soporte insuficiente**, sin veredicto. Ningún tema con soporte tiene una diferencia cuyo IC excluya el cero.

**Dónde gana la IA (punto estimado):** entiende titulares sin la palabra clave. La base los deja en `sin_tema`; la IA los ubica:

| ID | Titular | Humano | Base | IA |
|---|---|---|---|---|
| `NOT-0d91fa48b0` | Más de 30 mujeres han muerto de forma violenta en Panamá este año | servicios_publicos | sin_tema | servicios_publicos |
| `NOT-4e1754a3f9` | Tres hombres asaltan casino y despojan a clientes… en San Miguelito | servicios_publicos | sin_tema | servicios_publicos |
| `NOT-549c8211e8` | Veraguas: Preocupación por aumento de muertes por enfermedades transmisibles y respiratorias | servicios_publicos | sin_tema | servicios_publicos |
| `NOT-613e8bdf24` | Aeropuerto panameño suscribe convenio con empresa asiática | regulacion | sin_tema | regulacion |
| `NOT-66fdc7fa16` | Disparan contra el vehículo del exdiputado Pedro Torres en Colón | servicios_publicos | sin_tema | servicios_publicos |

**Dónde no gana (y pierde en el punto estimado):** la IA nunca predice `sin_tema` (0 predichos, 4 reales: recall 0) y por eso asigna un tema a titulares que las personas dejaron ahí y confunde con `servicios_publicos` titulares cuyo tema de fondo es otro:

| ID | Titular | Humano | Base | IA |
|---|---|---|---|---|
| `NOT-14dcb8e259` | Contenido Exclusivo: Turismo en transporte público | turismo | turismo | servicios_publicos |
| `NOT-38702b3c42` | Profesor Angel Dust, el rey de la noche de Barcelona que acabó en una prisión de Panamá… | sin_tema | sin_tema | servicios_publicos |
| `NOT-aacff154c6` | La Chorrera proyecta renovar el parque Tomás Martín Feuillet con una inversión de 620 mil dólares | economia | economia | servicios_publicos |
| `NOT-d6cc7acc03` | Semana de la RSE busca impulsar la sostenibilidad en las empresas | sin_tema | sin_tema | turismo |
| `NOT-fbc3efaa5d` | Presidente de Panamá visita Singapur y Vietnam en busca de inversiones | economia | economia | logistica |

**Lectura honesta:** con estas etiquetas no se puede decir que la IA clasifique mejor que las palabras clave. Se puede decir que son errores distintos (10 titulares que solo la IA acierta frente a 5 que solo acierta la base), y que ninguno de los dos supera a las personas. El diagnóstico detallado está en `docs/clasificacion.md`.

## 2 · Agrupación de titulares (eventos)

- **IA:** embeddings `paraphrase-multilingual-MiniLM-L12-v2` con umbral coseno calibrado. **Base:** unir solo titulares idénticos (tras normalizar). Etiquetas: 100 titulares agrupados por personas en `eval/etiquetas.csv`.
- La cifra honesta de la IA es la de **validación cruzada agrupada** (el umbral de cada pliegue no vio los pares de prueba: 0.600 y 0.720). La del umbral elegido con todas las etiquetas (0.625) es optimista porque las mismas etiquetas calibran y evalúan; se muestra aparte en el JSON.
- Pares en alcance: 2.466 (93 positivos).

| Métrica | IA (CV) | Base | IA − base, IC 95 % | Veredicto |
|---|---|---|---|---|
| Precisión | 1.000 (91/91; IC 1.000–1.000) | 1.000 (65/65; IC 1.000–1.000) | 0.000 (0.000 a 0.000) | Sin diferencia demostrable |
| Recall | 0.979 (91/93; IC 0.866–1.000) | 0.699 (65/93; IC 0.447–0.950) | +0.280 (0.011 a 0.521) | **Gana la IA** |
| F1 | 0.989 (IC 0.928–1.000) | 0.823 (IC 0.617–0.974) | +0.166 (0.005 a 0.358) | **Gana la IA** |

**Dónde gana la IA:** une titulares de un mismo evento aunque no sean idénticos (26 pares que la IA une y la base no en la validación cruzada; la base nunca une un par que la IA no una):

| Par | Titulares | Grupo humano |
|---|---|---|
| `NOT-0969f86532` · `NOT-2ece201ac9` | «World Insights: Intensifying El Nino deepens economic risks across LatAm» · «Intensifying El Nino deepens economic risks across LatAm» | el-nino-latam |
| `NOT-1819a7014e` · `NOT-fbc3efaa5d` | «Presidente panameño visitará Singapur y Vietnam» · «Presidente de Panamá visita Singapur y Vietnam en busca de inversiones» | mulino-gira-asia |
| `NOT-364916b1e1` · `NOT-7170117798` | «Intensifying El Nino…» · «World Insights: Intensifying El Nino…» | el-nino-latam |
| `NOT-7bc0adfe59` · `NOT-bac341eccd` | «Intensifying El Nino…» · «World Insights: Intensifying El Nino…» | el-nino-latam |

Entre idiomas, la base no puede hacerlo.

**Dónde no gana:** en la validación cruzada la IA no introduce falsos positivos (0; la base tampoco), pero se le escapan 2 pares (1 con el umbral elegido), los de poca superposición léxica:

| Tipo | Par | Titulares |
|---|---|---|
| Falso negativo (umbral elegido) | `NOT-8206bf1857` · `NOT-f1f1f6e600` | «El abrir para cerrar de la mina de cobre…» · «Cobre Panamá volvería a producir…» (mina-cobre-panama: 0 de 1 par recuperado) |

**Lectura honesta:** el beneficio es de recall, no de precisión. Con el umbral elegido, la mayor parte de los pares sale de un grupo grande (`el-nino-latam`, 20 titulares, 190 de 190 pares); en grupos pequeños el efecto no se puede medir (`mulino-gira-asia`: 3 de 3; `mina-cobre-panama`: 0 de 1).

## 3 · Búsqueda (consultas del benchmark de desarrollo)

- **IA:** búsqueda semántica (`e5`). **Base:** BM25 sobre el mismo corpus e índice. Recall@5 por IDs esperados, 20 consultas con evidencia en el corpus. Bootstrap pareado sobre **consultas**.
- Sistema (semántica): 32/50 IDs (0.640); consultas completas 17/20 = 0.850 (IC 0.65–1.00). BM25: 24/50 IDs (0.480); consultas completas 12/20 = 0.600 (IC 0.399–0.800).
- Diferencia +0.160, IC 95 % 0.038 a 0.429: **la IA gana**. Es una de las cuatro diferencias que el criterio da por demostradas en este documento: las otras tres son el recall de pares en agrupación (+0.280, IC 0.011–0.521), el F1 de pares (+0.166, IC 0.005–0.358) y la búsqueda restringida a datos oficiales (+0.667, IC 0.273–1.000, abajo).
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

El ranking (puntaje P con R, I, U, N, E) es **código determinista de reglas v1.3, no un modelo**; no hay «IA» que comparar. La pregunta útil es si la bandeja prioriza lo que prioriza un editor, que es Precision@5 contra una selección independiente. **La selección la hizo una persona:** `outputs/precision_at_5.json` la rotula `origen_juicio: humano` (`eval/seleccion_editor.csv`), sin especialista editorial (`especialista: false`), así que es **exploratoria**. La sección `ranking` de `ia_vs_baseline.json` no repite la cifra (`utilidad_medible: false`): «la selección de eval/seleccion_editor.csv la hizo una persona; su Precision@5 (exploratoria) está en outputs/precision_at_5.json y aquí no se repite».

**Precision@5 (exploratoria: 5 temas, 1 fecha de corte, 2026-10-08T03:35:18Z, 69 candidatos).** Selección de la persona: `GRP-1df3ab1e22`, `GRP-3a15fc6a18`, `GRP-41ed91b93c`, `GRP-7ddcf92e16`, `GRP-dd7d78a551`.

| | Aciertos | Precision@5 | IC 95 % | Fallos (IDs) |
|---|---|---|---|---|
| Sistema (bandeja) | 0 de 5 | 0.000 | 0.000–0.434 | `GRP-5e6531917f`, `GRP-21ad932d54`, `GRP-4d8b340bd9`, `GRP-a329f4e91e`, `GRP-29baaf270e` |
| Baseline (más reciente primero) | 1 de 5 (`GRP-3a15fc6a18`) | 0.200 | 0.036–0.625 | `GRP-1dc52c45ff`, `GRP-50d72e2b04`, `GRP-a03bab5b02`, `GRP-1627d09497` |

Los IC se solapan: **sin diferencia demostrable**; los temas de un mismo corte no son independientes. El acierto del baseline es `GRP-3a15fc6a18` (detención domiciliaria de Lau Cortés), 1.º por fecha y 33.º en la bandeja. De los elegidos, `GRP-7ddcf92e16` (ataque a tiros cerca del metro de San Miguelito) queda 6.º en la bandeja (`outputs/prioridad.json`), justo fuera del top 5.

**Lo descriptivo (69 grupos):** el top 5 de la bandeja y el top 5 de «más reciente primero» (la línea base del PDF, sección 8) **no comparten ningún grupo** (0/5).

| Solo en el top del sistema | Titular central | Posición sistema · por fecha |
|---|---|---|
| `GRP-5e6531917f` | Más de 30 mujeres han muerto de forma violenta en Panamá este año | 1.º · 41.º |
| `GRP-21ad932d54` | Minsa enciende alarmas por diagnósticos de cáncer de mama en hombres en Panamá | 2.º · 48.º |
| `GRP-4d8b340bd9` | Aprehenden a 10 personas por presunta minería ilegal y delitos ambientales en Coclé del Norte | 3.º · 17.º |
| `GRP-a329f4e91e` | Chiriquí \| Investigan incendio en sastrería de calle Quinta en David | 4.º · 10.º |
| `GRP-29baaf270e` | Panamá mantiene vigilancia epidemiológica ante caso sospechoso de peste neumónica en Rusia | 5.º · 25.º |

| Solo en el top por fecha | Titular central | Posición por fecha · sistema |
|---|---|---|
| `GRP-3a15fc6a18` | Lau Cortés: Ordenan detención domiciliaria e imputan cargos por enriquecimiento injustificado y blanqueo de capitales | 1.º · 33.º |
| `GRP-1dc52c45ff` | César Caicedo ahora está recluido en el Hospital Santo Tomás; había sido trasladado a Coiba | 2.º · 30.º |
| `GRP-50d72e2b04` | Unos 22 aprehendidos en la operación Comunidad Segura contra el microtráfico en Colón y Panama Oeste | 3.º · 20.º |
| `GRP-a03bab5b02` | Asamblea: Debate por la renovación del contrato de Ciudad del Saber genera cuestionamientos por exoneraciones | 4.º · 47.º |
| `GRP-1627d09497` | Contenido exclusivo: Dietilenglicol, 20 años de dolor | 5.º · 31.º |

**Estabilidad** (`outputs/sensibilidad.json`, cada peso ±5 puntos y cada supuesto ±20 %): el top 5 no cambia de temas en 44 de 51 variantes con efecto (0.863, IC 0.743–0.932) y conserva el mismo orden en 38 de 51 (0.745, IC 0.611–0.845).

**Advertencia:** los cinco grupos del top del sistema tienen estado de evidencia `insuficiente`, un solo titular de un solo medio y la acción «Investigar ya». Que el ranking difiera del orden por fecha no dice que sea mejor, y con esta selección el orden por fecha acierta uno más.

## 5 · Análisis de abstención: ¿abstención correcta o fallo de recall?

**Histórico (E1-11 a E1-18):** el umbral de similitud de la consulta era **0.874** (percentil 5 de las consultas respondibles de la mitad de calibración). D-134 lo recalibró a **0.840** por margen máximo (`docs/consulta.md`, sección D-134); lo que sigue describe el análisis que motivó el cambio y sus cifras son las del umbral anterior. Reproducible con `poetry run python -m src.consulta "<pregunta>"` y con el análisis del umbral de `outputs/metricas.json` (`analisis_umbral`).

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
| **0.874 (anterior)** | 7/7 | 2 | `BDEV-004`, `BDEV-017` |
| 0.88 | 7/7 | 3 | `BDEV-004`, `BDEV-015`, `BDEV-017` |
| 0.90 | 7/7 | 9 | 9 consultas |

**Conclusión y qué falta:** el umbral prioriza no responder mal (abstención correcta 7/7 = 100 %, Wilson 64.6–100 %, n pequeño) a costa de rechazar algo de lo respondible. Para el pitch: «el sistema prefiere abstenerse a responder mal»; ante una consulta libre y corta sobre un tema de la bandeja, reformular con las palabras del titular lo resuelve. Para mejorarlo de verdad hacen falta **al menos unas 30 consultas negativas que lleguen a la puerta de similitud** (hoy hay 1) y datos de evaluación que nadie haya mirado al redactar las reglas. Con ese análisis, D-134 recalibró el umbral a 0.840 (vigente; `docs/consulta.md`).

## 6 · Lo que este análisis no demuestra

- No hay veredicto para la clasificación: el IC de la diferencia de macro-F1 incluye el cero.
- La ventaja de la búsqueda es en datos oficiales; en titulares no hay diferencia (22/38 = 22/38).
- El ranking solo tiene una Precision@5 exploratoria (5 temas, 1 corte, sin especialista editorial): los IC se solapan y no hay veredicto.
- Los temas con n < 5 (`logistica`, `turismo`, `regulacion`, `sin_tema`) no permiten veredicto por tema.
