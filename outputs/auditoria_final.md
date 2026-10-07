# Auditoría final · condiciones previas (C-07)

Generada el 2026-10-07T23:30:12Z desde el commit `f85e425` con `poetry run python -m scripts.auditoria_final`. PASS: 9 · FALTA: 6 · NO VERIFICABLE AUTOMÁTICAMENTE: 10.

| ID | Requisito | Estado | Depende de |
|---|---|---|---|
| S5-01 | URL de Notion accesible al jurado al cierre | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-05 |
| S5-02 | Plan con al menos 8 tareas y 3 decisiones justificadas | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-05 |
| S5-03 | Registro durante la ejecución, no solo un resumen final | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-05 |
| S5-04 | Catálogo completo de las fuentes utilizadas (cada fuente del manifest, con licencia/condiciones) | **PASS** | — |
| S5-05 | Al menos 5 fichas trazables, incluyendo un caso sin evidencia suficiente | **PASS** | C-01 |
| S5-06 | Matriz de los 10 casos de prueba, todos en «Pasa» | **FALTA** | C-04, E2-02 |
| S5-07 | Métricas de la ejecución final: página generada del commit vigente, sin borrador ni juicios provisionales | **FALTA** | C-09, C-10 |
| S5-08 | Pitch de 10 minutos presentado desde Notion | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-03, C-04 |
| S10-01 | Prototipo ejecutable y demo reproducible sin fuente en vivo | **FALTA** | C-06, C-04 |
| S10-02 | README con instalación, comando de ejecución, pruebas y evaluación reservada | **PASS** | — |
| S10-03 | .env.example solo con nombres de variables, sin valores en las claves y sin nada que parezca un secreto | **PASS** | — |
| S10-04 | Dependencias fijadas | **PASS** | — |
| S10-05 | Archivo LICENSE para el código (spec C-07) | **FALTA** | decisión del equipo |
| S10-06 | Repositorio con acceso del jurado (privado con colaboradores, o público) | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-05 |
| S10-07 | Espacio Notion con los artefactos de la sección 5 y la presentación final (PDF de respaldo opcional) | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-03, C-05, C-08 |
| S10-08 | Instalación limpia en otra máquina: git clone, poetry install, comando de ejecución y pytest | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-04 |
| S10-09 | Checklist de admisión y autoevaluación con la rúbrica completos | **NO VERIFICABLE AUTOMÁTICAMENTE** | C-08 |
| S10-10 | Paquete de datos redistribuible: snapshot, diccionario, manifest, licencias, benchmark dev, sin campos restringidos | **PASS** | — |
| S10-11 | SBP (D-116): autorización escrita o CSV retirado si la entrega es pública | **NO VERIFICABLE AUTOMÁTICAMENTE** | decisión del dueño |
| P-01 | Sin secretos en historial, archivos, capturas ni exportaciones | **FALTA** | C-11 |
| P-02 | Toda afirmación de fichas.jsonl y de las exportaciones pasa el validador; ninguna cita falsa | **PASS** | C-01 |
| P-03 | Ninguna acción, botón o estado «publicar» | **PASS** | — |
| P-04 | Nada con redistribución restringida, ni bases de datos de la sesión, ni el benchmark reservado en el repositorio (D-72) | **PASS** | — |
| P-05 | Los juicios que exige una persona (sustento, Precision@5, revisión editorial) los hizo una persona (D-85, D-101) | **FALTA** | C-09 |
| P-06 | Reproducibilidad de punta a punta (hashes del manifest) | **NO VERIFICABLE AUTOMÁTICAMENTE** | — |

## Evidencia y cómo verificar

### S5-01 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** URL de Notion accesible al jurado al cierre
- **Evidencia:** Depende del acceso de la cuenta del jurado; no hay URL ni token de Notion en el repo.
- **Cómo verificar o corregir:** Abrir la URL del espacio en una ventana privada y con la cuenta del jurado.

### S5-02 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Plan con al menos 8 tareas y 3 decisiones justificadas
- **Evidencia:** Local: 44 specs en specs/ (una por tarea). El conteo real vive en las bases Backlog y Decisiones de Notion.
- **Cómo verificar o corregir:** En Notion: Backlog ≥ 8 filas y Decisiones ≥ 3 con contexto, opciones y justificación.

### S5-03 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Registro durante la ejecución, no solo un resumen final
- **Evidencia:** Las bases Bitácora y Decisiones con Fase = Evento.
- **Cómo verificar o corregir:** En Notion: filtrar Bitácora y Decisiones por Fase = Evento y comprobar fechas repartidas durante el evento.

