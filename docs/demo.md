# Guion de la demo · 4 minutos (D-52)

El PDF pide, en 4 minutos de demo en vivo: **una consulta útil, una ficha con citas, un borrador y un caso de abstención**. Este guion los encadena
sobre el snapshot real, con los IDs que existen hoy. La app corre **local y sin internet**; Notion se abre en paralelo como respaldo.

```bash
poetry run streamlit run app.py              # snapshot (data/senales.duckdb)
.venv/bin/streamlit run app.py -- --demo    # (poetry run se come el «--» y no pasa --demo) base de demo (data/demo.duckdb, la crea C-06) y barra lateral con estos pasos
```

La barra lateral del modo demo lee la tabla de abajo: **mantén el formato** (`| m:ss–m:ss | pantalla | qué se hace | "qué se dice" | plan B |`).
La aplicación abre en **Cómo funciona** (D-131): qué hace, quién la usa, las tres modalidades, las siete etapas con lo que entra y sale de cada una (con su cuenta real) y las tres reglas de la casa. Las pantallas de la barra lateral siguen esa entrada, las siete etapas del reto (PDF sección 3: Cargar, Organizar, Contextualizar, Priorizar, Explicar, Producir, Revisar) y, aparte, la Consulta (D-128). Cada etapa muestra arriba el indicador de las siete (la actual resaltada, cada una con su salto), una guía de tres líneas (qué hace, cómo leerla y qué caso de uso demuestra) y, al pie, los botones «Etapa anterior» y «Siguiente».
Los atajos `?caso=<GRP-…|posición>` abren la ficha (5 · Explicar) directamente (ej. `http://localhost:8501/?caso=GRP-da35c3dead`).

## Recorrido cronometrado

| Tiempo | Pantalla (atajo) | Qué se hace | Qué se dice | Plan B |
|---|---|---|---|---|
| 0:00–0:15 | Cómo funciona → 1 · Cargar | Abrir en **Cómo funciona**: señalar la secuencia de siete etapas (qué entra, qué sale, cuánto hay) y las tres reglas de la casa; abrir **1 · Cargar** desde su tarjeta. Mostrar la arquitectura del prototipo (cada paso con su cuenta real), el ruido marcado (con su IC 95 %) y el reporte de carga | "Esta es la secuencia, de la señal a la decisión. Cargamos el snapshot; lo que no sirve se marca, no se borra." | Captura de Calidad |
| 0:15–1:00 | 4 · Priorizar | Señalar la versión de reglas y el corte del snapshot (hora de Panamá); abrir las 5 primeras filas: P, barras R·I·U·N·E, estado y acción. La #1 (`GRP-5e6531917f`) es **Alto + Insuficiente → Investigar ya** | "El puntaje ordena la atención; la evidencia dice si se puede trabajar. Son independientes." | Captura de Bandeja |
| 1:00–1:30 | 5 · Explicar `?caso=GRP-79f3183472` | Abrir *Quién lo reporta*: 20 titulares de 18 medios y **1 procedencia** (Xinhua + Big News Network) | "20 titulares, 18 medios, una sola procedencia: se cuenta una fuente independiente." | Ficha en Markdown (`python -m src.ficha --grupo GRP-79f3183472`) |
| 1:30–2:00 | Consulta | Preguntar «¿Cuál fue la inflación de Panamá en 2023?»; hacer clic en la cita `IND-PAN-FP.CPI.TOTL.ZG-2023 · valor` (valor con su unidad, **año del dato**, **fecha de extracción**, país, indicador y URL) | "Este dato es del Banco Mundial, anual, de 2023: el sistema no lo presenta como actual." | `python -m src.consulta "…"` |
| 2:00–2:40 | 5 · Explicar `?caso=GRP-da35c3dead` | Titular central, 3 medios, 3 procedencias, **Borrador opcional**; abrir *Qué está respaldado* y hacer clic en una cita `NOT-… · titulo_limpio` | "Cada línea respaldada lleva su cita ID + campo; un titular es una declaración de su medio, no un hecho." | Ficha en Markdown |
| 2:40–3:20 | 6 · Producir → 7 · Revisar | Paquete: cada sección dice a quién sirve («Para: Editor/a y periodista», «Productor/a digital», «Analista (banca)»); el borrador del grupo, leído de la caché (`data/cache_llm/`, sin red). Si una sección aparece vacía es porque el validador la rechazó: el sistema prefiere el vacío a inventar. Revisar: los cinco estados del reto, lo que la persona debe comprobar y el *Registro en Notion* (crea o actualiza la ficha) | "Todo es borrador: el estado máximo es «aprobado como borrador»." | Pantalla de Revisión |
| 3:20–4:00 | Consulta | Preguntar «¿Cuál fue el desempleo de Panamá en 2025?» → **abstención** con el último dato disponible (2024: 8.45 %) y qué haría falta | "Si no hay evidencia, se abstiene y dice qué falta." | `python -m src.consulta "…"` |

