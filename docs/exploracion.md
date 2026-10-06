# Exploración de la muestra real (E0-09)


> Generado por `poetry run python -m scripts.explorar`. **Offline:** usa `data/processed/`, el crudo versionado de Banco Mundial y USGS y, en solo lectura (`--crudos`), los crudos de RSS y GDELT que no están en el repositorio (no se copian). Fase: Preparación (D-74). No muestra descripciones del RSS (D-31, D-72) ni nombres de autores (D-32). Los porcentajes llevan su n e intervalo de Wilson al 95 %. **El IC de Wilson supone una muestra aleatoria; este snapshot NO lo es (ventana corta, consultas dirigidas, cobertura parcial): los intervalos son descriptivos, no inferenciales.** Todo lo marcado como ruido es **candidato**: el etiquetado es E1-03b / E1-06.


**Muestra:** snapshot de E0-04 (`fecha_corte_UTC` 2026-10-06T17:07:06Z); no se descargó una muestra nueva porque GDELT está limitando las solicitudes (HTTP 429). **No es una muestra de 1–3 días con una consulta por tema**: es lo que quedó cubierto (ver Cobertura).


## 1 · Perfil de campos


**noticias.csv** (n = 186)

| Campo | Presente | Nulo | Formato observado |
|---|---|---|---|
| `id_noticia` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | prefijo `NOT-` ×186; únicos 186/186 |
| `titulo` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | texto, largo mín 9 · mediana 73 · máx 171 |
| `url` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | texto, largo mín 38 · mediana 107 · máx 189; https: 151/186 |
| `medio` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | texto, largo mín 5 · mediana 12 · máx 25 |
| `idioma` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | `a+` ×186 |
| `fecha_publicacion` | 53/186 = 28.5 % [IC 95 %: 22.5–35.4 %] | 133/186 = 71.5 % [IC 95 %: 64.6–77.5 %] | `9+-9+-9+a9+:9+:9+a` ×53 |
| `fecha_deteccion` | 133/186 = 71.5 % [IC 95 %: 64.6–77.5 %] | 53/186 = 28.5 % [IC 95 %: 22.5–35.4 %] | `9+-9+-9+a9+:9+:9+a` ×133 |
| `fecha_extraccion` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | `9+-9+-9+a9+:9+:9+a` ×186 |
| `tema` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | `a+` ×139 · `a+\|a+` ×39 |
| `origen` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | `a+` ×133 · `a+ a+` ×53 |
| `alcance_texto` | 186/186 = 100.0 % [IC 95 %: 98.0–100.0 %] | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | `a+ a+ a+ a+/a+` ×186 |

**indicadores.csv** (n = 540)

| Campo | Presente | Nulo | Formato observado |
|---|---|---|---|
| `id_indicador` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | prefijo `IND-` ×540; únicos 540/540 |
| `pais_iso3` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | `a+` ×540 |
| `indicador_id` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | `a+.a+.a+.a+` ×360 · `a+.a+.a+.a+.a+` ×90 |
| `anio` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | `9+` ×540 |
| `valor` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | `9.9+` ×240 · `9+.9+` ×186 |
| `unidad` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | texto, largo mín 7 · mediana 8 · máx 22 |
| `fuente_url` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | texto, largo mín 89 · mediana 92 · máx 95 |
| `fecha_extraccion` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | `9+-9+-9+a9+:9+:9+a` ×540 |
| `licencia` | 540/540 = 100.0 % [IC 95 %: 99.3–100.0 %] | 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %] | texto, largo mín 73 · mediana 73 · máx 73 |

**eventos.geojson (propiedades)** (n = 82)

