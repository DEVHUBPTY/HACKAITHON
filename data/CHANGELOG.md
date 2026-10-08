# Historial del snapshot

Generado por `python -m scripts.manifest` a partir del historial de `manifest.json`.
No editar a mano.

## v1.4 · 2026-10-08T03:35:18Z

- Hash del snapshot: `4503952d97fb1018429b517c2e230cf69fcb501f9f0529c38faa01d16e3683b6`
- Cambio de fuente: noticias.csv: 221 -> 268
- Cambio de fuente: Contenido distinto en processed/conversion.json (mismo conteo)
- Registros excluidos: 97 {'fuera_de_ventana': 97}
- Cantidad por archivo: conversion.json 97, eventos.geojson 82, fuentes.json 110, indicadores.csv 540, noticias.csv 268, sbp_series.csv 36

## v1.3 · 2026-10-07T00:41:03Z

- Hash del snapshot: `d0ae54537df7824aaf0a4295b56a50c9d4dcd00806d3ddb36e931d3007e8057e`
- Cambio de fuente: Fuente D (SBP, E3-02): sbp_series.csv con 3 series agregadas del sistema bancario, 12 meses de 2024 (36 filas); crudos .xlsx en raw/sbp/ no versionados (aviso legal de la SBP)
- Cambio de fuente: sbp_series.csv: 0 -> 36
- Registros excluidos: 97 {'fuera_de_ventana': 97}
- Cantidad por archivo: conversion.json 97, eventos.geojson 82, fuentes.json 110, indicadores.csv 540, noticias.csv 221, sbp_series.csv 36

## v1.2 · 2026-10-07T00:41:03Z

- Hash del snapshot: `ecc81c41ed6441436d5496a2efb5467fcb0ccdd8bf92eca81f435ab4610a4ff8`
- Cambio de fuente: Nueva captura del RSS de TVN (2026-10-07T00:41:03Z). Corrección D-89 de D-83: los crudos de GDELT de las consultas anteriores a E0-04 vuelven a alimentar noticias.csv, declarados con su consulta histórica (crudos_consulta_historica); la cobertura de las consultas vigentes de GDELT sigue en 0 porque la API responde HTTP 429 de forma sostenida (extracción en pausa). | Consultas de GDELT modificadas: E0-04 (seguimiento): las consultas 'Panama + palabra genérica' traían ~67 % de ruido (E0-09; solo 4 de 95 de 'logistica' eran logística). Ahora cada tema tiene una pata de medios de Panamá (sourcecountry:panama + términos en español) y una internacional con frases específicas de Panamá (excluye medios de Panamá).
- Cambio de fuente: noticias.csv: 186 -> 221
- Nota: Brecha conocida: las noticias útiles (sin ruido) son 94 (57 de GDELT y 37 de TVN), por debajo del objetivo interno más estricto de 100 útiles. El mínimo del PDF (100 registros únicos, al menos 20 de TVN) sí se cumple: 221 únicos y 88 de TVN. Cerrarla requiere nuevas capturas del RSS o una extracción de GDELT, hoy en pausa por HTTP 429.
- Registros excluidos: 97 {'fuera_de_ventana': 97}
- Cantidad por archivo: conversion.json 97, eventos.geojson 82, fuentes.json 110, indicadores.csv 540, noticias.csv 221

## v1.1 · 2026-10-06T17:07:06Z

- Hash del snapshot: `9e5f5d2ad57854efe9b677b4107bedc59220c11a2eaf04d411379c3c82817fb2`
- Cambio de fuente: Cambió el contenido sin cambiar los conteos
- Nota: Normalizamos idioma a ISO 639-1 y país en español en fuentes.json, y la cobertura de GDELT pasó a calcularse por tema a partir de los crudos (revisión del PR #2).
- Registros excluidos: 97 {'fuera_de_ventana': 97}
- Cantidad por archivo: conversion.json 97, eventos.geojson 82, fuentes.json 110, indicadores.csv 540, noticias.csv 186

## v1.0 · 2026-10-06T17:18:32Z

- Hash del snapshot: `ae297b7491ba381562ba72c7fe86c926f8d8ca11c62732e0597d984142915aec`
- Cambio de fuente: Snapshot inicial construido por el equipo con la receta de scripts.extraer (D-74).
- Cambio de fuente: URL del RSS de TVN: https://www.tvn-2.com/rss/ (tomada del hipervínculo [2] del PDF).
- Registros excluidos: 97 {'fuera_de_ventana': 97}
- Cantidad por archivo: conversion.json 97, eventos.geojson 82, fuentes.json 110, indicadores.csv 540, noticias.csv 186
