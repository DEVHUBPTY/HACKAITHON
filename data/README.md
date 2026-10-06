# Datos del snapshot

Receta reproducible de la spec E0-04 (D-74). Todo se genera con scripts; no se edita a mano.

```bash
poetry run python -m scripts.extraer --todo       # RSS + GDELT + Banco Mundial + USGS -> raw/ y processed/
poetry run python -m scripts.extraer --rss        # solo el RSS de TVN: correr a diario, agrega un archivo nuevo
poetry run python -m scripts.manifest             # data/manifest.json + data/CHANGELOG.md
poetry run python -m scripts.validar_snapshot     # outputs/validacion_snapshot.json
```

## Qué se versiona y qué no (D-72)

| Carpeta | En git | Por qué |
|---|---|---|
| `raw/rss_tvn/` | **No** (`.gitignore`) | El RSS trae la descripción de cada nota: extracto con redistribución restringida |
| `raw/gdelt/` | **No** (`.gitignore`) | GDELT trae `socialimage` (derechos de imagen) |
| `raw/banco_mundial/`, `raw/usgs/` | Sí | Datos abiertos (CC BY 4.0 · dominio público de USGS) |
| `processed/` | Sí | Solo metadatos: no contiene `descripcion` ni `socialimage` |
| `manifest.json`, `CHANGELOG.md` | Sí | Huellas SHA-256, consultas, historial |

El manifest registra el SHA-256 de los crudos que no se versionan, de modo que quien regenere
el snapshot pueda comparar. Para reconstruir `raw/rss_tvn/` y `raw/gdelt/` basta correr
`scripts.extraer` (GDELT solo cubre ~3 meses hacia atrás; el RSS no conserva todo el histórico,
por eso se descarga a diario).

## Reglas que aplica la conversión

- Crudos inmutables: cada descarga es un archivo nuevo `<fuente>_<UTC>.ext`; nunca se sobrescribe.
- `seendate` de GDELT -> `fecha_deteccion`; `fecha_publicacion` solo viene del RSS.
- Ventana de noticias: 30 días previos a la extracción (hasta 90 si faltan registros), medida sobre
  `fecha_deteccion` (o `fecha_publicacion` si no hay detección). El intervalo de la sección 7 del PDF
  no se aplica (inconsistencia documentada en el manifest).
- `indicadores.csv`: siempre 1.350 filas; lo faltante queda vacío, nunca 0.
- `processed/conversion.json`: ventana aplicada y registros excluidos con motivo.
- `fecha_corte_UTC` del manifest sale de los crudos, no del reloj: mismo `raw/`, mismo manifest.
