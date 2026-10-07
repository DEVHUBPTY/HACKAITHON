# HackIAthon · De la señal a la decisión

Copiloto que convierte titulares públicos (TVN RSS + GDELT) y datos oficiales (Banco Mundial, USGS, SBP) en una **bandeja de temas priorizados, fichas de evidencia y borradores** para una decisión humana.

- **Modalidad principal:** editorial (TVN). **Extensión:** banca, como configuración sobre el mismo núcleo.
- **Todo lo que produce el sistema es BORRADOR.** Nada se publica.
- Principio rector: **nunca afirmar más de lo que la evidencia permite, y demostrarlo cita por cita.**

## Cómo trabajar en este repo

El enunciado oficial está en `docs/reto_TVN.pdf`. Toda referencia "PDF sección X" en las specs apunta ahí.

1. Cada tarea tiene una spec en `specs/<ID>.md` con **Objetivo · Punteros · Restricciones · Listo cuando**. Léela completa antes de escribir código.
2. Propón un plan breve (archivos a crear o tocar, enfoque, riesgos) y **espera aprobación** antes de implementar.
3. Trabaja **solo dentro del alcance de la spec**. Si falta información o algo contradice este archivo, pregunta; no inventes.
4. Al terminar, ejecuta **todos** los comandos de "Listo cuando" y muestra su salida real.
5. Commits pequeños, *conventional commits* con el ID como ámbito: `feat(E1-02): carga con validación lazy`.
6. Antes de dar una tarea por cerrada, haz la revisión de `docs/REVISION.md`.
7. Tramos del evento y punto de corte: `docs/cronograma.md`.
8. Flujo: una tarea = un worktree → una rama (ej. `e1-02-carga`) → un PR a `main` con la plantilla de `.github/`. Cada PR lo revisa un agente revisor independiente, que deja su veredicto escrito en el PR y en Notion; con veredicto favorable, el asistente integra el PR (D-78).

**Equipo:** David Fen, Javier Acosta y Juan Zhou. Todos hacen de todo; el responsable de cada tarea está en el Backlog de Notion. El evento ya empezó (fase *Evento* en Notion). La demo corre **en local**: no hay despliegue.

## Comandos

Disponibles hoy:

```bash
poetry install                                       # instala todo desde poetry.lock
poetry run pytest -v                                 # todas las pruebas (hoy T01 y T03; las demás T llegan con su spec)
poetry run python -m scripts.extraer --todo          # RSS + GDELT + Banco Mundial + USGS → data/raw/ y data/processed/ (E0-04)
poetry run python -m scripts.extraer --rss           # solo el RSS de TVN (correr a diario)
poetry run python -m scripts.extraer --sbp            # fuente D: informes agregados de la SBP → data/raw/sbp/ y data/processed/sbp_series.csv, el CSV se versiona (D-116, riesgo aceptado) y los .xlsx de raw/sbp/ quedan solo locales (E3-02)
poetry run python -m scripts.manifest                # data/manifest.json + data/CHANGELOG.md
poetry run python -m scripts.validar_snapshot        # snapshot contra la receta → outputs/validacion_snapshot.json
poetry run python -m src.config --validar            # valida todo config/*.yaml (D-79)
poetry run python -m src.carga                       # carga + validación → data/processed/validos/ y reporte de calidad (D-82)
poetry run python -m src.normalizacion               # normaliza y crea data/senales.duckdb
poetry run python -m src.limpieza                    # limpia titulares y marca ruido
poetry run python -m src.clasificacion               # embeddings locales y tema_clasificado (E1-07)
poetry run python -m eval.clasificacion              # métricas de clasificación (casos difíciles y etiquetas)
poetry run python -m src.agrupacion                  # grupos GRP- y procedencias independientes (estimadas)
poetry run python -m eval.agrupacion                 # calibra el umbral y mide precisión/recall de pares con etiquetas
poetry run python -m src.contexto                    # vínculos por subtema con el Banco Mundial y, por defecto, USGS (--eventos, data/processed/eventos.geojson) → tabla vinculos y outputs/reporte_vinculos.json (E1-09, E1-09b)
poetry run python -m src.puntaje                     # R I U N E y P, estado de evidencia, vacíos, contradicciones y acción → tablas puntajes, evidencia, contradicciones y outputs/prioridad.json (E1-10; --sin-llm no compara con el LLM)
poetry run python -m eval.puntaje                    # distribución de P y de cada componente; tabla rango × estado de evidencia → outputs/puntaje.json (E1-10)
poetry run python -m eval.sensibilidad               # top 5 ante cada peso ±5 y cada supuesto ±20 % → outputs/sensibilidad.json (E1-10, X02)
poetry run python -m src.ficha --grupo GRP-… --modalidad editorial|banca   # ficha de evidencia con las 5 partes, en Markdown (--formato jsonl: línea de fichas.jsonl); después de src.puntaje (E1-10b)
poetry run python -m src.generacion --ficha-json tests/fixtures/ficha_generacion.json  # borrador desde una ficha (E1-12); --grupo GRP-… genera desde la ficha real
poetry run python -m src.generacion --grupo GRP-… --modalidad banca   # boletín de entorno bancario (E2-02); antes: src.puntaje --modalidad banca
poetry run python -m scripts.medir_generacion --proveedor ollama  # latencia: primera respuesta y paquete completo (E1-12)
poetry run python -m src.validador --tasas            # tasa de rechazo por modelo y por regla (n e IC 95 %) desde outputs/rechazos.jsonl (E1-13)
poetry run python -m src.consulta "pregunta"         # consulta en español con abstención (--metodo semantica|bm25)
poetry run python -m eval.recuperacion               # Recall@5 y abstención, semántica vs. BM25, con n e IC
poetry run streamlit run app.py                      # interfaz: 6 pantallas (E1-15); ?caso=GRP-… o ?caso=CASO-… abre la ficha; la pantalla Revisión es el flujo de la etapa 7 (E1-16)
poetry run python -m src.revision --abrir GRP-… --revisor "Nombre"   # abre el grupo como CASO-… (también --estado GRP-…, --historial CASO-…); las acciones se hacen en la app (E1-16)
poetry run python -m scripts.fichas_trazables --casos   # C-01: 5 fichas reales, una por caso de uso CU-01…CU-05 (D-118), elegidas por regla (config/fichas_trazables.yaml), trazabilidad comprobada contra los datos → outputs/fichas_trazables/ y CASO- (revisión provisional del asistente); sin --casos solo escribe en outputs/fichas_trazables/vista_previa/ (fuera de git)
poetry run python -m src.exportar --caso CASO-001    # (--demo: rutas de la demo) Markdown + fila CSV de «Casos y evidencias» (Notion) en outputs/notion/, y outputs/fichas.jsonl; volver a exportar actualiza (E1-16)
poetry run python -m eval.revision                   # tasas de aceptación, corrección y descarte con n e IC, motivos, tiempo por caso y % de afirmaciones editadas → outputs/revision.json (E1-16)
poetry run python -m eval.reporte_pruebas          # corre T01–T10 por marcador y escribe outputs/pruebas.csv con las columnas de la base Pruebas de Notion; pendientes en config/pruebas.yaml (E1-17)
poetry run streamlit run app.py -- --demo            # modo demo (data/demo.duckdb, C-06) con los pasos de docs/demo.md
poetry run python -m scripts.verificar_offline       # chequeo antes del pitch
poetry run python -m scripts.calentar_cache          # borradores en data/cache_llm (con red; --verificar sin red) · docs/fallback.md
poetry run python -m scripts.catalogo                # outputs/catalogo.csv (E1-04)
poetry run python -m scripts.explorar                # docs/exploracion.md (E0-09)
poetry run python -m scripts.probar_llm --modelo <tag>  # latencia, JSON válido y memoria de un modelo de Ollama (E0-07)
poetry run streamlit run eval/etiquetar.py           # etiquetado humano (E1-06; ver docs/etiquetado.md)
poetry run python -m eval.ruido                      # precisión y recall del filtro de ruido contra eval/etiquetas.csv
poetry run python -m eval.validar_benchmark          # valida benchmark/benchmark_dev.jsonl (E0-06)
poetry run python -m scripts.pagina_metricas           # página de métricas desde outputs/ (n, IC 95 %, fuente, commit y origen del juicio por métrica; falla si una proporción no lleva n e IC o si un juicio provisional se rotula humano) → outputs/pagina_metricas.md (C-02)
poetry run python -m scripts.reproducir --verificar  # reconstruye todo desde data/raw/ y compara los hashes con el manifest; sin --verificar registra los hashes (E1-20; docs/reproducibilidad.md)
poetry run python -m scripts.empaquetar_datos        # paquete de datos redistribuible en entrega/datos/ (ignorado por git) + outputs/entrega_manifest.json; revisa que no haya campos restringidos (C-07; --verificar revisa el existente)
poetry run python -m scripts.auditoria_final         # condiciones previas de la sección 10: PASS / FALTA / NO VERIFICABLE por ítem → outputs/auditoria_final.md y .json (C-07; --reproducir, --estricto)
```

