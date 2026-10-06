# Registro de parámetros (D-57)

Todo número que use el sistema está aquí, con su **origen** y **cómo se valida**. Los valores viven en `config/*.yaml`; este documento explica de dónde salen.

**Origen:** `PDF` = lo fija el reto · `Práctica` = práctica reconocida · `Calibrado` = se ajusta con datos etiquetados · `Supuesto` = elección razonable del equipo, todavía no demostrada.

> Un **supuesto** se presenta siempre como supuesto, en el pitch y en Notion.

## Puntaje de atención

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Pesos R · I · U · N · E | 30 · 25 · 20 · 15 · 10 | PDF | X02 (sensibilidad) · Precision@5 |
| Rangos | bajo [0,40) · medio [40,70) · alto [70,100] | PDF | — |
| Desempate | Mayor U, luego menor ID | PDF | Test |
| Partes de R (foco · temática) | 0.5 · 0.5 | Supuesto | X02 |
| Foco (Panamá sujeto · otro país que afecta) | 1 · 0.5 | Supuesto | Revisión editorial |
| Similitudes en percentil | — | Calibrado | X04 (distribución) |
| Partes de I (subtema · geográfico) | 0.5 · 0.5 | Supuesto | X02 |
| Alcance por subtema (38 subtemas, 0.4 a 1.0) | Tabla en `reglas_v1.3.yaml` | Supuesto (criterio editorial; el diseño pide la tabla documentada en YAML, D-35) | Precision@5 y revisión editorial |
| Alcance geográfico | nacional 1 · provincial 0.6 · local 0.3 · desconocido 0.5 | Supuesto | X02 |
| Ventana de urgencia U: horas con U = 1 · días con U = 0 (lineal entre ambos) | 24 h · 7 días | Diseño (v1.3, D-35: <24 h y 7 días) | X02 |
| Partes de E (procedencias · oficial · identificable) | 0.5 · 0.3 · 0.2 | Supuesto | X02 |
| Tope de procedencias en E | 3 | Supuesto | X02 |
| U sin fecha de publicación en ningún titular | Usa `fecha_deteccion` y agrega el vacío "urgencia estimada: fecha de publicación desconocida" | Supuesto (53 de 186 noticias del snapshot traen publicación; GDELT no) | Test de E1-10 |
| N del primer grupo (sin grupos previos) | 1.0 | Supuesto | Test de E1-10 |
| Listas de provincias, comarcas y distritos | 10 · 6 · 60 | Práctica (división político-administrativa; lista parcial de distritos) | Titulares reales de TVN; `validar_coherencia` |
| Agencias de noticias para el tipo de firma | 10 nombres | Práctica (el RSS de TVN no trae firma, no se derivan de datos) | Se usa solo si un titular de GDELT la nombra |

## Estado de evidencia

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Procedencias para "parcial" / "suficiente" | 2 | Práctica (regla periodística de las dos fuentes independientes) | Revisión editorial |
| Dato oficial obligatorio si hay cifras | — | PDF (secciones 7 y 9: toda cifra con evidencia) | Test |
| Una procedencia + dato o evento oficial = "parcial" | 1 | Diseño (estado de evidencia: parcial = 2 o más procedencias, o 1 + dato oficial) | Test de E1-10 |
| Tabla de acciones 3×3 (editorial y banca) | Editorial: Alto = Producir borrador · Completar evidencia y producir · Investigar ya; Medio = Borrador opcional · Vigilar · Vigilar; Bajo = Archivar como contexto · Archivar · Archivar. Banca: Alto = Incluir en el boletín como observación · Incluir como señal a confirmar · Seguimiento prioritario; Medio = Incluir como contexto · Seguimiento · Seguimiento; Bajo = Archivar | Diseño (D-35, D-38; página "Diseño de solución", Acción recomendada) | Test que fija las 9 celdas; ninguna dice publicar |
| "Suficiente" exige sin contradicción abierta y, si hay cifras, dato oficial | Regla | Diseño (estado de evidencia) | Test de E1-10 |
| Vínculos con evidencia oficial (6 subtemas + Logística/Canal indirecto) y sus 5 motivos sin vínculo | Tabla en `vinculos.yaml` | Diseño ("Vínculos con evidencia oficial") | Test que fija la tabla exacta |
| Sectores de banca (5) y su mapeo desde los temas | `temas.yaml` y `modalidad_banca.yaml` | Diseño (D-11, propuesta) | Validación del esquema |
| Alcance por sector (banca, sustituye al del subtema) | Por definir al crear `modalidad_banca.yaml` | Supuesto | X02 |
| Cantidad de temas | 6 | PDF (sección 3, etapa 2) | `cantidad_temas` en `temas.yaml`, validada |