| Campo | Presente | Nulo | Formato observado |
|---|---|---|---|
| `depth` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `9+.9` ×47 · `9+.9+` ×30 |
| `id` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | prefijo `SIS-` ×82; únicos 82/82 |
| `latitude` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `9.9+` ×70 · `9+.9+` ×12 |
| `longitude` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `-9+.9+` ×82 |
| `magnitude` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `9.9` ×82 |
| `place` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | texto, largo mín 15 · mediana 30 · máx 39 |
| `status` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `a+` ×82 |
| `time` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `9+-9+-9+a9+:9+:9+a` ×82 |
| `updated` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | `9+-9+-9+a9+:9+:9+a` ×82 |
| `url` | 82/82 = 100.0 % [IC 95 %: 95.5–100.0 %] | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] | texto, largo mín 60 · mediana 60 · máx 60; https: 82/82 |

## 2 · Conteos


Noticias en el snapshot: **186**. TVN RSS: **53/186 = 28.5 % [IC 95 %: 22.5–35.4 %]**.

### Por medio

| Medio | n | % (IC 95 %) |
|---|---|---|
| `TVN Panamá` | 53 | 53/186 = 28.5 % [IC 95 %: 22.5–35.4 %] |
| `newsroomamerica.com` | 7 | 7/186 = 3.8 % [IC 95 %: 1.8–7.6 %] |
| `panamaamerica.com.pa` | 6 | 6/186 = 3.2 % [IC 95 %: 1.5–6.9 %] |
| `listindiario.com` | 3 | 3/186 = 1.6 % [IC 95 %: 0.6–4.6 %] |
| `prensa.com` | 3 | 3/186 = 1.6 % [IC 95 %: 0.6–4.6 %] |
| `bignewsnetwork.com` | 3 | 3/186 = 1.6 % [IC 95 %: 0.6–4.6 %] |
| `unosantafe.com.ar` | 2 | 2/186 = 1.1 % [IC 95 %: 0.3–3.8 %] |
| `laestrella.com.pa` | 2 | 2/186 = 1.1 % [IC 95 %: 0.3–3.8 %] |
| `trinidadtimes.com` | 2 | 2/186 = 1.1 % [IC 95 %: 0.3–3.8 %] |
| `gfmag.com` | 2 | 2/186 = 1.1 % [IC 95 %: 0.3–3.8 %] |

_n = 186; 110 valores distintos, se muestran 10._

### Por idioma

| Idioma (ISO 639-1) | n | % (IC 95 %) |
|---|---|---|
| `es` | 109 | 109/186 = 58.6 % [IC 95 %: 51.4–65.4 %] |
| `en` | 50 | 50/186 = 26.9 % [IC 95 %: 21.0–33.7 %] |
| `de` | 10 | 10/186 = 5.4 % [IC 95 %: 2.9–9.6 %] |
| `zh` | 3 | 3/186 = 1.6 % [IC 95 %: 0.6–4.6 %] |
| `ru` | 3 | 3/186 = 1.6 % [IC 95 %: 0.6–4.6 %] |
| `ko` | 2 | 2/186 = 1.1 % [IC 95 %: 0.3–3.8 %] |
| `ro` | 1 | 1/186 = 0.5 % [IC 95 %: 0.1–3.0 %] |
| `uk` | 1 | 1/186 = 0.5 % [IC 95 %: 0.1–3.0 %] |
| `hr` | 1 | 1/186 = 0.5 % [IC 95 %: 0.1–3.0 %] |
| `fr` | 1 | 1/186 = 0.5 % [IC 95 %: 0.1–3.0 %] |

_n = 186; 15 valores distintos, se muestran 10._

Español: 109/186 = 58.6 % [IC 95 %: 51.4–65.4 %].

### Por país del medio (`fuentes.json`)

