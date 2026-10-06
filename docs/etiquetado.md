# Etiquetado humano (E1-06)

Las métricas de clasificación, agrupación y ruido se calculan sobre **etiquetas humanas** (sección 9.1). Este documento dice cómo se etiqueta, con qué muestra y cómo se mide el acuerdo. La herramienta (`eval/etiquetar.py`) **no etiqueta**: solo arma la muestra, la muestra y guarda lo que decide cada persona.

> **Estado:** las 100 etiquetas reales existen (2026-10-06): propuestas por el asistente y revisadas por Javier Acosta (D-85). Ver "Etiquetadores" y "Acuerdo"; el kappa entre etiquetadores no se midió.

## Tamaño y método

| | |
|---|---|
| Población | **170** noticias elegibles de `data/senales.duckdb` (186 en el snapshot menos los 16 titulares de ejemplo de `config/temas.yaml`, `config/ejemplos_excluidos.txt`, que nunca entran) |
| Muestra | **100** titulares, **estratificada** por la decisión del filtro automático de E1-03b, aleatoria dentro de cada estrato |
| Semilla | **20261006**, en `config/etiquetado.yaml` (`muestra.semilla`). Mismas noticias y misma semilla dan la misma muestra y el mismo orden |
| Qué se etiqueta | **Ruido** (`ninguno` · `no_es_panama` · `fuera_de_temas` · `no_es_noticia`), **tema principal** y **secundario** (opcional), **grupo de evento** y, si no es ruido, **alcance regional** (D-84) |
| Guía | `docs/guia_temas.md`; la herramienta la muestra en pantalla, con las reglas de frontera y la regla D-84 |
| Quién y cuándo | Cada etiqueta guarda `etiquetado_por` y `fecha_etiquetado` (UTC; la interfaz muestra hora de Panamá) |
| Qué ve la persona | Titular, medio, fechas y URL. **Nunca** la descripción del RSS (D-31), ni la decisión del filtro ni el estrato, ni las etiquetas de otra persona sobre un titular doble |
| Datos personales | **No** se escriben en la columna `nota` (ni nombres de personas ni contactos); la nota es solo para dudas sobre el criterio |

### Composición real (salida de `poetry run python -m eval.etiquetar --muestra`)

| Estrato | Población | Muestra | Peso (población / muestra) | Dobles |
|---|---|---|---|---|
| `no_ruido` (incluye 38 notas de alcance regional) | 63 | 63 | 1.000 | 14 |
| `ruido` | 107 | 37 | 2.892 | 6 |
| **Total** | **170** | **100** | | **20** |

- La cuota configurada es 70 no ruido y 30 ruido (`muestra.estratos`), pero el estrato "no ruido" solo tiene 63 noticias elegibles: se toma completo y el faltante (7) pasa al estrato de ruido. **Hay que decirlo: la muestra es 63 / 37, no 70 / 30.** Los 16 ejemplos excluidos eran todos "no ruido".
- Cada fila del consolidado lleva `estrato` y `peso_muestreo` (= población / muestra) para reponderar las métricas de ruido a la población. Las filas del estrato `no_ruido` pesan 1 (son todas); las del estrato `ruido`, 2.892.
- Los **dobles** (20) son 14 de no ruido y 6 de ruido, para que el acuerdo se mida sobre todo en titulares con tema (11 de los 14 son de alcance regional).

### n efectivo por métrica

El **n efectivo de Kish** de toda la muestra ponderada es (Σw)² / Σw² = **77.6** de 100. Por métrica:

| Métrica | Base | n |
|---|---|---|
| Clasificación por tema (macro-F1, F1 por tema) | Titulares que las personas consideran no ruido: los 63 del estrato `no_ruido` más los del estrato `ruido` que la persona no marque como ruido | ≥ 63, sin ponderar (es un censo del estrato) |
| Precisión del filtro de ruido | Marcados por el filtro = estrato `ruido` | 37, sin ponderar |
| Recall del filtro de ruido | Todo lo que la persona marque como ruido; los del estrato `ruido` se ponderan por 2.892 | depende de cuántos ruidos marque la persona en el estrato `no_ruido` (se reportan con n e IC; el IC debe usar el n efectivo, no 100) |
| Alcance regional (`eval.ruido`) | Subconjunto aparte, solo titulares sin ruido | ≤ 38 regionales según el filtro |
| Agrupación (precisión y recall de pares) | Pares dentro de la muestra de 100. La muestra no fue diseñada para encontrar eventos: pocos pares reales | **exploratoria** |
| Acuerdo entre etiquetadores | Los 20 dobles | 20 (kappa impreciso: indicativo) |

## Cómo etiqueta una persona

1. `poetry install` y, una vez, `poetry run python -m src.carga && poetry run python -m src.normalizacion && poetry run python -m src.limpieza` (crea `data/senales.duckdb`, con la marca de ruido que usa la muestra).
2. `poetry run streamlit run eval/etiquetar.py`
3. En la barra lateral: tu **nombre** (el de una persona; se rechazan nombres de herramientas o modelos), **tu parte** y **de cuántas personas** (con dos personas: una es 1 de 2 y la otra 2 de 2). Lee la guía que aparece abajo.
4. Para cada titular: marca si es ruido; si no lo es, elige tema principal, secundario (opcional), grupo y, si aplica, **alcance regional**; pulsa **Guardar y seguir**.
   - **Grupo:** titulares que cuentan el mismo hecho comparten grupo (nombre corto, ej. `sismo-chiriqui`). Un titular que no repite el hecho de otro va **suelto** ("ninguno").
   - **Alcance regional (D-84):** nota de la región o de un fenómeno regional que afecta a Panamá. **No es ruido**: elige `ninguno`, su tema y marca la casilla.
   - **`no_es_noticia`:** titular sin contenido (solo el nombre del medio, portada, promoción).
   - Un titular de ruido no lleva tema, grupo ni alcance regional.
5. Tu hoja queda en `eval/etiquetas/<tu_nombre>.csv`. Haz commit de ese archivo (cada persona tiene el suyo, no se pisan). Puedes volver a un titular y corregirlo: se reemplaza.

## Columnas

Hojas por persona: `id_noticia · titulo · tema_principal · tema_secundario · ruido · grupo · alcance_regional · nota · etiquetado_por · fecha_etiquetado`. `eval/etiquetas.csv` (consolidado) agrega `estrato · peso_muestreo · n_etiquetadores`.

## Después de etiquetar (en este orden)

```bash
poetry run python -m eval.etiquetar --validar      # formato de cada hoja
poetry run python -m eval.etiquetar --acuerdo      # kappa de Cohen sobre los 20 dobles
poetry run python -m eval.etiquetar --grupos       # nombres de grupo de todas las hojas, con sus titulares
poetry run python -m eval.etiquetar --desempate    # titulares en disputa (los etiqueta una tercera persona)
poetry run python -m eval.etiquetar --consolidar   # escribe eval/etiquetas.csv (una fila por titular)
poetry run python -m eval.ruido                    # precisión y recall del filtro; subconjunto regional aparte
```

