# Coherencia entre documentos (E0-08)

Revisión de `CLAUDE.md`, `README.md`, `docs/`, `specs/` y la plantilla de PR contra las decisiones vigentes de Notion (D-74 a D-85 y las anteriores que citan) y contra lo que existe en el repo. Fecha: 2026-10-06.

**Criterio:** no se cambió la sustancia de ninguna decisión ni regla. Solo se alineó texto desactualizado a una decisión, se corrigieron inconsistencias de hecho entre documentos y se actualizaron las listas de comandos y estructura de `CLAUDE.md` a lo que existe (cada comando "disponible" se verificó con `--help`). Donde una spec choca en sustancia con `CLAUDE.md` y ninguna decisión lo resuelve, no se eligió: quedó en **Requiere decisión** y después se resolvió (ver abajo).

Las líneas citadas son las de `main` antes de este cambio (commit `9e09231`).

## Corregido (32)

| # | Archivo:línea | Contradicción | Corrección |
|---|---|---|---|
| 1 | `CLAUDE.md:18` | Formato de commit `E1-02: ...`; el repo usa *conventional commits* con el ID como ámbito (`feat(E1-06): ...`) | Ejemplo `feat(E1-02): ...` |
| 2 | `CLAUDE.md:22-37` | Comandos presentados como disponibles que no existen (`app.py`, `scripts.verificar_offline`, `eval.run_benchmark`, `scripts.reproducir`, `scripts.auditoria_final`) y faltaban los que sí existen (`scripts.extraer`, `scripts.manifest`, `scripts.validar_snapshot`, `src.config --validar`, `scripts.catalogo`, `scripts.explorar`, `eval/etiquetar.py`, `eval.ruido`, `eval.validar_benchmark`) | Dos bloques: *Disponibles hoy* (verificados) y *Previstos* con la spec que los crea |
| 3 | `CLAUDE.md:26` | "incluidas T01–T10": hoy solo existen `test_t01_carga.py` y `test_t03_recirculada.py` | "hoy T01 y T03; las demás llegan con su spec" |
| 4 | `CLAUDE.md:39-56` | La estructura listaba archivos inexistentes (`app.py`, `templates/ficha.md.j2`, 4 prompts, `revision.yaml`, `verificacion.yaml`, `modalidad_banca.yaml`, `extraer_*.py`, scripts de C-06/C-07/E1-20, `eval/run_benchmark.py`…, `outputs/fichas.jsonl`…) y omitía los existentes (`config/carga.yaml`, `contrato.yaml`, `normalizacion.yaml`, `etiquetado.yaml`, `exploracion.yaml`, `llm.yaml`, `benchmark.yaml`, `prompts/afirmaciones_citadas.txt`, `scripts/extraer.py`, `conversion.py`, `estimar_consultas_gdelt.py`, `src/config.py`, `src/consultas_gdelt.py`, `eval/ruido.py`, `eval/validar_benchmark.py`, `eval/etiquetas/`, `benchmark/sinteticos.csv`, `data/CHANGELOG.md`, `data/registro_extraccion/`, `notion/`) | *Lo que existe hoy* + *Previsto (spec)*; módulos de `src/` que son solo docstring marcados como tales |
| 5 | `CLAUDE.md:9-20` | Sin el flujo vigente ni el estado del evento: worktree → rama → PR con revisor independiente y merge del asistente (D-78); equipo y responsables por tarea; evento iniciado; demo local | Paso 8 (flujo, D-78) y párrafo *Equipo* |
| 6 | `CLAUDE.md:105` | "Primario: Ollama local" sin el modelo provisional (E0-07) ni el respaldo DeepSeek (D-80) | Se agregan `qwen3.5:9b` provisional y DeepSeek provisional con tope de costo (D-67, D-80) |
| 7 | `README.md:27-39` | Todo marcado como "previsto", incluidos comandos que ya existen; faltaba la extracción | *Disponibles hoy* / *Previstos*, y "la demo corre en local" |
| 8 | `docs/REVISION.md:26-30` | "Aprueba una persona distinta al autor" contradice D-78 | Paso 2 reescrito según D-78: agente revisor independiente que no escribió el código; veredicto escrito en el PR y en Notion (Backlog y Bitácora); merge del asistente solo con veredicto favorable; se mantienen la verificación de intención y el caso borde probado a mano; lo que el reto exige a personas sigue siendo humano (etiquetas D-85, benchmark E0-06, validez de sustento, revisión editorial) |
| 9 | `docs/FLUJO_CLAUDE_CODE.md:11` | Fase *Revisar*: "Aprueba alguien distinto al autor" | Revisor independiente + merge del asistente (D-78); el equipo sigue por el chat y aprueba lo que el reto exige a personas |
| 10 | `docs/FLUJO_CLAUDE_CODE.md:10` | Fase *Probar*: "el equipo etiqueta datos de evaluación" | Revisa y aprueba las etiquetas que propone el asistente (D-85) |
| 11 | `docs/FLUJO_CLAUDE_CODE.md:40-41` | Regla 5 antes que la 4; "Tres personas, tres ramas" contradice el flujo por worktree/PR y el reparto por Backlog | Regla 4: una tarea, un worktree, una rama, un PR (D-78); todos hacen de todo |
| 12 | `.github/pull_request_template.md:17-18` | "Aprobado por alguien distinto al autor" | Primera pasada del autor + veredicto favorable del revisor independiente (D-78) |
| 13 | `docs/cronograma.md:17-19` | Las columnas de rol se leían como personas | Son áreas; el responsable está en el Backlog |
| 14 | `docs/cronograma.md:21` | Tramo *Inicio* usa `verificar_offline`, que se construye en C-06 (*Cierre*) | `scripts.probar_llm` (E0-07); `verificar_offline` llega con C-06 |
| 15 | `docs/cronograma.md:22` | "Sesión de etiquetado con todos (E1-06)" | Revisión humana de las etiquetas propuestas (D-85) |
| 16 | `docs/cronograma.md:44-45` | Solo describía el plan previo; el evento ya empezó | Nota de estado: lo de la Etapa 0 que se cierre en el evento va con fase *Evento* (D-58) |
| 17 | `docs/protocolo_evaluacion.md:51` | "Idealmente la persona editorial que designe la organización" | D-74: revisa un integrante que no escribió el código; las métricas que requieren persona editorial se declaran exploratorias |
| 18 | `docs/protocolo_evaluacion.md:69` | Acuerdo con 20 dobles de dos personas (kappa) | Método D-85 y coincidencia propuesta–revisión, declarada como tal |
| 19 | `docs/parametros.md:102-103` | Falta línea en blanco: el título "Carga y validación" quedaba pegado a la tabla anterior | Línea en blanco |
| 20 | `docs/parametros.md:151` | Motivo del filtro de mención describe las consultas de GDELT anteriores a D-83 | Se aclara que se midió con las consultas anteriores y se revisa con la v1.2 |
| 21 | `docs/parametros.md:205-206` | Dobles y kappa mínimo como si se hubieran aplicado | Nota: no aplicados en las etiquetas actuales (D-85); `--consolidar` con `--forzar` |
| 22 | `docs/guia_temas.md:25` | Línea en blanco partía la tabla: la fila `no_es_noticia` no se mostraba como tabla | Se quita la línea en blanco |
| 23 | `specs/E0-03.md:22` | Solo `.env` en `.gitignore` | `.env` y `local.env` ignorados; `local.env` para configuración y secretos (D-77) |
| 24 | `specs/E0-04.md:21` | Consultas de GDELT "'Panama' combinado con…" | Dos patas por tema; los crudos anteriores se conservan como consultas históricas (D-83, corregido por D-89: sí alimentan `noticias.csv`) |
| 25 | `specs/E1-02.md:14` | Puntero a `config/reglas_v1.3.yaml`; la carga usa `config/carga.yaml` y `config/contrato.yaml` | Puntero corregido |
| 26 | `specs/E1-03b.md:11` | Ventana "[2024-01-01, 2025-10-01) o la que confirmen los organizadores" | Ventana de la sección 6 sobre la detección; el intervalo de la sección 7 no se aplica (D-74) |
| 27 | `specs/E1-03b.md:21` | Pide similitud con prototipo, pero quedó diferida a E1-07 (`specs/E1-07.md:30`, `similitud_prototipo.activo: false`) | Referencia cruzada a E1-07 |
| 28 | `specs/E1-03b.md:25` | No recogía D-84 (notas regionales), ya implementada | Restricción D-84 (`alcance_regional`, se cuentan aparte) |
| 29 | `specs/E1-06.md:3, 6, 16, 18, 20, 27` | "Claude Code no etiqueta", "todos etiquetan", 20 dobles con kappa | Alineado con D-85, dejando constancia de lo que decía la spec original |
| 30 | `specs/E1-07.md:35` | "llena `tema`", que choca con D-62 y con la línea 23 de la misma spec (`tema_clasificado`) | `tema_clasificado`; el `tema` de origen no se toca |
| 31 | `specs/E1-09b.md:12` | Ventana de sismos en `reglas_v1.3.yaml`; vive en `config/vinculos.yaml` (`ventana_coincidencia_dias`, `docs/parametros.md:54`) | Puntero corregido |
| 32 | `specs/README.md:8, 21, 34-38` | Roles leídos como personas; rol de E1-06 contra D-85; filas fuera de orden (E1-20 y E2-02 antes de E1-17) | Nota de áreas, rol de E1-06 según D-85 y orden corregido |