| País | n | % (IC 95 %) |
|---|---|---|
| `Panamá` | 66 | 66/186 = 35.5 % [IC 95 %: 29.0–42.6 %] |
| `Estados Unidos` | 37 | 37/186 = 19.9 % [IC 95 %: 14.8–26.2 %] |
| `Argentina` | 11 | 11/186 = 5.9 % [IC 95 %: 3.3–10.3 %] |
| `Alemania` | 10 | 10/186 = 5.4 % [IC 95 %: 2.9–9.6 %] |
| `China` | 6 | 6/186 = 3.2 % [IC 95 %: 1.5–6.9 %] |
| `Colombia` | 5 | 5/186 = 2.7 % [IC 95 %: 1.2–6.1 %] |
| `Rusia` | 5 | 5/186 = 2.7 % [IC 95 %: 1.2–6.1 %] |
| `(sin país)` | 4 | 4/186 = 2.2 % [IC 95 %: 0.8–5.4 %] |
| `México` | 4 | 4/186 = 2.2 % [IC 95 %: 0.8–5.4 %] |
| `Reino Unido` | 3 | 3/186 = 1.6 % [IC 95 %: 0.6–4.6 %] |

_n = 186; 36 valores distintos, se muestran 10._

Sin país conocido: 4/186 = 2.2 % [IC 95 %: 0.8–5.4 %].

### Por categoría del RSS (tema de origen de TVN = primera sección de la URL)

| Sección RSS | n | % (IC 95 %) |
|---|---|---|
| `nacionales` | 20 | 20/53 = 37.7 % [IC 95 %: 25.9–51.2 %] |
| `mundo` | 10 | 10/53 = 18.9 % [IC 95 %: 10.6–31.4 %] |
| `tvmax` | 9 | 9/53 = 17.0 % [IC 95 %: 9.2–29.2 %] |
| `entretenimiento` | 9 | 9/53 = 17.0 % [IC 95 %: 9.2–29.2 %] |
| `contenido-exclusivo` | 3 | 3/53 = 5.7 % [IC 95 %: 1.9–15.4 %] |
| `videos` | 1 | 1/53 = 1.9 % [IC 95 %: 0.3–9.9 %] |
| `gente-tvn` | 1 | 1/53 = 1.9 % [IC 95 %: 0.3–9.9 %] |

_n = 53; 7 valores distintos._

### Por tema de origen de GDELT (una URL puede salir en varios temas)

| Consulta GDELT | n | % (IC 95 %) |
|---|---|---|
| `logistica` | 95 | 95/180 = 52.8 % [IC 95 %: 45.5–59.9 %] |
| `economia` | 55 | 55/180 = 30.6 % [IC 95 %: 24.3–37.6 %] |
| `turismo` | 30 | 30/180 = 16.7 % [IC 95 %: 11.9–22.8 %] |

_n = 180; 3 valores distintos._

### Por día (fecha base: detección; publicación si no hay detección; UTC)

| Día | GDELT | TVN RSS |
|---|---|---|
| 2026-09-29 | 0 | 1 |
| 2026-10-01 | 52 | 1 |
| 2026-10-02 | 77 | 1 |
| 2026-10-04 | 0 | 1 |
| 2026-10-05 | 0 | 26 |
| 2026-10-06 | 4 | 23 |

_Días con datos: 6. La hora de Panamá solo se usa en la interfaz._

## 3 · Preguntas del spec


### ¿GDELT trae fecha de publicación?

**No.** GDELT DOC 2.0 (`mode=artlist`) entrega `seendate` (cuándo GDELT vio la noticia) y no la fecha en que el medio la publicó. En el snapshot, de los registros que vinieron solo de GDELT (n = 133): `fecha_publicacion` presente en 0/133 = 0.0 % [IC 95 %: 0.0–2.8 %]; `fecha_deteccion` presente en 133/133 = 100.0 % [IC 95 %: 97.2–100.0 %]. Registros presentes en el RSS **y** en GDELT: 0 de 186.

**Verificado en el crudo** (9 archivos, 370 artículos; los archivos pueden repetir artículos entre rangos): campos con valor: `url` ×370, `title` ×370, `seendate` ×370, `domain` ×370, `language` ×370, `sourcecountry` ×358, `socialimage` ×286, `url_mobile` ×71. Ninguno es una fecha de publicación; `seendate` es la única fecha.

