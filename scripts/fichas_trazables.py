"""C-01 · Cinco fichas trazables: selecciona por regla, arma las fichas, comprueba su trazabilidad y (opcional) las abre como casos.

Uso::

    poetry run python -m scripts.fichas_trazables            # selecciona, arma, comprueba y escribe outputs/fichas_trazables/ (solo lectura de la base)
    poetry run python -m scripts.fichas_trazables --casos    # además abre cada ficha como CASO- (revisión provisional del asistente, D-112) y la exporta

La regla de selección y la resolución de citas viven en ``config/fichas_trazables.yaml``. Todo es BORRADOR. El comando termina con código
1 si alguna comprobación falla. Para llevar los casos a Notion: ``poetry run python -m src.exportar --caso CASO-00N --notion`` (lo hace una persona con token).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src import db
from src.configuracion import RAIZ, ConfigFichasTrazables, cargar_fichas_trazables, cargar_normalizacion, cargar_revision
from src.esquemas import Ficha
from src.exportar import escribir_csv, exportar_caso, sincronizar_con_notion
from src.ficha import a_markdown, construir_ficha
from src.generacion import SinBorrador, generar_paquete
from src.revision import ErrorDeRevision, Revisiones, huellas_de_exportacion, ruta_de_revision
from src.trazabilidad import (
    REGLAS,
    Candidato,
    ErrorDeTrazabilidad,
    ResultadoFicha,
    Resolutor,
    candidatos,
    informe,
    seleccionar,
    verificar_ficha,
)

ESTADO_EN_REVISION = "en revisión"


def _borrador_en_cache(id_grupo: str, modalidad: str, base: Path) -> Any | None:
    """El paquete de la caché de generación (``solo_cache``: nunca llama a un proveedor ni gasta), o ``None``."""
    try:
        return generar_paquete(id_grupo, modalidad, solo_cache=True, base=base)
    except SinBorrador:
        return None


def revisar_provisionalmente(rev: Revisiones, c: Candidato, ficha: Ficha, cfg: ConfigFichasTrazables, base: Path) -> str:
    """Abre el grupo como caso (si no lo estaba) y, si sigue «en revisión», aplica la acción de ``cfg.revision`` según su estado de
    evidencia. Idempotente: un caso que ya avanzó no se toca. Siempre con el revisor provisional del asistente (D-101, D-112)."""
    modalidad = cfg.modalidad
    caso = rev.caso_de_grupo(c.id_grupo, modalidad)
    if caso is None:
        paquete = _borrador_en_cache(c.id_grupo, modalidad, base)
        caso = rev.abrir(c.id_grupo, modalidad, cfg.revision.revisor, paquete=paquete, comentario=cfg.revision.comentario)
    if rev.estado(caso.id_caso) == ESTADO_EN_REVISION:
        accion = cfg.revision.accion_por_estado[c.estado]
        if accion == "aceptar":
            rev.aceptar(caso.id_caso, cfg.revision.revisor, cfg.revision.comentario)
        else:
            vacios = [v.codigo for v in (*ficha.falta_comprobar.principales, *ficha.falta_comprobar.otros)]
            rev.pedir_evidencia(caso.id_caso, cfg.revision.revisor, vacios, cfg.revision.comentario, motivo=cfg.revision.comentario)
    return caso.id_caso


def indice_markdown(cfg: ConfigFichasTrazables, filas: list[dict[str, Any]], inf: dict[str, Any], marca: dict[str, Any]) -> str:
    """El índice legible: regla de selección, las cinco fichas y los conteos por comprobación (n e IC 95 %)."""
    L = ["# Cinco fichas trazables (C-01)", "", "**BORRADOR · requiere revisión**", "", f"> {cfg.textos.aviso_provisional}", "",
         cfg.textos.aviso_corrida.format(**marca), "", "## Regla de selección (`config/fichas_trazables.yaml`)", ""]
    s = cfg.seleccion
    L += [f"- Se recorre el ranking oficial (posición 1 = mayor P) y se toman, por estado de evidencia, los primeros: {', '.join(f'{k} {v}' for k, v in s.cupos.items())}.",
          f"- Mínimo {s.minimo_total} fichas, al menos {s.minimo_insuficiente} con evidencia insuficiente (PDF sección 5). Si un estado no alcanza su cupo, se completa con el ranking: {'sí' if s.completar_con_ranking else 'no'}.", "",
          "## Las fichas", "", "| Caso | Grupo | Posición | P | Estado de evidencia | Titular central | Revisión | Borrador | Comprobaciones | Fallos |", "|---|---|---|---|---|---|---|---|---|---|"]
    for f in filas:
        L.append(f"| {f['id_caso'] or '—'} | {f['id_grupo']} | {f['posicion']} | {f['puntaje']:.2f} | {f['estado']} | {f['titular']} | {f['revision']} | {f['borrador']} | {f['ok']}/{f['n']} | {f['fallos']} |")
    L += ["", "## Comprobaciones (proporciones con n e IC 95 % de Wilson)", "", "| Comprobación | ok / n | Proporción | IC 95 % |", "|---|---|---|---|"]
    for regla in REGLAS:
        r = inf["por_regla"][regla]
        if not r["n"]:
            L.append(f"| `{regla}` | 0 / 0 | no aplica | — |")
            continue
        L.append(f"| `{regla}` | {r['ok']} / {r['n']} | {r['proporcion']:.0%} | [{r['ic95'][0]:.0%}, {r['ic95'][1]:.0%}] |")
    L += ["", f"Resultado: **{'todas las comprobaciones pasan' if inf['todo_ok'] else 'HAY FALLOS (ver trazabilidad.json)'}** · detalle por cita en `{cfg.archivos.informe}`.", ""]
    return "\n".join(L)


def principal(argv: list[str] | None = None) -> int:
    cfg = cargar_fichas_trazables()
    parser = argparse.ArgumentParser(description="C-01: cinco fichas trazables (selección por regla, comprobación de trazabilidad y casos provisionales)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--casos", action="store_true", help="abre cada ficha como CASO- con la revisión provisional del asistente y la exporta (Markdown, CSV de Notion y fichas.jsonl)")
    parser.add_argument("--revision", type=Path, default=None, help="por defecto data/revision.duckdb")
    parser.add_argument("--salida", type=Path, default=None, help=f"por defecto {cfg.archivos.carpeta}")
    parser.add_argument("--notion", action="store_true", help="con --casos: además sincroniza cada caso con «Casos y evidencias» por la API (E3-03; necesita NOTION_TOKEN en local.env; sin él solo avisa)")
    args = parser.parse_args(argv)
    if args.notion and not args.casos:
        parser.error("--notion exige --casos")
    if not args.base.exists():
        print(f"ERROR: no existe {args.base}: ejecute primero el pipeline (`poetry run python -m src.puntaje`)", file=sys.stderr)
        return 1
    carpeta = args.salida or RAIZ / cfg.archivos.carpeta
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in (*carpeta.glob("GRP-*.md"), *carpeta.glob("CASO-*.md"), carpeta / cargar_revision().exportacion.csv):   # esta corrida reemplaza a la anterior
        viejo.unlink(missing_ok=True)

    con = db.conectar(args.base, solo_lectura=True)
    try:
        elegidos = seleccionar(candidatos(con, cfg.modalidad), cfg)
        fichas = {c.id_grupo: construir_ficha(c.id_grupo, cfg.modalidad, con, emb=None) for c in elegidos}
        resolutor = Resolutor(con, cfg)
        cfg_rev = cargar_revision()
        rev = Revisiones(args.revision or ruta_de_revision(False, cfg_rev), args.base, cfg_rev, huellas=huellas_de_exportacion(False, cfg_rev, RAIZ)) if args.casos else None

        resultados: list[ResultadoFicha] = []
        filas: list[dict[str, Any]] = []
        for c in elegidos:
            ficha = fichas[c.id_grupo]
            id_caso = estado = None
            extra: list[str] = []
            exportacion = None
            fila_notion: dict[str, str] | None = None
            provisional: bool | None = None
            if rev is not None:
                id_caso = revisar_provisionalmente(rev, c, ficha, cfg, args.base)
                exportacion = e = exportar_caso(rev, id_caso)
                (carpeta / f"{id_caso}.md").write_text(e.markdown, encoding="utf-8")                      # el caso tal como se exporta a Notion
                escribir_csv(carpeta / cfg_rev.exportacion.csv, e.fila, cfg_rev.exportacion.columnas)    # las cinco filas de «Casos y evidencias» de esta corrida
                ficha = rev.ficha_revisada(id_caso) or ficha        # lo que se exporta es la ficha que se revisó
                estado, provisional = rev.estado(id_caso), rev.vigente_provisional(id_caso)
                extra, fila_notion = [e.markdown, *e.fila.values()], e.fila
            if rev is None:
                (carpeta / f"{c.id_grupo}.md").write_text(a_markdown(ficha), encoding="utf-8")
            r = verificar_ficha(ficha, resolutor, cfg, id_caso=id_caso, estado_revision=estado, textos_extra=extra, fila_notion=fila_notion,
                                revision_provisional=provisional, marca_provisional=cfg_rev.textos.marca_provisional if rev else None)
            resultados.append(r)
            if args.notion and exportacion is not None and sincronizar_con_notion(exportacion) != 0:
                print(f"ERROR: {id_caso} no se sincronizó con Notion", file=sys.stderr)
                return 1
            ok, n = sum(r.conteo(x)[0] for x in REGLAS), sum(r.conteo(x)[1] for x in REGLAS)
            filas.append({
                "id_caso": id_caso, "id_grupo": c.id_grupo, "posicion": c.posicion, "puntaje": c.puntaje, "estado": c.estado,
                "titular": ficha.que_se_reporta.titular_central.titular.replace("|", "\\|"),
                "revision": (rev.estado_rotulado(id_caso) if rev and id_caso else "sin caso (dry-run)"),
                "borrador": (f"versión {v.version}" if rev and id_caso and (v := rev.version_actual(id_caso)) else cfg.textos.sin_borrador),
                "ok": ok, "n": n, "fallos": len(r.fallos()),
            })
        marca = {"version_reglas": fichas[elegidos[0].id_grupo].puntaje.version_reglas, "fecha_referencia": fichas[elegidos[0].id_grupo].puntaje.fecha_referencia}
    except (ErrorDeTrazabilidad, ErrorDeRevision, db.ModalidadDistinta, LookupError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    inf = informe(resultados, cfg)
    inf = {
        "tarea": "C-01", "borrador": True, "juicio_humano": False, "aviso": cfg.textos.aviso_provisional,
        "generado_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "modalidad": cfg.modalidad, **marca,
        "seleccion": {"cupos": cfg.seleccion.cupos, "minimo_total": cfg.seleccion.minimo_total, "minimo_insuficiente": cfg.seleccion.minimo_insuficiente,
                      "elegidas": [{"id_grupo": f["id_grupo"], "posicion": f["posicion"], "puntaje": round(f["puntaje"], 2), "estado": f["estado"], "id_caso": f["id_caso"]} for f in filas]},
        "con_casos": rev is not None, **inf,
    }
    (RAIZ / cfg.archivos.informe if args.salida is None else carpeta / "trazabilidad.json").write_text(json.dumps(inf, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RAIZ / cfg.archivos.indice if args.salida is None else carpeta / "indice.md").write_text(indice_markdown(cfg, filas, inf, marca), encoding="utf-8")
    for f in filas:
        print(f"{f['id_caso'] or '-':9} {f['id_grupo']} pos {f['posicion']:>2} P {f['puntaje']:6.2f} {f['estado']:12} comprobaciones {f['ok']}/{f['n']} fallos {f['fallos']}")
    print(f"{inf['n_fichas']} fichas · {'TODO OK' if inf['todo_ok'] else 'HAY FALLOS'} · {carpeta}")
    return 0 if inf["todo_ok"] else 1


if __name__ == "__main__":
    sys.exit(principal())
