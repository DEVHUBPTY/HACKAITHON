# Guion de la demo · 4 minutos (D-52)

El PDF pide, en 4 minutos de demo en vivo: **una consulta útil, una ficha con citas, un borrador y un caso de abstención**. Este guion los encadena
sobre el snapshot real, con los IDs que existen hoy. La app corre **local y sin internet**; Notion se abre en paralelo como respaldo.

```bash
poetry run streamlit run app.py              # snapshot (data/senales.duckdb)
poetry run streamlit run app.py -- --demo    # base de demo (data/demo.duckdb, la crea C-06) y barra lateral con estos pasos
```

La barra lateral del modo demo lee la tabla de abajo: **mantén el formato** (`| m:ss–m:ss | pantalla | qué se hace | "qué se dice" | plan B |`).
Los atajos `?caso=<GRP-…|posición>` abren la ficha directamente (ej. `http://localhost:8501/?caso=GRP-da35c3dead`).

## Recorrido cronometrado

| Tiempo | Pantalla (atajo) | Qué se hace | Qué se dice | Plan B |
|---|---|---|---|---|
| 0:00–0:15 | Calidad | Mostrar el ruido marcado (127 de 221 titulares, con su IC 95 %) y el reporte de carga | "Cargamos el snapshot; lo que no sirve se marca, no se borra." | Captura de Calidad |
| 0:15–1:00 | Bandeja | Señalar la versión de reglas y el corte del snapshot (hora de Panamá); abrir las 5 primeras filas: P, barras R·I·U·N·E, estado y acción. La #1 (`GRP-84a6b3a04b`) es **Alto + Insuficiente → Investigar ya** | "El puntaje ordena la atención; la evidencia dice si se puede trabajar. Son independientes." | Captura de Bandeja |
| 1:00–1:30 | Ficha `?caso=GRP-79f3183472` | Abrir *Quién lo reporta*: 20 titulares de 18 medios y **1 procedencia** (Xinhua + Big News Network) | "20 titulares, 18 medios, una sola procedencia: se cuenta una fuente independiente." | Ficha en Markdown (`python -m src.ficha --grupo GRP-79f3183472`) |
| 1:30–2:00 | Consulta | Preguntar «¿Cuál fue la inflación de Panamá en 2023?»; hacer clic en la cita `IND-PAN-FP.CPI.TOTL.ZG-2023 · valor` (valor, año, fecha y URL) | "Este dato es del Banco Mundial, anual, de 2023: el sistema no lo presenta como actual." | `python -m src.consulta "…"` |
| 2:00–2:40 | Ficha `?caso=GRP-da35c3dead` | Titular central, 3 medios, 3 procedencias, **Borrador opcional**; abrir *Qué está respaldado* y hacer clic en una cita `NOT-… · titulo_limpio` | "Cada línea respaldada lleva su cita ID + campo; un titular es una declaración de su medio, no un hecho." | Ficha en Markdown |
| 2:40–3:20 | Paquete → Revisión | Paquete: el borrador del grupo (**hoy muestra «Generación disponible cuando se integre E1-12»**; ver *Estado de la pasada*). Revisión: los cinco estados del reto y lo que la persona debe comprobar | "Todo es borrador: el estado máximo es «aprobado como borrador»." | Pantalla de Revisión |
| 3:20–4:00 | Consulta | Preguntar «¿Cuál fue el desempleo de Panamá en 2025?» → **abstención** con el último dato disponible (2024: 8.45 %) y qué haría falta | "Si no hay evidencia, se abstiene y dice qué falta." | `python -m src.consulta "…"` |

## Pruebas dinámicas del jurado

| Pregunta | Dónde ir |
|---|---|
| "¿De dónde proviene esta cifra y de qué año es?" | Consulta de inflación 2023 → clic en la cita `IND-` → país, año, valor, fecha de extracción y URL |
| "Si cinco medios replican la misma agencia, ¿cuántas fuentes independientes cuentas?" | `?caso=GRP-79f3183472` → *Quién lo reporta* → "una" (20 titulares, 18 medios) |
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
  - **Borrador (E1-12):** la pestaña *Paquete* llama a `src.generacion.generar_paquete(id_grupo, modalidad, solo_cache=True)`
    (configurable en `config/interfaz.yaml:generacion`). Hasta que exista, dice que la generación se integra con E1-12 y no inventa nada.
  - **`CASO-00N` y revisión (E1-16):** hoy los grupos son `GRP-…`; `?caso=` acepta un `GRP-…` o la posición en la bandeja. La pantalla *Revisión* solo consulta.
  - **Base y capturas de demo (C-06):** `data/demo.duckdb`, `preparar_demo`, `calentar_cache` y `capturas_demo` todavía no existen; `--demo` cae al snapshot y lo avisa.
  - **Banca (E2-01):** la modalidad se puede elegir y se declara parcial (D-90); la bandeja bancaria llega con esa tarea.

## Checklist

**La noche anterior**
- [ ] `poetry run python -m scripts.preparar_demo` (base de demo; C-06, aún no existe)
- [ ] `poetry run python -m scripts.calentar_cache` (borradores en caché; C-06 + E1-12)
- [ ] `poetry run python -m scripts.capturas_demo` (capturas de respaldo; C-06)
- [ ] Las fichas exportadas y actualizadas en Notion (E1-16)
- [ ] Ensayo completo cronometrado (≤ 4:00)

**30 minutos antes**
- [ ] Wi-Fi apagado
- [ ] `poetry run python -m scripts.verificar_offline` en verde (C-06)
- [ ] `poetry run streamlit run app.py -- --demo` abierto en Calidad
- [ ] Notion abierto en *Presentación al jurado*
- [ ] Ollama local corriendo (`OLLAMA_HOST` apuntando a la laptop)
