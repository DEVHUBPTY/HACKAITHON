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
from dataclasses import replace
from datetime import UTC, datetime
from collections.abc import Sequence
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
    Elegida,
    ErrorDeTrazabilidad,
    ResultadoFicha,
    Resolutor,
    candidatos,
    informe,
    seleccionar,
    verificar_ficha,
)

ESTADO_EN_REVISION = "en revisión"
ESTADO_APROBADO = "aprobado como borrador"
ESTADO_DESCARTADO = "descartado"


def _borrador_en_cache(id_grupo: str, modalidad: str, base: Path) -> Any | None:
    """El paquete de la caché de generación (``solo_cache``: nunca llama a un proveedor ni gasta), o ``None``."""
    try:
        return generar_paquete(id_grupo, modalidad, solo_cache=True, base=base)
    except SinBorrador:
        return None


def revisar_provisionalmente(rev: Revisiones, c: Any, ficha: Ficha, cfg: ConfigFichasTrazables, base: Path) -> str:
    """Abre el grupo como caso (si no lo estaba) y, si sigue «en revisión», aplica la acción de ``cfg.revision`` según su estado de
    evidencia. Idempotente: un caso que ya avanzó no se toca. Siempre con el revisor provisional del asistente (D-101, D-112)."""
    modalidad = cfg.modalidad
    caso = rev.caso_de_grupo(c.id_grupo, modalidad)
    if caso is None:
        paquete = _borrador_en_cache(c.id_grupo, modalidad, base)
        caso = rev.abrir(c.id_grupo, modalidad, cfg.revision.revisor, paquete=paquete, comentario=cfg.revision.comentario)
    if rev.estado(caso.id_caso) == ESTADO_DESCARTADO and _lo_descarto_c01(rev, caso.id_caso, cfg):
        rev.reabrir(caso.id_caso, cfg.revision.revisor, "Vuelve a ser la ficha de un caso de uso (D-118)", cfg.revision.comentario)
    if rev.estado(caso.id_caso) == ESTADO_EN_REVISION:
        accion = cfg.revision.accion_por_estado[c.estado]
        if accion == "aceptar":
            rev.aceptar(caso.id_caso, cfg.revision.revisor, cfg.revision.comentario)
        else:
            vacios = [v.codigo for v in (*ficha.falta_comprobar.principales, *ficha.falta_comprobar.otros)]
            rev.pedir_evidencia(caso.id_caso, cfg.revision.revisor, vacios, cfg.revision.comentario, motivo=cfg.revision.comentario)
    return caso.id_caso


def _lo_abrio_c01(rev: Revisiones, id_caso: str, cfg: ConfigFichasTrazables) -> bool:
    """El caso lo abrió esta tarea (primer paso: el revisor provisional con el comentario de C-01), no una persona."""
    historial = rev.historial(id_caso)
    return bool(historial) and historial[0].revisor == cfg.revision.revisor and historial[0].comentario == cfg.revision.comentario


def _lo_descarto_c01(rev: Revisiones, id_caso: str, cfg: ConfigFichasTrazables) -> bool:
    ultima = rev.historial(id_caso)[-1]
    return ultima.accion == "descartar" and ultima.revisor == cfg.revision.revisor and ultima.motivo == cfg.reemplazo.motivo


def retirar_reemplazadas(rev: Revisiones, elegidas: set[tuple[str, str]], cfg: ConfigFichasTrazables) -> list[str]:
    """D-118: los casos que abrió C-01 en una corrida anterior y la selección actual ya no elige se descartan con el motivo de
    ``cfg.reemplazo`` (provisional y rotulado, D-112). No se borra nada (registro de solo agregar) y un caso al que una persona ya
    le agregó su fila no se toca. Un caso aprobado se reabre antes (el descarte parte de «en revisión» o «requiere evidencia»).
    Devuelve los ``CASO-`` descartados en esta llamada. Idempotente."""
    retirados: list[str] = []
    for caso in rev.casos():
        if (caso.id_grupo, caso.modalidad) in elegidas or not _lo_abrio_c01(rev, caso.id_caso, cfg):
            continue
        if rev.estado(caso.id_caso) == ESTADO_DESCARTADO or not rev.vigente_provisional(caso.id_caso):
            continue
        if rev.estado(caso.id_caso) == ESTADO_APROBADO:
            rev.reabrir(caso.id_caso, cfg.revision.revisor, cfg.reemplazo.motivo, cfg.reemplazo.comentario)
        rev.descartar(caso.id_caso, cfg.revision.revisor, cfg.reemplazo.motivo, cfg.reemplazo.comentario)
        retirados.append(caso.id_caso)
    return retirados