## Organizar y contextualizar

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Umbral de agrupación | Por definir | Calibrado (D-16) | F1 de pares con etiquetas · curva documentada |
| Ventana de agrupación | 7 días | Supuesto | X02 |
| Similitud para "mismo texto" en procedencias | 0.95 | Supuesto | Test CU-03 · etiquetas |
| Umbrales de ruido | Por definir | Calibrado | X01 (precisión/recall) |
| Coincidencia de sismos (`vinculos.yaml`) | ± 2 días | Supuesto | Revisión con la exploración (E0-09); datos sintéticos en E1-09 |
| Magnitud mínima USGS | 3 | PDF (sección 6) | — |

## Extracción del snapshot (E0-04, `config/fuentes.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Ventana de noticias | 30 días, ampliable a 90 | PDF (sección 6) · D-74 | `validar_snapshot` (cobertura efectiva) |
| Volumen de A: meta · mínimo · TVN | 200 · 100 · 20 | PDF (sección 6) | `validar_snapshot` (mínimos = error, meta = advertencia) |
| `maxrecords` de GDELT | 250 | PDF (sección 6) · API | Subdivisión del rango si una consulta llega al tope |
| `ventana_noticias.ampliar_si_no_alcanza_minimo` | `true` (bandera explícita, no automática) | PDF (sección 6: "ampliar hasta 90 días") · E0-09 | Con `true`, si con 30 días no se llega al mínimo de 100 noticias, la extracción amplía a 90 (nunca más atrás: GDELT cubre ~3 meses). **El ruido no se puede medir en la extracción** (llega con E1-03b): la decisión cuenta registros únicos producidos solo por fuentes vigentes (RSS de TVN + patas vigentes de GDELT; los crudos de consultas reemplazadas no cuentan, D-83), y la comprobación de "no ruido ≥ 100" queda **pendiente de E1-03b**, después de la limpieza. Con `false` solo avisa: **eso se aparta de la spec**, que manda ampliar. `test_la_ampliacion_a_90_dias_depende_de_la_bandera` |
| Consultas de GDELT: patas por tema · términos | 2 patas (`locales`, `internacional`) × 4 temas = 8 llamadas por rango (antes 4). Los términos de las patas locales evitan palabras ambiguas en medios de Panamá (`canal` = canal de TV, `carga`, `visitantes`, `inversión` suelta): se usan "Canal de Panamá", ACP, "carga marítima", "llegada de visitantes", "inversión extranjera" | Supuesto (cada pata es una llamada porque la API no anida `OR` ni mezcla filtros de país) | Estimación offline con `scripts.estimar_consultas_gdelt` (solo mide ruido filtrado sobre lo que las consultas anteriores devolvieron, no el recall nuevo); la cobertura real se verá tras la nueva extracción. `test_terminos_de_las_patas_locales_no_son_ambiguos` |
| Consultas reemplazadas (`gdelt.consultas_historicas`) | Los crudos sin pata (consultas anteriores a E0-04) no alimentan `noticias.csv`: quedan en `raw/` y el manifest los lista como `crudos_excluidos` ("consulta reemplazada (D-83)") con su consulta histórica | Decisión D-83 | `test_crudos_de_consultas_reemplazadas_no_alimentan_el_snapshot_y_se_informan` |
| Longitud mínima de un término de consulta (`gdelt.largo_minimo_termino`) | 3 caracteres | Supuesto (GDELT rechaza palabras muy cortas) | `test_terminos_invalidos_se_rechazan`, `test_el_largo_minimo_sale_de_la_configuracion` |
| Banco Mundial: países · años · indicadores | 6 · 2010–2024 · 6 | PDF (sección 6) | Cuadrícula completa = 540 filas (6 × 6 × 15). El PDF dice 1.350: inconsistencia aritmética, documentada en el manifest |
| `per_page` del Banco Mundial | 1000 | PDF · API (evita paginar) | La extracción falla si la API pagina |
| USGS: caja · fechas · magnitud mínima | lat 5–12, lon −86 a −76 · 2024 · 3 | PDF (sección 6) | `validar_snapshot` |
| Fin de USGS | 2024-12-31T23:59:59 | Supuesto (el `endtime` es exclusivo; así entra el 31/12 completo) | `validar_snapshot` (fechas) |
| Pausa entre llamadas a GDELT | 12 s | Práctica (GDELT pide ~1 cada 5 s; con 6 s hubo 429 sostenidos en la corrida real) | Sin 429 sostenidos en la corrida |
| Backoff ante 429 · intentos máximos por rango | 30 s base, ×2 por intento (manda `Retry-After`) · 5 | Supuesto (GDELT bloquea ~2 min tras unas pocas llamadas seguidas) | Corrida real; rangos fallidos quedan registrados |
| Reintentos HTTP · espera · timeout | 3 · 15 s · 60 s | Supuesto | Corrida real |
| Rango inicial de GDELT · mínimo al subdividir | 10 días · 6 h | Supuesto | Se subdivide si la consulta llega a 250 |
| Pausa entre indicadores del Banco Mundial | 1 s | Supuesto (cortesía) | Corrida real |
| Segmentos mínimos de la ruta para tomar la primera como sección (RSS) · tema sin sección | 2 · `sin_seccion` | Supuesto (`/seccion/nota.html` tiene 2 segmentos; una ruta de 1 no trae sección) | `test_seccion_de_la_url_sale_de_la_configuracion`; revisar los temas del RSS en el snapshot |
| Un `{}` de GDELT | Cobertura sin resolver (`vacio_sospechoso`), una sola llamada por rango y corrida | Práctica (el 2026-10-06 GDELT devolvió `{}` para un rango que sí tenía artículos) | `test_un_vacio_real_no_se_repite_ni_cuenta_como_cobertura` |
| Cobertura de un día de GDELT | Cubierto solo si un crudo `articles` lo contiene completo; una respuesta al tope (250) subdivisible no cubre sola | Supuesto | `test_cobertura_por_tema_lista_cada_rango_sin_resolver_con_su_motivo` |
| Tabla de idiomas de GDELT · tabla de países (`paises_es`) | Nombre -> ISO 639-1 · nombre en inglés -> español | Práctica (lista de idiomas de la API DOC 2.0; ISO 639-1) | `test_todos_los_idiomas_de_gdelt_tienen_codigo_de_dos_letras`; lo desconocido se marca en el manifest o queda nulo |

