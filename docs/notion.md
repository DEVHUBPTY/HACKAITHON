# Exportación a Notion y registro de casos (E1-16, D-47 a D-50)

La app (DuckDB) es la **fuente de verdad**. Notion recibe exportaciones **manuales** o, opcionalmente, la **sincronización por la API** (E3-03, abajo).

## Qué se exporta y de dónde sale

| Salida | Dónde | Contenido |
|---|---|---|
| `CASO-001.md` | `outputs/notion/` | La ficha **tal como se revisó**, el borrador vigente, el historial de revisión (hora de Panamá) y la leyenda de alcance (D-51) |
| `casos_y_evidencias.csv` | `outputs/notion/` | Una fila por caso, con las 24 columnas editables de la base *Casos y evidencias* (`P` y `Rango` son fórmulas de Notion) |
| `fichas.jsonl` | `outputs/` | Una línea por caso con los campos del contrato; `estado_revision` es la última fila de `revisiones` |

- **Se exporta lo que se revisó, no lo que diga la base de hoy.** Cada vez que una persona abre, regenera, rechaza un vínculo o aprueba, la `Ficha` queda guardada tal cual en la tabla `fichas_revisadas` (solo agregar). `src.exportar` lee esas fichas guardadas y **no abre `senales.duckdb`**: si el pipeline vuelve a agrupar los titulares y un `GRP-` desaparece (su ID es el hash de sus `NOT-`), el caso se conserva y se exporta igual, y no afecta a los demás.
- `--caso CASO-001` escribe solo ese caso; `fichas.jsonl` se regenera con las fichas guardadas de todos.
- **La demo exporta aparte:** `outputs/demo/notion/` y `outputs/demo/fichas.jsonl`, con su propia base (`data/revision_demo.duckdb`) y su propia numeración. Nunca toca las salidas reales (`config/revision.yaml`: `carpeta_demo`, `fichas_jsonl_demo`).

## Aprobación provisional del asistente (D-112, extiende D-101)

Durante el desarrollo el asistente hace los pasos de juicio humano, de forma **provisional y visible**. Está en la lista de revisores de `config/revision.yaml` con `provisional: true`; el código lee esa bandera, no un nombre.

- **Dónde se ve:** historial y estado en la pantalla *Revisión*, `src.revision --estado/--historial`, el estado y el historial del `CASO-00N.md`, la columna *Revisor* del CSV («Asistente (provisional, D-101) · provisional (D-101)») y `revision_provisional: true` en `fichas.jsonl`.
- **El contrato no cambia:** `estado_revision` sigue siendo uno de los cinco estados; la marca va en un campo aparte. La propiedad *Estado de revisión* de Notion tampoco se toca (es un select).
- **C-09 (rehacerlo una persona):** la persona abre el mismo `CASO-` en la app, **reabre** (con motivo) y **aprueba como borrador**. Esas filas se agregan a `revisiones` (solo agregar: no hay `UPDATE` ni `DELETE`), la suya pasa a ser la vigente y la exportación deja de decir «provisional». Las filas del asistente quedan en el historial, rotuladas. Se vuelve a exportar el caso y se reimporta la fila en Notion (ver el procedimiento de abajo).

- **Advertencia para Notion:** la columna *Estado de revisión* (select) dice «Aprobado como borrador» **sin** la marca; la marca provisional vive solo en la columna *Revisor*. Una vista o un filtro por estado cuenta `CASO-001` como aprobado: **combínelo siempre con *Revisor*** (excluya «provisional (D-101)») hasta que una persona lo rehaga en C-09.
- **El registro no pierde la marca:** la marca se deriva de `config/revision.yaml`, así que `Revisiones` falla con un error explícito si el registro tiene un revisor que ya no está en la configuración (X72). No se borra ni se renombra la entrada del asistente. Quitar solo la bandera `provisional` de una entrada que sigue existiendo no se detecta (la fila no guarda la bandera): es un cambio de configuración que pasa por revisión de PR.
- **Métricas:** `eval.revision` cuenta como humanos solo los casos cuya decisión vigente tomó una persona; los del asistente van aparte en `provisionales` (con `juicio_humano: false` y el aviso de D-101) y nunca en las tasas principales (X71).

## Cómo llevarlo a Notion (procedimiento manual)

1. Abra *Casos y evidencias* en Notion → `…` → **Merge with CSV** (o *Import*) y elija `outputs/notion/casos_y_evidencias.csv`.
2. **Importar agrega filas:** Notion no busca una página existente por *ID caso*. Volver a importar un `CASO-` que ya está en Notion **agrega una fila duplicada** (no lo verificamos contra Notion porque esta tarea no crea ni modifica páginas).
3. **Para actualizar un caso que ya existe en Notion**, si no usa la sincronización por la API (abajo): borre o archive la fila vieja y luego importe el CSV, o edite las propiedades de la página a mano. El cuerpo de la página es el contenido de `CASO-00N.md` (péguelo; incluye el historial completo, que no tiene columna).
4. El CSV local sí es idempotente: re-exportar un caso reemplaza su fila en `casos_y_evidencias.csv`; el duplicado solo aparece al importar en Notion.
5. Las propiedades de texto de Notion admiten 2000 caracteres: las más largas se recortan en el CSV con la marca «… (completo en el cuerpo de la página)».

