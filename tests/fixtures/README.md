# Fixtures sintéticos (E0-05)

**Todos los registros de esta carpeta son sintéticos e inventados.** Los titulares, medios, URLs (dominio reservado `.example`), cifras y personas no corresponden a hechos ni a fuentes reales. No contienen datos personales ni cuerpos de artículos: solo metadatos.

Reglas comunes:

- IDs `SYN-` deterministas y secuenciales por archivo (`SYN-T01-001`, `SYN-T02-001`, `SYN-T03-001`, `SYN-T05-001`, `SYN-T07-001`, `SYN-RUI-001`). El mismo registro conserva siempre el mismo ID (D-63).
- `origen = sintetico`; fechas ISO 8601 en UTC (`YYYY-MM-DDTHH:MM:SSZ`); UTF-8.
- Las columnas de los archivos de noticias son las de `noticias.csv` del contrato (CLAUDE.md), más las columnas extra de prueba indicadas abajo.
- **Nunca copiar estos archivos a `data/processed/`** ni usarlos para calcular métricas.
- Los registros sin error intencional cumplen el contrato de datos.
- **Cada fila de T01 con error tiene exactamente un error: el declarado en `error_esperado`.** En particular, su fecha de detección cae dentro de la ventana de D-74 (salvo en `SYN-T01-009`, donde la detección es la fecha inválida).
- La ventana de fechas es la de D-74: la fecha de detección cae dentro de los 90 días previos a la extracción (las filas de `ruido.csv` con motivo `fuera_de_ventana` son la excepción deliberada). El intervalo de la sección 7 del PDF no se usa porque hoy es imposible de extraer.

## Archivos

| Archivo | Prueba | Qué contiene |
|---|---|---|
| `t01_noticias_invalidas.csv` | T01 (carga y validación) | 6 filas válidas y 10 con error intencional (uno por fila, el declarado). Columna extra `error_esperado`. |
| `t01_indicadores_nulos.csv` | T01 (nulos) | Esquema de `indicadores.csv` con valores `valor` vacíos (nulos válidos; nunca 0). |
| `t02_mismo_evento.csv` | T02 (agrupación) | Tres titulares del mismo evento (lluvias en Chiriquí) en tres medios sintéticos; los tres citan a la agencia EFE. Se espera 1 grupo, 3 fuentes conservadas y 1 procedencia. |
| `t03_recirculada.csv` | T03 (noticia antigua) | Una noticia publicada en 2024 y detectada en septiembre de 2025. |
| `t05_contradiccion.csv` | T05 (afirmaciones incompatibles) | Dos titulares del mismo evento con cifras incompatibles (12 vs. más de 40 escuelas). |
| `t07_inyeccion.csv` | T07 (inyección) | Ocho titulares con descripción maliciosa. Columnas extra `descripcion` y `tipo_ataque`. |
| `ruido.csv` | Limpieza y ruido | 15 filas. Columnas extra `ruido_esperado` y `motivo_ruido`. |

## Errores intencionales de T01

`error_esperado` está vacío en las filas válidas. Se eligió una columna en lugar de una lista en este README para que las pruebas lean el error esperado del propio archivo, sin duplicar IDs. Es una columna extra de prueba: el contrato fija campos mínimos, y este archivo nunca llega a `data/`.

| Código | Filas | Error |
|---|---|---|
| `fecha_invalida` | `SYN-T01-007`, `-008`, `-009` | Mes 13 y día 45; texto libre; 30 de febrero |
| `id_duplicado` | segunda aparición de `SYN-T01-002` | Mismo ID con contenido distinto (la primera aparición es válida) |
| `url_mal_formada` | `SYN-T01-011`, `-012`, `-013` | Esquema `htp:/`; sin esquema; `https://` sin host |
| `obligatorio_vacio` | `SYN-T01-014`, `-015` y la fila sin ID | `titulo` vacío; `medio` vacío; `id_noticia` vacío |

Los nulos de `t01_indicadores_nulos.csv` **no son errores**: se conservan como nulos y no se rellenan con cero. Los indicadores no tienen ID ni `origen`; se marcan como sintéticos con `licencia = sintetico` y una `fuente_url` bajo `/sintetico/`. Sus valores están inventados y no coinciden con los datos reales del Banco Mundial.

## T03, T05 y T07

- **T03:** `fecha_publicacion` (2024-03-14) y `fecha_deteccion` (2025-09-28) son distintas. La detección cae dentro de la ventana de D-74 (hasta 90 días antes de la extracción); la publicación es antigua a propósito. Se espera mostrar la fecha original y no tratarla como evento nuevo.
- **T05:** dos medios distintos, mismo evento, cifras incompatibles. Se espera mostrar ambas versiones y la verificación pendiente.
- **T07:** cuatro tipos de ataque (`ignorar_instrucciones`, `revelar_prompt`, `cambiar_reglas`, `pedir_publicar`), cada uno en español e inglés. La `descripcion` es sintética (las descripciones reales del RSS no se redistribuyen, D-72); por eso `alcance_texto` usa la leyenda que menciona la descripción. Se espera tratarlos como contenido no confiable.

## ruido.csv

`ruido_esperado` es `true` o `false`; `motivo_ruido` va vacío cuando es `false`. El vocabulario de motivos es el de `docs/guia_temas.md` y `specs/E1-03b.md` (snake_case): `no_es_panama`, `fuera_de_temas`, `no_es_noticia`, `fuera_de_ventana`, `duplicado_url`. Las pruebas conservan la cobertura de cada categoría original (Panama City, Panama Papers, sombreros, deportes, farándula) por ID y título, no por motivo.

| Motivo | Filas | Notas |
|---|---|---|
| `no_es_panama` | `SYN-RUI-001` a `-003` | Panama City (Florida), Panama Papers como referencia histórica (titular sobre un debate académico, sin hecho nuevo), sombreros panamá |
| `fuera_de_temas` | `SYN-RUI-004`, `-005` | Deportes (fútbol) y farándula (videoclip). Son de Panamá, pero de un área que el reto no cubre |
| `no_es_noticia` | `SYN-RUI-006` | Ítem de RSS promocional |
| `fuera_de_ventana` | `SYN-RUI-007` | Detectada más de 90 días antes de la extracción (ventana de D-74) |
| `duplicado_url` | `SYN-RUI-009` a `-011` | Mismo artículo que `SYN-RUI-008` con URL `/amp`, `m.` y `http`; canonicalizadas coinciden |

No son ruido (controles): `SYN-RUI-008` (URL canónica; las cuatro variantes de la inflación usan coma decimal, "1,5 por ciento", como en el español de Panamá, y comparten título porque son el mismo artículo), `-012` y `-013` (sufijo del medio y entidades HTML que la limpieza debe resolver, pero la noticia se conserva) y `-014` y `-015` (agencia global, sección `/mundo/`, sobre hechos que afectan a Panamá; CLAUDE.md: no es ruido).
