# Hoja de preetiquetado (C-11)

Hoja para que **una persona** confirme o corrija las propuestas del asistente y así ampliar las etiquetas humanas, que es lo único que
mueve el límite de la clasificación (`docs/revision_etiquetas.md`, sección 4). Archivo: `eval/preetiquetado/hoja_preetiquetado.csv`.
**Es una propuesta, no una etiqueta.** Este documento no reproduce titulares y no etiqueta nada.

## Regla que no se rompe

Nada de esta hoja cuenta como etiqueta humana hasta que una persona lo confirma (D-85, D-101):

- Las propuestas viven en columnas `propuesta_*`; las columnas de decisión (`tema_humano`, `ruido_humano`, `tema_secundario`, `grupo`,
  `alcance_regional`, `nota`, `etiquetado_por`, `fecha_etiquetado`) salen **vacías**.
- Ningún lector de `src/`, `eval/` ni `scripts/` nombra la hoja, y un test lo vigila (`tests/test_c11_preetiquetado.py`). Ninguna métrica la lee.
- La hoja no modifica `eval/etiquetas.csv`, `eval/etiquetas/`, `config/` ni `src/`; el test comprueba el hash y `git diff`.
- Las 61 filas del bloque A ya figuran en `eval/etiquetas.csv` como `asistente_provisional`; eso no cambia.

## Qué contiene (conteos de esta rama, snapshot de 221 noticias)

| Bloque | Filas | Origen | Qué es |
|---|---|---|---|
| `A_provisionales` | **61** | `asistente_provisional` | Las filas provisionales de `eval/etiquetas.csv`, con su propuesta vigente más una revisión nueva contra `docs/guia_temas.md` |
| `B_sin_etiquetar` | **0** | `asistente_propuesta` | Titulares útiles (no ruido para el filtro del pipeline), sin etiqueta de ningún origen y fuera de `config/ejemplos_excluidos.txt` |

**El bloque B salió vacío, no por omisión.** En `data/senales.duckdb` hay 96 titulares que el filtro no marca como ruido y los 96 ya están
en `eval/etiquetas.csv` (humanos o provisionales). Los 44 titulares sin etiqueta y no excluidos que quedan en la base son todos ruido según
el filtro del pipeline (33 `no_es_panama`, 7 `fuera_de_temas`, 4 `no_es_noticia`); no se incluyeron porque la tarea pide titulares útiles
y porque confirmar ruido no suma eventos de tema. La cifra esperada (≈ 15) no se reproduce con esta base. Si el dueño quiere esos 44 como
bloque B, es una decisión suya (cambia la definición de «útil»); con más días de extracción (`scripts.extraer --rss`) el bloque B crecería solo.

### Dudosos y confianza (bloque A)

- **19 de 61** filas llevan `dudoso = si` (42 `no`): 10 propuestas sin tema (ruido), 5 de Economía, 3 de Servicios públicos y 1 de Logística.
- Confianza: 23 `alta`, 20 `media`, 18 `baja`.
- Los dudosos son los casos donde discrepo de la propuesta vigente o la guía es ambigua: procesos judiciales (la guía los saca de los
  temas salvo que el hecho central toque uno), beneficios educativos que también son transferencias, mercados globales con vínculo
  indirecto con Panamá, y tres titulares en ruso, coreano y portugués que leí con menos seguridad.
- Una propuesta vigente (audiencia contra dirigentes sindicales) la pasó el asistente de ruido a Servicios públicos sin revisión humana
  (lo dice su nota en `eval/etiquetas.csv`); está marcada dudosa y `motivo_corto` dice que discrepo. Se conserva la propuesta vigente
  en `propuesta_tema`: la corrección la decide la persona.

### Eventos distintos (solo conteos)

`evento` es la unidad del proyecto: el `grupo` de la etiqueta existente, o el `GRP-` del pipeline si no hay grupo, o la propia noticia.
`id_grupo` guarda el `GRP-` cuando existe. Hay **55 eventos distintos** en el bloque A, **54 nuevos** (solo `trump-ayuda-europa-latam`
ya tiene filas humanas).

| Tema propuesto | Filas | Eventos distintos | De ellos, nuevos frente a las etiquetas humanas |
|---|---|---|---|
| Economía | 7 | 3 | 2 |
| Servicios públicos | 7 | 7 | 7 |
| Logística/Canal | 1 | 1 | 1 |
| Turismo, Eventos naturales, Regulación | 0 | 0 | 0 |
| `sin_tema` (ruido) | 46 | 45 | 45 |

Un evento aparece en dos filas de temas distintos (`peste-neumonica`: una nota sin tema y otra de Servicios públicos), por eso las
filas por evento suman 56 y no 55. **Solo 11 eventos del bloque A llevan tema**, y ninguno es de Turismo, Eventos naturales ni Regulación,
los temas con un solo evento humano: confirmar las 61 no resuelve esa escasez (`docs/revision_etiquetas.md`, sección 4).

## Cómo la usa una persona

1. Abre la hoja en una hoja de cálculo o editor de CSV (UTF-8). Está ordenada por bloque y por `evento`: trabaja **un evento a la vez**
   y confirma sus filas juntas.