**Efecto:** U (urgencia) y T03 (noticia recirculada) no pueden usar GDELT como fecha del hecho; solo el RSS de TVN la trae (53/186 = 28.5 % [IC 95 %: 22.5–35.4 %] de las noticias). Una fecha de detección reciente de una nota vieja es justo el caso de T03. Ver recomendaciones.

### ¿El RSS de TVN trae autor o firma?

**Verificado: el RSS de TVN no trae autor ni firma** (150/150 entradas sin ninguno de los campos buscados). Entradas en 1 crudo(s): 150. Campos de firma buscados: author, dc_creator, creator.

| Tipo de firma | n | % (IC 95 %) |
|---|---|---|
| sin firma | 150 | 150/150 = 100.0 % [IC 95 %: 97.5–100.0 %] |

Categorías del RSS (`<category>`, solo conteos): 150/150 = 100.0 % [IC 95 %: 97.5–100.0 %] de las entradas traen alguna; `TVN Media` ×66, `Panamá` ×7, `Medios de comunicación` ×7, `Musica` ×6, `Medio Ambiente` ×6, `Convenio` ×6, `Líderes 360` ×5, `Liderazgo` ×5, `empresas` ×5, `gente tvn` ×5.

Agencias: ninguna

Claves presentes en las entradas (sin descripción): `title` ×150, `title_detail` ×150, `link` ×150, `id` ×150, `guidislink` ×150, `published` ×150, `published_parsed` ×150, `updated` ×150, `updated_parsed` ×150, `media_thumbnail` ×150, `href` ×150, `media_keywords` ×150, `tags` ×150

## 4 · Calidad de los titulares


| Señal (candidata) | Todas | TVN RSS | GDELT |
|---|---|---|---|
| Sufijo de medio (` - Medio`, ` \| Medio`) | 26/186 = 14.0 % [IC 95 %: 9.7–19.7 %] | 0/53 = 0.0 % [IC 95 %: 0.0–6.8 %] | 26/133 = 19.5 % [IC 95 %: 13.7–27.1 %] |
| Entidad HTML sin decodificar (`&amp;`, `&#39;`) | 0/186 = 0.0 % [IC 95 %: 0.0–2.0 %] | 0/53 = 0.0 % [IC 95 %: 0.0–6.8 %] | 0/133 = 0.0 % [IC 95 %: 0.0–2.8 %] |
| Espacio antes de puntuación (tokenización de GDELT: `21 , 2 %`) | 62/186 = 33.3 % [IC 95 %: 27.0–40.4 %] | 0/53 = 0.0 % [IC 95 %: 0.0–6.8 %] | 62/133 = 46.6 % [IC 95 %: 38.4–55.1 %] |
| Barra pegada a la palabra (`resultados\| texto`, estilo TVN) | 7/186 = 3.8 % [IC 95 %: 1.8–7.6 %] | 7/53 = 13.2 % [IC 95 %: 6.5–24.8 %] | 0/133 = 0.0 % [IC 95 %: 0.0–2.8 %] |
| Titular sin contenido (solo dominio, `Inicio \|`, `Preview -`) | 9/186 = 4.8 % [IC 95 %: 2.6–8.9 %] | 0/53 = 0.0 % [IC 95 %: 0.0–6.8 %] | 9/133 = 6.8 % [IC 95 %: 3.6–12.4 %] |

## 5 · Candidatos a ruido


| Señal | Candidatos / base |
|---|---|
| Titular sin contenido | 9/186 = 4.8 % [IC 95 %: 2.6–8.9 %] |
| Medio no TVN cuyo titular no nombra Panamá ni un término panameño | 115/133 = 86.5 % [IC 95 %: 79.6–91.3 %] |
| Falso Panamá conocido (Panama City Beach…) | 1/186 = 0.5 % [IC 95 %: 0.1–3.0 %] |
| Palabras de deportes | 16/186 = 8.6 % [IC 95 %: 5.4–13.5 %] |
| Palabras de farándula | 9/186 = 4.8 % [IC 95 %: 2.6–8.9 %] |
| Autopromoción de TVN | 6/53 = 11.3 % [IC 95 %: 5.3–22.6 %] |
| Cualquiera de las señales | 142/186 = 76.3 % [IC 95 %: 69.7–81.9 %] |

