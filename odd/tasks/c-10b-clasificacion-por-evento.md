# C-10b · Clasificación: evaluación por evento y modelo supervisado exploratorio

Branch: `c-10b-clasificacion-por-evento` (desde `12e7993`, mismo punto que el PR #51 de C-10). Backlog: continuación de C-10 (clasificación).
Engram mirror: `odd/c-10b-clasificacion-por-evento/tasks` (pendiente: el registro de sesión falló el 2026-10-07).

## Objetivo
La clasificación de temas acierta 35/64 = 54,7 % (e5, método A), pero la evaluación es débil: las 64 filas equivalen a ~29 eventos no
independientes y todo intento de arreglo se midió sobre las mismas etiquetas del diagnóstico. Dos intentos con Economía regional se
revirtieron en C-10. El PDF pide ML/NLP sustantivo, un baseline simple y «mejora o limitación medida», sin imponer un modelo.

## Decisiones del dueño (2026-10-07)
- Mejorar la clasificación, incluso rehacerla desde cero si hace falta; el análisis del PDF y de Notion recomienda: (1) arreglar la
  evaluación, (2) probar un modelo supervisado sobre embeddings con validación cruzada agrupada por evento, (3) ampliar etiquetas.
- Se permite entrenar con las etiquetas **humanas**; el resultado se reporta como **exploratorio** (n pequeño, ~29 eventos).
- La ampliación de etiquetas (3) la hace el dueño a mano, en paralelo: confirmar las 61 provisionales (C-09), un segundo etiquetador y
  más titulares. El asistente solo prepara material.

## Restricciones
- Solo etiquetas con `origen = humano`; las 61 `asistente_provisional` nunca entrenan ni evalúan (D-101).
- Nada de fuga: no entrenar y evaluar con los mismos eventos; validación cruzada agrupada por evento; ejemplos de `temas.yaml` fuera
  de la evaluación (`config/ejemplos_excluidos.txt`); no usar el benchmark reservado.
- No cambiar el clasificador de producción (`src/clasificacion.py`, método A) ni sus umbrales: pasar a otro método es decisión del
  dueño y exige el criterio de D-57 (IC por evento que excluya el cero a favor).
- Sin números mágicos en `src/` ni en `eval/`: valores en `config/*.yaml` con modelo pydantic estricto y fila en `docs/parametros.md`.
- Toda proporción con n e IC 95 % (IC por evento donde corresponda). Sin `if modalidad`.
- Rama propia, nunca `main`; commits convencionales sin atribución de IA; sin push ni PR sin pedirlo.

## Tareas
- [x] **T1** `specs/C-10b.md` (Objetivo, Punteros, Restricciones, Listo cuando). Ruta: delegada (writer).
- [x] **T2** Evaluación por evento: exactitud y macro-F1 con IC bootstrap por evento, con y sin abstención (cobertura frente a exactitud),
  reutilizando `eval/diagnostico_temas.py`. Ruta: delegada (writer).
- [x] **T3** Modelo supervisado exploratorio (regresión logística sobre embeddings e5, `class_weight` balanceado) con CV agrupada por
  evento; comparación pareada por evento contra el método A y el baseline; clases con menos de 2 eventos se reportan aparte. Salida
  `outputs/clasificacion_supervisada.json` y sección en `docs/clasificacion.md` rotulada exploratoria. Ruta: delegada (writer).
- [x] **T4** Material para el dueño: cómo revisar las 61 provisionales (C-09) con `eval/etiquetar.py`, cuántos eventos y titulares faltan por
  tema para defender una mejora. Ruta: delegada (writer); solo documentación, sin etiquetar.
- [ ] **T5** Medir, correr la suite, `src.config --validar`, `scripts.reproducir` y registrar hashes. Ruta: delegada (verificación).

## Evidencia
- T1 a T4 (ruta delegada, un writer): RED = los dos archivos de tests fallaron en la colección con `ImportError`; GREEN = 32 tests nuevos
  (46 con `test_diagnostico_temas.py`); suite completa 2973 passed, 3 skipped, 6 xfailed; `--validar` OK (33). Verificación del padre:
  108 passed (tests nuevos, diagnóstico, reproducibilidad y x15) y `--validar` OK; `src/clasificacion.py`, `config/temas.yaml`,
  `config/ejemplos_excluidos.txt`, `eval/etiquetas.csv`, `eval/diagnostico_temas.py` y `eval/clasificacion.py` sin cambios; los JSON
  nuevos no traen titulares (solo un ID de evento).
- Evaluación por evento (64 filas, 30 eventos, IC 95 % bootstrap por evento): método A activo 35/64 = 54,7 % por fila, 0,517
  [0,350–0,683] por evento, macro-F1 0,430 [0,248–0,619], cobertura 52/64 = 81,2 %. Sin abstención: 36/64, macro-F1 0,389. Baseline
  de palabras clave 29-30/64. Todos los IC se solapan. Eventos naturales 20/20 es un solo evento (31,2 % de las filas); Economía
  4/26 con las 12 abstenciones de un mismo evento de 13 filas que falla 0/13. Sin El Niño, el activo acierta 15/44 = 34,1 % [21,9–48,9].
- Modelo supervisado exploratorio (regresión logística sobre e5, 5 pliegues × 20 repeticiones por evento; 42 filas, 27 eventos;
  fuera por menos de 2 eventos: Eventos naturales, Turismo y Regulación): exactitud por evento 0,548 [0,392–0,715] frente a 0,500
  [0,315–0,685] del método A (diferencia +0,048 [−0,115; 0,226]); macro-F1 −0,032 [−0,234; 0,297]. El criterio D-57 NO se cumple.
  No está conectado a producción. La mejor línea base se eligió con las mismas etiquetas (favorece a la línea base).
- Conteos para ampliar etiquetas (humano): Economía 26 filas · 11 eventos; Servicios públicos 9 · 9; Eventos naturales 20 · 1;
  Logística 2 · 2; Turismo 1 · 1; Regulación 1 · 1; sin_tema 5 · 5. Para detectar una mejora de 0,20 / 0,15 / 0,10 hacen falta ~19 / 35 / 78
  eventos. Detalle en `docs/revision_etiquetas.md`.
- Límite a decidir por el dueño: `eval/etiquetar.py` no tiene modo para cargar las 61 provisionales (C-09); con el snapshot actual
  `--muestra` incluye solo 23 de las 61 y `--validar` rechaza ids fuera de la muestra. Es tarea de código fuera de este alcance.

## Próximo paso
T5: `scripts.reproducir` (cambió `config/clasificacion.yaml`, pueden cambiar hashes) y revisión del cambio. Decisión del dueño pendiente:
cargar las 61 provisionales en la herramienta de etiquetado (tarea de código aparte).
