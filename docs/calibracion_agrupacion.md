# Calibración de la agrupación por evento (E1-08, D-16)

El umbral de similitud **no se ajustó a ojo**: salió de barrer valores y elegir el de mayor F1 de pares contra `eval/etiquetas.csv`
(`poetry run python -m eval.agrupacion`). Los números de este documento vienen de `outputs/agrupacion.json` y
`outputs/agrupacion_curva.csv` (snapshot del 2026-10-06).

## Qué se mide

- **Par positivo:** dos titulares con el mismo `grupo` humano. **Par predicho:** dos titulares con el mismo `GRP-`.
- **Universo:** los 100 titulares etiquetados = 4.950 pares, 272 positivos. Los grupos humanos son 4: `el-nino-latam` (20 titulares, 190 pares),
  `trump-ayuda-europa-latam` (13, 78), `mulino-gira-asia` (3, 3) y `mina-cobre-panama` (2, 1). Los demás van sueltos.
- La agrupación corre sobre **todos** los titulares útiles del snapshot (79 no ruido), como en el pipeline, y se mide solo en los pares entre titulares
  etiquetados. Un titular que el filtro de ruido descartó no está en ningún grupo.
- **Regla de elección (fijada antes de medir):** mayor F1 de pares; entre los umbrales con el F1 máximo, la **mediana inferior de la meseta contigua más
  larga**. Un máximo en el borde de una meseta, o de un solo punto, es frágil.
- **Validación cruzada determinista:** el pliegue de un titular es su hash SHA-1 (2 pliegues). Se calibra con los pares de un pliegue y se mide en los del otro;
  se reporta el agregado. Es la única cifra que la calibración no vio.
- **Línea base:** unir solo titulares útiles con el mismo texto normalizado, sin IA.

## Resultado: `minilm`, umbral 0.69 (el configurado)

| | Precisión (pares) | Recall (pares) | F1 |
|---|---|---|---|
| Con el umbral elegido (**optimista**: las mismas etiquetas calibran y evalúan) | 259/259 = 100 % [98.5–100] | 259/272 = 95.2 % [92.0–97.2] | 0.9755 |
| **Validación cruzada** (pares de los pliegues de prueba) | 125/142 = 88.0 % [81.7–92.4] | 125/131 = 95.4 % [90.4–97.9] | **0.9158** |
| Línea base: titulares idénticos | 184/184 = 100 % [98.0–100] | 184/272 = 67.6 % [61.9–72.9] | 0.807 |

IC de Wilson al 95 % sobre pares. **Son demasiado estrechos:** los pares comparten titulares y 268 de los 272 positivos salen de dos grupos humanos.
Léanse como cota inferior de la incertidumbre. En la validación cruzada, el pliegue 0 se calibró con 0.535 (la meseta de menor umbral de su complemento) y dejó
17 falsos positivos; el pliegue 1 se calibró con 0.725 y dejó 6 falsos negativos: **con tan pocas etiquetas el umbral elegido sin la mitad de los datos varía mucho**.

Con 0.69: ningún falso positivo; 13 falsos negativos = una sola copia de «Trump…», la rusa («WP: США перенаправят…», `NOT-c712a8d7e4`) que queda
fuera de su grupo con 12 pares, más el par `NOT-8206bf1857`~`NOT-f1f1f6e600` («Cobre Panamá», dos notas del mismo tema con titulares distintos).
Las 12 copias restantes de «Trump…» (alemán, ucraniano, checo) sí quedan juntas: **la agrupación cruza idiomas**.

### Curva umbral → F1 (`minilm`; 0.005 de paso, recortada)

| Umbral | TP | FP | FN | F1 |
|---|---|---|---|---|
| 0.50 | 271 | 30 | 1 | 0.9459 |
| 0.55 | 271 | 27 | 1 | 0.9509 |
| 0.575 | 271 | 27 | 1 | 0.9509 |
| 0.58–0.62 | 259 | 3 | 13 | 0.9700 |
| 0.625–0.675 | 259 | 1 | 13 | 0.9737 |
| **0.68–0.705** | **259** | **0** | **13** | **0.9755** |
| 0.71–0.825 | 257 | 0 | 15 | 0.9716 |
| 0.85 | 246 | 0 | 26 | 0.9498 |
| 0.90 | 236 | 0 | 36 | 0.9291 |
| 0.95 | 184 | 0 | 88 | 0.8070 |

La meseta de F1 máximo tiene 6 puntos (0.68, 0.685, 0.69, 0.695, 0.70, 0.705): la regla elige el tercero, **0.69**.

## Por qué `minilm` y no `e5` (supuesto razonado, no calibrado)

Se calibraron los dos modelos con la misma regla (`--modelo e5`). El umbral de `e5` sería **0.845**:

| `e5` | Precisión | Recall | F1 |
|---|---|---|---|
| Con el umbral elegido (optimista) | 271/276 = 98.2 % [95.8–99.2] | 271/272 = 99.6 % [98.0–99.9] | 0.9891 |
| Validación cruzada | 131/155 = 84.5 % [78.0–89.4] | 131/131 = 100 % [97.2–100] | 0.9161 |

