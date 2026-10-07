# Diccionario de datos del snapshot

Describe cada archivo de `data/processed/` tal como lo escribe `scripts/conversion.py`. El contrato
completo (sección 7 del reto) está en `CLAUDE.md`. Fechas siempre ISO 8601 UTC con `Z`; los nulos
quedan como celda vacía (CSV) o `null` (JSON), nunca como 0.

## `noticias.csv`: una fila por URL canónica

| Campo | Contenido |
|---|---|
| `id_noticia` | `NOT-` + 10 primeros caracteres del SHA-1 de la URL canónica (https, sin `www`, sin fragmento ni rastreo). Estable. |
| `titulo` | Titular tal como lo reporta el medio. Un titular es lo que un medio reporta, no un hecho. |
| `url` | URL de la noticia (la del RSS si el registro vino también de allí). |
| `medio` | Nombre legible (`TVN Panamá`) o el dominio si el medio no está en `medios_conocidos`. |
| `idioma` | **Código ISO 639-1** (`es`, `en`, `ru`...). GDELT entrega el nombre del idioma y se traduce con `gdelt.idiomas` (config). Si un nombre no está en la tabla se conserva en minúsculas (`klingon`) y el manifest lo marca en `transformaciones`. El RSS aporta su código de dos letras. |
| `fecha_publicacion` | Solo la trae el RSS. Vacía para registros que solo vinieron de GDELT. |
| `fecha_deteccion` | `seendate` de GDELT (cuándo GDELT vio la noticia). **Vacía para los registros que solo vinieron del RSS.** Nunca se sustituye por la publicación. |
| `fecha_extraccion` | Marca de tiempo UTC del crudo en que se vio por primera vez. |
| `tema` | **Tema de origen**, no el del clasificador (D-62): clave de consulta de GDELT (`logistica`, `turismo`, `economia`, `eventos_naturales`) o primera sección de la URL del RSS (`nacionales`, `deportes`...; `sin_seccion` si la ruta no tiene sección). Si la misma URL salió en varios temas se unen con `\|` en orden alfabético (`economia\|logistica`). |
| `origen` | `TVN RSS`, `GDELT` o `TVN RSS · GDELT` si estuvo en ambos. |
| `alcance_texto` | Leyenda de alcance: "basado únicamente en titular/metadatos". |

**Ventana (D-74):** los 30 días previos a la extracción (hasta 90 si faltan registros), medida sobre
`fecha_deteccion`; para los registros sin detección (solo RSS) se mide sobre `fecha_publicacion`.
No se guarda la descripción del RSS ni `socialimage` (D-31, D-72).

## `fuentes.json`: un registro por medio

| Campo | Contenido |
|---|---|
| `dominio` | Host sin `www`. |
| `nombre_legible` | Nombre del medio o su dominio. |
| `pais` | País de la fuente en español (`sourcecountry` de GDELT traducido con `paises_es`; `Panamá` para TVN). **`null` si no se conoce.** No es una condición de uso. |
| `origen` | `TVN RSS`, `GDELT` o ambos. |
| `condiciones` | Condiciones de uso conocidas; `Pendiente de verificar` si no se conocen (solo este campo usa esa frase). |

## `indicadores.csv`: cuadrícula del Banco Mundial, 540 filas (6 países × 6 indicadores × 15 años)

| Campo | Contenido |
|---|---|
| `id_indicador` | `IND-<país>-<indicador>-<año>`, p. ej. `IND-PAN-FP.CPI.TOTL.ZG-2023`. Estable. |
| `pais_iso3`, `indicador_id`, `anio` | Clave de la fila. |
| `valor` | Valor del crudo; **vacío si el Banco Mundial no lo publica** (nunca 0). Datos anuales: no son "actuales". |
| `unidad` | Unidad original, de `config/fuentes.yaml`. |
| `fuente_url`, `fecha_extraccion`, `licencia` | Procedencia. |

`validar_snapshot` compara cada `valor` con el crudo: un 0 solo es válido si el crudo trae 0.

## `eventos.geojson`: sismos de USGS (2024, lat 5-12, lon -86 a -76, M >= 3)

Cada `Feature` lleva en `properties`: `id` (`SIS-<id USGS>`), `magnitude`, `time` y `updated`
(ISO UTC, convertidos desde milisegundos epoch), `longitude`, `latitude`, `depth`, `place` (texto
original de USGS; la caja no es Panamá), `status`, `url`. Solo sirve para hechos sísmicos.

## `conversion.json`: auditoría de la conversión

