# Exploración de la muestra real (E0-09)


> Generado por `poetry run python -m scripts.explorar`. **Offline:** usa `data/processed/`, el crudo versionado de Banco Mundial y USGS y, en solo lectura (`--crudos`), los crudos de RSS y GDELT que no están en el repositorio (no se copian). Fase: Preparación (D-74). No muestra descripciones del RSS (D-31, D-72) ni nombres de autores (D-32). Los porcentajes llevan su n e intervalo de Wilson al 95 %. **El IC de Wilson supone una muestra aleatoria; este snapshot NO lo es (ventana corta, consultas dirigidas, cobertura parcial): los intervalos son descriptivos, no inferenciales.** Todo lo marcado como ruido es **candidato**: el etiquetado es E1-03b / E1-06.


**Muestra:** snapshot de E0-04 (`fecha_corte_UTC` 2026-10-07T00:41:03Z); no se descargó una muestra nueva porque GDELT está limitando las solicitudes (HTTP 429). **No es una muestra de 1–3 días con una consulta por tema**: es lo que quedó cubierto (ver Cobertura).


## 1 · Perfil de campos


**noticias.csv** (n = 221)

| Campo | Presente | Nulo | Formato observado |
|---|---|---|---|
| `id_noticia` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | prefijo `NOT-` ×221; únicos 221/221 |
| `titulo` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | texto, largo mín 9 · mediana 77 · máx 171 |
| `url` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | texto, largo mín 38 · mediana 110 · máx 189; https: 186/221 |
| `medio` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | texto, largo mín 5 · mediana 10 · máx 25 |
| `idioma` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | `a+` ×221 |
| `fecha_publicacion` | 88/221 = 39.8 % [IC 95 %: 33.6–46.4 %] | 133/221 = 60.2 % [IC 95 %: 53.6–66.4 %] | `9+-9+-9+a9+:9+:9+a` ×88 |
| `fecha_deteccion` | 133/221 = 60.2 % [IC 95 %: 53.6–66.4 %] | 88/221 = 39.8 % [IC 95 %: 33.6–46.4 %] | `9+-9+-9+a9+:9+:9+a` ×133 |
| `fecha_extraccion` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | `9+-9+-9+a9+:9+:9+a` ×221 |
| `tema` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | `a+` ×174 · `a+\|a+` ×39 |
| `origen` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | `a+` ×133 · `a+ a+` ×88 |
| `alcance_texto` | 221/221 = 100.0 % [IC 95 %: 98.3–100.0 %] | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | `a+ a+ a+ a+/a+` ×221 |

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


Noticias en el snapshot: **221**. TVN RSS: **88/221 = 39.8 % [IC 95 %: 33.6–46.4 %]**.

### Por medio

| Medio | n | % (IC 95 %) |
|---|---|---|
| `TVN Panamá` | 88 | 88/221 = 39.8 % [IC 95 %: 33.6–46.4 %] |
| `newsroomamerica.com` | 7 | 7/221 = 3.2 % [IC 95 %: 1.5–6.4 %] |
| `panamaamerica.com.pa` | 6 | 6/221 = 2.7 % [IC 95 %: 1.3–5.8 %] |
| `listindiario.com` | 3 | 3/221 = 1.4 % [IC 95 %: 0.5–3.9 %] |
| `prensa.com` | 3 | 3/221 = 1.4 % [IC 95 %: 0.5–3.9 %] |
| `bignewsnetwork.com` | 3 | 3/221 = 1.4 % [IC 95 %: 0.5–3.9 %] |
| `unosantafe.com.ar` | 2 | 2/221 = 0.9 % [IC 95 %: 0.2–3.2 %] |
| `laestrella.com.pa` | 2 | 2/221 = 0.9 % [IC 95 %: 0.2–3.2 %] |
| `trinidadtimes.com` | 2 | 2/221 = 0.9 % [IC 95 %: 0.2–3.2 %] |
| `gfmag.com` | 2 | 2/221 = 0.9 % [IC 95 %: 0.2–3.2 %] |

