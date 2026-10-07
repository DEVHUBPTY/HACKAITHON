# Modo offline y fallback (T10, E1-14)

PDF T10: *«Sin internet durante la demo: funcionar con snapshot y fallback documentado»*. Este documento es ese fallback.

## Qué funciona sin internet

Todo, **salvo generar borradores nuevos**:

| Etapa | Sin red | De dónde sale |
|---|---|---|
| Carga y calidad | Sí | `data/senales.duckdb` (snapshot) |
| Bandeja y ficha | Sí | Snapshot; los embeddings salen de `models/` (`HF_HUB_OFFLINE=1`) |
| Consulta (incluida la abstención) | Sí | Snapshot y embeddings locales |
| Paquete (borrador) | Sí, **solo los que ya están en la caché** | `data/cache_llm/` (respuestas generadas antes) |
| Borrador **nuevo** | No | Requiere DeepSeek y saldo |

La interfaz **nunca llama al LLM ni abre una conexión**: `config/interfaz.yaml` fija `generacion.solo_cache: true`. Ninguna fuente en vivo
(RSS, GDELT, Banco Mundial, USGS) se consulta durante la demo; los datos son el snapshot.

## Proveedor de generación

DeepSeek es el único proveedor (D-94, D-95). **No hay respaldo local**: Ollama está apagado y nunca se arranca ni se usa como fallback.
Sin caché y sin red, no hay borrador y la pantalla lo dice; no se inventa nada.

## La caché

- **Dónde:** `data/cache_llm/<clave>.json`, una respuesta del LLM por archivo, versionada en git para que la máquina de la demo la tenga.
- **Qué contiene:** la respuesta cruda (borrador), proveedor, modelo, versión del prompt y cifras de uso. **No** contiene prompts, evidencia,
  claves ni descripciones del RSS.
- **Clave:** SHA-256 de versión de la caché, proveedor, modelo, versión del prompt, temperatura y semilla, mensaje de sistema, mensaje de usuario
  (la evidencia de la ficha) y esquema. Si cambia la ficha, el prompt, el esquema o el modelo, la clave cambia y la respuesta vieja **no se usa**.
- **Se cachea cada llamada** (afirmaciones, cada grupo de secciones y cada reintento). Al leer se **vuelve a validar** todo: un validador más
  estricto se aplica a lo guardado.
- **Invalidar todo a mano:** subir `version_cache` en `config/cache.yaml`.

## Antes del pitch (con internet)

```bash
poetry run python -m scripts.calentar_cache              # top 10 de la bandeja + los GRP- de docs/demo.md
poetry run python -m src.puntaje --modalidad banca && poetry run python -m scripts.calentar_cache --modalidad banca   # boletines (E2-02): la base debe tener los puntajes de banca
poetry run python -m scripts.calentar_cache --grupos GRP-… GRP-…
poetry run python -m scripts.calentar_cache --refrescar  # vuelve a llamar aunque haya respuesta guardada
```

Muestra el costo estimado de la corrida (cota superior, D-97). Se detiene con un mensaje claro si se alcanza el tope de costo o **se agota el
saldo de DeepSeek (D-98, HTTP 402)**; lo ya guardado sigue disponible. Después, `git add data/cache_llm` para llevarlo a la máquina de la demo.

**Volver a calentar** después de cambiar un prompt, el modelo, la lógica de la ficha o el validador (E1-13): la clave cambia y las respuestas
viejas dejan de servir (aparecerían como «sin caché»).

## Verificar sin red (30 minutos antes)

```bash
poetry run python -m scripts.calentar_cache --verificar   # no crea proveedor ni abre conexiones; sale con 1 si falta algún grupo
poetry run pytest tests/test_t10_offline.py               # recorrido carga → bandeja → ficha → paquete con la red simulada caída
```

**En la máquina de la demo, antes de nada:** `local.env` con `LLM_PROVIDER=deepseek` (la clave no hace falta para leer la caché) y, si
se calentó con otro, el mismo `DEEPSEEK_MODEL`. La clave de la caché incluye proveedor y modelo. Si `LLM_PROVIDER` está vacío se usa
`proveedor_por_defecto` de `config/cache.yaml` (deepseek, D-94/D-95); si pide otro proveedor o modelo, `--verificar` y la pantalla *Paquete* dicen
«la caché se calentó con deepseek/… y local.env pide …» en vez de «no hay borrador». Correr `--verificar` **en esa máquina** (debe dar 12/12).

`HACKIATHON_OFFLINE=true` en `local.env` ensaya el modo offline con la red encendida: aunque haya red, no se llama al proveedor.

## Qué muestra la interfaz

| Situación | Pantalla *Paquete* |
|---|---|
| Borrador completo en caché | El paquete con la marca BORRADOR, la leyenda de alcance, cada oración con las afirmaciones en que se apoya y los vacíos |
| Solo algunos grupos de secciones en caché | Lo guardado, y las demás secciones vacías con el motivo «no hay borrador en caché para este grupo de secciones» |
| Borrador guardado que ya no pasa la validación vigente | Secciones vacías (o aviso) con «el borrador guardado ya no pasa la validación vigente: hay que volver a calentar la caché» |
| `local.env` pide otro proveedor o modelo que el de la caché | Aviso con el desajuste («se calentó con deepseek/… y local.env pide …») |
| Nada en caché | Aviso: «no hay borrador en caché para este grupo: la interfaz no espera al modelo ni usa la red.» |
| La acción no genera borrador (p. ej. «Archivar») | Aviso con el motivo de D-42 |
| Saldo agotado o tope de costo (solo al generar) | Mensaje del error; la caché sigue disponible |

## Plan B si todo falla

Capturas de respaldo (C-06) y las fichas en Notion. Los borradores del paquete siempre son borrador: ninguna salida se publica.
