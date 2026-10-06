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
| Alcance por subtema | Tabla en YAML | Supuesto (criterio editorial) | Precision@5 y revisión editorial |
| Alcance geográfico | nacional 1 · provincial 0.6 · local 0.3 · desconocido 0.5 | Supuesto | X02 |
| Ventana de urgencia U | 1 a < 24 h → 0 a 7 días | Supuesto | X02 |
| Partes de E (procedencias · oficial · identificable) | 0.5 · 0.3 · 0.2 | Supuesto | X02 |
| Tope de procedencias en E | 3 | Supuesto | X02 |

## Estado de evidencia

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Procedencias para "parcial" / "suficiente" | 2 | Práctica (regla periodística de las dos fuentes independientes) | Revisión editorial |
| Dato oficial obligatorio si hay cifras | — | PDF (secciones 7 y 9: toda cifra con evidencia) | Test |

## Organizar y contextualizar

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Umbral de agrupación | Por definir | Calibrado (D-16) | F1 de pares con etiquetas · curva documentada |
| Ventana de agrupación | 7 días | Supuesto | X02 |
| Similitud para "mismo texto" en procedencias | 0.95 | Supuesto | Test CU-03 · etiquetas |
| Umbral "sin tema" | Por definir | Calibrado | Etiquetas humanas |
| Criterio opción A vs. B | IC 95 % de la diferencia de macro-F1 excluye 0 | Práctica estadística | Bootstrap |
| Umbrales de ruido | Por definir | Calibrado | X01 (precisión/recall) |
| Coincidencia de sismos | ± 2 días | Supuesto | Revisión con la exploración (E0-09) |
| Magnitud mínima USGS | 3 | PDF (sección 6) | — |

## Extracción del snapshot (E0-04, `config/fuentes.yaml`)

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Ventana de noticias | 30 días, ampliable a 90 | PDF (sección 6) · D-74 | `validar_snapshot` (cobertura efectiva) |
| Volumen de A: meta · mínimo · TVN | 200 · 100 · 20 | PDF (sección 6) | `validar_snapshot` (mínimos = error, meta = advertencia) |
| `maxrecords` de GDELT | 250 | PDF (sección 6) · API | Subdivisión del rango si una consulta llega al tope |
| `ventana_noticias.ampliar_si_no_alcanza_minimo` | `true` (bandera explícita, no automática) | PDF (sección 6: "ampliar hasta 90 días") · E0-09 | Con `true`, si con 30 días no se llega al mínimo de 100 noticias no ruido, la extracción amplía a 90 (nunca más atrás: GDELT cubre ~3 meses). Con `false` solo avisa. Evidencia: E0-09 halló que el mínimo útil no se cumple. `test_la_ampliacion_a_90_dias_depende_de_la_bandera` |
| Consultas de GDELT: patas por tema · términos | 2 patas (`locales`, `internacional`) × 4 temas = 8 llamadas por rango (antes 4) | Supuesto (cada pata es una llamada porque la API no anida `OR` ni mezcla filtros de país) | Estimación offline con `scripts.estimar_consultas_gdelt`; en la corrida real, `validar_snapshot` (no ruido ≥ 100) |
| Longitud mínima de un término de consulta | 3 caracteres | Supuesto (GDELT rechaza palabras muy cortas) | `test_terminos_invalidos_se_rechazan` |
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

## Consulta y generación

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Umbral de abstención | Por definir | Calibrado con el benchmark de desarrollo | Abstención correcta vs. abstenciones incorrectas |
| Temperatura | 0 | Práctica (reproducibilidad) | — |
| Reintentos ante JSON inválido | 1 | Supuesto | Tasa de JSON inválido |
| Cambio de proveedor: latencia | Mediana > 15 s | PDF (meta de 9.1) | Métrica de latencia |
| Cambio de proveedor: rechazo · JSON inválido | > 20 % · > 1 de 10 | Supuesto | E0-07 |

## Salidas

| Parámetro | Valor | Origen | Cómo se valida |
|---|---|---|---|
| Brief · copy · resumen bancario | ≤ 250 · ≤ 80 · ≤ 250 palabras | PDF | Test |
| Guion | 45–60 s | PDF | X03 |
| Guion en palabras | 110–150 | Calibrado | X03 (cronometrado) |
| Preguntas | Exactamente 3 | PDF | Test |
| Título · titulares · resumen web · hashtags | ≤ 14 · 2–3 · ≤ 120 · ≤ 2 | Supuesto (convención propia) | Tasa de corrección en revisión |
| Transiciones sin cita por sección | Máximo en YAML | Supuesto | Revisión editorial |

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