_n = 221; 110 valores distintos, se muestran 10._

### Por idioma

| Idioma (ISO 639-1) | n | % (IC 95 %) |
|---|---|---|
| `es` | 144 | 144/221 = 65.2 % [IC 95 %: 58.7–71.1 %] |
| `en` | 50 | 50/221 = 22.6 % [IC 95 %: 17.6–28.6 %] |
| `de` | 10 | 10/221 = 4.5 % [IC 95 %: 2.5–8.1 %] |
| `zh` | 3 | 3/221 = 1.4 % [IC 95 %: 0.5–3.9 %] |
| `ru` | 3 | 3/221 = 1.4 % [IC 95 %: 0.5–3.9 %] |
| `ko` | 2 | 2/221 = 0.9 % [IC 95 %: 0.2–3.2 %] |
| `ro` | 1 | 1/221 = 0.5 % [IC 95 %: 0.1–2.5 %] |
| `uk` | 1 | 1/221 = 0.5 % [IC 95 %: 0.1–2.5 %] |
| `hr` | 1 | 1/221 = 0.5 % [IC 95 %: 0.1–2.5 %] |
| `fr` | 1 | 1/221 = 0.5 % [IC 95 %: 0.1–2.5 %] |

_n = 221; 15 valores distintos, se muestran 10._

Español: 144/221 = 65.2 % [IC 95 %: 58.7–71.1 %].

### Por país del medio (`fuentes.json`)

| País | n | % (IC 95 %) |
|---|---|---|
| `Panamá` | 101 | 101/221 = 45.7 % [IC 95 %: 39.3–52.3 %] |
| `Estados Unidos` | 37 | 37/221 = 16.7 % [IC 95 %: 12.4–22.2 %] |
| `Argentina` | 11 | 11/221 = 5.0 % [IC 95 %: 2.8–8.7 %] |
| `Alemania` | 10 | 10/221 = 4.5 % [IC 95 %: 2.5–8.1 %] |
| `China` | 6 | 6/221 = 2.7 % [IC 95 %: 1.3–5.8 %] |
| `Colombia` | 5 | 5/221 = 2.3 % [IC 95 %: 1.0–5.2 %] |
| `Rusia` | 5 | 5/221 = 2.3 % [IC 95 %: 1.0–5.2 %] |
| `(sin país)` | 4 | 4/221 = 1.8 % [IC 95 %: 0.7–4.6 %] |
| `México` | 4 | 4/221 = 1.8 % [IC 95 %: 0.7–4.6 %] |
| `Reino Unido` | 3 | 3/221 = 1.4 % [IC 95 %: 0.5–3.9 %] |

_n = 221; 36 valores distintos, se muestran 10._

Sin país conocido: 4/221 = 1.8 % [IC 95 %: 0.7–4.6 %].

### Por categoría del RSS (tema de origen de TVN = primera sección de la URL)

| Sección RSS | n | % (IC 95 %) |
|---|---|---|
| `nacionales` | 35 | 35/88 = 39.8 % [IC 95 %: 30.2–50.2 %] |
| `tvmax` | 18 | 18/88 = 20.5 % [IC 95 %: 13.3–30.0 %] |
| `mundo` | 17 | 17/88 = 19.3 % [IC 95 %: 12.4–28.8 %] |
| `entretenimiento` | 13 | 13/88 = 14.8 % [IC 95 %: 8.8–23.7 %] |
| `contenido-exclusivo` | 3 | 3/88 = 3.4 % [IC 95 %: 1.2–9.5 %] |
| `videos` | 1 | 1/88 = 1.1 % [IC 95 %: 0.2–6.2 %] |
| `gente-tvn` | 1 | 1/88 = 1.1 % [IC 95 %: 0.2–6.2 %] |

_n = 88; 7 valores distintos._

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
| 2026-10-06 | 4 | 52 |
| 2026-10-07 | 0 | 6 |

_Días con datos: 7. La hora de Panamá solo se usa en la interfaz._

## 3 · Preguntas del spec


