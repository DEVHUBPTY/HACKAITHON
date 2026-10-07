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
| U sin fecha de publicación en ningún titular | Usa `fecha_deteccion` y agrega el vacío "urgencia estimada: fecha de publicación desconocida" | Supuesto (88 de 221 noticias del snapshot v1.2 traen publicación; GDELT no) | Test de E1-10 |
| N del primer grupo (sin grupos previos) | 1.0 | Supuesto | Test de E1-10 |
| Listas de provincias, comarcas y distritos | 10 · 6 · 60 | Práctica (división político-administrativa; lista parcial de distritos) | Titulares reales de TVN; `validar_coherencia` |
| Agencias de noticias para el tipo de firma | 10 nombres | Práctica (el RSS de TVN no trae firma, no se derivan de datos) | Se usa solo si un titular de GDELT la nombra |

### Cómo se calcula cada componente y qué parámetros agrega E1-10 (`config/prioridad.yaml`)

Las reglas v1.3 fijan las fórmulas; estas filas fijan lo que dejan abierto. Todas son **supuestos** salvo donde se indica, y `python -m eval.sensibilidad` mide cuánto mueven el top 5.

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Fecha de referencia de U | `fecha_corte_UTC` del manifest (opción `--ahora`) | Diseño (reproducibilidad: U no depende del reloj) | `test_la_fecha_de_referencia_se_registra_en_utc` · `test_dos_ejecuciones_producen_el_mismo_ranking` |
| Percentil | `(rango medio) / (n − 1)`: 0 el menor, 1 el mayor, empates comparten el rango medio; un solo valor = 0.5 | Práctica (rango percentil) | `test_los_percentiles_ocupan_el_rango_completo_*` |
| Similitud temática de un grupo (R) | Media de `tema_similitud` de sus titulares | Supuesto | X02 · `eval.puntaje` (R no casi constante) |
| Foco de un grupo (R) | 1 si algún titular trata a Panamá como sujeto; 0.5 si todos son notas regionales o de otro país que afectan a Panamá (`alcance_regional`, D-84) | Supuesto | `test_noticia_de_otro_pais_*` · revisión editorial |
| Alcance geográfico de un grupo (I) | El más amplio que nombran sus titulares (nacional > provincial > local); sin términos, `desconocido` | Supuesto | `test_alcance_geografico_*` |
| Prefijos obligatorios de términos ambiguos (`geografia.prefijos_obligatorios`) | «Panamá» solo es la provincia si lo precede «provincia de» (el país no es la provincia) | Supuesto | `test_alcance_geografico_nacional_provincial_local_*` |
| Alcance de I sin subtema (`impacto.alcance_subtema_desconocido`) | 0.5 (igual que el alcance geográfico desconocido) | Supuesto | X02 · vacío «subtema no determinado» |
| N: con quién se compara | Máxima similitud entre un titular del grupo y un titular de un grupo que **empezó antes** (`fecha_publicacion`, si falta `fecha_deteccion`); empate de fecha: menor ID | Supuesto | `test_n_compara_solo_con_grupos_anteriores_*` |
| Medios que no identifican (`medios.desconocidos`) | `""`, `desconocido`, `unknown`, `n/a` | Supuesto | `test_un_medio_desconocido_no_cuenta_como_identificable` |
| Decimales para comparar P y U al desempatar (`comparacion.decimales_p`) | 9 | Práctica (evita que el ruido de coma flotante rompa un empate) | `test_un_empate_por_ruido_de_coma_flotante_no_decide_el_orden` |
| Dato oficial en E y en el estado de evidencia (`dato_oficial.relaciones_aceptadas`) | Hay al menos un vínculo en `vinculos` con `id_evidencia`, valor no nulo, sin motivo de «sin vínculo» y de relación `directa` o `evento`. **`indirecta` no cuenta**: el indicador es contexto lejano y no mide el hecho (X22) | Diseño (E1-09, E1-09b; revisión del PR #22) | `test_x22_*` · `test_dos_grupos_identicos_salvo_por_tener_dato_oficial_*` |
| Cifras de un titular (`cifras.*`) | Un número que no es fecha («2 de octubre»), año (1900–2100 sin `%`) ni identificador (ley, decreto, resolución…); `84.000` = 84 mil, `3,2` = decimal; la unidad es `%` o la raíz de 5 letras de la palabra siguiente | Supuesto (conservador: ante la duda no cuenta como cifra) | `test_extraccion_de_cifras_*` · `test_valores_numericos_con_separadores` |

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

### Contradicciones, vacíos y sensibilidad (E1-10, `config/prioridad.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Candidatos a contradicción (D-23) | Dos titulares del mismo grupo con **cifras distintas** de la misma unidad, o con **verbos opuestos** (7 pares: sube/baja, aprueba/rechaza, confirma/niega, abre/cierra, suspende/reanuda, gana/pierde, condena/absuelve) | Supuesto (lista corta y conservadora; el LLM solo compara esos pares) | `test_t05_*` · revisar con titulares reales |
| `contradicciones.solo_entre_procedencias` | `false`: dos versiones distintas de un mismo origen (p. ej. un medio que actualiza una cifra) también se muestran | Supuesto | `test_dos_versiones_de_un_mismo_origen_*` |
| `contradicciones.maximo_candidatos_por_grupo` | 6 pares por grupo van al LLM; el resto queda «pendiente» (sigue abierto) | Supuesto (costo y contexto de `num_ctx`) | `test_un_par_sobre_el_tope_queda_pendiente_*` |
| Papel del LLM en una contradicción (X21) | Solo una nota (`nota_llm`: posible_contradiccion · compatible · pendiente) y fragmentos literales; **nunca cierra un par**: todo par detectado por reglas cuenta como abierto para el estado de evidencia. Solo una persona podrá cerrarlo (revisión, E1-16) | Diseño (D-23, revisión del PR #22) | `test_x21_*` |
| Etiqueta de la contradicción | «posible contradicción, verificar»; nunca un veredicto | PDF (CU-04) · D-23 | `test_el_resultado_es_una_posible_contradiccion_a_verificar_nunca_un_veredicto` |
| Raíz de la unidad de una cifra (`cifras.raiz_unidad_caracteres`) | 5 caracteres («escuela» = «escuelas») | Supuesto | `test_la_extraccion_de_cifras_*` |
| Variación de pesos en la sensibilidad | ±5 puntos de cada peso (los demás se reescalan para sumar 100) | PDF (permitir justificar cambios de pesos) · spec E1-10 | `eval.sensibilidad` |
| Variación de supuestos en la sensibilidad | ±20 % de cada parámetro supuesto que cambia P | spec E1-10 | `eval.sensibilidad` |
| Tamaño del ranking comparado | 5 | PDF (CU-01) | `eval.sensibilidad` |
| Componente «casi constante» (`puntaje_eval.casi_constante_desviacion`) | Desviación estándar < 0.05 en [0, 1] | Supuesto | `eval.puntaje` |
| Filas del ranking en `outputs/prioridad.json` (`puntaje_eval.top_en_reporte`) | 10 | Presentación | — |

## Ficha de evidencia (E1-10b, `config/verificacion.yaml`, `config/modalidad_*.yaml`)

La ficha no calcula puntaje ni estado: lee lo de E1-10 y agrega presentación y reglas de verificación (sin LLM, D-36). Solo la tabla de acciones, el medio de referencia y las fuentes extra cambian por modalidad.

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Vacíos arriba (`vacios.principales`) | 3; el resto va en un desplegable | PDF/spec E1-10b («los 3 más importantes arriba») | `test_los_tres_vacios_mas_importantes_van_arriba_*` |
| Orden de importancia de los vacíos (`vacios.orden_importancia`) | contradicción · cifra discrepante · cifras sin dato oficial · sin dato oficial · solo vínculo indirecto · procedencias insuficientes · recirculada · evento sin revisar · período distinto · medios o fechas desconocidos · urgencia sin publicación · subtema desconocido | Supuesto (criterio editorial: lo que más cambia la decisión va primero) | Revisión editorial · `test_los_tres_vacios_mas_importantes_*` |
| Vacíos que nacen de los vínculos (`prioridad.yaml:vacios`, tabla `evidencia`) | `solo_vinculo_indirecto` (X22: el indicador vinculado no mide el hecho), `cifra_discrepante` y `cifra_periodo_distinto` (de `vinculos.comparacion_titular`), `evento_sin_revisar` (`vinculos.estado_evento = automatic`). **Única fuente**: los calcula E1-10 y la ficha solo los lee (revisión del PR #24, M2) | Diseño | `test_m2_los_vacios_de_la_ficha_son_los_que_guardo_e1_10_sin_recalcular` · `test_cada_tipo_de_vacio_aparece_cuando_se_cumple_su_condicion_y_no_cuando_no` |
| Una cifra discrepante abierta impide «suficiente» | Igual que una contradicción abierta (`estado_evidencia.sin_contradiccion_abierta_para_suficiente`): el estado queda como máximo `parcial`. «Período distinto» y «evento sin revisar» no bloquean | Decisión del orquestador (nunca afirmar más de lo que la evidencia permite) | `test_una_cifra_discrepante_abierta_impide_suficiente_como_una_contradiccion` · `test_m2_una_discrepancia_abierta_*` |
| Motivos de «sin dato oficial» en palabras (`vacios.motivos_sin_vinculo`) | Un texto por motivo de `vinculos.yaml`; ningún código interno llega a la ficha (m4) | Presentación | `test_m4_ningun_vacio_muestra_un_codigo_interno_*` · `validar_coherencia` |
| Leyenda de alcance (D-51, m3) | «basado únicamente en titular/metadatos», salvo que algún titular del grupo traiga descripción del RSS **y** se haya codificado junto al titular para clasificar (`clasificacion.yaml: usar_descripcion`) o agrupar (`reglas_v1.3.yaml: agrupacion.usar_descripcion`): entonces «basado en titular, descripción del RSS y metadatos; no se leyó el artículo completo». La descripción sigue siendo de uso interno y nunca se muestra (D-31); la leyenda declara que el tema, el subtema o el grupo dependen de ella. Hoy ningún grupo la trae | PDF sección 3 · D-31 · D-51 | `test_m3_la_leyenda_declara_la_descripcion_si_se_uso_al_clasificar_o_agrupar` |
| Textos de la ficha | Un texto que cita un titular lleva el campo citado literal (`titulo_limpio`, documentado en `data/diccionario.md`); el conteo dice «reportan este tema», nunca «este hecho»; los textos de los datos se escapan en el Markdown (X23, X24, M1) | PDF («las comillas son siempre literales») · CLAUDE.md | `test_x23_*` · `test_x24_*` · `test_m1_*` |
| Siguientes pasos de la acción (`siguientes_pasos.maximo`) | 3, derivados de las verificaciones de los vacíos más importantes | Supuesto | `test_los_siguientes_pasos_se_derivan_de_los_vacios_mas_importantes` |
| Candidatos a titular central (`titular_central.candidatos`) | Los 3 titulares más cercanos al centroide compiten por la preferencia | Supuesto | `test_el_titular_central_prefiere_espanol_y_medio_panameno_*` |
| Preferencia del titular central | Idioma `es` y medio de `pais_medio` = Panamá | Spec E1-10b | Ídem |
| Empate de distancia al centroide | Se redondea a la precisión de float32 (6 decimales, `np.finfo`) y gana el menor `id_noticia` | Práctica (el ruido de coma flotante no decide) | `test_el_titular_central_es_determinista_ante_empates` |
| Fuentes sugeridas por subtema y por tema (`fuentes.por_subtema`, `fuentes.por_tema`) | 38 subtemas y 6 temas, de 1 a 3 instituciones cada uno; sin subtema (D-92) solo las del tema | Supuesto (criterio editorial; son sugerencias, nunca evidencia, D-37) | `test_verificacion_cubre_todos_los_subtemas_y_temas` · `validar_coherencia` |
| Fuentes sugeridas extra de la banca | SBP, MEF, INEC (`fuentes_sugeridas_extra`) | Diseño (D-38) | `test_la_banca_agrega_sus_fuentes_extra_al_final_y_sin_repetir` |
| Zona horaria y formato al mostrar (`presentacion.zona_horaria`, `formato_fecha`) | `America/Panama` (UTC-5, sin horario de verano) · `AAAA-MM-DD HH:MM` | PDF (hora de Panamá solo en la interfaz) | `test_la_cobertura_dice_titulares_medios_y_rango_de_fechas_en_hora_de_panama` |
| Decimales al mostrar un valor (`presentacion.decimales_valor`) | 2 | Presentación | — |
| Tabla de acciones de la banca (`modalidad_banca.yaml`) | Alto = Incluir en el boletín como observación · Incluir como señal a confirmar · Seguimiento prioritario; Medio = Incluir como contexto · Seguimiento · Seguimiento; Bajo = Archivar | Diseño (D-35, D-38; mismas celdas que el diseño de solución) | `test_la_modalidad_banca_es_parcial_y_usa_el_mismo_modelo_que_la_editorial` |
| `modalidad_banca.yaml` es **parcial** (`parcial: true`, D-90) | Solo trae lo que necesita la ficha; E2-01 agrega el mapeo tema → sector, el alcance por sector, el horizonte y la bandeja | Diseño (D-90) | Ídem |

## Organizar y contextualizar

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Umbral de agrupación | 0.69 (coseno promedio, MiniLM; `agrupacion.umbral_similitud`) | **Calibrado** (D-16): mayor F1 de pares con `eval/etiquetas.csv`, mitad de la meseta más larga. Vale solo para MiniLM | `python -m eval.agrupacion` · curva en `docs/calibracion_agrupacion.md` |
| Ventana de agrupación | 7 días | Supuesto | X02 · `test_dos_titulares_a_mas_de_la_ventana_*` |
| Similitud para "mismo texto" en procedencias | 0.95 | Supuesto | `test_el_umbral_de_mismo_texto_*` · T02 · los 20 «Intensifying El Niño…» y los 10 «Trump streicht…» dan una procedencia |
| Detalle de la agrupación y de las procedencias (E1-08) | Ver «Agrupación y procedencias (E1-08)» más abajo | — | — |
| Umbrales de ruido | Por definir | Calibrado | X01 (precisión/recall) |
| Tendencia (`vinculos.tendencia_anios`) | 5 años de Panamá, hasta el último año con valor, nulos incluidos | PDF/spec E1-09 | `test_la_tendencia_son_los_ultimos_cinco_anios_de_panama_y_los_nulos_siguen_nulos` |
| Comparables | Los demás países de la cuadrícula, en el mismo año que Panamá, solo con dato (no hay número: sale de los datos) | PDF/spec E1-09 | `test_los_comparables_son_del_mismo_anio_que_panama_y_solo_con_dato` |
| Palabras prohibidas en la salida (`vinculos.palabras_prohibidas`) | `actual`, `actuales`, `actualmente`, `actualidad` | PDF/spec E1-09 (T04: el dato es anual); formas derivadas por la observación del PR #19 | `test_ningun_texto_de_la_configuracion_dice_actual` · `test_la_configuracion_rechaza_la_palabra_actual` · `verificar_texto` en cada corrida |
| Indicadores solo de contexto (`vinculos.indicadores_solo_contexto`) | `SP.POP.TOTL` (población no se vincula sola) | PDF/spec E1-09 | `test_la_poblacion_no_se_vincula_sola` |
| Ventana de la cifra del titular (`cifra_titular.ventana_caracteres`) | 40 caracteres entre la palabra clave y la cifra, sin otras cifras ni `%` | Supuesto (conservador: evita ligar «60% del PIB» con la inflación) | `test_la_extraccion_de_la_cifra_es_conservadora` · revisar con titulares reales |
| Palabras que rodean la cifra del titular (`cifra_titular.palabras_de_baja` · `_de_baja_ambiguas` · `_de_alza` · `_de_nivel` · `_de_cota`) | Verbos de baja y alza; «a»/«hasta» = nivel; «bajo», «menos de», «más de», «cerca de», «alrededor de», «hasta» = cota; «baja» ambigua (listas en `vinculos.yaml`) | Supuesto (X17/X19; principio: ante la duda no se compara). **Nivel:** verbo + «a»/«hasta» («cae a 0,7 %») conserva el signo. **Variación:** verbo sin «a» («cae 2 %») solo se compara en `indicadores_de_variacion` (hoy el PIB, ya es una tasa); contra el nivel oficial de inflación o desempleo no es comparable, y `comparacion_titular` queda nulo. **Cota:** no se compara. «bajo» nunca es verbo | `test_x17_*` · `test_x19_*` |
| Proyecciones y verbos no listados (`cifra_titular.palabras_de_proyeccion` · `patrones_de_verbo_no_listado`) | Proyección («podría», «prevé», «estima», «proyecta»…) en cualquier parte del titular, o entre la clave y la cifra una palabra tipo verbo fuera de las listas (futuro/condicional `-ría`/`-rá`, infinitivo `-ar/-er/-ir`, «se …»): no se compara | Supuesto (seguimiento PR #19: el signo es incierto o la cifra no es un dato observado; ante la duda no se compara). Regla: «cae al 0,7 %» = nivel («al» en `palabras_de_nivel`); «casi», «cerca del», «alrededor del», «al menos», «unos», «más/menos del» ampliaron `palabras_de_cota` | `test_seguimiento_x19_*` |
| Indicadores de variación (`cifra_titular.indicadores_de_variacion`) | `NY.GDP.MKTP.KD.ZG` | Supuesto (el indicador oficial es una tasa de cambio, así que «cae 2 %» equivale a -2) | `test_x19_la_variacion_del_pib_si_se_compara_con_signo` |
| Indicadores con comparación de cifra del titular (`cifra_titular.palabras_clave`) | PIB, inflación y desempleo | Supuesto (solo donde el % del titular mide lo mismo que el oficial; exportaciones e internet quedan fuera: un % del titular suele ser variación, no % del PIB o de la población) | `test_la_cifra_de_otro_indicador_no_se_compara_con_este` |
| Patrones de cifra (`%`) y año (`20xx`) del titular | Ver `vinculos.yaml` | Supuesto | `test_misma_anio_con_cifra_distinta_*` · `test_periodo_distinto_*` · `test_titular_sin_anio_*` |
| Subtema del grupo | Voto de los titulares (método B, tema del grupo); empate: suma de similitudes, luego nombre | Supuesto | `test_el_subtema_gana_por_votos_luego_por_similitud_y_es_determinista` |
| Coincidencia de sismos (`vinculos.yaml`) | ± 2 días | Supuesto | Revisión con la exploración (E0-09); datos sintéticos en E1-09 |
| Margen mínimo del subtema (`vinculos.subtema.margen_minimo`, D-92) | 0.015, **sin efecto desde E1-10c** (`criterios: [lexico]`) | Supuesto; **retirado como criterio suficiente por E1-10c (X41)**: en el snapshot del 2026-10-06 aceptaba 10 de 22 grupos de Servicios públicos y 8 de 36 del resto, y la mitad sin sustento en el titular (juicio del agente, no etiquetas humanas): el prototipo de agua potable trae «obras» y «La Chorrera» (MOP y un parque de La Chorrera → agua potable) y el de salud trae «CSS» (aprehensión de un exdirector de la CSS → salud). El margen medía el parecido con esas palabras sueltas, no el subtema. Se puede reactivar agregando `margen` a `criterios`. Antes: Margen = promedio, sobre los titulares del grupo, de (similitud del 1.º subtema − similitud del 2.º) dentro del tema asignado, método B (`similitud_tema.margen_subtema`); se exige `>=`. Un titular sin margen guardado no respalda subtema. Simulación del 2026-10-06 **excluyendo los 15 grupos cuyos titulares son ejemplos de `config/ejemplos_excluidos.txt`** (quedan 42 de 57), con juicio del agente, **no etiquetas humanas**: sin margen, 42 grupos con subtema y 9 correctos (21 %, n = 9/42, IC 95 % 12–36 %); con 0.015, 9 con subtema y 4 correctos (44 %, n = 4/9, IC 95 % 19–73 %). Los intervalos se solapan: con n tan chico la simulación solo indica la dirección (menos subtemas afirmados, mayor proporción correcta) y no demuestra el valor. (Con los 57 grupos, sin excluir, había salido 17 conservados y 8 correctos; esa cifra queda descartada por incluir ejemplos de configuración.) Con e5 las similitudes están entre 0.78 y 0.89 y el 1.º−2.º es menor a 0.01 en la mitad de los grupos. Se recalibra con etiquetas humanas de subtema (n e IC 95 %) | `test_d92_*` (`tests/test_d92_subtema_margen.py`) |
| Criterios del subtema (`vinculos.subtema.criterios`, E1-10c) | `[lexico]` | Diseño (E1-10c, X41): un subtema se afirma solo si algún titular del grupo nombra un término del subtema más cercano y **ningún** titular nombra un término de otro subtema del mismo tema (si nombra dos, es ambiguo: «aprehenden al exdirector de la CSS» nombra seguridad y salud). Sin sustento, I usa el alcance neutro (`impacto.alcance_subtema_desconocido`, 0.5) con el vacío «subtema no determinado». Resultado en el snapshot: 18 → 10 grupos con subtema; los 10 nombran su subtema en el titular (juicio del agente, no etiquetas humanas) | `test_x41_*` (`tests/test_e1_10c_puntaje.py`) · `test_d92_*` |
| Términos por subtema (`vinculos.subtema.terminos_por_subtema`, D-92, ampliado en E1-10c) | Una lista para cada uno de los 38 subtemas del catálogo (antes solo 6) | Supuesto/práctica. Salen de la columna «Incluye» de `docs/guia_temas.md` (con los paréntesis de salud, educación y seguridad: hospitales, CSS, MINSA, medicamentos; escuelas, clases, docentes; policía, operativos, cárceles, delitos) y de las formas léxicas directas de esas palabras; seguridad ciudadana agrega los nombres de los delitos y de los actos de un operativo (homicidio, robo, asalto, aprehensión, detención, reclusión, droga), que la guía incluye en «delitos» y «operativos». Palabras sueltas ambiguas quedan fuera («banco»: Banco Mundial y BID; «luz»: «dar a luz»; «clase»: «clase media»; «precio(s)»: revisión del PR #23). Advertencia: el agente escribió las listas después de ver los titulares del snapshot; no se agregó ningún nombre propio de una noticia, pero la precisión se mide con etiquetas humanas de subtema (n e IC 95 %) cuando existan. Antes (D-92): Supuesto/práctica. Salen de la columna «Incluye» de `docs/guia_temas.md` más las formas léxicas directas de esas palabras (singular/plural, «desempleo»), no de los titulares del snapshot. «precio(s)» suelto se excluyó (revisión del PR #23): solo cuentan frases como «precio del combustible», «canasta básica», «IPC», «costo de la vida»; los términos aceptados por léxico no se evaluaron aún fuera de los ejemplos excluidos (los 2 grupos aceptados así en el snapshot son de ejemplos excluidos). Un grupo conserva su subtema más cercano si el margen llega al mínimo **o** algún titular contiene un término de ese subtema (palabra completa, sin mayúsculas ni acentos); se guarda el criterio (`margen` o `lexico`). Un término de otro subtema no respalda. Se valida con etiquetas humanas de subtema (n e IC 95 %) cuando existan | `test_d92_*` |
| Magnitud mínima USGS | 3 | PDF (sección 6) | — |

## Extracción del snapshot (E0-04, `config/fuentes.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Ventana de noticias | 30 días, ampliable a 90 | PDF (sección 6) · D-74 | `validar_snapshot` (cobertura efectiva) |
| Volumen de A: meta · mínimo · TVN | 200 · 100 · 20 | PDF (sección 6) | `validar_snapshot` (mínimos = error, meta = advertencia) |
| `maxrecords` de GDELT | 250 | PDF (sección 6) · API | Subdivisión del rango si una consulta llega al tope |
| `ventana_noticias.ampliar_si_no_alcanza_minimo` | `true` (bandera explícita, no automática) | PDF (sección 6: "ampliar hasta 90 días") · E0-09 | Con `true`, si con 30 días no se llega al mínimo de 100 noticias, la extracción amplía a 90 (nunca más atrás: GDELT cubre ~3 meses). **El ruido no se puede medir en la extracción** (llega con E1-03b): la decisión cuenta los registros únicos del snapshot (RSS de TVN + patas vigentes de GDELT + crudos de consultas históricas; las noticias de las consultas anteriores a E0-04 también cuentan, porque D-89 las devuelve al snapshot), y la comprobación de "no ruido ≥ 100" queda **pendiente de E1-03b**, después de la limpieza. Con `false` solo avisa: **eso se aparta de la spec**, que manda ampliar. `test_la_ampliacion_a_90_dias_depende_de_la_bandera`, `test_la_decision_de_ampliar_cuenta_las_noticias_de_consultas_historicas` |
| Consultas de GDELT: patas por tema · términos | 2 patas (`locales`, `internacional`) × 4 temas = 8 llamadas por rango (antes 4). Los términos de las patas locales evitan palabras ambiguas en medios de Panamá (`canal` = canal de TV, `carga`, `visitantes`, `inversión` suelta): se usan "Canal de Panamá", ACP, "carga marítima", "llegada de visitantes", "inversión extranjera" | Supuesto (cada pata es una llamada porque la API no anida `OR` ni mezcla filtros de país) | Estimación offline con `scripts.estimar_consultas_gdelt` (solo mide ruido filtrado sobre lo que las consultas anteriores devolvieron, no el recall nuevo); la cobertura real se verá tras la nueva extracción. `test_terminos_de_las_patas_locales_no_son_ambiguos` |
| Consultas históricas (`gdelt.consultas_historicas`) | Los crudos sin pata (consultas anteriores a E0-04) alimentan `noticias.csv` (D-89, corrige D-83); el manifest los declara en `crudos_consulta_historica` con su consulta y su cobertura aparte | Decisión D-89 | `test_crudos_de_consultas_historicas_alimentan_el_snapshot_y_se_declaran`, `test_crudo_gdelt_de_nombre_desconocido_sigue_fallando` |
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
| Días para marcar una noticia como recirculada | 30 (detección − publicación > 30 días) | **Supuesto puro.** El PDF no da ningún umbral para T03: solo pide mostrar la fecha original y no presentarla como evento nuevo. 30 coincide con la ventana base de D-74, sin dato que lo calibre. Es una marca derivada, no filtra. **Con los datos reales es nula en los 221 registros del snapshot v1.2**, porque ninguna fuente aporta publicación y detección a la vez (RSS solo publicación, GDELT solo detección) | T03 (`tests/test_t03_recirculada.py`, con el fixture sintético); revisar si E1-03b o E1-06 cruzan fuentes |
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
| Origen sujeto al filtro de mención | `GDELT`; exentos: `TVN RSS` y medios con `pais_medio = Panamá` | **Supuesto** según E0-09: las consultas de GDELT piden "Panama" más un término amplio sin anclarlo al titular (motivo medido con las consultas anteriores a E0-04, que D-89 mantiene en el snapshot v1.2; con las patas nuevas se revisa cuando haya una extracción que las use, pues GDELT está en pausa por HTTP 429) | `test_gdelt_sin_mencion_de_panama_*` · `test_medio_panameno_o_tvn_nacional_*` |
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
| `umbral_sin_tema` y `margen_secundario` por modelo y método (reemplaza la fila antigua «Umbral "sin tema": por definir») | e5 · A 0.824 / 0.002 · e5 · B 0.797 / 0.004 · MiniLM · A 0.213 / 0.030 · MiniLM · B 0.283 / 0.019 | **Supuesto**: percentil 5 de la similitud máxima y percentil 25 de la brecha entre la 1.ª y la 2.ª, sobre 52 titulares únicos útiles (`python -m eval.calibrar_clasificacion`, recalculado tras corregir las referencias en X15). **No calibrado con etiquetas: E1-07b lo intentó (validación cruzada por evento) y con 5 `sin_tema` humanos ningún valor queda respaldado; se mantiene hasta tener ≥ ~30 positivos** (`docs/clasificacion.md`, «Diagnóstico de los errores de tema») | `test_bajo_el_umbral_*` · `test_tema_secundario_*` · `python -m eval.diagnostico_temas` |
| Centroide del método A | Media de la descripción y los ejemplos (peso igual) | Supuesto (el más simple; sin peso extra que calibrar) | Casos difíciles · etiquetas (E1-06) |
| Tema secundario | El 2.º tema por similitud si su diferencia con el 1.º ≤ `margen_secundario` y supera `umbral_sin_tema` | Supuesto | `test_tema_secundario_solo_si_esta_dentro_del_margen` |
| Baseline por palabras clave | Dos variantes: `guia` (solo términos literales de `docs/guia_temas.md` fuera de los casos difíciles; principal) y `ampliado` (guía + `extension`); puntaje = términos distintos que coinciden | Supuesto. La extensión la escribió quien ya había leído los casos difíciles y varios términos coinciden con ellos (`asep`, `asamblea`, `homicidio`, `aerolinea`): **no es independiente de los casos difíciles** y se reporta aparte (`baseline_ampliado`) | `test_h3_*` (cada término de `guia` está en la guía) · casos difíciles |
| `similitud_prototipo.umbral` | 0.774 (e5), **sin efecto** mientras `activo: false` | Supuesto (percentil 5 de la similitud con los prototipos de Panamá) | `eval.ruido` con E1-06; hoy dejaría un falso positivo evidente de 2 marcas (`docs/clasificacion.md`) |
| Solapamiento máximo de un caso difícil con una referencia | Jaccard de palabras < 0.8 (`eval.clasificacion.BASE_JACCARD`) | Supuesto (detector de fuga, no afecta ninguna decisión) | `test_el_detector_de_fuga_*` |
| Fuga semántica: coseno máximo entre un caso difícil y un ejemplo o prototipo | < 0.56 con MiniLM, ignorando «Panamá» (`fuga_semantica` en `clasificacion.yaml`); una excepción aceptada de forma explícita (CD-02 con un ejemplo real del snapshot, 0.566) | **Supuesto elegido después de ver los pares**: detecta las paráfrasis de CD-02, CD-11 y CD-12; CD-01 con el prototipo original daba 0.56 | `test_h4_ningun_ejemplo_ni_prototipo_parafrasea_un_caso_dificil` |
| Diagnóstico de errores de tema (E1-07b, `eval/diagnostico_temas.py`): pliegues · repeticiones · semilla | 5 · 20 · 20261007 | **Calibrado** (procedimiento declarado antes de medir; son constantes del módulo de evaluación, no parámetros del sistema, como en `eval/calibrar_clasificacion.py`) | `test_un_evento_nunca_esta_en_el_entrenamiento_y_en_la_prueba_a_la_vez` · `test_la_calibracion_cv_*` |
| Diagnóstico: porcentajes de abstención por margen · por parecido a «fuera de temas» | 10, 20, 30 % · 1, 5, 10 % de los 94 titulares útiles del snapshot | Supuesto (rejilla de exploración; el corte sale de un percentil del snapshot, **no de las etiquetas**) | Cada opción se mide con n e IC (`outputs/diagnostico_temas.json`) |
| Diagnóstico: mínimo de positivos para fiarse de una proporción o un AUC de abstención | 30 | Supuesto (regla práctica; con 5 `sin_tema` hoy el reporte marca `positivos_suficientes: false`) | `outputs/diagnostico_temas.json` |
| Diagnóstico: referencias exploratorias («fuera de temas» y Economía regional) | 10 textos y 1 frase + 6 ejemplos, en el módulo | Supuesto: escritos a partir de `docs/guia_temas.md` (Fuera de los temas) y de la regla D-84; **no se escribieron para parecerse a un titular etiquetado**, pero el diagnóstico ya había visto las etiquetas. No son parte del sistema | `docs/clasificacion.md`, opciones medidas |
| Unidad de análisis de la clasificación con etiquetas | El **evento** (`grupo` de la etiqueta; la noticia si no tiene): 63 filas = 29 eventos | Práctica estadística (los duplicados no son observaciones independientes) | `test_el_ic_por_evento_no_deja_que_un_evento_repetido_domine` |
| Clases de la evaluación | 6 temas + `sin_tema` (agrupa `fuera_de_temas` y `no_es_panama`) | `guia_temas.md` | `test_tema_a_id_*` |
| Macro-F1 | Media de los F1 definidos de las clases con soporte en las etiquetas; un F1 indefinido no cuenta como 0 | Práctica (se declara para no inflar ni hundir la media) | `test_una_clase_sin_soporte_*` |

## Agrupación y procedencias (E1-08, `config/reglas_v1.3.yaml`, `config/procedencias.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Modelo de la agrupación (`agrupacion.modelo`) | `minilm` | **Supuesto** razonado: con e5 y con MiniLM la validación cruzada empata (F1 0.916 y 0.916), pero con e5 el máximo es un solo punto del barrido al borde de un acantilado (0.845 → 45 falsos positivos a 0.84) y agrupa en el snapshot titulares que no son del mismo evento; MiniLM tiene una meseta de 6 puntos y comete errores por omisión, no por comisión (detalle en `docs/calibracion_agrupacion.md`). Es un modelo aparte del de la clasificación (`modelo_activo`, D-20) | `python -m eval.agrupacion --modelo e5` frente a `--modelo minilm` |
| Enlace del clustering | `average` con métrica `cosine` | Spec E1-08 | `test_titulares_del_mismo_evento_*` |
| `distance_threshold` | `1 − umbral_similitud` | Definición (distancia coseno = 1 − similitud) | `test_un_umbral_mas_alto_separa_*` |
| Barrido de calibración | 0.50 a 0.99 cada 0.005 (99 valores) | **Supuesto**: cubre las escalas de e5 (0.75–0.95) y MiniLM (0.3–0.95) | `test_el_barrido_incluye_los_extremos_*` |
| Regla de elección del umbral | Mayor F1 de pares; entre empatados, la mediana inferior de la meseta contigua más larga | Fijada antes de medir (D-16): un punto en el borde de una meseta es frágil | `test_en_una_meseta_elige_la_mitad_*` |
| Pliegues de la validación cruzada | 2, por hash SHA-1 del ID | **Supuesto**: con 100 etiquetas y 4 grupos humanos no cabe un conjunto reservado; la partición determinista da una cifra que la calibración no vio | `test_el_pliegue_es_determinista_*` |
| Dato de la agrupación | `titulo_limpio` (`usar_descripcion: false`) | Supuesto: los grupos humanos se etiquetaron por titular y la descripción es de uso interno (D-31) | — |
| Fecha de un titular | `fecha_publicacion`; si falta, `fecha_deteccion` (`campos_fecha`) | `reglas_v1.3.yaml` (`urgencia.fecha_sin_publicacion`) y D-74: la detección es solo una cota; la ventana de D-74 se mide sobre ella. El grupo guarda de qué campo sale cada fecha (`fecha_inicio_origen`, `fecha_fin_origen`) | `test_la_fecha_es_la_publicacion_y_si_falta_la_deteccion` |
| Hash del `GRP-` | `agrupacion.prefijo_id` `GRP-` · `largo_hash_id` 10 · `separador_ids` `\|` (SHA-1 de los `NOT-` ordenados) | D-63 (mismo largo que `NOT-`, `normalizacion.yaml`) | `test_id_de_grupo_*` · `test_mismo_snapshot_y_mismas_reglas_dan_los_mismos_ids` |
| Redes de sindicación | Big News Network: 17 dominios espejo (`procedencias.yaml`) | **Supuesto**: dominios con titulares idénticos y casi la misma hora en el snapshot del 2026-10-06; no se confirmó con el medio | `test_la_red_de_sindicacion_une_sus_sitios_espejo` · grupo de «Intensifying El Niño…» |
| Dominios de agencias | Xinhua, Prensa Latina, EFE, AFP, Reuters, AP, Europa Press, DPA, ANSA, Bloomberg (`agencias_por_dominio`) | Práctica: dominios oficiales de las agencias de `agencias` | `test_un_dominio_de_agencia_se_une_con_quien_la_nombra` |
| Alias de agencias | Associated Press, Agence France-Presse, Agencia EFE, Deutsche Presse-Agentur, Thomson Reuters, Noticias Prensa Latina | Práctica (nombres oficiales) | `test_la_agencia_nombrada_en_el_titular_une_a_sus_replicas` |
| Siglas sensibles a mayúsculas | EFE, AFP, AP, DPA, ANSA | Diseño: «ap» o «efe» en minúscula no son la agencia | `test_las_siglas_distinguen_mayusculas_y_los_nombres_no` |
| Tope de procedencias en E | 3 (de `evidencia.tope_procedencias`) | Supuesto (X02). **E1-10 debe calcular la parte de procedencias de E con `procedencias.fraccion_de_procedencias(n_procedencias)`**, nunca con `n_titulares` | `test_las_procedencias_aportan_a_e_con_tope_y_sin_contar_titulares` · T02 |
| Grupos listados en el reporte | 5 (`GRUPOS_EN_REPORTE`) | Presentación: no afecta ninguna decisión | — |
| Regla entre idiomas | Pendiente: sin umbral propio | Una traducción cuenta como otra procedencia (puede sobrecontar); ver `docs/calibracion_agrupacion.md` | — |

El conteo de procedencias es una **estimación** (`grupos.estimado = true`, leyenda `etiqueta_estimado`): una traducción
independiente del mismo despacho cuenta como otra procedencia porque ninguna regla sabe que comparten origen.

## Sismos (E1-09b, `config/vinculos.yaml`, `config/fuentes.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Ventana de coincidencia (`ventana_coincidencia_dias`) | ± 2 días, medidos en horas entre la hora UTC del evento y la fecha de la noticia (borde inclusivo) | Supuesto (el valor ya figuraba en «Organizar y contextualizar») | `test_el_borde_de_la_ventana_es_inclusivo_en_horas` · `test_sin_evento_dentro_de_la_ventana_o_bajo_la_magnitud_minima` |
| Magnitud mínima de coincidencia | `usgs.minmagnitude` de `fuentes.yaml` (3) | PDF (sección 6); no se duplica en `vinculos.yaml` | `test_sin_evento_dentro_de_la_ventana_o_bajo_la_magnitud_minima` |
| Fecha de la noticia | `campos_fecha` de `reglas_v1.3.yaml`: publicación y, solo si falta, detección; el uso de detección queda declarado en `origenes_fecha` y en la `regla` (`sismos.nota_fecha_deteccion`). Con varias noticias en el grupo se usa la más cercana al evento | Decisión de E1-09b (consistente con E1-08; nunca se sustituye en silencio) | `test_fecha_de_deteccion_solo_si_falta_la_de_publicacion_y_queda_declarado` · `test_la_publicacion_no_se_sustituye_por_la_deteccion_cuando_existe` |
| Cobertura de USGS | De `usgs.starttime` a `usgs.endtime` de `fuentes.yaml` (2024-01-01 a 2024-12-31, UTC); no está fija en el código. Noticias fuera del periodo no se comparan | PDF (sección 6) · Supuesto del fin (ver «Extracción del snapshot») | `test_noticia_de_2025_es_fuera_de_cobertura` · `test_la_cobertura_sale_de_fuentes_y_no_esta_fija_en_2024` |
| Grupo sin ninguna fecha | Motivo `sin_dato_en_periodo` (ya declarado en `motivos_sin_vinculo`) | Decisión de E1-09b | `test_noticia_sin_fecha_es_sin_dato_en_periodo` |
| Subtemas que se vinculan a USGS | Los de `vinculos.yaml` con `fuente: usgs` y `relacion: evento` (hoy `sismos`); el resto devuelve «no aplica» | Spec E1-09b | `test_lluvias_inundaciones_y_danos_nunca_se_vinculan_a_usgs` |
| Subtema de un grupo | El de E1-09 (`contexto.leer_grupos`): voto de los titulares sobre `similitud_tema` método B dentro del tema del grupo, aunque el método activo sea A; no se lee `subtema_clasificado` | Decisión de E1-09, reutilizada (X18) | `test_x18_un_grupo_de_sismos_se_vincula_con_la_base_del_metodo_a` |
| Precisión de `diferencia_horas` (`sismos.decimales_horas`) y formato de la hora UTC guardada (`sismos.formato_hora_utc`) | 2 decimales · `%Y-%m-%dT%H:%M:%SZ` | Supuesto (presentación; no cambia la coincidencia, que usa el tiempo exacto) | `test_un_evento_coincidente_da_vinculo_sis_con_todos_los_campos` |
| Unidad de la magnitud en `vinculos.unidad` (`sismos.unidad_magnitud`) | `magnitud` (USGS no fija el tipo en el contrato) | Supuesto | `test_las_filas_de_usgs_entran_en_el_esquema_y_el_reproceso_respeta_las_de_indicador` |
| Magnitud nula de un evento | Se conserva nula, no coincide con ninguna noticia y se cuenta (`eventos_sin_magnitud` en el reporte) | Decisión de E1-09b (O3): los nulos son nulos | `test_magnitud_nula_no_rompe_la_carga_ni_coincide_y_se_cuenta` |
| Zona y formato de la hora mostrada (`sismos.zona_horaria`, `sismos.formato_hora`) | `America/Panama`, `%Y-%m-%d %H:%M`; el dato se guarda en UTC | CLAUDE.md (hora de Panamá solo en la interfaz) | `test_un_evento_coincidente_da_vinculo_sis_con_todos_los_campos` |
| Limitaciones fijas (`sismos.limitaciones`) y plantilla de la regla (`sismos.plantilla_regla`) | Tres frases: lugar posiblemente fuera de Panamá, la fuente no informa daños, un evento automático puede cambiar | Spec E1-09b | mismo test; `test_el_bloque_sismos_prohibe_claves_desconocidas_y_zonas_invalidas` |
| Borde de la cobertura | Una noticia de los primeros días de 2024 puede tener un evento de finales de 2023 dentro de su ventana, que la extracción no pidió: puede dar `sin_evento_coincidente` en vez de `fuera_de_cobertura` | Límite conocido (no se amplía la cobertura) | — |

## Consulta y generación

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

## Validador de citas (E1-13 · `config/validador.yaml`)

Las listas de frases prohibidas siguen en `config/restricciones.yaml` y los límites de palabras y cantidades en `config/salidas.yaml`; aquí están los valores propios del validador. Toda lista de palabras es un **supuesto** nuestro (el reto fija las prohibiciones, no el léxico) y se calibra con la tasa de rechazo real.

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Normalización de cifras | «1,5 %» = «1.5»; «1.234,5» = «1,234.5»; «1.234» vale 1.234 o 1234 (se acepta si cualquiera de los dos respalda la cifra) | Spec E1-13 (normalizar antes de comparar) | `test_coma_o_punto_decimal_*`, `test_el_separador_de_miles_se_normaliza` |
| Tolerancia absoluta de cifras (`numeros.tolerancia_absoluta`) | 0.0 | Supuesto (una cifra distinta es otra cifra) | `test_una_cifra_que_no_coincide_*` |
| Redondeo (`numeros.redondeo_permitido`, `decimales_minimos`, `decimales_maximos`, `tolerancia_relativa`) | Solo si el texto escribe **al menos 1 decimal** (hasta 6): «2.9 %» respalda 2.934; «1,49 %» respalda 1.5 (diferencia ≤ 1 % del valor citado); «2 %» **no** respalda 1.5 ni «3 %» 2.9 | Supuesto (un texto periodístico redondea a la precisión que escribe; un entero cambiaba el valor hasta un 33 %: M2 del PR #29) | `test_el_redondeo_a_entero_no_cambia_el_valor`, `test_la_cifra_redondeada_se_acepta_y_la_distinta_no` |
| Cifras en palabras (`palabras_numero`, `multiplicadores`) | «tres», «mil quinientos», «dos coma nueve» se convierten a cifra y se comparan como cualquier cifra; «un/una/uno» solos no cuentan; «por ciento» no es 100 | Supuesto (M1 del PR #29) | `test_una_cifra_en_palabras_*` |
| Cantidades vagas (`cantidades_vagas`) | «miles de», «decenas de», «la mitad», «el doble»… se rechazan salvo que el campo citado (o la afirmación de apoyo) las traiga literales; tampoco en una transición | Supuesto (M1) | `test_una_cantidad_vaga_*` |
| Marcadores condicionales | podría, es posible, sería, habría, quizá, a verificar, no se descarta, de confirmarse… | Spec E1-13 (D-41); lista ampliada: supuesto | `test_una_hipotesis_sin_marcador_condicional_se_rechaza` |
| Conectores causales | causó, provocó, debido a, por culpa de, a raíz de, porque, ya que, gracias a, por lo que, dado que, por eso, fruto de, derivó en, lo que provocó, impulsado por… | Spec E1-13 (D-68); lista ampliada: supuesto (M1 del PR #29) | `test_causalidad_*`, `test_mas_conectores_causales_en_un_hecho` |
| Acusaciones | Verbos (robó), **participios e infinitivos** (robado, robar: cubren «habría malversado» y «podría haber robado»), adjetivos (corrupto, culpable), **sustantivos** (robo, fraude, corrupción, malversación, soborno, peculado, desfalco) y «implicado en». Se comparan **con tildes**: «robó» y «robo» son entradas distintas. Como hecho, inferencia, hipótesis o en el cuerpo se rechazan siempre; una declaración las admite solo atribuida a un medio y presentes literales en el campo citado (una nota sobre un robo pasa si el titular dice «robo») | Spec E1-13 (D-68); X29 del PR #29 (el léxico solo en indicativo dejaba pasar la hipótesis en condicional); léxico: supuesto | `test_una_acusacion_*`, `test_el_sustantivo_robo_y_el_verbo_robo_*` |
| Palabras volátiles junto a un `IND-` | actual, actualmente, hoy, en la actualidad, a la fecha, en este momento, vigente, este año, recientemente, ayer (`generacion.yaml:volatiles`) | CLAUDE.md («actual», «hoy»); las demás, supuesto (M1) | `test_mas_volatiles_junto_a_un_dato_anual` |
| Lectura simulada y entrevistas (patrones) | `patrones.lectura_simulada` (artículo, nota, reportaje, texto, noticia + explica, detalla, indica…) y `patrones.entrevistas` («dijo a TVN», «declaró a la prensa»), además de las frases de `restricciones.yaml`; la excepción del titular literal sigue valiendo para entrevistas | Spec E1-13 (D-51, D-53); patrones: supuesto (M1) | `test_mas_lectura_simulada`, `test_mas_frases_de_entrevista_*` |
| Comillas simples | `'…'` se tratan como comillas y deben ser literales del campo citado; un apóstrofo entre letras no abre una cita | D-45; M1 | `test_las_comillas_simples_*`, `test_un_apostrofo_no_es_una_comilla` |
| Juicios en transiciones (`juicios_transicion`) | mala noticia, preocupante, grave, lamentable, importante, urgente… no pueden ir en una oración sin cita | Supuesto (M4: una transición no afirma) | `test_una_transicion_no_lleva_juicios_evaluativos` |
| Detalle sin cita | fuentes oficiales, fuentes confirmaron, confirmaron, testigos, según expertos… | Spec E1-13 (D-51, «cualquier detalle sin cita») y PR #26; lista: supuesto | `test_un_detalle_sin_cita_se_rechaza` |
| Excepción del titular literal | `entrevistas`, `sensacionalistas` (salvo título, titulares y copy) y `perdidas_en_inferencias` admiten la frase si está literal en un titular citado; `lectura_simulada`, `imagenes`, `recomendacion` y `certeza` no | Spec E1-13 (D-53, banca de `docs/salidas.md`) | `test_una_frase_de_entrevista_inventada_*`, `test_las_reglas_de_banca_vienen_del_yaml` |
| Transiciones sin cita | máximo 1 por sección (`salidas.yaml`), de a lo más 15 palabras, solo en brief, resumen web y guion, sin cifras, fechas, nombres ni entidades | Spec E1-13 (D-41); 15 palabras y secciones: supuesto | `test_una_transicion_*`, `test_mas_transiciones_que_el_maximo_*` |
| Nombre nuevo | Una palabra con mayúscula que no abre la oración (o dos que la abren) y que ni el campo citado, ni su contexto (medio, indicador), ni las afirmaciones de apoyo traen; «Panamá» siempre se admite. **Ahora también en hechos y declaraciones** (paso 1): «Colombia» sobre un `IND-PAN`, «el FMI», «Juan Pérez» o «el Canal» en un conteo se rechazan | Spec E1-13 (D-41, D-51); X30 del PR #29; heurística conservadora (0 rechazos sobre 40 afirmaciones de la caché antes del cambio) | `test_una_inferencia_con_un_nombre_nuevo_*`, `test_un_dato_oficial_de_panama_no_se_atribuye_a_otro_pais`, `test_una_declaracion_no_trae_personas_*` |
| Atribución al medio correcto | Una declaración que nombra a un medio de la ficha que no es el de su cita se rechaza (`atribucion_incorrecta`) | X30 | `test_una_declaracion_se_atribuye_al_medio_del_registro_citado` |
| Titulares traducidos (`equivalencias_traduccion`, `cognados_prefijo_min`) | Una cita de un titular en otro idioma admite las formas españolas de una tabla de equivalencias (América Latina / Latin America) y los cognados que comparten 5 letras de prefijo (Singapur / Singapore); una entidad ausente del titular y de la tabla se rechaza | D-45; X30 (6 declaraciones traducidas de GRP-79f3183472 marcaban «América Latina») | `test_la_traduccion_cambia_la_forma_de_un_nombre_*` |
| Fecha | ISO, «5 de octubre [de 2026]», «octubre de 2026», un año o un mes del texto deben coincidir con un campo de fecha de la evidencia citada (`campos_fecha`), el año del ID o una fecha que diga el propio titular | Spec E1-13 (D-45) | `test_una_fecha_que_no_coincide_*` |
| Año de un dato anual | Una afirmación lleva el año de cada ID `IND-` que cita; una oración que resume varios, al menos uno | CLAUDE.md; la segunda parte es supuesto (m1 del PR #26) | `test_una_oracion_que_resume_varios_anios_*` |
| Contradicción abierta | ambas versiones en brief, resumen web y guion; no se exige en título, titulares ni copy | Spec E1-13; el alcance es supuesto (m4 del PR #26) | `test_con_una_contradiccion_abierta_*` |
| Atribución | toda oración basada en una declaración nombra al medio o usa un verbo de reporte (`generacion.yaml`); una línea solo de hashtags no | Spec E1-13 (D-41); la excepción de hashtags nació de la prueba real | `test_una_declaracion_en_el_cuerpo_sin_atribucion_*`, `test_una_oracion_solo_de_hashtags_*` |
| Registro de rechazos (`registro`) | `outputs/rechazos.jsonl`, una línea `rechazo` por cada rechazo y una `evaluacion` por unidad evaluada (afirmación o sección) con `proveedor`, `modelo`, `id_caso`, `seccion`, `item`, `intento`, `ts` UTC. Nunca el valor de un secreto ni el system prompt. Ignorado por git | Spec E1-13 | `test_cada_rechazo_queda_registrado_*`, `test_el_registro_nunca_copia_un_secreto_*` |
| Tasa de rechazo | Por modelo: unidades rechazadas / evaluadas. Por regla **y por tipo de unidad** (`afirmacion`, `seccion:brief`, `seccion:enfoque`…): unidades de ese tipo en que la regla rechazó (una vez por unidad) / evaluadas **de ese tipo** (L2 del PR #29). Siempre con n e IC de Wilson al 95 % (`python -m src.validador --tasas`). Un reintento cuenta como otra unidad; la caída por base descartada (`base_invalida`) cuenta aparte | CLAUDE.md (proporciones con n e IC) | `test_el_registro_permite_calcular_la_tasa_*` |

### Compuerta final y caché

- **Reintento del paso 1 sin inferencia** (`afirmaciones.exigir_inferencia: true`, `generacion.yaml`): en la medición real 17 de 21 enfoques salían vacíos porque la única inferencia traía «porque» (D-68). Si ninguna inferencia o hipótesis pasa la validación se reintenta una vez con el motivo; si el reintento tampoco la trae se conservan las afirmaciones válidas del primero (`test_si_ninguna_inferencia_sobrevive_*`). Supuesto nuestro: un enfoque vacío cuesta más que una llamada.

- `Generador.paquete()` pasa el paquete armado por `validar_paquete`: una sección que no valida se vacía con su motivo en `vacios` (`test_el_paquete_pasa_por_la_compuerta_final_*`). `Consultor` rechaza una leyenda de alcance que no sea la de `restricciones.yaml` (`test_el_consultor_exige_una_leyenda_valida`); la respuesta de consulta es extractiva y no pasa por las reglas de redacción.
- `calentar_cache --verificar` dice **«con vacíos (…)»** cuando una sección quedó vacía por la validación, y `--podar` borra las respuestas que ningún grupo verificado usa (`CacheLlm.usadas`/`podar`).

### Tasa de rechazo medida con DeepSeek (E1-13, 2026-10-06)

`deepseek-flash`, 11 paquetes reales (`python -m src.generacion --grupo …`: 1 «Borrador opcional», 6 completos forzados y 4 de investigación, de la bandeja), con los prompts `afirmaciones_ficha` 1.3 y `paquete_editorial` 1.2.

- **Unidades rechazadas: 34 de 136 (25 %, IC 95 % 18–33 %)**, contando cada intento (afirmaciones del paso 1 y secciones del paso 2). La mayoría se corrige en el reintento; las secciones que no, quedan vacías con su motivo.
- Por regla (unidades de 136): `enfoque_como_hecho` 10 · `limite_palabras` 8 (guion corto: con un solo titular no hay 110 palabras sin inventar) · `causalidad` 6 · `sin_atribucion` 5 · `nombre_nuevo` 4 · `base_invalida` 2 · `cifra_no_coincide` 2 · `hipotesis_sin_condicional` 1.
- Primera medición, con los prompts de E1-12 (1.2 y 1.1) sobre los 10 grupos de «Investigar ya»: la causalidad y el enfoque como hecho eran los motivos dominantes; los prompts 1.3 y 1.2 piden explícitamente lo que el validador exige (no es relajar reglas).
- Falsos positivos hallados y corregidos con prueba: línea solo de hashtags pedía atribución; «Según TVN…» al abrir una oración contaba como nombre; una oración que resumía 3 años exigía los 3.
- El costo del contador de `outputs/costo_llm.json` por las 3 rondas (≈ 32 paquetes): ≈ USD 0.14 (estimación a tarifa pico, cota superior).

## Evaluación

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Titulares etiquetados | ~100 | Supuesto (tiempo disponible) | Se reporta con IC |
| Muestra de validez de sustento | ≥ 30 afirmaciones | PDF | Se reporta con IC |
| Benchmark | 60 (30 · 10 · 10 · 10), 40 desarrollo / 20 reservadas **del jurado** | PDF | — |
| Intervalos de confianza | 95 %, bootstrap de 1.000 remuestreos | Práctica estadística | — |
| Semillas aleatorias | Fijas en `config/` (etiquetado, bootstrap, clustering si aplica) | Práctica (reproducibilidad) | `scripts.reproducir` (D-65) |
| Benchmark del equipo (si la organización no lo entrega) | 40 de desarrollo: 20 · 7 · 7 · 6 | PDF (proporciones de la sección 7) | `eval.validar_benchmark` |
| Sensibilidad X02 | Pesos ± 5; parámetros supuestos ± 20 % | Supuesto (spec E1-10) | `python -m eval.sensibilidad` (E1-10): top 5 de cada variante, con n e IC de Wilson de las variantes que no lo cambian |
| Precision@5 | 3 fechas de corte si hay editor; si no, n = 1 y exploratoria | PDF (exploratoria sin especialista) | `python -m eval.precision_at_5` (E1-19; ver sección siguiente) |
| Duración de la demo | 4 min | PDF | Ensayo cronometrado |

## Precision@5 y prueba de tiempo (E1-19 · `config/precision.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| `k` | 5 | PDF 9.1 (Precision@5: el editor elige 5 temas) | `eval/precision_at_5.py` exige exactamente `k` marcas por corte |
| `cortes_minimos` | 3 | Spec E1-19 y D-57 (3 fechas de corte distintas si hay editor) | Con menos cortes el resultado se declara exploratorio; con 1, n = 1. Sin `--especialista` es exploratorio siempre (D-74) |
| `hoja_ciega.semilla` | `e1-19-hoja-ciega` | Práctica (orden reproducible que no depende de P, posición ni fecha) | `tests/test_e1_19_precision.py`: el orden no cambia si cambian P y fechas |
| `hoja_ciega.marca` | `x` | Convención de la hoja | Lectura de `eval/seleccion_editor.csv` |
| Baseline «ranking por fecha» | Máximo de `fecha_publicacion` de las noticias del grupo, descendente; sin fecha de publicación al final; empate por ID. Nunca la fecha de detección | PDF sección 8 y reglas de datos (publicación ≠ detección) | Test del baseline con un grupo solo-GDELT; el reporte y el JSON cuentan los grupos sin fecha de publicación |
| Pruebas de tiempo por condición | ≥ 3 (6 en total, orden alternado) | `docs/protocolo_evaluacion.md` sección 6 (D-71) | `docs/prueba_tiempo.md`: se reporta n; con pocas pruebas, exploratorio |

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

## Generación del borrador (E1-12 · `config/generacion.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Reintentos por llamada | 1 | Spec E1-12 (un reintento ante salida inválida). Cubre JSON que no cumple el esquema y sección que no pasa la validación; un fallo de transporte no se reintenta | `test_json_invalido_se_reintenta_una_vez`, `test_json_invalido_dos_veces_deja_la_seccion_vacia_con_el_motivo` |
| Afirmaciones: mínimo válidas / máximo | 1 / 8 | Supuesto (sin al menos una no hay nada que redactar; 8 acota el contexto de `num_ctx`) | `test_sin_ninguna_afirmacion_valida_no_se_redacta_nada_y_se_dice_por_que` |
| Acciones → qué se genera | completo: Producir borrador, Borrador opcional · completo con vacíos: Completar evidencia y producir · investigación: Investigar ya, Vigilar · nada: Archivar, Archivar como contexto | D-42 (docs/salidas.md). «Borrador opcional» (atención media, evidencia suficiente) se trata como completo porque la persona lo pidió; «Archivar como contexto» como nada: **supuesto** | `test_producir_borrador_*`, `test_investigar_ya_y_vigilar_*`, `test_archivar_*` |
| Prefijos de dato oficial / de reporte | IND-, SIS-, SBP- / NOT-, SYN- | CLAUDE.md (IDs estables, D-63); `SYN-` = casos sintéticos | `test_un_hecho_que_cita_solo_un_titular_*`, `test_un_conteo_de_reportes_si_puede_ser_hecho` |
| Verbos de atribución | reporta/n, reportó, informa/n, según, señala/n, indica/n, publica/n, afirma/n… | Supuesto (verbos de reporte de docs/salidas.md; amplía los de `llm.yaml`) | `test_un_titulo_que_es_declaracion_lleva_atribucion` |
| Marca de traducción | `(traducido)`; idioma base `es` | D-45 | `test_una_cita_de_un_titular_en_ingles_se_marca_como_traducida` |
| Fuga del system prompt | 6 palabras consecutivas iguales | Supuesto (T07; una frase corta legítima no coincide con 6 palabras seguidas del prompt) | `tests/test_t07_inyeccion.py` |
| Llamadas por paquete | 1 de afirmaciones + 4 de redacción (título · brief · guion · resumen); investigación: 1 + 1 | D-44 / spec E1-12 | `test_producir_borrador_da_el_paquete_completo_*`, `test_cada_grupo_se_genera_solo_cuando_se_pide` |
| DeepSeek: modelo, `max_tokens`, timeout | `deepseek-flash` (sobrescribible con `DEEPSEEK_MODEL` en `local.env`), 1536, 120 s | Supuesto (proveedor único durante el evento, D-94 y D-95; `max_tokens` ≈ 3× la salida medida del modelo local) | `scripts.medir_generacion --proveedor deepseek` |
| DeepSeek: precio USD por millón de tokens | entrada (sin caché) 0.30 · salida 1.20 | **Fuente:** https://api-docs.deepseek.com/quick_start/pricing, consultada el 2026-10-06. `deepseek-flash`: entrada sin caché 0.15 off-peak / 0.30 pico; salida 0.60 off-peak / 1.20 pico (pico = 01:00–04:00 y 06:00–10:00 UTC, lunes a viernes, salvo feriados chinos). Se usa la tarifa pico, conservadora. La página no menciona `deepseek-chat` ni `deepseek-reasoner`: las mediciones previas con `deepseek-chat` funcionaron (alias heredado, sin garantía oficial) y se cambió al modelo documentado. Verificar contra la factura | `test_bajo_el_tope_se_usa_deepseek_y_se_acumula_el_costo` |
| Tope de costo (D-67, D-95, D-98) | **200 000 000 tokens y USD 100.00** acumulados (D-98: el dueño decidió gastar hasta agotar el saldo de la cuenta; antes 10 000 000 y USD 5.00 por D-97, y 1 000 000 y USD 0.50 al inicio). Queda **solo como guarda contra un bucle descontrolado** (CLAUDE.md exige un tope); el límite real es el saldo. **Al alcanzarlo la generación se detiene** con `TopeDeCostoAlcanzado` (sin respaldo local); registro en `outputs/costo_llm.json` | Decisión del dueño (D-98). Antes: supuesto (un paquete completo medido con DeepSeek ≈ 16 000 tokens y ≈ USD 0.005) | `test_al_superar_el_tope_de_tokens_*`, `test_al_superar_el_tope_de_usd_*`, `test_el_acumulado_persiste_entre_ejecuciones` |
| Medición de latencia | 5 repeticiones, 1 de calentamiento, percentil 95 | Supuesto (n pequeño: el p95 con n = 5 es el máximo; se reporta con su n) | `scripts.medir_generacion` |
| Límites de palabras y cantidades de cada sección | En `config/salidas.yaml` | docs/salidas.md | `test_limites_*`, `test_el_guion_respeta_el_rango_*` |
| Proveedor durante el evento | **DeepSeek es el único proveedor de generación** (`LLM_PROVIDER=deepseek` en `local.env`), con tope de costo. Ollama sigue soportado por configuración pero apagado: no se usa y no es respaldo | Decisión del dueño (D-94, D-95): `qwen3.5:9b` local era demasiado lento. Evidencia histórica: Ollama local, medición parcial interrumpida por lentitud (una corrida completa, n = 1: ≈ 110–150 s por paquete) frente a ≈ 16 s con DeepSeek | `outputs/latencia_generacion_deepseek.json` |
| Latencia con DeepSeek (n = 5) | Primera respuesta: mediana 7.8 s, p95 8.2 s · paquete completo: mediana 16.6 s, p95 17.2 s (con n = 5 el p95 es el máximo); ≈ 15 000 tokens (11 817 entrada + 3 355 salida) y ≈ USD 0.0076 por paquete con `deepseek-flash` a tarifa pico | Medición real (E1-12) | `poetry run python -m scripts.medir_generacion --proveedor deepseek` |
| Secciones vacías por límite de palabras | Antes (ficha de prueba, `deepseek-chat`, n = 5 paquetes): 6 de 40 secciones vacías (15 %). Después (prompt v1.1 con límites estrictos y objetivo de longitud, límites numéricos en el mensaje, `deepseek-flash` sin razonamiento, recorte de oraciones finales tras el reintento): 0 de 40 vacías en la misma ficha (7 de 40 recortadas: copy y resumen web) y 1 de 24 vacías en 3 paquetes completos de grupos reales (antes del recorte) | Medición real (E1-12). Los máximos de brief (250), copy (80) y guion (45–60 s) son del PDF y no se relajan; resumen web (120), título y titulares (14) y el rango de palabras del guion son supuestos nuestros (D-10, calibrable) y se mantienen. El recorte solo quita oraciones del final de brief, resumen web y copy (`recortables`), nunca reescribe, y lo deja en `vacios` | `test_una_seccion_que_solo_supera_el_maximo_*`; `scripts.medir_generacion` |
| Objetivo de longitud del aviso de reintento | 0.8 del máximo | Supuesto | `scripts.medir_generacion` |
| `deepseek-flash` y el razonamiento | Se envía `thinking: disabled` (`llm.yaml` · `generacion.pensar: false`) | Observación real: con razonamiento activo (el valor por defecto) el razonamiento consume `max_tokens` y `content` llega vacío | `test_deepseek_pide_json_con_temperatura_cero_*` |
| Recorte tras el reintento (D-96) | Si brief, resumen web o copy solo fallan por exceso de palabras tras el reintento, se quitan oraciones **enteras del final** hasta que caben, se revalida y se deja una nota `recortada…` en `vacios`. Nunca se reescribe ni se agrega texto; no se recorta la leyenda; si quitar el final dejaría una contradicción con una sola versión, la sección queda vacía | Decisión D-96 (revisión del PR #26); supuesto nuestro, los máximos del PDF no se relajan | `test_una_seccion_que_solo_supera_el_maximo_*`, `test_el_recorte_nunca_deja_una_contradiccion_*` |
| Delimitador de evidencia (X27) | `<` y `>` de todo texto derivado de fuentes o del LLM pasan a `‹` y `›` en el mensaje de usuario, incluido el aviso del reintento; hay exactamente una apertura y un cierre | Revisión del PR #26 (X27) | `test_ninguna_variante_del_delimitador_se_cuela_*` (T07) |
| Qué puede ser `hecho` (X28) | Solo `hecho_oficial` (IND-, SIS-, SBP-) o `hecho_conteo` (GRP- con los campos de `campos_conteo`); nunca un titular, ni siquiera dos. Una acusación es siempre una declaración atribuida (D-18, D-68). Las acusaciones no se detectan por léxico aquí: lo hace el validador de E1-13 | Revisión del PR #26 (X28) | `test_un_hecho_solo_cita_datos_oficiales_o_el_conteo_del_grupo_*` |
| Campos citables | Solo los que la ficha cita (`titulo_limpio`, `valor`, `magnitude`, `n_*`); medio, fecha, año e indicador son contexto y no se citan. Cada ID `IND-` lleva el valor de **su** año y el año de su ID | Revisión del PR #26 (m1) | `test_solo_son_citables_los_campos_que_la_ficha_cita_*` |
| Palabras volátiles, patrón del año en el ID y patrón del valor por año | `volatiles`, `patron_anio_en_id`, `patron_valor_por_anio` en `config/generacion.yaml` | CLAUDE.md («actual», «hoy»); formato de la línea de `src/ficha.py` | `test_las_listas_de_la_validacion_viven_en_el_yaml` |
| Registro de costo corrupto | Falla cerrado (`ErrorProveedor`); no se reinicia el acumulado en silencio | Revisión del PR #26 | `test_un_registro_de_costo_corrupto_falla_cerrado_*` |
| Forzar el paquete completo | Permitido para cualquier acción conocida (D-42: «la persona puede forzar el paquete completo y queda registrado»), incluida «Archivar»; una acción desconocida nunca genera | D-42 | `test_forzar_el_paquete_completo_no_genera_para_una_accion_desconocida` |
| El contador de costo es una estimación | `outputs/costo_llm.json` acumula los tokens que devuelve la API (`usage`) × el precio **pico** configurado: es una **estimación**, no la factura del proveedor. Se reinició una vez al cambiar de `deepseek-chat` a `deepseek-flash` (el total real en ese momento era ≈ USD 0.29); desde entonces acumula sin reinicios | Decisión de diseño (E1-12) | Comparar con la factura de DeepSeek |
| Calibración del estimador de costo (D-97) | El 2026-10-06 la consola de DeepSeek marcaba un gasto real de **USD 0.11** frente a ≈ **USD 0.29** estimados por el contador (0.267 acumulado más lo gastado antes del reinicio): el estimador sobreestima ≈ 2.6×. Se mantiene el precio pico sin descuento por caché: un tope que sobreestima es seguro, y el contador es una **cota superior conservadora**, no la factura | Medición real (consola de DeepSeek) y decisión D-97 | Comparar periódicamente con la consola |

## Caché y modo offline (E1-14 · `config/cache.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Clave de la caché | SHA-256 de versión de la caché · proveedor · modelo · versión del prompt · temperatura y semilla · mensaje de sistema · mensaje de usuario (evidencia) · esquema | Spec E1-14 («hash de proveedor + modelo + versión del prompt + evidencia»), ampliada con el resto de la petición para que nada la deje desactualizada | `test_la_clave_es_determinista_y_cambia_con_cada_parte_de_la_peticion`, `test_la_clave_de_la_peticion_no_depende_del_orden_de_hash_del_proceso` |
| Dónde se cachea | Cada llamada al proveedor (paso 1, cada grupo, cada reintento), no solo el paquete; la validación se repite al leer | Decisión de diseño (E1-14): un validador más estricto (E1-13) se aplica a lo guardado sin llamar de nuevo | `test_la_cache_cubre_cada_reintento`, `test_una_primera_respuesta_invalida_seguida_de_un_reintento_valido_se_reconstruye_desde_la_cache` |
| `version_cache` | `"1"`; subirla invalida toda la caché | Supuesto (palanca manual para invalidar tras cambios fuera de la clave) | `test_subir_version_cache_invalida_toda_la_cache` |
| `proveedor_por_defecto` | `deepseek` (se usa si `LLM_PROVIDER` está vacío en `local.env`) | D-94, D-95: leer la caché no debe depender de un `local.env` completo | `test_con_llm_provider_vacio_se_lee_la_cache_con_el_proveedor_por_defecto` |
| `ruta` | `data/cache_llm/` (una respuesta por archivo, **versionada en git**) | Decisión de diseño: la máquina de la demo necesita los borradores sin red ni dinero. Solo contiene respuestas generadas (borradores), el proveedor, el modelo y cifras de uso: ni prompts, ni evidencia, ni claves, ni descripciones del RSS | `test_lo_guardado_es_la_respuesta_sin_prompts_ni_evidencia_ni_claves` |
| Respuestas inválidas | También se guardan (solo se descartan las vacías): el reintento de la generación necesita que la primera respuesta se repita igual | Hallazgo real al calentar: sin esto el grupo parecía «sin caché» | `test_una_respuesta_invalida_tambien_se_repite_igual_*` |
| `sondeo_red` | 2 s, puerto 443 | Supuesto (basta para distinguir «hay red» de «no hay»; nunca bloquea la interfaz, que no sondea) | `test_el_sondeo_de_red_dice_que_no_hay_red_sin_bloquear` |
| `variable_offline` | `HACKIATHON_OFFLINE=true` (en `local.env` o en el entorno) fuerza el modo solo caché | Decisión de diseño (ensayo de T10 con red disponible) | `test_sin_red_o_en_modo_offline_generar_se_comporta_como_solo_cache` |
| `paquete.etiquetas` (`config/interfaz.yaml`) | Nombre legible de cada campo del paquete en la pantalla *Paquete* (ej. `id_caso` → «Caso») | Texto de presentación (docs/salidas.md); sin etiqueta se usa el nombre del campo | `test_la_pantalla_paquete_usa_las_etiquetas_del_yaml` |
| `calentamiento` | Top 10 de la bandeja + todo `GRP-` del guion de la demo | Supuesto (cubre el recorrido de `docs/demo.md` y la fila que el jurado pueda abrir) | `scripts/calentar_cache.py --verificar` |
| Saldo agotado (D-98) | HTTP 402 de DeepSeek → `SaldoAgotado` (subtipo de `TopeDeCostoAlcanzado`): sin reintento, mensaje en español, la caché sigue sirviendo | Decisión del dueño (D-98) | `test_http_402_es_saldo_agotado_*`, `test_con_saldo_agotado_la_generacion_se_detiene_*` |

## Interfaz Streamlit (E1-15, `config/interfaz.yaml`)

Constantes de presentación: ninguna decide un puntaje, una acción ni un vacío (eso lo calculan E1-10 y E1-10b).

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Filas de la bandeja al abrir (`bandeja.filas_iniciales`) | 10 (el resto, con «Mostrar las N filas») | Supuesto (legibilidad; la demo señala las 5 primeras) | `test_la_bandeja_trae_reglas_corte_y_el_ranking_con_las_columnas_de_la_spec` |
| Alto de cada fila de la tabla (`bandeja.alto_filas_px`) | 36 px | Supuesto (solo presentación) | — |
| Decimales de P y de las barras al mostrar (`bandeja.decimales_puntaje`) | 1 (barras: 2) | Supuesto (solo presentación; el dato no se redondea) | — |
| Largo del titular en los selectores (`bandeja.largo_titular_selector`) | 80 caracteres | Supuesto (solo presentación) | — |
| Recuadros de cita por fila (`ficha.citas_por_fila`) | 3 | Supuesto (solo presentación) | — |
| Decimales del valor de un indicador en el recuadro de cita (`citas.decimales_valor`) | 2 | Supuesto (legibilidad; el dato no se redondea) | `test_la_precision_del_valor_sale_del_yaml` |
| Medios mostrados en Calidad (`calidad.top_medios`) | 5 | Supuesto (legibilidad) | `test_calidad_muestra_el_ruido_con_su_n_y_el_reporte_de_carga` |
| Método de consulta inicial (`consulta.metodo_inicial`) | `semantica` | E1-11 (método elegido sobre BM25) | `test_la_consulta_responde_con_citas_y_se_abstiene_diciendo_que_falta` |
| Largo máximo de la pregunta (`consulta.largo_maximo_caracteres`) | 500 | Supuesto (una pregunta, no un documento) | — |
| Campos que nunca se muestran (`ficha.campos_ocultos`) | `descripcion` | CLAUDE.md (D-31: la descripción del RSS es solo interna) | `test_la_descripcion_del_rss_nunca_se_muestra_ni_aunque_la_cita_la_pida` |
| Solo caché al pedir el borrador (`generacion.solo_cache`) | `true` | Spec E1-15 (funciona sin red; la interfaz no espera al modelo) | `test_con_generador_se_pide_solo_cache_y_se_aplanan_las_secciones` |
| Estados de revisión (`revision.estados`) | nuevo · en revisión · requiere evidencia · aprobado como borrador · descartado | PDF sección 8 (control humano) | `test_un_grupo_sin_caso_esta_en_el_estado_inicial` |
| Zona horaria y formato al mostrar | Los de `verificacion.yaml:presentacion` (`America/Panama`) | PDF (hora de Panamá solo en la interfaz) | `test_la_hora_se_muestra_en_panama_y_el_dato_no_cambia` |
| Intervalo de las proporciones de Calidad | Wilson, z = 1.96 (el de `carga.yaml`) | Práctica estadística | `test_el_resumen_de_calidad_cuenta_el_ruido_con_n_e_intervalo` |

## Revisión humana y exportación (E1-16, `config/revision.yaml`)

Ninguno decide un puntaje, una acción ni un vacío: solo gobiernan quién puede hacer qué y cómo se exporta.

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Estados (`estados`) | nuevo · en revisión · requiere evidencia · aprobado como borrador · descartado; ninguno va después de «aprobado como borrador» | PDF sección 8 (control humano) | `test_la_configuracion_define_los_cinco_estados_y_ninguno_despues_de_aprobar` |
| Acciones y transiciones (`acciones`) | abrir · aceptar · corregir · regenerar · pedir_evidencia · descartar · reabrir · rechazar/restaurar_vinculo, con sus estados de origen y destino | D-46 | `test_las_transiciones_que_no_estan_en_el_yaml_se_rechazan_sin_escribir_nada` y `test_cada_accion_produce_el_estado_correcto` |
| Botón de la aprobación | «Aprobar como borrador»; la ficha aprobada conserva la marca BORRADOR | Spec E1-16 (nunca «publicar») | `test_aprobar_como_borrador_conserva_la_marca_y_ya_no_se_puede_repetir` |
| Motivos de descarte (`motivos_descarte`) | 7 motivos; «Otro» exige además un comentario | Supuesto (criterios de `docs/guia_temas.md` y de la revisión editorial) | `test_descartar_sin_motivo_de_la_lista_se_rechaza` |
| Revisores (`revisores`) | David Fen, Javier Acosta y Juan Zhou; rol «Revisión editorial» en editorial y «Analista» en banca. **Sin autenticación**: el registro confía en la elección (limitación declarada) | D-49; se reemplaza por la lista real antes del evento | `test_el_revisor_se_elige_de_la_lista_con_su_rol_y_la_limitacion_se_declara` |
| ID de caso (`casos`) | `CASO-` + correlativo de 3 dígitos; el mismo grupo abre siempre el mismo caso | D-63 | `test_abrir_un_grupo_crea_un_caso_correlativo_y_estable_que_persiste_entre_corridas` |
| Base de las revisiones (`almacen`) | `data/revision.duckdb` (demo: `data/revision_demo.duckdb`), aparte de `senales.duckdb`: el pipeline regenera esa base y borraría las revisiones | Decisión de E1-16 | `test_la_base_de_senales_no_cambia_al_revisar` |
| Registro de solo agregar | `casos`, `versiones` y `revisiones` solo reciben `INSERT`; ninguna fila se actualiza ni se borra | D-47 | `test_la_tabla_revisiones_solo_crece_y_ninguna_fila_se_modifica` y `test_la_api_no_tiene_ni_una_sentencia_de_modificar_o_borrar` |
| Revalidación de una corrección | Cada texto corregido pasa por `src/validador.py` (`validar_afirmaciones` y `validar_seccion`, las mismas reglas que la generación); cada rechazo nuevo es una advertencia con el nombre de su regla que la persona confirma o la corrección no se guarda. Sin reglas locales | D-48, E1-13 | `test_una_correccion_con_un_dato_sin_cita_genera_advertencia_y_queda_registrada_si_se_confirma` y `test_la_revalidacion_llama_al_validador_y_no_a_las_funciones_privadas_de_la_generacion` |
| Vínculo rechazado | Se excluye de la ficha y del borrador regenerado; la ficha agrega el vacío `vinculo_rechazado`. Puntaje y estado de evidencia **no** se recalculan (los guarda E1-10) | Spec E1-16 | `test_un_vinculo_rechazado_no_aparece_en_el_borrador_regenerado` |
| Columnas del CSV (`exportacion.columnas`) | Las 24 propiedades editables de la base «Casos y evidencias» de Notion (leídas de Notion el 2026-10-06); `P` y `Rango` son fórmulas de Notion y no se exportan | D-50 | `test_las_columnas_del_csv_son_las_de_la_base_casos_y_evidencias_de_notion` |
| Largo de una propiedad de texto (`exportacion.max_caracteres_texto`) | 2000 caracteres; lo que sobra queda en el cuerpo (Markdown) | Límite de Notion por bloque de texto | `test_las_propiedades_largas_se_recortan_para_notion` |
| Intervalo de las tasas de revisión | Wilson, z = 1.96 (el de `carga.yaml`); toda tasa con su n; sin casos decididos, «sin datos» | `docs/protocolo_evaluacion.md` | `test_eval_calcula_tasas_con_n_e_intervalo_y_los_motivos` y `test_eval_sin_datos_lo_dice_y_no_inventa_cifras` |
| Tiempo de revisión por caso | Minutos entre la fila `abrir` y la última decisión (aprobar o descartar); es reloj, no esfuerzo | Supuesto | `test_eval_calcula_tasas_con_n_e_intervalo_y_los_motivos` |
| Exportación de la demo (`exportacion.carpeta_demo`, `fichas_jsonl_demo`) | `outputs/demo/notion/` y `outputs/demo/fichas.jsonl`, distintas de las reales | Revisión del PR #30 (X31, B1) | `test_exportar_desde_la_demo_deja_identicos_las_salidas_reales` |
| Ficha guardada por revisión (`fichas_revisadas`) | La `Ficha` se guarda al abrir, regenerar, rechazar o restaurar un vínculo y aprobar; se exporta desde ahí y un caso huérfano no rompe a los demás | Revisión del PR #30 (X32, B2 y M2) | `test_un_caso_huerfano_no_tumba_la_exportacion_de_los_demas` |
| Numeración de `CASO-` | Máximo conocido (base, `data/revision.casos.csv` y lo exportado) + 1: no se reutiliza si se borra la base | Revisión del PR #30 (X32, M1) | `test_borrar_la_base_de_revisiones_no_reutiliza_los_id` |
| «Pedir evidencia» | Exige enlazar al menos un vacío o, si la ficha no tiene ninguno, un motivo escrito | Spec E1-16 y revisión del PR #30 (L3) | `test_pedir_evidencia_exige_al_menos_un_vacio` |

## Benchmark y métricas (E1-18, `config/benchmark.yaml`, `eval/ia_vs_baseline.py`)

Ninguno de estos valores decide un puntaje, una acción ni qué se responde: solo gobiernan cómo se mide. Las metas de abstención, cobertura y latencia son las de `docs/protocolo_evaluacion.md`.

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Remuestreos · confianza · semilla del bootstrap (`intervalos`) | 2.000 · 0.95 · 42 | Práctica estadística (D-57; más remuestreos que los 1.000 de clasificación, porque aquí hay pocas consultas y el IC de un percentil es más ruidoso) | `test_la_configuracion_del_benchmark_trae_intervalos_y_muestra`; mismo resultado en dos corridas |
| Wilson junto al bootstrap | z = 1.96 | Práctica estadística: el bootstrap de una proporción 0/n o n/n se degenera en [p, p] (se marca `bootstrap_degenerado`) y Wilson sí informa | `test_el_bootstrap_degenerado_se_avisa_y_wilson_no_lo_es` |
| Muestra de validez de sustento (`sustento.muestra`) | 30 afirmaciones | PDF 9.1 («al menos 30, si se producen tantas»); si hay menos, se usan todas | `outputs/revision_sustento.csv` tiene 30 filas (pool de 108) |
| Semilla de la muestra (`sustento.semilla`) | 42 | Práctica (reproducibilidad: la misma muestra para las mismas salidas) | Re-correr no cambia el archivo (`estado_del_archivo: reescrita_sin_cambios`) |
| Meta de validez de sustento (`sustento.meta_validez`) | 0.9 | PDF 9.1 (≥ 90 %; solo cuenta «sustentada») | `eval.sustento` (pendiente de la revisión humana) |
| Veredictos (`sustento.veredictos`) | sustentada · parcial · no sustentada · tipo incorrecto | Spec E1-18 | `eval.sustento` rechaza cualquier otro valor |
| Curva del umbral (`analisis_umbral`) | de 0.82 a 0.90, paso 0.01 | Supuesto: rodea el umbral configurado (0.874); es **descriptiva**, nunca elige ni cambia el umbral | Tabla de sensibilidad en `outputs/metricas.json` y `docs/ia_vs_baseline.md`, sección 5 |
| Modalidad de la medición del LLM (`llm.modalidad`) | editorial | Modalidad principal del reto | `--medir-llm`, `outputs/benchmark/medicion_llm.json` |
| Meta de latencia | mediana ≤ 15 s | PDF 9.1 | `latencia.meta_sugerida` en `outputs/metricas.json`; se reporta por tipo de paquete |
| Soporte mínimo por tema en la comparación IA-vs-base (`SOPORTE_MINIMO_TEMA`) | 5 titulares humanos | Supuesto: con n = 1 un IC bootstrap se degenera; por debajo no se da veredicto por tema («soporte insuficiente») | `test_discordantes_*` y los de `docs/ia_vs_baseline.md` (el soporte lo aplica `eval/ia_vs_baseline.py`) |
| Ejemplos por caso (`EJEMPLOS_POR_CASO`) | 5 | Spec E1-18 (3 a 5 ejemplos de cada caso) | `docs/ia_vs_baseline.md` |
| Tamaño del top que se compara en el ranking (`TAMANO_TOP`) | 5 | El del Precision@5 de E1-19 | `ranking.solapamiento` en `outputs/ia_vs_baseline.json` |
| Regla de veredicto de IA vs. base | «gana»/«pierde» solo si el IC 95 % de la diferencia pareada excluye el cero (límites sin redondear) | D-21 y D-57 (fijada antes de medir) | `test_veredicto_solo_si_el_ic_excluye_el_cero` |
| Unidad de remuestreo en agrupación | El titular, no el par | Los pares comparten titulares y no son independientes; remuestrear pares daría IC demasiado estrechos | `test_bootstrap_por_titular_es_reproducible_y_pareado` |
| Medición de embeddings (`scripts/medir_embeddings.py`) | Hasta 200 titulares (`--n`; la base aportó 94), un proceso por modelo, RSS máximo del proceso | Supuesto (el tamaño de la muestra es solo de cómputo, no afecta ninguna métrica); cifras de `docs/modelos.md` (D-67) | `test_medir_embeddings_con_un_motor_falso_reporta_cifras_sin_costo` |

| Metas reportadas (`metas`) | abstención correcta ≥ 0.8 · latencia mediana ≤ 15 s | PDF 9.1 (antes escritas en `eval/run_benchmark.py`, ahora en `config/benchmark.yaml`) | `test_las_metas_de_abstencion_y_latencia_viven_en_la_configuracion` |
| Medición del LLM versionada | `outputs/benchmark/medicion_llm.json` (excepción en `.gitignore`); si falta, el runner avisa en consola y en `avisos` y deja `no_corrido` | X38 (revisión del PR #33) | `test_sin_medicion_del_llm_se_advierte_en_consola_y_en_las_metricas` · `test_la_medicion_del_llm_del_benchmark_de_desarrollo_se_versiona` |