Previstos (existirán cuando se implemente su spec):

```bash
poetry run python -m scripts.verificar_offline       # chequeo antes del pitch (C-06)
poetry run python -m eval.run_benchmark --split dev  # benchmark → outputs/metricas.json (E1-18)
```

## Estructura

Lo que existe hoy:

```
CLAUDE.md  README.md  pyproject.toml  poetry.lock  .env.example  .github/pull_request_template.md  app.py (E1-15)  .streamlit/config.toml
config/      reglas_v1.3.yaml · temas.yaml · ejemplos_excluidos.txt · vinculos.yaml · modalidad_editorial.yaml · salidas.yaml · restricciones.yaml · validador.yaml (E1-13)
             cache.yaml (E1-14) · ruido.yaml · fuentes.yaml · contrato.yaml · carga.yaml · normalizacion.yaml · clasificacion.yaml · etiquetado.yaml · exploracion.yaml · llm.yaml · benchmark.yaml · consulta.yaml · prioridad.yaml (E1-10) · generacion.yaml (E1-12) · origen_juicio.yaml (D-101: quién hizo el juicio de una métrica; el provisional del asistente nunca sale como humano)
             verificacion.yaml (E1-10b) · interfaz.yaml (E1-15) · revision.yaml (E1-16: estados, transiciones, motivos de descarte, revisores y roles, columnas de Notion) · reproducibilidad.yaml (E1-20: pasos, salidas que se hashean y qué se excluye) · modalidad_banca.yaml (E1-10b, PARCIAL: solo tabla de acciones y fuentes extra; E2-01 la completa, D-90)
templates/   ficha.md.j2 (E1-10b) · caso.md.j2 (E1-16: ficha + versión + historial + leyenda, para Notion)
prompts/     afirmaciones_citadas.txt (E0-07) · comparar_contradicciones.txt (E1-10) · afirmaciones_ficha.txt · paquete_editorial.txt (E1-12) · boletin_banca.txt (E2-02: los dos pasos del boletín), versionados
data/        raw/ (inmutable) · processed/ (validos/ fuera de git) · registro_extraccion/ · manifest.json · CHANGELOG.md · diccionario.md · README.md
             processed/sbp_series.csv (E3-02: fuente D, 3 series agregadas × 12 meses de 2024; el CSV se versiona por D-116 (riesgo aceptado: aviso legal de la SBP) y los .xlsx de raw/sbp/ no (D-72); se regeneran con `scripts.extraer --sbp`; las rutas restringidas están en `redistribucion_restringida` de config/fuentes.yaml y un test las vigila) · senales.duckdb (generado, fuera de git) · revision.duckdb (E1-16: casos, versiones y `revisiones` de solo agregar; fuera de git, NO se regenera con el pipeline) · cache_llm/ (E1-14: borradores generados, SÍ versionada; docs/fallback.md)
src/         trazabilidad (C-01: selección y comprobación de citas contra los datos) · carga · contexto (E1-09) · contexto_sbp (E3-02: series agregadas de la SBP como vínculo del subtema de banca) · normalizacion · limpieza · embeddings · clasificacion · baseline · consulta · db · registro (D-75) · configuracion (D-79; config = alias de su CLI) · consultas_gdelt · esquemas (`Ficha` de E1-10b; paso 1 y paquetes de E1-12)
             agrupacion · procedencias · puntaje · evidencia · contradicciones · prioridad (E1-10: `python -m src.puntaje`) · ficha (E1-10b) · interfaz (E1-15: lógica de presentación de app.py, sin Streamlit)
             generacion (E1-12: dos pasos) · validador (E1-13: reglas deterministas; la generación y la corrección de la revisión solo lo llaman)
             revision (E1-16: casos CASO-, acciones y transiciones, versiones, registro de solo agregar en `data/revision.duckdb`) · exportar (E1-16: Markdown, CSV de Notion, fichas.jsonl)
             cache (E1-14: caché de respuestas del LLM, `data/cache_llm/` versionada, solo cache para la interfaz) · llm/costo (tope D-98: USD 100 / 200 M tokens; `SaldoAgotado` ante HTTP 402)
src/llm/     proveedor.py (interfaz, `UsoLlm` y `crear_proveedor`, por LLM_PROVIDER) · ollama.py · deepseek.py · costo.py (tope de costo D-67; al alcanzarlo lanza `TopeDeCostoAlcanzado`, D-95)
scripts/     extraer.py · sbp.py (E3-02: conversión de los .xlsx de la SBP a sbp_series.csv) · conversion.py · manifest.py · validar_snapshot.py · catalogo.py · explorar.py · estimar_consultas_gdelt.py · probar_llm.py · medir_generacion.py (E1-12) · calentar_cache.py (E1-14: calienta y `--verificar` la caché de borradores) · reproducir.py (E1-20: pipeline de punta a punta y hashes contra el manifest) · empaquetar_datos.py · auditoria_final.py (C-07: paquete de datos redistribuible y condiciones previas de la sección 10; `config/entrega.yaml`)
eval/        revision.py (E1-16) · etiquetar.py · etiquetas/ (una hoja por persona) · etiquetas.csv · ruido.py · validar_benchmark.py · clasificacion.py · calibrar_clasificacion.py · metricas.py · recuperacion.py · puntaje.py · sensibilidad.py
benchmark/   benchmark_dev.jsonl (solo desarrollo) · sinteticos.csv · README.md
tests/       fixtures/ · test_t01_carga.py · test_t03_recirculada.py · test_casos_dificiles.py · test_*.py
outputs/     fichas.jsonl · revision.json · notion/ (E1-16, se generan al exportar) · catalogo.csv · reporte_vinculos.json · clasificacion.json · recuperacion.json · prioridad.json · puntaje.json · sensibilidad.json · validacion_snapshot.json · probar_llm_<modelo>.json
notion/      exportación inicial para importar en Notion (la versión vigente está en Notion)
specs/  docs/
```