- **Acuerdo (D-71):** 20 titulares etiquetados por **dos** personas por separado (spec E1-06 · D-71). Por cada par: kappa de la categoría (tema o motivo de ruido), kappa del ruido y kappa de los pares "mismo grupo / distinto grupo" (no se comparan los nombres de grupo, solo qué titulares juntó cada persona), con el acuerdo observado, su n e intervalo de Wilson al 95 %. Sin hojas, `--acuerdo` termina con código 2. **Acuerdo bajo** (kappa < 0.6): se revisa la guía antes de usar las etiquetas; `--consolidar` se niega a escribir (`--forzar` solo después de revisarla).
- **Conciliar grupos (`--grupos`):** antes de consolidar, el equipo revisa la lista. Si dos nombres cuentan el mismo hecho, la persona dueña de uno lo unifica: `poetry run python -m eval.etiquetar --renombrar VIEJO NUEVO --persona "Nombre"`. Un grupo de un solo titular se marca para decidir si va suelto. La interfaz no sugiere a una persona los grupos que otra usó en los titulares dobles, para no sesgar el acuerdo; la conciliación se hace después de medirlo.
- **Disputas y desempate:** si dos personas difieren en ruido o tema principal, el titular queda **fuera** del consolidado. `--consolidar` imprime cuántos excluyó y los lista (id, titular y quiénes lo etiquetaron); nunca los descarta en silencio. Una **tercera persona** abre la interfaz con la opción **Desempate**, que muestra solo esos titulares (sin las etiquetas de las otras dos), y vuelve a consolidar: gana la mayoría. El secundario, el grupo y el alcance regional del consolidado son los de la primera persona (orden alfabético); el secundario y el alcance regional solo se conservan si todas coinciden.
- Los titulares se muestran como texto plano: un titular es dato, nunca instrucción.

## Etiquetadores

| | |
|---|---|
| Método (D-85) | El asistente **propone** las 100 etiquetas, con una justificación por titular, y una persona **revisa y aprueba** cada una. No hubo doble etiquetado independiente. |
| Revisora | **Javier Acosta** (hoja `eval/etiquetas/javier_acosta.csv`, 100 titulares, fecha 2026-10-06) |
| Registro | La misma revisión se llevó a la base Notion "Etiquetas de clasificación (E1-06)" (campos `Aprobada`, `Etiquetado por`, `Cambios hechos`) |
| Decisiones de grupo | `el-nino-latam` (20 titulares): eventos_naturales + secundario economía (la guía incluye "sequía y El Niño"; regla de frontera 1, hecho central). `trump-ayuda-europa-latam` (13): economía, alcance regional. Ambas se aprobaron como se propusieron. |

Las etiquetas son de **una sola persona** sobre una propuesta del asistente: las métricas que dependen de ellas heredan ese límite (posible sesgo de anclaje hacia la propuesta).

## Acuerdo entre etiquetadores

**El kappa entre etiquetadores no se midió**: hay una sola hoja y `--acuerdo` termina con "SIN ACUERDO" (necesita dos personas). Por eso `--consolidar` se corrió con `--forzar`. Razón registrada: **D-85: etiquetado por propuesta del asistente y revisión de una persona; sin doble etiquetado**.

Lo que sí se mide es la **coincidencia entre la propuesta del asistente y la revisión humana**: **96 de 100 filas sin cambios = 96.0 % (IC de Wilson 95 %: 90.2 a 98.4 %, n = 100)**. No es un acuerdo entre personas independientes y no debe leerse como tal. Los 4 cambios de la revisora:

| Titular | Propuesta | Revisión |
|---|---|---|
| República Dominicana se encuentra entre los países con menor incidencia de dengue… | servicios_publicos, regional | `no_es_panama` (sin vínculo con Panamá) |
| Negocios de Gilinski y de Ecopetrol son claves para Colombia en América Latina | economía, regional | `no_es_panama` (sin vínculo con Panamá) |
| Árbol cae sobre dos vehículos en estacionamientos del hospital San Miguel Arcángel | eventos_naturales | `fuera_de_temas` (no se indica fenómeno natural) |
| Reformas electorales: Blandón defiende el 3%… | regulación | `fuera_de_temas` (postura política, no una norma aprobada; la guía excluye la política electoral sin norma) |

Los 4 titulares quedaron como ruido, sin tema, grupo ni alcance regional (esquema de la herramienta). Los 20 titulares "dobles" de la muestra quedaron con una sola etiqueta.

## Límites

- `fuera_de_ventana` no se etiqueta (es un hecho de fecha, no de contenido); `eval.ruido` compara los motivos que el filtro marca con los cuatro valores humanos.
- Una muestra de 100 titulares da intervalos amplios; toda proporción se reporta con n e IC (`docs/protocolo_evaluacion.md`), usando el n efectivo cuando se pondera.
