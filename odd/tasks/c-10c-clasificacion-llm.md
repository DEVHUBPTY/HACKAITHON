# C-10c · Clasificación de temas con LLM (medición única)

Branch: `c-10c-clasificacion-llm` (desde `97b3c69`, la rama de C-10b que trae la evaluación por evento). Continuación de C-10.
Engram mirror: `odd/c-10c-clasificacion-llm/tasks` (pendiente: el registro de sesión falló el 2026-10-07).

## Objetivo
El clasificador activo (e5 método A, centroides) acierta 35/64 = 54,7 % [42,6–66,3], solo ~14 puntos sobre responder siempre «Economía»
(26/64 = 40,6 %), y el modelo supervisado exploratorio de C-10b no mejora de forma demostrable (D-57 no se cumple). El dueño pidió una
clasificación más exacta. Se prueba un LLM que lee el titular con la guía de temas (regla regional D-84 incluida) y devuelve el tema.

## Decisiones del dueño (2026-10-07)
- Opción A: clasificación con LLM usando el proveedor configurado (DeepSeek, `LLM_PROVIDER=deepseek` en `local.env`), con el tope de costo
  existente (D-67, D-98). Autoriza enviar a ese servicio **solo los titulares** (metadatos públicos), nada más.
- El resultado se mide **una sola vez** sobre las mismas etiquetas humanas y se reporta tal cual; **no** se conecta a producción hasta
  que el dueño lo decida (cambia el diseño: hoy la clasificación es solo de embeddings locales).

## Restricciones
- Prompt congelado ANTES de medir, escrito desde `docs/guia_temas.md` y `config/temas.yaml`; sin ningún titular etiquetado dentro; sin
  ajustar después de ver el resultado (una medición, sin bucles).
- Fuga declarada: la regla regional D-84 de la guía salió en parte de analizar las mismas etiquetas; el informe debe decirlo.
- Solo etiquetas `origen = humano`; las 61 provisionales no participan (D-101). No se imprimen ni citan titulares etiquetados.
- El texto del titular va dentro de `<titular>…</titular>` en el mensaje de usuario (dato, nunca instrucción); reglas en el system
  prompt. Salida JSON validada con pydantic, temperatura 0, modelo y versión del prompt fijados en config y en la clave de caché.
- Caché versionada de las respuestas para reproducir y para la demo sin internet (T10). Tope de costo respetado; sin secretos en logs,
  código, tests ni salidas (D-69).
- Sin números mágicos en `src/` ni `eval/`: valores en `config/*.yaml` con modelo pydantic estricto y fila en `docs/parametros.md`.
- No cambiar `src/clasificacion.py` (producción), umbrales, `config/temas.yaml` ni `eval/etiquetas.csv`.
- Toda proporción con n e IC 95 %, y métricas por evento con IC bootstrap por evento.
- Rama propia; commits convencionales sin atribución de IA; sin push ni PR sin pedirlo.

## Tareas
- [x] **T1** `specs/C-10c.md`. Ruta: delegada (writer).
- [x] **T2** Clasificador LLM (prompt versionado, esquema pydantic, caché, tope de costo) con tests con proveedor falso (sin red). Ruta: delegada (writer).
- [x] **T3** `eval.clasificacion_llm`: una sola corrida real sobre las filas evaluadas; comparación pareada por evento contra el método A y el criterio D-57; costo real. Ruta: delegada (writer).
- [ ] **T4** Decisión del dueño sobre conectarlo a producción (no se hace aquí).

## Evidencia
- T1 a T3 (ruta delegada, un writer; `done`): RED = error de colección (`ImportError`); GREEN = 45 tests nuevos; suite completa 3018 passed,
  3 skipped, 6 xfailed; `--validar` OK (34). Verificación del padre: 107 passed (tests nuevos, reproducibilidad y x15) y `--validar` OK;
  sin claves `sk-…` ni `DEEPSEEK_API_KEY=` con valor en nada versionable; `src/clasificacion.py`, `config/temas.yaml`,
  `config/ejemplos_excluidos.txt` y `eval/etiquetas.csv` sin cambios.
- Medición única (modelo `deepseek-flash`, prompt 1.0, temperatura 0; 64 filas, 30 eventos, solo humanas; fuga leve declarada: la regla D-84
  salió en parte de estas mismas etiquetas): exactitud por fila 35/64 = 54,7 % [42,6–66,3], igual que el método A; por evento 0,511
  [0,333–0,689] frente a 0,517 [0,350–0,683]; macro-F1 por evento 0,393 [0,199–0,643] frente a 0,430. Diferencia pareada por evento
  contra el método A: exactitud −0,006 [−0,233; +0,228], macro-F1 −0,037 [−0,226; +0,171]. IC solapados, D-57 NO se cumple.
- Comportamiento: 25 de 64 filas a `sin_tema` (cobertura 60,9 %); exactitud entre cubiertas 31/39 = 79,5 % [64,5–89,2]. Economía 3/26 (18
  pasaron a `sin_tema`), Eventos naturales 20/20 (un solo evento), Servicios públicos 7/9, `sin_tema` 4/5 (el método A: 0/5).
- Costo (corregido tras la revisión: solo las llamadas reales): 82 204 tokens de entrada y 1 699 de salida, ≈ USD 0,027 estimado (el
  contador sobreestima ≈ 2,6×); los 59 802 y 1 260 repetidos desde la caché van aparte. La primera versión sumaba las 64 respuestas
  (142 006 y 2 959, USD 0,046). 37 llamadas reales (hay 37
  titulares distintos); `--verificar` reproduce las métricas desde la caché sin red (64/64).
- Pendiente de decidir: 1 de 37 respuestas guardadas repite en `motivo` un fragmento del titular (4 o más palabras seguidas); el caché
  de `data/cache_clasificacion_llm/` guarda la respuesta cruda. Los titulares son metadatos permitidos; no hay descripciones.

## Próximo paso
T4: decisión del dueño. El LLM no mejora la exactitud de forma demostrable con las etiquetas actuales y NO se conecta a producción.
Reproducibilidad: el prompt nuevo cambia hashes de `scripts.reproducir` (no se corrió).

## Revisión nativa de C-10c
- Aprobada y reconocida (lente `review-reliability`, 48 archivos, 2898 líneas). Dos advertencias, corregidas después por pedido del dueño
  (ruta delegada, un writer): los tokens y el costo sumaban también los aciertos de caché (ahora solo las 37 llamadas reales; las
  métricas no cambian, verificado con `cmp` sobre el JSON sin tokens) y se agregaron 4 tests de las guardas de la CLI (ya se cumplían:
  guardas de regresión) más 2 de tokens. Suite completa 3024 passed, 3 skipped, 6 xfailed; `--validar` OK; `--verificar` rc 0.