Ventana aplicada, registros excluidos con motivo (`fuera_de_ventana`, `sin_titulo`, `sin_url`...),
duplicados descartados, `idiomas_sin_mapeo`, `gdelt_cobertura_por_tema` (días cubiertos y esperados) y
`gdelt_rangos_sin_resolver` (tema, rango, `motivo`: `no_solicitado`, `bloqueado`, `vacio_sospechoso`,
`cobertura_parcial`, `truncado_sin_resolver`).

## Qué NO es cobertura

`ventana_dias_aplicada` del manifest es el filtro de fechas, **no** la cobertura lograda. Un día de GDELT
cuenta como cubierto solo si un crudo con la clave `articles` lo contiene completo; una respuesta `{}` no
prueba que no haya resultados (queda como `vacio_sospechoso`, apta para reintentar). Los días cubiertos por
tema están en `manifest.json` → `cobertura_efectiva.gdelt_dias_por_tema`.

## `processed/validos/`: filas válidas (D-82)

Lo escribe `poetry run python -m src.carga` (E1-02), no `conversion.py`. Contiene solo las filas que
pasaron la validación, con los mismos nombres de archivo y campos del contrato: `noticias.csv`,
`indicadores.csv`, `eventos.geojson`, `fuentes.json`. Es la entrada de las etapas siguientes (E1-03).

- Los archivos de `processed/` y su manifest **no cambian**: `validos/` es una vista derivada, ignorada por git
  y regenerable.
- Salida determinista: filas ordenadas por clave (`id_noticia`; país, indicador y año; `id`; `dominio`),
  UTF-8, saltos LF. Los nulos siguen siendo nulos (celda vacía o `null`, nunca 0).
- Las filas rechazadas, con su motivo, van a `outputs/errores.csv`; el conteo, a `outputs/reporte_calidad.json`
  (por archivo: `validas + rechazadas = leidas`, `errores_de_archivo` y `lineas_mal_formadas` aparte).

## Fuera de `processed/`

- `raw/`: **solo** respuestas de la API, sin modificar. Nunca contiene notas ni registros de fallos.
- `registro_extraccion/`: fallos y notas de extracción (`origen` dice si los generó la herramienta o se
  escribieron a mano a partir del log). No definen `fecha_corte_UTC`. No contienen contenido restringido.

## `senales.duckdb`: base de datos de las etapas siguientes (E1-03)

La crea `poetry run python -m src.normalizacion` a partir de `processed/validos/` (no modifica ningún archivo de
entrada) y está ignorada por git. Columnas: **tipo** (DuckDB), **nullable**, **fuente** (de dónde sale) y **clase**:
**mínimo** (campo del contrato de la sección 7), **opcional** (permitido por E1-03, puede ser nulo) o **derivado**
(lo calcula la normalización). Las fechas son texto ISO 8601 UTC con `Z`, tal como el contrato. Una cadena vacía es
siempre nulo, en CSV y en JSON; los nulos nunca se rellenan con 0.

**Reglas que aplica:** `url_canonica` = esquema `https`, dominio en minúsculas sin `www.`, sin `m.` (móvil), sin `utm_*` ni parámetros de
rastreo, sin `/amp` ni `?outputType=amp`/`?amp=1`, sin fragmento ni barra final (E1-03b). Las noticias con la misma URL canónica se fusionan en una (primer valor no nulo
de cada campo; `tema` y `origen` se unen; `fecha_extraccion` es la más antigua) y cada descartada queda en
`duplicados_eliminados` con su motivo (decisión E1-03b: los duplicados por URL **no** se marcan en `noticias`; se fusionan aquí y se cuentan con el motivo `duplicado_url` en `outputs/reporte_calidad.json`, de modo que cada fila de entrada queda en `noticias` o en `duplicados_eliminados`). De las duplicadas, `fecha_deteccion` es la más temprana. El `id_noticia` es `NOT-` + 10 caracteres del SHA-1 de la URL canónica
(los `SYN-` conservan el suyo), así que no depende del orden de carga. `fecha_publicacion` y `fecha_deteccion` nunca
se sustituyen entre sí. El nombre de la persona que firma **no se guarda** (D-32), solo `agencia` y `tipo_firma`.