## Prueba del modelo local (E0-07, `config/llm.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Host de Ollama por defecto | `http://localhost:11434` | Práctica (puerto estándar de Ollama) | Se lee `OLLAMA_HOST` de `local.env`, nunca del shell |
| Timeout por llamada | 180 s | Supuesto (≈ 12× la meta de latencia, para no cortar una llamada lenta y medirla) | Llamadas con error cuentan como inválidas |
| `keep_alive` durante la prueba | 10 m | Supuesto (el modelo no se descarga entre llamadas) | La carga solo pesa en el calentamiento |
| Temperatura | 0.0 | Práctica (reproducibilidad); Ollama la recomienda para salida estructurada | — |
| Semilla | 0 | Práctica (reproducibilidad) | — |
| `num_ctx` | 4096 | Supuesto (el prompt mide ≈ 930 tokens; margen ≈ 4×) | `prompt_eval_count` en `outputs/probar_llm_*.json` |
| `num_predict` | 1024 | Supuesto (la salida mide ≈ 200–400 tokens; margen ≈ 3×) | `done_reason` = `stop` en todas las llamadas |
| Pensamiento (`think`) | `false` | Documentación de Ollama (ver `docs/eleccion_modelo.md`) | `pensamiento_presente` = false en todas las llamadas |
| Repeticiones por titular | 4 (→ 20 llamadas con 5 titulares) | Supuesto (mínimo para estimar mediana y p95 con n = 20) | IC de Wilson sobre la validez |
| Llamadas de calentamiento | 1 (fuera de las estadísticas) | Práctica (excluir la carga del modelo en frío) | `load_duration_s` en los resultados |
| Titulares de la muestra | 5 de TVN Panamá: 2 nacionales, 1 mundo, 1 tvmax, 1 entretenimiento | Spec E0-07 (5 titulares reales); reparto por tema = supuesto | Selección determinista por `id_noticia` ordenado |
| Marcadores de atribución | reporta, reportó, reportado, informa, informó, según, señala, indica, publica, publicó (o el nombre del medio) | Supuesto (verbos de reporte de `docs/salidas.md`) | Métrica `atribucion` de `scripts.probar_llm`; E1-13 la mide con el validador real |
| Longitud mínima de un secreto a redactar | 8 caracteres | Supuesto | `test_local_env_ignora_secretos_cortos` |
| Confianza del IC | 95 % (Wilson para proporciones) | Práctica estadística (CLAUDE.md) | — |
| Criterio D-02: mediana | ≤ 15 s | PDF (meta de 9.1) | `scripts.probar_llm` |
| Criterio D-02: JSON inválido | ≤ 1 de cada 10 llamadas | Supuesto (D-02) | `scripts.probar_llm` |
| Criterio D-02: rechazo del validador | ≤ 20 % | Supuesto (D-02) | No evaluable en E0-07 (el validador es de E1); se usa el indicador `hecho_sobre_titular` como aproximación |

