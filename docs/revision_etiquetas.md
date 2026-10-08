# Material para ampliar y revisar las etiquetas de tema (C-10b, T4)

Para el dueño: qué hay hoy, cómo revisar las 61 etiquetas provisionales, cómo sumar un segundo etiquetador y cuántos eventos
hacen falta para defender una comparación de modelos. **Solo cuentas: este documento no cita ningún titular y no etiqueta nada.**
Los comandos salen de `eval/etiquetar.py` y de `docs/etiquetado.md` y se revisaron contra el código; el recuento es de
`eval/etiquetas.csv` (columna `origen`) en la rama `c-10b-clasificacion-por-evento`.

## 1 · Qué hay hoy (conteos por tema)

El **evento** es la unidad que cuenta (`grupo` de la etiqueta, o la propia noticia si no tiene grupo): varias filas del mismo
hecho no son observaciones independientes (`docs/clasificacion.md`, «Diagnóstico de los errores de tema»).

| Tema (etiqueta) | `humano`: filas · eventos | `asistente_provisional`: filas · eventos |
|---|---|---|
| Economía | 26 · 11 | 7 · 3 |
| Servicios públicos | 9 · 9 | 7 · 7 |
| Eventos naturales | 20 · **1** (un solo evento) | 0 · 0 |
| Logística | 2 · 2 | 1 · 1 |
| Turismo | 1 · 1 | 0 · 0 |
| Regulación | 1 · 1 | 0 · 0 |
| `sin_tema` (ruido: `no_es_panama`, `fuera_de_temas`, `no_es_noticia`) | 41 · 41 | 46 · 45 |
| **Total** | **100 filas** | **61 filas** |

- De las 100 humanas, **64** pasan el filtro de ruido y llegan al clasificador (30 eventos): 59 con tema y 5 `sin_tema`
  (`outputs/clasificacion_por_evento.json`). Las otras 36 ya eran ruido para el filtro.
- De las 61 provisionales, **15** tienen tema y llegarían al clasificador; las otras 46 son ruido y no entran en la
  medición de temas. Las 61 son del asistente (D-101): **no entrenan ni evalúan**; solo una persona las convierte en humanas.
- Hoy solo Economía (11 eventos) y Servicios públicos (9) tienen 9 o más eventos humanos entre los que llegan al
  clasificador; Eventos naturales, Turismo y Regulación tienen **un** evento cada uno: con un solo evento no queda ninguno para
  entrenar mientras se prueba otro.

## 2 · Cómo revisa una persona las 61 provisionales (C-09)

**Lo que hace el código hoy** (verificado en `eval/etiquetar.py`):

1. Las filas provisionales **no están en ninguna hoja de persona**: viven solo en `eval/etiquetas.csv` con
   `origen = asistente_provisional` y `etiquetado_por = Asistente provisional`. `--validar` las ignora (solo valida las humanas).
2. La interfaz (`poetry run streamlit run eval/etiquetar.py`) muestra la **muestra de 100** que se calcula desde
   `data/senales.duckdb` con la semilla de `config/etiquetado.yaml`; `poetry run python -m eval.etiquetar --muestra` la imprime
   (orden, doble, estrato, peso, `id_noticia`, medio). **No existe un modo que cargue las 61**.
3. `poetry run python -m eval.etiquetar --consolidar` escribe `eval/etiquetas.csv` con las filas de las hojas y **conserva** una
   fila provisional solo si su `id_noticia` **no** está ya en las hojas. Es decir, si una persona etiqueta ese mismo titular en
   su hoja, su etiqueta **reemplaza** a la provisional; si no, la provisional se queda y el comando lo avisa.

**Procedimiento posible con lo que existe** (`docs/etiquetado.md`, «Cómo etiqueta una persona» y «Después de etiquetar»):

```bash
poetry run python -m eval.etiquetar --muestra            # ¿cuáles de las 61 caen en la muestra actual? (comparar id_noticia con el CSV)
poetry run streamlit run eval/etiquetar.py                # la persona etiqueta con su nombre; su hoja: eval/etiquetas/<nombre>.csv
poetry run python -m eval.etiquetar --validar            # formato de cada hoja y que cada id esté en la muestra
poetry run python -m eval.etiquetar --grupos             # unificar nombres de grupo (mismo hecho = mismo grupo) antes de consolidar
poetry run python -m eval.etiquetar --consolidar --forzar  # --forzar solo si no hay segunda persona (D-85); si no, se niega por falta de acuerdo
```

**Hueco a decidir (no es parte de C-10b):** con la base de este checkout (205 titulares elegibles, no los 170 de cuando se
etiquetó), `--muestra` incluye **23 de las 61** provisionales; las otras **38** no están en la muestra y `--validar` rechaza en
una hoja un id que no esté en la muestra. Además la muestra recalculada coincide solo en **68 de los 100** ids que ya etiquetó
la revisora actual. Para confirmar las 61 hace falta una de dos cosas, y es decisión del dueño: (a) un modo nuevo de
`eval/etiquetar.py` que presente exactamente esas 61 (una tarea de código con su test), o (b) fijar la muestra (congelar la lista
de ids) para que no cambie al cambiar el snapshot. Hasta entonces, confirmar las 23 que sí caen en la muestra es lo único que
el código permite sin tocarlo.

Reglas para quien revise: aplicar `docs/guia_temas.md` (incluida la regla D-84 de alcance regional), no mirar la etiqueta
provisional antes de decidir (la interfaz tampoco la muestra) y anotar en `nota` solo dudas de criterio, sin datos personales.
Tras consolidar, correr `HF_HUB_OFFLINE=1 poetry run python -m eval.clasificacion_por_evento` para ver cómo cambian los conteos.