Son **candidatos por palabras clave** (listas en `config/exploracion.yaml`). No miden precisión; la medición contra etiquetas humanas es `eval.ruido` (E1-03b).

## 6 · Titulares casi duplicados (pistas de agrupación de eventos)


Grupos de ≥ 2 titulares casi idénticos (texto normalizado, sin sufijo de medio): **7**; cubren 45/186 = 24.2 % [IC 95 %: 18.6–30.8 %] de los registros.

| Registros | Medios | Idiomas | Titular (primero) |
|---|---|---|---|
| 20 | 18 | en | World Insights : Intensifying El Nino deepens economic risks across LatAm - Xinhua |
| 10 | 10 | de | Trump streicht Europa - Hilfe , lenkt Millionen nach Lateinamerika |
| 7 | 1 | en | newsroomamerica . com |
| 2 | 1 | es | ¿ Cómo se fija el precio del combustible en Panamá ? El MEF explica la fórmula quincenal tras aprobarse nuevo  |
| 2 | 2 | es | Jóvenes de Haina que se fueron engañados para pelear en Rusia piden auxilio para retornar al país |
| 2 | 2 | en | Kiev reaping huge profits on EU arms supplies Russian intel |
| 2 | 2 | en | Remembering The False Gloom And Doom Of The 1992 Elections ... And The Upcoming Midterms |

_No detecta traducciones: «Trump streicht Europa-Hilfe…» (de) y «Допомога США Європі…» (uk) son el mismo evento y quedan en grupos distintos. Eso lo cubre la similitud semántica (E1-08)._

## 7 · Cobertura y vacíos


| Tema GDELT | Días cubiertos | Días esperados | Cobertura (IC 95 %) |
|---|---|---|---|
| economia | 4 | 30 | 4/30 = 13.3 % [IC 95 %: 5.3–29.7 %] |
| eventos_naturales | 0 | 30 | 0/30 = 0.0 % [IC 95 %: 0.0–11.4 %] |
| logistica | 4 | 30 | 4/30 = 13.3 % [IC 95 %: 5.3–29.7 %] |
| turismo | 4 | 30 | 4/30 = 13.3 % [IC 95 %: 5.3–29.7 %] |

Días sin resolver (suma de rangos):

| Tema | Motivo | Días |
|---|---|---|
| economia | cobertura_parcial | 1 |
| economia | no_solicitado | 25 |
| eventos_naturales | bloqueado | 2 |
| eventos_naturales | no_solicitado | 28 |
| logistica | cobertura_parcial | 1 |
| logistica | no_solicitado | 25 |
| turismo | cobertura_parcial | 1 |
| turismo | no_solicitado | 25 |

RSS: de 2026-09-29T01:23:06Z a 2026-10-06T15:45:50Z; detección GDELT: de 2026-10-01T16:00:00Z a 2026-10-06T08:30:00Z.

**`eventos_naturales` tiene 0 días cubiertos**: no hay ni un titular de GDELT en ese tema, y los sismos/lluvias son un tema central del reto. Los números de este informe no representan los 30 días de la ventana (D-74).

## 8 · Banco Mundial