### ¿GDELT trae fecha de publicación?

**No.** GDELT DOC 2.0 (`mode=artlist`) entrega `seendate` (cuándo GDELT vio la noticia) y no la fecha en que el medio la publicó. En el snapshot, de los registros que vinieron solo de GDELT (n = 133): `fecha_publicacion` presente en 0/133 = 0.0 % [IC 95 %: 0.0–2.8 %]; `fecha_deteccion` presente en 133/133 = 100.0 % [IC 95 %: 97.2–100.0 %]. Registros presentes en el RSS **y** en GDELT: 0 de 221.

**Verificado en el crudo** (9 archivos, 370 artículos; los archivos pueden repetir artículos entre rangos): campos con valor: `url` ×370, `title` ×370, `seendate` ×370, `domain` ×370, `language` ×370, `sourcecountry` ×358, `socialimage` ×286, `url_mobile` ×71. Ninguno es una fecha de publicación; `seendate` es la única fecha.

**Efecto:** U (urgencia) y T03 (noticia recirculada) no pueden usar GDELT como fecha del hecho; solo el RSS de TVN la trae (88/221 = 39.8 % [IC 95 %: 33.6–46.4 %] de las noticias). Una fecha de detección reciente de una nota vieja es justo el caso de T03. Ver recomendaciones.

### ¿El RSS de TVN trae autor o firma?

**Verificado: el RSS de TVN no trae autor ni firma** (300/300 entradas sin ninguno de los campos buscados). Entradas en 2 crudo(s): 300. Campos de firma buscados: author, dc_creator, creator.

| Tipo de firma | n | % (IC 95 %) |
|---|---|---|
| sin firma | 300 | 300/300 = 100.0 % [IC 95 %: 98.7–100.0 %] |

Categorías del RSS (`<category>`, solo conteos): 300/300 = 100.0 % [IC 95 %: 98.7–100.0 %] de las entradas traen alguna; `TVN Media` ×132, `Medios de comunicación` ×14, `Panamá` ×12, `Medio Ambiente` ×12, `Convenio` ×12, `Líderes 360` ×10, `Liderazgo` ×10, `empresas` ×10, `gente tvn` ×10, `Lionel Messi` ×9.

Agencias: ninguna

Claves presentes en las entradas (sin descripción): `title` ×300, `title_detail` ×300, `link` ×300, `id` ×300, `guidislink` ×300, `published` ×300, `published_parsed` ×300, `updated` ×300, `updated_parsed` ×300, `media_thumbnail` ×300, `href` ×300, `media_keywords` ×300, `tags` ×300

## 4 · Calidad de los titulares


| Señal (candidata) | Todas | TVN RSS | GDELT |
|---|---|---|---|
| Sufijo de medio (` - Medio`, ` \| Medio`) | 27/221 = 12.2 % [IC 95 %: 8.5–17.2 %] | 1/88 = 1.1 % [IC 95 %: 0.2–6.2 %] | 26/133 = 19.5 % [IC 95 %: 13.7–27.1 %] |
| Entidad HTML sin decodificar (`&amp;`, `&#39;`) | 0/221 = 0.0 % [IC 95 %: 0.0–1.7 %] | 0/88 = 0.0 % [IC 95 %: 0.0–4.2 %] | 0/133 = 0.0 % [IC 95 %: 0.0–2.8 %] |
| Espacio antes de puntuación (tokenización de GDELT: `21 , 2 %`) | 62/221 = 28.1 % [IC 95 %: 22.5–34.3 %] | 0/88 = 0.0 % [IC 95 %: 0.0–4.2 %] | 62/133 = 46.6 % [IC 95 %: 38.4–55.1 %] |
| Barra pegada a la palabra (`resultados\| texto`, estilo TVN) | 10/221 = 4.5 % [IC 95 %: 2.5–8.1 %] | 10/88 = 11.4 % [IC 95 %: 6.3–19.7 %] | 0/133 = 0.0 % [IC 95 %: 0.0–2.8 %] |
| Titular sin contenido (solo dominio, `Inicio \|`, `Preview -`) | 9/221 = 4.1 % [IC 95 %: 2.2–7.6 %] | 0/88 = 0.0 % [IC 95 %: 0.0–4.2 %] | 9/133 = 6.8 % [IC 95 %: 3.6–12.4 %] |

