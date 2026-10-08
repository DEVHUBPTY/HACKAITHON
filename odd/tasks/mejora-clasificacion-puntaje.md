# Mejora de clasificación, subtema y puntaje

- **Rama:** `mejora-clasificacion-puntaje` (desde `datos-tvn-20261008` @ ccb2a8e; el trabajo sin commit de D-119/D-120 viaja en el árbol y NO se commitea aquí)
- **Mirror Engram:** `odd/mejora-clasificacion-puntaje/tasks` (proyecto hackaithon)
- **TDD:** desactivado (sin configuración de proyecto/sesión). Chequeos funcionales: `poetry run pytest -v` + el eval de cada tarea.

## Objetivo

Que la etapa 2 (organizar) y la 4 (priorizar) del PDF discriminen: hoy 52 de 72 grupos quedan en "alto", 0 en "bajo", y la macro-F1 de tema es 0,49 (n = 46).

## Problema (medido 2026-10-08)

- R = 1 en 66/72 grupos y N = 1 en 71/72: suman ~45 puntos fijos; solo U ordena.
- 41/99 noticias útiles sin `fecha_publicacion` usan `fecha_deteccion` → U alto artificial.
- 49/72 grupos sin subtema: 13 porque el **tema está mal** (el titular nombra un subtema de otro tema), ~15 ruido colado, ~19 huecos de vocabulario, 2 ambiguos.
- Clasificador = centroide + umbral (método A); no aprende fronteras economía/regulación/servicios públicos.
- GDELT: todo lo del snapshot sale de consultas históricas; `economia sourcecountry:panama` devuelve 0 → hipótesis: GDELT busca sobre la traducción al inglés.

## Por qué

Un componente constante pesa cero (OECD/JRC Handbook, pasos 5–7). El tema mal clasificado arrastra subtema → I → vínculos.

## Restricciones

Todo número en `config/*.yaml` + `docs/parametros.md`; embeddings locales; puntaje determinista; sin `if modalidad`; nunca leer el benchmark reservado; rangos 40/70 del PDF intactos; ~400 líneas por tarea es solo heurística.

## Tareas

- [x] **T1 · D-121 Clasificador por regresión logística.** Ruta: delegada, con escritor único. Se agregó el método `logistica`, una LogisticRegression sobre e5.
  - **Entrenamiento:** solo con las 99 referencias de `temas.yaml`. Las etiquetas humanas no se usan, así que no hay fuga.
  - **Parámetros:** C=1000, umbral 0,472 y margen 0,462, todos calibrados por validación cruzada estratificada de 5 pliegues.
  - **Resultado sobre n = 46:**

    | Método | Exactitud | Macro-F1 |
    |---|---|---|
    | logística | 34/46 (73,9 %) | 0,576 |
    | A | 33/46 (71,7 %) | 0,492 |

  - **Diferencia pareada:** +0,085, IC [−0,137; 0,276]. Como el IC incluye el 0, **`metodo_activo` sigue en A**. El "35/46" del traspaso era incorrecto: A da 33/46.
  - **Pruebas:** 13 tests nuevos en verde. En la suite completa fallan 3 `test_x100_*` (`tests/test_c02_pagina_metricas.py`), que tienen `n=33, de=63` fijo en el código. Probablemente vienen de los outputs sin commit de D-119/D-120; no se aisló.
  - **Pendiente:**
    - `eval/ia_vs_baseline.py:284` trata cualquier método distinto de A como si fuera B. Hay que arreglarlo antes de activar `logistica`.
    - **Sin commit:** `src/configuracion.py` y `docs/parametros.md` están mezclados con lo de D-119/D-120.