### S5-04 · PASS

- **Requisito:** Catálogo completo de las fuentes utilizadas (cada fuente del manifest, con licencia/condiciones)
- **Evidencia:** outputs/catalogo.csv: 4 fuentes; fuentes del manifest (data/manifest.json): ['banco_mundial', 'gdelt', 'sbp', 'tvn_rss', 'usgs']; sin nombre de catálogo en la configuración: ninguna; sin catalogar: ninguna; sin licencia: ninguna.
- **Cómo verificar o corregir:** poetry run python -m scripts.catalogo

### S5-05 · PASS

- **Requisito:** Al menos 5 fichas trazables, incluyendo un caso sin evidencia suficiente
- **Evidencia:** outputs/fichas_trazables/trazabilidad.json: 5 fichas, todo_ok=True, insuficientes=['CASO-002', 'CASO-008', 'CASO-007']. Aviso: juicio_humano=False (revisión provisional hasta C-09).
- **Cómo verificar o corregir:** poetry run python -m scripts.fichas_trazables

### S5-06 · FALTA

- **Requisito:** Matriz de los 10 casos de prueba, todos en «Pasa»
- **Evidencia:** outputs/pruebas.csv: 10 filas; faltan ninguna; no pasan: {'T09': 'Pendiente', 'T10': 'Pendiente'}.
- **Cómo verificar o corregir:** poetry run python -m eval.reporte_pruebas (tras terminar E2-02/C-04 para T09 y T10)

### S5-07 · FALTA

- **Requisito:** Métricas de la ejecución final: página generada del commit vigente, sin borrador ni juicios provisionales
- **Evidencia:** outputs/pagina_metricas.md (commit b4dc6ca): 10 archivos de ['src', 'eval', 'config', 'prompts', 'data/processed'] cambiaron desde el commit b4dc6ca (p. ej. ['config/fichas_trazables.yaml', 'config/notion.yaml', 'config/revision.yaml']): regenerar las métricas; la página sigue marcada «BORRADOR»; hay métricas con juicio PROVISIONAL (D-101)
- **Cómo verificar o corregir:** Tras C-09 y C-10: correr los eval/ y `poetry run python -m scripts.pagina_metricas`.

### S5-08 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Pitch de 10 minutos presentado desde Notion
- **Evidencia:** No hay artefacto local que lo demuestre; se presenta en vivo desde Notion.
- **Cómo verificar o corregir:** Ensayo cronometrado desde la página de Notion (sin PDF ni PowerPoint) con enlaces al prototipo y a GitHub.

### S10-01 · FALTA

- **Requisito:** Prototipo ejecutable y demo reproducible sin fuente en vivo
- **Evidencia:** Faltan: ['data/demo.duckdb', 'scripts/verificar_offline.py']
- **Cómo verificar o corregir:** poetry run python -m scripts.verificar_offline

### S10-02 · PASS

- **Requisito:** README con instalación, comando de ejecución, pruebas y evaluación reservada
- **Evidencia:** README.md: encabezados 10; secciones que faltan: ninguna.
- **Cómo verificar o corregir:** Editar README.md

### S10-03 · PASS

- **Requisito:** .env.example solo con nombres de variables, sin valores en las claves y sin nada que parezca un secreto
- **Evidencia:** .env.example: 5 variables; claves con valor: ninguna; coincidencias con patrones de secreto: ninguna.
- **Cómo verificar o corregir:** Dejar vacíos los valores de *_KEY, *_TOKEN, *_SECRET y *_PASSWORD; el valor real va en local.env.

### S10-04 · PASS

- **Requisito:** Dependencias fijadas
- **Evidencia:** poetry.lock presente.
- **Cómo verificar o corregir:** poetry lock

### S10-05 · FALTA

- **Requisito:** Archivo LICENSE para el código (spec C-07)
- **Evidencia:** No existe ninguno de ['LICENSE', 'LICENSE.md', 'LICENSE.txt']; el README dice «licencia pendiente de decisión del equipo».
- **Cómo verificar o corregir:** El equipo elige la licencia y agrega LICENSE.

### S10-06 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Repositorio con acceso del jurado (privado con colaboradores, o público)
- **Evidencia:** La visibilidad y los colaboradores viven en GitHub.
- **Cómo verificar o corregir:** `gh repo view DEVHUBPTY/HackAIthon --json visibility` y comprobar que el jurado figura como colaborador.