## 5 · Candidatos a ruido


| Señal | Candidatos / base |
|---|---|
| Titular sin contenido | 9/221 = 4.1 % [IC 95 %: 2.2–7.6 %] |
| Medio no TVN cuyo titular no nombra Panamá ni un término panameño | 115/133 = 86.5 % [IC 95 %: 79.6–91.3 %] |
| Falso Panamá conocido (Panama City Beach…) | 1/221 = 0.5 % [IC 95 %: 0.1–2.5 %] |
| Palabras de deportes | 26/221 = 11.8 % [IC 95 %: 8.2–16.7 %] |
| Palabras de farándula | 9/221 = 4.1 % [IC 95 %: 2.2–7.6 %] |
| Autopromoción de TVN | 6/88 = 6.8 % [IC 95 %: 3.2–14.1 %] |
| Cualquiera de las señales | 152/221 = 68.8 % [IC 95 %: 62.4–74.5 %] |

Son **candidatos por palabras clave** (listas en `config/exploracion.yaml`). No miden precisión; la medición contra etiquetas humanas es `eval.ruido` (E1-03b).

## 6 · Titulares casi duplicados (pistas de agrupación de eventos)


Grupos de ≥ 2 titulares casi idénticos (texto normalizado, sin sufijo de medio): **8**; cubren 49/221 = 22.2 % [IC 95 %: 17.2–28.1 %] de los registros.

| Registros | Medios | Idiomas | Titular (primero) |
|---|---|---|---|
| 20 | 18 | en | World Insights : Intensifying El Nino deepens economic risks across LatAm - Xinhua |
| 10 | 10 | de | Trump streicht Europa - Hilfe , lenkt Millionen nach Lateinamerika |
| 7 | 1 | en | newsroomamerica . com |
| 4 | 1 | es | Lionel Messi despedida \| Argentina vs Benín: El último partido, fiesta de agradecimiento en el Monumental |
| 2 | 1 | es | ¿ Cómo se fija el precio del combustible en Panamá ? El MEF explica la fórmula quincenal tras aprobarse nuevo  |
| 2 | 2 | es | Jóvenes de Haina que se fueron engañados para pelear en Rusia piden auxilio para retornar al país |
| 2 | 2 | en | Kiev reaping huge profits on EU arms supplies Russian intel |
| 2 | 2 | en | Remembering The False Gloom And Doom Of The 1992 Elections ... And The Upcoming Midterms |

_No detecta traducciones: «Trump streicht Europa-Hilfe…» (de) y «Допомога США Європі…» (uk) son el mismo evento y quedan en grupos distintos. Eso lo cubre la similitud semántica (E1-08)._

## 7 · Cobertura y vacíos


Consultas vigentes (E0-04, dos patas por tema):

| Tema GDELT | Días cubiertos | Días esperados | Cobertura (IC 95 %) |
|---|---|---|---|
| economia | 0 | 30 | 0/30 = 0.0 % [IC 95 %: 0.0–11.4 %] |
| eventos_naturales | 0 | 30 | 0/30 = 0.0 % [IC 95 %: 0.0–11.4 %] |
| logistica | 0 | 30 | 0/30 = 0.0 % [IC 95 %: 0.0–11.4 %] |
| turismo | 0 | 30 | 0/30 = 0.0 % [IC 95 %: 0.0–11.4 %] |

Las noticias de GDELT del snapshot salen de los crudos de las consultas anteriores a E0-04 (D-89); su cobertura va aparte de la tabla anterior, que mide solo las consultas vigentes:

| Tema (consulta histórica) | Crudos | Días cubiertos | Días esperados | Cobertura (IC 95 %) |
|---|---|---|---|---|
| economia | 2 | 4 | 30 | 4/30 = 13.3 % [IC 95 %: 5.3–29.7 %] |
| eventos_naturales | 0 | 0 | 30 | 0/30 = 0.0 % [IC 95 %: 0.0–11.4 %] |
| logistica | 5 | 4 | 30 | 4/30 = 13.3 % [IC 95 %: 5.3–29.7 %] |
| turismo | 2 | 4 | 30 | 4/30 = 13.3 % [IC 95 %: 5.3–29.7 %] |

Días sin resolver (suma de rangos):

| Tema | Motivo | Días |
|---|---|---|
| economia | no_solicitado | 30 |
| eventos_naturales | no_solicitado | 30 |
| logistica | no_solicitado | 30 |
| turismo | no_solicitado | 30 |

RSS: de 2026-09-29T01:23:06Z a 2026-10-07T00:30:57Z; detección GDELT: de 2026-10-01T16:00:00Z a 2026-10-06T08:30:00Z.

**`eventos_naturales` tiene 0 días cubiertos** (vigentes e históricos): no hay ni un titular de GDELT en ese tema, y los sismos/lluvias son un tema central del reto. Los números de este informe no representan los 30 días de la ventana (D-74).

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


Se revisaron **a mano las 221 filas** del snapshot (no solo una muestra) y se les propuso un tema de la guía (`docs/exploracion_revision.csv`). **Es una propuesta del agente de desarrollo (`fuente = propuesta_agente`), pendiente de confirmación humana; no son etiquetas de evaluación (E1-06).** Las filas dudosas llevan `ambiguo = si`.

| Tema | Candidatos (palabra clave ∪ propuestos) | Asignados al tema | …sin ambigüedad | Marcados como ejemplo | ≥ 15 del spec |
|---|---|---|---|---|---|
| economia | 19 | 10 | 6 | 2 | **NO** (faltan 5) |
| logistica | 10 | 5 | 3 | 3 | **NO** (faltan 10) |
| turismo | 7 | 1 | 1 | 1 | **NO** (faltan 14) |
| servicios_publicos | 27 | 24 | 16 | 6 | sí |
| eventos_naturales | 22 | 2 | 2 | 2 | **NO** (faltan 13) |
| regulacion | 5 | 4 | 3 | 2 | **NO** (faltan 11) |

Fuera de los 6 temas: `no_es_panama` 141, `fuera_de_temas` 24, `sin_contenido` 10. Marcados como ejemplo para `temas.yaml`: 16.

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
   sistema; no es una etiqueta humana): `no_es_panama` 141/221 = 63.8 % [IC 95 %: 57.3–69.9 %], `fuera_de_temas` 24/221 = 10.9 % [IC 95 %: 7.4–15.6 %], sin contenido 10/221 = 4.5 % [IC 95 %: 2.5–8.1 %]. Además, 115 de
   133 registros no TVN no nombran Panamá ni un término panameño en el titular. Causa probable (según
   `config/fuentes.yaml`): las consultas de GDELT piden `Panama` más un término amplio (`port`, `cargo`, `hotel`, `economy`…) sin
   anclarlos al titular; GDELT puede resolverlas sobre el texto del artículo (no verificado aquí: el crudo no está en git), así que el
   titular puede no decir Panamá aunque el artículo sí. Como el sistema solo lee el titular, no puede
   distinguir esos casos, y es una decisión de producto qué hacer con ellos. Un patrón de menciones de Panamá sobre el titular es el primer
   filtro, **no** se aplica a TVN, y la regla de la guía manda: lo que afecta a Panamá no es ruido (p. ej. la nota sindicada sobre
   El Niño en Latinoamérica es dudosa; el aviso de que un capitán de remolcador del Canal murió, no).
2. **Titulares sin contenido** (solo dominio, `Inicio |`, `Preview -`): patrón de `titulo_generico` en `config/ruido.yaml`;
   hoy 9 de 221.