def cabecera_caso_de_uso(e: Elegida) -> str:
    """La línea que rotula una ficha con su caso de uso y la regla que la eligió (para el Markdown de esta corrida)."""
    respaldo = " · criterio de respaldo declarado" if e.es_respaldo else ""
    return f"> **Caso de uso {e.caso_de_uso}** — {e.pregunta} · elegida por: {e.criterio_texto}{respaldo}\n\n"


def indice_markdown(cfg: ConfigFichasTrazables, filas: list[dict[str, Any]], inf: dict[str, Any], marca: dict[str, Any], reemplazados: Sequence[str] = ()) -> str:
    """El índice legible: regla de selección por caso de uso, las cinco fichas y los conteos por comprobación (n e IC 95 %)."""
    L = ["# Cinco fichas trazables (C-01)", "", "**BORRADOR · requiere revisión**", "", f"> {cfg.textos.aviso_provisional}", "",
         cfg.textos.aviso_corrida.format(**marca), "", "## Regla de selección (`config/fichas_trazables.yaml`, D-118)", ""]
    s = cfg.seleccion
    L += [f"- Una ficha por caso de uso del reto (PDF sección 4), en orden y sobre el ranking oficial (posición 1 = mayor P). Un grupo no se repite entre casos de uso.",
          f"- Mínimo {s.minimo_total} fichas, al menos {s.minimo_insuficiente} con evidencia insuficiente (PDF sección 5); si no hubiera ninguna, {s.garantia_insuficiente.caso_de_uso} se vuelve a elegir como insuficiente.", ""]
    L += ["| Caso de uso | Pregunta | Criterio (en orden; el primero con algún grupo manda) |", "|---|---|---|"]
    for cu in s.casos_de_uso:
        crit = f"grupo fijo `{cu.grupo}` ({cu.modalidad}); se reutiliza su CASO-" if cu.grupo else " → ".join(f"`{_resumen(c)}`" for c in cu.criterios)
        L.append(f"| {cu.id} | {cu.pregunta} | {crit} |")
    L += ["", "## Las fichas", "", "| Caso de uso | Caso | Grupo | Posición | P | Estado de evidencia | Elegida por | Titular central | Revisión | Borrador | Comprobaciones | Fallos |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in filas:
        L.append(f"| {f['caso_de_uso']} | {f['id_caso'] or '—'} | {f['id_grupo']} | {f['posicion']} | {f['puntaje']:.2f} | {f['estado']} | {f['elegida_por']} | {f['titular']} | {f['revision']} | {f['borrador']} | {f['ok']}/{f['n']} | {f['fallos']} |")
    if reemplazados:
        L += ["", f"Casos de la corrida anterior reemplazados (descartados con el motivo «{cfg.reemplazo.motivo}», provisional; siguen en el registro): {', '.join(reemplazados)}."]
    L += ["", "## Comprobaciones (proporciones con n e IC 95 % de Wilson)", "", "| Comprobación | ok / n | Proporción | IC 95 % |", "|---|---|---|---|"]
    for regla in REGLAS:
        r = inf["por_regla"][regla]
        if not r["n"]:
            L.append(f"| `{regla}` | 0 / 0 | no aplica | — |")
            continue
        L.append(f"| `{regla}` | {r['ok']} / {r['n']} | {r['proporcion']:.0%} | [{r['ic95'][0]:.0%}, {r['ic95'][1]:.0%}] |")
    L += ["", f"Resultado: **{'todas las comprobaciones pasan' if inf['todo_ok'] else 'HAY FALLOS (ver trazabilidad.json)'}** · detalle por cita en `{cfg.archivos.informe}`.", ""]
    return "\n".join(L)


def _resumen(c: Any) -> str:
    partes = [f"{k}={v}" for k, v in c.model_dump(exclude_none=True).items()]
    return ", ".join(partes) if partes else "primero del ranking"


def principal(argv: list[str] | None = None) -> int:
    cfg = cargar_fichas_trazables()
    parser = argparse.ArgumentParser(description="C-01: cinco fichas trazables (una por caso de uso, comprobación de trazabilidad y casos provisionales)")
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
    cfg_rev = cargar_revision()
    for viejo in (*carpeta.glob("GRP-*.md"), *carpeta.glob("CASO-*.md"), carpeta / cfg_rev.exportacion.csv):   # esta corrida reemplaza a la anterior
        viejo.unlink(missing_ok=True)

    con = db.conectar(args.base, solo_lectura=True)
    try:
        elegidas = seleccionar(candidatos(con, cfg.modalidad), cfg)
        resolutor = Resolutor(con, cfg)
        # El registro de revisión se lee siempre (el grupo fijo de CU-05 sale de su caso ya revisado); solo se escribe con --casos.
        rev = Revisiones(args.revision or ruta_de_revision(False, cfg_rev), args.base, cfg_rev, huellas=huellas_de_exportacion(False, cfg_rev, RAIZ))
        reemplazados: list[str] = []
        if args.casos:
            reemplazados = retirar_reemplazadas(rev, {(e.id_grupo, e.modalidad or cfg.modalidad) for e in elegidas}, cfg)

        resultados: list[ResultadoFicha] = []
        filas: list[dict[str, Any]] = []
        for e in elegidas:
            fijo = e.candidato is None
            id_caso = estado = None
            extra: list[str] = []
            exportacion = None
            fila_notion: dict[str, str] | None = None
            provisional: bool | None = None
            if fijo:                       # un caso ya revisado en otra modalidad: se reutiliza por referencia, no se reabre ni se renumera
                caso_fijo = rev.caso_de_grupo(e.id_grupo, str(e.modalidad))
                ficha = rev.ficha_revisada(caso_fijo.id_caso) if caso_fijo else None
                if caso_fijo is None or ficha is None:
                    raise ErrorDeTrazabilidad(f"{e.caso_de_uso}: no hay un caso revisado de {e.id_grupo} ({e.modalidad}); corra primero la tarea que lo revisó (E2-03)")
                id_caso = caso_fijo.id_caso
                posicion, puntaje, evidencia = ficha.puntaje.posicion, ficha.puntaje.puntaje, ficha.accion_recomendada.estado_evidencia
            else:
                c = e.candidato
                ficha = construir_ficha(c.id_grupo, cfg.modalidad, con, emb=None)
                posicion, puntaje, evidencia = c.posicion, c.puntaje, c.estado
            cabecera = cabecera_caso_de_uso(e)
            if args.casos:
                if not fijo:
                    id_caso = revisar_provisionalmente(rev, e.candidato, ficha, cfg, args.base)
                exportacion = x = exportar_caso(rev, id_caso)
                x = exportacion = replace(x, fila={**x.fila, "Caso de uso": e.caso_de_uso})   # D-118: el caso de uso sale de esta selección, no de una etiqueta del grupo
                escribir_csv(x.ruta_csv, x.fila, cfg_rev.exportacion.columnas)                  # el CSV de E1-16 y el de esta corrida llevan el mismo valor
                (carpeta / f"{id_caso}.md").write_text(cabecera + x.markdown, encoding="utf-8")   # el caso tal como se exporta a Notion
                escribir_csv(carpeta / cfg_rev.exportacion.csv, x.fila, cfg_rev.exportacion.columnas)   # las cinco filas de «Casos y evidencias» de esta corrida
                ficha = rev.ficha_revisada(id_caso) or ficha        # lo que se exporta es la ficha que se revisó
                estado, provisional = rev.estado(id_caso), rev.vigente_provisional(id_caso)
                extra, fila_notion = [x.markdown, *x.fila.values()], x.fila
            else:
                (carpeta / f"{e.id_grupo}.md").write_text(cabecera + a_markdown(ficha), encoding="utf-8")
                if fijo:
                    estado, provisional = rev.estado(id_caso), rev.vigente_provisional(id_caso)
            r = verificar_ficha(ficha, resolutor, cfg, id_caso=id_caso if (args.casos or fijo) else None, estado_revision=estado,
                                textos_extra=extra, fila_notion=fila_notion, revision_provisional=provisional if args.casos else None,
                                marca_provisional=cfg_rev.textos.marca_provisional if args.casos else None)   # la marca se comprueba contra lo exportado: solo con --casos
            resultados.append(r)
            if args.notion and exportacion is not None and sincronizar_con_notion(exportacion) != 0:
                print(f"ERROR: {id_caso} no se sincronizó con Notion", file=sys.stderr)
                return 1
            ok, n = sum(r.conteo(x)[0] for x in REGLAS), sum(r.conteo(x)[1] for x in REGLAS)
            filas.append({
                "caso_de_uso": e.caso_de_uso, "id_caso": id_caso, "id_grupo": e.id_grupo, "posicion": posicion, "puntaje": puntaje, "estado": evidencia,
                "elegida_por": e.criterio_texto + (" (respaldo declarado)" if e.es_respaldo else "") + (" (garantía de evidencia insuficiente)" if e.garantia else ""),
                "criterio": e.criterio, "respaldo": e.es_respaldo, "garantia": e.garantia, "reutilizado": fijo, "modalidad": e.modalidad or cfg.modalidad,
                "titular": ficha.que_se_reporta.titular_central.titular.replace("|", "\\|"),
                "revision": (rev.estado_rotulado(id_caso) if id_caso and (args.casos or fijo) else "sin caso (dry-run)"),
                "borrador": (f"versión {v.version}" if id_caso and (args.casos or fijo) and (v := rev.version_actual(id_caso)) else cfg.textos.sin_borrador),
                "ok": ok, "n": n, "fallos": len(r.fallos()),
            })
        if sum(f["estado"] == "insuficiente" for f in filas) < cfg.seleccion.minimo_insuficiente:
            raise ErrorDeTrazabilidad("ninguna de las fichas elegidas tiene evidencia insuficiente; el reto pide al menos una (sección 5)")
        primera = next(f for f in filas if not f["reutilizado"])
        puntaje_ref = construir_ficha(primera["id_grupo"], cfg.modalidad, con, emb=None).puntaje
        marca = {"version_reglas": puntaje_ref.version_reglas, "fecha_referencia": puntaje_ref.fecha_referencia}
    except (ErrorDeTrazabilidad, ErrorDeRevision, db.ModalidadDistinta, LookupError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    inf = informe(resultados, cfg)
    inf = {
        "tarea": "C-01", "decision": "D-118", "borrador": True, "juicio_humano": False, "aviso": cfg.textos.aviso_provisional,
        "generado_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "modalidad": cfg.modalidad, **marca,
        "seleccion": {"regla": "una ficha por caso de uso sobre el ranking oficial (config/fichas_trazables.yaml: seleccion)", "minimo_total": cfg.seleccion.minimo_total,
                      "minimo_insuficiente": cfg.seleccion.minimo_insuficiente,
                      "elegidas": [{k: (round(f[k], 2) if k == "puntaje" else f[k]) for k in ("caso_de_uso", "id_grupo", "id_caso", "posicion", "puntaje", "estado", "modalidad", "elegida_por", "criterio", "respaldo", "garantia", "reutilizado")} for f in filas],
                      "respaldos_usados": [f["caso_de_uso"] for f in filas if f["respaldo"]]},
        "reemplazados": reemplazados,
        "con_casos": args.casos, **inf,
    }
    (RAIZ / cfg.archivos.informe if args.salida is None else carpeta / "trazabilidad.json").write_text(json.dumps(inf, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RAIZ / cfg.archivos.indice if args.salida is None else carpeta / "indice.md").write_text(indice_markdown(cfg, filas, inf, marca, reemplazados), encoding="utf-8")
    for f in filas:
        print(f"{f['caso_de_uso']} {f['id_caso'] or '-':9} {f['id_grupo']} pos {f['posicion']:>2} P {f['puntaje']:6.2f} {f['estado']:12} comprobaciones {f['ok']}/{f['n']} fallos {f['fallos']}{' · respaldo' if f['respaldo'] else ''}")
    if reemplazados:
        print(f"reemplazados (D-118): {', '.join(reemplazados)}")
    print(f"{inf['n_fichas']} fichas · {'TODO OK' if inf['todo_ok'] else 'HAY FALLOS'} · {carpeta}")
    return 0 if inf["todo_ok"] else 1


if __name__ == "__main__":
    sys.exit(principal())
