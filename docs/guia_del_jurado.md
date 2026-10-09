# Guía para el jurado

Esta guía recorre el prototipo en el orden en que el reto lo evalúa. Cada cifra sale de un archivo del repositorio, que se cita al lado; cada comando existe y se puede ejecutar. El enunciado oficial es [`docs/reto_TVN.pdf`](reto_TVN.pdf).

**Contenido**

1. [El reto](#1--el-reto)
2. [Las 7 etapas](#2--las-7-etapas)
3. [Casos de uso CU-01 a CU-05](#3--casos-de-uso-cu-01-a-cu-05)
4. [Puntuación](#4--puntuación)
5. [Arquitectura de IA y controles](#5--arquitectura-de-ia-y-controles)
6. [Seguridad, privacidad y ética](#6--seguridad-privacidad-y-ética)
7. [Datos: dónde están, contrato y diccionario](#7--datos-dónde-están-contrato-y-diccionario)
8. [Cómo correr todo](#8--cómo-correr-todo)
9. [Pruebas de aceptación y métricas](#9--pruebas-de-aceptación-y-métricas)
10. [Evaluación reproducible](#10--evaluación-reproducible)
11. [Limitaciones](#11--limitaciones)

---

## 1 · El reto

**«De la señal a la decisión»** (TVN Media). El reto pide un prototipo que convierta noticias públicas e indicadores oficiales en una **bandeja de temas priorizados, fichas de evidencia y borradores útiles para una decisión humana**. La innovación no está en producir más texto, sino en reducir el tiempo para encontrar un tema relevante, comprobar qué evidencia existe, identificar qué falta verificar y entregar un resultado trazable (PDF, sección 1).

**Modalidad elegida**

- **Principal: editorial (TVN).** Usuarios: editor/a y periodista (agenda priorizada, ficha de investigación, preguntas pendientes, borradores) y productor/a digital (titulares, resumen web y copy social).
- **Extensión: banca**, como configuración sobre el mismo núcleo (`config/modalidad_banca.yaml`): boletín de entorno para un analista, sin evaluar clientes ni ejecutar decisiones financieras.

**Qué hace el sistema**

- Carga un snapshot congelado de titulares (TVN RSS y GDELT) y datos oficiales (Banco Mundial, USGS y, en banca, la SBP).
- Clasifica los titulares en los seis temas del reto, agrupa los que hablan del mismo evento y cuenta las procedencias independientes.
- Relaciona cada grupo con datos oficiales pertinentes, o declara que no hay relación sustentada.
- Calcula un puntaje de atención explicable y, aparte, un estado de evidencia; de ambos sale una acción recomendada.
- Arma una ficha de evidencia con citas verificables (ID + campo) y, si la evidencia alcanza, un borrador con citas por afirmación.
- Registra la revisión de una persona (aceptar, corregir, descartar) y exporta la ficha para Notion.

**Qué no hace** (PDF, sección 2, y `CLAUDE.md`)

- No publica nada. **Todo lo que produce es un BORRADOR**; el estado máximo es «aprobado como borrador» y no existe acción, botón ni estado «publicar».
- No etiqueta noticias como verdaderas o falsas, ni detecta fraude, solvencia o riesgo de crédito.
- No mide rating, audiencia ni conversión.
- No lee artículos completos, no hace scraping ni guarda datos personales.
- En banca no recomienda comprar o vender ni infiere pérdidas, impagos o exposición de cartera.

Principio rector: **no afirmar más de lo que la evidencia permite, y demostrarlo cita por cita.**

---

## 2 · Las 7 etapas

La app (`poetry run streamlit run app.py`) tiene una pantalla por etapa, cada una con su URL (`config/interfaz.yaml`, `pantallas`), más la Consulta aparte. La raíz (`/`) abre «Cómo funciona».

| Etapa | Comportamiento mínimo del reto | Cómo lo cumple el prototipo | Dónde verlo |
|---|---|---|---|
| **1 · Cargar** | Leer el paquete público congelado; validar IDs, URLs, fechas, campos obligatorios y filas nulas; emitir un reporte de calidad. | Lee `data/processed/`, comprueba el SHA-256 de cada archivo contra `data/manifest.json` y valida cada registro con las reglas de `config/carga.yaml`. Los rechazos se separan con su motivo sin bloquear la carga; los nulos quedan como nulos. Escribe `data/processed/validos/`, `outputs/errores.csv` y `outputs/reporte_calidad.json`; la normalización crea `data/senales.duckdb`. En la pantalla se puede ejecutar la carga en vivo y validar un archivo propio (T01). | `/cargar` · `src/carga.py`, `src/normalizacion.py` · `tests/test_t01_carga.py`, `tests/test_d130_carga_en_vivo.py` |
| **2 · Organizar** | Clasificar temas (economía, logística/Canal, turismo, servicios públicos, eventos naturales y regulación); agrupar noticias sobre el mismo evento. | Limpieza: el ruido se **marca** (`es_ruido`, `motivo_ruido`), no se borra. Clasificación con embeddings locales (`intfloat/multilingual-e5-small`) en los seis temas, con tema secundario. Agrupación con `paraphrase-multilingual-MiniLM-L12-v2`: coseno promedio ≥ 0.69 y ventana de 7 días (`config/reglas_v1.3.yaml`, `agrupacion`). Por grupo se estiman las procedencias independientes: titulares que replican un mismo medio, agencia o red cuentan como una. | `/organizar` · `src/limpieza.py`, `src/clasificacion.py`, `src/agrupacion.py`, `src/procedencias.py` · `tests/test_t02_agrupacion.py`, `tests/test_clasificacion.py`, `tests/test_ruido.py`, `tests/test_procedencias.py` |
| **3 · Contextualizar** | Relacionar noticias con indicadores o eventos oficiales pertinentes; mostrar período, unidad y limitaciones; si no existe relación sustentada, no forzarla. | Vincula cada grupo con indicadores del Banco Mundial (`IND-`), sismos de USGS (`SIS-`) y, en banca, series de la SBP (`SBP-`), según el tema y una regla por vínculo (`config/vinculos.yaml`). Cada vínculo muestra período, unidad y limitación (p. ej. «dato anual … puede revisarse»). Sin relación sustentada, la ficha dice «no se fuerza la relación». | `/contextualizar` · `src/contexto.py`, `src/contexto_sismos.py`, `src/contexto_sbp.py` · `tests/test_t04_contexto.py`, `tests/test_d127_contexto_sustentado.py`, `tests/test_e1_09b_sismos.py` |
| **4 · Priorizar** | Calcular un puntaje de atención, mostrar componentes y generar una lista ordenada; distinguir relevancia de suficiencia de evidencia. | P = 30R + 25I + 20U + 15N + 10E (reglas v1.3), con cada componente visible y desempate por mayor U y luego ID. El **estado de evidencia** (insuficiente, parcial, suficiente) se calcula aparte y no entra en P. La acción sale de una tabla rango × estado (sección 4). | `/priorizar` · `src/puntaje.py` (CLI), `src/prioridad.py`, `src/evidencia.py`, `src/contradicciones.py` · `tests/test_t08_prioridad.py`, `tests/test_t03_recirculada.py`, `tests/test_prioridad.py` |
| **5 · Explicar** | Abrir una ficha: qué se reporta, quién lo reporta, qué está respaldado, qué falta comprobar y qué acción se recomienda. | La ficha (`Ficha`, modelo pydantic) tiene esas cinco partes. Cada línea respaldada lleva su cita ID + campo; un titular se presenta como declaración de su medio. Los vacíos llevan qué verificar y fuentes sugeridas. Se muestra en la app, en Markdown y como línea de `fichas.jsonl`. | `/explicar` (atajo `?caso=GRP-…`) · `src/ficha.py`, `templates/ficha.md.j2` · `tests/test_ficha.py`, `tests/test_t05_contradiccion.py` |
| **6 · Producir** | Redactar un borrador propio de la modalidad, con citas por afirmación; diferenciar hechos, declaraciones, inferencias e hipótesis. | Generación en dos pasos con DeepSeek (sección 5): primero afirmaciones tipadas y citadas, que pasan el validador; después cada sección se redacta solo con esas afirmaciones. La acción de la ficha decide qué se genera: sin evidencia suficiente, solo paquete de investigación. Campos exactos en [`docs/salidas.md`](salidas.md). La app lee los borradores de la caché, sin red. | `/producir` · `src/generacion.py`, `src/validador.py`, `src/esquemas.py`, `prompts/` · `tests/test_t09_borrador.py`, `tests/test_e1_13_reglas.py`, `tests/test_t07_inyeccion.py`, `tests/test_e1_12_generacion.py` |
| **7 · Revisar** | Registrar aceptación, corrección o descarte por una persona responsable; crear o actualizar manualmente la ficha en Notion (automatizar es opcional). | Cinco estados del reto (`config/revision.yaml`): nuevo, en revisión, requiere evidencia, aprobado como borrador, descartado. Acciones: «Aprobar como borrador», «Guardar corrección», «Pedir evidencia», «Descartar» (con motivo de una lista), «Reabrir». El revisor se elige de una lista. El registro (`data/revision.duckdb`) es de solo agregar. La exportación produce Markdown y la fila CSV de la base «Casos y evidencias» para importar a mano; la sincronización por la API de Notion es opcional ([`docs/notion.md`](notion.md)). | `/revisar` · `src/revision.py`, `src/exportar.py`, `src/notion.py` · `tests/test_e1_16_revision.py`, `tests/test_e3_03_notion.py` |
| Consulta (aparte) | Consultas en español (PDF, sección 2). | Respuesta extractiva con citas, o abstención antes de cualquier LLM (sección 5). | `/consulta?q=…` · `src/consulta.py` · `tests/test_t06_abstencion.py`, `tests/test_consulta.py` |

---

## 3 · Casos de uso CU-01 a CU-05

Las cinco fichas trazables salen de una **regla de selección de configuración** (`config/fichas_trazables.yaml`, D-118): una ficha por caso de uso, en orden, sobre el ranking oficial; nadie elige a mano. Las genera `poetry run python -m scripts.fichas_trazables --casos`. Índice completo: [`outputs/fichas_trazables/indice.md`](../outputs/fichas_trazables/indice.md); fila de Notion: [`casos_y_evidencias.csv`](../outputs/fichas_trazables/casos_y_evidencias.csv).

| Caso de uso (texto del PDF, sección 4) | Ficha | Cómo se eligió | Resultado |
|---|---|---|---|
| **CU-01 · TVN:** «¿Qué cinco temas merecen revisión para la agenda de Panamá y por qué?». Mostrar ranking, evidencia disponible y vacíos de verificación. | [CASO-016](../outputs/fichas_trazables/CASO-016.md) · `GRP-5e6531917f` | El primero del ranking. | Posición 1 · P = 86.08 · evidencia **insuficiente** · «Investigar ya» · revisión: requiere evidencia |
| **CU-02 · TVN:** abrir un tema económico, incorporar una serie oficial y redactar un brief sin confundir un dato anual histórico con una medición de hoy. | [CASO-017](../outputs/fichas_trazables/CASO-017.md) · `GRP-81a11a5998` | Primer grupo con `tema = economia` y vínculo directo a una serie oficial. | Posición 45 · P = 70.16 · evidencia **parcial** · «Completar evidencia y producir» · cita `IND-PAN-FP.CPI.TOTL.ZG-2024` como dato anual · revisión: aprobado como borrador (provisional) |
| **CU-03 · Común:** agrupar titulares repetidos y distinguir repetición de corroboración independiente; una agencia replicada cuenta como una sola procedencia. | [CASO-018](../outputs/fichas_trazables/CASO-018.md) · `GRP-79f3183472` | Primer grupo del reto, sin ruido, con más titulares que procedencias y al menos 3 titulares. | Posición 67 · P = 49.04 · evidencia **insuficiente** · «Vigilar» · **20 titulares de 18 medios = 1 procedencia** · revisión: requiere evidencia (provisional) |
| **CU-04 · Común:** preguntar por una cifra inexistente o por una contradicción. Abstenerse o mostrar las versiones y la verificación pendiente. | [CASO-019](../outputs/fichas_trazables/CASO-019.md) · `GRP-4d8b340bd9` | El snapshot no tiene contradicciones abiertas, así que aplica el criterio de respaldo declarado: evidencia insuficiente con cifras sin dato oficial. | Posición 3 · P = 85.28 · evidencia **insuficiente** · «Investigar ya» · vacío «los titulares traen cifras y no hay dato oficial vinculado» · revisión: requiere evidencia (provisional) |
| **CU-05 · Banca:** «¿Qué señales públicas del entorno logístico debo revisar?». Entregar contexto sectorial, no un score de clientes ni una alerta regulatoria definitiva. | [CASO-015](../outputs/fichas_trazables/CASO-015.md) · `GRP-da35c3dead` | Grupo fijo de la configuración (modalidad banca). | Posición 59 · P = 68.17 · evidencia **suficiente** · «Incluir como contexto» · 3 titulares, 3 procedencias · revisión: requiere evidencia (provisional) |

**CU-04 se demuestra además de dos formas** ([`docs/demo.md`](demo.md)):

- *Cifra inexistente (real):* la Consulta «¿Cuál fue el desempleo de Panamá en 2025?» se abstiene y ofrece el último dato disponible (2024: 8.45 %).
- *Contradicción (SINTÉTICA):* `GRP-55e0774b97` en la base de demo (`data/demo.duckdb`, fuera de git), con dos titulares sintéticos marcados (`SYN-C06-001`: «36 tránsitos diarios»; `SYN-C06-002`: «28 tránsitos diarios»). La ficha muestra las dos versiones y la verificación pendiente, sin elegir una. La base de demo nunca se usa para métricas.

**Trazabilidad comprobada contra los datos** (`outputs/fichas_trazables/trazabilidad.json`): todas las comprobaciones pasan, por ejemplo `afirmacion_con_cita` 40/40 (IC 95 % 91–100 %), `cita_con_id_en_datos` 52/52 (93–100 %), `cifra_oficial_coincide` 11/11 (74–100 %), `declaracion_literal` 27/27 (88–100 %).

**Quién revisó cada ficha (estado honesto)**

- **CASO-016 (CU-01) lo revisó una persona: Javier Acosta** (acción «Pedir evidencia», comentario «Cifra de mas de 30 muertes sin dato oficial vicnulado», 2026-10-09T04:15:00Z en el CSV).
- **CASO-015, CASO-017, CASO-018 y CASO-019 tienen revisión provisional del asistente** (D-101), rotulada en cada salida como «Asistente (provisional, D-101) · provisional (D-101)». No es un juicio editorial humano; lo debe rehacer una persona ([`docs/pendientes_humanos.md`](pendientes_humanos.md), C-09).
- `eval.revision` cuenta como «decidido» solo un caso que terminó aprobado o descartado. La revisión de CASO-016 terminó en «requiere evidencia», por eso `outputs/revision.json` sigue con 0 casos decididos por una persona y 1 decidido de forma provisional (CASO-017).

---

## 4 · Puntuación

El puntaje es una herramienta de **ordenamiento**, no una probabilidad de verdad ni de pérdida. Todo vive en [`config/reglas_v1.3.yaml`](../config/reglas_v1.3.yaml); cada número tiene su origen en [`docs/parametros.md`](parametros.md).

**P = 30R + 25I + 20U + 15N + 10E**, cada componente normalizado a 0–1.

| Componente | Peso | Cómo se calcula (v1.3) |
|---|---|---|
| R · Relevancia | 30 | Foco en Panamá × pertenencia temática. Foco: 1.0 si un titular trata a Panamá como sujeto, 0.7 si es implícito (medio panameño), 0.5 si es nota regional o de otro país. Pertenencia: 1.0 tema principal del reto, 0.6 solo secundario, 0.3 sin tema. |
| I · Impacto | 25 | 0.5 × alcance del tema + 0.5 × alcance geográfico (nacional 1.0, provincial 0.6, local, desconocido o exterior 0.3). El dato oficial y las procedencias no entran en I. |
| U · Urgencia | 20 | Fracción que queda de una ventana de 7 días desde la publicación más reciente (lineal de 1 a 0). Si solo hay fecha de detección, U se topa en 0.5 y se marca el vacío. |
| N · Novedad | 15 | Similitud del grupo con los grupos anteriores de los últimos 7 días: N = 1 por debajo de 0.50, N = 0 desde el umbral de agrupación (0.69), lineal entre ambos. Repetir no sube N. |
| E · Evidencia disponible | 10 | 0.5 × procedencias (tope 3) + 0.3 × dato oficial + 0.2 × proporción de titulares con medio y fecha conocidos. |

- **Rangos** (sin solapamiento): bajo [0, 40), medio [40, 70), alto [70, 100]. **Empates:** mayor U y luego menor ID; P se compara con el decimal que muestra la bandeja.
- **Estado de evidencia, independiente de P:** *suficiente* = 2 o más procedencias, sin contradicción abierta y, si hay cifras, con dato oficial; *parcial* = 2 o más procedencias, o 1 procedencia con dato oficial; si no, *insuficiente*.

**Tabla de acciones (rango × estado)** — ninguna celda habilita publicar.

| Rango | Suficiente | Parcial | Insuficiente |
|---|---|---|---|
| Alto | Producir borrador | Completar evidencia y producir | Investigar ya |
| Medio | Borrador opcional | Vigilar | Vigilar |
| Bajo | Archivar como contexto | Archivar | Archivar |

Fuente: `config/modalidad_editorial.yaml`. En banca la tabla cambia solo de etiquetas (`config/modalidad_banca.yaml`: «Incluir en el boletín como observación», «Seguimiento prioritario», «Incluir como contexto», etc.).

**Distribución en el snapshot** (69 grupos, `outputs/prioridad.json` y `outputs/pagina_metricas.md`): alto 46/69 (66.7 %, IC 95 % 54.9–76.6 %), medio 23/69 (33.3 %, 23.4–45.1 %), bajo 0/69 (0–5.3 %). Estado de evidencia: suficiente 2/69, parcial 3/69, insuficiente 64/69. P: mínimo 46.358, mediana 72.460, máximo 86.079.

**Sensibilidad** (`poetry run python -m eval.sensibilidad`, cada peso ±5 puntos y cada supuesto ±20 %):

| Medida | Resultado | IC 95 % |
|---|---|---|
| Variantes cuyo top 5 no cambia de temas | 44/51 = 86.3 % | 74.3–93.2 % |
| Variantes que conservan el mismo orden | 38/51 = 74.5 % | 61.1–84.5 % |
| Temas del top 5 que se conservan (todas las variantes) | 247/255 = 96.9 % | 93.9–98.4 % |

---

## 5 · Arquitectura de IA y controles

Flujo (PDF, sección 8): snapshot → validación y normalización → DuckDB → clasificación, agrupación y búsqueda → priorización → ficha → generación con evidencias → interfaz → revisión humana → exportación a Notion.

### Dónde se usa IA

| Uso | Modelo | Dónde corre |
|---|---|---|
| Clasificación de tema | `intfloat/multilingual-e5-small` (embeddings) | Local (`models/`; sin red con `HF_HUB_OFFLINE=1`) |
| Agrupación de eventos y novedad | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Local |
| Búsqueda de la Consulta | e5 (semántica) | Local |
| Redacción de borradores y comparación de pares candidatos a contradicción | DeepSeek `deepseek-flash`, temperatura 0, semilla 0 | API de pago, solo al generar; la demo lee de la caché |

- **Generación en dos pasos** (`config/generacion.yaml`): paso 1, afirmaciones tipadas con cita (`prompts/afirmaciones_ficha.txt`); paso 2, cada grupo de secciones se redacta por separado usando solo las afirmaciones validadas (`prompts/paquete_editorial.txt`; en banca `prompts/boletin_banca.txt`). La salida es JSON validado con pydantic (`src/esquemas.py`). Hay un reintento; si tampoco valida, la sección queda vacía con el motivo, nunca se rellena.
- **Código determinista, sin LLM:** puntaje, estado de evidencia, acción, ficha, validador y la respuesta de la Consulta (extractiva).
- **Medido** (`outputs/pagina_metricas.md`): paquete completo p50 6.36 s (n = 12, IC 5.04–7.69 s), p95 12.41 s; Consulta p50 0.0125 s (n = 40); costo mediano por paquete 0.0031 USD (cota superior, n = 12); unidades rechazadas por el validador 33/149 = 22.1 % (IC 16.2–29.5 %).

### IA contra su línea base

Detalle completo en [`docs/ia_vs_baseline.md`](ia_vs_baseline.md) (`poetry run python -m eval.ia_vs_baseline`). Regla fijada antes de medir: una diferencia está demostrada solo si el IC 95 % de la diferencia pareada excluye el cero.

| Tarea | IA | Línea base | IA − base (IC 95 %) | Veredicto |
|---|---|---|---|---|
| Clasificación (macro-F1, n = 100 titulares) | 0.629 (0.427–0.774) | Palabras clave: 0.601 (0.399–0.749) | +0.028 (−0.244 a 0.310) | Sin diferencia demostrable |
| Agrupación (F1 de pares, validación cruzada, 100 titulares) | 0.989 (0.928–1.000) | Titulares idénticos: 0.823 (0.617–0.974) | +0.166 (0.005 a 0.358) | **Gana la IA** (por recall: 91/93 frente a 65/93) |
| Búsqueda (Recall@5, 20 consultas, 50 IDs) | 32/50 = 0.640 | BM25: 24/50 = 0.480 | +0.160 (0.038 a 0.429) | **Gana la IA** (en datos oficiales; en titulares empatan 22/38) |
| Ranking (Precision@5, exploratoria) | 0/5 (0.000–0.434) | Más reciente primero: 1/5 (0.036–0.625) | IC solapados | Sin diferencia demostrable |

**Cuándo no ayuda:** en clasificación la IA nunca predice `sin_tema` y confunde titulares con `servicios_publicos`; los temas con n < 5 no permiten veredicto. El ranking no es un modelo sino reglas.

### Modelos locales medidos y descartados

[`docs/eleccion_modelo.md`](eleccion_modelo.md): con el pipeline real (dos pasos y validador) sobre la misma ficha, `qwen3.5:9b` tardó 122.3 s y `gemma4:12b` 190.2 s por paquete (mediana, n = 3), con 1 afirmación válida cada uno y secciones vacías; DeepSeek, 16.6 s (n = 5) y 6–7 afirmaciones válidas. Por eso DeepSeek es el único proveedor de generación (D-94, D-95). Ollama sigue soportado por configuración pero está apagado y no se usa como respaldo.

### Controles

| Control | Cómo se aplica | Dónde |
|---|---|---|
| Cita válida = ID + campo | Toda afirmación cita un ID con prefijo y un campo; una URL suelta no es cita. Lo que no valida no se emite. | `src/validador.py`, `config/validador.yaml` |
| Tipos de afirmación | *Hecho* solo con datos oficiales (`IND-`, `SIS-`, `SBP-`) o conteos del grupo (`GRP-`); un titular es siempre *declaración* de su medio; *inferencia* e *hipótesis* citan afirmaciones base y la hipótesis va en condicional. | `config/generacion.yaml` (`prefijos`), `config/validador.yaml` |
| Comillas literales | Todo texto entre comillas debe ser literal del titular citado. | Validador (D-45) |
| Cifras | Toda cifra debe coincidir con el campo citado (con redondeo declarado). | `config/validador.yaml` (`numeros`) |
| Causalidad | Conectores causales solo si están literales en el titular citado o dentro de una hipótesis condicional. | `config/validador.yaml` (`causales`, D-68) |
| Acusaciones | Solo como declaración atribuida y literal del titular; nunca como hecho, inferencia ni hipótesis. | `config/validador.yaml` (`acusaciones`, D-68) |
| Sin lectura simulada | Frases como «según el artículo» se rechazan; toda salida lleva la leyenda «basado únicamente en titular/metadatos». | `config/restricciones.yaml` (D-51) |
| Abstención antes del LLM | La Consulta no usa LLM y se abstiene sin evidencia suficiente (umbral de similitud 0.840). En la generación, la acción de la ficha decide antes de llamar al modelo: «Archivar» o «Seguimiento» no generan nada y «Investigar ya» o «Vigilar» solo el paquete de investigación; sin al menos una afirmación válida no se redacta ninguna sección. | `src/consulta.py`, `config/consulta.yaml`, `config/generacion.yaml` (`acciones`, `afirmaciones`) |
| Fuentes como dato, no instrucción | La evidencia va dentro de `<evidencia>…</evidencia>` en el mensaje de usuario y las reglas en el system prompt; los titulares con patrones de instrucción se marcan `sospechoso_inyeccion` y se muestran como texto. El LLM no tiene herramientas. | `config/restricciones.yaml` (`inyeccion`), `tests/test_t07_inyeccion.py` (T07: 25/25) |
| Tope de costo | USD 100 o 200 M tokens; al alcanzarlo, `TopeDeCostoAlcanzado`; un HTTP 402 (`SaldoAgotado`) detiene sin reintento y sin volver a un modelo local. | `config/generacion.yaml` (`tope_costo`), `src/llm/costo.py` |
| Sin red | La interfaz solo lee la caché `data/cache_llm/` (versionada) y nunca llama al LLM. | [`docs/fallback.md`](fallback.md), `config/interfaz.yaml` |

---

## 6 · Seguridad, privacidad y ética

- **Secretos.** Solo en `local.env` (ignorado por git). En el repositorio está `.env.example` con los nombres vacíos (`LLM_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `DEEPSEEK_API_KEY`, `NOTION_TOKEN`). Los logs redactan los valores de `*_KEY`, `*_TOKEN` y `*_SECRET` (D-69). Escaneo con gitleaks 8.30.1 sobre el historial completo (462 commits), `outputs/` y el árbol de trabajo: `limpio: true`, 0 hallazgos reales (los crudos eran claves de widgets de Streamlit) — [`outputs/auditoria_secretos.json`](../outputs/auditoria_secretos.json).
- **Sin datos personales.** De la firma solo se guarda `agencia` y `tipo_firma`, nunca el nombre del autor (D-32); `sin_nombres_de_autor` pasa en las 5 fichas trazables. No se crean perfiles ni se agrupa por persona.
- **Solo metadatos.** No se descargan cuerpos de artículos, imágenes ni videos. La descripción del RSS se usa solo para clasificar; nunca se muestra ni se republica (D-31).
- **Redistribución restringida (D-72).** `data/raw/rss_tvn/`, `data/raw/gdelt/` y `data/raw/sbp/` no se versionan; `socialimage` no se guarda. El manifest conserva sus SHA-256 y la receta para regenerarlos ([`data/README.md`](../data/README.md)).
- **SBP: riesgo aceptado (D-116).** `data/processed/sbp_series.csv` (36 valores agregados del sistema bancario, 2024) **sí se versiona** por decisión del dueño, aunque el aviso legal de la SBP prohíbe reproducir o redistribuir sin autorización escrita. La autorización **no se ha pedido**. Si el repositorio o el paquete de entrega se hacen públicos, hay que pedirla o retirar esos valores ([`docs/fuentes.md`](fuentes.md)).
- **Sin «publicar».** Los estados son los cinco del reto; la auditoría (P-03) no encuentra ningún estado, etiqueta ni botón «publicar».
- **Acusaciones solo como declaraciones atribuidas** (D-68). La causalidad solo si es literal o condicional.
- **Sin etiquetas de verdad.** No hay verdadero/falso ni detección de fake news. Una contradicción se presenta solo como «posible contradicción, verificar», sin veredicto.
- **Límites de banca.** El validador rechaza recomendaciones de compra o venta, certezas, futuros asertivos y léxico de pérdidas, impagos, morosidad, exposición, cartera o solvencia en inferencias e hipótesis (`config/restricciones.yaml`, grupo `banca`). Todo boletín dice «No constituye recomendación financiera ni opinión oficial de la SBP».
- **Una alerta es una invitación a investigar.** Ni tono, ni volumen, ni repetición equivalen a verdad comprobada.

---

## 7 · Datos: dónde están, contrato y diccionario

**Snapshot** (`data/manifest.json`): versión **1.4**, corte **2026-10-08T03:35:18Z**, ventana de 30 días (2026-09-08 a 2026-10-08), hash del snapshot `4503952d97fb…`. Cada archivo lleva su SHA-256, la consulta que lo produjo, su licencia y el historial de transformaciones.

| Ruta | Qué es | Registros |
|---|---|---|
| `data/raw/` | Crudos inmutables (Banco Mundial y USGS en git; RSS, GDELT y SBP solo locales, D-72) | — |
| `data/processed/noticias.csv` | Titulares de TVN RSS y GDELT, solo metadatos | 268 |
| `data/processed/indicadores.csv` | Banco Mundial: 6 países × 6 indicadores × 15 años, con nulos explícitos (D-81) | 540 |
| `data/processed/eventos.geojson` | Sismos de USGS, 2024, caja lat 5–12 / lon −86 a −76, M ≥ 3 | 82 |
| `data/processed/sbp_series.csv` | SBP: 3 series agregadas × 12 meses de 2024 (solo banca) | 36 |
| [`data/diccionario.md`](../data/diccionario.md) | Diccionario de cada archivo y de cada tabla de `senales.duckdb` | — |
| [`docs/fuentes.md`](fuentes.md) | Origen, URL, licencia y condiciones de cada fuente | — |
| `benchmark/benchmark_dev.jsonl` | Benchmark de desarrollo: 40 consultas aprobadas por una persona ([`benchmark/README.md`](../benchmark/README.md)) | 40 |

Licencias (`data/manifest.json`, `licencias`): Banco Mundial CC BY 4.0; USGS dominio público; TVN y GDELT solo metadatos, sin licencia sobre los artículos; SBP pendiente de verificar (ver sección 6). El código es MIT (`LICENSE`) y no cubre los datos.

**Contrato de datos (PDF, sección 7)** — los encabezados reales coinciden con los campos mínimos:

| Archivo | Campos mínimos |
|---|---|
| `noticias.csv` | id_noticia, titulo, url, medio, idioma, fecha_publicacion, fecha_deteccion, fecha_extraccion, tema, origen, alcance_texto |
| `indicadores.csv` | pais_iso3, indicador_id, anio, valor (nullable), unidad, fuente_url, fecha_extraccion, licencia |
| `eventos.geojson` | id, magnitude, time, updated, longitude, latitude, depth, place, status, url |
| `fichas.jsonl` | id_caso, modalidad, ids_fuente, afirmaciones, citas, puntaje, componentes, estado_evidencia, borrador, estado_revision |
| `manifest.json` | version, fecha_corte_UTC, consultas, cantidad por archivo, licencia/condiciones, sha256, transformaciones |

**Reglas de integridad:** UTF-8; fechas ISO 8601 UTC en los datos y hora de Panamá solo en la interfaz; `fecha_publicacion` y `fecha_deteccion` (seendate de GDELT) nunca se sustituyen una por otra; los nulos son nulos, nunca cero.

**IDs estables (D-63):** `NOT-` = SHA-1 de la URL canónica (10 caracteres) · `IND-<país>-<indicador>-<año>` · `SIS-<id USGS>` · `SBP-<serie>-<período>` · `GRP-` = hash de sus `NOT-` ordenados · `CASO-` correlativo y persistente (nunca se reutiliza) · `SYN-` dato sintético. El mismo dato produce siempre el mismo ID.

---

## 8 · Cómo correr todo

**Instalación** (Python 3.11 y Poetry):

```bash
poetry env use python3.11
poetry install            # dependencias fijadas en poetry.lock
cp .env.example local.env # completar localmente; local.env no se versiona
```

**La app:**

```bash
poetry run streamlit run app.py              # snapshot (data/senales.duckdb)
```

**Preparar la demo:**

```bash
poetry run python -m scripts.preparar_demo           # crea data/demo.duckdb (snapshot + caso sintético de CU-04); sin red ni LLM
poetry run python -m scripts.calentar_cache          # SOLO CON RED: genera los borradores y los guarda en data/cache_llm/
poetry run python -m scripts.calentar_cache --verificar   # sin red: comprueba que la caché cubre los grupos de la demo
poetry run python -m scripts.verificar_offline       # chequeo antes del pitch, sin red ni LLM; sale con 1 si falla algo obligatorio
.venv/bin/streamlit run app.py -- --demo            # modo demo (poetry run no pasa el «--»)
```

- Recorrido cronometrado de 4 minutos, pruebas dinámicas del jurado y plan B: [`docs/demo.md`](demo.md).
- Funcionamiento sin internet y qué hacer si algo falla: [`docs/fallback.md`](fallback.md). Sin red funciona todo salvo generar borradores nuevos; los que están en la caché se leen igual.

### Cada modalidad

- **Editorial (TVN)** viene por defecto en la app.
- **Banca:** en la barra lateral, «Modalidad» → «Banca». La app recalcula los puntajes de banca en una copia de sesión (la base original no se toca) y todas las pantallas pasan a esa modalidad: **4 · Priorizar** muestra la bandeja agrupada por sector y **6 · Producir** el boletín de entorno (observaciones, hipótesis de impacto, sectores relacionados, horizonte temporal y tres preguntas para el analista). Para CU-05, elegir el grupo «Presidente de Panamá visita Singapur y Vietnam» (`GRP-da35c3dead`).
- Por línea de comandos (`--modalidad banca` en `src.puntaje`, `src.ficha` y `src.generacion`) y calentado de la caché de banca: [README, «Cómo usar cada modalidad»](../README.md#cómo-usar-cada-modalidad). Campos del boletín y sus prohibiciones: [`docs/salidas.md`](salidas.md).

---

## 9 · Pruebas de aceptación y métricas

```bash
poetry run pytest -v                                 # todas las pruebas
poetry run python -m eval.reporte_pruebas            # T01–T10 por marcador → outputs/pruebas.csv (columnas de la base Pruebas de Notion)
```

**Matriz T01–T10** ([`outputs/pruebas.csv`](../outputs/pruebas.csv), 10 de 10 en «Pasa»):

| ID | Prueba | Caso de uso | Resultado observado | Estado | Archivo de test |
|---|---|---|---|---|---|
| T01 | Archivo con fechas inválidas y nulos | — | 58 de 58 pruebas pasan | Pasa | `tests/test_t01_carga.py` |
| T02 | Tres registros del mismo evento | CU-03 | 7 de 7 | Pasa | `tests/test_t02_agrupacion.py` |
| T03 | Noticia antigua recirculada | — | 14 de 14 | Pasa | `tests/test_t03_recirculada.py` |
| T04 | Cifra anual del Banco Mundial | CU-02 | 76 de 76 | Pasa | `tests/test_t04_contexto.py` |
| T05 | Dos afirmaciones incompatibles | CU-04 | 28 de 28 | Pasa | `tests/test_t05_contradiccion.py` |
| T06 | Consulta sin respuesta en el corpus | CU-04 | 7 de 7 | Pasa | `tests/test_t06_abstencion.py` |
| T07 | Fuente que exige ignorar instrucciones | — | 25 de 25 | Pasa | `tests/test_t07_inyeccion.py` |
| T08 | Caso de prioridad alta | CU-01 | 49 de 49 | Pasa | `tests/test_t08_prioridad.py` |
| T09 | Brief editorial o boletín bancario | CU-02 · CU-05 | 37 de 37 | Pasa | `tests/test_t09_borrador.py` |
| T10 | Sin internet durante la demo | — | 9 de 9 | Pasa | `tests/test_t10_offline.py` + ensayo C-04 |

**Página de métricas:** [`outputs/pagina_metricas.md`](../outputs/pagina_metricas.md), generada con `poetry run python -m scripts.pagina_metricas` desde los JSON de `outputs/`. Ninguna cifra se escribe a mano; cada una indica su archivo de origen y quién hizo el juicio (`humano`, `automático` o `PROVISIONAL` del asistente). Cómo se mide cada métrica: [`docs/protocolo_evaluacion.md`](protocolo_evaluacion.md).

| Métrica (PDF 9.1) | Resultado | IC 95 % | Juicio | Meta |
|---|---|---|---|---|
| Cobertura de citas (respuestas de la Consulta) | 84/84 = 100 % | Wilson 95.6–100 % | automático | 100 % |
| Afirmaciones factuales de borradores con cita válida | 43/43 = 100 % | Wilson 91.8–100 % | automático | 100 % |
| Validez de sustento | 29/30 = 96.7 % (fallo: `GRP-39773bed5a/A4`) | Wilson 83.3–99.4 % | humano | ≥ 90 % (estimación puntual) |
| Abstención correcta (sin respuesta) | 7/7 = 100 % | Wilson 64.6–100 % | automático | ≥ 80 % |
| Abstención correcta, preguntas fuera del corpus escritas por una persona | 24/30 = 80 % | 62.7–90.5 % | humano | ≥ 80 % |
| Abstenciones incorrectas (respondibles rechazadas) | 0/30 | Wilson 0–11.3 % | automático | se reporta |
| Recall@5 semántica / BM25 | 32/50 = 64 % / 24/50 = 48 % | 42.6–100 % / 32.1–80 % | automático | se reporta |
| Macro-F1 clasificación IA / baseline (n = 100) | 0.629 / 0.601 | 0.427–0.774 / 0.399–0.749 | humano | se reporta |
| Recall de pares de agrupación IA / baseline | 91/93 = 97.9 % / 65/93 = 69.9 % | 86.6–100 % / 44.6–95.0 % | humano | se reporta |
| Precision@5 sistema / baseline por fecha | 0/5 / 1/5 | 0–43.5 % / 3.6–62.5 % | humano, exploratoria | — |
| Latencia p50 Consulta / paquete completo | 0.0125 s (n = 40) / 6.36 s (n = 12) | 0.0004–0.0128 s / 5.04–7.69 s | automático | mediana ≤ 15 s |

La meta de sustento se cumple con la estimación puntual (96.7 %), no con el límite inferior de Wilson (83.3 %); el criterio oficial es la estimación puntual (protocolo, sección 4).

---

## 10 · Evaluación reproducible

```bash
poetry run python -m scripts.reproducir --verificar  # reconstruye desde data/raw/ y compara los SHA-256 con el manifest; sale con 1 si algo difiere (≈ 1 min)
poetry run python -m eval.run_benchmark --split dev  # benchmark de desarrollo → outputs/benchmark/ y outputs/metricas.json
poetry run python -m eval.run_benchmark --archivo <ruta-al-archivo.jsonl> --salida <carpeta-de-salida>   # evaluación reservada del jurado
```

- **Evaluación reservada:** el runner solo lee el archivo, solo escribe en la carpeta de salida y funciona sin internet ni clave (la Consulta no usa LLM). Formato y salidas: sección «Evaluación reservada» del [`README.md`](../README.md) y [`benchmark/README.md`](../benchmark/README.md). La validez de sustento requiere que una persona complete `revision_sustento.csv` y luego `poetry run python -m eval.sustento --archivo … --salida …`.
- **Qué se reproduce:** el snapshot reconstruido desde `raw/`, las tablas de `senales.duckdb`, los informes, las fichas y las métricas, comparados por hash ([`docs/reproducibilidad.md`](reproducibilidad.md)).
- **Qué no se reproduce:** el texto del LLM. Se reproduce solo desde `data/cache_llm/`; con temperatura 0 y semilla 0 DeepSeek no es estable entre llamadas, por eso nunca se regenera al reproducir. RSS y GDELT no se versionan: en un clon sin esos crudos se usa el `processed/` versionado y se declara como limitación. Lo que depende del reloj o de la máquina (marcas de tiempo, latencias de la Consulta) se excluye del hash con su motivo.

---

## 11 · Limitaciones

- **Ranking:** Precision@5 es exploratoria (5 temas, 1 fecha de corte, sin especialista editorial): sistema 0/5 frente a 1/5 del orden por fecha, con IC solapados. Quien eligió los temas conocía la selección y el resultado anteriores: no es una selección ciega e independiente.
- **Ahorro de tiempo: no medido** (0 pruebas, [`docs/prueba_tiempo.md`](prueba_tiempo.md)). El pitch presenta el valor operativo como **hipótesis de valor**: pasar de fuentes dispersas a un tema investigable con evidencia citada y vacíos explícitos. No se infiere audiencia, rentabilidad ni reducción de riesgo.
- **Umbral de la Consulta con poco margen:** con 0.840 la abstención en preguntas fuera del corpus es 24/30 = 80 % (cumple la meta justo); subirlo a 0.857 rechaza preguntas legítimas, por eso no se cambió ([`docs/consulta.md`](consulta.md)). Una pregunta muy genérica puede abstenerse.
- **La contradicción de CU-04 es sintética:** el snapshot real no tiene ninguna contradicción abierta; el caso de la demo está marcado SINTÉTICO y vive solo en `data/demo.duckdb`.
- **4 de 5 fichas con revisión provisional del asistente** (CASO-015, CASO-017, CASO-018, CASO-019). Solo CASO-016 lo revisó una persona. Por eso la página de métricas sigue marcada BORRADOR y la auditoría final ([`outputs/auditoria_final.md`](../outputs/auditoria_final.md)) da FALTA en S5-07 y P-05 (13 PASS, 2 FALTA, 10 no verificables automáticamente).
- **Clasificación sin ventaja demostrada** sobre palabras clave; temas con menos de 5 titulares etiquetados sin veredicto.
- **Benchmark de desarrollo pequeño** (40 consultas) y construido por el equipo; las reglas de la Consulta se redactaron viendo esas consultas, así que la abstención medida es optimista.
- **Cobertura de GDELT parcial:** las consultas vigentes tienen 0 días cubiertos por respuestas HTTP 429 sostenidas; las noticias de GDELT vienen de consultas anteriores con 4 días cubiertos por tema (`data/manifest.json`, `cobertura_efectiva`).
- **Borradores:** el validador rechaza el 22.1 % de las unidades generadas (33/149); el sistema prefiere una sección vacía a una inventada. La latencia del paquete editorial (n = 1) supera los 15 s.
- **Costo:** el contador sobreestima ≈ 2.6 × frente a la consola del proveedor (supuesto del proyecto); las cifras en USD son cota superior.
- **SBP:** datos versionados con riesgo aceptado y autorización pendiente (sección 6).