### `noticias`: una fila por URL canónica

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_noticia` | VARCHAR | no | `noticias.csv` o derivado | mínimo | `NOT-<sha1[:10]>` de la URL canónica; `SYN-...` para datos sintéticos. Clave primaria. |
| `titulo` | VARCHAR | no | `noticias.csv` | mínimo | Titular tal como lo reporta el medio (no es un hecho). |
| `url` | VARCHAR | no | `noticias.csv` | mínimo | URL de la noticia tal como llegó (la primera de las duplicadas, en orden determinista). |
| `url_canonica` | VARCHAR | no | `url` | derivado | URL canónica (reglas arriba). Es la clave de deduplicación. |
| `medio` | VARCHAR | no | `fuentes.json` (dominio → medio) | mínimo | Nombre legible del medio; si el dominio no está en `fuentes.json`, el de `noticias.csv`. |
| `idioma` | VARCHAR | sí | `noticias.csv` | mínimo | Código ISO 639-1. |
| `fecha_publicacion` | VARCHAR | sí | `noticias.csv` (RSS) | mínimo | ISO UTC. Nula si la fuente no la trae. Nunca se sustituye por la detección. |
| `fecha_deteccion` | VARCHAR | sí | `noticias.csv` (GDELT `seendate`) | mínimo | ISO UTC. Nula si no hubo detección. Nunca se sustituye por la publicación. |
| `fecha_extraccion` | VARCHAR | sí | `noticias.csv` | mínimo | ISO UTC del crudo; en duplicadas, la más antigua. |
| `tema` | VARCHAR | sí | `noticias.csv` | mínimo | Tema de origen (no el del clasificador, D-62); varios se unen con `\|`. |
| `origen` | VARCHAR | sí | `noticias.csv` | mínimo | `TVN RSS`, `GDELT` o `TVN RSS · GDELT`. |
| `alcance_texto` | VARCHAR | sí | `noticias.csv` | mínimo | Leyenda de alcance (D-51). |
| `descripcion` | VARCHAR | sí | entrada opcional | opcional | **Solo uso interno** (D-31, D-72): nunca se muestra ni se republica. El snapshot no la trae. |
| `categoria_fuente` | VARCHAR | sí | entrada opcional | opcional | Categoría que da la fuente. |
| `dominio` | VARCHAR | sí | URL canónica | opcional | Host sin `www.`. |
| `pais_medio` | VARCHAR | sí | `fuentes.json` (`pais`) | opcional | País **del medio**, no de la noticia. |
| `url_movil` | VARCHAR | sí | entrada opcional | opcional | Variante móvil de la URL, si la fuente la da. |
| `agencia` | VARCHAR | sí | campo de firma de la entrada | derivado | Agencia de la lista en `config/normalizacion.yaml` (EFE, AFP, AP, Reuters...). |
| `tipo_firma` | VARCHAR | no | campo de firma de la entrada | derivado | `agencia` · `medio` · `persona` · `sin firma`. Nunca el nombre (D-32). |
| `es_recirculada` | BOOLEAN | sí | fechas | derivado | Verdadero si la detección es más de 30 días posterior a la publicación (T03). Nulo si falta alguna de las dos fechas. |
| `titulo_original` | VARCHAR | sí | `titulo` | derivado | Copia del titular recibido (E1-03b). La interfaz muestra este. Nulo hasta correr `python -m src.limpieza`. |
| `titulo_limpio` | VARCHAR | sí | `titulo` | derivado | Sin sufijo del medio, entidades HTML decodificadas, espacios y comillas normalizados (E1-03b). Los embeddings usan este. |
| `es_ruido` | BOOLEAN | sí | limpieza | derivado | Verdadero si el registro no es una noticia pertinente sobre Panamá (E1-03b). **El registro se conserva**; el ruido no entra en la bandeja ni en el puntaje. |
| `motivo_ruido` | VARCHAR | sí | limpieza | derivado | `no_es_panama` · `fuera_de_temas` · `no_es_noticia` · `fuera_de_ventana`; nulo si no es ruido. `duplicado_url` no aparece aquí: lo registra `duplicados_eliminados` (E1-03). |
| `sospechoso_inyeccion` | BOOLEAN | sí | limpieza | derivado | Verdadero si el titular o la descripción traen patrones de instrucción (D-69). No excluye el registro; la ficha avisa al revisor. |
| `alcance_regional` | BOOLEAN | sí | limpieza | derivado | Verdadero si el titular nombra la región (Centroamérica, América Latina, LatAm, Caribe) o un fenómeno regional que afecta a Panamá (El Niño, rutas marítimas) y no es ruido (D-84). Se cuenta aparte en el reporte. |
| `similitud_panama` | DOUBLE | sí | clasificación | derivado | Mayor similitud coseno del titular con los prototipos de noticia sobre Panamá (`ruido.yaml`; diferido desde E1-03b en la revisión X14). Se guarda siempre; marca ruido solo si `similitud_prototipo.activo` (hoy `false`). Nula hasta correr `python -m src.clasificacion` (E1-07). |
| `ruido_similitud` | BOOLEAN | sí | clasificación | derivado | Verdadero si el registro se marcó `no_es_panama` por esa similitud (nunca una nota con `alcance_regional`). Nulo si no se marcó. |
| `tema_clasificado` | VARCHAR | sí | clasificación | derivado | Salida del clasificador (E1-07): uno de los 6 temas de `temas.yaml` o `sin_tema`. **No es el `tema` de origen** (D-62) y nunca se usan una como etiqueta de la otra. Nulo en el ruido. |
| `tema_similitud` | DOUBLE | sí | clasificación | derivado | Mayor similitud coseno con un tema (también si el resultado es `sin_tema`). |
| `subtema_clasificado` | VARCHAR | sí | clasificación | derivado | Solo con el método B: subtema más parecido dentro del tema (por ejemplo `agua_potable`). Nulo con A. |
| `tema_secundario` | VARCHAR | sí | clasificación | derivado | Segundo tema, solo si está a menos de `margen_secundario` del principal. |
| `tema_secundario_similitud` | DOUBLE | sí | clasificación | derivado | Similitud del tema secundario. |
| `tema_baseline` | VARCHAR | sí | clasificación | derivado | Tema del baseline de palabras clave (D-66), con las mismas categorías: 6 temas o `sin_tema`. |
| `id_grupo` | VARCHAR | sí | agrupación | derivado | `GRP-` + hash de los `NOT-` ordenados del grupo (E1-08, D-63). Cada noticia que no es ruido está en exactamente un grupo. Nulo en el ruido (no entra en la bandeja) y hasta correr `python -m src.agrupacion`. |
| `procedencia` | VARCHAR | sí | agrupación | derivado | Etiqueta de la procedencia independiente de la noticia dentro de su grupo (agencia, red de sindicación o medio). **Estimada** (CU-03). |

### `indicadores`: cuadrícula del Banco Mundial

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_indicador` | VARCHAR | no | derivado | derivado | `IND-<país>-<indicador>-<año>`. Clave primaria. |
| `pais_iso3` | VARCHAR | no | `indicadores.csv` | mínimo | ISO 3166-1 alfa-3. |
| `indicador_id` | VARCHAR | no | `indicadores.csv` | mínimo | Código del indicador del Banco Mundial. |
| `anio` | INTEGER | no | `indicadores.csv` | mínimo | Año. Los datos son anuales: no son "actuales". |
| `valor` | DOUBLE | sí | `indicadores.csv` | mínimo | Valor original; **nulo si el Banco Mundial no lo publica** (nunca 0). |
| `unidad` | VARCHAR | sí | `indicadores.csv` | mínimo | Unidad original. |
| `fuente_url` | VARCHAR | sí | `indicadores.csv` | mínimo | URL de la consulta. |
| `fecha_extraccion` | VARCHAR | sí | `indicadores.csv` | mínimo | ISO UTC. |
| `licencia` | VARCHAR | sí | `indicadores.csv` | mínimo | Licencia y condiciones. |

