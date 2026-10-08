# Guion de la demo · 4 minutos (D-52)

El PDF pide, en 4 minutos de demo en vivo: **una consulta útil, una ficha con citas, un borrador y un caso de abstención**. Este guion los encadena
sobre el snapshot real, con los IDs que existen hoy. La app corre **local y sin internet**; Notion se abre en paralelo como respaldo.

```bash
poetry run streamlit run app.py              # snapshot (data/senales.duckdb)
poetry run streamlit run app.py -- --demo    # base de demo (data/demo.duckdb, la crea C-06) y barra lateral con estos pasos
```

La barra lateral del modo demo lee la tabla de abajo: **mantén el formato** (`| m:ss–m:ss | pantalla | qué se hace | "qué se dice" | plan B |`).
La aplicación abre en **Cómo funciona** (D-131): qué hace, quién la usa, las tres modalidades, las siete etapas con lo que entra y sale de cada una (con su cuenta real) y las tres reglas de la casa. Las pantallas de la barra lateral siguen esa entrada, las siete etapas del reto (PDF sección 3: Cargar, Organizar, Contextualizar, Priorizar, Explicar, Producir, Revisar) y, aparte, la Consulta (D-128). Cada etapa muestra arriba el indicador de las siete (la actual resaltada, cada una con su salto), una guía de tres líneas (qué hace, cómo leerla y qué caso de uso demuestra) y, al pie, los botones «Etapa anterior» y «Siguiente».
Los atajos `?caso=<GRP-…|posición>` abren la ficha (5 · Explicar) directamente (ej. `http://localhost:8501/?caso=GRP-da35c3dead`).

## Recorrido cronometrado

| Tiempo | Pantalla (atajo) | Qué se hace | Qué se dice | Plan B |
|---|---|---|---|---|
| 0:00–0:15 | Cómo funciona → 1 · Cargar | Abrir en **Cómo funciona**: señalar la secuencia de siete etapas (qué entra, qué sale, cuánto hay) y las tres reglas de la casa; abrir **1 · Cargar** desde su tarjeta. Mostrar la arquitectura del prototipo (cada paso con su cuenta real), el ruido marcado (con su IC 95 %) y el reporte de carga | "Esta es la secuencia, de la señal a la decisión. Cargamos el snapshot; lo que no sirve se marca, no se borra." | Captura de Calidad |
| 0:15–1:00 | 4 · Priorizar | Señalar la versión de reglas y el corte del snapshot (hora de Panamá); abrir las 5 primeras filas: P, barras R·I·U·N·E, estado y acción. La #1 (`GRP-84a6b3a04b`) es **Alto + Insuficiente → Investigar ya** | "El puntaje ordena la atención; la evidencia dice si se puede trabajar. Son independientes." | Captura de Bandeja |
| 1:00–1:30 | 5 · Explicar `?caso=GRP-79f3183472` | Abrir *Quién lo reporta*: 20 titulares de 18 medios y **1 procedencia** (Xinhua + Big News Network) | "20 titulares, 18 medios, una sola procedencia: se cuenta una fuente independiente." | Ficha en Markdown (`python -m src.ficha --grupo GRP-79f3183472`) |
| 1:30–2:00 | Consulta | Preguntar «¿Cuál fue la inflación de Panamá en 2023?»; hacer clic en la cita `IND-PAN-FP.CPI.TOTL.ZG-2023 · valor` (valor con su unidad, **año del dato**, **fecha de extracción**, país, indicador y URL) | "Este dato es del Banco Mundial, anual, de 2023: el sistema no lo presenta como actual." | `python -m src.consulta "…"` |
| 2:00–2:40 | 5 · Explicar `?caso=GRP-da35c3dead` | Titular central, 3 medios, 3 procedencias, **Borrador opcional**; abrir *Qué está respaldado* y hacer clic en una cita `NOT-… · titulo_limpio` | "Cada línea respaldada lleva su cita ID + campo; un titular es una declaración de su medio, no un hecho." | Ficha en Markdown |
| 2:40–3:20 | 6 · Producir → 7 · Revisar | Paquete: cada sección dice a quién sirve («Para: Editor/a y periodista», «Productor/a digital», «Analista (banca)»); el borrador del grupo, leído de la caché (`data/cache_llm/`, sin red). **Aviso:** `GRP-da35c3dead` quedó con `titulares`, `copy_digital` y `guion` vacíos tras recalentar la caché (X45; `docs/reproducibilidad.md`); la tarea E1-12b lo corrige. Revisar: los cinco estados del reto, lo que la persona debe comprobar y el *Registro en Notion* (crea o actualiza la ficha) | "Todo es borrador: el estado máximo es «aprobado como borrador»." | Pantalla de Revisión |
| 3:20–4:00 | Consulta | Preguntar «¿Cuál fue el desempleo de Panamá en 2025?» → **abstención** con el último dato disponible (2024: 8.45 %) y qué haría falta | "Si no hay evidencia, se abstiene y dice qué falta." | `python -m src.consulta "…"` |