## Carga y validación (E1-02, `config/carga.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Campos críticos de noticias | `id_noticia`, `titulo`, `url`, `medio` + al menos una fecha (publicación o detección) | Spec E1-02 · fixtures T01 (`medio` vacío es `obligatorio_vacio`) | `tests/test_t01_carga.py` (T01) |
| Campos críticos de indicadores, eventos y fuentes | Indicadores: `pais_iso3`, `indicador_id`, `anio`, `unidad`, `fuente_url`, `fecha_extraccion`, `licencia` · Eventos: `id`, `magnitude`, `time`, `longitude`, `latitude`, `url` · Fuentes: `dominio`, `nombre_legible`, `origen`, `condiciones`. Vacío o en blanco invalida la fila | Contrato sección 7 (los opcionales solo cuentan como nulo) | `test_a2_*`, `test_low_criticos_*` |
| Patrón de `id_noticia` | `NOT-` + 10 hex, o `SYN-<serie>-<n>` | CLAUDE.md (D-63) | T01 |
| Patrón de `id_indicador` | `IND-<ISO3>-<indicador>-<año>` | CLAUDE.md (D-63) | `test_clave_repetida_de_indicador_es_id_duplicado` y la carga del snapshot real |
| Patrón de `id` de evento | `SIS-<id USGS>` (sin espacios) | CLAUDE.md (D-63) | `test_eventos_y_fuentes_con_pydantic` |
| Patrón de `pais_iso3` | 3 mayúsculas | ISO 3166-1 alfa-3 | Carga del snapshot real (6 países) |
| Patrón de `anio` | 4 dígitos | Contrato (el año es entero de 4 cifras) | `test_low_rango_de_anio` |
| Patrón de URL | `http(s)://` + host, resto opcional | Supuesto (sintaxis mínima; no se verifica que el sitio exista) | T01 (3 casos de `url_mal_formada`) |
| Formato de fecha en `processed/` | ISO 8601 UTC con `Z`, fecha real (rechaza 30 de febrero) | CLAUDE.md · contrato de datos | T01 (3 casos de `fecha_invalida`) |
| Formatos de fecha de origen (GDELT, RFC 822, USGS en ms) | No los lee la carga: los parsea `scripts/conversion.py` | Spec E0-04 | `tests/test_extraccion.py` |
| Rango de `anio` | 1960–2100 | Supuesto (el Banco Mundial publica desde 1960; el tope es solo defensivo) | `test_low_rango_de_anio` |
| Límites de latitud y longitud | ±90 · ±180 | Física (coordenadas geográficas) | `test_low_limites_de_latitud_y_longitud` |
| Clave de indicador | (`pais_iso3`, `indicador_id`, `anio`) | CLAUDE.md (D-63) | T01 (`id_duplicado`) · `test_low_duplicado_*` |
| Top N de medios en el reporte | 5 | Supuesto (riesgo R-10: concentración de fuentes) | `test_m1_*` (n e IC) |
| z del intervalo de confianza | 1,96 (Wilson, 95 %) | Práctica estadística (normal estándar; CLAUDE.md exige IC del 95 %) | `test_m1_*` (valores conocidos de Wilson) |
| Recorte del valor en `errores.csv` | 200 caracteres | Supuesto (legibilidad del archivo) | `test_low_recorte_del_valor_en_errores` |
| Carpeta de filas válidas | `data/processed/validos/` | Decisión D-82 | `test_a1_*` (no toca el snapshot; salida determinista) |

Un `valor` nulo en indicadores es válido (no es un parámetro: lo exige el contrato). Un duplicado conserva la primera aparición **válida**.

## Normalización y almacenamiento (E1-03, `config/normalizacion.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Largo del hash del `id_noticia` | 10 caracteres del SHA-1 de la URL canónica | CLAUDE.md (D-63) | `test_id_noticia_es_sha1_*` · `test_los_ids_recalculados_coinciden_con_los_del_snapshot` |
| Prefijos de ID | `NOT-` · `IND-` · `SIS-`; los `SYN-` conservan su ID | CLAUDE.md (D-63) | `test_ids_de_indicador_y_sismo` · T03 |
| Días para marcar una noticia como recirculada | 30 (detección − publicación > 30 días) | **Supuesto puro.** El PDF no da ningún umbral para T03: solo pide mostrar la fecha original y no presentarla como evento nuevo. 30 coincide con la ventana base de D-74, sin dato que lo calibre. Es una marca derivada, no filtra. **Con los datos reales es nula en los 186 registros**, porque ninguna fuente aporta publicación y detección a la vez (RSS solo publicación, GDELT solo detección) | T03 (`tests/test_t03_recirculada.py`, con el fixture sintético); revisar si E1-03b o E1-06 cruzan fuentes |
| Separador de temas / orígenes al fusionar duplicados | `\|` · ` · ` (orden TVN RSS, GDELT) | Formato ya usado por `scripts/conversion.py` (diccionario) | `test_duplicados_por_url_se_fusionan_*` |
| Agencias, nombres completos y firmas de redacción (D-32) | EFE, AFP, AP, Reuters, Europa Press, DPA, ANSA, Xinhua, Prensa Latina, Bloomberg, con sus nombres completos (Associated Press, Agence France-Presse...) · "agencias" genérico · redacción, tvn, web. Se buscan como palabra completa dentro de la firma, sin distinguir tildes ni mayúsculas | Spec E1-03 · lista de `config/exploracion.yaml`; nombres completos: supuesto (nombres oficiales de las agencias) | `test_derivar_firma_busca_dentro_del_texto` · `test_el_nombre_de_la_persona_no_se_guarda_*` |
| Campos de entrada de la firma | `firma`, `autor`, `author`, `dc_creator`, `creator` (opcionales; el valor nunca se guarda) | Supuesto (el snapshot actual no trae firma: el RSS de TVN no la incluye) | `test_derivar_firma` |
| Formato de fecha de salida | ISO 8601 UTC con `Z`; una fecha sin zona o ilegible queda nula y se registra | CLAUDE.md · contrato de datos | T03 (`test_una_fecha_ilegible_o_sin_zona_*`) |