Previsto (lo crea la spec indicada):

```
data/demo.duckdb (C-06)
config/      modalidad_banca.yaml completa (E2-01: sectores, horizonte, bandeja)
prompts/     comparar_contradicciones.txt (E1-10) · respuesta_consulta.txt (E1-11)
scripts/     buscar_casos.py · preparar_demo.py · capturas_demo.py · verificar_offline.py (C-06)
eval/        run_benchmark.py (E1-18) · precision_at_5.py (E1-19) · y los módulos de métricas que pide cada spec
tests/       test_t02_*.py, test_t04_*.py … test_t10_*.py (ver docs/protocolo_evaluacion.md)
outputs/     pruebas.csv (E1-17) · metricas.json (E1-18)
```

## Contrato de datos (sección 7 del reto)

| Archivo | Campos mínimos |
|---|---|
| noticias.csv | id_noticia, titulo, url, medio, idioma, fecha_publicacion, fecha_deteccion, fecha_extraccion, tema, origen, alcance_texto |
| indicadores.csv | pais_iso3, indicador_id, anio, valor (nullable), unidad, fuente_url, fecha_extraccion, licencia |
| eventos.geojson | id, magnitude, time, updated, longitude, latitude, depth, place, status, url |
| fichas.jsonl | id_caso, modalidad, ids_fuente, afirmaciones, citas, puntaje, componentes, estado_evidencia, borrador, estado_revision |
| manifest.json | version, fecha_corte_UTC, consultas, cantidad por archivo, licencia/condiciones, sha256, transformaciones |