### S10-07 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Espacio Notion con los artefactos de la sección 5 y la presentación final (PDF de respaldo opcional)
- **Evidencia:** Solo se ve en Notion.
- **Cómo verificar o corregir:** Recorrer el índice del espacio con la lista de la sección 5.

### S10-08 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Instalación limpia en otra máquina: git clone, poetry install, comando de ejecución y pytest
- **Evidencia:** Requiere otra máquina.
- **Cómo verificar o corregir:** En una máquina sin el repo: seguir README.md y correr `poetry run pytest -v`.

### S10-09 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Checklist de admisión y autoevaluación con la rúbrica completos
- **Evidencia:** Viven en Notion.
- **Cómo verificar o corregir:** Revisar la página de autoevaluación contra la rúbrica de 100 puntos.

### S10-10 · PASS

- **Requisito:** Paquete de datos redistribuible: snapshot, diccionario, manifest, licencias, benchmark dev, sin campos restringidos
- **Evidencia:** entrega/datos: checksums correctos y sin material prohibido.
- **Cómo verificar o corregir:** poetry run python -m scripts.empaquetar_datos

### S10-11 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** SBP (D-116): autorización escrita o CSV retirado si la entrega es pública
- **Evidencia:** El CSV se incluye en el paquete; autorización escrita de la SBP: pendiente de pedir (docs/fuentes.md). Decisión del dueño según la visibilidad.
- **Cómo verificar o corregir:** Si el repo o el paquete son públicos: pedir la autorización o poner paquete.sbp.incluir: false y retirar data/processed/sbp_series.csv.

### P-01 · FALTA

- **Requisito:** Sin secretos en historial, archivos, capturas ni exportaciones
- **Evidencia:** Pendiente C-11: no existe outputs/auditoria_secretos.json (escaneo del historial de git, capturas y exportaciones). escaneo rápido de 443 archivos versionados: sin coincidencias; local.env/.env versionados: no.
- **Cómo verificar o corregir:** Correr el escaneo de C-11 y guardar su resultado.

### P-02 · PASS

- **Requisito:** Toda afirmación de fichas.jsonl y de las exportaciones pasa el validador; ninguna cita falsa
- **Evidencia:** outputs/fichas.jsonl: 8 fichas (CASO-001, CASO-002, CASO-003, CASO-004, CASO-005, CASO-006, CASO-007, CASO-008); re-verificadas con el validador contra data/senales.duckdb: 8 de 8; exportaciones revisadas: 6 archivos; problemas: ninguno.
- **Cómo verificar o corregir:** poetry run python -m scripts.fichas_trazables --casos; poetry run python -m src.ficha --formato jsonl

### P-03 · PASS

- **Requisito:** Ninguna acción, botón o estado «publicar»
- **Evidencia:** config/revision.yaml: estados ['nuevo', 'en revisión', 'requiere evidencia', 'aprobado como borrador', 'descartado']; con «publicar»: ninguno; etiquetas: ninguna; botones en app.py: ninguno.
- **Cómo verificar o corregir:** Revisar a mano la app antes de cerrar.

### P-04 · PASS

- **Requisito:** Nada con redistribución restringida, ni bases de datos de la sesión, ni el benchmark reservado en el repositorio (D-72)
- **Evidencia:** `git ls-files` (443 archivos): rutas restringidas (['data/raw/rss_tvn/', 'data/raw/gdelt/', 'data/raw/sbp/']) versionadas: ninguna; bases ['data/demo.duckdb', '*.duckdb', '*.duckdb.wal'] versionadas: ninguna; benchmark reservado versionado: ninguno.
- **Cómo verificar o corregir:** git rm --cached <ruta>

### P-05 · FALTA

- **Requisito:** Los juicios que exige una persona (sustento, Precision@5, revisión editorial) los hizo una persona (D-85, D-101)
- **Evidencia:** fichas trazables: revisión provisional del asistente; página de métricas: sustento y Precision@5 PROVISIONAL
- **Cómo verificar o corregir:** Una persona rehace el juicio y se regenera (C-09).

### P-06 · NO VERIFICABLE AUTOMÁTICAMENTE

- **Requisito:** Reproducibilidad de punta a punta (hashes del manifest)
- **Evidencia:** Hashes registrados en el manifest: sí. No se corrió aquí (≈ 1 min).
- **Cómo verificar o corregir:** poetry run python -m scripts.reproducir --verificar, o esta auditoría con --reproducir (restaurar outputs/metricas.json si solo cambió el tiempo).
