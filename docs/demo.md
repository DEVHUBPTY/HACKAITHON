# Guion de la demo · 4 minutos (D-52)

Un caso de uso por ficha (CASO-001 a CASO-005), encadenados en un solo recorrido.
La app corre **local y sin internet**; Notion se abre en paralelo como respaldo.

## Recorrido cronometrado

| Tiempo | CU | Pantalla (atajo) | Qué se hace | Qué se dice | Plan B |
|---|---|---|---|---|---|
| 0:00–0:15 | — | Calidad | Mostrar el reporte de carga y el ruido marcado | "Cargamos el snapshot; lo que no sirve se marca, no se borra." | Captura 01 |
| 0:15–1:00 | **CU-01** | Bandeja | Top 5 con P, barras R·I·U·N·E, estado y acción; señalar uno con **Alto + Insuficiente → Investigar ya** | "El puntaje ordena la atención; la evidencia dice si se puede trabajar. Son independientes." | Captura 02 · CASO-001 en Notion |
| 1:00–1:20 | **CU-03** | Ficha CASO-002 (`?caso=CASO-002`) | Abrir *Quién lo reporta*: titulares, medios y procedencias | "8 titulares, 6 medios, 2 procedencias: cinco replican la misma agencia." | Captura 03 · CASO-002 |
| 1:20–2:30 | **CU-02** | Ficha CASO-003 → Paquete | Dato oficial con año, unidad, comparables y limitación; generar el brief (desde caché); pasar el cursor por una cita | "Este dato es de 2023 y el sistema no lo presenta como actual." | Captura 04–05 · CASO-003 |
| 2:30–3:00 | **CU-04** | Consulta | Preguntar "¿Cuál fue el desempleo de Panamá en 2025?" → abstención con último dato disponible | "Si no hay evidencia, se abstiene y dice qué falta." | Captura 06 |
| 3:00–3:30 | **CU-04** | Ficha CASO-004 | Dos versiones de una contradicción; evidencia insuficiente → solo paquete de investigación | "Prioridad alta no habilita publicar." | Captura 07 · CASO-004 |
| 3:30–4:00 | **CU-05** | Selector → Banca · CASO-005 | Misma bandeja por sector logística; boletín con observaciones e hipótesis | "Mismo motor, otro usuario: cambiamos un archivo de configuración." | Captura 08 · CASO-005 (o `modalidad_banca.yaml` si la Etapa 2 no está lista) |

## Pruebas dinámicas del jurado

| Pregunta | Dónde ir |
|---|---|
| "¿De dónde proviene esta cifra y de qué año es?" | CASO-003 → cita `IND-` → país, año, unidad, URL |
| "Si cinco medios replican la misma agencia, ¿cuántas fuentes independientes cuentas?" | CASO-002 → *Quién lo reporta* → "una" |
| "¿Qué pasa sin evidencia o si una fuente intenta cambiar las instrucciones?" | Consulta de abstención · caso sintético T07 (`SYN-`) |
| "Muéstrame en Notion una decisión, una prueba fallida y su corrección" | Notion → Decisiones → Pruebas (estado *Corregido*) |

## Checklist

**La noche anterior**
- [ ] `poetry run python -m scripts.preparar_demo` (base de demo con los 5 casos)
- [ ] `poetry run python -m scripts.calentar_cache` (borradores de los 5 casos en caché)
- [ ] `poetry run python -m scripts.capturas_demo` (capturas de respaldo actualizadas)
- [ ] Las 5 fichas exportadas y actualizadas en Notion
- [ ] Ensayo completo cronometrado (≤ 4:00)

**30 minutos antes**
- [ ] Wi-Fi apagado
- [ ] `poetry run python -m scripts.verificar_offline` en verde
- [ ] `poetry run streamlit run app.py -- --demo` abierto en la Calidad
- [ ] Notion abierto en *Presentación al jurado*
- [ ] Ollama local corriendo (`OLLAMA_HOST` apuntando a la laptop)
