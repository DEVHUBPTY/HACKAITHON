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

Hojas por persona: `id_noticia · titulo · tema_principal · tema_secundario · ruido · grupo · alcance_regional · nota · etiquetado_por · fecha_etiquetado`. `eval/etiquetas.csv` (consolidado) agrega `estrato · peso_muestreo · n_etiquetadores`. Desde E1-07b agrega también `origen` (`humano` | `asistente_provisional`): las 61 filas `asistente_provisional` (D-101) las propuso un agente y las aprobó provisionalmente el asistente, pendientes de la revisión humana C-09; los lectores de `eval/` usan solo las `humano` por defecto, `--validar` solo valida las humanas, y `--consolidar` **conserva** las filas provisionales del consolidado existente (no salen de las hojas) y lo avisa.

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

## Muestra congelada

Las 100 etiquetas de D-85 se hicieron sobre una población de 170 titulares elegibles. Desde entonces la base creció (capturas del 2026-10-07 y del 2026-10-08) y el filtro de ruido se recalculó: volver a sortear con la misma semilla daría **otra** muestra (5 titulares distintos incluso sobre la población original). Por eso la muestra original está **fijada** en `eval/muestra_original.csv` (`muestra.congelada` en `config/etiquetado.yaml`): orden, estrato, población, peso y marca de doble de cada uno de los 100 titulares. Se generó reproduciendo la semilla sobre la población y los estratos de entonces (los estratos salen de `eval/etiquetas.csv`) y coincide con las 100 etiquetas de `eval/etiquetas/javier_acosta.csv`. Sin `congelada` la herramienta sortea como antes (las pruebas sintéticas lo usan).

## Ampliación 2026-10-08

| | |
|---|---|
| Qué es | Los **47 titulares nuevos** de la captura del RSS de TVN del 2026-10-08. Se agregan **después** de los 100 (órdenes 101 a 147); la muestra original no cambia (mismos IDs, orden, estratos, pesos y dobles) |
| Dónde se declara | `muestra.ampliaciones` en `config/etiquetado.yaml` (nombre, archivo del que salen los IDs, estrato y peso), validado por `src/configuracion.py` (sin claves desconocidas) |
| Estrato y peso | Estrato propio `ampliacion_tvn_20261008`, **censo** de esa captura: población 47, muestra 47, peso **1.0**, ningún doble. No representa a las capturas anteriores: el n efectivo de Kish de toda la muestra es 112.3 de 147 y cualquier métrica que mezcle estratos lo declara |
| Método | **Propuesto por un LLM y revisado por una persona**, el mismo método de las 100 originales (D-85, que las propuso el asistente). La propuesta (`eval/propuestas/llm_20261008.csv`, columna `propuesto_por`, aquí `llm:deepseek:deepseek-flash`) solo **rellena el formulario**, con el rótulo «Propuesta de LLM (deepseek) — revísala: confirma o corrige» y el texto de `duda` si lo hay |
| Qué cuenta como etiqueta | Solo lo que una persona guarda con **«Guardar y seguir»**, una por titular, en su hoja `eval/etiquetas/<nombre>.csv` (`etiquetado_por` = la persona, `origen` = `humano`; `nota` es de la persona y nunca se rellena). **Una propuesta sin revisar nunca es una etiqueta ni cuenta como humana** (D-85, D-101): ningún lector de `eval/` abre `eval/propuestas/` |
| Cómo revisarlos | `poetry run streamlit run eval/etiquetar.py` y, en la barra lateral, tu nombre y **«Qué titulares ver» → `tvn_20261008`** (muestra los 47 completos, sin repartir por «parte»). Después, los comandos de «Después de etiquetar» |

`--validar` y `--consolidar` aceptan estas filas (con su `estrato` y `peso_muestreo` 1 en el consolidado); las 61 filas `asistente_provisional` se siguen conservando. Los lectores de `eval/` usan `peso_muestreo` como un número por fila (`eval/metricas.py`), así que el estrato nuevo no los rompe: es un censo, peso 1.

## Aprendizaje activo (D-123)

El etiquetado también alimenta al clasificador, con una persona decidiendo siempre. El ciclo es **etiquetar → reentrenar → medir**:

1. **Etiquetar.** En `streamlit run eval/etiquetar.py`, la ampliación (`tvn_20261008`) se muestra ordenada por incertidumbre (`ordenar_por_incertidumbre` en `config/etiquetado.yaml`): primero los titulares donde el clasificador logístico tiene la menor probabilidad máxima, luego el menor margen entre la 1.ª y la 2.ª y, al final, el `id_noticia`. Junto a cada titular se ve esa probabilidad como indicador; **no es una etiqueta** y no se guarda nada sin «Guardar y seguir». Si el modelo local no está disponible, la herramienta avisa y usa el orden normal.
2. **Consolidar** (`--consolidar`, ver arriba). La cola y el entrenamiento leen `eval/etiquetas.csv`.
3. **Reentrenar y medir:** `poetry run python -m eval.clasificacion`. El método `logistica` se entrena con los textos de referencia de `temas.yaml` **más** el *pool*: las etiquetas de origen `humano`, firmadas por una persona, con tema y sin ruido, de titulares que **no** están en la muestra original. El informe imprime la huella sha256 del pool (sobre `id` y tema ordenados), el n por clase del pool, de las referencias y el total, y el bootstrap pareado contra el método A. Una corrida con el mismo pool da la misma huella y las mismas métricas.

**Por qué la evaluación queda congelada.** Se mide siempre sobre los 100 IDs de `eval/muestra_original.csv`. Si los titulares etiquetados después entraran a la evaluación y al entrenamiento a la vez, la métrica premiaría memorizar y dejaría de decir cuánto generaliza el clasificador; además, la cola por incertidumbre elige justo los casos difíciles, y medir sobre ellos movería el n y los pesos del muestreo. Por eso `eval/aprendizaje_activo.py` excluye esos IDs del pool y `ErrorDeSeparacion` salta si alguno se cuela (hay un test). Nunca entran al pool las filas `asistente_provisional` (D-101) ni las propuestas de un LLM.

**Límites.** C, el umbral y el margen siguen siendo los calibrados con las referencias; no se recalibran con el pool. La revisión editorial (E1-16) no permite cambiar el tema de un grupo, así que hoy no hay correcciones de tema por esa vía que sumar al pool (hueco declarado). Con C-12 el pool tiene las filas con tema del conjunto ampliado (ver más abajo); las 47 de la ampliación `tvn_20261008` siguen esperando a una persona. `metodo_activo` sigue en `A` hasta que el IC 95 % de la diferencia pareada quede sobre cero.

## Conjunto ampliado: las 61 filas que confirmó una persona (C-12)

`eval/etiquetas_ampliadas.csv` = las 100 etiquetas humanas de `eval/etiquetas.csv` + 61 filas que **David** decidió el 2026-10-07 sobre la hoja `eval/preetiquetado/hoja_preetiquetado.csv` (`docs/preetiquetado.md`). Se genera con `poetry run python -m eval.etiquetar --incorporar-hoja --hoja eval/preetiquetado/hoja_preetiquetado.csv` (todo o nada, determinista, no escribe sobre sus entradas). `eval/etiquetas.csv` **no cambia**: esas 61 siguen ahí como `asistente_provisional`.

- **Son humanas (D-85).** Una persona las firmó (`etiquetado_por` = David, `fecha_etiquetado` = 2026-10-07) y conservan esos campos y su `origen = humano`. Lo que sigue siendo provisional (D-101) es la copia de `eval/etiquetas.csv`.
- **Confirmación más débil en 42 de las 61.** 19 se revisaron una a una (las marcadas `dudoso = si` en la hoja) y **42 se aprobaron en bloque** (nota «Aprobado en bloque por la persona»). Es una confirmación humana, pero no una revisión fila por fila; cualquier cifra que se apoye en ellas debe decirlo. 3 de las 61 cambiaron de etiqueta respecto de la propuesta provisional.
- **Solo entrenan, nunca evalúan.** El *pool* de D-123 sale de este archivo (`logistica.aprendizaje_activo.etiquetas_pool` en `config/clasificacion.yaml`); la evaluación sigue siendo `eval/muestra_original.csv`, y `construir_pool` excluye esos 100 IDs (hay un test que lo comprueba contra los archivos reales). Una fila de ruido no entra al pool: la abstención sale del umbral, no se aprende.
- **Sin peso de muestreo.** No vienen de la muestra estratificada de E1-06 (`estrato = preetiquetado_c11`, `peso_muestreo` vacío): no se mezclan en estimaciones ponderadas. Un titular de ruido con `grupo` en la hoja lo pierde y se avisa.

## Límites

- `fuera_de_ventana` no se etiqueta (es un hecho de fecha, no de contenido); `eval.ruido` compara los motivos que el filtro marca con los cuatro valores humanos.
- Una muestra de 100 titulares da intervalos amplios; toda proporción se reporta con n e IC (`docs/protocolo_evaluacion.md`), usando el n efectivo cuando se pondera.
