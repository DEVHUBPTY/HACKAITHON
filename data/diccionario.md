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

**Reglas que aplica:** `url_canonica` = esquema `https`, dominio en minúsculas sin `www.`, sin `utm_*` ni parámetros de
rastreo, sin fragmento ni barra final. Las noticias con la misma URL canónica se fusionan en una (primer valor no nulo
de cada campo; `tema` y `origen` se unen; `fecha_extraccion` es la más antigua) y cada descartada queda en
`duplicados_eliminados` con su motivo. El `id_noticia` es `NOT-` + 10 caracteres del SHA-1 de la URL canónica
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

### `registro_normalizacion`: valores que no se pudieron normalizar

Una fecha ilegible o sin zona horaria no se adivina: queda nula y se anota aquí; igual un número no numérico (queda nulo, nunca 0).

| Campo | Tipo | Nullable | Fuente | Clase | Descripción |
|---|---|---|---|---|---|
| `tabla` | VARCHAR | no | normalización | derivado | Tabla afectada. |
| `clave` | VARCHAR | no | normalización | derivado | ID o clave de la fila. |
| `campo` | VARCHAR | no | normalización | derivado | Campo afectado. |
| `valor_original` | VARCHAR | sí | entrada | derivado | Valor que no se pudo normalizar. |
| `motivo` | VARCHAR | no | normalización | derivado | P. ej. `fecha_no_normalizable:fecha_sin_zona_horaria`. |
