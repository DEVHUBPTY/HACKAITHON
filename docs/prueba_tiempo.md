# Prueba de tiempo (E1-19 · D-71)

Mide cuánto tarda una persona en la misma tarea de forma **manual** y **asistida** por la app, y si el sustento de lo que entrega se mantiene. Alimenta el minuto de «valor operativo medido» del pitch (PDF sección 11).

**Estado: protocolo listo, pruebas pendientes.** Pruebas realizadas hasta hoy: **0**. Ningún tiempo de esta página es una medición: los campos de resultados están vacíos a propósito y solo se llenan con tiempos cronometrados de personas reales. No se estiman ni se simulan.

## Tarea equivalente

A partir del mismo snapshot: **elegir 5 temas para la agenda** y, **para uno de ellos, preparar un brief con sus fuentes y 3 preguntas de investigación**.

| | Manual | Asistida |
|---|---|---|
| Herramientas | Navegador y los archivos del snapshot (`data/processed/`) | La app (`poetry run streamlit run app.py`) |
| Qué se entrega | Lista de 5 temas + brief con fuentes citadas + 3 preguntas | Igual |
| Qué se mide | Minutos hasta terminar + validez de las fuentes citadas | Igual |

## Diseño (para que sea justa)

1. **Una condición por fecha de corte distinta.** Cada participante hace la condición manual con un corte y la asistida con otro, para no recordar los temas. Los cortes son los de la selección de Precision@5 (`docs/protocolo_evaluacion.md`, sección 3, y `eval/precision_at_5.py`).
2. **Orden alternado.** Mitad de los participantes empieza manual y mitad asistida.
3. **Mínimo 3 pruebas por condición** (6 en total). Se reporta n. Con menos, o sin especialista editorial, el resultado se declara **exploratorio** (D-74).
4. **Calidad aparte del tiempo.** Una persona que no hizo la tarea revisa las fuentes citadas del brief con el veredicto de `docs/protocolo_evaluacion.md` sección 4 (sustentada, parcial, no sustentada, tipo incorrecto). Ahorrar tiempo no vale si baja el sustento.
5. **Qué se cronometra.** Desde que se entrega la consigna hasta que la persona declara que terminó, sin contar el arranque de la app ni la carga de datos. El cronómetro lo maneja quien modera, no el participante.
6. **Quien hace la prueba de tiempo en una fecha de corte no es quien eligió los 5 temas de Precision@5 para ese mismo corte** (vería la respuesta, o la habría influido).
7. **Consigna idéntica** en ambas condiciones. La persona del equipo que probó la app antes (quien la construyó) no participa como sujeto.

## Registro de pruebas

Cada fila es una prueba real. Se llena durante la sesión; no se completa a posteriori.

| # | Participante (código, sin nombre) | Condición | Fecha de corte del snapshot | Orden (1.º o 2.º) | Minutos | Fuentes citadas | Fuentes sustentadas | Observaciones |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| 4 | | | | | | | | |
| 5 | | | | | | | | |
| 6 | | | | | | | | |

## Resultados

| | Manual | Asistida |
|---|---|---|
| Pruebas (n) | pendiente | pendiente |
| Mediana de minutos | pendiente | pendiente |
| Mínimo–máximo | pendiente | pendiente |
| Fuentes sustentadas / citadas (con n e IC 95 %) | pendiente | pendiente |

**Ahorro de tiempo:** pendiente (se calcula como diferencia de medianas, con n por condición, solo cuando haya al menos 3 pruebas por condición).

**Declaración:** exploratorio hasta que se cumpla el diseño completo. No se infiere audiencia, rentabilidad ni reducción de riesgo.
