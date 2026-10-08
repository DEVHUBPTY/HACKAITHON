"""C-06 · Chequeo antes del pitch: ¿la demo corre con el Wi-Fi apagado?

    poetry run python -m scripts.verificar_offline

No toca la red (las comprobaciones corren con las conexiones no locales bloqueadas y con ``HF_HUB_OFFLINE=1`` y
``TRANSFORMERS_OFFLINE=1``), no crea ningún proveedor de LLM y no escribe en ``data/``. Imprime ✓/✗ con una razón por
comprobación y sale con 1 si falla alguna obligatoria:

1. el modelo de embeddings se carga desde ``models/`` (local);
2. ``data/senales.duckdb`` existe, tiene puntajes y no es una base de demo; ``data/demo.duckdb`` existe (si falta, solo avisa);
3. los borradores están en la caché (``data/cache_llm/``), en editorial y en banca (copia de sesión de la base, D-132); son
   obligatorios los grupos que nombra el guion de la demo (``docs/demo.md``);
4. la app de Streamlit importa y dibuja su pantalla de entrada sin intentar ninguna conexión no local.

Ollama no se usa (D-94/D-95): DeepSeek es el único proveedor de generación y sin red los borradores salen solo de la caché.
El ensayo con el Wi-Fi apagado (C-04/T10) lo hace una persona y se registra en Notion: este script no lo reemplaza.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import os
import re
import socket
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts import calentar_cache
from src import corrida, db
from src.cache import CacheLlm
from src.configuracion import MODALIDADES, RAIZ, cargar_cache, cargar_clasificacion, cargar_interfaz, cargar_normalizacion

ESTADOS_LISTOS = ("completo", "con vacíos", "no genera")   # mismos que `calentar_cache --verificar`
VARIABLES_OFFLINE = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
COMANDO_DEMO = ".venv/bin/streamlit run app.py -- --demo"   # `poetry run` se traga el `--`
COMANDO_PREPARAR_DEMO = "poetry run python -m scripts.preparar_demo"
RECORDATORIO = "RECORDATORIO: el ensayo con el Wi-Fi apagado (C-04/T10) lo hace una persona y se registra en Notion; este chequeo no lo reemplaza."
OLLAMA = "Ollama: no se usa (D-94/D-95); DeepSeek es el único proveedor y sin red los borradores salen solo de la caché."


@dataclass(frozen=True)
class Resultado:
    nombre: str
    ok: bool
    detalle: str
    obligatoria: bool = True

    def linea(self) -> str:
        marca = "✓" if self.ok else ("✗" if self.obligatoria else "!")
        return f"{marca} {self.nombre}: {self.detalle}"


class ConexionBloqueada(OSError):
    """Alguien intentó una conexión no local mientras corría el chequeo."""


def _es_local(direccion: object) -> bool:
    if isinstance(direccion, (str, bytes, os.PathLike)):   # socket Unix
        return True
    host = direccion[0] if isinstance(direccion, tuple) and direccion else ""
    if isinstance(host, bytes):
        host = host.decode()
    if host in ("", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def sin_red(intentos: list[str] | None = None) -> Iterator[list[str]]:
    """Bloquea ``socket.connect`` (y su variante no bloqueante) hacia hosts que no sean locales y anota cada intento."""
    registro = intentos if intentos is not None else []
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def _vigilar(direccion: object) -> None:
        if not _es_local(direccion):
            registro.append(str(direccion))
            raise ConexionBloqueada(f"conexión no local bloqueada: {direccion}")

    def connect(self: socket.socket, direccion: object) -> None:
        _vigilar(direccion)
        return original(self, direccion)  # type: ignore[arg-type]

    def connect_ex(self: socket.socket, direccion: object) -> int:
        _vigilar(direccion)
        return original_ex(self, direccion)  # type: ignore[arg-type]

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    try:
        yield registro
    finally:
        socket.socket.connect = original  # type: ignore[method-assign]
        socket.socket.connect_ex = original_ex  # type: ignore[method-assign]


# ------------------------------------------------------------------ comprobaciones


def cargar_modelo_local() -> tuple[int, ...]:
    """Carga el modelo de embeddings activo solo desde ``models/`` (sin descargar) y devuelve la forma de un vector."""
    from src.embeddings import MotorSentenceTransformers

    cfg = cargar_clasificacion()
    vectores = MotorSentenceTransformers(cfg.modelos[cfg.modelo_activo], cfg).codificar(["verificación sin conexión"])
    return tuple(vectores.shape)


def comprobar_embeddings(cargar: Callable[[], tuple[int, ...]] | None = None) -> Resultado:
    cargar = cargar or cargar_modelo_local
    faltan = [v for v in VARIABLES_OFFLINE if os.environ.get(v) != "1"]
    if faltan:
        return Resultado("embeddings", False, f"el modo sin conexión no está activo ({', '.join(faltan)} != 1)")
    cfg = cargar_clasificacion()
    nombre = cfg.modelos[cfg.modelo_activo].id
    try:
        forma = cargar()
    except Exception as exc:  # noqa: BLE001  cualquier fallo de carga es «no está»
        return Resultado("embeddings", False, f"{nombre} no carga desde {cfg.carpetas.modelos}/: {str(exc)[:120]}")
    return Resultado("embeddings", True, f"{nombre} cargado desde {cfg.carpetas.modelos}/ (local), vector {forma}")


def comprobar_bases(base: Path, base_demo: Path) -> list[Resultado]:
    resultados: list[Resultado] = []
    if not base.exists():
        resultados.append(Resultado("base real", False, f"no existe {_rel(base)}; corra el pipeline (scripts.reproducir)"))
    elif db.es_base_de_demo(base):
        resultados.append(Resultado("base real", False, f"{_rel(base)} es una base de demo; las métricas y la bandeja real no deben usarla"))
    else:
        modalidades = calentar_cache.modalidades_de_la_base(base)
        if not modalidades:
            resultados.append(Resultado("base real", False, f"{_rel(base)} no tiene puntajes (corra `poetry run python -m src.puntaje`)"))
        else:
            resultados.append(Resultado("base real", True, f"{_rel(base)} con puntajes de {', '.join(modalidades)}, no es una base de demo"))
    if base_demo.exists():
        resultados.append(Resultado("base de demo", True, f"{_rel(base_demo)} existe para `--demo`", obligatoria=False))
    else:
        resultados.append(Resultado("base de demo", False, f"falta {_rel(base_demo)}; cree con `{COMANDO_PREPARAR_DEMO}`", obligatoria=False))
    return resultados


def _rel(ruta: Path) -> str:
    return str(ruta.relative_to(RAIZ)) if ruta.is_relative_to(RAIZ) else str(ruta)


def _grupos_del_guion(guion: Path) -> list[str]:
    cfg = cargar_cache().calentamiento
    texto = guion.read_text(encoding="utf-8") if guion.exists() else ""
    return list(dict.fromkeys(re.findall(cfg.patron_id_grupo, texto)))


def comprobar_borradores(
    base: Path,
    modalidades: Sequence[str] = MODALIDADES,
    guion: Path | None = None,
    cache: CacheLlm | None = None,
    grupos: Callable[[Path, str], list[str]] | None = None,
    estado: Callable[[str, str, Path, CacheLlm], str] | None = None,
    base_de: Callable[[Path, str], Path] | None = None,
) -> list[Resultado]:
    """Por modalidad: cuántos grupos tienen su borrador completo en la caché. Obligatorios: los grupos del guion de la demo."""
    cache = cache or CacheLlm()
    guion = guion or RAIZ / cargar_cache().calentamiento.guion_demo
    grupos = grupos or calentar_cache.grupos_por_defecto
    estado = estado or calentar_cache.estado_de
    base_de = base_de or corrida.base_de_modalidad
    del_guion = set(_grupos_del_guion(guion))
    resultados: list[Resultado] = []
    for m in modalidades:
        try:
            base_m = base_de(base, m)   # banca: copia de sesión re-puntuada (D-132); nunca escribe en `base`
            ids = grupos(base_m, m)
        except Exception as exc:  # noqa: BLE001
            resultados.append(Resultado(f"borradores ({m})", False, f"no se pudo leer la bandeja de {m}: {str(exc)[:120]}"))
            continue
        estados = {g: estado(g, m, base_m, cache) for g in ids}
        listos = [g for g, e in estados.items() if e.startswith(ESTADOS_LISTOS)]
        faltan_guion = [g for g in estados if g in del_guion and g not in listos]
        resumen = f"{len(listos)} de {len(estados)} grupos listos"
        if faltan_guion:
            detalle = "; ".join(f"{g}: {estados[g]}" for g in faltan_guion)
            resultados.append(Resultado(f"borradores ({m})", False, f"{resumen}; faltan los del guion: {detalle}"))
        else:
            en_guion = sum(1 for g in estados if g in del_guion)
            resultados.append(Resultado(f"borradores ({m})", True, f"{resumen} ({en_guion} del guion de la demo, todos listos) · {len(cache)} respuestas en la caché"))
    return resultados


def comprobar_app(base: Path, base_demo: Path, intentos: list[str] | None = None) -> Resultado:
    """Importa ``app.py`` y dibuja la pantalla de entrada con ``AppTest``; ninguna conexión no local puede salir."""
    from streamlit.testing.v1 import AppTest

    from src import interfaz as ui

    usar_demo = base_demo.exists()
    argv_anterior = sys.argv
    sys.argv = ["app.py", "--demo"] if usar_demo else ["app.py"]
    originales = (ui.modo_demo, ui.elegir_base)
    registro = intentos if intentos is not None else []
    try:
        ui.modo_demo = lambda argv=None: usar_demo   # type: ignore[assignment]
        ui.elegir_base = lambda d, c, base_normal=None: ((base_demo if usar_demo else base), None)   # type: ignore[assignment]
        with sin_red(registro):
            try:
                import streamlit as st

                st.cache_resource.clear()
                st.cache_data.clear()
                at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=cargar_interfaz().demo.espera_verificacion_s).run()
            except Exception as exc:  # noqa: BLE001
                return Resultado("app", False, f"app.py no arranca: {str(exc)[:120]}")
    finally:
        ui.modo_demo, ui.elegir_base = originales   # type: ignore[assignment]
        sys.argv = argv_anterior
    if registro:
        return Resultado("app", False, f"intentó {len(registro)} conexión(es) no local(es): {', '.join(registro[:3])}")
    if len(at.exception):
        return Resultado("app", False, f"la pantalla de entrada lanzó una excepción: {str(at.exception[0].value)[:120]}")
    if not (len(at.title) or len(at.header) or len(at.markdown)):
        return Resultado("app", False, "la pantalla de entrada no dibujó ningún elemento")
    modo = "modo demo" if usar_demo else "base real (no hay base de demo)"
    return Resultado("app", True, f"app.py arranca en {modo} y dibuja la pantalla de entrada sin conexiones no locales")


# ------------------------------------------------------------------ principal


def principal(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chequeo antes del pitch, sin red (C-06)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--base-demo", type=Path, default=RAIZ / cargar_interfaz().demo.ruta_base)
    args = parser.parse_args(argv)
    for variable in VARIABLES_OFFLINE:
        os.environ[variable] = "1"
    resultados: list[Resultado] = []
    with sin_red() as intentos:
        resultados.append(comprobar_embeddings())
        resultados.extend(comprobar_bases(args.base, args.base_demo))
        if args.base.exists():
            resultados.extend(comprobar_borradores(args.base))
        resultados.append(comprobar_app(args.base, args.base_demo, intentos))
    for r in resultados:
        print(r.linea())
    print(f"· {OLLAMA}")
    print(f"· Comando de la demo: {COMANDO_DEMO}")
    print(RECORDATORIO)
    fallas = [r for r in resultados if r.obligatoria and not r.ok]
    print(f"\n{'VERDE' if not fallas else 'ROJO'}: {len(fallas)} comprobación(es) obligatoria(s) fallida(s)")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(principal())
