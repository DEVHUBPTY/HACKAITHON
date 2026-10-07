# Datos del snapshot

Receta reproducible de la spec E0-04 (D-74). Todo se genera con scripts; no se edita a mano.

```bash
poetry run python -m scripts.extraer --todo       # RSS + GDELT + Banco Mundial + USGS -> raw/ y processed/
poetry run python -m scripts.extraer --rss        # solo el RSS de TVN: correr a diario, agrega un archivo nuevo
poetry run python -m scripts.manifest             # data/manifest.json + data/CHANGELOG.md
poetry run python -m scripts.validar_snapshot     # outputs/validacion_snapshot.json
poetry run python -m src.carga                    # processed/validos/ + outputs/errores.csv + outputs/reporte_calidad.json (D-82)
poetry run python -m scripts.catalogo             # outputs/catalogo.csv (E1-04): una fila por fuente, desde el manifest
# requiere outputs/reporte_calidad.json (src.carga); sin él, --sin-reporte marca "reporte de calidad no generado"
```

El catálogo (`outputs/catalogo.csv`) lista las 4 fuentes que define la base *Catálogo de datos* de Notion; las que aún no se usan quedan marcadas como "Fuente no usada todavía". La fuente D (SBP) ya está en el snapshot (E3-02, `processed/sbp_series.csv`).

## Versión del snapshot y receta (D-83, corregida por D-89)

El snapshot versionado es la v1.3 (v1.2 más la fuente D, E3-02). Sus noticias de GDELT vienen de los crudos de las consultas antiguas (anteriores a E0-04, sin pata), que D-89 devuelve a `noticias.csv` (D-83 los había excluido, pero las etiquetas humanas y el benchmark de desarrollo apuntan a esas noticias). Esas consultas figuran en `consultas_historicas` de `config/fuentes.yaml` y en el manifest, que declara cada crudo en `crudos_consulta_historica` y reporta su cobertura aparte (`cobertura_efectiva.gdelt_dias_por_tema_consulta_historica`). Las consultas vigentes de `config/fuentes.yaml` (dos patas por tema) son la receta de la próxima extracción; su cobertura sigue en 0 porque GDELT responde HTTP 429 de forma sostenida y la extracción está en pausa. El ruido se marca en `src.limpieza`, no se borra.

## Qué se versiona y qué no (D-72)

| Carpeta | En git | Por qué |
|---|---|---|
| `raw/rss_tvn/` | **No** (`.gitignore`) | El RSS trae la descripción de cada nota: extracto con redistribución restringida |
| `raw/gdelt/` | **No** (`.gitignore`) | GDELT trae `socialimage` (derechos de imagen) |
| `raw/sbp/` | **No** (`.gitignore`) | Los .xlsx de la SBP: su aviso legal prohíbe reproducir o redistribuir sin autorización escrita (pendiente de pedir). Se regeneran con `scripts.extraer --sbp` |
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
- `sbp_series.csv` (fuente D, E3-02): 3 series agregadas del sistema bancario × 12 meses de 2024 = 36 filas; una fila de cada informe .xlsx (la del «Sistema Bancario», verificada por su etiqueta); celda vacía = nulo; unidad original; `pagina` = hoja y celda. Es opcional: sin `raw/sbp/` la conversión no lo toca.
- `processed/conversion.json`: ventana aplicada, registros excluidos con motivo y cobertura de GDELT por tema.
- Campos de cada archivo: `diccionario.md`.
- `fecha_corte_UTC` del manifest sale de los crudos, no del reloj: mismo `raw/`, mismo manifest.