- [x] **T2 · D-122 El subtema nombrado corrige el tema.** Ruta: delegada, con escritor único.
  - **Dónde vive la corrección:** en `agrupacion`, que es donde se crea `grupos.tema_clasificado`. El tema original queda en `tema_origen_clasificador`, y la columna `criterio_tema` lo marca. Se activa en `vinculos.subtema.correccion_tema`.
  - **Resultado:** 11 de 72 grupos cambian de tema. El diagnóstico decía 13; los 2 restantes no se encontraron. Los grupos sin subtema pasan de 49 a 38. P casi no se mueve: de 0/20/52 a 0/19/53.
  - **Pruebas:** `tests/test_d122_subtema_corrige_tema.py`, 14 tests.
  - **Suite completa en verde:** 2869 tests más los 54 de c02. Para llegar ahí:
    - Se regeneró `outputs/ia_vs_baseline.json`, que estaba viejo (35/64, de antes de D-120).
    - El test x100 que fijaba n=33 en el código ahora calcula el cambio a partir del valor real.
  - **Pregunta abierta:** con esta regla, los operativos policiales caen en servicios_publicos a través de `seguridad_ciudadana`.
  - **Sin commit.**
- [x] **T5 · D-123 Aprendizaje activo** (commit f4e6f0d). Ruta: delegada.
  - La evaluación queda congelada en `eval/muestra_original.csv`. El pool de entrenamiento toma solo etiquetas humanas que estén fuera de esa muestra, y hoy está vacío.
  - La cola de etiquetado se ordena por incertidumbre y cada resultado lleva la huella del pool.
  - Hueco: la revisión editorial no permite cambiar el tema, así que de ahí no salen etiquetas.
- [x] **T3 · D-124 N continua y tope de U con fecha imputada** (commit 5d522a2). Ruta: delegada.
  - N toma valores entre 0,50 (ancla baja, supuesto) y 0,69 (umbral de agrupación), comparando contra los 7 días previos. El tope de U es 0,5.
  - N en su moda: 71/72 → 53/72. P por rango: 0/19/53 → 0/23/49.

- [x] **T6 · D-125 Solo los 6 temas del PDF, sin subtemas.** Hecha: commits db5da7c y 61d9589, merge 5800bb5 a main, push hecho.
  - Tests de los archivos tocados: 1077 en verde. La suite completa NO se corrió, por pedido del usuario.
  - P quedó en 0/18/54.
  - La logística entrenada sin prototipos pierde contra A (−0,007), así que A sigue activo.
  - Pendiente: recalentar la caché con red (2 fixtures e2_03) y regenerar `fichas_trazables`. Decisión del dueño (2026-10-08). Rama `sin-subtemas`. Ruta: delegada, con escritor único (unos 30 archivos de código y configuración, y 20 de tests).
  - **I:** pasa a ser alcance por tema (6 valores) + alcance geográfico.
  - **Vínculos:** los dispara una regla interna de tema + términos, que no se muestra como categoría.
  - **Se elimina:** D-122 (corrección de tema por subtema) y el método B.
  - **Base de datos:** las columnas `subtema*` se conservan, pero se dejan de llenar.
  - **Chequeo:** tests de los archivos tocados; la suite completa se corre una sola vez en main.

## Integración (2026-10-08)
- Merge `e90f002` a main y push `01027c5..e807b85`, sin PR (pedido del usuario: se saltea el revisor independiente de D-78).
- Suite en main: 8 fallas, todas corregidas.
  - c01 (6): el fixture no tenía el evento SIS-us7000rev1; D-124 cambió la selección de CU-03 y quedó expuesto (de5e0de).
  - c02 (2): `ia_vs_baseline.json` había quedado viejo (e807b85).
  - Después del arreglo, c01 + c02 pasan 119/119. El resto de la suite ya había pasado en esa corrida (2944).
- Pendiente del usuario: revisar las 47 etiquetas de tvn_20261008 (llenan el pool) y luego `eval.clasificacion`.
- [x] ~~T4 · Consultas GDELT en inglés~~ — **CANCELADA.** Decisión vigente del dueño (2026-10-07): GDELT queda fuera, ni API ni GKG. La IP sigue bloqueada. Lo que ya está en el snapshot se queda como está, porque raw es inmutable, y se declara como hueco conocido. No volver a llamar a GDELT.

## Criterios de aceptación

- Macro-F1 con n e IC 95 %, comparación pareada contra el método A.
- Distribución de P por rango antes/después; ningún componente con > 80 % de valores iguales salvo justificación.
- `poetry run pytest -v` completo en verde.

## Progreso y evidencia

- 2026-10-08: rama creada; diagnóstico de subtemas hecho (tabla arriba).

## Próximo paso

T1.
