# Specs de tareas

Cada spec sigue el formato **Objetivo · Punteros de contexto · Restricciones · Listo cuando**.
Para usar una: abre Claude Code y escribe *"Lee specs/<ID>.md y propón un plan"*.

## Specs disponibles

| ID | Tarea | Rol | Depende de | Spec |
|---|---|---|---|---|
| E0-03 | Repo base | IA | — | [`E0-03.md`](E0-03.md) |
| E0-04 | Extracción de datos y manifest | D | E0-01 | [`E0-04.md`](E0-04.md) |
| E0-05 | Fixtures sintéticos | D | — | [`E0-05.md`](E0-05.md) |
| E0-06 | Benchmark de desarrollo | Todos (IA coordina) | E0-04 | [`E0-06.md`](E0-06.md) |
| E0-07 | Elección del modelo local | IA | — | [`E0-07.md`](E0-07.md) |
| E0-09 | Exploración de una muestra real | D | E0-04 | [`E0-09.md`](E0-09.md) |
| E1-02 | Carga, validación y reporte de calidad | D | E0-04 | [`E1-02.md`](E1-02.md) |
| E1-03 | Normalización, almacenamiento y diccionario | D | E1-02 | [`E1-03.md`](E1-03.md) |
| E1-03b | Limpieza de titulares y filtro de ruido | D | E1-03 | [`E1-03b.md`](E1-03b.md) |
| E1-04 | Catálogo de datos para Notion | D | E1-03 | [`E1-04.md`](E1-04.md) |
| E1-05 | Configuración y reglas v1.3 | D | E0-09 | [`E1-05.md`](E1-05.md) |
| E1-06 | Herramienta de etiquetado humano | IA (construye) · Todos (etiquetan) | E1-03b | [`E1-06.md`](E1-06.md) |
| E1-07 | Embeddings, clasificación y baseline | IA | E1-03b, E1-05 | [`E1-07.md`](E1-07.md) |
| E1-08 | Agrupación por evento y procedencias independientes | IA | E1-07 | [`E1-08.md`](E1-08.md) |
| E1-09 | Contextualización con el Banco Mundial | D | E1-05, E1-08 | [`E1-09.md`](E1-09.md) |
| E1-09b | Vínculo con eventos sísmicos de USGS | D | E1-08 | [`E1-09b.md`](E1-09b.md) |
| E1-10 | Puntaje, estado de evidencia, vacíos y contradicciones | D + IA | E1-08, E1-09, E1-09b | [`E1-10.md`](E1-10.md) |
| E1-10b | Ficha de evidencia (común a ambas modalidades) | D + P | E1-10 | [`E1-10b.md`](E1-10b.md) |
| E1-11 | Consulta en español con abstención | IA | E1-07 | [`E1-11.md`](E1-11.md) |
| E1-12 | Proveedor LLM y generación del paquete editorial | IA | E1-10 | [`E1-12.md`](E1-12.md) |
| E1-13 | Validador de citas | D + IA | E1-12 | [`E1-13.md`](E1-13.md) |
| E1-14 | Caché y modo offline | IA | E1-12 | [`E1-14.md`](E1-14.md) |
| E1-15 | Interfaz Streamlit | P | E1-10b | [`E1-15.md`](E1-15.md) |
| E1-16 | Revisión humana, versiones y exportación a Notion | P | E1-15, E1-10b | [`E1-16.md`](E1-16.md) |
| E1-20 | Reproducibilidad de punta a punta | IA + D | E1-18 | [`E1-20.md`](E1-20.md) |
| E2-02 | Boletín de entorno bancario | IA | E2-01 | [`E2-02.md`](E2-02.md) |
| E1-17 | Suite T01–T10 y reporte de pruebas | Todos | E1-16 | [`E1-17.md`](E1-17.md) |
| E1-18 | Benchmark y métricas | IA | E0-06, E1-14 | [`E1-18.md`](E1-18.md) |
| E1-19 | Precision@5 y prueba de tiempo | P | E1-16 | [`E1-19.md`](E1-19.md) |
| E3-02 | Fuente D · Series agregadas de la SBP | D | E2-03 | [`E3-02.md`](E3-02.md) |
| C-06 | Casos de demostración por caso de uso | P + D | E1-16 | [`C-06.md`](C-06.md) |
| C-07 | Paquete de entrega y auditoría final | D + P | C-06 | [`C-07.md`](C-07.md) |

## Tareas humanas (sin spec)

| ID | Tarea | Rol | Tipo |
|---|---|---|---|
| E0-01 | Enviar preguntas a los organizadores | P | Humana, sin spec |
| E0-02 | Crear espacio Notion y probar acceso del jurado | P | Humana, sin spec |
| E1-01 | Completar Inicio del reto y registrar decisiones | P | Humana, sin spec |

## Pendientes de spec

E2-01, E2-03, Etapa 3 y Cierre (salvo C-06 y C-07): se escriben al llegar al punto de corte de la Etapa 1, con lo aprendido.
Usa `_plantilla.md`.