| Indicador | Unidad | Nulos | Último año con dato (rango) | Último año por país |
|---|---|---|---|---|
| `FP.CPI.TOTL.ZG` | % anual | 0/90 = 0.0 % [IC 95 %: 0.0–4.1 %] | 2024–2024 | COL 2024, CRI 2024, DOM 2024, GTM 2024, MEX 2024, PAN 2024 |
| `IT.NET.USER.ZS` | % de la población | 0/90 = 0.0 % [IC 95 %: 0.0–4.1 %] | 2024–2024 | COL 2024, CRI 2024, DOM 2024, GTM 2024, MEX 2024, PAN 2024 |
| `NE.EXP.GNFS.ZS` | % del PIB | 0/90 = 0.0 % [IC 95 %: 0.0–4.1 %] | 2024–2024 | COL 2024, CRI 2024, DOM 2024, GTM 2024, MEX 2024, PAN 2024 |
| `NY.GDP.MKTP.KD.ZG` | % anual | 0/90 = 0.0 % [IC 95 %: 0.0–4.1 %] | 2024–2024 | COL 2024, CRI 2024, DOM 2024, GTM 2024, MEX 2024, PAN 2024 |
| `SL.UEM.TOTL.ZS` | % de la fuerza laboral | 0/90 = 0.0 % [IC 95 %: 0.0–4.1 %] | 2024–2024 | COL 2024, CRI 2024, DOM 2024, GTM 2024, MEX 2024, PAN 2024 |
| `SP.POP.TOTL` | personas | 0/90 = 0.0 % [IC 95 %: 0.0–4.1 %] | 2024–2024 | COL 2024, CRI 2024, DOM 2024, GTM 2024, MEX 2024, PAN 2024 |

Cuadrícula: 540 filas; valores nulos: 0/540 = 0.0 % [IC 95 %: 0.0–0.7 %]. Año final de la cuadrícula: 2024. Los nulos se conservan como nulos; los datos son **anuales** y nunca "actuales".

## 9 · USGS


Eventos: **82**, de 2024-01-07T01:02:08Z a 2024-12-29T23:00:10Z. Magnitud: mín 3.2, mediana 4.5, máx 5.8.

| Magnitud | n | % (IC 95 %) |
|---|---|---|
| M < 3 | 0 | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] |
| M ≥ 3 | 1 | 1/82 = 1.2 % [IC 95 %: 0.2–6.6 %] |
| M ≥ 4 | 68 | 68/82 = 82.9 % [IC 95 %: 73.4–89.5 %] |
| M ≥ 5 | 13 | 13/82 = 15.9 % [IC 95 %: 9.5–25.3 %] |
| M ≥ 6 | 0 | 0/82 = 0.0 % [IC 95 %: 0.0–4.5 %] |

Valores de `place` (texto tras la última coma):

| place (país/zona) | n | % (IC 95 %) |
|---|---|---|
| `Panama` | 41 | 41/82 = 50.0 % [IC 95 %: 39.4–60.6 %] |
| `Costa Rica` | 17 | 17/82 = 20.7 % [IC 95 %: 13.4–30.7 %] |
| `Colombia` | 13 | 13/82 = 15.9 % [IC 95 %: 9.5–25.3 %] |
| `Nicaragua` | 6 | 6/82 = 7.3 % [IC 95 %: 3.4–15.1 %] |
| `south of Panama` | 5 | 5/82 = 6.1 % [IC 95 %: 2.6–13.5 %] |

`place` menciona Panamá: 46/82 = 56.1 % [IC 95 %: 45.3–66.3 %]. **La caja de USGS no es Panamá**: el resto cae en otros países; se muestra siempre el `place` original. 

**Desfase temporal:** los sismos son de 2024 (intervalo del PDF) y las noticias de septiembre–octubre de 2026: ningún sismo coincide en el tiempo con ningún titular de este snapshot, así que la coincidencia de sismos (± 2 días) no se puede probar con esta muestra.

## 10 · Revisión manual de titulares por tema


Se revisaron **a mano las 186 filas** del snapshot (no solo una muestra) y se les propuso un tema de la guía (`docs/exploracion_revision.csv`). **Es una propuesta del agente de desarrollo (`fuente = propuesta_agente`), pendiente de confirmación humana; no son etiquetas de evaluación (E1-06).** Las filas dudosas llevan `ambiguo = si`.

