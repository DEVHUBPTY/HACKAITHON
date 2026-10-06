# ✅ Checklist de admisión (sección 5)

Si falta cualquiera de estos puntos, **no se admite la entrega** hasta corregirlo dentro del plazo.

| # | Evidencia mínima | Dónde | Responsable | Tarea | Estado |
|---|---|---|---|---|---|
| 1 | URL de Notion accesible al jurado al cierre | Configuración de compartir | P | E0-02 · C-05 | ⬜ |
| 2 | Plan con ≥ 8 tareas | Plan y decisiones → Backlog | P | E1-01 | ⬜ |
| 3 | ≥ 3 decisiones justificadas | Plan y decisiones → Decisiones | Todos | E1-01 | ⬜ |
| 4 | Registro **durante** la ejecución | Bitácora y Decisiones con *Fase = Evento* | Todos | D-58 | ⬜ |
| 5 | Catálogo completo de las fuentes usadas (con hash) | Catálogo de datos | D | E1-04 | ⬜ |
| 6 | ≥ 5 fichas trazables | Casos y evidencias | P | C-01 · C-06 | ⬜ |
| 7 | Al menos una ficha sin evidencia suficiente | Casos y evidencias → CASO-004 | P | C-06 | ⬜ |
| 8 | Matriz con T01–T10 | Pruebas y métricas → Pruebas | Todos | E1-17 | ⬜ |
| 9 | Métricas de la ejecución final | Pruebas y métricas → Métricas | IA | C-02 | ⬜ |
| 10 | Pitch de 10 min presentado desde Notion | Presentación al jurado | P | C-03 | ⬜ |
| 11 | Las 8 secciones obligatorias presentes | Página raíz | P | E0-02 | ⬜ |

## Contenido exigido por sección (tabla de la sección 5)

| Sección | Contenido exigido | Dónde está | Estado |
|---|---|---|---|
| Inicio del reto | Equipo · modalidad · problema · usuario · alcance · criterios de éxito · accesos a demo y repositorio | Página *Inicio del reto* | ⬜ Faltan nombres y URLs |
| Plan y decisiones | Backlog · responsables · estados · cronología · decisiones técnicas o de producto | Backlog (Responsable, Estado, Fechas, vista Cronología) · Decisiones (propiedad Tipo) | ⬜ |
| Catálogo de datos | Fuente · URL · fecha de extracción · cobertura · campos · licencia · transformaciones · hash | Base *Catálogo de datos* | ⬜ Valores con los datos reales |
| Diseño de solución | Arquitectura · modelo de datos · reglas · modelos · prompts · versiones · límites | Secciones de *Diseño de solución* + base *Prompts* | ⬜ Completar modelos y versiones |
| Casos y evidencias | IDs · fuentes · puntaje desglosado · estado de evidencia · borrador · persona revisora | Base *Casos y evidencias* | ⬜ |
| Pruebas y métricas | Caso · entrada · esperado · observado · evidencia de ejecución · corrección | Base *Pruebas* + *Métricas* | ⬜ |
| Riesgos y ética | Privacidad · derechos · sesgos · ataques al agente · controles · fuera de alcance | Base *Riesgos* + *Fuera de alcance* | ⬜ |
| Presentación al jurado | Problema → solución → demo → IA y evidencias → resultados → límites → próximos pasos | Página *Presentación al jurado* | ⬜ Guion al final |

## Condiciones previas (sección 10)

| # | Condición | Estado |
|---|---|---|
| 12 | Demo ejecutable (C-04, C-07) | ⬜ |
| 13 | Fuentes declaradas (`scripts.auditoria_final`) | ⬜ |
| 14 | Ningún secreto en Notion, repositorio ni capturas (`scripts.auditoria_final`) | ⬜ |
| 15 | Sin citas falsas ni acciones prohibidas (`scripts.auditoria_final`) | ⬜ |

## Accesos y políticas (antes del evento)

- [ ] El paquete se importó en el workspace de la organización si existe; si no, en uno propio del equipo (D-74)
- [ ] Equipo con permiso de edición
- [ ] Jurado como invitado con permiso de ver y comentar, probado con una cuenta externa
- [ ] Espacio **no** publicado en la web

## Entregables obligatorios (sección 10)

| Entregable | Contenido | Tarea | Estado |
|---|---|---|---|
| Prototipo ejecutable | Flujo completo + demo sin fuente en vivo | Etapa 1 · C-04 | ⬜ |
| Repositorio GitHub con acceso al jurado | README, instalación, comando, `poetry.lock`, `.env.example`, pruebas, `LICENSE` | E0-03 · C-07 | ⬜ |
| Paquete de datos | Snapshot, diccionario, manifest, licencias, benchmark de desarrollo; solo metadatos y receta para fuentes restringidas | C-07 | ⬜ |
| Espacio Notion | Artefactos de la sección 5 + presentación final | Todo el proyecto | ⬜ |
| PDF de respaldo (opcional) | Exportación del espacio; nunca sustituto | C-07 | ⬜ |