## Etapa 1 en vivo y prueba T01 (D-130)

En **1 · Cargar**, bajo la arquitectura (cada tarjeta 1 a 3 tiene un enlace que baja a su paso):

1. **Cargar el paquete congelado.** Muestra, paso a paso y con cifras reales: *fuentes* (archivos y registros leídos, SHA-256 contra `data/manifest.json` con ✓/✗, versión y corte), *validación* (las reglas de `config/carga.yaml` y los rechazos por tipo), *normalización* (transformaciones del manifest y cuentas), *almacenamiento* (tablas de la base de la corrida y `data/raw` / `data/processed` idénticos antes y después) y luego limpieza, clasificación, agrupación, contexto y puntaje (`--sin-llm`) sobre **esa** base. Al final compara con la base de la app (cuentas y huellas fila a fila). Tarda unos 3 s con la caché de embeddings caliente.
2. **Explorar esta corrida** cambia, solo en esa sesión, la base de todas las pantallas por la de la corrida; **Volver a la base de la app** lo deshace. Nunca se reemplaza `data/senales.duckdb`; la corrida vive en `<tmp>/hackiathon_corridas/<hora UTC>/` (fuera de git) y se conservan las últimas 5.
3. **Probar con un archivo propio (T01).** Descargar «ejemplo de noticias con errores», subirlo y pulsar *Validar mi archivo*: solo corre la etapa 1; cada fila sale «aceptada» o «rechazada» con su motivo (fecha inválida, ID duplicado, URL mal formada, campo obligatorio vacío) y los nulos quedan como nulos. El ejemplo de indicadores muestra que un `valor` nulo es válido. Nada de lo subido entra a la base de la app.

*Qué se dice:* "Esta es la etapa 1 corriendo ahora, no una captura: lee el paquete congelado, verifica sus hashes, valida, normaliza y guarda; y las etapas siguientes corren sobre esa carga y dan lo mismo que la base de la app." *Plan B:* captura de la pantalla, o `poetry run python -m scripts.reproducir --verificar`.

## Pruebas dinámicas del jurado

| Pregunta | Dónde ir |
|---|---|
| "¿De dónde proviene esta cifra y de qué año es?" | Consulta de inflación 2023 → clic en la cita `IND-` → país, año del dato, valor con unidad, fecha de extracción (etiquetada) y URL |
| "Si cinco medios replican la misma agencia, ¿cuántas fuentes independientes cuentas?" | 2 · Organizar → abrir `GRP-79f3183472` (20 titulares, 18 medios, **1 procedencia**), o `?caso=GRP-79f3183472` → *Quién lo reporta* |
| "¿A qué dato oficial se relaciona esta noticia, y si no hay relación?" | 3 · Contextualizar → cada vínculo con período, unidad y limitaciones; los grupos sin vínculo dicen «no se fuerza la relación» |
| "¿Qué pasa sin evidencia o si una fuente intenta cambiar las instrucciones?" | Consulta de abstención (desempleo 2025) · casos con `sospechoso_inyeccion` se muestran como texto, no como instrucción |
| "Muéstrame en Notion una decisión, una prueba fallida y su corrección" | Notion → Decisiones → Pruebas (estado *Corregido*) |

## Estado de la pasada (E1-15)