| Tema | Candidatos (palabra clave ∪ propuestos) | Asignados al tema | …sin ambigüedad | Marcados como ejemplo | ≥ 15 del spec |
|---|---|---|---|---|---|
| economia | 15 | 7 | 3 | 2 | **NO** (faltan 8) |
| logistica | 9 | 5 | 3 | 3 | **NO** (faltan 10) |
| turismo | 7 | 1 | 1 | 1 | **NO** (faltan 14) |
| servicios_publicos | 20 | 17 | 12 | 6 | sí |
| eventos_naturales | 22 | 2 | 2 | 2 | **NO** (faltan 13) |
| regulacion | 5 | 4 | 3 | 2 | **NO** (faltan 11) |

Fuera de los 6 temas: `no_es_panama` 125, `fuera_de_temas` 15, `sin_contenido` 10. Marcados como ejemplo para `temas.yaml`: 16.

**Tema de origen vs. revisión manual (D-62).** Cuántos de los registros que devolvió cada consulta de GDELT caen en alguno de los 6 temas, y cuántos en el tema de la consulta (por titular):

| Consulta de GDELT | Registros | En alguno de los 6 temas | En el tema de la consulta |
|---|---|---|---|
| logistica | 95 | 8/95 = 8.4 % [IC 95 %: 4.3–15.7 %] | 4/95 = 4.2 % [IC 95 %: 1.6–10.3 %] |
| turismo | 30 | 3/30 = 10.0 % [IC 95 %: 3.5–25.6 %] | 1/30 = 3.3 % [IC 95 %: 0.6–16.7 %] |
| economia | 55 | 8/55 = 14.5 % [IC 95 %: 7.6–26.2 %] | 5/55 = 9.1 % [IC 95 %: 3.9–19.6 %] |
| eventos_naturales | 0 | sin registros (0 días cubiertos) | — |

Por eso el tema de origen **nunca** sirve de etiqueta.

## 11 · Recomendaciones (no implementadas aquí)


### Para E1-03b (limpieza y ruido)

1. **Hipótesis: el mayor ruido sería "no es Panamá", no deportes ni farándula.** En la propuesta del agente (por titular, que es lo único que ve el
   sistema; no es una etiqueta humana): `no_es_panama` 125/186 = 67.2 % [IC 95 %: 60.2–73.5 %], `fuera_de_temas` 15/186 = 8.1 % [IC 95 %: 4.9–12.9 %], sin contenido 10/186 = 5.4 % [IC 95 %: 2.9–9.6 %]. Además, 115 de
   133 registros no TVN no nombran Panamá ni un término panameño en el titular. Causa probable (según
   `config/fuentes.yaml`): las consultas de GDELT piden `Panama` más un término amplio (`port`, `cargo`, `hotel`, `economy`…) sin
   anclarlos al titular; GDELT puede resolverlas sobre el texto del artículo (no verificado aquí: el crudo no está en git), así que el
   titular puede no decir Panamá aunque el artículo sí. Como el sistema solo lee el titular, no puede
   distinguir esos casos, y es una decisión de producto qué hacer con ellos. Un patrón de menciones de Panamá sobre el titular es el primer
   filtro, **no** se aplica a TVN, y la regla de la guía manda: lo que afecta a Panamá no es ruido (p. ej. la nota sindicada sobre
   El Niño en Latinoamérica es dudosa; el aviso de que un capitán de remolcador del Canal murió, no).
2. **Titulares sin contenido** (solo dominio, `Inicio |`, `Preview -`): patrón de `titulo_generico` en `config/ruido.yaml`;
   hoy 9 de 186.
3. **Falsos Panamá concretos:** `Panama City Beach` / `PCB` (turismo de Florida) cae en el tema Turismo. Lista en YAML, no en código.
4. **Limpieza:** sufijos de medio, espacios antes de puntuación (`21 , 2 %`, `US$84 . 000`; es la tokenización de GDELT, dañan
   los embeddings y las cifras), barra pegada de TVN (`resultados| texto`) y prefijos de sección de TVN (`Liga de Naciones … resultados|`).