### `sismos`: eventos de USGS

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id` | VARCHAR | no | `eventos.geojson` | mínimo | `SIS-<id USGS>`. Clave primaria. |
| `magnitude` | DOUBLE | sí | `eventos.geojson` | mínimo | Magnitud. |
| `time` | VARCHAR | sí | `eventos.geojson` | mínimo | ISO UTC del sismo. |
| `updated` | VARCHAR | sí | `eventos.geojson` | mínimo | ISO UTC de la última actualización. |
| `longitude` | DOUBLE | sí | `eventos.geojson` | mínimo | Grados. |
| `latitude` | DOUBLE | sí | `eventos.geojson` | mínimo | Grados. |
| `depth` | DOUBLE | sí | `eventos.geojson` | mínimo | Profundidad en km, nula si USGS no la da. |
| `place` | VARCHAR | sí | `eventos.geojson` | mínimo | Texto original de USGS (la caja no es Panamá). |
| `status` | VARCHAR | sí | `eventos.geojson` | mínimo | `reviewed` o `automatic`. |
| `url` | VARCHAR | sí | `eventos.geojson` | mínimo | Página del evento en USGS. |

### `fuentes`: un registro por medio (tabla auxiliar)

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `dominio` | VARCHAR | no | `fuentes.json` | opcional | Host sin `www.`, en minúsculas. Clave primaria. |
| `nombre_legible` | VARCHAR | no | `fuentes.json` | opcional | Nombre del medio. |
| `pais` | VARCHAR | sí | `fuentes.json` | opcional | País de la fuente; nulo si no se conoce. |
| `origen` | VARCHAR | sí | `fuentes.json` | opcional | `TVN RSS`, `GDELT` o ambos. |
| `condiciones` | VARCHAR | sí | `fuentes.json` | opcional | Condiciones de uso conocidas o `Pendiente de verificar`. |

### `duplicados_eliminados`: auditoría de la deduplicación

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `tabla` | VARCHAR | no | normalización | derivado | Tabla de la que se descartó la fila. |
| `id_conservado` | VARCHAR | no | normalización | derivado | ID de la fila que quedó. |
| `id_descartado` | VARCHAR | no | normalización | derivado | ID original de la fila descartada (o su URL si no tenía). |
| `clave` | VARCHAR | no | normalización | derivado | Valor que las hacía iguales (URL canónica, ID...). |
| `motivo` | VARCHAR | no | normalización | derivado | `duplicado_url`, `duplicado_clave`, `duplicado_id`, `duplicado_dominio`. |

### `similitud_tema`: similitud de cada noticia con cada tema (E1-07)

Explicabilidad de la clasificación: una fila por noticia clasificada (no ruido), método (`A` o `B`) y tema.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_noticia` | VARCHAR | no | `noticias` | derivado | Noticia clasificada. |
| `metodo` | VARCHAR | no | clasificación | derivado | `A` (descripción + ejemplos) o `B` (prototipos por subtema), D-21. |
| `tema` | VARCHAR | no | `temas.yaml` | derivado | Uno de los 6 temas. |
| `similitud` | DOUBLE | no | clasificación | derivado | Coseno entre el titular y el tema (A: centroide; B: el subtema más parecido del tema). |
| `subtema` | VARCHAR | sí | `temas.yaml` | derivado | Solo con B: el subtema que dio esa similitud. |
| `margen_subtema` | DOUBLE | sí | clasificación | derivado | Solo con B (D-92): similitud del 1.º subtema menos la del 2.º dentro del tema. Nulo con A. |