## 3 · Cómo agregar un segundo etiquetador (D-71, acuerdo y kappa)

1. La segunda persona abre la misma interfaz con **su** nombre (la herramienta rechaza nombres de herramientas o modelos). Con
   dos personas: la primera es «1 de 2» y la segunda «2 de 2»; los titulares **dobles** (20 en la configuración,
   `muestra.tamano_acuerdo`) los etiquetan las dos por separado, sin ver las etiquetas de la otra.
2. `poetry run python -m eval.etiquetar --acuerdo` calcula el **kappa de Cohen** sobre los dobles (kappa de la categoría, del
   ruido y de los pares «mismo grupo»), con acuerdo observado, n e IC de Wilson. Por debajo de **0.6**
   (`acuerdo.kappa_minimo`) se revisa `docs/guia_temas.md` antes de usar las etiquetas, y `--consolidar` se niega a escribir.
3. `poetry run python -m eval.etiquetar --desempate` lista los titulares en disputa (difieren en ruido o tema principal): una
   **tercera** persona los etiqueta en la interfaz (casilla «Desempate») y gana la mayoría.
4. `poetry run python -m eval.etiquetar --consolidar` (sin `--forzar` cuando ya hay dos personas) escribe `eval/etiquetas.csv` con
   `n_etiquetadores`.

**Advertencia con la base actual:** de los 20 dobles de la muestra recalculada, la revisora actual etiquetó **12**; el kappa solo
se calcula sobre los dobles que ambas personas etiqueten (`--acuerdo` avisa «INCOMPLETO: faltan N»). Con n ≈ 12–20 el kappa es
solo indicativo; para un kappa útil conviene que la segunda persona etiquete **todos los titulares con tema** que ya etiquetó la
primera, no solo los dobles (si no, el acuerdo sale sobre muy pocos eventos).

## 4 · Cuántos eventos hacen falta para defender una comparación de modelos

**Razonamiento** (todo es aritmética sobre eventos, no sobre filas):

- **IC de un recall por tema.** Con k eventos y recall 50 %, la mitad del ancho del IC de Wilson al 95 % es ±0.33 con 5 eventos,
  ±0.26 con 10, ±0.20 con 20 y ±0.17 con 30. Con 10 eventos un tema apenas se puede entrenar y probar (validación cruzada de 5
  pliegues: 2 eventos de prueba y 8 de entrenamiento por pliegue); **20 por tema** es una meta razonable (±0.20).
- **Diferencia entre dos modelos, pareada por evento.** En la comparación exploratoria de C-10b la desviación de la diferencia por
  evento fue ≈ 0.45. Para que el IC 95 % de una mejora real de `d` excluya el cero (potencia ≈ 50 %) hacen falta
  n ≈ (1.96 · 0.45 / d)² eventos: **19** para `d = 0.20`, **35** para `d = 0.15` y **78** para `d = 0.10`; con potencia 80 %, **40,
  71 y 159**. Con ~30 eventos solo se ve una mejora grande (≥ 0.17), que es lo que hoy no se detecta.
- **Umbral de `sin_tema`:** la regla vigente es **≥ 30 positivos** (`docs/parametros.md`); hoy hay 5 que llegan al clasificador.
- **Conjunto de prueba aparte:** para no sobreestimar, además de los eventos de desarrollo conviene un conjunto **reservado** de ≥ 10
  eventos por tema que nadie mire hasta la comparación final (60 eventos para 6 temas); quien tuneó con unas etiquetas no puede
  usarlas para decir que mejoró (la misma lección de C-10 con Economía regional).

| Tema | Eventos humanos hoy | Con las provisionales confirmadas (techo) | Faltan para 10 | Faltan para 20 |
|---|---|---|---|---|
| Economía | 11 | 14 | 0 | 9 |
| Servicios públicos | 9 | 16 | 1 | 11 |
| Eventos naturales | 1 | 1 | 9 | 19 |
| Logística | 2 | 3 | 8 | 18 |
| Turismo | 1 | 1 | 9 | 19 |
| Regulación | 1 | 1 | 9 | 19 |
| `sin_tema` que llega al clasificador | 5 | 5 | 5 | 15 (y 25 para llegar a 30 y calibrar el umbral) |

(«Con las provisionales confirmadas» es un techo: solo suma si la persona **coincide** con la propuesta del asistente.) Para 20
eventos por tema faltan unos **95 eventos de tema** más 15–25 de `sin_tema`, y otros ~60 si se quiere el conjunto reservado.

**Por qué no basta con etiquetar más del mismo muestreo.** En la muestra aleatoria de 100 titulares salió **1 evento** de Turismo,
1 de Regulación, 1 de Eventos naturales y 2 de Logística: ~1–2 por cada 100 titulares. A ese ritmo, 20 eventos de un tema raro
piden cientos o miles de titulares al azar, y el snapshot actual tiene solo 205 elegibles. Hay dos caminos (no excluyentes):
(1) **más días de extracción** (`poetry run python -m scripts.extraer --rss`) para tener población, y (2) **buscar candidatos por
tema** (por palabras de la guía) y etiquetarlos; esto sirve para medir **recall** por tema, pero **no** para precisión ni
exactitud global (sesgo de selección), y debe decirse así en cada informe. Otra regla útil: limitar cuántos titulares de un mismo
evento se etiquetan (un evento de 20 filas, como El Niño, pesa en la exactitud por fila pero cuenta una sola vez por evento).
