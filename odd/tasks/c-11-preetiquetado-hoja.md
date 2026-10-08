# C-11 · Hoja de preetiquetado para que una persona confirme

Branch: `c-11-preetiquetado-hoja` (desde `811f5c9`, punta de C-10c). Continuación de C-10 (clasificación).
Engram mirror: `odd/c-11-preetiquetado-hoja/tasks` (pendiente: el registro de sesión falló el 2026-10-07).

## Objetivo
Ampliar las etiquetas humanas, que es lo único que mueve el límite de la clasificación (≈ 30 eventos hoy; hacen falta unos 19 eventos más para
detectar una mejora de 0,20). El asistente **propone** y una **persona** confirma o corrige (D-85); lo propuesto no cuenta como etiqueta humana
ni entra en ninguna métrica hasta que lo confirme una persona (D-101).

## Decisiones del dueño (2026-10-07)
- Preparar la hoja con (a) las 61 filas `asistente_provisional` para confirmar y (b) los titulares útiles del snapshot aún sin etiquetar, con una
  propuesta nueva. Marcada como propuesta.
- Proponer leyendo `docs/guia_temas.md`, sin llamar al LLM de pago (costo cero).

## Restricciones
- No tocar `eval/etiquetas.csv`, `eval/etiquetas/` (las hojas de las personas), `config/temas.yaml`, `config/ejemplos_excluidos.txt` ni `src/`.
- Ningún titular de `config/ejemplos_excluidos.txt` entra a la hoja. Nada del benchmark reservado.
- Columna `origen = asistente_propuesta`; columnas de decisión humana vacías; los dudosos se marcan con motivo, sin forzar una etiqueta.
- Formato compatible con las hojas del proyecto (`docs/etiquetado.md`) para que la persona pueda usar `eval/etiquetar.py` y `--consolidar`.
- Rama propia; commits convencionales sin atribución de IA; sin push ni PR sin pedirlo.

## Tareas
- [x] **T1** Hoja `eval/preetiquetado/hoja_preetiquetado.csv` y guía `docs/preetiquetado.md`. Ruta: delegada (writer).
- [x] **T2** Test del formato de la hoja (columnas, valores permitidos, sin ids de ejemplos excluidos, sin tocar las etiquetas). Ruta: delegada (writer).
- [ ] **T3** La persona confirma o corrige (humano); después `--consolidar` y volver a medir. Fuera de este alcance.

## Evidencia
- T1 y T2 escritas (sin commit; lo hace el dueño). Ruta: delegada (writer), disparador de escritura (3 archivos no triviales).
- RED: con la hoja ausente, `pytest -q tests/test_c11_preetiquetado.py` dio 3 failed, 13 errors, 1 passed. GREEN tras crear la hoja y la guía: 17 passed.
- Hoja: 61 filas en el bloque A (todas las `asistente_provisional`), **0 en el bloque B**: los 96 titulares útiles de la base ya están en
  `eval/etiquetas.csv`; los 44 sin etiqueta y no excluidos son ruido del pipeline. La cifra esperada (≈ 15) no se reproduce.
- 19 dudosos de 61. Eventos distintos del bloque A: 55 (54 nuevos frente a las humanas); con tema, 11.
- Límite verificado: `--validar` rechaza ids fuera de la muestra recalculada; solo 23 de las 61 caen en ella (el estado previo ya da 64 problemas).
- Doc: `docs/preetiquetado.md`. No se tocaron `eval/etiquetas.csv`, `eval/etiquetas/`, `config/`, `src/` ni `eval/*.py`.

## Próximo paso
Dueño: decidir el bloque B vacío y el hueco de `--validar` (modo nuevo o muestra congelada); T3 la hace una persona.