## Etapa 1 en vivo y prueba T01 (D-130)

En **1 · Cargar**, bajo la arquitectura (cada tarjeta 1 a 3 tiene un enlace que baja a su paso):

1. **Cargar el paquete congelado.** Muestra, paso a paso y con cifras reales: *fuentes* (archivos y registros leídos, SHA-256 contra `data/manifest.json` con ✓/✗, versión y corte), *validación* (las reglas de `config/carga.yaml` y los rechazos por tipo), *normalización* (transformaciones del manifest y cuentas), *almacenamiento* (tablas de la base de la corrida y `data/raw` / `data/processed` idénticos antes y después) y luego limpieza, clasificación, agrupación, contexto y puntaje (`--sin-llm`) sobre **esa** base. Al final compara con la base de la app (cuentas y huellas fila a fila). Tarda unos 3 s con la caché de embeddings caliente.
2. **Explorar esta corrida** cambia, solo en esa sesión, la base de todas las pantallas por la de la corrida; **Volver a la base de la app** lo deshace. Nunca se reemplaza `data/senales.duckdb`; la corrida vive en `<tmp>/hackiathon_corridas/<hora UTC>/` (fuera de git) y se conservan las últimas 5.
3. **Probar con un archivo propio (T01).** Descargar «ejemplo de noticias con errores», subirlo y pulsar *Validar mi archivo*: solo corre la etapa 1; cada fila sale «aceptada» o «rechazada» con su motivo (fecha inválida, ID duplicado, URL mal formada, campo obligatorio vacío) y los nulos quedan como nulos. El ejemplo de indicadores muestra que un `valor` nulo es válido. Nada de lo subido entra a la base de la app.

*Qué se dice:* "Esta es la etapa 1 corriendo ahora, no una captura: lee el paquete congelado, verifica sus hashes, valida, normaliza y guarda; y las etapas siguientes corren sobre esa carga y dan lo mismo que la base de la app." *Plan B:* captura de la pantalla, o `poetry run python -m scripts.reproducir --verificar`.

## CU-04 · contradicción (caso sintético, C-06)

El PDF pide para CU-04 «preguntar por una cifra inexistente o por una contradicción»: abstenerse o mostrar las versiones y la verificación pendiente. Las dos mitades se muestran así:

| Mitad de CU-04 | Caso | Origen | Cómo se abre |
|---|---|---|---|
| Cifra inexistente | Consulta «¿Cuál fue el desempleo de Panamá en 2025?» → abstención con el último dato (2024) | **Real** (snapshot) | Consulta (guion, 3:20–4:00) |
| Contradicción | `GRP-55e0774b97`: `SYN-C06-001` (Medio Sintético C: «36 tránsitos diarios») frente a `SYN-C06-002` (Medio Sintético D: «28 tránsitos diarios») | **SINTÉTICO** (`tests/fixtures/c06_contradiccion_demo.csv`) | `.venv/bin/streamlit run app.py -- --demo` y `http://localhost:8501/?caso=GRP-55e0774b97` |