IDs **estables** con prefijo (D-63): `NOT-` = SHA-1 de la URL canónica (10 caracteres) · `IND-<pais>-<indicador>-<anio>` · `SIS-<id USGS>` · `SBP-<serie>-<periodo>` · `GRP-` = hash de sus `NOT-` ordenados · `CASO-` correlativo y persistente · `SYN-` datos sintéticos. El mismo dato produce siempre el mismo ID.

El `tema` de `noticias.csv` es el **tema de origen** (consulta de GDELT o categoría del RSS). El del clasificador es `tema_clasificado`; nunca se usa uno como etiqueta del otro (D-62).

## Reglas de datos (no negociables)

- UTF-8. Fechas en **ISO 8601 UTC** en datos; **hora de Panamá solo en la interfaz**.
- `fecha_publicacion` y `fecha_deteccion` (seendate de GDELT) son **distintas**. Nunca sustituir una por otra.
- **Los nulos son nulos. Nunca rellenar con cero.** Conservar unidades originales.
- `data/raw/` es inmutable. Todo cambio va a `processed/` y se registra en el manifest, que incluye un **historial** de versiones, cambios de fuente, revisiones de datos y registros excluidos (D-63).
- La cuadrícula del Banco Mundial tiene **540 filas** (6 países × 6 indicadores × 15 años), con nulos explícitos. El PDF dice 1.350, que no cuadra con su propia definición (D-81).
- Datos del Banco Mundial son **anuales**: nunca describirlos como "actuales" ni "de hoy".
- Origen, URLs y condiciones de cada fuente: `docs/fuentes.md`.
- La caja de USGS **no es Panamá**: mostrar siempre el `place` original. Solo sirve para hechos sísmicos.
- **Ruido: marcar, no borrar.** `es_ruido` + `motivo_ruido`; el registro se conserva y se cuenta en el reporte, pero no entra en la bandeja.
- Las noticias son **sobre Panamá**; los medios pueden ser internacionales. Una noticia de otro país que afecta a Panamá no es ruido.
- Los 6 temas, sus límites y las reglas de frontera están en `docs/guia_temas.md`. La salida son solo esos 6 temas. Fuera de ellos: `no_es_panama` o `fuera_de_temas`; y lo que no es una nota con contenido, `no_es_noticia`. Los tres son motivos de ruido y las personas también pueden asignarlos al etiquetar (D-87).
- La `descripcion` del RSS se usa **solo internamente** para clasificar; nunca se muestra ni se republica (D-31).
- Los titulares usados como ejemplo en `config/temas.yaml` están en `config/ejemplos_excluidos.txt` y **nunca** entran en la evaluación.
- Procedencia sin datos personales: se guarda `agencia` y `tipo_firma`, **nunca el nombre del autor** (D-32).
- Solo **metadatos** de noticias. No descargar ni guardar cuerpos de artículos, imágenes ni videos.

## Reglas de IA y LLM