| Umbral `e5` | TP | FP | FN | F1 |
|---|---|---|---|---|
| 0.75 | 272 | 1195 | 0 | 0.3128 |
| 0.80 | 271 | 114 | 1 | 0.8250 |
| 0.835 | 271 | 47 | 1 | 0.9186 |
| 0.84 | 271 | 45 | 1 | 0.9218 |
| **0.845** | **271** | **5** | **1** | **0.9891** |
| 0.85–0.855 | 259 | 5 | 13 | 0.9664 |
| 0.86 | 239 | 2 | 33 | 0.9318 |
| 0.90 | 236 | 0 | 36 | 0.9291 |

La validación cruzada **empata** (0.9161 frente a 0.9158: la diferencia está muy por debajo del ruido). Lo que desempata:

1. El máximo de `e5` es **un solo punto** del barrido, al borde de un acantilado (de 0.845 a 0.84 pasan de 5 a 45 falsos positivos). La meseta de `minilm` tiene 6 puntos.
2. Esos falsos positivos no se ven en las etiquetas porque casi todos involucran titulares sin etiquetar. Con 0.845, `e5` agrupa en el snapshot: cuatro titulares de
   TVN sin relación («Contenido Exclusivo…» con una nota de vacunación), «precio del combustible» con «lista fiscal de la UE» y «Cobre Panamá», y «presidente visita
   Singapur» con «aeropuerto panameño suscribe convenio con empresa asiática» y la oficina marítima de Vietnam. Con 0.69, `minilm` no junta ninguno de esos.
3. Un grupo de más **infla** la evidencia (suma procedencias de eventos distintos); un grupo de menos solo la **subestima**. Con la regla del proyecto («nunca afirmar
   más de lo que la evidencia permite») se prefiere el modelo cuyos errores son por omisión.

El costo: `minilm` deja fuera la copia rusa de «Trump…» (recall 95.2 % frente a 99.6 % de `e5`). Los umbrales de `e5` y `minilm` no son intercambiables (escalas distintas):
`reglas_v1.3.yaml` guarda `agrupacion.modelo` junto con el umbral. La clasificación sigue con `e5` (`modelo_activo`, D-20); son decisiones independientes.

## Grupos en datos reales (79 titulares útiles, `minilm`, 0.69, ventana 7 días)

45 grupos. Los mayores:

| Grupo | Titulares | Medios | Procedencias (estimadas) |
|---|---|---|---|
| «Intensifying El Nino deepens economic risks across LatAm» (`GRP-79f3183472`) | 20 | 18 | **1** (Xinhua + Big News Network: red de sindicación, mismo medio y texto casi idéntico) |
| «Trump streicht Europa-Hilfe, lenkt Millionen nach Lateinamerika» (`GRP-0dfdd5a021`) | 12 | 12 | **3** (10 copias alemanas por texto casi idéntico, `zn.ua`, `novinky.cz`) |
| «Presidente de Panamá visita Singapur y Vietnam…» (`GRP-da35c3dead`) | 3 | 3 | 3 |
| «¿Cómo se fija el precio del combustible…?» (`GRP-81a11a5998`) | 2 | 1 | 1 (`NOT-1710ce462f` y `NOT-96d1ecac7d`: la misma nota de `panamaamerica.com.pa`) |

Las 20 copias de «Intensifying El Niño…» (17 dominios espejo de Big News Network, dos de ellos con dos copias, y Xinhua) son **una** procedencia. En cambio,
las 12 copias de «Trump…» dan 3 procedencias, no 1: las traducciones al ucraniano y al checo no comparten dominio, agencia nombrada ni texto casi idéntico con las alemanas,
aunque probablemente deriven del mismo despacho (la copia rusa dice «WP»). **Pendiente: una regla entre idiomas.** Hoy no existe (no se agrega ningún umbral nuevo en E1-08): las traducciones cuentan como procedencias separadas y el grupo de «Trump…» da 3. **El conteo es una estimación que puede errar por exceso:** sobrecuenta
traducciones del mismo despacho, pero no une medios sin una regla que lo justifique.

## Uso en E1-10

La parte de procedencias de E **debe** calcularse con `procedencias.fraccion_de_procedencias(n_procedencias, reglas)` (`min(n, tope) / tope`) y
**nunca** con `n_titulares`: tres copias de una agencia valen 1/tope, no tope/tope. Lo fija la prueba T02 (`test_el_puntaje_no_se_triplica`).

## Limitaciones

- **Una persona etiquetó** (D-85, propuestas del asistente aprobadas por Javier Acosta): no hay acuerdo entre etiquetadores para los grupos.
- **Muestra pequeña y concentrada:** 4 grupos humanos, dos de ellos con casi todos los pares. Los 38 titulares agrupados son casi todos de GDELT con `fecha_publicacion` vacía.
- **Punto ciego:** los falsos positivos entre titulares sin etiquetar no entran en la métrica. Por eso la elección de modelo se apoyó, además, en la inspección de los grupos del snapshot.
- **Calibración y evaluación comparten datos.** La cifra honesta es la validación cruzada; con 2 pliegues su umbral cambia mucho entre pliegues.
- La ventana de 7 días (supuesto) no se calibró: en el snapshot todos los grupos de 2 o más titulares caben en pocos días, así que la métrica no la pone a prueba.
- Reproducir: `HF_HUB_OFFLINE=1 poetry run python -m eval.agrupacion [--modelo e5]`; el umbral elegido se pasa a `reglas_v1.3.yaml` a mano (el script avisa si no coincide).
