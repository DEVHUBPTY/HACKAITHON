# Pendientes que debe hacer una persona

El reto exige una persona en cada uno de estos puntos; un agente no los reemplaza (`docs/REVISION.md`, paso 2). Cada ítem indica su tarea del Backlog de Notion y los comandos exactos. Mientras no se hagan, las métricas correspondientes siguen rotuladas como provisionales (D-101) y no se presentan como juicio humano.

Orden sugerido: C-09 → C-04 → C-11 → C-05 → C-12 → C-08 → C-03. Al terminar, `poetry run python -m scripts.auditoria_final` actualiza el estado de la sección 10.

## C-09 · Revisión humana de las métricas

1. **Validez de sustento.** Una persona que no escribió el código de generación completa la columna `veredicto` (sustentada, parcial, no sustentada, tipo incorrecto; `docs/protocolo_evaluacion.md`, sección 4) en `outputs/revision_sustento.csv` y en `outputs/revision_sustento_boletin_cu05.csv` (boletín de CU-05). Deja `origen_juicio` vacío o `humano`. Después:
   ```bash
   poetry run python -m eval.sustento
   ```
2. **Precision@5 con selección ciega, sobre el corte actual.** Generar la hoja ciega, que la marque un editor y calcular:
   ```bash
   poetry run python -m eval.precision_at_5 --hoja
   poetry run python -m eval.precision_at_5 --seleccion eval/seleccion_editor.csv          # --especialista solo si quien eligió es especialista
   ```
3. **Revisión humana de las fichas.** En `poetry run streamlit run app.py`, pantalla *7 · Revisar*, revisar al menos la ficha de CU-05 (`GRP-da35c3dead`) y las 5 fichas trazables (`poetry run python -m scripts.fichas_trazables --casos`). Luego:
   ```bash
   poetry run python -m eval.revision
   ```
4. **Prueba de ahorro de tiempo.** Seguir `docs/prueba_tiempo.md` (condición manual y asistida, calidad aparte).
5. **Opcional: los 47 titulares `tvn_20261008`.**
   ```bash
   poetry run streamlit run eval/etiquetar.py        # barra lateral: «Qué titulares ver» → tvn_20261008
   ```
   Pasos posteriores en `docs/etiquetado.md`, sección «Después de etiquetar».

Después de 1–3 regenerar la página de métricas: `poetry run python -m scripts.pagina_metricas`.

## C-04 · Ensayo sin Wi-Fi (cierra T10)

Con la red apagada:
```bash
poetry run python -m scripts.verificar_offline
.venv/bin/streamlit run app.py -- --demo
```
Esperar a que termine la primera carga antes de navegar y recorrer `docs/demo.md`.

## C-05 · Notion

Confirmar que el espacio de Notion está compartido solo con el equipo y el jurado.

## C-11 · Escaneo de secretos

Escaneo completo, incluido el historial de git (por ejemplo con `gitleaks detect --source . --log-opts="--all"`), y guardar el resultado en `outputs/auditoria_secretos.json` con `"limpio": true|false`. Sin ese archivo, el ítem P-01 de la auditoría queda en FALTA.

## C-12 · Umbral de Consulta (0.840)

Escribir unas 30 preguntas fuera del corpus (D-134) y medir cuántas se abstienen:
```bash
poetry run python -m eval.recuperacion
```
Agregarlas, aprobadas por la persona, a las consultas negativas del benchmark de desarrollo (`benchmark/benchmark_dev.jsonl`, formato en `benchmark/README.md`) y volver a correr el comando; si el margen sigue siendo estrecho, el umbral se recalibra con `--calibrar` (`docs/consulta.md`).

## C-03 · Pitch

Preparar y ensayar el pitch con `docs/demo.md` (recorrido cronometrado).

## C-08 · Autoevaluación

Completar la autoevaluación con la rúbrica del reto y registrar el resultado en Notion.
