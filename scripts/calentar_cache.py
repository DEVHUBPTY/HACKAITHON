"""Calienta (o verifica) la caché de borradores para la demo sin internet (E1-14, T10).

    poetry run python -m scripts.calentar_cache                       # top de la bandeja + los grupos del guion de la demo (con red)
    poetry run python -m scripts.calentar_cache --grupos GRP-… GRP-…  # solo esos
    poetry run python -m scripts.calentar_cache --verificar           # sin red: qué grupos tienen su borrador completo en la caché

Genera con el proveedor de ``local.env`` (``LLM_PROVIDER=deepseek``, D-94/D-95), guarda cada respuesta en ``data/cache_llm/`` y muestra el
costo estimado (cota superior, D-97). Con ``--verificar`` nunca se crea un proveedor ni se abre una conexión. Se detiene con un mensaje
claro si se alcanza el tope de costo o se agota el saldo (D-98); lo ya guardado queda disponible.

Re-calentar después de cambiar un prompt, el modelo, la ficha o el validador (E1-13): la clave cambia y las respuestas viejas no se usan.
E1-14 implementa lo mínimo del ``calentar_cache`` que C-06 prevé; C-06 puede ampliarlo (base de demo, capturas).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from src.cache import CacheLlm, SinBorrador, red_disponible
from src.configuracion import RAIZ, MODALIDADES, cargar_cache, cargar_generacion, cargar_normalizacion
from src.llm.costo import RegistroCosto, TopeDeCostoAlcanzado
from src.llm.proveedor import ErrorProveedor


def grupos_por_defecto(base: Path, modalidad: str) -> list[str]:
    """Top de la bandeja (``calentamiento.top_bandeja``) y los grupos del guion de la demo, sin repetir y en ese orden."""
    from src import db
    from src import interfaz as ui

    cfg = cargar_cache().calentamiento
    con = db.conectar(base, solo_lectura=True)
    try:
        top = [f.id_grupo for f in ui.leer_bandeja(con, modalidad)[: cfg.top_bandeja]]
        existentes = {f.id_grupo for f in ui.leer_bandeja(con, modalidad)}
    finally:
        con.close()
    guion = (RAIZ / cfg.guion_demo).read_text(encoding="utf-8") if (RAIZ / cfg.guion_demo).exists() else ""
    demo = [x for x in re.findall(cfg.patron_id_grupo, guion) if x in existentes]
    return list(dict.fromkeys([*demo, *top]))


def estado_de(id_grupo: str, modalidad: str, base: Path, cache: CacheLlm) -> str:
    """``completo``, ``parcial (…)``, ``sin borrador: <por qué>`` (sin caché, desajuste de proveedor o validación) o ``no genera: …``."""
    from src.generacion import generar_paquete

    try:
        p = generar_paquete(id_grupo, modalidad, solo_cache=True, base=base, cache=cache)
    except SinBorrador as exc:
        return f"no genera: {exc}" if exc.por_accion else f"sin borrador: {exc}"
    faltan = [v.referencia for v in p.vacios if v.motivo == cache.cfg.textos.sin_cache_grupo]
    return "completo" if not faltan else f"parcial (faltan: {', '.join(faltan)})"


def principal(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calienta o verifica la caché de borradores (E1-14)")
    parser.add_argument("--grupos", nargs="*", help="GRP-… a generar; por defecto el top de la bandeja y los grupos del guion de la demo")
    parser.add_argument("--modalidad", choices=MODALIDADES, default="editorial")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--verificar", action="store_true", help="solo lee la caché (sin red, sin proveedor); sale con 1 si algo falta")
    parser.add_argument("--refrescar", action="store_true", help="vuelve a llamar al proveedor aunque haya respuesta guardada")
    args = parser.parse_args(argv)
    from src.registro import configurar_logging

    configurar_logging()
    if not args.base.exists():
        print(f"ERROR: no existe {args.base}", file=sys.stderr)
        return 1
    grupos = args.grupos or grupos_por_defecto(args.base, args.modalidad)
    cache = CacheLlm()
    if args.verificar:
        estados = {g: estado_de(g, args.modalidad, args.base, cache) for g in grupos}
        for g, e in estados.items():
            print(f"{g}  {e}")
        faltan = [g for g, e in estados.items() if e != "completo" and not e.startswith("no genera")]
        print(f"\n{len(grupos) - len(faltan)} de {len(grupos)} grupos listos · {len(cache)} respuestas en {cache.carpeta.relative_to(RAIZ)}")
        return 1 if faltan else 0

    from src.cache import modo_offline
    from src.generacion import generar_paquete
    from src.llm.proveedor import crear_proveedor

    if modo_offline() or not red_disponible():
        print("ERROR: no hay red (o el modo offline está activo): no se puede generar. Use --verificar para revisar lo guardado.", file=sys.stderr)
        return 2
    try:
        proveedor = crear_proveedor()
    except ErrorProveedor as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    gen = cargar_generacion()
    registro = RegistroCosto(RAIZ / gen.tope_costo.registro)
    antes_usd, antes_tokens, antes_n = registro.usd, registro.tokens, len(cache)
    for g in grupos:
        try:
            p = generar_paquete(g, args.modalidad, solo_cache=False, base=args.base, proveedor=proveedor, cache=cache, refrescar=args.refrescar)
            motivos = [f"{v.referencia}: {v.motivo[:80]}" for v in p.vacios if v.origen == "seccion"]
            print(f"{g}  {p.accion}  {'sin vacíos' if not motivos else 'vacíos: ' + '; '.join(motivos)}")
        except SinBorrador as exc:
            print(f"{g}  sin borrador: {exc}")
        except TopeDeCostoAlcanzado as exc:
            print(f"\nDETENIDO en {g}: {exc}", file=sys.stderr)
            return 3
        except ErrorProveedor as exc:
            print(f"{g}  ERROR del proveedor: {exc}", file=sys.stderr)
    despues = RegistroCosto(RAIZ / gen.tope_costo.registro)
    print(
        f"\n{len(cache) - antes_n} respuestas nuevas · {len(cache)} en la caché · costo de esta corrida (estimado, cota superior): "
        f"USD {despues.usd - antes_usd:.4f} · {despues.tokens - antes_tokens} tokens · acumulado USD {despues.usd:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