Pasada ejecutada el 2026-10-06 con el snapshot real (`data/senales.duckdb`), sin navegador:

- **Verificado:** las 6 pantallas abren sin error (`AppTest`); las 58 fichas del snapshot se arman y se pintan (Ficha, Paquete y Revisión) sin errores;
  la consulta responde la de inflación y la de Singapur/Vietnam y se abstiene en la de desempleo 2025; el servidor
  (`streamlit run app.py --server.headless true`) responde HTTP 200 en `/`, `/_stcore/health` y `/?caso=GRP-da35c3dead`; durante la pasada
  completa no se intentó **ninguna** conexión que no fuera local (se bloquearon los `socket.connect` externos). El modelo de embeddings se carga de `models/` (`HF_HUB_OFFLINE=1`).
- **Falta una persona con navegador:** el cronometraje real del recorrido (≤ 4:00), el aspecto visual (barras, recuadros de cita, insignia),
  y apagar de verdad el Wi-Fi. La pasada con `AppTest` no mide tiempos de una persona ni lo que se ve.
- **Pendiente de otras tareas (la app ya lo prevé):**
  - **Borrador (E1-12 y E1-14):** ya integrado: la pestaña *Paquete* llama a `src.generacion.generar_paquete(id_grupo, modalidad, solo_cache=True)` y muestra lo guardado en `data/cache_llm/` (ver `docs/fallback.md`). 
    La integración se configura en `config/interfaz.yaml:generacion`.
  - **`CASO-00N` y revisión (E1-16):** ya integrado. Al abrir un grupo en *Revisión* nace su `CASO-00N`; `?caso=` acepta un `GRP-…`, un `CASO-…` o la posición en la bandeja. La revisión de la demo va a `data/revision_demo.duckdb`, aparte de la real.
  - **Base y capturas de demo (C-06):** `data/demo.duckdb`, `preparar_demo`, y `capturas_demo` todavía no existen (`scripts/calentar_cache.py` ya existe, E1-14); `--demo` cae al snapshot y lo avisa.
  - **Banca (E2-01):** la modalidad se puede elegir y se declara parcial (D-90); la bandeja bancaria llega con esa tarea.

## Riesgos

- **Consultas libres sobre temas de la bandeja pueden abstenerse (umbral de E1-11, 0.874).** Ejemplos medidos: «¿qué se reporta sobre la
  vacunación contra el VSR?» (la #2 de la bandeja) da similitud 0.848 y «¿Qué pasó con MiBus?» (la #3) da 0.851: ambas se abstienen.
  Las tres consultas de este guion sí funcionan (inflación 2023, Singapur/Vietnam con 0.922 y desempleo 2025, que se abstiene a propósito).
  Si el jurado pregunta libremente por un tema de la bandeja, lo probable es una abstención: ensayar la explicación («el umbral prefiere
  abstenerse a responder mal»). **Calibrar el umbral es de E1-18; no se toca en E1-15.**
- Los borradores dependen de la caché de E1-14 y de que E1-12 esté integrada; sin ellos, Paquete muestra el aviso y no inventa nada.

## Checklist

**La noche anterior**
- [ ] `poetry run python -m scripts.preparar_demo` (base de demo; C-06, aún no existe)
- [ ] `poetry run python -m scripts.calentar_cache` (borradores en caché, E1-14; volver a correrlo tras cambiar prompt, modelo o validador) y `--verificar`
- [ ] `poetry run python -m scripts.capturas_demo` (capturas de respaldo; C-06)
- [ ] Las fichas exportadas y actualizadas en Notion (E1-16)
- [ ] Ensayo completo cronometrado (≤ 4:00)

**30 minutos antes**
- [ ] Wi-Fi apagado
- [ ] `poetry run python -m scripts.verificar_offline` en verde (C-06)
- [ ] `poetry run streamlit run app.py -- --demo` abierto en Calidad
- [ ] Notion abierto en *Presentación al jurado*
- [ ] Con el Wi-Fi apagado (T10) los borradores salen **solo de la caché** (E1-14, calentada la noche anterior): DeepSeek es el único proveedor de generación (D-94/D-95) y no hay modelo local que arrancar