## Decisiones pendientes, ya resueltas (4)

Las cuatro quedaron sin decidir en la primera pasada; el equipo las resolvió y están registradas en Notion.

| # | Dónde | Choque | Resolución |
|---|---|---|---|
| A | `CLAUDE.md:84` frente a `docs/guia_temas.md:26`, `specs/E1-06.md:17`, `specs/E1-03b.md:22`, `config/etiquetado.yaml:23-24` y `src/limpieza.py` | `CLAUDE.md` decía que fuera de los 6 temas solo hay `no_es_panama` o `fuera_de_temas`; la guía, E1-06 y el código usaban también `no_es_noticia`, sin ID de decisión | **D-87:** `no_es_noticia` es motivo de ruido junto a `no_es_panama` y `fuera_de_temas`, y las personas también pueden asignarlo. Se citó D-87 en `CLAUDE.md`, la guía, E1-03b ("dos motivos" → tres) y E1-06 |
| B | `specs/E0-06.md:18` frente a `benchmark/README.md:11` | La spec decía que las etiquetas del benchmark las escriben y aprueban personas; en la práctica el asistente las propuso y una persona las aprobó | **D-85 ampliada:** cubre las 100 etiquetas de clasificación y las 40 consultas del benchmark de desarrollo con sus respuestas esperadas (el asistente propone; una persona revisa, edita si hace falta y aprueba). E0-06 lo dice, conservando la revisión humana que exige el PDF |
| C | `specs/E0-03.md:16`, `E0-04.md:18`, `E0-05.md:15`, `E0-06.md:15`, `E0-07.md:15`, `E0-09.md:16` | "Se hace antes del evento y se registra con fase Preparación", con el evento ya empezado y tareas E0 abiertas | **D-58:** cada tarea se registra con la fase en que realmente se hace: *Preparación* antes del evento y *Evento* desde que empezó (2026-10-06). Las seis specs E0 lo dicen así |
| D | `specs/E1-07.md:30` (y las mismas citas en `docs/clasificacion.md:37, 272`, `data/diccionario.md:133` y el comentario de `config/ruido.yaml:108`) | Atribuían a D-84 el diferimiento del filtro de similitud con prototipo; D-84 solo trata las notas regionales | Se cita la **revisión X14 de E1-03b**, donde se decidió el diferimiento |

## Fuera de alcance (no se tocó)

- `notion/`: exportación inicial desactualizada respecto de Notion (por ejemplo, `notion/bases/Decisiones.csv` termina en D-74). La versión vigente está en Notion.
- `docs/fuentes.md:61-67`: la lista "Qué se verifica al congelar el snapshot" sigue sin marcar salvo el RSS. No se pudo comprobar desde el repo si esas verificaciones se hicieron.
- `docs/exploracion.md`: lo genera `scripts.explorar`; no se edita a mano.
