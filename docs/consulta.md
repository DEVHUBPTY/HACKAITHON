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
