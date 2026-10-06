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
```

Previstos; cada uno estará disponible cuando se implemente su spec:

```bash
poetry run streamlit run app.py                      # interfaz (E1-15)
poetry run streamlit run app.py -- --demo            # modo demo con data/demo.duckdb (C-06)
poetry run python -m scripts.verificar_offline       # chequeo antes del pitch (C-06)
poetry run python -m eval.run_benchmark --split dev  # benchmark de desarrollo (E1-18)
poetry run python -m scripts.reproducir --verificar  # reproduce y compara con el manifest (E1-20)
```

## Pruebas

```bash
poetry run pytest -v
```

## Datos

Fuentes: TVN RSS, GDELT, Banco Mundial, USGS y SBP. Solo se usan **metadatos** de noticias; no se descargan cuerpos de artículos, imágenes ni videos. `data/raw/` es inmutable y cada transformación se registra en `data/manifest.json`. Origen, URLs y condiciones de cada fuente: `docs/fuentes.md`.

## Licencias

Las licencias y condiciones de uso de los datos están en `docs/fuentes.md` y en el manifest (`data/manifest.json`). La licencia del código está pendiente de decisión del equipo.