Una cadena vacía o en blanco es nulo en CSV y en JSON. Duplicados: en noticias se toma la detección más temprana (por instante) y el primer valor no nulo de los demás campos; en indicadores se conserva la primera aparición completa sin rellenar con otras, como E1-02. Un `valor` ausente en indicadores nunca se rellena con 0 (no es un parámetro: lo exige el contrato).

## Limpieza y ruido (E1-03b, `config/ruido.yaml`, `config/restricciones.yaml`, `config/fuentes.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Ventana de fechas del ruido | `ventana_noticias.dias_maximo` (90 días) antes de la `fecha_extraccion` del propio registro; base = detección, si falta, publicación | D-74 · `config/fuentes.yaml` (no se agrega número nuevo) | `test_fuera_de_ventana_usa_la_deteccion_y_no_sustituye_fechas` · fila `SYN-RUI-007` |
| URL canónica ampliada | sin `m.`, sin sufijo `/amp`, sin `?outputType=amp` ni `?amp=1|true` | Spec E1-03b | `test_url_canonica_ampliada_*` · `SYN-RUI-009` a `-011` |
| `limpieza.max_palabras_sufijo` | 6 palabras | **Supuesto**: los nombres de medio más largos ("Global Finance Magazine") caben; un sufijo mayor es parte del titular | `test_limpiar_titulo` (guion que no es medio no se corta) |
| `limpieza.min_letras_medio` | 5 letras | **Supuesto**: evita que "AP"/"ABC" coincidan por contención con cualquier sufijo | `test_limpiar_titulo` |
| Medios conocidos (sufijos) | lista corta de `ruido.yaml` | Exploración E0-09 (sufijos vistos en el snapshot) | `test_limpiar_titulo` |
| Patrones de falsos Panamá, menciones, deportes, farándula, cultura, política partidista, no-noticia | listas de `ruido.yaml` | `docs/guia_temas.md` + exploración E0-09 (`config/exploracion.yaml`). **Son heurísticas por palabras clave sobre el titular, no etiquetas humanas** | `tests/test_ruido.py` (fixture `ruido.csv`) · precisión/recall reales con `python -m eval.ruido` cuando E1-06 entregue `eval/etiquetas.csv` |
| Origen sujeto al filtro de mención | `GDELT`; exentos: `TVN RSS` y medios con `pais_medio = Panamá` | **Supuesto** según E0-09: las consultas de GDELT piden "Panama" más un término amplio sin anclarlo al titular (motivo medido con las consultas anteriores a D-83; con las patas de D-83 se revisa al extraer la v1.2 del snapshot) | `test_gdelt_sin_mencion_de_panama_*` · `test_medio_panameno_o_tvn_nacional_*` |
| Secciones dudosas de TVN | `mundo`, `tvmax`, `entretenimiento` (señal candidata: el titular decide) | E0-09, recomendación 5 | `test_la_seccion_de_tvn_solo_sospecha_el_titular_decide` |
| Patrones de inyección (D-69) | lista en `restricciones.yaml`, sección `inyeccion` | Fixture T07 (4 tipos de ataque, ES/EN) · D-69 | `test_t07_los_ocho_titulares_*` · `test_ruido_csv_no_dispara_falsos_positivos_de_inyeccion` |
| `similitud_prototipo.activo` | `false` | **Implementado en E1-07** (`src/clasificacion.py`, con los embeddings locales) pero **sin activar**: sin etiquetas humanas no se puede validar. Ver «Clasificación (E1-07)» | `tests/test_clasificacion.py` (marca, alcance regional, reversibilidad) · `python -m eval.ruido` con E1-06 |
| Alcance regional (D-84) | `panama.regionales` en `ruido.yaml`: Centroamérica, América Latina/Latinoamérica/LatAm, Caribe, El Niño/La Niña, rutas marítimas | Decisión D-84 (revisión X14): una nota regional o de un fenómeno regional que afecta a Panamá no es ruido; se conserva con `alcance_regional = true` y se cuenta aparte | `test_x14_h2_*` |
| Autopromoción de TVN | `fuera_de_temas.autopromocion_tvn` (`TVN Media`, `Gente TVN`, `Gente que Inspira` al inicio del titular) | Revisión X14, H5 | `test_x14_h5_*` |
| Decimales del reporte | 4 (`limpieza.DECIMALES_PRESENTACION`) | Presentación: no afecta ninguna decisión | `test_x14_h8_*` |
| z del IC de Wilson | 1.96 (el de `carga.yaml`) | Estándar | `test_reporte_de_calidad_cuenta_ruido_por_motivo_con_n_e_ic` |