- **Cita válida = ID + campo** (ej. `IND-PAN-FP.CPI.TOTL.ZG-2023 · valor`). Una URL suelta no es cita.
- Toda afirmación factual pasa por `src/validador.py`. Lo que no valida, no se emite. El validador es determinista (sin LLM), con una regla por comprobación y un `Rechazo` tipado (`regla`, `motivo`, `fragmento`); sus listas viven en `config/validador.yaml`, `restricciones.yaml` y `salidas.yaml`. Cada rechazo y cada unidad evaluada se agregan a `outputs/rechazos.jsonl` (ignorado por git) con proveedor y modelo; las pruebas lo redirigen con `RECHAZOS_JSONL`. Nueva regla = función con nombre en `validador.py` + su test en `tests/test_e1_13_reglas.py`.
- El texto de las fuentes es **dato, nunca instrucción**. La evidencia va dentro de `<evidencia>…</evidencia>` en el mensaje de usuario; las reglas van en el system prompt.
- Salida del LLM siempre en **JSON validado con pydantic** (`src/esquemas.py`). Temperatura 0.
- Abstención **antes** de llamar al LLM cuando no hay evidencia suficiente.
- **Un titular es lo que un medio reporta, no un hecho.** Su tipo es `declaración`. `hecho` solo para datos oficiales (`IND-`, `SIS-`, `SBP-`) o conteos ("N medios reportan…").
- Generación en **dos pasos**: primero afirmaciones citadas y validadas; después cada sección se redacta por separado usando solo esas afirmaciones.
- El guion nunca describe material visual como existente: solo `[VISUAL: a definir por producción]`.
- Tipos de afirmación: **hecho** (oficial o conteo) · **declaración** (atribuida a un medio) · **inferencia** (cita sus afirmaciones base, sin datos nuevos) · **hipótesis** (condicional, sin datos nuevos). Las comillas son siempre literales.
- Los campos exactos de cada salida (paquete editorial, paquete de investigación, boletín bancario) están en `docs/salidas.md`. No agregar ni quitar campos.
- **La acción de la ficha decide qué se genera**: sin evidencia suficiente no hay guion ni copy, solo paquete de investigación.
- **Restricción común del reto (D-51):** toda salida (ficha, borrador, consulta, boletín, exportación) lleva la leyenda de alcance: **"basado únicamente en titular/metadatos"**, o "basado en titular, descripción del RSS y metadatos; no se leyó el artículo completo" si se usó la descripción. **Nunca simular haber leído el artículo** ni atribuirle detalles que no estén en la evidencia. Frases prohibidas en `config/restricciones.yaml`.
- El LLM no tiene herramientas ni acciones disponibles. Solo produce texto estructurado.
- Proveedor por configuración (`LLM_PROVIDER`), nunca hardcodeado. Durante el evento **DeepSeek es el único proveedor de generación** (D-94, D-95; `LLM_PROVIDER=deepseek`), con el tope de costo de D-67. Ollama (`qwen3.5:9b`, E0-07) sigue soportado por configuración pero está apagado y no se usa: era demasiado lento (≈ 2 min por paquete).
- Embeddings **siempre locales**.
- Puntaje, estado de evidencia, **ficha** y validación son **código determinista**, no LLM.
- **Ningún número mágico en `src/`**: pesos, umbrales y ventanas viven en `config/*.yaml`.
- Todo YAML de `config/` se carga con `src.configuracion` y se valida con un modelo pydantic que prohíbe claves desconocidas (D-79).
- Ningún `if modalidad == ...` en `src/`: las diferencias entre modalidades van en YAML, plantillas y reglas del validador.
- **Revisión humana (E1-16, D-46 a D-50):** las acciones, transiciones, motivos de descarte y revisores viven en `config/revision.yaml`. El botón se llama **«Aprobar como borrador»** y la ficha aprobada conserva la marca BORRADOR. `casos`, `versiones` y `revisiones` (en `data/revision.duckdb`) son de **solo agregar**: no hay `UPDATE` ni `DELETE`, y el estado actual es la última fila. Regenerar nunca sobrescribe una versión corregida. La ficha que se revisó queda guardada (`fichas_revisadas`) y se **exporta desde ahí**, no desde `senales.duckdb`; la demo exporta a `outputs/demo/`; un `CASO-` nunca se reutiliza (ver `docs/notion.md`). Todo texto corregido pasa por `src/validador.py` (vía `revalidar_correccion`) y la persona confirma cada advertencia. **No hay autenticación** (el revisor se elige de la lista): limitación declarada, no un control de seguridad. Lo que el reto exige a una persona (la revisión editorial) lo sigue haciendo una persona.

