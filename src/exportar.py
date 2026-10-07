"""Exportación de fichas y borradores (Markdown, CSV de Notion y ``fichas.jsonl``) siempre como borrador · E1-16, D-50.

La app (DuckDB) es la fuente de verdad; Notion recibe **exportaciones manuales**. ``exportar_caso`` produce, para un ``CASO-``:

* un **Markdown** (Jinja2, ``templates/caso.md.j2``) con lo mismo que ve la persona en la ficha, la versión del borrador, el
  historial completo de la revisión y la leyenda de alcance (D-51);
* una **fila CSV** para la base *Casos y evidencias* de Notion, con las columnas **exactas** de esa base (menos las fórmulas ``P`` y
  ``Rango``, que Notion calcula). Si el caso ya se había exportado, su fila se **reemplaza** (idempotente por ``ID caso``) y la
  página de Notion se actualiza al importarla; ``--notion`` lo sincroniza por la API (E3-03, ``src/notion.py``);
* ``outputs/fichas.jsonl``: una línea por caso, con los campos del contrato y ``estado_revision`` = última fila de ``revisiones``.

Todo se marca BORRADOR, también un caso «aprobado como borrador». Las fechas de los datos son ISO 8601 UTC; la hora de Panamá solo
aparece en el texto que lee la persona (el Markdown).

Uso: ``poetry run python -m src.exportar --caso CASO-001 [--notion] [--revision data/revision.duckdb] [--base data/senales.duckdb]``
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from jinja2 import Environment, FileSystemLoader

from src.configuracion import RAIZ, ConfigRevision, cargar_interfaz, cargar_notion, leer_local_env, cargar_revision, cargar_temas, cargar_verificacion
from src.esquemas import ETIQUETA_BORRADOR, Ficha, RegistroFichasJsonl
from src.ficha import CARPETA_PLANTILLAS, a_registro, escapar_markdown, vista
from src.notion import ClienteNotion, ErrorNotion, SinConexion
from src.registro import redactar
from src.interfaz import hora_panama, rotulo_de_elemento, secciones_de_paquete
from src.revision import ErrorDeRevision, Fila, Revisiones, huellas_de_exportacion, ruta_de_revision, rutas_de_exportacion

PLANTILLA_CASO = "caso.md.j2"
FORMATO_FECHA = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Exportacion:
    id_caso: str
    ruta_markdown: Path
    ruta_csv: Path
    markdown: str
    fila: dict[str, str]
    actualizada: bool


def _version_texto(rev: Revisiones, id_caso: str) -> str:
    v = rev.version_actual(id_caso)
    return f"versión {v.version} ({v.origen})" if v else rev.cfg.exportacion.sin_borrador


def _texto_plano(lineas: Any) -> str:
    return "\n".join(l.texto for l in lineas)


def _recortar(texto: str, cfg: ConfigRevision) -> str:
    """Una propiedad de texto de Notion admite ``max_caracteres_texto``; lo que sobra queda en el cuerpo de la página."""
    maximo = cfg.exportacion.max_caracteres_texto
    marca = cfg.exportacion.marca_recorte
    return texto if len(texto) <= maximo else texto[: maximo - len(marca)].rstrip() + marca


def fila_notion(rev: Revisiones, id_caso: str, ficha: Ficha, ahora: datetime | None = None) -> dict[str, str]:
    """La fila CSV de *Casos y evidencias*: las columnas exactas de ``exportacion.columnas``, en ese orden."""
    cfg = rev.cfg
    caso = rev.caso(id_caso)
    historial = rev.historial(id_caso)
    ultima = historial[-1] if historial else None
    secciones = {s.clave: s for s in vista(ficha, cargar_verificacion()).secciones}
    tema = cargar_temas().temas.get(ficha.que_se_reporta.tema or "")
    comentario = next((f.comentario for f in reversed(historial) if f.comentario), "")
    c = ficha.puntaje.componentes
    valores: dict[str, str] = {
        "ID caso": id_caso,
        "Modalidad": cfg.exportacion.modalidades[caso.modalidad],
        "Tema": tema.nombre if tema else "",
        "Caso de uso": "",
        "Estado de revisión": (ultima.estado_nuevo if ultima else cfg.estado_inicial).capitalize(),
        "Estado de evidencia": ficha.accion_recomendada.estado_evidencia.capitalize(),
        "Acción recomendada": ficha.accion_recomendada.accion,
        **{k: f"{c[k].valor:g}" for k in ("R", "I", "U", "N", "E") if k in c},
        "Versión de reglas": ficha.puntaje.version_reglas,
        "Versión del borrador": _version_texto(rev, id_caso),
        "Alcance del texto": ficha.alcance,
        "Qué se reporta": _texto_plano(secciones["que_se_reporta"].lineas),
        "Quién lo reporta": _texto_plano(secciones["quien_lo_reporta"].lineas),
        "Qué está respaldado": _texto_plano(secciones["respaldado"].lineas),
        "Qué falta comprobar": _texto_plano(secciones["falta_comprobar"].lineas),
        "IDs de fuente": ", ".join(a_registro(ficha)["ids_fuente"]),
        "Revisor": (ultima.revisor + (f" · {cfg.textos.marca_provisional}" if rev.es_provisional(ultima.revisor, caso.modalidad) else "")) if ultima else "",
        "Comentario del revisor": comentario,
        "Fecha de revisión": ultima.fecha_utc if ultima else "",
        "Última exportación": (ahora or rev.ahora()).astimezone(UTC).strftime(FORMATO_FECHA),
    }
    faltan = [col for col in cfg.exportacion.columnas if col not in valores]
    if faltan:
        raise ErrorDeRevision(f"columnas de Notion sin valor: {faltan}")
    return {col: _recortar(valores[col], cfg) for col in cfg.exportacion.columnas}


def _fila_historial(f: Fila, cfg_ver: Any, revisor: str | None = None) -> dict[str, str]:
    return {
        "id_revision": str(f.id_revision),
        "fecha": hora_panama(f.fecha_utc, cfg_ver, con_zona=False),
        "accion": escapar_markdown(f.accion),
        "estado_anterior": escapar_markdown(f.estado_anterior),
        "estado_nuevo": escapar_markdown(f.estado_nuevo),
        "revisor": escapar_markdown(revisor or f"{f.revisor} ({f.rol})"),
        "version": "" if f.version is None else str(f.version),
        "motivo": escapar_markdown(f.motivo or "").replace("\n", " "),
        "comentario": escapar_markdown(f.comentario or "").replace("\n", " "),
    }


def a_markdown(rev: Revisiones, id_caso: str, ficha: Ficha, ahora: datetime | None = None) -> str:
    """Markdown del caso: la ficha tal como la ve la persona, el borrador vigente, el historial y la leyenda de alcance."""
    cfg_ver = cargar_verificacion()
    caso = rev.caso(id_caso)
    v = vista(ficha, cfg_ver)
    historial = rev.historial(id_caso)
    etiquetas = cargar_interfaz().paquete.etiquetas
    actual = rev.version_actual(id_caso)
    diferencias: list[dict[str, Any]] = []
    for f in historial:
        for x in f.diferencias:
            diferencias.append({"version": f.version, "clave": escapar_markdown(rotulo_de_elemento(x["clave"], etiquetas)), "antes": escapar_markdown(x["antes"]), "despues": escapar_markdown(x["despues"])})
    datos = {
        "id_caso": escapar_markdown(id_caso),
        "id_grupo": escapar_markdown(caso.id_grupo),
        "marca": ETIQUETA_BORRADOR,
        "estado": escapar_markdown(rev.estado_rotulado(id_caso)),
        "version_texto": _version_texto(rev, id_caso),
        "modalidad": rev.cfg.exportacion.modalidades[caso.modalidad],
        "alcance": escapar_markdown(ficha.alcance),
        "exportado": hora_panama((ahora or rev.ahora()).astimezone(UTC).strftime(FORMATO_FECHA), cfg_ver),
        "secciones": [
            {"titulo": s.titulo, "lineas": [{"texto": escapar_markdown(l.texto), "nivel": l.nivel} for l in s.lineas]} for s in v.secciones
        ],
        "borrador": [
            {"titulo": t, "parrafos": [escapar_markdown(p) for p in ps]}
            for t, ps in (secciones_de_paquete(actual.contenido, etiquetas) if actual else [])
        ],
        "sin_borrador": rev.cfg.exportacion.sin_borrador,
        "nota_historial": rev.cfg.textos.limitacion_historial,
        "historial": [_fila_historial(f, cfg_ver, rev.revisor_rotulado(f, caso.modalidad)) for f in historial],
        "diferencias": diferencias,
    }
    entorno = Environment(loader=FileSystemLoader(CARPETA_PLANTILLAS), autoescape=False, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)  # noqa: S701 - Markdown; el escape lo hace escapar_markdown
    return entorno.get_template(PLANTILLA_CASO).render(d=datos)


def escribir_csv(ruta: Path, fila: dict[str, str], columnas: list[str]) -> bool:
    """Agrega la fila al CSV o **reemplaza** la del mismo ``ID caso`` (idempotente). Devuelve ``True`` si ya existía."""
    filas: list[dict[str, str]] = []
    if ruta.exists():
        with ruta.open(encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
    existia = any(x["ID caso"] == fila["ID caso"] for x in filas)
    filas = [fila if x["ID caso"] == fila["ID caso"] else x for x in filas] if existia else [*filas, fila]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    return existia


def registro_jsonl(rev: Revisiones, id_caso: str, ficha: Ficha) -> dict[str, Any]:
    """El registro de ``fichas.jsonl`` de un caso, validado contra el esquema del contrato."""
    caso = rev.caso(id_caso)
    actual = rev.version_actual(id_caso)
    r = a_registro(ficha, id_caso, rev.estado(id_caso))
    r["version"] = actual.version if actual else None
    r["revision_provisional"] = rev.vigente_provisional(id_caso)  # D-112: el estado_revision del contrato no cambia; la marca va aparte
    RegistroFichasJsonl.model_validate({**r, "modalidad": caso.modalidad})
    return r


def escribir_fichas_jsonl(rev: Revisiones, ruta: Path) -> int:
    """Reescribe ``fichas.jsonl`` con los casos de ``rev`` (una línea cada uno, ordenados por ``CASO-``), cada uno desde **su ficha
    guardada** al revisarla: nunca se reconstruye desde ``senales.duckdb``, así que un caso huérfano no rompe a los demás (B2, M2).
    Devuelve cuántas líneas escribió."""
    lineas = []
    for caso in rev.casos():
        if (ficha := rev.ficha_revisada(caso.id_caso)) is not None:
            lineas.append(json.dumps(registro_jsonl(rev, caso.id_caso, ficha), ensure_ascii=False, sort_keys=True))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text("".join(f"{l}\n" for l in lineas), encoding="utf-8")
    temporal.replace(ruta)
    return len(lineas)


def exportar_caso(rev: Revisiones, id_caso: str, carpeta: Path | None = None, ruta_jsonl: Path | None = None) -> Exportacion:
    """Escribe el Markdown y la fila CSV **solo del caso pedido** (y regenera ``fichas.jsonl`` desde las fichas guardadas).

    Sale de la ficha que una persona revisó (``Revisiones.ficha_revisada``), no de la base de señales de hoy. Volver a exportar
    actualiza, no duplica. Sin rutas, usa las reales o, si ``rev.demo``, las de la demo: la demo nunca pisa lo real (X31).
    """
    cfg = rev.cfg
    caso = rev.caso(id_caso)
    if rev.estado(id_caso) == cfg.estado_inicial:
        raise ErrorDeRevision(f"{id_caso}: no se abrió para revisar")
    ficha = rev.ficha_revisada(id_caso)
    if ficha is None:
        raise ErrorDeRevision(f"{id_caso}: no tiene una ficha revisada guardada que exportar")
    por_defecto = rutas_de_exportacion(rev.demo, cfg, RAIZ)
    carpeta = carpeta or por_defecto[0]
    carpeta.mkdir(parents=True, exist_ok=True)
    ahora = rev.ahora()
    fila = fila_notion(rev, id_caso, ficha, ahora)
    md = a_markdown(rev, id_caso, ficha, ahora)
    ruta_md = carpeta / f"{id_caso}.md"
    ruta_md.write_text(md, encoding="utf-8")
    ruta_csv = carpeta / cfg.exportacion.csv
    actualizada = escribir_csv(ruta_csv, fila, cfg.exportacion.columnas)
    escribir_fichas_jsonl(rev, ruta_jsonl or por_defecto[1])
    return Exportacion(id_caso, ruta_md, ruta_csv, md, fila, actualizada)


def principal(argv: list[str] | None = None) -> int:
    """CLI: ``python -m src.exportar --caso CASO-001``."""
    cfg = cargar_revision()
    parser = argparse.ArgumentParser(description="E1-16: exporta un caso a Markdown y a la fila CSV de «Casos y evidencias» (Notion)")
    parser.add_argument("--caso", required=True, help="ID del caso, p. ej. CASO-001")
    parser.add_argument("--demo", action="store_true", help="revisiones y exportación de la demo (rutas aparte de las reales)")
    parser.add_argument("--revision", type=Path, default=None, help="por defecto la base real, o la de la demo con --demo")
    parser.add_argument("--base", type=Path, default=None, help="senales.duckdb (ya no hace falta para exportar: se exporta la ficha guardada)")
    parser.add_argument("--salida", type=Path, default=None)
    parser.add_argument("--fichas", type=Path, default=None)
    parser.add_argument("--notion", action="store_true", help="además sincroniza el caso con la base «Casos y evidencias» por la API (E3-03); sin token o sin red degrada a la exportación local")
    args = parser.parse_args(argv)
    if args.notion and args.demo:
        print("ERROR: --notion no se combina con --demo: los casos sintéticos de la demo nunca van a la base real de Notion.", file=sys.stderr)
        return 1
    carpeta, jsonl = rutas_de_exportacion(args.demo, cfg, RAIZ)
    args.salida, args.fichas = args.salida or carpeta, args.fichas or jsonl
    rev = Revisiones(args.revision or ruta_de_revision(args.demo, cfg), args.base, cfg, demo=args.demo, huellas=huellas_de_exportacion(args.demo, cfg, RAIZ))
    try:
        e = exportar_caso(rev, args.caso, args.salida, args.fichas)
    except (ErrorDeRevision, LookupError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"{e.id_caso}: {'actualizado' if e.actualizada else 'exportado'} · {e.ruta_markdown} · {e.ruta_csv} · {args.fichas}")
    return sincronizar_con_notion(e) if args.notion else 0


def sincronizar_con_notion(e: Exportacion, env: Mapping[str, str] | None = None, cliente: ClienteNotion | None = None) -> int:
    """Envía la exportación a Notion (E3-03). Sin token o sin red la exportación local ya está escrita: avisa y devuelve 0.
    Un error de la API es real y devuelve 1. El token nunca se imprime."""
    cfg = cargar_notion()
    if cliente is None:
        env = leer_local_env() if env is None else env
        token = (env.get(cfg.variable_token) or "").strip()
        if not token:
            print(cfg.textos.sin_token.format(variable=cfg.variable_token), file=sys.stderr)
            return 0
        cliente = ClienteNotion(token, cfg)
    try:
        s = cliente.sincronizar(e.id_caso, e.fila, e.markdown)
    except SinConexion:
        print(cfg.textos.sin_red, file=sys.stderr)
        return 0
    except ErrorNotion as exc:
        print(f"ERROR: {redactar(str(exc))}", file=sys.stderr)
        return 1
    print(f"{s.id_caso}: {cfg.textos.sincronizado_nuevo if s.creada else cfg.textos.sincronizado_existente} · {s.url} · {s.bloques} bloques")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
