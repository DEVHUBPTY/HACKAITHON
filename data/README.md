# Datos del snapshot

Receta reproducible de la spec E0-04 (D-74). Todo se genera con scripts; no se edita a mano.

```bash
poetry run python -m scripts.extraer --todo       # RSS + GDELT + Banco Mundial + USGS -> raw/ y processed/
poetry run python -m scripts.extraer --rss        # solo el RSS de TVN: correr a diario, agrega un archivo nuevo
poetry run python -m scripts.manifest             # data/manifest.json + data/CHANGELOG.md
poetry run python -m scripts.validar_snapshot     # outputs/validacion_snapshot.json
poetry run python -m src.carga                    # processed/validos/ + outputs/errores.csv + outputs/reporte_calidad.json (D-82)
```

## Qué se versiona y qué no (D-72)

| Carpeta | En git | Por qué |
|---|---|---|
| `raw/rss_tvn/` | **No** (`.gitignore`) | El RSS trae la descripción de cada nota: extracto con redistribución restringida |
| `raw/gdelt/` | **No** (`.gitignore`) | GDELT trae `socialimage` (derechos de imagen) |
| `raw/banco_mundial/`, `raw/usgs/` | Sí | Datos abiertos (CC BY 4.0 · dominio público de USGS) |
| `registro_extraccion/` | Sí | Fallos y notas de extracción (rangos, motivos, origen); sin contenido restringido. **No son respuestas de la API** |
| `processed/` | Sí | Solo metadatos: no contiene `descripcion` ni `socialimage` |
| `processed/validos/` | **No** (`.gitignore`) | Derivado y regenerable: las filas válidas que deja `python -m src.carga` (D-82). Mismos nombres que el contrato; salida determinista; nunca modifica los archivos de `processed/` ni su manifest. Es la entrada de E1-03 (si una prueba la necesita, la genera con ese comando) |
| `manifest.json`, `CHANGELOG.md` | Sí | Huellas SHA-256, consultas, historial |

El manifest registra el SHA-256 de los crudos que no se versionan, de modo que quien regenere
el snapshot pueda comparar. Para reconstruir `raw/rss_tvn/` y `raw/gdelt/` basta correr
`scripts.extraer` (GDELT solo cubre ~3 meses hacia atrás; el RSS no conserva todo el histórico,
por eso se descarga a diario).

## Reglas que aplica la conversión

- `raw/` guarda solo respuestas de la API sin modificar (incluida la que llega al tope de 250 y se subdivide).
  Los fallos y notas van a `registro_extraccion/`, con `origen` (generado por la herramienta o escrito a mano).
- Un `{}` de GDELT no prueba que no haya resultados: se guarda y queda como `vacio_sospechoso`; la cobertura
  de GDELT se mide por días con crudo `articles` (ver `diccionario.md`). `ventana_dias_aplicada` es el filtro, no la cobertura.
- Crudos inmutables: cada descarga es un archivo nuevo `<fuente>_<UTC>.ext`; nunca se sobrescribe.
- `seendate` de GDELT -> `fecha_deteccion`; `fecha_publicacion` solo viene del RSS.
- Ventana de noticias: 30 días previos a la extracción (hasta 90 si faltan registros), medida sobre
  `fecha_deteccion` (o `fecha_publicacion` si no hay detección). El intervalo de la sección 7 del PDF
  no se aplica (inconsistencia documentada en el manifest).
- `indicadores.csv`: cuadrícula completa de 6 países × 6 indicadores × 15 años = **540** filas (el PDF
  dice 1.350, pero su propia aritmética da 540; se documenta en el manifest). Lo faltante queda vacío, nunca 0.
- `processed/conversion.json`: ventana aplicada, registros excluidos con motivo y cobertura de GDELT por tema.
- Campos de cada archivo: `diccionario.md`.
- `fecha_corte_UTC` del manifest sale de los crudos, no del reloj: mismo `raw/`, mismo manifest.