## Seguridad

- Secretos y configuración local solo en `local.env` (ignorado por git; D-77). En el repo, solo `.env.example` con nombres de variables vacíos.
- No imprimir ni registrar claves, tokens ni prompts con secretos en logs, tests o capturas.
- `data/demo.duckdb` (snapshot + casos sintéticos marcados) **nunca** se usa para calcular métricas.
- **Nada con redistribución restringida entra al repositorio ni al paquete de entrega** (descripciones del RSS, `socialimage`, extractos): de esas fuentes solo metadatos y la receta (D-72) (salvo la SBP, versionada por D-116 con riesgo aceptado).
- **Nunca leer, abrir ni buscar el benchmark reservado** (vive fuera del repo). Solo existe `benchmark/benchmark_dev.jsonl`.
- No crear perfiles de personas ni agrupar por persona. Las acusaciones se atribuyen como declaraciones; **nunca** como hecho, inferencia ni hipótesis (D-68).
- Causalidad solo si está literal en la fuente o en una hipótesis condicional (D-68).
- Los logs redactan cualquier valor de variables sensibles (`*_KEY`, `*_TOKEN`, `*_SECRET`) (D-69).
- Proveedor de pago con tope de costo (D-67); al alcanzarlo la generación **se detiene** con un error explícito (`TopeDeCostoAlcanzado`), sin volver a un modelo local (D-95). D-98: el tope es solo una guarda (USD 100 / 200 M tokens); el límite real es el saldo, y un HTTP 402 (`SaldoAgotado`) detiene la generación sin reintento. Sin red, los borradores salen **solo de la caché** (`data/cache_llm/`, E1-14; `docs/fallback.md`). Los embeddings siguen siendo locales.
- **Una alerta es una invitación a investigar.** Ni tono, ni volumen, ni repetición equivalen a fraude, pérdida o verdad comprobada.

## Lo que NUNCA se construye

- Botón, función o estado "publicar". El estado máximo es **"aprobado como borrador"**. La tabla `revisiones` es de solo agregar.
- Etiquetas de verdadero/falso, detección de fake news, fraude, solvencia o riesgo de crédito.
- Métricas de rating, audiencia o conversión.
- Scraping de artículos, paywalls o datos personales.
- Audio, video, clonación de voz o integraciones transaccionales.
- En banca: recomendaciones de compra/venta, pérdidas, impagos, exposición de cartera o scores de clientes.

## Convenciones de código

- Python 3.11, type hints en funciones públicas, docstrings y nombres en español.
- La ficha es un modelo pydantic (`Ficha`) que se renderiza en Streamlit, en Markdown (Jinja2) y en `fichas.jsonl`.
- Funciones puras donde se pueda; `logging`, no `print`, salvo en CLIs.
- Cada módulo de `src/` ejecutable con `python -m src.<modulo>` cuando la spec lo pida.
- **Todo número nuevo** (umbral, peso, límite) se agrega a `docs/parametros.md` con su origen (PDF · práctica · calibrado · supuesto) y cómo se valida.
- Toda proporción reportada lleva su n y su intervalo de confianza del 95 %. Cómo se mide cada métrica: `docs/protocolo_evaluacion.md`.
- Toda regla nueva lleva su test. Nunca debilitar un assert para que una prueba pase.
- Dependencias con **Poetry**: `poetry add <paquete>` (o `poetry add --group dev <paquete>`), justificadas en el plan. `poetry.lock` siempre se versiona. Nunca `pip install` suelto.

## Definición de terminado (todas las tareas)

- [ ] Se cumplen todos los puntos de "Listo cuando" de la spec, con salida mostrada.
- [ ] `pytest -v` pasa completo, no solo el test nuevo.
- [ ] Sin secretos, sin números mágicos, sin `if modalidad`.
- [ ] Revisión de `docs/REVISION.md` hecha.

Revisión de código: @docs/REVISION.md
