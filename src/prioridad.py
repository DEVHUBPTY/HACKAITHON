"""Prioridad de los grupos: puntaje, estado de evidencia, vacíos, contradicciones y acción recomendada · E1-10, CU-01, T08.

Une los módulos puros (``puntaje``, ``evidencia``, ``contradicciones``) con ``data/senales.duckdb``:

1. Lee los grupos (``src.agrupacion``), sus procedencias y su contexto oficial (``src.contexto``) y vuelve a codificar los
   titulares con la caché de embeddings (``src.embeddings``; sin red).
2. Calcula R, I, U, N, E y P (``src.puntaje``), compara con el LLM los pares candidatos a contradicción
   (``src.contradicciones``; si el LLM falla, el puntaje no se rompe) y deduce estado, vacíos y acción (``src.evidencia``).
3. Reemplaza ``puntajes``, ``evidencia`` y ``contradicciones`` en una transacción y escribe ``outputs/prioridad.json``.

La fecha de referencia de U es el corte del snapshot (``data/manifest.json``: ``fecha_corte_UTC``): dos corridas dan el mismo
ranking. El resultado es **borrador para una decisión humana**: ninguna salida habilita publicar.

Uso: ``poetry run python -m src.puntaje [--sin-llm] [--ahora AAAA-MM-DDTHH:MM:SSZ]`` (después de ``src.contexto``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from src import contradicciones as contradiccion_mod
from src import db
from src.agrupacion import codificar_titulares
from src.clasificacion import proporcion
from src.configuracion import (
    MODALIDADES,
    RAIZ,
    Accion,
    ConfigModalidad,
    ConfigPrioridad,
    ReglasV13,
    cargar_carga,
    cargar_clasificacion,
    cargar_modalidad,
    cargar_normalizacion,
    cargar_prioridad,
    cargar_reglas,
    cargar_vinculos,
)
from src.contexto import leer_grupos as leer_contexto_de_grupos
from src.contradicciones import Contradiccion
from src.embeddings import Embeddings, crear
from src.evidencia import Evidencia, accion_recomendada, evaluar_evidencia
from src.llm.proveedor import ErrorProveedor, Proveedor, crear_proveedor
from src.puntaje import EntradaGrupo, Puntaje, calcular_puntajes
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

MODALIDAD_POR_DEFECTO = "editorial"
REPORTE = "prioridad.json"
MANIFEST = Path("manifest.json")              # bajo ``data/``
CAMPO_CORTE = "fecha_corte_UTC"
SEPARADOR_LISTA = ","
ANCHO_TITULAR_EN_LOG = 60          # solo presentación en la terminal
ESTADOS_DE_LLM = ("sin_llm", "usado", "no_disponible", "sin_candidatos")


@dataclass(frozen=True)
class ResultadoGrupo:
    """Todo lo que se sabe de la prioridad de un grupo."""

    puntaje: Puntaje
    evidencia: Evidencia
    accion: Accion
    contradicciones: tuple[Contradiccion, ...]


class ProveedorConCorte:
    """Envuelve un proveedor: tras el primer fallo no vuelve a llamarlo en esta corrida (evita esperar el tiempo de espera N veces)."""

    def __init__(self, proveedor: Proveedor) -> None:
        self.proveedor = proveedor
        self.nombre = proveedor.nombre
        self.modelo = proveedor.modelo
        self.caido: str | None = None

    def generar_json(self, system: str, usuario: str, esquema: dict[str, Any]) -> str:
        if self.caido is not None:
            raise ErrorProveedor(f"{self.caido} (no se vuelve a intentar en esta corrida)")
        try:
            return self.proveedor.generar_json(system, usuario, esquema)
        except ErrorProveedor as exc:
            self.caido = str(exc)
            raise


# ------------------------------------------------------------------ lectura


def fecha_de_corte(ruta_manifest: Path) -> datetime:
    """``fecha_corte_UTC`` del manifest como fecha con zona UTC."""
    with ruta_manifest.open(encoding="utf-8") as f:
        texto = json.load(f)[CAMPO_CORTE]
    return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).astimezone(UTC)


def parsear_fecha(texto: str) -> datetime:
    """Fecha ISO 8601 con zona (``--ahora``); sin zona se rechaza: no se adivina."""
    fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if fecha.tzinfo is None:
        raise ValueError(f"la fecha de referencia necesita zona horaria (UTC): {texto!r}")
    return fecha.astimezone(UTC)


def _oficial_por_grupo(
    vinculos: Sequence[Mapping[str, Any]], relaciones_aceptadas: Sequence[str]
) -> tuple[dict[str, bool], dict[str, str]]:
    """Por grupo: ¿hay un dato o evento oficial vinculado con valor? y el motivo si no lo hay.

    Solo cuentan las relaciones de ``relaciones_aceptadas`` (``directa`` y ``evento``): un vínculo ``indirecta`` es contexto
    lejano y no mide el hecho (X22), así que no es dato oficial.
    """
    oficial: dict[str, bool] = {}
    motivos: dict[str, str] = {}
    for v in vinculos:
        grupo = str(v["id_grupo"])
        if v.get("id_evidencia") and v.get("tipo") in relaciones_aceptadas and not v.get("motivo_sin_vinculo") and v.get("valor") is not None:
            oficial[grupo] = True
        elif v.get("motivo_sin_vinculo"):
            motivos.setdefault(grupo, str(v["motivo_sin_vinculo"]))
    return oficial, motivos


def _hallazgos_de_vinculos(vinculos: Sequence[Mapping[str, Any]], cfg: ConfigPrioridad, etiquetas: Any) -> dict[str, dict[str, Any]]:
    """Por grupo, lo que los vínculos dicen además de «hay dato oficial»: solo indirecto, cifras discrepantes o de otro período, eventos sin revisar.

    Solo cuentan los vínculos con dato real (``directa`` o ``evento``); el de relación ``indirecta`` solo marca ``solo_indirecto``.
    """
    aceptadas = cfg.dato_oficial.relaciones_aceptadas
    hallazgos: dict[str, dict[str, Any]] = {}
    for v in vinculos:
        if not (v.get("id_evidencia") and v.get("valor") is not None and not v.get("motivo_sin_vinculo")):
            continue
        h = hallazgos.setdefault(str(v["id_grupo"]), {"indirecto": False, "discrepancias": [], "periodos": [], "eventos": []})
        if v.get("tipo") not in aceptadas:
            h["indirecto"] = True
            continue
        comparacion, id_ = v.get("comparacion_titular"), str(v["id_evidencia"])
        if comparacion == etiquetas.discrepancia:
            h["discrepancias"].append(id_)
        elif comparacion == etiquetas.periodo_distinto:
            h["periodos"].append(id_)
        if str(v.get("fuente")) == "usgs" and v.get("estado_evento") == cfg.dato_oficial.estado_evento_automatico:
            h["eventos"].append(id_)
    return hallazgos


def leer_entradas(
    con: Any, reglas: ReglasV13, emb: Embeddings, cfg: ConfigPrioridad | None = None
) -> tuple[list[EntradaGrupo], dict[str, int], dict[str, str]]:
    """Entradas del puntaje, procedencia de cada noticia (su ``orden``) y titular central de cada grupo."""
    grupos = db.leer_tabla(con, "grupos", "id_grupo")
    if not grupos:
        raise RuntimeError("no hay grupos: ejecute `poetry run python -m src.agrupacion`")
    noticias = [n for n in db.leer_tabla(con, "noticias", "id_noticia") if n.get("id_grupo")]
    vectores = codificar_titulares(noticias, emb, reglas.agrupacion.usar_descripcion)
    posicion = {str(n["id_noticia"]): i for i, n in enumerate(noticias)}
    por_grupo: dict[str, list[Mapping[str, Any]]] = {}
    for n in noticias:
        por_grupo.setdefault(str(n["id_grupo"]), []).append(n)
    procedencia_de: dict[str, int] = {}
    n_procedencias: Counter[str] = Counter()
    for p in db.leer_tabla(con, "procedencias"):
        n_procedencias[str(p["id_grupo"])] += 1
        for id_noticia in str(p["ids_noticia"]).split(SEPARADOR_LISTA):
            procedencia_de[id_noticia] = int(p["orden"])
    subtemas = {g["id_grupo"]: g["subtema"] for g in leer_contexto_de_grupos(con)}
    cfg = cfg or cargar_prioridad()
    filas_vinculos = db.leer_tabla(con, "vinculos")
    oficial, motivos = _oficial_por_grupo(filas_vinculos, cfg.dato_oficial.relaciones_aceptadas)
    hallazgos = _hallazgos_de_vinculos(filas_vinculos, cfg, cargar_vinculos().cifra_titular.etiquetas)
    entradas = []
    for g in grupos:
        id_grupo = str(g["id_grupo"])
        miembros = tuple(sorted(por_grupo.get(id_grupo, []), key=lambda n: str(n["id_noticia"])))
        if len(miembros) != g["n_titulares"]:
            raise RuntimeError(f"{id_grupo}: la tabla grupos dice {g['n_titulares']} titulares y noticias tiene {len(miembros)}: vuelva a ejecutar src.agrupacion")
        entradas.append(
            EntradaGrupo(
                id_grupo=id_grupo,
                miembros=miembros,
                vectores=np.stack([vectores[posicion[str(m["id_noticia"])]] for m in miembros]),
                subtema=subtemas.get(id_grupo),
                n_procedencias=n_procedencias[id_grupo],
                tiene_oficial=oficial.get(id_grupo, False),
                motivo_sin_oficial=motivos.get(id_grupo),
                solo_indirecto=hallazgos.get(id_grupo, {}).get("indirecto", False) and not oficial.get(id_grupo, False),
                discrepancias=tuple(hallazgos.get(id_grupo, {}).get("discrepancias", ())),
                periodos_distintos=tuple(hallazgos.get(id_grupo, {}).get("periodos", ())),
                eventos_sin_revisar=tuple(hallazgos.get(id_grupo, {}).get("eventos", ())),
            )
        )
    return entradas, procedencia_de, {str(g["id_grupo"]): str(g["titular_central"]) for g in grupos}


# ------------------------------------------------------------------ cálculo


def evaluar(
    entradas: Sequence[EntradaGrupo],
    procedencia_de: Mapping[str, object],
    reglas: ReglasV13,
    cfg: ConfigPrioridad,
    modalidad: ConfigModalidad,
    ahora: datetime,
    proveedor: Proveedor | None,
) -> list[ResultadoGrupo]:
    """Puntaje, contradicciones, estado de evidencia y acción de cada grupo, en orden de ranking."""
    por_id = {e.id_grupo: e for e in entradas}
    resultados = []
    for p in calcular_puntajes(entradas, reglas, cfg, ahora):
        e = por_id[p.id_grupo]
        contradicciones = tuple(contradiccion_mod.evaluar_grupo(e.miembros, procedencia_de, proveedor, cfg))
        evidencia = evaluar_evidencia(
            n_procedencias=e.n_procedencias,
            tiene_oficial=e.tiene_oficial,
            titulares=[str(m.get("titulo_limpio") or "") for m in e.miembros],
            contradicciones_abiertas=contradiccion_mod.abiertas(contradicciones),
            n_identificables=int(p.componentes["E"].explicacion["n_identificables"]),
            motivo_sin_oficial=e.motivo_sin_oficial,
            reglas=reglas,
            cfg=cfg,
            solo_indirecto=e.solo_indirecto,
            discrepancias=e.discrepancias,
            periodos_distintos=e.periodos_distintos,
            eventos_sin_revisar=e.eventos_sin_revisar,
        )
        resultados.append(ResultadoGrupo(p, evidencia, accion_recomendada(p.rango, evidencia.estado, modalidad), contradicciones))
    return resultados


# ------------------------------------------------------------------ DuckDB


def _json(objeto: Any) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True)


def filas_de(resultados: Sequence[ResultadoGrupo], modalidad: ConfigModalidad) -> dict[str, list[dict[str, Any]]]:
    """Filas de ``puntajes``, ``evidencia`` y ``contradicciones``."""
    puntajes, evidencias, contradicciones = [], [], []
    for r in resultados:
        p, e = r.puntaje, r.evidencia
        puntajes.append(
            {
                "id_grupo": p.id_grupo, "posicion": p.posicion, "version_reglas": p.version_reglas, "fecha_referencia": p.fecha_referencia,
                "relevancia": p.componentes["R"].valor, "impacto": p.componentes["I"].valor, "urgencia": p.componentes["U"].valor,
                "novedad": p.componentes["N"].valor, "evidencia": p.componentes["E"].valor, "puntaje": p.puntaje, "rango": p.rango,
                "componentes": _json({k: {"valor": c.valor, "explicacion": c.explicacion} for k, c in p.componentes.items()}),
                "vacios": _json([{"codigo": v.codigo, "texto": v.texto} for v in p.vacios]),
                "recirculada": p.recirculada, "es_nueva": p.es_nueva,
            }
        )
        evidencias.append(
            {
                "id_grupo": p.id_grupo, "estado": e.estado, "n_procedencias": e.n_procedencias, "tiene_oficial": e.tiene_oficial,
                "hay_cifras": e.hay_cifras, "contradicciones_abiertas": e.contradicciones_abiertas,
                "vacios": _json([{"codigo": v.codigo, "texto": v.texto} for v in e.vacios]),
                "modalidad": modalidad.modalidad, "rango": p.rango, "accion": r.accion.accion, "motivo_accion": r.accion.motivo,
            }
        )
        for c in r.contradicciones:
            k = c.candidato
            contradicciones.append(
                {
                    "id_grupo": p.id_grupo, "id_noticia_a": k.id_a, "id_noticia_b": k.id_b, "medio_a": k.medio_a, "medio_b": k.medio_b,
                    "titular_a": k.titular_a, "titular_b": k.titular_b, "fecha_publicacion_a": k.fecha_a, "fecha_publicacion_b": k.fecha_b,
                    "reglas": SEPARADOR_LISTA.join(k.reglas), "detalle": k.detalle, "estado": c.estado, "nota_llm": c.nota_llm, "etiqueta": c.etiqueta,
                    "fragmento_a": c.fragmento_a or None, "fragmento_b": c.fragmento_b or None,
                    "proveedor": c.proveedor, "modelo": c.modelo, "motivo_pendiente": c.motivo_pendiente,
                }
            )
    return {"puntajes": puntajes, "evidencia": evidencias, "contradicciones": contradicciones}


def guardar(ruta_base: Path, filas: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    """Reemplaza las tres tablas en una transacción: una falla deja la corrida anterior."""
    con = db.conectar(ruta_base)
    try:
        db.asegurar_esquema(con)
        con.begin()
        try:
            for tabla in ("puntajes", "evidencia", "contradicciones"):
                con.execute(f'DELETE FROM "{tabla}"')
                db.insertar(con, tabla, filas[tabla])
            con.commit()
        except BaseException:
            con.rollback()
            raise
    finally:
        con.close()


# ------------------------------------------------------------------ reporte


def estado_del_llm(proveedor: Proveedor | None, resultados: Sequence[ResultadoGrupo]) -> dict[str, Any]:
    """Si el LLM se usó, falló o no se configuró (nunca incluye credenciales)."""
    cs = [c for r in resultados for c in r.contradicciones]
    pendientes = [c for c in cs if c.nota_llm == contradiccion_mod.NOTA_PENDIENTE]
    if not cs:
        estado = ESTADOS_DE_LLM[3]          # abstención antes de llamar: ningún par candidato, haya o no proveedor
    elif proveedor is None:
        estado = ESTADOS_DE_LLM[0]          # no hay proveedor configurado (o --sin-llm)
    elif len(pendientes) == len(cs):
        estado = ESTADOS_DE_LLM[2]          # configurado pero no respondió o respondió algo inválido
    else:
        estado = ESTADOS_DE_LLM[1]
    usado = proveedor if cs else None       # sin candidatos no se usó: el reporte versionado no depende de si Ollama está prendido
    return {
        "estado": estado,
        "proveedor": getattr(usado, "nombre", None),
        "modelo": getattr(usado, "modelo", None),
        "motivos_pendientes": dict(sorted(Counter(c.motivo_pendiente for c in pendientes).items())),
    }


def construir_reporte(
    resultados: Sequence[ResultadoGrupo],
    titulares_centrales: Mapping[str, str],
    reglas: ReglasV13,
    cfg: ConfigPrioridad,
    modalidad: ConfigModalidad,
    proveedor: Proveedor | None,
    z: float,
) -> dict[str, Any]:
    """Ranking y resumen con n e IC de Wilson. Todo es borrador: nada se publica."""
    n = len(resultados)
    cs = [c for r in resultados for c in r.contradicciones]
    return {
        "nota": "Puntaje de ordenamiento, no una probabilidad de verdad ni de pérdida. Todo es borrador para una decisión humana; ninguna acción habilita publicar.",
        "version_reglas": reglas.version,
        "modalidad": modalidad.modalidad,
        "fecha_referencia": resultados[0].puntaje.fecha_referencia if resultados else None,
        "grupos": n,
        "por_rango": {k: proporcion(sum(1 for r in resultados if r.puntaje.rango == k), n, z) for k in ("alto", "medio", "bajo")},
        "por_estado_de_evidencia": {k: proporcion(sum(1 for r in resultados if r.evidencia.estado == k), n, z) for k in ("suficiente", "parcial", "insuficiente")},
        "contradicciones": {
            "candidatos": len(cs),
            "abiertas": len(cs),
            "por_nota_llm": dict(sorted(Counter(c.nota_llm for c in cs).items())),
            "grupos_con_candidatos": sum(1 for r in resultados if r.contradicciones),
            "pares": [
                {"id_grupo": r.puntaje.id_grupo, "estado": c.estado, "nota_llm": c.nota_llm, "reglas": list(c.candidato.reglas), "detalle": c.candidato.detalle,
                 "versiones": [{"id": c.candidato.id_a, "medio": c.candidato.medio_a, "titular": c.candidato.titular_a, "fragmento": c.fragmento_a or None},
                               {"id": c.candidato.id_b, "medio": c.candidato.medio_b, "titular": c.candidato.titular_b, "fragmento": c.fragmento_b or None}]}
                for r in resultados for c in r.contradicciones
            ],
        },
        "llm": estado_del_llm(proveedor, resultados),
        "ranking": [
            {
                "posicion": r.puntaje.posicion,
                "id_grupo": r.puntaje.id_grupo,
                "titular_central": titulares_centrales.get(r.puntaje.id_grupo),
                "puntaje": round(r.puntaje.puntaje, 2),
                "rango": r.puntaje.rango,
                "componentes": {k: round(c.valor, 4) for k, c in r.puntaje.componentes.items()},
                "estado_de_evidencia": r.evidencia.estado,
                "accion": r.accion.accion,
                "vacios": [v.texto for v in (*r.puntaje.vacios, *r.evidencia.vacios)],
                "contradicciones": [
                    {"estado": c.estado, "nota_llm": c.nota_llm, "fragmentos": [c.fragmento_a or None, c.fragmento_b or None], "etiqueta": c.etiqueta, "versiones": [
                        {"id": c.candidato.id_a, "medio": c.candidato.medio_a, "titular": c.candidato.titular_a},
                        {"id": c.candidato.id_b, "medio": c.candidato.medio_b, "titular": c.candidato.titular_b}]}
                    for c in r.contradicciones if c.abierta
                ],
            }
            for r in resultados[: cfg.puntaje_eval.top_en_reporte]
        ],
    }


def escribir_reporte(ruta: Path, reporte: Mapping[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
        f.write("\n")


def ejecutar(
    ruta_base: Path,
    ruta_reporte: Path,
    ahora: datetime,
    proveedor: Proveedor | None,
    modalidad: str = MODALIDAD_POR_DEFECTO,
    emb: Embeddings | None = None,
) -> dict[str, Any]:
    """Calcula y guarda la prioridad de todos los grupos de la base; devuelve el reporte."""
    reglas, cfg, mod = cargar_reglas(), cargar_prioridad(), cargar_modalidad(modalidad)
    emb = emb or crear(cargar_clasificacion(), reglas.agrupacion.modelo)
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        entradas, procedencia_de, centrales = leer_entradas(con, reglas, emb)
    finally:
        con.close()
    envuelto = ProveedorConCorte(proveedor) if proveedor is not None else None
    resultados = evaluar(entradas, procedencia_de, reglas, cfg, mod, ahora, envuelto)
    guardar(ruta_base, filas_de(resultados, mod))
    reporte = construir_reporte(resultados, centrales, reglas, cfg, mod, proveedor, cargar_carga().salida.z_intervalo_confianza)
    escribir_reporte(ruta_reporte, reporte)
    return reporte


def _proveedor(sin_llm: bool) -> Proveedor | None:
    if sin_llm:
        logger.info("--sin-llm: los pares candidatos a contradicción quedan sin nota del LLM")
        return None
    try:
        return crear_proveedor()
    except ErrorProveedor as exc:
        logger.warning("Sin LLM (%s): los pares candidatos a contradicción quedan sin nota del LLM", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI: puntaje, evidencia y contradicciones de ``data/senales.duckdb`` y ``outputs/prioridad.json``."""
    configurar_logging()
    parser = argparse.ArgumentParser(description="E1-10: puntaje, estado de evidencia, vacíos y contradicciones")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--manifest", type=Path, default=RAIZ / "data" / MANIFEST, help="de aquí sale la fecha de referencia de U")
    parser.add_argument("--ahora", default=None, help="fecha de referencia ISO 8601 UTC (por defecto, fecha_corte_UTC del manifest)")
    parser.add_argument("--reporte", type=Path, default=RAIZ / "outputs" / REPORTE)
    parser.add_argument("--modalidad", choices=MODALIDADES, default=MODALIDAD_POR_DEFECTO)
    parser.add_argument("--sin-llm", action="store_true", help="no comparar contradicciones con el LLM (quedan pendientes)")
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero `normalizacion`, `limpieza`, `clasificacion`, `agrupacion` y `contexto`", args.base)
        return 1
    try:
        ahora = parsear_fecha(args.ahora) if args.ahora else fecha_de_corte(args.manifest)
        reporte = ejecutar(args.base, args.reporte, ahora, _proveedor(args.sin_llm), args.modalidad)
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        logger.error("%s", exc)
        return 1
    logger.info("%d grupos puntuados con las reglas %s (referencia %s)", reporte["grupos"], reporte["version_reglas"], reporte["fecha_referencia"])
    logger.info("rango: %s", {k: v["n"] for k, v in reporte["por_rango"].items()})
    logger.info("estado de evidencia: %s", {k: v["n"] for k, v in reporte["por_estado_de_evidencia"].items()})
    logger.info("contradicciones: %s · LLM: %s", reporte["contradicciones"]["por_nota_llm"] or "ninguna", reporte["llm"]["estado"])
    for fila in reporte["ranking"][:5]:
        logger.info("  %d. %s · P=%.1f (%s) · evidencia %s · %s · %s", fila["posicion"], fila["id_grupo"], fila["puntaje"], fila["rango"], fila["estado_de_evidencia"], fila["accion"], (fila["titular_central"] or "")[:ANCHO_TITULAR_EN_LOG])
    return 0


if __name__ == "__main__":
    sys.exit(main())