### Columnas que quedan vacías o se completan a mano
- **Caso de uso** (CU-01…CU-05, `Ejemplo`) sale **vacío en `src.exportar`**: ningún grupo lleva esa etiqueta, y una exportación suelta no sabe a qué pregunta del reto responde. Desde D-118 la correspondencia existe **solo para las cinco fichas trazables**: `python -m scripts.fichas_trazables --casos` la deriva de `config/fichas_trazables.yaml: seleccion.casos_de_uso` (una ficha por caso de uso) y rellena la columna en el CSV de esa corrida, en el CSV de E1-16 y en lo que sincroniza con Notion. Re-exportar un caso con `src.exportar --caso` la deja vacía en el CSV; con `--notion`, esa propiedad vacía NO se envía (`notion.yaml: sin_valor_no_se_envia`), así que el valor que ya puso C-01 en Notion se conserva. Para llevar los casos a Notion usar `scripts.fichas_trazables --casos --notion`. Las demás fichas se completan a mano.
- **Tema** es el nombre del tema clasificado; si Notion no tiene esa opción de select, la crea al importar.

## Sincronización automática por la API (E3-03, opcional)

`poetry run python -m src.exportar --caso CASO-001 --notion` exporta como siempre (Markdown, CSV, `fichas.jsonl`) y además **crea o actualiza** la página del caso en *Casos y evidencias* (`src/notion.py`, `config/notion.yaml`). El CSV y el procedimiento manual de arriba siguen siendo el respaldo.

**Configuración (una vez, por una persona):**
1. Crear una integración interna de Notion y **compartirla con la base** *Casos y evidencias* (menú `…` → Conexiones).
2. Guardar su token en `local.env` como `NOTION_TOKEN=…` (solo ahí: `.env.example` lleva el nombre; el valor no va al repo, a engram ni al chat). Los logs lo redactan (`*_TOKEN`, D-69).
3. El `id` de la base (no es secreto) está en `config/notion.yaml: base_de_datos.id`.

**Qué hace:**
- **Idempotente por `ID caso`:** busca la página por su título. Si existe, actualiza sus propiedades y **reemplaza el cuerpo**; si no, la crea. Re-sincronizar no duplica. Si hay **más de una** página con ese `ID caso` (p. ej. por importar el CSV varias veces) se detiene sin escribir y pide archivar los duplicados.
- **Envía lo exportado:** las mismas 24 columnas del CSV (incluida *Revisor* con la marca «provisional (D-101)», D-112) y el Markdown del caso como bloques de texto literal (encabezados, viñetas y párrafos; la tabla del historial queda como líneas de texto). Sale de `fichas_revisadas`, nunca de `senales.duckdb`. `P` y `Rango` son fórmulas de Notion y no se escriben.
- **No escribe en el registro de revisiones** ni cambia ningún estado: todo sigue siendo BORRADOR y no existe «publicar».
- **`--demo` no se combina con `--notion`:** los casos sintéticos nunca van a la base real.

**Sin red o sin token** la exportación local queda escrita igual y se imprime «No se sincronizó con Notion…» (código de salida 0). Un error de la API (permiso, esquema, límite agotado tras los reintentos) devuelve código 1. Los reintentos ante HTTP 429/5xx son acotados y respetan `Retry-After`.

**Mapeo de columnas (esquema leído de la base en solo lectura):**

| Tipo en Notion | Propiedades |
|---|---|
| título | `ID caso` |
| select | `Modalidad`, `Tema`, `Caso de uso`, `Estado de revisión`, `Estado de evidencia` (un valor vacío queda sin valor) |
| número | `R`, `I`, `U`, `N`, `E` (un nulo queda nulo, nunca cero) |
| fecha | `Fecha de revisión`, `Última exportación` (ISO 8601 UTC) |
| texto | las demás (`Acción recomendada`, `Versión de reglas`, `Versión del borrador`, `Alcance del texto`, `Qué se reporta`, `Quién lo reporta`, `Qué está respaldado`, `Qué falta comprobar`, `IDs de fuente`, `Revisor`, `Comentario del revisor`); se parten en trozos de ≤ 2000 caracteres |
| fórmula (no se escribe) | `P`, `Rango` |

`config/notion.yaml: propiedades` declara este mapa y `python -m src.config --validar` comprueba que cubra exactamente `revision.yaml: exportacion.columnas`. *Caso de uso* sigue vacío (ver abajo). La advertencia sobre *Estado de revisión* y *Revisor* (D-112) aplica igual a las páginas sincronizadas.

## Numeración de casos: un `CASO-` nunca se reutiliza (D-63)

- El número siguiente es el **máximo conocido + 1**, donde «conocido» es la unión de: los casos de `data/revision.duckdb`, el **registro** `data/revision.casos.csv` (CSV de solo agregar, junto a la base, que **sí se versiona**), y los `CASO-` que aparecen en lo ya exportado (`outputs/notion/*.md` y su CSV, `outputs/fichas.jsonl`).
- Por eso borrar o recrear `data/revision.duckdb` no reinicia la cuenta mientras el registro o lo exportado sigan ahí. Si se borran **todos** (base, registro y exportaciones), no queda memoria y la cuenta vuelve a `CASO-001`: es un límite declarado.
- Las revisiones son un **dato humano de entrada**, no una salida del pipeline: `scripts.reproducir` (E1-20) debe tratarlas como insumo y no regenerarlas.

## Concurrencia y límites declarados

- Dos sesiones de la app sobre la misma base: la segunda acción falla sin escribir nada y la pantalla dice «otra persona actuó sobre este caso al mismo tiempo; recargue y vuelva a intentar». Abrir a la vez el mismo grupo devuelve el mismo caso.
- «Solo agregar» se garantiza **en la API** (ninguna sentencia `UPDATE` ni `DELETE`, vigilado por una prueba). DuckDB no tiene permisos por tabla ni disparadores, así que alguien con acceso al archivo puede editarlo: es la misma limitación que la falta de autenticación (D-49).
- Un caso **huérfano** (su grupo ya no existe en la base de señales) se puede exportar, aprobar, descartar y reabrir; no se puede regenerar, corregir ni cambiar sus vínculos, y la pantalla lo dice.
