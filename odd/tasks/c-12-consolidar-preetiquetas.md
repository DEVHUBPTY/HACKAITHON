# C-12 · Incorporar las 61 etiquetas confirmadas y medir de nuevo la clasificación

Branch: `c-12-consolidar-preetiquetas` (desde `f227493`, punta de C-11). Continuación de C-10 / C-11.
Engram mirror: `odd/c-12-consolidar-preetiquetas/tasks` (pendiente: el registro de sesión falló el 2026-10-07).

## Objetivo
La persona (David) confirmó el 2026-10-07 las 61 filas de `eval/preetiquetado/hoja_preetiquetado.csv` (19 dudosas una a una, 42 en bloque).
Hay que hacerlas utilizables por las evaluaciones y medir cuántos puntos de exactitud tiene ahora la clasificación con ese conjunto
ampliado, comparado con el conjunto original (35/64 = 54,7 %).

## Decisión de diseño del asistente (a confirmar por el dueño al revisar el PR)
- **No se modifica `eval/etiquetas.csv`**: pruebas y hashes de reproducibilidad asumen exactamente 100 etiquetas humanas. Se crea un archivo
  aparte, `eval/etiquetas_ampliadas.csv` = filas `origen=humano` de `eval/etiquetas.csv` + las 61 confirmadas (origen `humano`, estrato
  `preetiquetado_c11`, `n_etiquetadores=1`, sin peso de muestreo propio), generado por un modo nuevo de `eval/etiquetar.py` que valida y no
  toca sus entradas. Fusionarlo con el original queda para una decisión posterior del dueño.

## Restricciones
- No tocar `eval/etiquetas.csv`, `eval/etiquetas/`, `config/temas.yaml`, `config/ejemplos_excluidos.txt`, `src/clasificacion.py` ni los umbrales.
- Las 42 filas aprobadas en bloque se marcan como tales (nota); no se presentan como revisión fila por fila.
- Sin llamadas de red ni de pago. Sin números mágicos; valores nuevos en config con fila en `docs/parametros.md`.
- Se reportan las métricas del conjunto original y del ampliado, y solo de las filas nuevas, con n, eventos e IC 95 % por evento. Sin ajustar nada
  después de ver el resultado: una sola medición.
- Rama propia; commits convencionales sin atribución de IA; sin push ni PR sin pedirlo.

## Tareas
- [ ] **T1** Modo `--incorporar-hoja` en `eval/etiquetar.py` con tests (valida, no toca entradas, idempotente) y `eval/etiquetas_ampliadas.csv`. Ruta: delegada (writer).
- [ ] **T2** Medición única con el conjunto ampliado (`eval.clasificacion` y `eval.clasificacion_por_evento`). Ruta: delegada (writer).
- [ ] **T3** PR de las ramas de clasificación (C-10b, C-10c, C-11, C-12) y registro en Notion. Ruta: padre.

## Evidencia
- T1 y T2 (ruta delegada, un writer; `done`): RED = 37 de 37 tests nuevos fallaban antes del código; GREEN = 39 passed; suite completa
  3080 passed, 3 skipped, 6 xfailed (base 3041); `--validar` OK (34). Verificación del padre: 118 passed (C-12, C-11, reproducibilidad y x15),
  `--validar` OK; `eval/etiquetas.csv`, `eval/etiquetas/`, `eval/preetiquetado/`, `outputs/clasificacion.json`, `outputs/clasificacion_por_evento.json`,
  `config/temas.yaml`, `config/ejemplos_excluidos.txt` y `src/clasificacion.py` sin cambios.
- `eval/etiquetas_ampliadas.csv`: 161 filas = 100 humanas originales + 61 confirmadas (estrato `preetiquetado_c11`, `n_etiquetadores=1`,
  `peso_muestreo` vacío = 1,0). Idempotente (`cmp` idéntico). 5 filas de ruido de la hoja llevan `grupo`, que `validar_fila` prohíbe: el modo lo
  descarta y avisa por stderr en vez de abortar (decisión pendiente del dueño).
- Medición única (e5 método A, 95 % bootstrap por evento): conjunto original 35/64 = 54,7 % [42,6–66,3], 30 eventos (se reproduce);
  ampliado 39/80 = 48,7 % [38,1–59,5], 44 eventos, por evento 0,443 [0,307–0,591], macro-F1 0,376, cobertura 85,0 %, exactitud entre cubiertas 57,4 %;
  solo las 16 filas nuevas (14 eventos: 8 `servicios_publicos`, 3 `economia`, 5 `sin_tema`) 4/16 = 25,0 % [10,2–49,5].
  Solo 16 de las 61 entran a la evaluación de clasificación (el filtro de ruido del sistema ya marcaba las otras 45).
- Lectura honesta: el porcentaje bajó porque cambió el conjunto evaluado, no se demuestra que el sistema empeore. Las filas nuevas apuntan a
  que el 54,7 % era optimista, pero con n = 16 y 14 eventos el IC es muy ancho y se solapa con el original.
- Límite conocido: `outputs/clasificacion_por_evento_ampliada.json` conserva la advertencia fija «≈ 29 eventos» (el conjunto ampliado tiene 44).

## Próximo paso
T3: PR de las ramas de clasificación (C-10b, C-10c, C-11, C-12) y registro en Notion.
