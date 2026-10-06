# Historial del snapshot

Generado por `python -m scripts.manifest` a partir del historial de `manifest.json`.
No editar a mano.

## v1.2 · 2026-10-06T17:07:06Z

- Hash del snapshot: `c5d0749731370909a8ad4cfbf0d30fe3e2f2754aa34410980988bb77a05e9f29`
- Cambio de fuente: D-83: los crudos de GDELT de las consultas reemplazadas (sin pata) dejan de alimentar noticias.csv; siguen en raw/ y se listan como crudos excluidos | Consultas de GDELT modificadas: E0-04 (seguimiento): las consultas 'Panama + palabra genérica' traían ~67 % de ruido (E0-09; solo 4 de 95 de 'logistica' eran logística). Ahora cada tema tiene una pata de medios de Panamá (sourcecountry:panama + términos en español) y una internacional con frases específicas de Panamá (excluye medios de Panamá).
- Cambio de fuente: conversion.json: 97 -> 79
- Cambio de fuente: fuentes.json: 110 -> 1
- Cambio de fuente: noticias.csv: 186 -> 71
- Registros excluidos: 79 {'fuera_de_ventana': 79}
- Cantidad por archivo: conversion.json 79, eventos.geojson 82, fuentes.json 1, indicadores.csv 540, noticias.csv 71

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