Todo lo marcado como ruido es una **propuesta por titular**, no una etiqueta humana. El IC de Wilson del reporte es descriptivo: el snapshot no es una muestra aleatoria.

## Clasificación (E1-07, `config/clasificacion.yaml`, `config/ruido.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Modelo activo | `e5` = `intfloat/multilingual-e5-small` @ `614241f622f53c4eeff9890bdc4f31cfecc418b3` | D-20 (propuesta) | Macro-F1 contra MiniLM con `eval/etiquetas.csv` (E1-06); en 15 casos difíciles no es decidible (`docs/clasificacion.md`) |
| Modelo de comparación | `minilm` = `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` @ `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | D-20 | Ídem |
| Prefijos de e5 | `query: ` (titular) · `passage: ` (descripción, ejemplos, prototipos); MiniLM sin prefijo | Spec E1-07 · ficha del modelo (retrieval asimétrico) | No se midió la alternativa `query: ` en ambos lados |
| Método activo | `A` | D-21/D-57: A salvo evidencia estadística a favor de B | `python -m eval.clasificacion` (criterio A vs. B) |
| Criterio A vs. B | IC 95 % bootstrap de B − A excluye el cero a favor de B **y** ningún tema con soporte empeora de forma significativa (límites sin redondear) | D-57 (fijado antes de medir) | `test_criterio_*` (`tests/test_eval_clasificacion.py`) |
| Remuestreos · confianza · semilla del bootstrap | 1.000 · 0.95 · 42 | Práctica estadística (`criterio_ab`) | `test_el_ic_de_bootstrap_es_reproducible_*` |
| Semilla global | 42 | Práctica (reproducibilidad) | `test_el_resultado_es_determinista` |
| Dispositivo · lote | CPU · 32 | Supuesto (determinismo y portabilidad; el lote no cambia el resultado) | — |
| `umbral_sin_tema` y `margen_secundario` por modelo y método (reemplaza la fila antigua «Umbral "sin tema": por definir») | e5 · A 0.824 / 0.002 · e5 · B 0.797 / 0.004 · MiniLM · A 0.213 / 0.030 · MiniLM · B 0.283 / 0.019 | **Supuesto**: percentil 5 de la similitud máxima y percentil 25 de la brecha entre la 1.ª y la 2.ª, sobre 52 titulares únicos útiles (`python -m eval.calibrar_clasificacion`, recalculado tras corregir las referencias en X15). **No calibrado con etiquetas** | `test_bajo_el_umbral_*` · `test_tema_secundario_*` · recalibrar con las etiquetas de E1-06 |
| Centroide del método A | Media de la descripción y los ejemplos (peso igual) | Supuesto (el más simple; sin peso extra que calibrar) | Casos difíciles · etiquetas (E1-06) |
| Tema secundario | El 2.º tema por similitud si su diferencia con el 1.º ≤ `margen_secundario` y supera `umbral_sin_tema` | Supuesto | `test_tema_secundario_solo_si_esta_dentro_del_margen` |
| Baseline por palabras clave | Dos variantes: `guia` (solo términos literales de `docs/guia_temas.md` fuera de los casos difíciles; principal) y `ampliado` (guía + `extension`); puntaje = términos distintos que coinciden | Supuesto. La extensión la escribió quien ya había leído los casos difíciles y varios términos coinciden con ellos (`asep`, `asamblea`, `homicidio`, `aerolinea`): **no es independiente de los casos difíciles** y se reporta aparte (`baseline_ampliado`) | `test_h3_*` (cada término de `guia` está en la guía) · casos difíciles |
| `similitud_prototipo.umbral` | 0.774 (e5), **sin efecto** mientras `activo: false` | Supuesto (percentil 5 de la similitud con los prototipos de Panamá) | `eval.ruido` con E1-06; hoy dejaría un falso positivo evidente de 2 marcas (`docs/clasificacion.md`) |
| Solapamiento máximo de un caso difícil con una referencia | Jaccard de palabras < 0.8 (`eval.clasificacion.BASE_JACCARD`) | Supuesto (detector de fuga, no afecta ninguna decisión) | `test_el_detector_de_fuga_*` |
| Fuga semántica: coseno máximo entre un caso difícil y un ejemplo o prototipo | < 0.56 con MiniLM, ignorando «Panamá» (`fuga_semantica` en `clasificacion.yaml`); una excepción aceptada de forma explícita (CD-02 con un ejemplo real del snapshot, 0.566) | **Supuesto elegido después de ver los pares**: detecta las paráfrasis de CD-02, CD-11 y CD-12; CD-01 con el prototipo original daba 0.56 | `test_h4_ningun_ejemplo_ni_prototipo_parafrasea_un_caso_dificil` |
| Clases de la evaluación | 6 temas + `sin_tema` (agrupa `fuera_de_temas` y `no_es_panama`) | `guia_temas.md` | `test_tema_a_id_*` |
| Macro-F1 | Media de los F1 definidos de las clases con soporte en las etiquetas; un F1 indefinido no cuenta como 0 | Práctica (se declara para no inflar ni hundir la media) | `test_una_clase_sin_soporte_*` |

## Consulta y generación (E1-11 · `config/consulta.yaml`; la generación es E1-12)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| `abstencion.umbral_similitud` | semántica (e5) **0.874** · BM25 **10.765** | **Calibrado** (E1-11): percentil 5 de la similitud máxima de las 9 consultas respondibles de la mitad de calibración (ids pares del benchmark de desarrollo) que llegan a la puerta de similitud, truncado a 3 decimales (`python -m eval.recuperacion --calibrar`) | `eval.recuperacion` sobre la mitad de evaluación (ids impares); n = 20 por mitad: IC muy anchos |
| `abstencion.percentil_umbral` | 5 | Supuesto (misma regla que `umbral_sin_tema` en E1-07; por construcción rechaza ~5 % de las respondibles de calibración) | Abstenciones incorrectas |
| División calibración/evaluación | Pares calibran, impares evalúan (`evaluacion.calibracion`) | Supuesto (determinista y sin azar; con 40 consultas las mitades son de 20) | `test_la_division_calibracion_evaluacion_es_determinista_por_paridad` |
| `recuperacion.top_k` | 5 | PDF (Recall@5, sección 9.1) | `eval.recuperacion` |
| `recuperacion.bm25.k1` · `b` | 1.5 · 0.75 | Práctica (valores por defecto de `rank-bm25`) | `eval.recuperacion` (baseline D-66) |
| `recuperacion.bm25.largo_minimo_token` | 2 | Supuesto | — |
| `recuperacion.bm25.palabras_vacias` | 52 palabras | Supuesto (lista corta de palabras funcionales en español) | `test_bm25_responde_y_se_abstiene_con_su_propio_umbral` |
| `reglas` de abstención (lectura del artículo, autoría o perfil, cifra de periodo relativo) | Patrones en `consulta.yaml` | **Supuesto redactado DESPUÉS de leer el benchmark de desarrollo**: su desempeño allí es optimista y no una medida independiente. Origen de fondo: D-51 (no se leyó el artículo), D-32/D-68 (sin autores ni perfiles) | Un test por regla (`test_las_reglas_por_patron_*`) |
| `datos_oficiales.calificadores` · `relacionados` | Listas en `consulta.yaml` (edad/sexo/etnia, territorios, sector; «PIB» como relacionado del crecimiento) | Supuesto (X16), redactadas tras la revisión del PR #16 | `test_x16_*` |
| `respuesta.decimales_valor` | 2 | Supuesto (solo presentación) | `test_x16_el_valor_se_muestra_*` |
| `datos_oficiales.variacion` | `subió`, `bajó`, `cambió`… agregan el año anterior | Supuesto | `test_una_variacion_incluye_el_anio_anterior` |
| `respuesta.maximo_afirmaciones` | 5 (= `top_k`) | Supuesto | — |
| Temperatura | 0 | Práctica (reproducibilidad) | — |
| Reintentos ante JSON inválido | 1 | Supuesto | Tasa de JSON inválido |
| Cambio de proveedor: latencia | Mediana > 15 s | PDF (meta de 9.1) | Métrica de latencia |
| Cambio de proveedor: rechazo · JSON inválido | > 20 % · > 1 de 10 | Supuesto | E0-07 |

## Salidas

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Brief · copy · resumen bancario | ≤ 250 · ≤ 80 · ≤ 250 palabras | PDF | Test |
| Guion | 45–60 s | PDF | X03 |
| Guion en palabras | 110–150 (`salidas.yaml`) | Calibrado | X03 (cronometrado) |
| Preguntas | Exactamente 3 | PDF | Test |
| Título · titulares · resumen web · hashtags | ≤ 14 · 2–3 · ≤ 120 · ≤ 2 | Supuesto (convención propia) | Tasa de corrección en revisión |
| Transiciones sin cita por sección | 1 (`salidas.yaml`) | Supuesto | Revisión editorial |
| Palabras sensacionalistas y frases prohibidas | Grupos `comunes`, `editorial` y `banca` en `restricciones.yaml` | PDF (prohibiciones) · diseño (validador, D-25, D-51); las listas de frases, Supuesto | Un test por frase (E1-13) |

## Evaluación

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Titulares etiquetados | ~100 | Supuesto (tiempo disponible) | Se reporta con IC |
| Muestra de validez de sustento | ≥ 30 afirmaciones | PDF | Se reporta con IC |
| Benchmark | 60 (30 · 10 · 10 · 10), 40 desarrollo / 20 reservadas **del jurado** | PDF | — |
| Intervalos de confianza | 95 %, bootstrap de 1.000 remuestreos | Práctica estadística | — |
| Semillas aleatorias | Fijas en `config/` (etiquetado, bootstrap, clustering si aplica) | Práctica (reproducibilidad) | `scripts.reproducir` (D-65) |
| Benchmark del equipo (si la organización no lo entrega) | 40 de desarrollo: 20 · 7 · 7 · 6 | PDF (proporciones de la sección 7) | `eval.validar_benchmark` |
| Sensibilidad X02 | Pesos ± 5; parámetros supuestos ± 20 % | Supuesto | — |
| Precision@5 | 3 fechas de corte si hay editor; si no, n = 1 y exploratoria | PDF (exploratoria sin especialista) | — |
| Duración de la demo | 4 min | PDF | Ensayo cronometrado |

## Etiquetado humano (E1-06, `config/etiquetado.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Semilla de la muestra | 20261006 | Práctica (reproducibilidad) | `test_muestra_reproducible_con_la_semilla_y_del_tamano_pedido` |
| Tamaño de la muestra | 100 | Supuesto (tiempo disponible; ~100 según el reto) | `eval.etiquetar --muestra` |
| Cuotas por estrato (no ruido / ruido) | 70 / 30 (real 63 / 37: el estrato no ruido solo tiene 63) | Supuesto (medir el filtro necesita ruido suficiente) | `test_muestra_estratificada_70_30_con_dobles_14_6_y_pesos`; pesos en `eval.etiquetar --muestra` |
| Titulares dobles (acuerdo) | 20 (14 no ruido + 6 ruido) | D-71 / spec E1-06. **No aplicado en las etiquetas actuales:** D-85 reemplazó el doble etiquetado por propuesta del asistente + revisión de una persona | `eval.etiquetar --acuerdo` |
| Kappa mínimo del acuerdo | 0.6 | Supuesto (umbral "sustancial" de Landis y Koch; con n = 20 es impreciso). Sin doble etiquetado (D-85) no se calcula; `--consolidar` se corrió con `--forzar` (`docs/etiquetado.md`) | `eval.etiquetar --acuerdo` y `--consolidar` |
| Marcadores de IA en nombres | `nombres.marcadores_ia` (palabra) y `marcadores_ia_nombre_completo` (`ia`, `ai`, `llm`, `bot`: solo el nombre completo) | Supuesto (lista corta; palabra exacta) | `test_rechaza_nombres_de_herramientas_o_invalidos` |

## Exploración (E0-09)

Valores en `config/exploracion.yaml`. Todo lo que marcan es **candidato**; las medidas reales son E1-03b y E1-06.

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Intervalo de confianza de las proporciones | Wilson, z = 1.96 (95 %) | Práctica estadística | `test_wilson_es_un_intervalo_valido` |
| Filas de cada tabla de conteos | 10 | Supuesto (legibilidad) | — |
| Mínimo de titulares revisados por tema | 15 | PDF (spec E0-09) | Sección 10 de `docs/exploracion.md` |
| Largo mínimo para contar un titular contenido en otro como duplicado | 30 caracteres | Supuesto | `test_duplicados_agrupa_sufijos_y_contencion`; revisar con E1-08 |
| Bins de magnitud USGS | < 3 · 3 · 4 · 5 · 6 | Práctica (escala de magnitud) | — |
| Año final esperado de la cuadrícula del Banco Mundial | 2024 | Supuesto (config de `fuentes.yaml`) | Sección 8 de `docs/exploracion.md` |
| Listas de palabras (deportes, farándula, falso Panamá, menciones de Panamá, temas) | En YAML | Supuesto (exploratorias; no clasifican) | Se descartan al medir E1-03b / E1-07 |