El snapshot real no tiene ninguna contradicción abierta, así que ese caso se agrega a una **copia** de la base (`poetry run python -m scripts.preparar_demo` → `data/demo.duckdb`, fuera de git). Lleva la insignia **SINTÉTICO** en cada pantalla donde aparece (Organizar, Contextualizar, Priorizar, Explicar, Producir y Revisar) y en la exportación a Notion (Markdown y CSV). En 5 · Explicar la ficha muestra *Versión A* y *Versión B* con su medio, su ID y su cita, la etiqueta «posible contradicción, verificar» y, en *Qué falta comprobar*, la verificación pendiente; **nunca elige cuál es la verdadera** ni cierra el par. *Qué se dice:* "Dos medios dan cifras incompatibles: mostramos las dos versiones con su fuente y dejamos la verificación a una persona. Este caso es sintético y está marcado." La base de la demo **nunca** se usa para métricas: toda métrica se niega a leerla.

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
  - **Base y capturas de demo (C-06):** `data/demo.duckdb` y `scripts/preparar_demo.py` ya existen (caso sintético de CU-04, ver arriba). Todavía no existen `capturas_demo`, `verificar_offline` ni `buscar_casos` (`scripts/calentar_cache.py` ya existe, E1-14); sin `data/demo.duckdb`, `--demo` cae al snapshot y lo avisa.
  - **Banca (E2-01, D-132):** la modalidad Banca funciona en toda la interfaz. La base guarda los puntajes de una sola modalidad, así que al elegir Banca la app calcula (sin LLM, ~0,3 s) una copia de sesión en el directorio temporal y la usa en todas las pantallas; el archivo vivo no se toca y *Editorial* vuelve a él. Los borradores de banca se calientan sobre esa misma copia (ver la noche anterior).

## Riesgos

- **Consultas libres cortas pueden abstenerse todavía (umbral de similitud 0.840, D-134).** Con el umbral anterior (0.874) se abstenían
  «¿qué se reporta sobre la vacunación contra el VSR?» (0.850), «¿Qué pasó con MiBus?» (0.851), «la mina de cobre» (0.856) y «el Canal de
  Panamá» (0.856); con 0.840 se responden. Un tema que el corpus apenas toca sigue dando similitud baja (0.77 a 0.83 en seis consultas de
  prueba fuera del corpus, que se rechazan). El margen es estrecho (unos 0.015 a cada lado): si el jurado pregunta algo muy genérico,
  ensayar la explicación («el umbral prefiere abstenerse a responder mal»). La calibración original fue de E1-18 y D-134 la rehízo. Las tres consultas de este guion funcionan (inflación 2023,
  Singapur/Vietnam con 0.922 y desempleo 2025, que se abstiene a propósito).
- Los borradores dependen de la caché de E1-14 y de que E1-12 esté integrada; sin ellos, Paquete muestra el aviso y no inventa nada.

## Checklist

**La noche anterior**
- [ ] `poetry run python -m scripts.preparar_demo` (base de demo con el caso sintético de CU-04; C-06; sin red ni LLM, ~15 s)
- [ ] `poetry run python -m scripts.calentar_cache` (borradores en caché, E1-14; volver a correrlo tras cambiar prompt, modelo o validador) y `--verificar`
- [ ] Borradores de **banca** en caché (D-132; con red): la base viva tiene los puntajes de editorial, así que se calienta sobre la copia de sesión:
  ```bash
  BANCA=$(poetry run python -c "from src.corrida import base_de_modalidad; from src.configuracion import RAIZ; print(base_de_modalidad(RAIZ/'data'/'senales.duckdb','banca'))" 2>/dev/null | tail -1)
  poetry run python -m scripts.calentar_cache --modalidad banca --base "$BANCA"             # genera (con red)
  poetry run python -m scripts.calentar_cache --modalidad banca --base "$BANCA" --verificar # sin red
  ```
- [ ] `poetry run python -m scripts.capturas_demo` (capturas de respaldo; C-06)
- [ ] Las fichas exportadas y actualizadas en Notion (E1-16)
- [ ] Ensayo completo cronometrado (≤ 4:00)

**30 minutos antes**
- [ ] Wi-Fi apagado
- [ ] `poetry run python -m scripts.verificar_offline` en verde (C-06)
- [ ] `.venv/bin/streamlit run app.py -- --demo` abierto en «Cómo funciona», y recorridas una vez las 7 etapas: la primera carga tarda 15–20 s (carga el modelo de embeddings) y un clic hecho mientras arriba a la derecha dice «Running» se pierde
- [ ] Notion abierto en *Presentación al jurado*
- [ ] Con el Wi-Fi apagado (T10) los borradores salen **solo de la caché** (E1-14, calentada la noche anterior): DeepSeek es el único proveedor de generación (D-94/D-95) y no hay modelo local que arrancar
