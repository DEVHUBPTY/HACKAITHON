# 📏 Protocolo de evaluación

Cómo se mide cada cosa, con qué datos, con qué comando y cómo se reporta.
**Regla general:** toda métrica se reporta con **numerador, denominador, intervalo de confianza del 95 % y los IDs de los fallos**. Las metas son orientativas del reto, no resultados obtenidos.

## 1 · Pruebas de aceptación T01–T10

| ID | Prueba | Archivo de test | Spec |
|---|---|---|---|
| T01 | Fechas inválidas y nulos | `tests/test_t01_carga.py` | E1-02 |
| T02 | Tres registros del mismo evento | `tests/test_t02_agrupacion.py` | E1-08 |
| T03 | Noticia antigua recirculada | `tests/test_t03_recirculada.py` | E1-10 |
| T04 | Cifra anual del Banco Mundial | `tests/test_t04_contexto.py` | E1-09 |
| T05 | Dos afirmaciones incompatibles | `tests/test_t05_contradiccion.py` | E1-10 |
| T06 | Consulta sin respuesta | `tests/test_t06_abstencion.py` | E1-11 |
| T07 | Fuente que exige ignorar instrucciones | `tests/test_t07_inyeccion.py` | E1-12 |
| T08 | Caso de prioridad alta | `tests/test_t08_prioridad.py` | E1-10 |
| T09 | Brief editorial o boletín bancario | `tests/test_t09_borrador.py` | E1-13 · E2-02 |
| T10 | Sin internet durante la demo | `tests/test_t10_offline.py` + ensayo C-04 | E1-14 |

`poetry run pytest -v tests/` · el resultado va a la base *Pruebas* de Notion (E1-17).

## 2 · Benchmark: desarrollo y evaluación reservada

| | Desarrollo | Reservada |
|---|---|---|
| Quién la tiene | El equipo (`benchmark/benchmark_dev.jsonl`) | **Solo el jurado** |
| Cómo se corre | `poetry run python -m eval.run_benchmark --split dev` | `poetry run python -m eval.run_benchmark --archivo <ruta> --salida <carpeta>` |
| Salidas | `outputs/benchmark/` + `outputs/metricas.json` | En la carpeta que elija el jurado |

El comando para la evaluación reservada acepta **cualquier archivo con el mismo formato**, funciona **sin internet** y nunca copia el archivo al repositorio. El README explica cómo usarlo.

## 3 · Métricas de la sección 9.1

| Métrica | Numerador / denominador | Datos | Comando | Meta |
|---|---|---|---|---|
| **Cobertura de citas** | Afirmaciones factuales emitidas con cita válida / afirmaciones factuales emitidas | Salidas del benchmark | `eval.run_benchmark` | 100 % |
| ↳ Rechazos previos | Afirmaciones rechazadas por el validador / generadas, por regla | `outputs/rechazos.jsonl` | `eval.run_benchmark` | Se reporta |
| **Validez de sustento** | Afirmaciones *sustentadas* / afirmaciones revisadas (≥ 30) | `outputs/revision_sustento.csv` | `eval.sustento` | ≥ 90 % |
| **Abstención correcta** | Consultas sin respuesta rechazadas / consultas sin respuesta | Benchmark (tipo "sin respuesta") | `eval.run_benchmark` | ≥ 80 % |
| ↳ Abstenciones incorrectas | Respondibles rechazadas / respondibles | Benchmark (tipo "sustentada") | `eval.run_benchmark` | Se reporta |
| **Clasificación** | Macro-F1 y F1 por tema, IA vs. baseline | `eval/etiquetas.csv` (~100) | `eval.clasificacion` | Se reporta |
| **Agrupación** | Precisión y recall de pares | `eval/etiquetas.csv` | `eval.agrupacion` | Se reporta |
| **Búsqueda** | Recall@5 de las evidencias esperadas, semántica vs. BM25 | Benchmark | `eval.recuperacion` | Se reporta |
| **Utilidad del ranking** | Temas del top 5 elegidos por el editor / 5 (sistema y baseline por fecha) | `eval/seleccion_editor.csv` | `eval.precision_at_5` | Exploratoria si no hay especialista |
| **Eficiencia** | Mediana y p95 de latencia; tokens y costo por consulta | Benchmark | `eval.run_benchmark` | Mediana ≤ 15 s |
| **Ahorro de tiempo** | Tiempo asistido vs. manual en la misma tarea, con n | `docs/prueba_tiempo.md` | Manual | Se reporta |

## 4 · Revisión humana de la validez de sustento

**Quién revisa:** una persona que **no** escribió el código de generación; idealmente la persona editorial que designe la organización.

**Muestra:** 30 afirmaciones elegidas al azar (semilla fija) de las salidas del benchmark, o todas si hay menos.

**Veredicto por afirmación** (columna `veredicto` de `revision_sustento.csv`):

| Veredicto | Cuándo |
|---|---|
| **Sustentada** | La evidencia citada dice lo que afirma el texto, con su fecha y alcance |
| **Parcial** | La evidencia apoya solo una parte, o falta el año o el alcance |
| **No sustentada** | La evidencia no dice eso |
| **Tipo incorrecto** | El contenido es correcto pero está etiquetado con el tipo equivocado (por ejemplo, una declaración como hecho) |

Para la meta de ≥ 90 % **solo cuenta "sustentada"**. "Parcial" y "tipo incorrecto" se reportan aparte.

## 5 · Calidad de las etiquetas

- **Tamaño y método** en `docs/etiquetado.md`: cuántos titulares, cómo se eligieron (semilla), quién etiquetó y con qué guía (`docs/guia_temas.md`).
- **Acuerdo entre etiquetadores:** 20 titulares etiquetados por **dos** personas por separado; se reporta el acuerdo (kappa de Cohen). Si es bajo, se revisa la guía antes de usar las etiquetas.

## 6 · Prueba de ahorro de tiempo

**Tarea equivalente:** a partir del mismo snapshot, elegir 5 temas para la agenda y, para uno de ellos, preparar un brief con sus fuentes y 3 preguntas de investigación.

| | Manual | Asistida |
|---|---|---|
| Herramientas | Navegador y los archivos del snapshot | La app |
| Se mide | Tiempo hasta terminar + validez de las fuentes citadas | Igual |

**Para que sea justa:**
- Cada participante hace **una condición por fecha de corte distinta**, para que no recuerde los temas.
- Se alterna el orden (unos empiezan manual, otros asistida).
- **Mínimo 3 pruebas por condición**; se reporta n.
- Se reporta también la **calidad** del resultado: ahorrar tiempo no vale si baja el sustento.
- Con pocas pruebas, el resultado se declara **exploratorio**.

## 7 · Lo que NO se mide ni se infiere

- Exactitud de un modelo de fraude: el reto no tiene etiquetas de fraude.
- Aumento de audiencia, rentabilidad o reducción de riesgo bancario.
- Que una noticia sea verdadera o falsa.