### `grupos`: un grupo por evento (E1-08)

Titulares del mismo evento (similitud y ventana de `reglas_v1.3.yaml`). **`n_procedencias` es una estimación** (`estimado = true`):
cinco medios que replican una agencia son una procedencia. Los reemplaza `python -m src.agrupacion`.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_grupo` | VARCHAR | no | agrupación | derivado | `GRP-` + hash de los `NOT-` ordenados (D-63): mismo snapshot y mismas reglas, mismos IDs. Clave primaria. |
| `titular_central` | VARCHAR | no | `noticias` | derivado | `titulo_limpio` del titular más parecido al resto del grupo. |
| `id_noticia_central` | VARCHAR | no | `noticias` | derivado | ID del titular central. |
| `n_titulares` | INTEGER | no | agrupación | derivado | Noticias del grupo (ninguna fuente se pierde). |
| `n_medios` | INTEGER | no | agrupación | derivado | Dominios distintos. |
| `n_procedencias` | INTEGER | no | `procedencias.yaml` | derivado | Procedencias independientes, **estimadas**: la unión de medios por dominio, red, agencia y texto casi idéntico. |
| `fecha_inicio` | VARCHAR | sí | `noticias` | derivado | La más antigua de los titulares del grupo: `fecha_publicacion` de cada uno y, si le falta, su `fecha_deteccion` (cota, no publicación). ISO UTC. |
| `fecha_inicio_origen` | VARCHAR | sí | `noticias` | derivado | `publicacion` o `deteccion`: de qué campo sale `fecha_inicio`. Nulo si ningún titular tiene fecha. |
| `fecha_fin` | VARCHAR | sí | `noticias` | derivado | La más reciente, con el mismo criterio. |
| `fecha_fin_origen` | VARCHAR | sí | `noticias` | derivado | `publicacion` o `deteccion`: de qué campo sale `fecha_fin`. |
| `idiomas` | VARCHAR | sí | `noticias` | derivado | Idiomas de los titulares, ordenados, separados por coma. |
| `tema_clasificado` | VARCHAR | sí | `noticias` | derivado | Tema más frecuente de sus titulares (empate: orden alfabético); nulo si ninguno está clasificado. |
| `ids_noticia` | VARCHAR | no | `noticias` | derivado | Los `NOT-` del grupo, ordenados y separados por coma. |
| `estimado` | BOOLEAN | no | agrupación | derivado | Siempre verdadero: el conteo de procedencias es una estimación y se presenta así. |

### `procedencias`: procedencias independientes de cada grupo (E1-08)

Una fila por procedencia estimada. Nunca guarda el nombre de un autor (D-32): solo agencia, red o medio.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_grupo` | VARCHAR | no | `grupos` | derivado | Grupo al que pertenece. |
| `orden` | INTEGER | no | agrupación | derivado | 1, 2, ... por su menor `id_noticia`. |
| `etiqueta` | VARCHAR | no | `procedencias.yaml` | derivado | Agencia o red (por ejemplo `Xinhua + Big News Network`); si no hay ninguna, el medio más antiguo del conjunto. |
| `reglas` | VARCHAR | sí | agrupación | derivado | Reglas que unieron sus titulares, separadas por coma (`mismo_medio`, `agencia_campo`, `agencia_dominio`, `agencia_mencionada`, `misma_red`, `texto_casi_identico`). Nulo si es un solo titular. |
| `n_titulares` | INTEGER | no | agrupación | derivado | Titulares de la procedencia. |
| `medios` | VARCHAR | no | `noticias` | derivado | Dominios, ordenados, separados por coma. |
| `ids_noticia` | VARCHAR | no | `noticias` | derivado | Los `NOT-` de la procedencia, ordenados, separados por coma. |

