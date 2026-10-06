# Cronograma del evento (sección 11 · D-73)

Tramos del PDF convertidos a horas. **Ajustar a la fecha y duración definitivas.**
Regla del PDF: *limitarse a una modalidad y un recorrido convincente antes de añadir funcionalidades.*

## Tramos en horas

| Tramo | % | Evento de 48 h | Evento de 24 h | Evidencia en Notion |
|---|---|---|---|---|
| **Inicio** | 15 % | 0 – 7 h | 0 – 3,5 h | Inicio del reto completo · decisiones confirmadas con fase *Evento* · accesos verificados |
| **Datos y diseño** | 20 % | 7 – 17 h | 3,5 – 8,5 h | Catálogo con hash · etiquetas · baseline · reglas v1.3 |
| **Construcción** | 40 % | 17 – 36 h | 8,5 – 18 h | Decisiones y Bitácora cada 2 h |
| ↳ **Punto de corte** | 60 % | **hora 29** | **hora 14,5** | Decisión registrada: ¿se activa banca? |
| **Pruebas** | 15 % | 36 – 43 h | 18 – 21,5 h | T01–T10 · benchmark · fallos y correcciones |
| **Cierre** | 10 % | 43 – 48 h | 21,5 – 24 h | Fichas · métricas · pitch · ensayo offline · acceso al repo |

## Qué hace cada área en cada tramo

Las columnas son **áreas de trabajo**, no personas: el equipo (David Fen, Javier Acosta, Juan Zhou) hace de todo y el responsable de cada tarea está en el Backlog de Notion.

| Tramo | Datos (D) | IA | Producto (P) |
|---|---|---|---|
| **Inicio** | Verificar el snapshot congelado con `validar_snapshot` y registrar las decisiones con fase *Evento* | Verificar entorno, Ollama y modelos con `scripts.probar_llm` (E0-07); `verificar_offline` llega con C-06 | Confirmar usuario, modalidad y alcance · accesos de Notion y del jurado (E1-01) |
| **Datos y diseño** | Carga, normalización, limpieza, catálogo (E1-02 a E1-04) · reglas y configuración (E1-05) | Ajustes con lo aprendido en la exploración (E0-09) y el benchmark (E0-06), ya preparados antes | Herramienta de etiquetado y revisión humana de las etiquetas que propone el asistente (E1-06, D-85) · plantilla de ficha en Notion |
| **Construcción** | Contexto, sismos, puntaje y estado de evidencia (E1-09, E1-09b, E1-10) | Embeddings, clasificación, agrupación, consulta, LLM, validador, caché (E1-07, E1-08, E1-11 a E1-14) | Ficha, interfaz, revisión y exportación (E1-10b, E1-15, E1-16) |
| ↳ **Después del corte** | Apoyo a pruebas | Sigue con lo pendiente | **Banca** (E2-01 a E2-03), solo si se cumplió el criterio |
| **Pruebas** | T01, T03, T04 · reproducibilidad (E1-20) | Benchmark y métricas (E1-18) · T06, T07 | Precision@5 y prueba de tiempo (E1-19) · registrar fallos en Notion |
| **Cierre** | Paquete de datos y auditoría final (C-07) | Página de métricas (C-02) | Fichas (C-01, C-06), pitch (C-03), ensayo (C-04), accesos (C-05), autoevaluación (C-08) |

## Punto de corte (60 % del tiempo)

**Se activa la extensión bancaria solo si**, en ese momento:
- El flujo editorial corre **de punta a punta** con datos reales (carga → bandeja → ficha → borrador → revisión).
- Pasan al menos **T01, T02, T04, T06 y T07**.

Si no se cumple: banca queda como "diseñada" (`modalidad_banca.yaml` y ficha con acciones bancarias) y todo el equipo sigue con la editorial. La decisión se registra en Notion con fase *Evento*.

## Si el evento es de 24 horas

Se recorta, en este orden:
1. Toda la **Etapa 3** (USGS ya está en la Etapa 1; SBP, sincronización con Notion, pesos editables y comparación de modelos quedan fuera).
2. **Banca**, salvo que el punto de corte se cumpla con holgura.
3. **Precision@5 en un solo corte** y prueba de tiempo con el n mínimo, declaradas exploratorias.
4. La opción B de clasificación se mide solo si sobra tiempo; si no, se usa A.

## Preparación previa (D-74)
La Etapa 0 completa (repo, snapshot propio, RSS diario, fixtures, benchmark de desarrollo, modelos, exploración) se hace **antes** del evento y queda registrada con fase *Preparación*. El evento arranca verificando, no construyendo desde cero.

**Estado:** el evento ya empezó (fase *Evento* en Notion). Lo que de la Etapa 0 se cierre durante el evento se registra con fase *Evento* (D-58 separa el registro por fase).

## Ritmo de registro (D-58)
- Cada decisión, al tomarla. Cada prueba fallida, antes de corregirla.
- Bitácora al menos **cada 2 horas**.
- Al cerrar cada tramo, una entrada de Bitácora con lo logrado y lo pendiente.

## Prueba fallida y corrección
El jurado pide ver *"una decisión, una prueba fallida y su corrección"*. Durante las pruebas **habrá fallos**: registrarlos con honestidad (estado *Falla* → *Corregido*) es justamente la evidencia que se pide. No hay que ocultarlos ni corregirlos antes de anotarlos.
