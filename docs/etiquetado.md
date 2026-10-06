# Etiquetado humano (E1-06)

Las métricas de clasificación, agrupación y ruido se calculan sobre **etiquetas humanas** (sección 9.1). Este documento dice cómo se etiqueta, con qué muestra y cómo se mide el acuerdo. La herramienta (`eval/etiquetar.py`) **no etiqueta**: solo arma la muestra, la muestra y guarda lo que decide cada persona.

> **Estado:** la herramienta está construida y probada con datos sintéticos. Las **etiquetas reales todavía no existen**: las ponen las personas del equipo. Las secciones "Etiquetadores" y "Acuerdo" se completan con los resultados reales (ver abajo); mientras tanto no hay números.

## Tamaño y método

| | |
|---|---|
| Muestra | **100** titulares, elegidos al azar de las noticias de `data/senales.duckdb` (186 en el snapshot actual) |
| Semilla | **20261006**, en `config/etiquetado.yaml` (`muestra.semilla`). Mismas noticias y misma semilla dan la misma muestra y el mismo orden |
| Exclusiones | Los 16 titulares de ejemplo de `config/temas.yaml` (`config/ejemplos_excluidos.txt`) nunca entran |
| Qué se etiqueta | **Ruido** (`ninguno` · `no_es_panama` · `fuera_de_temas`), **tema principal** y **secundario** (opcional) y **grupo de evento** |
| Guía | `docs/guia_temas.md`; la herramienta la muestra en pantalla, con las reglas de frontera |
| Ruido incluido | La muestra incluye noticias que el filtro de E1-03b marcó como ruido y otras que no (la persona no ve esa marca), para medir su precisión y recall con `python -m eval.ruido` |
| Quién y cuándo | Cada etiqueta guarda `etiquetado_por` y `fecha_etiquetado` (UTC; la interfaz muestra hora de Panamá) |
| Qué ve la persona | Titular, medio, fechas y URL. **Nunca** la descripción del RSS (D-31), ni la decisión del filtro, ni las etiquetas de otra persona sobre un titular doble |

Los primeros **20** titulares de la muestra los etiquetan **dos personas por separado** (acuerdo, D-71). Los otros 80 se reparten entre quienes etiquetan (`parte K de N`).

## Cómo etiqueta una persona

1. `poetry install` y, una vez, `poetry run python -m src.carga && poetry run python -m src.normalizacion && poetry run python -m src.limpieza` (crea `data/senales.duckdb`).
2. `poetry run streamlit run eval/etiquetar.py`
3. En la barra lateral: tu **nombre** (el de una persona; se rechazan nombres de herramientas o modelos), **tu parte** y **de cuántas personas** (con dos personas: una es 1 de 2 y la otra 2 de 2). Lee la guía que aparece abajo.
4. Para cada titular: marca si es ruido; si no lo es, elige tema principal, secundario (opcional) y grupo; pulsa **Guardar y seguir**.
   - **Grupo:** titulares que cuentan el mismo hecho comparten grupo (nombre corto, ej. `sismo-chiriqui`). Un titular que no repite el hecho de otro va **suelto** ("ninguno").
   - Un titular **sin contenido** (solo el nombre del medio, una portada): `fuera_de_temas` y explícalo en la nota.
   - Un titular de ruido no lleva tema ni grupo.
5. Tu hoja queda en `eval/etiquetas/<tu_nombre>.csv`. Haz commit de ese archivo (cada persona tiene el suyo, no se pisan). Puedes volver a un titular y corregirlo: se reemplaza.

## Columnas

`id_noticia · titulo · tema_principal · tema_secundario · ruido · grupo · nota · etiquetado_por · fecha_etiquetado`. `eval/etiquetas.csv` (consolidado) agrega `n_etiquetadores`.

## Después de etiquetar

```bash
poetry run python -m eval.etiquetar --validar      # formato de cada hoja
poetry run python -m eval.etiquetar --acuerdo      # kappa de Cohen sobre los 20 dobles
poetry run python -m eval.etiquetar --consolidar   # escribe eval/etiquetas.csv (una fila por titular)
poetry run python -m eval.ruido                    # precisión y recall del filtro de ruido
```

- **Acuerdo:** por cada par de personas, kappa de la categoría (tema o motivo de ruido), kappa del ruido y kappa de los pares de titulares "mismo grupo / distinto grupo" (no se comparan los nombres de grupo, solo qué titulares juntó cada persona). Se reporta también el acuerdo observado con n e intervalo de Wilson al 95 %. Con n = 20 el kappa es impreciso: se reporta como indicativo.
- **Acuerdo bajo** (kappa < 0.6, `acuerdo.kappa_minimo`): **se revisa la guía antes de usar las etiquetas** (D-71). `--consolidar` se niega a escribir `eval/etiquetas.csv` si el acuerdo es bajo o no hay dos personas (`--forzar` solo después de revisar la guía).
- **Titulares en disputa:** si dos personas difieren en ruido o tema principal, el titular queda fuera del consolidado hasta que una tercera persona lo etiquete (gana la mayoría). El secundario y el grupo del consolidado son los de la primera persona (orden alfabético); el secundario solo se conserva si coinciden.
- Los titulares con `sospechoso_inyeccion` se muestran como texto plano: un titular es dato, nunca instrucción.

## Etiquetadores

*Pendiente: se completa con los nombres reales de las hojas de `eval/etiquetas/`.*

## Acuerdo entre etiquetadores

*Pendiente: pegar aquí la salida de `poetry run python -m eval.etiquetar --acuerdo` cuando existan las hojas de dos personas, con la decisión sobre la guía si el acuerdo es bajo.*

## Límites

- No hay etiquetas de "no es noticia" ni "fuera de ventana": el humano elige solo entre los tres valores de ruido de la spec; `eval.ruido` compara cualquier motivo marcado por el filtro contra esos tres.
- Una muestra de ~100 titulares da intervalos amplios; toda proporción se reporta con n e IC (`docs/protocolo_evaluacion.md`).