### `vinculos`: contexto oficial de cada grupo (E1-09, E1-09b)

Una fila por dato (o una por grupo sin vínculo). Es **contexto, nunca prueba de causa**. Los datos del Banco Mundial son
**anuales**. `python -m src.contexto` reemplaza solo sus filas (`fuente = 'indicador'`) y, con `eventos.geojson`, las de USGS (`fuente = 'usgs'`, E1-09b); nunca mezcla unas con otras.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_grupo` | VARCHAR | no | `grupos` | derivado | Grupo contextualizado. |
| `id_evidencia` | VARCHAR | sí | `indicadores` · `sismos` | derivado | `IND-<pais>-<indicador>-<anio>` o `SIS-<id USGS>`. Nulo si el grupo no tiene vínculo. |
| `tipo` | VARCHAR | sí | `vinculos.yaml` | derivado | Tipo de relación: `directa`, `indirecta` o `evento`. Nulo si no hay vínculo. |
| `regla` | VARCHAR | no | contexto | derivado | Regla que generó la fila (`vinculo_por_subtema:<subtema>`, `vinculo_por_tema:<tema>`, `sin_vinculo_en_tabla:<tema>/<subtema>`, `sin_dato_en_periodo:<indicador>`). |
| `limitacion` | VARCHAR | sí | `vinculos.yaml` | derivado | Limitación del vínculo más la nota del dato anual (año, último año disponible, años sin valor). Nunca dice «actual». |
| `motivo_sin_vinculo` | VARCHAR | sí | `vinculos.yaml` | derivado | `tema_sin_indicador`, `sin_dato_en_periodo` (y los de sismos de E1-09b). Sin vínculo lleva `id_evidencia` nulo; la excepción es `candidatos_ambiguos` (USGS, E1-09b), que puede traer a la vez el `SIS-` del candidato y el motivo. |
| `fuente` | VARCHAR | no | contexto | derivado | Quién escribe la fila: `indicador` (`src.contexto`) o `usgs` (`src.contexto_sismos`). |
| `rol` | VARCHAR | sí | contexto | derivado | `panama` (último año con valor), `comparable` (otros países, mismo año, con dato), `tendencia` (últimos años de Panamá) o `evento` (USGS). |
| `subtema` | VARCHAR | sí | `similitud_tema` | derivado | Subtema más cercano del grupo dentro de su tema (método B) solo si supera el margen mínimo (D-92); si no, nulo (`sin_subtema`). |
| `pais_iso3` | VARCHAR | sí | `indicadores` | derivado | País del dato. |
| `indicador_id` | VARCHAR | sí | `indicadores` | derivado | Indicador del Banco Mundial. |
| `anio` | INTEGER | sí | `indicadores` | derivado | Año del dato. |
| `unidad` | VARCHAR | sí | `indicadores` | derivado | Unidad original. |
| `valor` | DOUBLE | sí | `indicadores` | derivado | Valor; nulo = sin dato, nunca 0. |
| `fecha_extraccion` | VARCHAR | sí | `indicadores` | derivado | ISO 8601 UTC. |
| `cifra_titular` | DOUBLE | sí | `grupos` | derivado | Solo en la fila `panama`: cifra (%) del titular central sobre el mismo indicador. |
| `anio_titular` | INTEGER | sí | `grupos` | derivado | Año que declara el titular; nulo si no declara uno solo. |
| `comparacion_titular` | VARCHAR | sí | `vinculos.yaml` | derivado | `posible discrepancia, verificar`, `período distinto, no comparable` o `cifra coincidente con la oficial`. Nunca se corrige al medio. |
| `place` | VARCHAR | sí | `eventos.geojson` | derivado | Solo filas `usgs`: lugar tal como lo da USGS, sin traducir. Puede estar fuera de territorio panameño. |
| `profundidad_km` | DOUBLE | sí | `eventos.geojson` | derivado | Solo filas `usgs`: profundidad (`depth`); nulo = sin dato, nunca 0. |
| `hora_utc` | VARCHAR | sí | `eventos.geojson` | derivado | Solo filas `usgs`: hora del evento en ISO 8601 UTC (la hora de Panamá se calcula solo al mostrar). |
| `estado_evento` | VARCHAR | sí | `eventos.geojson` | derivado | Solo filas `usgs`: `automatic` o `reviewed`; un evento automático puede cambiar. |
| `url_evento` | VARCHAR | sí | `eventos.geojson` | derivado | Solo filas `usgs`: página del evento en USGS. |
| `diferencia_horas` | DOUBLE | sí | contexto | derivado | Solo filas `usgs`: horas entre el evento y la noticia más cercana del grupo. |
| `criterio_subtema` | VARCHAR | sí | contexto | derivado | D-92: por qué se aceptó el subtema del grupo, `margen` (1.º − 2.º subtema ≥ mínimo) o `lexico` (un titular nombra un término del subtema). Nulo si no hay subtema. |

En las filas `usgs`, `valor` es la magnitud y `unidad` es `magnitud`. `tipo` es `evento` solo con un `SIS-` (vinculado o candidato ambiguo) y nulo si no hay vínculo; `rol` es siempre `evento`.

### `puntajes`: puntaje de atención de cada grupo (E1-10)

R, I, U, N, E y P con las reglas v1.3 (PDF sección 4). Es una herramienta de **ordenamiento**: no es una probabilidad de verdad ni de pérdida, y **no habilita publicación**.
Los reemplaza `python -m src.puntaje`. Cada componente guarda de qué valores sale (`componentes`, JSON) para la ficha.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_grupo` | VARCHAR | no | `grupos` | derivado | Grupo puntuado. Clave primaria. |
| `posicion` | INTEGER | no | puntaje | derivado | 1 = el más prioritario: mayor P, luego mayor U, luego menor ID. |
| `version_reglas` | VARCHAR | no | `reglas_v1.3.yaml` | derivado | Versión de las reglas con que se calculó (`1.3`). |
| `fecha_referencia` | VARCHAR | no | `manifest.json` | derivado | ISO 8601 UTC contra la que se midió U: el corte del snapshot, no el reloj. |
| `relevancia` | DOUBLE | no | puntaje | derivado | R en [0, 1]: foco y percentil de la similitud temática. |
| `impacto` | DOUBLE | no | puntaje | derivado | I en [0, 1]: alcance del subtema y alcance geográfico. Ni el dato oficial ni las procedencias suman (D-15, D-35). |
| `urgencia` | DOUBLE | no | puntaje | derivado | U en [0, 1] sobre la publicación original más reciente del grupo (o la detección más reciente, con el vacío correspondiente). |
| `novedad` | DOUBLE | no | puntaje | derivado | N en [0, 1]: 1 − percentil de la similitud máxima con grupos anteriores. |
| `evidencia` | DOUBLE | no | puntaje | derivado | E en [0, 1]: procedencias independientes (no titulares), dato oficial y titulares identificables (D-56). |
| `puntaje` | DOUBLE | no | puntaje | derivado | P = 30R + 25I + 20U + 15N + 10E, de 0 a 100. |
| `rango` | VARCHAR | no | `reglas_v1.3.yaml` | derivado | `bajo` [0, 40) · `medio` [40, 70) · `alto` [70, 100]. |
| `componentes` | VARCHAR | no | puntaje | derivado | JSON: por componente, su valor y la explicación (los valores de los que sale). |
| `vacios` | VARCHAR | no | puntaje | derivado | JSON: vacíos que nacen del puntaje («urgencia estimada: fecha de publicación desconocida», noticia recirculada, subtema no determinado). |
| `recirculada` | BOOLEAN | no | `noticias` | derivado | Verdadero si todos los titulares del grupo son noticias recirculadas (publicación muy anterior a la detección). |
| `es_nueva` | BOOLEAN | no | `noticias` | derivado | Falso si el grupo es una noticia recirculada: no se presenta como nueva. |

