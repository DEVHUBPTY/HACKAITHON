# Fuentes de datos y notas de implementación (sección 12 del PDF)

Referencias del PDF [1]–[9], qué fuente alimentan, dónde se consultan y qué condiciones hay que respetar.
Verificado el 2026-10-06 en la documentación pública. **Se vuelve a verificar al congelar el snapshot** (lo pide el PDF).

## A · Noticias

### [1] TVN Panamá · sitio oficial
- **Dónde:** https://www.tvn-2.com
- **Para qué:** identificar el medio y sus secciones; enlaces de las noticias de TVN.

### [2] TVN · feed RSS público
- **Dónde:** `https://www.tvn-2.com/rss/` (URL tomada del hipervínculo de la referencia [2] del PDF; verificada el 2026-10-06: responde 200 con ~150 ítems).
- **Qué trae:** noticias, fechas y descripciones. No trae categoría: el tema de origen es la primera sección de la ruta de la URL (ej. `nacionales`, `economia`).
- **Condiciones:** que el RSS sea público **no implica licencia abierta** sobre artículos, videos o imágenes. Solo metadatos; la descripción, solo para uso interno (D-31).
- **Cuidado:** el RSS no conserva todo el histórico (R-23).

### [3] GDELT · API DOC 2.0
- **Dónde:** `https://api.gdeltproject.org/api/v2/doc/doc` · documentación: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- **Cómo:** `mode=ArtList`, `format=json`, `maxrecords=250`, filtros de dominio e idioma y ventana temporal. Sin clave ni autenticación.
- **Consultas (E0-04, seguimiento):** cada tema tiene dos patas, una llamada por pata y rango (`config/fuentes.yaml` → `gdelt.consultas`; las arma `src/consultas_gdelt.py`): `locales` = `(términos en español) sourcecountry:panama` e `internacional` = `("frase específica de Panamá" OR ...) -sourcecountry:panama`. Operadores documentados en el blog de la API: frase entre comillas, `(a OR b)` sin anidar, `sourcecountry:` (nombre o FIPS), prefijo `-` para excluir. Motivo: la versión anterior (`Panama` + palabra genérica) traía ~67 % de ruido (Panama City Beach, Panama Papers, etc.; E0-09). El motivo queda en el manifest (`consultas.gdelt.motivo_cambio_consultas` y el historial). Los crudos se nombran `gdelt_<tema>__<pata>_...`; los de la versión anterior (sin pata) no cuentan como cobertura ni alimentan `noticias.csv` (D-83): siguen intactos en `raw/` y el manifest los lista como `crudos_excluidos`, con su consulta histórica en `consultas.gdelt.consultas_historicas`.
- **Qué trae por artículo:** `url`, `url_mobile`, `title`, `seendate`, `socialimage`, `domain`, `language`, `sourcecountry`.
- **Cuidado:**
  - Máximo 250 resultados por consulta → dividir por fechas.
  - **`seendate` es la fecha de detección**, no la de publicación (no hay campo de publicación).
  - **Solo cubre aproximadamente los últimos 3 meses** (R-27). No sirve para reconstruir noticias más antiguas.
  - `socialimage` **no se guarda** (derechos de imagen).
  - No confundir con los servicios comerciales llamados *GDELT Cloud*.
  - La API no transfiere derechos de los medios enlazados.

## B · Banco Mundial

### [4] Indicators API v2 · documentación
- **Dónde:** `https://api.worldbank.org/v2/country/{ISO3;ISO3…}/indicator/{CODIGO}?format=json&date=2010:2024&per_page=1000` · documentación: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
- **Cómo:** una consulta por indicador; países separados por `;`. Sin clave. `per_page=1000` evita la paginación (el valor por defecto es 50).
- **Cuidado:** el año más reciente suele venir vacío; los valores se revisan con el tiempo → registrar la fecha de extracción.

### [5] Banco Mundial · indicadores de Panamá
- **Para qué:** consultar la ficha de cada indicador y sus metadatos (unidad, fuente original, excepciones).

### [6] Banco Mundial · términos para datasets
- **Condiciones:** licencia general CC BY 4.0 con **atribución obligatoria**; revisar **excepciones de terceros por indicador**.
- **Cuidado:** el período de referencia del dato **no coincide necesariamente** con el año de extracción.

## C · USGS

### [7] Catálogo sísmico y parámetros del servicio
- **Dónde:** `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-12-31&minlatitude=5&maxlatitude=12&minlongitude=-86&maxlongitude=-76&minmagnitude=3` · documentación: https://earthquake.usgs.gov/fdsnws/event/1/
- **Cómo:** una sola consulta; el servicio admite hasta 20.000 eventos por consulta.
- **Trazabilidad:** usar el **ID y la URL de cada evento**.
- **Condiciones:** confirmar las aplicables a datos o elementos de terceros.

## D · Superintendencia de Bancos de Panamá (solo banca)

### [8] Estadísticas financieras · [9] Estudios e informes
- **Dónde:** https://www.superbancos.gob.pa (sección de estadísticas y analítica, e informes publicados).
- **Qué hay:** estadísticas mensuales del sistema (balance, resultados, cartera de crédito, crédito por actividad, tasas), en versión individual y consolidada.
- **Condiciones (aviso de la propia SBP):** información **solo informativa**, sujeta a cambios; la SBP **no se hace responsable** de análisis de terceros; sus opiniones formales están solo en sus informes oficiales.
- **Cómo:** manual. Seleccionar informes y columnas **antes del evento**, conservando las advertencias de uso (E3-02).

## Qué se verifica al congelar el snapshot
- [x] URL del RSS de TVN confirmada y funcionando (2026-10-06)
- [ ] GDELT responde y la ventana pedida está dentro de su cobertura (~3 meses)
- [ ] Banco Mundial: excepciones de licencia por indicador revisadas
- [ ] USGS: condiciones de terceros confirmadas
- [ ] SBP: condiciones de reutilización registradas
- [ ] Todo anotado en `fuentes.json`, el manifest y el Catálogo de datos
