# Exportación a Notion y registro de casos (E1-16, D-47 a D-50)

La app (DuckDB) es la **fuente de verdad**. Notion recibe exportaciones **manuales**; automatizarlas con la API es E3-03 (opcional).

## Qué se exporta y de dónde sale

| Salida | Dónde | Contenido |
|---|---|---|
| `CASO-001.md` | `outputs/notion/` | La ficha **tal como se revisó**, el borrador vigente, el historial de revisión (hora de Panamá) y la leyenda de alcance (D-51) |
| `casos_y_evidencias.csv` | `outputs/notion/` | Una fila por caso, con las 24 columnas editables de la base *Casos y evidencias* (`P` y `Rango` son fórmulas de Notion) |
| `fichas.jsonl` | `outputs/` | Una línea por caso con los campos del contrato; `estado_revision` es la última fila de `revisiones` |

- **Se exporta lo que se revisó, no lo que diga la base de hoy.** Cada vez que una persona abre, regenera, rechaza un vínculo o aprueba, la `Ficha` queda guardada tal cual en la tabla `fichas_revisadas` (solo agregar). `src.exportar` lee esas fichas guardadas y **no abre `senales.duckdb`**: si el pipeline vuelve a agrupar los titulares y un `GRP-` desaparece (su ID es el hash de sus `NOT-`), el caso se conserva y se exporta igual, y no afecta a los demás.
- `--caso CASO-001` escribe solo ese caso; `fichas.jsonl` se regenera con las fichas guardadas de todos.
- **La demo exporta aparte:** `outputs/demo/notion/` y `outputs/demo/fichas.jsonl`, con su propia base (`data/revision_demo.duckdb`) y su propia numeración. Nunca toca las salidas reales (`config/revision.yaml`: `carpeta_demo`, `fichas_jsonl_demo`).

## Cómo llevarlo a Notion (procedimiento manual)

1. Abra *Casos y evidencias* en Notion → `…` → **Merge with CSV** (o *Import*) y elija `outputs/notion/casos_y_evidencias.csv`.
2. **Importar agrega filas:** Notion no busca una página existente por *ID caso*. Volver a importar un `CASO-` que ya está en Notion **agrega una fila duplicada** (no lo verificamos contra Notion porque esta tarea no crea ni modifica páginas).
3. **Para actualizar un caso que ya existe en Notion**, hasta que llegue la API (E3-03): borre o archive la fila vieja y luego importe el CSV, o edite las propiedades de la página a mano. El cuerpo de la página es el contenido de `CASO-00N.md` (péguelo; incluye el historial completo, que no tiene columna).
4. El CSV local sí es idempotente: re-exportar un caso reemplaza su fila en `casos_y_evidencias.csv`; el duplicado solo aparece al importar en Notion.
5. Las propiedades de texto de Notion admiten 2000 caracteres: las más largas se recortan en el CSV con la marca «… (completo en el cuerpo de la página)».

### Columnas que quedan vacías o se completan a mano
- **Caso de uso** (CU-01…CU-05, `Ejemplo`) sale **vacío a propósito**: ningún YAML ni tabla del repositorio asocia un grupo con un caso de uso del reto (los grupos no llevan esa etiqueta), y inventar una sería afirmar más de lo que hay. Se completa a mano en Notion. Si algún día existe esa correspondencia, se agrega a `config/revision.yaml` y el CSV la usa.
- **Tema** es el nombre del tema clasificado; si Notion no tiene esa opción de select, la crea al importar.

## Numeración de casos: un `CASO-` nunca se reutiliza (D-63)

- El número siguiente es el **máximo conocido + 1**, donde «conocido» es la unión de: los casos de `data/revision.duckdb`, el **registro** `data/revision.casos.csv` (CSV de solo agregar, junto a la base, que **sí se versiona**), y los `CASO-` que aparecen en lo ya exportado (`outputs/notion/*.md` y su CSV, `outputs/fichas.jsonl`).
- Por eso borrar o recrear `data/revision.duckdb` no reinicia la cuenta mientras el registro o lo exportado sigan ahí. Si se borran **todos** (base, registro y exportaciones), no queda memoria y la cuenta vuelve a `CASO-001`: es un límite declarado.
- Las revisiones son un **dato humano de entrada**, no una salida del pipeline: `scripts.reproducir` (E1-20) debe tratarlas como insumo y no regenerarlas.

## Concurrencia y límites declarados

- Dos sesiones de la app sobre la misma base: la segunda acción falla sin escribir nada y la pantalla dice «otra persona actuó sobre este caso al mismo tiempo; recargue y vuelva a intentar». Abrir a la vez el mismo grupo devuelve el mismo caso.
- «Solo agregar» se garantiza **en la API** (ninguna sentencia `UPDATE` ni `DELETE`, vigilado por una prueba). DuckDB no tiene permisos por tabla ni disparadores, así que alguien con acceso al archivo puede editarlo: es la misma limitación que la falta de autenticación (D-49).
- Un caso **huérfano** (su grupo ya no existe en la base de señales) se puede exportar, aprobar, descartar y reabrir; no se puede regenerar, corregir ni cambiar sus vínculos, y la pantalla lo dice.