2. Aplica `docs/guia_temas.md` (reglas de frontera y alcance regional D-84). Conviene decidir **antes** de leer `propuesta_*` para no
   anclarse en la propuesta (`docs/etiquetado.md`, «Etiquetadores»); `motivo_corto` es el porqué del asistente, no una instrucción.
3. Rellena, por fila:
   - `ruido_humano`: `ninguno`, `no_es_panama`, `fuera_de_temas` o `no_es_noticia`.
   - `tema_humano`: uno de `economia`, `logistica`, `turismo`, `servicios_publicos`, `eventos_naturales`, `regulacion`; **vacío si hay ruido**.
   - Opcionales: `tema_secundario`, `grupo` (titulares del mismo hecho comparten nombre; minúsculas, dígitos y guiones), `alcance_regional`
     (`si` o vacío; solo sin ruido), `nota` (solo dudas de criterio, sin datos personales).
   - `etiquetado_por` (nombre de una persona; la herramienta rechaza nombres de herramientas o modelos) y `fecha_etiquetado`
     (ISO 8601 UTC con `Z`, p. ej. `2026-10-07T15:00:00Z`).
4. Una fila sin esas columnas rellenas sigue siendo propuesta. Marcar `dudoso = no` o aceptar una propuesta sin rellenar no la convierte
   en etiqueta.

### Pasar las filas confirmadas al formato de la hoja por persona

El formato que lee `eval/etiquetar.py` es el de `docs/etiquetado.md` («Columnas»): `id_noticia · titulo · tema_principal · tema_secundario ·
ruido · grupo · alcance_regional · nota · etiquetado_por · fecha_etiquetado`, en `eval/etiquetas/<nombre>.csv` (una hoja por persona,
nombrada como ella). La correspondencia desde esta hoja es: `tema_humano` → `tema_principal`, `ruido_humano` → `ruido`; las demás
columnas de decisión conservan su nombre. Un titular con ruido no lleva tema, grupo ni alcance regional (`validar_fila`).

Los comandos reales del flujo (de `docs/etiquetado.md` y `eval/etiquetar.py`, sin añadir ninguno):

```bash
poetry run python -m eval.etiquetar --validar      # formato de cada hoja
poetry run python -m eval.etiquetar --grupos       # unificar nombres de grupo antes de consolidar
poetry run python -m eval.etiquetar --consolidar   # escribe eval/etiquetas.csv (con --forzar si hay una sola persona, D-85)
```

Al consolidar, la fila humana de un `id_noticia` **reemplaza** a la provisional del mismo id y las provisionales sin hoja se conservan
(`eval/etiquetar.py`, líneas 659-665). Después, `HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion_por_evento` muestra cómo cambian
los conteos por evento.

## Limitación conocida: `--validar` rechaza ids fuera de su muestra

Lo que **verifiqué leyendo el código** (`eval/etiquetar.py`) y ejecutando solo lecturas:

- `validar_hoja` (líneas 318-338) agrega el problema «no está en la muestra» a toda fila de la hoja cuyo `id_noticia` no pertenezca a
  `ids_muestra`, que `main` calcula con `muestra_desde_base` (líneas 606-612) **si `data/senales.duckdb` existe**. Sin la base, solo avisa y no comprueba.
- Con problemas, `--consolidar` se detiene antes de escribir (líneas 629-632). `--forzar` omite el chequeo de acuerdo, **no** este.
- La muestra se recalcula desde el snapshot actual (semilla fija, pero la población cambió): en esta rama la muestra tiene 100 titulares y
  **solo 23 de las 61 filas del bloque A caen en ella**; las otras 38 serían rechazadas.
- Estado actual sin tocar nada: `poetry run python -m eval.etiquetar --validar` ya termina con `ERROR: 1 hojas, 64 problemas`, todos de este tipo
  (32 de las 100 filas humanas de `eval/etiquetas/` y las mismas 32 en `eval/etiquetas.csv`; solo 68 de las 100 ids humanas están en la muestra recalculada).
  No lo causa esta hoja.
- La interfaz (`streamlit run eval/etiquetar.py`) solo presenta titulares de esa muestra: no carga esta hoja.

Por tanto, **con el código actual solo se pueden consolidar sin error las filas del bloque A que están en la muestra (23)**. Para las otras
38 hace falta una decisión del dueño, que no tomé: un modo nuevo de `eval/etiquetar.py` que acepte esta hoja, o congelar la lista de ids de la
muestra (las mismas dos opciones de `docs/revision_etiquetas.md`, sección 2). No modifiqué `eval/etiquetar.py`.

## Lo que no verifiqué

- No ejecuté `--consolidar` ni escribí ninguna hoja por persona (sería escribir etiquetas humanas que nadie ha confirmado).
- No comprobé que las propuestas sean correctas: son lectura mía de los titulares contra la guía, sin leer artículos ni descripciones
  del RSS. Los idiomas ruso, coreano y portugués los leí con límites.
- No re-ejecuté `src.limpieza`: el bloque B depende de la marca de ruido ya guardada en la base; si el filtro cambia, hay que recalcularlo.
- No medí cuántos eventos de tema nuevos darían las 23 filas confirmables hoy, ni el efecto sobre ninguna métrica.
- No hubo llamadas de red ni al LLM de pago; costo cero.
