# 🏠 Inicio del reto

**HackIAthon · Reto TVN Media · "De la señal a la decisión"**
Copiloto de inteligencia informativa y análisis de entorno con IA.

> Todo lo que produce este sistema es **borrador para revisión humana**. Nada se publica automáticamente.

## Equipo

| Rol | Responsable de | Integrante |
|---|---|---|
| Datos (D) | Ingesta, validación, catálogo, reglas, contextualización | _por definir_ |
| IA | Embeddings, agrupación, consultas, LLM, caché, métricas | _por definir_ |
| Producto (P) | Interfaz, revisión humana, Notion, pitch | _por definir_ |

## Modalidad

- **Principal:** editorial (TVN Media).
- **Extensión:** bancaria, sobre el mismo núcleo. Se activa en la Etapa 2, después de que la editorial pase T01–T10.

## Problema

Un equipo editorial debe revisar fuentes dispersas, eliminar duplicados, ubicar los hechos en contexto y preparar piezas con rapidez. La circulación de una noticia no equivale a su confirmación: varios medios pueden repetir una misma fuente. Un analista bancario enfrenta un problema similar al monitorear economía, logística, turismo, regulación y continuidad operativa.

## Usuarios

| Usuario | Escenario | Resultado útil |
|---|---|---|
| Editora de asignaciones (TVN) | 7:30 a. m., 20 minutos antes de la reunión de pauta | Agenda priorizada, ficha de investigación, preguntas pendientes y borradores por formato |
| Productor digital (TVN) | Adapta los temas aprobados a web y redes | Titulares propuestos, resumen web y copy social, sujetos a revisión |
| Analista de estudios económicos (banco comercial panameño genérico) | _Escenario por definir_ | Boletín de entorno, señales y preguntas para seguimiento |

## Objetivo

Demostrar que la IA puede transformar un corpus público en información accionable, con evidencia verificable, una priorización explicada y un flujo de revisión documentado en Notion.

**En una frase:** un sistema que nunca afirma más de lo que su evidencia permite, y lo demuestra cita por cita.

## Alcance

**Incluye:** ingesta de noticias y datos oficiales; normalización, búsqueda, clasificación, agrupación, faltantes y contradicciones; bandeja priorizada, ficha de evidencia, consultas en español y entregable por modalidad; registro en Notion.

**No incluye:** ver la página *Riesgos y ética → Fuera de alcance*.

## Criterios de éxito

| Métrica | Meta |
|---|---|
| Cobertura de citas | 100% de afirmaciones factuales con evidencia identificable |
| Validez de sustento | ≥90% (revisión humana de ≥30 afirmaciones) |
| Abstención correcta | ≥80% de consultas sin respuesta |
| Clasificación / agrupación | Macro-F1 o precisión/recall sobre etiquetas humanas |
| Utilidad del ranking | Precision@5 frente a la selección de un editor |
| Latencia | Mediana ≤15 s, reportando p95 |
| Pruebas de aceptación | T01–T10 |

Criterio cualitativo (sección 12): una persona de editorial pasa de fuentes dispersas a un tema investigable, con evidencia y un borrador responsable.

## Accesos

- **Demo:** _pendiente_
- **Repositorio GitHub:** _pendiente_
- **Versión de reglas activa:** v1.3

## Etapas del desarrollo

| Etapa | Contenido | Criterio para avanzar |
|---|---|---|
| 0 · Antes del evento | Preguntas a organizadores, Notion, datos, fixtures, benchmark, modelos | Notion accesible y datos listos |
| 1 · Obligatorio (editorial) | Flujo completo de 7 etapas con A + B | T01–T10 pasan y la demo funciona offline |
| 2 · Extensión bancaria | Configuración, boletín, validador de banca, CU-05 | Boletín pasa T09 |
| 3 · Mejoras | USGS, SBP, sincronización Notion, pesos editables, comparación de modelos | Solo si sobra tiempo |
| Cierre (protegido) | Fichas, métricas, pitch, ensayo offline | Último 10% del tiempo |

## Supuestos del equipo (D-74)

No dependemos de respuestas de la organización. Estos son los supuestos con los que avanzamos; si la organización responde algo distinto, se ajusta y se registra.

| Tema | Supuesto |
|---|---|
| Reglas y rúbrica | El PDF del reto es el reglamento |
| Duración | Se planifica para 48 h, con el plan de recortes para 24 h del cronograma |
| Snapshot | Lo construimos y congelamos nosotros (E0-04) |
| Ventana de noticias | La de la sección 6: 30 días antes de la extracción, ampliable a 90. El intervalo [2024-01-01, 2025-10-01) de la sección 7 es imposible de extraer hoy (GDELT cubre ~3 meses) y se documenta como inconsistencia |
| RSS de TVN | Se descarga a diario desde ya para acumular las 20 noticias mínimas |
| Benchmark | Construimos el de desarrollo (40). El reservado es del jurado |
| Persona editorial | No hay: revisa un integrante que no escribió el código; Precision@5, validez de sustento y prueba de tiempo se declaran exploratorias |
| Derechos de extractos de TVN | No verificados: solo metadatos; la descripción solo para uso interno, nunca se muestra ni se entrega |
| Preparación previa | Se hace todo antes del evento y se registra con fase *Preparación* |
| Notion | Workspace de la organización si existe; si no, uno propio compartido solo con el jurado |
| Banca parcial | Si no se completa, se presenta como extensión diseñada |

## Pendientes del equipo

1. Perfiles y nombres de los tres integrantes.
2. Escenario concreto del analista bancario.
3. Confirmar las decisiones propuestas: D-07, D-11, D-12, D-19, D-20, D-22, D-23 y D-24.
