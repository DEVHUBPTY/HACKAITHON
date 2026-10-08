"""Sensibilidad del ranking (E1-10, X02): ¿cuántos temas del top 5 cambian si se mueve un peso o un supuesto?

Recalcula el top 5 (CU-01) variando **un parámetro a la vez**:

* **Cada peso (R, I, U, N, E) en ±``variacion_peso`` puntos**: los otros cuatro se reescalan proporcionalmente para que los
  pesos sigan sumando 100 (``Pesos`` lo exige).
* **Cada parámetro supuesto de ``docs/parametros.md`` que cambia P, en ±``variacion_supuesto`` (20 %)**: partes de R, foco,
  partes de I, alcance por tema (la tabla entera), alcance geográfico (cada nivel), alcance sin tema, ventana de U (horas y
  días), partes de E, tope de procedencias, N del primer grupo y los dos supuestos de la agrupación que cambian los grupos
  (``ventana_dias`` y ``umbral_mismo_texto``; con ellos se **vuelve a agrupar** y se vuelve a vincular el dato oficial del
  Banco Mundial). Una parte que forma un par se reescala para que el par siga sumando 1; un valor en [0, 1] se recorta a 1.
  Los enteros (tope, ventana en días) se redondean y no bajan de 1.

Una variante que deja la regla idéntica (el valor recortado a 1 no cambia) **no cuenta** en la estabilidad: se lista aparte como `sin_efecto`.

Para cada variante se reporta qué temas entran y salen del top 5 y si cambia el orden. **Un tema «cambia» si estaba en el top
5 de las reglas v1.3 y ya no está.** La estabilidad se resume con n e IC de Wilson al 95 % (variantes cuyo top 5 no cambia).
El estado de evidencia no depende de P, así que no entra aquí.

**Lo que no se mueve, y por qué:** supuestos que no afectan a P (cifra del titular, las reglas internas de vínculo del contexto, los
umbrales de contradicción: solo afectan al estado de evidencia o al contexto), la coincidencia de sismos (± 2 días; el snapshot
no tiene grupos de sismos) y los de banca (modalidad_banca.yaml es parcial hasta E2-01, D-90). El detalle va en el JSON (``fuera_del_alcance``).

Uso: ``poetry run python -m eval.sensibilidad [--salida outputs/sensibilidad.json] [--ahora ISO]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from src import contexto, db, prioridad
from src.agrupacion import Grupo, codificar_titulares, construir_grupos
from src.clasificacion import proporcion
from src.configuracion import (
    RAIZ,
    ConfigPrioridad,
    ConfigVinculos,
    ReglasV13,
    cargar_carga,
    cargar_clasificacion,
    cargar_normalizacion,
    cargar_prioridad,
    cargar_procedencias,
    cargar_reglas,
    cargar_vinculos,
)
from src.embeddings import Embeddings, crear
from src.puntaje import COMPONENTES, EntradaGrupo, calcular_puntajes, empate_en_el_corte, p_para_empate

logger = logging.getLogger(__name__)

SALIDA = RAIZ / "outputs" / "sensibilidad.json"
ARRIBA, ABAJO = "+", "-"
GRUPO_PESO, GRUPO_SUPUESTO = "peso", "supuesto"
FUERA_DEL_ALCANCE = {
    "cifra_titular.* (ventana, palabras, patrones)": "solo cambia la etiqueta de comparación del contexto, no P ni el estado",
    "reglas de vínculo (tema + términos)": "método de contexto (D-125); I usa el tema, no la regla",
    "coincidencia de sismos (± 2 días)": "el snapshot no tiene grupos de sismos con vínculo de USGS que dependan de ella",
    "alcance por sector (banca)": "modalidad_banca.yaml es parcial (D-90): no define el alcance por sector hasta E2-01",
    "contradicciones.* (tope, verbos, solo_entre_procedencias)": "cambian el estado de evidencia y la acción, no P ni el ranking",
    "umbral de agrupación (calibrado, no supuesto)": "se calibra con etiquetas humanas (python -m eval.agrupacion)",
}


@dataclass(frozen=True)
class Ajuste:
    """Un parámetro que se mueve: cómo se aplica a las reglas y a ``prioridad.yaml``."""

    grupo: str
    nombre: str
    aplicar: Callable[[ReglasV13, ConfigPrioridad, float], tuple[ReglasV13, ConfigPrioridad]]
    reagrupa: bool = False


@dataclass(frozen=True)
class Variante:
    ajuste: Ajuste
    direccion: str
    reglas: ReglasV13
    cfg: ConfigPrioridad


# ------------------------------------------------------------------ cómo se mueve cada parámetro


def _recortar(x: float) -> float:
    """Un valor de [0, 1] no pasa de 1."""
    return min(x, 1.0)


def _par(a: float, b: float, factor: float) -> tuple[float, float]:
    """``a`` se multiplica por ``factor`` (recortado a 1) y ``b`` queda en lo que falta para sumar 1."""
    nuevo = _recortar(a * factor)
    return nuevo, 1.0 - nuevo


def _reparto(valores: Mapping[str, float], clave: str, nuevo: float, total: float) -> dict[str, float]:
    """``clave`` pasa a ``nuevo`` y las demás se reescalan proporcionalmente para que todo siga sumando ``total``."""
    resto_antes = total - valores[clave]
    resto_despues = total - nuevo
    return {k: (nuevo if k == clave else v * resto_despues / resto_antes) for k, v in valores.items()}


def _redondeado(valor: float, factor: float) -> int:
    return max(1, round(valor * factor))


def ajustes(reglas: ReglasV13) -> list[Ajuste]:
    """Los parámetros supuestos que cambian P (los pesos van aparte: ``variantes_de_pesos``)."""
    def en_reglas(**cambios: Any) -> Callable[[ReglasV13, ConfigPrioridad, float], tuple[ReglasV13, ConfigPrioridad]]:
        return lambda r, c, f: (r.model_copy(update=cambios), c)

    lista: list[Ajuste] = []

    def agregar(nombre: str, fn: Callable[[ReglasV13, ConfigPrioridad, float], tuple[ReglasV13, ConfigPrioridad]], reagrupa: bool = False) -> None:
        lista.append(Ajuste(GRUPO_SUPUESTO, nombre, fn, reagrupa))

    rel, imp, urg, nov, evi, agr = reglas.relevancia, reglas.impacto, reglas.urgencia, reglas.novedad, reglas.evidencia, reglas.agrupacion

    # D-103: R tiene una sola parte (foco, peso 1); ya no hay reparto de R que variar.
    agregar("Foco: otro país que afecta a Panamá", lambda r, c, f: (r.model_copy(update={"relevancia": r.relevancia.model_copy(update={"foco_otro_pais_afecta": _recortar(rel.foco_otro_pais_afecta * f)})}), c))
    agregar("Foco: Panamá implícito", lambda r, c, f: (r.model_copy(update={"relevancia": r.relevancia.model_copy(update={"foco_panama_implicito": _recortar(rel.foco_panama_implicito * f)})}), c))
    agregar("Foco: Panamá sujeto", lambda r, c, f: (r.model_copy(update={"relevancia": r.relevancia.model_copy(update={"foco_panama_sujeto": _recortar(rel.foco_panama_sujeto * f)})}), c))

    def peso_tema(r: ReglasV13, c: ConfigPrioridad, f: float):
        tema, geo = _par(imp.peso_tema, imp.peso_geografico, f)
        return r.model_copy(update={"impacto": r.impacto.model_copy(update={"peso_tema": tema, "peso_geografico": geo})}), c

    agregar("Partes de I (tema · geográfico)", peso_tema)
    for nivel in ("nacional", "provincial", "local", "desconocido", "exterior"):
        def alcance(r: ReglasV13, c: ConfigPrioridad, f: float, nivel: str = nivel):
            nuevo = r.impacto.alcance_geografico.model_copy(update={nivel: _recortar(getattr(imp.alcance_geografico, nivel) * f)})
            return r.model_copy(update={"impacto": r.impacto.model_copy(update={"alcance_geografico": nuevo})}), c

        agregar(f"Alcance geográfico {nivel}", alcance)

    def tabla_temas(r: ReglasV13, c: ConfigPrioridad, f: float):
        nueva = {k: _recortar(v * f) for k, v in imp.alcance_tema.items()}
        return r.model_copy(update={"impacto": r.impacto.model_copy(update={"alcance_tema": nueva})}), c

    agregar("Alcance por tema (la tabla entera)", tabla_temas)
    agregar(
        "Alcance de I sin tema",
        lambda r, c, f: (r, c.model_copy(update={"impacto": c.impacto.model_copy(update={"alcance_tema_desconocido": _recortar(c.impacto.alcance_tema_desconocido * f)})})),
    )
    # D-106: «horas con U = 1» es 0 por decisión (sin meseta), no un supuesto: no se varía.
    agregar("U: días con U = 0", lambda r, c, f: (r.model_copy(update={"urgencia": r.urgencia.model_copy(update={"dias_nulo": urg.dias_nulo * f})}), c))
    partes_e = {"peso_procedencias": evi.peso_procedencias, "peso_oficial": evi.peso_oficial, "peso_identificables": evi.peso_identificables}
    for clave, nombre in (("peso_procedencias", "procedencias"), ("peso_oficial", "oficial"), ("peso_identificables", "identificable")):
        def parte(r: ReglasV13, c: ConfigPrioridad, f: float, clave: str = clave):
            nuevas = _reparto(partes_e, clave, _recortar(partes_e[clave] * f), 1.0)
            return r.model_copy(update={"evidencia": r.evidencia.model_copy(update=nuevas)}), c

        agregar(f"Partes de E: {nombre}", parte)
    agregar("Tope de procedencias en E", lambda r, c, f: (r.model_copy(update={"evidencia": r.evidencia.model_copy(update={"tope_procedencias": _redondeado(evi.tope_procedencias, f)})}), c))
    agregar("N: ancla baja (D-124)", lambda r, c, f: (r.model_copy(update={"novedad": r.novedad.model_copy(update={"ancla_baja": _recortar(nov.ancla_baja * f)})}), c))
    agregar("N: ventana de comparación (días, D-124)", lambda r, c, f: (r.model_copy(update={"novedad": r.novedad.model_copy(update={"ventana_dias": nov.ventana_dias * f})}), c))
    agregar("U: tope con fecha imputada (D-124)", lambda r, c, f: (r.model_copy(update={"urgencia": r.urgencia.model_copy(update={"tope_fecha_imputada": _recortar(urg.tope_fecha_imputada * f)})}), c))
    agregar("N del primer grupo", lambda r, c, f: (r.model_copy(update={"novedad": r.novedad.model_copy(update={"sin_grupos_previos": _recortar(nov.sin_grupos_previos * f)})}), c))
    agregar("Ventana de agrupación (días)", lambda r, c, f: (r.model_copy(update={"agrupacion": r.agrupacion.model_copy(update={"ventana_dias": _redondeado(agr.ventana_dias, f)})}), c), reagrupa=True)
    agregar("Umbral de «mismo texto» (procedencias)", lambda r, c, f: (r.model_copy(update={"agrupacion": r.agrupacion.model_copy(update={"umbral_mismo_texto": _recortar(agr.umbral_mismo_texto * f)})}), c), reagrupa=True)
    return lista


def variantes_de_pesos(reglas: ReglasV13, cfg: ConfigPrioridad) -> list[Variante]:
    """Cada peso en ±``variacion_peso`` puntos; los otros se reescalan para que los pesos sumen 100."""
    puntos = cfg.sensibilidad.variacion_peso
    base = {k: getattr(reglas.pesos, k) for k in COMPONENTES}
    salida = []
    for k in COMPONENTES:
        for signo, direccion in ((1, ARRIBA), (-1, ABAJO)):
            nuevo = base[k] + signo * puntos
            if not 0 <= nuevo <= sum(base.values()):
                continue
            pesos = reglas.pesos.model_copy(update=_reparto(base, k, nuevo, sum(base.values())))
            ajuste = Ajuste(GRUPO_PESO, f"Peso {k}", lambda r, c, f: (r, c))
            salida.append(Variante(ajuste, direccion, reglas.model_copy(update={"pesos": pesos}), cfg))
    return salida


def variantes_de_supuestos(reglas: ReglasV13, cfg: ConfigPrioridad) -> list[Variante]:
    """Cada supuesto en ±``variacion_supuesto``."""
    v = cfg.sensibilidad.variacion_supuesto
    salida = []
    for a in ajustes(reglas):
        for factor, direccion in ((1 + v, ARRIBA), (1 - v, ABAJO)):
            r, c = a.aplicar(reglas, cfg, factor)
            salida.append(Variante(a, direccion, r, c))
    return salida


# ------------------------------------------------------------------ insumos


@dataclass(frozen=True)
class Insumos:
    """Todo lo que hace falta para recalcular el ranking con otras reglas, leído una sola vez de la base."""

    entradas: list[EntradaGrupo]
    filas: list[dict[str, Any]]                      # titulares que no son ruido, con ``titulo_limpio``
    vectores: np.ndarray
    indicadores: list[dict[str, Any]]
    oficial_en_base: dict[str, bool]                 # id_grupo (de la base) -> había dato oficial
    vinculos: ConfigVinculos


def leer_insumos(ruta_base: Path, reglas: ReglasV13, emb: Embeddings) -> Insumos:
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        entradas, _, _ = prioridad.leer_entradas(con, reglas, emb)
        filas = [n for n in db.leer_tabla(con, "noticias", "id_noticia") if n.get("id_grupo")]
        indicadores = db.leer_tabla(con, "indicadores")
    finally:
        con.close()
    return Insumos(
        entradas=entradas, filas=filas, vectores=codificar_titulares(filas, emb, reglas.agrupacion.usar_descripcion),
        indicadores=indicadores,
        oficial_en_base={e.id_grupo: e.tiene_oficial for e in entradas}, vinculos=cargar_vinculos(),
    )


def _anio_de(fecha: str | None) -> int | None:
    return int(fecha[contexto.POSICION_ANIO]) if fecha and fecha[contexto.POSICION_ANIO].isdigit() else None


def entradas_reagrupadas(insumos: Insumos, reglas: ReglasV13) -> list[EntradaGrupo]:
    """Vuelve a agrupar con ``reglas`` y recalcula procedencias, reglas de vínculo y dato oficial del Banco Mundial de cada grupo nuevo.

    Un grupo con los mismos titulares conserva su ID, y entonces su dato oficial de USGS (si lo tiene) se toma de la base.
    """
    grupos = construir_grupos(insumos.filas, insumos.vectores, reglas, cargar_procedencias())
    por_id = {str(f["id_noticia"]): i for i, f in enumerate(insumos.filas)}
    vinculables = []
    for g in grupos:
        miembros = [insumos.filas[por_id[i]] for i in g.ids_noticia]
        titulares = [str(m.get("titulo_limpio") or m.get("titulo") or "") for m in miembros]
        reglas_del_grupo = contexto.reglas_disparadas(titulares, g.tema_clasificado, insumos.vinculos)
        central = insumos.filas[por_id[g.id_noticia_central]]
        fecha = central.get("fecha_publicacion") or central.get("fecha_deteccion")
        vinculables.append({"id_grupo": g.id_grupo, "tema": g.tema_clasificado, "reglas": reglas_del_grupo, "titular": g.titular_central, "anio_publicacion": _anio_de(fecha)})
    filas_vinculo, _ = contexto.construir_vinculos(vinculables, insumos.indicadores, insumos.vinculos)
    aceptadas = cargar_prioridad().dato_oficial.relaciones_aceptadas
    oficial = {f["id_grupo"] for f in filas_vinculo if f["id_evidencia"] and f["tipo"] in aceptadas and not f["motivo_sin_vinculo"] and f["valor"] is not None}
    entradas = []
    for g, v in zip(grupos, vinculables, strict=True):
        indices = [por_id[i] for i in g.ids_noticia]
        entradas.append(
            EntradaGrupo(
                id_grupo=g.id_grupo,
                miembros=tuple(insumos.filas[i] for i in indices),
                vectores=insumos.vectores[indices],
                tema=g.tema_clasificado,
                n_procedencias=g.n_procedencias,
                tiene_oficial=g.id_grupo in oficial or insumos.oficial_en_base.get(g.id_grupo, False),
            )
        )
    return entradas


# ------------------------------------------------------------------ comparación


def top(entradas: Sequence[EntradaGrupo], reglas: ReglasV13, cfg: ConfigPrioridad, ahora: datetime, n: int) -> list[str]:
    """Los ``n`` primeros ``id_grupo`` del ranking."""
    return [p.id_grupo for p in calcular_puntajes(entradas, reglas, cfg, ahora)[:n]]


def comparar(base: Sequence[str], variante: Sequence[str]) -> dict[str, Any]:
    """Qué temas del top 5 base salen y cuáles entran, y si cambia el orden."""
    salen = [g for g in base if g not in variante]
    return {
        "top": list(variante),
        "cambian": len(salen),
        "salen": salen,
        "entran": [g for g in variante if g not in base],
        "mismo_conjunto": not salen,
        "mismo_orden": list(variante) == list(base),
    }


def evaluar(ruta_base: Path, reglas: ReglasV13, cfg: ConfigPrioridad, ahora: datetime, z: float, emb: Embeddings) -> dict[str, Any]:
    """Top 5 base y de cada variante, con el resumen de estabilidad."""
    insumos = leer_insumos(ruta_base, reglas, emb)
    n = cfg.sensibilidad.tamano_ranking
    base = top(insumos.entradas, reglas, cfg, ahora, n)
    ranking_base = calcular_puntajes(insumos.entradas, reglas, cfg, ahora)
    empate_base = empate_en_el_corte([p_para_empate(p.puntaje, cfg) for p in ranking_base], n)
    reproduce = sorted(e.id_grupo for e in entradas_reagrupadas(insumos, reglas)) == sorted(e.id_grupo for e in insumos.entradas)
    reagrupadas: dict[tuple[int, float], list[EntradaGrupo]] = {}
    filas: list[dict[str, Any]] = []
    for v in [*variantes_de_pesos(reglas, cfg), *variantes_de_supuestos(reglas, cfg)]:
        if v.ajuste.reagrupa:
            clave = (v.reglas.agrupacion.ventana_dias, v.reglas.agrupacion.umbral_mismo_texto)
            if clave not in reagrupadas:
                reagrupadas[clave] = entradas_reagrupadas(insumos, v.reglas)
            entradas = reagrupadas[clave]
        else:
            entradas = insumos.entradas
        filas.append(
            {"grupo": v.ajuste.grupo, "parametro": v.ajuste.nombre, "direccion": v.direccion, "reagrupa": v.ajuste.reagrupa,
             "con_efecto": not (v.reglas == reglas and v.cfg == cfg),
             **comparar(base, top(entradas, v.reglas, v.cfg, ahora, n))}
        )
    for f in filas:
        f["parametro_con_direccion"] = f"{f['parametro']} {f['direccion']}"
    efectivas = [f for f in filas if f["con_efecto"]]
    total = len(efectivas)
    sin_cambio = sum(1 for f in efectivas if f["mismo_conjunto"])
    return {
        "nota": "Un tema cambia si estaba en el top 5 de las reglas v1.3 y ya no está. Las variantes que dejan la regla igual (valor recortado a 1) no cuentan como estabilidad: van en `sin_efecto`. P es de ordenamiento; no habilita publicación.",
        "version_reglas": reglas.version,
        "fecha_referencia": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tamano_ranking": n,
        "variacion_peso_puntos": cfg.sensibilidad.variacion_peso,
        "variacion_supuesto": cfg.sensibilidad.variacion_supuesto,
        "top_base": base,
        # D-105: si el corte del top parte un empate en P, el top base lo completa la regla del reto (mayor U, luego ID) y la
        # estabilidad de esos puestos dice poco: se informa el empate en el corte.
        "empate_en_el_corte_base": empate_base,
        "reagrupar_con_las_reglas_actuales_reproduce_la_base": reproduce,
        "variantes": len(filas),
        "variantes_con_efecto": total,
        "sin_efecto": [f["parametro_con_direccion"] for f in filas if not f["con_efecto"]],
        "top_sin_cambio": proporcion(sin_cambio, total, z),
        "con_algun_cambio": proporcion(total - sin_cambio, total, z),
        "mismo_orden": proporcion(sum(1 for f in efectivas if f["mismo_orden"]), total, z),
        "maximo_de_temas_que_cambian": max((f["cambian"] for f in efectivas), default=0),
        "temas_retenidos": {**proporcion(sum(len(base) - f["cambian"] for f in efectivas), len(base) * total, z), "nota": "puestos del top 5 que se conservan en las variantes con efecto; los puestos de una misma variante no son independientes, el IC es orientativo"},
        "por_grupo": {g: {"variantes": sum(1 for f in filas if f["grupo"] == g), "con_cambio": sum(1 for f in efectivas if f["grupo"] == g and not f["mismo_conjunto"])} for g in (GRUPO_PESO, GRUPO_SUPUESTO)},
        "detalle": filas,
        "mas_sensibles": [
            {"parametro": f["parametro_con_direccion"], "cambian": f["cambian"], "salen": f["salen"], "entran": f["entran"]}
            for f in sorted(efectivas, key=lambda f: (-f["cambian"], f["parametro_con_direccion"]))
            if f["cambian"]
        ],
        "fuera_del_alcance": FUERA_DEL_ALCANCE,
    }


def imprimir(r: Mapping[str, Any]) -> None:
    def f(p: Mapping[str, Any]) -> str:
        return f"{p['n']}/{p['de']} = {p['proporcion']} IC95 {p['ic95']}"

    print(f"== Sensibilidad del top {r['tamano_ranking']} (reglas {r['version_reglas']}, referencia {r['fecha_referencia']}) ==")
    if not r["reagrupar_con_las_reglas_actuales_reproduce_la_base"]:
        print("  AVISO: volver a agrupar con las reglas actuales NO reproduce los grupos de la base; las variantes que reagrupan no son comparables")
    print(f"  variantes: {r['variantes']} ({r['variantes_con_efecto']} con efecto; pesos ±{r['variacion_peso_puntos']:g} puntos; supuestos ±{int(r['variacion_supuesto'] * 100)} %)")
    print(f"  top 5 sin ningún cambio de tema: {f(r['top_sin_cambio'])}")
    print(f"  variantes con algún tema distinto: {f(r['con_algun_cambio'])} · máximo de temas que cambian: {r['maximo_de_temas_que_cambian']}/{r['tamano_ranking']}")
    print(f"  mismo orden además del mismo conjunto: {f(r['mismo_orden'])}")
    print(f"  puestos del top 5 que se conservan: {f(r['temas_retenidos'])}")
    if r["sin_efecto"]:
        print(f"  sin efecto (no cuentan): {r['sin_efecto']}")
    for g, d in r["por_grupo"].items():
        print(f"  {g}: {d['con_cambio']}/{d['variantes']} variantes cambian el top")
    print("\n== Top 5 base ==")
    for i, g in enumerate(r["top_base"], start=1):
        print(f"  {i}. {g}")
    if r.get("empate_en_el_corte_base"):
        e = r["empate_en_el_corte_base"]
        print(f"  empate en el corte (D-105): P = {e['valor']} lo comparten {e['empatados']} grupos; {e['dentro_del_top']} entran y {e['fuera_del_top']} quedan fuera por la regla del reto (mayor U, luego ID)")
    print("\n== Variantes que cambian algún tema (de mayor a menor) ==")
    for m in r["mas_sensibles"][:15]:
        print(f"  {m['cambian']} · {m['parametro']} · salen {m['salen']} · entran {m['entran']}")
    if not r["mas_sensibles"]:
        print("  ninguna")
    print("\n== Fuera del alcance (no cambian P) ==")
    for k, v in r["fuera_del_alcance"].items():
        print(f"  {k}: {v}")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m eval.sensibilidad``."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="E1-10: sensibilidad del top 5 a los pesos (±5) y a los supuestos (±20 %)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--manifest", type=Path, default=RAIZ / "data" / prioridad.MANIFEST)
    parser.add_argument("--ahora", default=None, help="fecha de referencia ISO 8601 UTC (por defecto, fecha_corte_UTC del manifest)")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args(argv)
    db.base_real_o_salir(args.base)    # C-06: la base de la demo nunca entra en una métrica
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero la tubería hasta `python -m src.contexto`", args.base)
        return 1
    reglas, cfg = cargar_reglas(), cargar_prioridad()
    try:
        ahora = prioridad.parsear_fecha(args.ahora) if args.ahora else prioridad.fecha_de_corte(args.manifest)
        resultado = evaluar(args.base, reglas, cfg, ahora, cargar_carga().salida.z_intervalo_confianza, crear(cargar_clasificacion(), reglas.agrupacion.modelo))
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        logger.error("%s", exc)
        return 1
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    imprimir(resultado)
    print(f"\nEscrito: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