### `evidencia`: estado de evidencia y acción recomendada (E1-10)

El **estado de evidencia es independiente del puntaje** (PDF sección 4). La acción sale de la tabla 3×3 (rango × estado) de la modalidad; ninguna celda habilita publicar.
Los reemplaza `python -m src.puntaje`.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_grupo` | VARCHAR | no | `grupos` | derivado | Grupo evaluado. Clave primaria. |
| `estado` | VARCHAR | no | `reglas_v1.3.yaml` | derivado | `insuficiente`, `parcial` o `suficiente` (para el borrador). |
| `n_procedencias` | INTEGER | no | `procedencias` | derivado | Procedencias independientes, **estimadas** (E1-08). |
| `tiene_oficial` | BOOLEAN | no | `vinculos` | derivado | Hay un dato oficial `directa` o un evento `evento` (USGS) vinculado con valor. Un vínculo `indirecta` no cuenta (X22): no mide el hecho. |
| `hay_cifras` | BOOLEAN | no | `noticias` | derivado | Algún titular trae una cifra (sin contar fechas, años ni identificadores). |
| `contradicciones_abiertas` | INTEGER | no | `contradicciones` | derivado | Pares detectados por reglas: todos cuentan, diga lo que diga el LLM (solo una persona puede cerrarlos). |
| `vacios` | VARCHAR | no | evidencia | derivado | JSON: vacíos de verificación de la evidencia (procedencias, dato oficial, contradicciones, titulares sin medio o fecha). |
| `modalidad` | VARCHAR | no | `modalidad_<modalidad>.yaml` | derivado | Modalidad cuya tabla de acciones se aplicó (`editorial`). |
| `rango` | VARCHAR | no | `puntajes` | derivado | Rango de P usado para elegir la celda. |
| `accion` | VARCHAR | no | `modalidad_<modalidad>.yaml` | derivado | Acción recomendada de la celda (rango × estado). Nunca «publicar». |
| `motivo_accion` | VARCHAR | no | `modalidad_<modalidad>.yaml` | derivado | Motivo de la celda. |

### `contradicciones`: pares de titulares con versiones distintas (E1-10, D-23)

Candidatos por reglas (cifras distintas de la misma unidad, verbos opuestos); el LLM solo los compara y nunca emite un veredicto: lo que se muestra es «posible contradicción, verificar» con ambas versiones y su fuente.
El LLM solo agrega una nota (`nota_llm`); **nunca cierra un par** (X21): si no está disponible la nota es `pendiente` y el par sigue abierto. Los reemplaza `python -m src.puntaje`.

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `id_grupo` | VARCHAR | no | `grupos` | derivado | Grupo al que pertenece el par. |
| `id_noticia_a` | VARCHAR | no | `noticias` | derivado | Primera noticia del par (menor ID). |
| `id_noticia_b` | VARCHAR | no | `noticias` | derivado | Segunda noticia del par. |
| `medio_a` | VARCHAR | sí | `noticias` | derivado | Medio de la versión A. |
| `medio_b` | VARCHAR | sí | `noticias` | derivado | Medio de la versión B. |
| `titular_a` | VARCHAR | no | `noticias` | derivado | `titulo_limpio` de la versión A. |
| `titular_b` | VARCHAR | no | `noticias` | derivado | `titulo_limpio` de la versión B. |
| `fecha_publicacion_a` | VARCHAR | sí | `noticias` | derivado | Publicación de A (ISO UTC); nulo si se desconoce. |
| `fecha_publicacion_b` | VARCHAR | sí | `noticias` | derivado | Publicación de B. |
| `reglas` | VARCHAR | no | contradicciones | derivado | Reglas que lo hicieron candidato: `cifras_distintas`, `verbos_opuestos` (separadas por coma). |
| `detalle` | VARCHAR | no | contradicciones | derivado | Qué cifras o verbos chocan. |
| `estado` | VARCHAR | no | contradicciones | derivado | Siempre `verificar`: abierta hasta que una persona la cierre en la revisión (E1-16). |
| `nota_llm` | VARCHAR | no | LLM | derivado | Anotación para la persona: `posible_contradiccion`, `compatible` o `pendiente` (sin LLM, falló o respondió algo inválido). No cambia el estado de evidencia ni oculta el par. |
| `etiqueta` | VARCHAR | no | `prioridad.yaml` | derivado | «posible contradicción, verificar». |
| `fragmento_a` | VARCHAR | sí | LLM | derivado | Fragmento literal del titular A que cita el LLM (validado como subcadena); solo con `nota_llm = posible_contradiccion`. |
| `fragmento_b` | VARCHAR | sí | LLM | derivado | Fragmento literal del titular B; solo con `nota_llm = posible_contradiccion`. |
| `proveedor` | VARCHAR | sí | `local.env` | derivado | Proveedor del LLM (`ollama`); nulo si no hubo. |
| `modelo` | VARCHAR | sí | `local.env` | derivado | Modelo del proveedor. |
| `motivo_pendiente` | VARCHAR | sí | contradicciones | derivado | Solo con `nota_llm = pendiente`: por qué no se comparó (sin proveedor, proveedor caído, salida inválida, sobre el tope). |

### `registro_normalizacion`: valores que no se pudieron normalizar

Una fecha ilegible o sin zona horaria no se adivina: queda nula y se anota aquí; igual un número no numérico (queda nulo, nunca 0).

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `tabla` | VARCHAR | no | normalización | derivado | Tabla afectada. |
| `clave` | VARCHAR | no | normalización | derivado | ID o clave de la fila. |
| `campo` | VARCHAR | no | normalización | derivado | Campo afectado. |
| `valor_original` | VARCHAR | sí | entrada | derivado | Valor que no se pudo normalizar. |
| `motivo` | VARCHAR | no | normalización | derivado | P. ej. `fecha_no_normalizable:fecha_sin_zona_horaria`. |