3. **Falsos Panamá concretos:** `Panama City Beach` / `PCB` (turismo de Florida) cae en el tema Turismo. Lista en YAML, no en código.
4. **Limpieza:** sufijos de medio, espacios antes de puntuación (`21 , 2 %`, `US$84 . 000`; es la tokenización de GDELT, dañan
   los embeddings y las cifras), barra pegada de TVN (`resultados| texto`) y prefijos de sección de TVN (`Liga de Naciones … resultados|`).
5. **La sección de TVN es solo una señal CANDIDATA de `fuera_de_temas`; decide el titular.** `tvmax`, `entretenimiento`, `gente-tvn` y
   `videos` suelen ser deportes, farándula o cultura, pero varios de `tvmax`/`entretenimiento` tratan de otros países (`no_es_panama`:
   p. ej. Messi/Argentina, Pedro Pascal), y los de `contenido-exclusivo` son sobre Panamá y pueden estar en los temas (transporte público,
   sequía). Un patrón de URL no debe excluir ni etiquetar por sí solo: úsese para subir la sospecha y confirmar con el titular. `mundo` es
   noticia internacional: `no_es_panama` salvo que afecte a Panamá.
6. **Duplicados:** 8 grupos de titulares casi idénticos; los sindicados (Xinhua, Trump/Europa) aparecen en decenas de
   dominios. Deduplicar por URL no los junta: hay que contar procedencias **independientes**, no republicaciones (E1-08).

### Para E1-05 (`reglas_v1.3.yaml`, `temas.yaml`)

1. **U (urgencia):** GDELT no trae `fecha_publicacion`. La regla debe usar `fecha_publicacion` solo cuando exista y, si no,
   tratar la detección como cota de "visto por GDELT" (nunca como publicación). Con esta muestra, solo
   88 de 221 noticias tienen publicación: **U será desconocida para la mayoría de los grupos**; hay que definir
   su valor por defecto y decirlo en la ficha.
2. **E (evidencia):** el término "titulares con medio y fecha de publicación conocidos" (0.2) quedará bajo para todo lo que viene de GDELT.
3. **`temas.yaml`:** con esta muestra no se llega a ~10 ejemplos reales por tema en todos los temas
   (asignados: economia 10, logistica 5, turismo 1, servicios_publicos 24, eventos_naturales 2, regulacion 4). `eventos_naturales` no tiene cobertura de GDELT
   (0 días) y `turismo`/`regulacion` casi no tienen titulares propios. Completar con una extracción nueva cuando GDELT deje de limitar, o
   redactar esos ejemplos como ilustrativos (como en la guía) y **no** presentarlos como reales. Los ejemplos propuestos están en
   `config/ejemplos_excluidos.txt`; E1-05 agrega ahí los que sume y **elimina de ese archivo los que no use** (excluir de la evaluación
   un titular que no es ejemplo solo resta datos).
4. **Alcance geográfico (I):** los titulares de TVN nombran provincia/distrito (Chiriquí, Veraguas, Coclé, Colón, San Miguelito, La Chorrera);
   la lista de provincias y distritos del YAML tiene ejemplos reales para probarla.
5. **Agencias:** el RSS de TVN **no trae firma** (300/300 entradas sin autor ni `dc:creator`), así que la lista `agencias` no puede derivarse de él. Las procedencias independientes (CU-03) salen del dominio del medio y de la repetición del titular, no de la firma; la lista de agencias solo serviría si un titular de GDELT la nombra (`- EFE`, `Xinhua`) y eso se decide en E1-05/E1-08. No inventar agencias ni tipos de firma.
6. **T01 (nulos):** la cuadrícula del Banco Mundial de esta corrida no tiene ningún nulo (0/540), contra lo que se esperaba; las
   pruebas de nulos (T01, T04) deben usar fixtures sintéticos (`SYN-`), no depender de este snapshot. Los sismos de USGS son de 2024 y las
   noticias de 2026: la coincidencia ± 2 días de E1-09 se prueba con datos sintéticos.
7. **Consultas de GDELT:** el desequilibrio de temas (`logistica` domina; `eventos_naturales` = 0) sugiere revisar las consultas antes
   del evento, no el clasificador.

