# C-10 · Calidad: ranking y clasificación

Branch: `c-10-calidad-ranking-clasificacion` (desde `146f4e5`). Backlog: C-10. Estrategia de entrega: `ask-on-risk`.
Engram mirror: `odd/c-10-calidad-ranking-clasificacion/tasks` (pendiente: el registro de sesión falló el 2026-10-07).

## Objetivo
Corregir los defectos de ranking y clasificación que dejan la Precision@5 sin superar la línea base por fecha y la
exactitud de tema en 35/64 (54,7 %). Fuera de alcance por ahora: generación (caché y X45).

## Decisiones del dueño (2026-10-07)
- D3: lista en `config/` de nombres propios con «Panamá» que cuentan como mención del país.
- D4: la sección de la URL sube la sospecha de `fuera_de_temas`; solo se marca si el clasificador tampoco halla tema con confianza.
- D6: Panamá nombrado como parte del hecho manda sobre el lugar o la contraparte extranjera (no `exterior`).
- D7: se agregan estados y provincias extranjeras no ambiguos a `exterior` (sin «Georgia», «Washington», etc.).
- D1: R sigue como filtro de foco (se revisa tras mejorar la clasificación). D2: desempate por mayor similitud. Sin cambio de código.

## Restricciones
- Nunca ajustar pesos ni umbrales para acercarse a la selección provisional de Precision@5 (D-101).
- Sin números mágicos en `src/`; todo valor nuevo en `config/*.yaml` y en `docs/parametros.md` con su origen. Sin `if modalidad`.
- Sin fuga de evaluación: ejemplos reales nuevos van a `config/ejemplos_excluidos.txt`.
- Rama propia, nunca `main`. Sin push ni PR sin pedirlo. Commits convencionales, sin atribución de IA.
- Falla encontrada → se registra en *Pruebas* (siguiente libre X91) antes de corregir. Decisión nueva → *Decisiones* (siguiente D-117).

## Línea base (2026-10-07)
`src.config --validar`: 30 válidos. Suite: 2619 passed, 2 failed (pasan solas: `test_la_evaluacion_se_niega_a_correr_si_hay_fuga`,
`test_un_conflicto_al_abrir_no_deja_ninguna_fila_en_el_registro`), 6 skipped, 6 xfailed. Precision@5: sistema 1/5, línea base 0/5 (n = 5, exploratoria).

## Tareas
- [x] **T1** `specs/C-10.md` (Objetivo, Punteros, Restricciones, Listo cuando). Ruta: delegada (writer).
- [x] **T2** Ranking D3, D6, D7 en `src/puntaje.py` y `config/reglas_v1.3.yaml`, con tests (RED→GREEN) y filas en `docs/parametros.md`. Ruta: delegada (writer).
- [ ] **T3** Clasificación: matriz de confusión, Economía regional/multilingüe, D4 (URL como sospecha), sin fuga. Ruta: explorador y luego writer.
- [ ] **T4** Medir (n, IC 95 %): `eval.clasificacion`, `eval.precision_at_5`, `eval.puntaje`, `eval.sensibilidad`; suite completa, `src.config --validar`, `scripts.reproducir --verificar`. Ruta: delegada (verificación).
- [ ] **T5** PR con revisión independiente (D-78); corregir todo antes de integrar. Solo con pedido del dueño.

## Evidencia
- T1/T2 (ruta delegada, un writer): RED 36 failed y 9 passed en `tests/test_c10_ranking.py`; GREEN 155 passed en los tres
  archivos de prueba del ranking y la configuración; suite completa 2669 passed, 3 skipped, 6 xfailed; `src.config --validar` OK
  (30). Verificación del padre: repetí los tres archivos (155 passed) y `--validar` (OK).
- Cambios con efecto visible: se quitaron de `exterior_terminos` Georgia, Ghana, Guinea, India, Jordania, Mali, Lima y Washington
  (ambiguos; hallazgo 2 de la revisión del PR #45); «Brote en India» ya no es `exterior`. Pendiente de confirmar por el dueño.
- D3 no cambia ningún resultado por sí sola: «Panamá» suelto ya cuenta como mención del país; el efecto sobre «Canal de Panamá
  recibe barco de China» viene de D6.
- Asserts cambiados en `tests/test_e1_10d_ranking.py`: Texas pasa de `desconocido` a `exterior` (D7); dos titulares con Panamá
  nombrado pasan de `exterior` a `nacional` (D6).
- Revisión independiente (D-78) del PR #45: favorable con observaciones (3); no se publicó en GitHub ni en Notion.
- Revisión nativa de T1/T2 (riesgo medio, lente `review-reliability`): aprobada y reconocida (autoridad quemada). Hallazgos no
  bloqueantes: «Panama City» extranjero contaba como mención del país (WARNING) y un test de Georgia que no probaba nada.
- Seguimiento (ruta delegada, un writer): el dueño decidió restaurar India, Ghana, Guinea, Mali, Jordania y Lima (siguen fuera
  Georgia y Washington); nueva lista `geografia.panama_nombres_extranjeros` («Panama City», «Panama City Beach»); tests
  reescritos. RED 17 failed y 38 passed; GREEN 165 passed en los tres archivos, suite completa 2679 passed, 3 skipped, 6 xfailed,
  `src.config --validar` OK. Verificación del padre: 165 passed y `--validar` OK.

## Próximo paso
T3 (clasificación y D4).
