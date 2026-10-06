# ⚖️ Opciones por etapa (sección 3 del reto)

Para cada etapa: lo que exige el PDF, las opciones evaluadas, la elegida y la decisión que la registra.
Las decisiones en estado **Propuesta** las confirma el equipo.

## 1 · Cargar
**PDF:** validar IDs, URLs, fechas, obligatorios y nulos; reporte de calidad (T01).

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| Validación | pandera · pydantic por fila · Great Expectations | pandera (tablas) + pydantic (JSON/GeoJSON) | D-19 |
| Extracción | gdeltdoc / wbgapi · requests directo · feedparser | feedparser (RSS) + requests directo (GDELT, BM, USGS) | D-24 |
| Fechas | Parser genérico · un parser por fuente | Un parser por fuente | E1-02 |
| Ruido | Borrar · marcar y excluir de la bandeja | Marcar con motivo, contar en el reporte | D-26 |
| Detección de ruido | Solo patrones · solo similitud · ambos | Patrones en YAML + similitud con prototipo de "noticia sobre Panamá" | E1-03b |

## 2 · Organizar
**PDF:** clasificar en 6 temas; agrupar noticias del mismo evento. Sección 8: al menos una capacidad de ML/NLP y un baseline.

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| Embeddings | multilingual-e5-small · paraphrase-multilingual-MiniLM · bge-m3 | e5-small, comparado con MiniLM | D-20 |
| Clasificación | 6 descripciones (A) · subtemas (B) · NLI zero-shot · LLM · regresión logística | Medir A y B; elegir con criterio fijado antes | D-21 |
| Procedencia | Guardar autor · nada · agencia y tipo de firma | Agencia y tipo de firma, sin nombre | D-32 |
| Descripción del RSS | No usar · mostrar · solo interna | Solo interna | D-31 |
| Límites entre temas | Criterio libre · guía con reglas de frontera | Guía única (ver Guía de temas) | D-27 a D-30 |
| Agrupación | Aglomerativo con umbral · HDBSCAN · pares con umbral (union-find) | Aglomerativo (coseno, promedio) + ventana de días | D-16 |
| Umbral | A ojo · calibrado con etiquetas | Calibrado | D-16 |
| Baseline | Palabras clave · Jaccard de tokens · ranking por fecha | Palabras clave (tema) + Jaccard (grupos) | E1-07 |

## 3 · Contextualizar
**PDF:** relacionar con datos oficiales; período, unidad y limitaciones; no forzar.

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| Vínculo tema → indicador | Tabla fija · similitud semántica · LLM | Tabla fija | D-05 |
| Temas sin indicador | Forzar el más parecido · declarar "sin dato oficial" | Declararlo | D-05 |
| Limitaciones | Solo año · nota fija por dato | Nota fija (anual, último año, revisable) | E1-09 |
| Nivel del vínculo | Por tema · por subtema | Por subtema, con motivo cuando no hay vínculo | D-34 |
| Eventos oficiales (USGS) | Etapa 3 · Etapa 1 | Etapa 1 | D-33 |

## 4 · Priorizar
**PDF:** puntaje con componentes; relevancia ≠ suficiencia de evidencia.

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| Componente I | v1.0 (con dato oficial) · v1.1 (sin dato oficial) · v1.2 (alcance del subtema + geográfico) | v1.2 | D-15, D-35 |
| Similitudes | Crudas · percentil en el snapshot | Percentil | D-35 |
| Componente E | Procedencias + oficial (v1.2) · + procedencia identificable (v1.3) | v1.3 | D-56 |
| Baseline del ranking | Ninguno · ranking por fecha | Ranking por fecha | D-56 |
| Acción recomendada | Matriz 2×2 · tabla 3×3 | Tabla 3×3 | D-35 |
| Urgencia U | Decaimiento lineal · exponencial | Lineal (más fácil de explicar) | D-06 |
| Pesos | Fijos del PDF · ajustables | Los del PDF, ajustables con versión y justificación | D-06 |

## 5 · Explicar
**PDF:** qué se reporta, quién, qué está respaldado, qué falta, acción recomendada.

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| Procedencias | Solo por medio · texto casi idéntico · + menciones de agencia | Texto casi idéntico + agencias, como estimación | E1-08 |
| Acción recomendada | LLM · reglas por cuadrante | Reglas por cuadrante | E1-10 |
| Nombre del medio | Dominio · tabla dominio → medio | Tabla en fuentes.json | E1-03 |
| Armado de la ficha | LLM · determinista | Determinista | D-36 |
| Qué se reporta | Síntesis del LLM · titular representativo | Titular más central + cobertura | E1-10b |
| A quién verificar | Nada · LLM · tabla por subtema | Tabla por subtema, como sugerencia | D-37 |
| Modalidades | Fichas separadas · ficha común configurable | Común | D-38 |

## 6 · Producir
**PDF:** borrador con citas por afirmación; hechos, declaraciones, inferencias e hipótesis.

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| LLM | Ollama local · DeepSeek · híbrido | Ollama con criterio de cambio | D-02 |
| Estructura | Una llamada · una por sección · afirmaciones primero | Afirmaciones primero + una llamada por sección | D-17, D-22 |
| Formato | Prompt + parseo · `format` JSON schema + pydantic | `format` + pydantic + un reintento | E1-12 |
| Hecho vs. declaración | Lo decide el LLM · regla fija | Regla fija | D-18 |
| Contradicciones | Reglas · NLI · LLM por pares | Reglas + LLM solo en pares candidatos | D-23 |
| Guion y copy | Sin reglas · reglas verificables | Marcadores visuales, rango de palabras, lista de palabras prohibidas | D-25 |
| Tipos de afirmación | Criterio del LLM · reglas por tipo | Reglas por tipo verificables | D-41 |
| Qué generar | Siempre todo · según la acción | Según la acción de la ficha | D-42 |
| Fuentes y verificaciones | LLM · copia de la ficha | Copia de la ficha | D-43 |
| Llamadas | 1 · 8 · agrupadas bajo demanda | 1 + 4, bajo demanda | D-44 |
| Comillas, fechas, traducciones | Sin control · reglas | Reglas en el validador | D-45 |

## 7 · Revisar
**PDF:** aceptación, corrección o descarte por una persona; ficha en Notion.

| Tema | Opciones | Elegida | Decisión |
|---|---|---|---|
| Almacenamiento | DuckDB · JSONL · Notion como base | DuckDB (fuente de verdad) + fichas.jsonl | E1-16 |
| Notion | Manual · importación CSV · API | Markdown + fila CSV con ID estable; API en Etapa 3 | D-50 |
| Corrección | Estado nuevo · acción con versión | Acción con versión revalidada | D-46, D-48 |
| Historial | Sobrescribir · solo agregar | Solo agregar | D-47 |
| Revisor | Login · lista | Lista, limitación declarada | D-49 |

## Transversal · Interfaz
**PDF:** web, dashboard o notebook, si muestra todo el recorrido.

| Opciones | Elegida | Decisión |
|---|---|---|
| Streamlit · Gradio · React + FastAPI · Jupyter | Streamlit | D-07 |