5. **La sección de TVN es solo una señal CANDIDATA de `fuera_de_temas`; decide el titular.** `tvmax`, `entretenimiento`, `gente-tvn` y
   `videos` suelen ser deportes, farándula o cultura, pero varios de `tvmax`/`entretenimiento` tratan de otros países (`no_es_panama`:
   p. ej. Messi/Argentina, Pedro Pascal), y los de `contenido-exclusivo` son sobre Panamá y pueden estar en los temas (transporte público,
   sequía). Un patrón de URL no debe excluir ni etiquetar por sí solo: úsese para subir la sospecha y confirmar con el titular. `mundo` es
   noticia internacional: `no_es_panama` salvo que afecte a Panamá.
6. **Duplicados:** 7 grupos de titulares casi idénticos; los sindicados (Xinhua, Trump/Europa) aparecen en decenas de
   dominios. Deduplicar por URL no los junta: hay que contar procedencias **independientes**, no republicaciones (E1-08).

### Para E1-05 (`reglas_v1.3.yaml`, `temas.yaml`)

1. **U (urgencia):** GDELT no trae `fecha_publicacion`. La regla debe usar `fecha_publicacion` solo cuando exista y, si no,
   tratar la detección como cota de "visto por GDELT" (nunca como publicación). Con esta muestra, solo
   53 de 186 noticias tienen publicación: **U será desconocida para la mayoría de los grupos**; hay que definir
   su valor por defecto y decirlo en la ficha.
2. **E (evidencia):** el término "titulares con medio y fecha de publicación conocidos" (0.2) quedará bajo para todo lo que viene de GDELT.
3. **`temas.yaml`:** con esta muestra no se llega a ~10 ejemplos reales por tema en todos los temas
   (asignados: economia 7, logistica 5, turismo 1, servicios_publicos 17, eventos_naturales 2, regulacion 4). `eventos_naturales` no tiene cobertura de GDELT
   (0 días) y `turismo`/`regulacion` casi no tienen titulares propios. Completar con una extracción nueva cuando GDELT deje de limitar, o
   redactar esos ejemplos como ilustrativos (como en la guía) y **no** presentarlos como reales. Los ejemplos propuestos están en
   `config/ejemplos_excluidos.txt`; E1-05 agrega ahí los que sume y **elimina de ese archivo los que no use** (excluir de la evaluación
   un titular que no es ejemplo solo resta datos).
4. **Alcance geográfico (I):** los titulares de TVN nombran provincia/distrito (Chiriquí, Veraguas, Coclé, Colón, San Miguelito, La Chorrera);
   la lista de provincias y distritos del YAML tiene ejemplos reales para probarla.
5. **Agencias:** el RSS de TVN **no trae firma** (150/150 entradas sin autor ni `dc:creator`), así que la lista `agencias` no puede derivarse de él. Las procedencias independientes (CU-03) salen del dominio del medio y de la repetición del titular, no de la firma; la lista de agencias solo serviría si un titular de GDELT la nombra (`- EFE`, `Xinhua`) y eso se decide en E1-05/E1-08. No inventar agencias ni tipos de firma.
6. **T01 (nulos):** la cuadrícula del Banco Mundial de esta corrida no tiene ningún nulo (0/540), contra lo que se esperaba; las
   pruebas de nulos (T01, T04) deben usar fixtures sintéticos (`SYN-`), no depender de este snapshot. Los sismos de USGS son de 2024 y las
   noticias de 2026: la coincidencia ± 2 días de E1-09 se prueba con datos sintéticos.
7. **Consultas de GDELT:** el desequilibrio de temas (`logistica` domina; `eventos_naturales` = 0) sugiere revisar las consultas antes
   del evento, no el clasificador.

