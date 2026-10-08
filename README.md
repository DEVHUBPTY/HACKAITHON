# HackIAthon · De la señal a la decisión

## Descripción

Copiloto que convierte titulares públicos (TVN RSS y GDELT) y datos oficiales (Banco Mundial, USGS, SBP) en una bandeja de temas priorizados, fichas de evidencia y borradores para una decisión humana.

- Modalidad principal: editorial (TVN). Extensión: banca, como configuración sobre el mismo núcleo.
- Todo lo que produce el sistema es un **borrador**. Nada se publica.
- Principio rector: no afirmar más de lo que la evidencia permite, y demostrarlo cita por cita.

Las reglas del proyecto están en `CLAUDE.md`; las tareas, en `specs/`.

## Instalación (con Poetry)

Requisitos: Python 3.11 y [Poetry](https://python-poetry.org/).

```bash
poetry env use python3.11
poetry install            # instala las dependencias fijadas en poetry.lock
cp .env.example local.env # completar localmente; local.env no se versiona
```

Variables de `local.env`: `LLM_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `DEEPSEEK_API_KEY`. Nunca se registran valores de claves en los logs.

## Ejecución

La demo corre en local; no hay despliegue.

Disponibles hoy (receta del snapshot en `data/README.md`):

```bash
poetry run python -m scripts.extraer --todo          # extracción del snapshot (E0-04)
poetry run python -m scripts.validar_snapshot        # valida el snapshot contra la receta
poetry run python -m src.config --validar            # valida la configuración de config/
poetry run python -m src.carga                       # carga y validación de datos
poetry run python -m src.normalizacion               # crea data/senales.duckdb
poetry run python -m src.limpieza                    # limpia titulares y marca ruido
poetry run python -m scripts.catalogo                # catálogo de datos (outputs/catalogo.csv)
poetry run streamlit run eval/etiquetar.py           # etiquetado humano (E1-06; ver docs/etiquetado.md)
poetry run python -m eval.ruido                      # precisión y recall del filtro de ruido
poetry run python -m eval.validar_benchmark          # valida el benchmark de desarrollo
poetry run python -m eval.run_benchmark --split dev  # benchmark de desarrollo (E1-18)
poetry run python -m eval.ia_vs_baseline             # IA contra su línea base con IC (docs/ia_vs_baseline.md, E1-18)
poetry run python -m eval.sustento                   # validez de sustento, cuando una persona completó outputs/revision_sustento.csv (E1-18)
poetry run python -m scripts.pagina_metricas           # página de métricas generada desde outputs/ → outputs/pagina_metricas.md, lista para Notion (C-02)
poetry run python -m scripts.reproducir --verificar  # reconstruye todo desde data/raw/ y compara con el manifest (E1-20)
```

Previstos; cada uno estará disponible cuando se implemente su spec:

```bash
poetry run streamlit run app.py                      # interfaz (E1-15)
.venv/bin/streamlit run app.py -- --demo            # modo demo con data/demo.duckdb (C-06)
poetry run python -m scripts.verificar_offline       # chequeo antes del pitch (C-06)
```

## Reproducir en una máquina nueva (E1-20)

```bash
poetry install                                       # dependencias fijadas en poetry.lock (Python 3.11)
poetry run python -m scripts.reproducir --verificar  # un solo comando
```

Reconstruye todo desde `data/raw/` (conversión, validación, normalización, limpieza, clasificación, agrupación, contexto, puntaje, fichas, benchmark y métricas) y compara el SHA-256 de cada salida determinista con `data/manifest.json`. Imprime cada diferencia y sale con código 1 si hay alguna. Tarda ≈ 1 minuto.

- La primera vez, con red, se descargan los dos modelos de embeddings locales a `models/`; después no hace falta red (`HF_HUB_OFFLINE=1` la evita). No llama a ningún proveedor de LLM y no necesita clave.
- Los borradores del LLM salen de `data/cache_llm/` y se comparan como tales; nunca se regeneran. Sin caché pueden variar (se declara como limitación).
- RSS y GDELT no se versionan (D-72): sin esos crudos no se reconstruye `processed/` y se usa el versionado (también se declara). Cómo recuperarlos: `data/README.md`.
- Qué se compara, qué se excluye del hash y por qué, y los no determinismos encontrados: `docs/reproducibilidad.md`.

## Evaluación reservada (para el jurado)

El jurado corre su propio conjunto de consultas **sin internet** y sin copiarlo al repositorio. El runner solo **lee** el archivo y solo **escribe** en la carpeta de salida.

```bash
poetry run python -m eval.run_benchmark --archivo <ruta-al-archivo.jsonl> --salida <carpeta-de-salida>
```

- **Formato del archivo:** un objeto JSON por línea, el mismo de `benchmark/README.md`. Obligatorios: `id`, `tipo` (`respuesta_sustentada`, `contradiccion_ambiguedad`, `sin_respuesta` o `adversarial`), `consulta` y `debe_abstenerse` (booleano). `respuesta_esperada`, `ids_evidencia`, `sintetico` y `etiquetado_por` son opcionales; con `ids_evidencia` se calcula el Recall@5.
- **Requisitos:** `poetry install` y la base `data/senales.duckdb` (se crea con `poetry run python -m src.normalizacion`; el snapshot y su receta están en `data/README.md`). El modelo de embeddings es local y la consulta no usa LLM: no hace falta red ni clave. Si el modelo ya está en la caché local de Hugging Face, `HF_HUB_OFFLINE=1` evita cualquier intento de conexión.
- **Salidas en `<carpeta-de-salida>`:** `metricas.json` (cobertura de citas, abstención correcta, abstenciones incorrectas, Recall@5 semántica y BM25, latencia p50 y p95, tokens y costo; toda proporción con numerador, denominador, IC 95 % bootstrap y los IDs de los fallos), `consultas.jsonl` (la respuesta a cada consulta) y `revision_sustento.csv`.
- **Qué no calcula solo:** la validez de sustento necesita a una persona. El runner genera la muestra (30 afirmaciones elegidas al azar con semilla fija) en `revision_sustento.csv`; una persona completa la columna `veredicto` (`sustentada`, `parcial`, `no sustentada` o `tipo incorrecto`) y luego `poetry run python -m eval.sustento --archivo <carpeta-de-salida>/revision_sustento.csv --salida <carpeta-de-salida>/validez_sustento.json` calcula la validez con su intervalo. La columna `origen_juicio` dice quién juzgó (`humano` o `asistente_provisional`, D-101); un juicio provisional del asistente se rotula así en el JSON y en la consola, nunca como humano.
- En `metricas.json` el archivo se identifica por su nombre y su SHA-256, nunca por su ruta.

## Pruebas

```bash
poetry run pytest -v
```

## Datos

Fuentes: TVN RSS, GDELT, Banco Mundial, USGS y SBP. Solo se usan **metadatos** de noticias; no se descargan cuerpos de artículos, imágenes ni videos. `data/raw/` es inmutable y cada transformación se registra en `data/manifest.json`. Origen, URLs y condiciones de cada fuente: `docs/fuentes.md`.

## Licencias

Las licencias y condiciones de uso de los datos están en `docs/fuentes.md` y en el manifest (`data/manifest.json`). La licencia del código está pendiente de decisión del equipo.
