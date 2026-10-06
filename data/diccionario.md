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
