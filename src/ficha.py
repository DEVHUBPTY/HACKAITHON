"""Ficha de evidencia de un grupo, común a ambas modalidades · E1-10b, etapa 5 del reto, D-36 a D-38, D-90.

Un solo flujo: DuckDB -> ``Ficha`` (pydantic, ``src/esquemas.py``) -> tres salidas: la **vista** (secciones y líneas que
pintará Streamlit en E1-15), el **Markdown** (Jinja2, ``templates/ficha.md.j2``; se renderiza desde la misma vista, así que dice
exactamente lo mismo que la app) y la línea de ``fichas.jsonl``.

Las cinco partes: qué se reporta, quién lo reporta, qué está respaldado, qué falta comprobar y qué acción se recomienda.
**Sin LLM** (D-36): la ficha se arma con lo que ya calcularon E1-08 a E1-10 y con reglas de ``config/verificacion.yaml``. Lo único
que cambia entre modalidades sale de ``config/modalidad_<modalidad>.yaml``: la tabla de acciones, el medio de referencia y
las fuentes sugeridas extra. No hay ningún ``if modalidad``.

* Toda línea de «respaldado» lleva una cita ``ID + campo``. Un titular es una **declaración** atribuida a su medio, nunca un
  hecho; hecho solo es un conteo o un dato oficial (``directa`` o ``evento``: un vínculo ``indirecta`` no mide el hecho, X22).
* Las fuentes sugeridas son una **sugerencia** para quien verifica (D-37): nunca evidencia ni con formato de cita.
* Nunca el nombre de un autor (D-32), nunca la descripción del RSS (D-31). Fechas en ISO 8601 UTC en los datos; la hora de Panamá
  solo al mostrar. Una publicación desconocida se dice «desconocida»: no se sustituye por la detección.
* Los vacíos los calcula E1-10 (tabla `evidencia`): la ficha los lee y no recalcula ninguno. Un texto citado lleva el campo citado literal (`titulo_limpio`).
* El titular central es el más cercano al centroide del grupo según los embeddings **cacheados** (nunca recarga el modelo),
  prefiriendo español y medio panameño entre los más centrales.

Uso: ``poetry run python -m src.ficha --grupo GRP-… --modalidad editorial|banca [--formato markdown|jsonl]``
(después de ``src.puntaje``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from jinja2 import Environment, FileSystemLoader

from src import db
from src.agrupacion import codificar_titulares
from src.configuracion import (
    MODALIDADES,
    RAIZ,
    ConfigModalidad,
    ConfigVerificacion,
    cargar_clasificacion,
    cargar_fuentes,
    cargar_modalidad,
    cargar_normalizacion,
    cargar_prioridad,
    cargar_procedencias,
    cargar_reglas,
    cargar_restricciones,
    cargar_temas,
    cargar_verificacion,
    cargar_vinculos,
)
from src.embeddings import Embeddings, crear
from src.esquemas import (
    ETIQUETA_BORRADOR,
    AccionRecomendada,
    ComponentePuntaje,
    ContradiccionFicha,
    Cita,
    Cobertura,
    DetalleProcedencia,
    FaltaComprobar,
    Ficha,
    FuenteSugerida,
    LineaRespaldo,
    MedioReferenciaFicha,
    ProcedenciasFicha,
    PuntajeFicha,
    QueSeReporta,
    QuienLoReporta,
    Respaldado,
    TitularCentral,
    TitularReportado,
    VacioFicha,
    VersionContradiccion,
)
from src.evidencia import accion_recomendada
from src.puntaje import CAMPO_PUBLICACION, COMPONENTES

MODALIDAD_POR_DEFECTO = "editorial"
FORMATOS = ("markdown", "jsonl")
PLANTILLA = "ficha.md.j2"
CARPETA_PLANTILLAS = RAIZ / "templates"
SEPARADOR_LISTA = ","
ESPACIOS = re.compile(r"\s+")
URL = re.compile(r"https?://\S+")
ESPECIALES_MARKDOWN = re.compile(r"([\\`*_\[\]<>&|~])")
ESPECIALES_EN_URL = re.compile(r"([\[\]<>])")
SEPARADOR_FUENTES = "; "
ROL_PANAMA, ROL_COMPARABLE, ROL_TENDENCIA = "panama", "comparable", "tendencia"
ORDEN_DE_ROLES = (ROL_PANAMA, ROL_COMPARABLE, ROL_TENDENCIA)
FUENTE_INDICADOR = "indicador"
SIN_DATO = "sin dato"
TITULOS = {
    "que_se_reporta": "1 · Qué se reporta",
    "quien_lo_reporta": "2 · Quién lo reporta",
    "respaldado": "3 · Qué está respaldado",
    "falta_comprobar": "4 · Qué falta comprobar",
    "accion_recomendada": "5 · Acción recomendada",
}
PRESENTACION_DE_NOTA = {
    "posible_contradiccion": "también ve una posible contradicción",
    "compatible": "ve las versiones como compatibles; el par sigue abierto",
    "pendiente": "sin nota: no hay LLM, falló o respondió algo inválido; el par sigue abierto",
}


# ------------------------------------------------------------------ vista (lo que muestran la app y el Markdown)


@dataclass(frozen=True)
class Linea:
    """Una línea de la vista: texto sin saltos de línea, nivel de sangría y si va en un desplegable."""

    texto: str
    nivel: int = 0
    desplegable: bool = False

    def __post_init__(self) -> None:
        # Una línea nunca trae saltos de línea ni espacios repetidos: un titular no puede abrir una sección falsa (M1).
        object.__setattr__(self, "texto", ESPACIOS.sub(" ", self.texto).strip())


@dataclass(frozen=True)
class Seccion:
    clave: str
    titulo: str
    lineas: tuple[Linea, ...]


@dataclass(frozen=True)
class Vista:
    """Estructura que consumen Streamlit (E1-15) y la plantilla de Markdown: las mismas cinco secciones."""

    id_grupo: str
    marca: str
    secciones: tuple[Seccion, ...]


# ------------------------------------------------------------------ utilidades


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _hora_panama(iso: str | None, cfg: ConfigVerificacion, con_zona: bool = True) -> str:
    """ISO 8601 UTC -> hora de Panamá para mostrar; nula -> «desconocida». Los datos nunca se transforman."""
    p = cfg.presentacion
    if not iso:
        return p.fecha_desconocida
    fecha = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZoneInfo(p.zona_horaria))
    return f"{fecha.strftime(p.formato_fecha)} ({p.sufijo_zona})" if con_zona else fecha.strftime(p.formato_fecha)


def _numero(valor: float, cfg: ConfigVerificacion) -> str:
    return f"{round(valor, cfg.presentacion.decimales_valor):g}"


def _embeddings() -> Embeddings:
    """Embeddings del modelo con que se agrupa (caché local; sin red)."""
    return crear(cargar_clasificacion(), cargar_reglas().agrupacion.modelo)


def _consulta(con: Any, sql: str, parametros: Sequence[Any] = ()) -> list[dict[str, Any]]:
    cur = con.execute(sql, list(parametros))
    nombres = [d[0] for d in cur.description]
    return [dict(zip(nombres, fila, strict=True)) for fila in cur.fetchall()]


def _json(texto: str | None, por_defecto: Any) -> Any:
    return json.loads(texto) if texto else por_defecto


# ------------------------------------------------------------------ titular central


def elegir_titular_central(miembros: Sequence[Mapping[str, Any]], vectores: np.ndarray, cfg: ConfigVerificacion) -> int:
    """Índice del titular central: entre los ``candidatos`` más cercanos al centroide, el primero en español y de medio panameño.

    Orden de preferencia entre los candidatos: español y panameño, español, panameño, y por último la cercanía al centroide;
    el empate lo rompe el menor ``id_noticia`` (determinista). Los vectores vienen de la caché de embeddings.
    """
    if len(miembros) == 1:
        return 0
    centroide = vectores.mean(axis=0)
    centroide = centroide / (np.linalg.norm(centroide) or 1.0)
    precision = np.finfo(np.float32).precision       # el ruido de coma flotante no decide un empate
    distancia = [round(float(1.0 - v @ centroide), precision) for v in vectores]
    orden = sorted(range(len(miembros)), key=lambda i: (distancia[i], str(miembros[i]["id_noticia"])))
    t = cfg.titular_central

    def preferencia(i: int) -> tuple[Any, ...]:
        m = miembros[i]
        return (m.get("idioma") != t.idioma_preferido, m.get("pais_medio") != t.pais_medio_preferido, distancia[i], str(m["id_noticia"]))

    return min(orden[: t.candidatos], key=preferencia)


# ------------------------------------------------------------------ fuentes sugeridas


def fuentes_sugeridas(tema: str | None, subtema: str | None, modalidad: ConfigModalidad, cfg: ConfigVerificacion) -> list[FuenteSugerida]:
    """Fuentes para verificar: las del subtema; sin subtema conocido (D-92), solo las del tema; y las extra de la modalidad al final."""
    f = cfg.fuentes
    if subtema and subtema != f.subtema_desconocido and subtema in f.por_subtema:
        base = [FuenteSugerida(nombre=n, origen="subtema") for n in f.por_subtema[subtema]]
    elif tema and tema in f.por_tema:
        base = [FuenteSugerida(nombre=n, origen="tema") for n in f.por_tema[tema]]
    else:
        base = []
    vistas = {s.nombre for s in base}
    extra = [FuenteSugerida(nombre=n, origen="modalidad") for n in dict.fromkeys(modalidad.fuentes_sugeridas_extra) if n not in vistas]
    return [*base, *extra]


# ------------------------------------------------------------------ lectura


@dataclass(frozen=True)
class Datos:
    """Todo lo que lee la ficha de la base."""

    grupo: dict[str, Any]
    puntaje: dict[str, Any]
    evidencia: dict[str, Any]
    noticias: list[dict[str, Any]]
    procedencias: list[dict[str, Any]]
    vinculos: list[dict[str, Any]]
    contradicciones: list[dict[str, Any]]
    fuentes: dict[str, dict[str, Any]]


def leer_datos(con: Any, id_grupo: str, modalidad: str) -> Datos:
    """Filas del grupo en ``grupos``, ``puntajes``, ``evidencia``, ``noticias``, ``procedencias``, ``vinculos`` y ``contradicciones``."""
    grupos = _consulta(con, "SELECT * FROM grupos WHERE id_grupo = ?", [id_grupo])
    if not grupos:
        raise LookupError(f"{id_grupo}: no existe en la tabla grupos")
    puntajes = _consulta(con, "SELECT * FROM puntajes WHERE id_grupo = ?", [id_grupo])
    evidencias = _consulta(con, "SELECT * FROM evidencia WHERE id_grupo = ?", [id_grupo])
    if not puntajes or not evidencias:
        raise LookupError(f"{id_grupo}: sin puntaje ni estado de evidencia; ejecute `poetry run python -m src.puntaje`")
    db.exigir_modalidad(evidencias[0].get("modalidad"), modalidad, id_grupo)       # X39: nunca se mezcla el puntaje de una modalidad con la acción de otra
    return Datos(
        grupo=grupos[0],
        puntaje=puntajes[0],
        evidencia=evidencias[0],
        noticias=_consulta(con, "SELECT * FROM noticias WHERE id_grupo = ? ORDER BY id_noticia", [id_grupo]),
        procedencias=_consulta(con, "SELECT * FROM procedencias WHERE id_grupo = ? ORDER BY orden", [id_grupo]),
        vinculos=_consulta(con, "SELECT * FROM vinculos WHERE id_grupo = ?", [id_grupo]),
        contradicciones=_consulta(con, "SELECT * FROM contradicciones WHERE id_grupo = ? ORDER BY id_noticia_a, id_noticia_b", [id_grupo]),
        fuentes={f["dominio"]: f for f in _consulta(con, "SELECT * FROM fuentes")},
    )


def _nombre_medio(fila: Mapping[str, Any], fuentes: Mapping[str, Mapping[str, Any]]) -> str:
    """Nombre legible del medio (``fuentes.nombre_legible``); si no hay, el medio o el dominio tal como llegaron."""
    dominio = str(fila.get("dominio") or "")
    legible = fuentes.get(dominio, {}).get("nombre_legible")
    return str(legible or fila.get("medio") or dominio or "medio desconocido")


# ------------------------------------------------------------------ cada parte


def _titulares(datos: Datos) -> list[TitularReportado]:
    procedencia_de = {i: int(p["orden"]) for p in datos.procedencias for i in str(p["ids_noticia"]).split(SEPARADOR_LISTA)}
    return [
        TitularReportado(
            id_noticia=str(n["id_noticia"]),
            titular=str(n.get("titulo_limpio") or n["titulo"]),
            campo_titular="titulo_limpio" if n.get("titulo_limpio") else "titulo",
            medio=_nombre_medio(n, datos.fuentes),
            dominio=str(n.get("dominio") or ""),
            pais_medio=n.get("pais_medio"),
            agencia=n.get("agencia"),
            tipo_firma=str(n["tipo_firma"]),
            fecha_publicacion=n.get(CAMPO_PUBLICACION),
            url=str(n["url"]),
            idioma=n.get("idioma"),
            sospechoso_inyeccion=bool(n.get("sospechoso_inyeccion")),
            procedencia=procedencia_de.get(str(n["id_noticia"])),
        )
        for n in datos.noticias
    ]


def _contradicciones(datos: Datos, cfg: ConfigVerificacion) -> list[ContradiccionFicha]:
    por_id = {str(n["id_noticia"]): n for n in datos.noticias}

    def version(id_noticia: str, titular: str, medio: str | None, fecha: str | None) -> VersionContradiccion:
        fila = por_id.get(id_noticia, {"medio": medio, "dominio": medio})
        return VersionContradiccion(id=id_noticia, medio=_nombre_medio(fila, datos.fuentes), titular=titular, fecha_publicacion=fecha)

    return [
        ContradiccionFicha(
            etiqueta=str(c["etiqueta"]),
            version_a=version(str(c["id_noticia_a"]), str(c["titular_a"]), c.get("medio_a"), c.get("fecha_publicacion_a")),
            version_b=version(str(c["id_noticia_b"]), str(c["titular_b"]), c.get("medio_b"), c.get("fecha_publicacion_b")),
            detalle=str(c["detalle"]),
            nota_llm=c["nota_llm"],
            fragmento_a=c.get("fragmento_a"),
            fragmento_b=c.get("fragmento_b"),
        )
        for c in datos.contradicciones
    ]


def _alcance(datos: Datos) -> str:
    """Leyenda de alcance (D-51): declara la descripción del RSS si se usó en algún paso que da forma a lo que muestra la ficha.

    La descripción es de uso interno y nunca se muestra (D-31), pero si se codificó junto al titular para **clasificar** (tema y
    subtema, ``clasificacion.yaml``) o para **agrupar** (``reglas_v1.3.yaml``), la ficha depende de ella y la leyenda debe decirlo.
    Solo cuenta si algún titular del grupo la trae: sin descripción no hay nada que declarar.
    """
    leyendas = cargar_restricciones().leyendas_alcance
    uso_en_pasos = cargar_clasificacion().usar_descripcion or cargar_reglas().agrupacion.usar_descripcion
    return leyendas.con_descripcion if uso_en_pasos and any(n.get("descripcion") for n in datos.noticias) else leyendas.titular_metadatos


def _que_se_reporta(datos: Datos, titulares: list[TitularReportado], emb: Embeddings | None, cfg: ConfigVerificacion, subtema: str | None) -> QueSeReporta:
    miembros = datos.noticias
    if len(miembros) > 1:
        emb = emb or _embeddings()
        vectores = codificar_titulares(miembros, emb, cargar_reglas().agrupacion.usar_descripcion)
    else:
        vectores = np.zeros((len(miembros), 0), dtype=np.float32)
    central = titulares[elegir_titular_central(miembros, vectores, cfg)]
    g = datos.grupo
    advertencias = []
    if any(t.sospechoso_inyeccion for t in titulares):
        advertencias.append(cfg.presentacion.advertencia_inyeccion)
    if datos.puntaje["recirculada"]:
        advertencias.append(cfg.presentacion.advertencia_recirculada)
    return QueSeReporta(
        tema=g.get("tema_clasificado"),
        subtema=subtema,
        criterio_subtema=next((str(v["criterio_subtema"]) for v in datos.vinculos if subtema and v.get("criterio_subtema")), None),
        titular_central=TitularCentral(id_noticia=central.id_noticia, titular=central.titular, medio=central.medio, url=central.url),
        cobertura=Cobertura(
            n_titulares=int(g["n_titulares"]), n_medios=int(g["n_medios"]), fecha_inicio=g.get("fecha_inicio"), fecha_fin=g.get("fecha_fin"),
            origen_fecha_inicio=g.get("fecha_inicio_origen"), origen_fecha_fin=g.get("fecha_fin_origen"),
        ),
        contradicciones=_contradicciones(datos, cfg),
        advertencias=advertencias,
        recirculada=bool(datos.puntaje["recirculada"]),
    )


def _texto_procedencias(n: int) -> str:
    return _plural(n, "procedencia independiente estimada", "procedencias independientes estimadas")


def _procedencias(datos: Datos, cfg: ConfigVerificacion) -> ProcedenciasFicha:
    n, titulares = int(datos.grupo["n_procedencias"]), int(datos.grupo["n_titulares"])
    nombres = cfg.procedencias.reglas
    detalle = [
        DetalleProcedencia(
            orden=int(p["orden"]), etiqueta=str(p["etiqueta"]),
            reglas=[nombres.get(r, r) for r in str(p["reglas"] or "").split(SEPARADOR_LISTA) if r],
            n_titulares=int(p["n_titulares"]), medios=str(p["medios"]).split(SEPARADOR_LISTA), ids_noticia=str(p["ids_noticia"]).split(SEPARADOR_LISTA),
        )
        for p in datos.procedencias
    ]
    explicacion = cfg.procedencias.explicacion.format(procedencias=_texto_procedencias(n), titulares=_plural(titulares, "titular", "titulares"))
    return ProcedenciasFicha(n=n, estimado=bool(datos.grupo["estimado"]), explicacion=explicacion, detalle=detalle)


def _medio_referencia(titulares: list[TitularReportado], modalidad: ConfigModalidad, cfg: ConfigVerificacion) -> MedioReferenciaFicha | None:
    ref = modalidad.medio_referencia
    if ref is None:
        return None
    dominio = ref.dominio.lower().removeprefix("www.")
    ids = [t.id_noticia for t in titulares if t.dominio.lower().removeprefix("www.") == dominio]
    plantilla = cfg.medio_referencia.cubrio if ids else cfg.medio_referencia.sin_titular
    return MedioReferenciaFicha(nombre=ref.nombre, dominio=ref.dominio, cubrio=bool(ids), n_titulares=len(ids), ids_noticia=ids, texto=plantilla.format(nombre=ref.nombre, titulares=_plural(len(ids), "titular", "titulares")))


def _vinculos_oficiales(datos: Datos, aceptadas: Sequence[str]) -> list[dict[str, Any]]:
    """Filas con dato o evento oficial real y de una relación aceptada (``directa`` o ``evento``; X22)."""
    return [v for v in datos.vinculos if _tiene_dato(v) and v.get("tipo") in aceptadas]


def _tiene_dato(v: Mapping[str, Any]) -> bool:
    return bool(v.get("id_evidencia")) and v.get("valor") is not None and not v.get("motivo_sin_vinculo")


def _limitacion_comun(filas: Sequence[Mapping[str, Any]]) -> str | None:
    """Lo que dicen todas las limitaciones de las filas (frases comunes, en el orden de la primera); si no hay, la de la primera."""
    frases = [re.split(r"(?<=\.)\s+", str(f["limitacion"])) for f in filas if f.get("limitacion")]
    if not frases:
        return None
    comunes = [x for x in frases[0] if all(x in otras for otras in frases[1:])]
    return " ".join(comunes) if comunes else " ".join(frases[0])


def _lineas_de_indicadores(indicadores: Sequence[Mapping[str, Any]], cfg: ConfigVerificacion) -> list[LineaRespaldo]:
    """Una línea por dato de Panamá y una por rol (comparables, tendencia): cada valor lleva su propia cita y el año va en el texto."""
    p = cfg.presentacion
    nombres = {i: x.nombre for i, x in cargar_fuentes().banco_mundial.indicadores.items()}
    lineas: list[LineaRespaldo] = []
    for rol in ORDEN_DE_ROLES:
        filas = [v for v in indicadores if v["rol"] == rol]
        lotes = [[v] for v in filas] if rol == ROL_PANAMA else ([filas] if filas else [])
        for lote in lotes:
            valores = SEPARADOR_FUENTES.join(
                f"{v['pais_iso3']} {v['anio']}: {_numero(float(v['valor']), cfg)}" + (f" {v['unidad']}" if v.get("unidad") else "") for v in lote
            )
            lineas.append(
                LineaRespaldo(
                    tipo="hecho",
                    texto=f"{p.fuentes_oficiales[FUENTE_INDICADOR]} · {p.roles[rol]} · {valores}",
                    citas=[Cita(id=str(v["id_evidencia"]), campo="valor") for v in lote],
                    limitacion=_limitacion_comun(lote),
                    indicador=" / ".join(dict.fromkeys(nombres.get(str(v["indicador_id"]), str(v["indicador_id"])) for v in lote)),
                )
            )
    return lineas


def _respaldado(datos: Datos, titulares: list[TitularReportado], cfg: ConfigVerificacion) -> Respaldado:
    g, p = datos.grupo, cfg.presentacion
    id_grupo = str(g["id_grupo"])
    n_titulares, n_medios, n_proc = int(g["n_titulares"]), int(g["n_medios"]), int(g["n_procedencias"])
    reportes = [
        LineaRespaldo(
            tipo="hecho", texto=f"{_plural(n_titulares, 'titular', 'titulares')} de {_plural(n_medios, 'medio', 'medios')} {'reporta' if n_titulares == 1 else 'reportan'} este tema",
            citas=[Cita(id=id_grupo, campo="n_titulares"), Cita(id=id_grupo, campo="n_medios")],
        ),
        LineaRespaldo(
            tipo="hecho",
            texto=f"{_texto_procedencias(n_proc)} (los titulares que replican a una misma fuente cuentan como una)",
            citas=[Cita(id=id_grupo, campo="n_procedencias")],
        ),
    ]
    aceptadas = cargar_prioridad().dato_oficial.relaciones_aceptadas
    oficiales = _vinculos_oficiales(datos, aceptadas)
    indicadores = sorted(
        (v for v in oficiales if v.get("fuente") == FUENTE_INDICADOR and v.get("rol") in ORDEN_DE_ROLES),
        key=lambda v: (ORDEN_DE_ROLES.index(v["rol"]), -int(v["anio"] or 0), str(v["id_evidencia"])),
    )
    datos_oficiales = _lineas_de_indicadores(indicadores, cfg)
    eventos = [
        LineaRespaldo(
            tipo="hecho",
            texto=(
                f"{p.fuentes_oficiales.get(str(v['fuente']), str(v['fuente']))} · {p.roles.get(str(v['rol']), str(v['rol']))}: magnitud {_numero(float(v['valor']), cfg)}, "
                f"lugar «{v.get('place') or SIN_DATO}» (tal como lo da la fuente)"
                + (f", profundidad {_numero(float(v['profundidad_km']), cfg)} km" if v.get("profundidad_km") is not None else "")
                + (f", estado {v['estado_evento']}" if v.get("estado_evento") else "")
            ),
            citas=[Cita(id=str(v["id_evidencia"]), campo="magnitude")],
            limitacion=v.get("limitacion"),
            fecha=v.get("hora_utc"),
        )
        for v in oficiales
        if str(v["id_evidencia"]).startswith("SIS-")
    ]
    declaraciones = [
        LineaRespaldo(tipo="declaración", texto=f"{t.medio} reporta: «{t.titular}»", citas=[Cita(id=t.id_noticia, campo=t.campo_titular)], atribucion=t.medio)
        for t in titulares
    ]
    return Respaldado(reportes=reportes, datos_oficiales=datos_oficiales, eventos_oficiales=eventos, declaraciones=declaraciones)


def _vacios(datos: Datos, cfg: ConfigVerificacion) -> list[VacioFicha]:
    """Los vacíos que guardó E1-10 (``puntajes.vacios`` y ``evidencia.vacios``: única fuente), ordenados por importancia.

    La ficha no recalcula ninguno: solo les agrega la verificación sugerida de ``verificacion.yaml``.
    """
    v = cfg.vacios
    por_codigo: dict[str, str] = {}
    for x in [*_json(datos.puntaje.get("vacios"), []), *_json(datos.evidencia.get("vacios"), [])]:
        por_codigo.setdefault(x["codigo"], x["texto"])
    orden = {c: i for i, c in enumerate(v.orden_importancia)}
    return [
        VacioFicha(codigo=c, texto=t, verificacion=v.catalogo[c].verificacion if c in v.catalogo else v.verificacion_por_defecto)
        for c, t in sorted(por_codigo.items(), key=lambda ct: orden.get(ct[0], len(orden)))
    ]


def _accion(datos: Datos, vacios: list[VacioFicha], modalidad: ConfigModalidad, cfg: ConfigVerificacion) -> AccionRecomendada:
    rango, estado = str(datos.puntaje["rango"]), str(datos.evidencia["estado"])
    celda = accion_recomendada(rango, estado, modalidad)
    pasos = list(dict.fromkeys(x.verificacion for x in vacios[: cfg.vacios.principales]))[: cfg.siguientes_pasos.maximo]
    return AccionRecomendada(accion=celda.accion, motivo=celda.motivo, rango=rango, estado_evidencia=estado, siguientes_pasos=pasos)  # type: ignore[arg-type]


def _puntaje(datos: Datos) -> PuntajeFicha:
    p = datos.puntaje
    guardados = _json(p["componentes"], {})
    comps = {k: ComponentePuntaje(valor=guardados[k]["valor"], explicacion=guardados[k]["explicacion"]) for k in COMPONENTES if k in guardados}
    return PuntajeFicha(
        puntaje=float(p["puntaje"]), rango=p["rango"], posicion=int(p["posicion"]), version_reglas=str(p["version_reglas"]),
        fecha_referencia=str(p["fecha_referencia"]), componentes=comps,
    )


def construir_ficha(
    id_grupo: str,
    modalidad: str,
    con: Any,
    emb: Embeddings | None = None,
    cfg: ConfigVerificacion | None = None,
    excluir_vinculos: Collection[str] = (),
    vacios_extra: Sequence[VacioFicha] = (),
) -> Ficha:
    """Ficha de evidencia de ``id_grupo`` para ``modalidad`` leyendo de la conexión DuckDB ``con`` (después de ``src.puntaje``).

    ``emb`` son los embeddings cacheados para el titular central (si no se pasan, se abren los del modelo de agrupación; con la
    caché llena no se carga el modelo). Lanza ``LookupError`` si el grupo no existe o no tiene puntaje y ``db.ModalidadDistinta`` si la corrida guardada es de otra modalidad.

    E1-16: ``excluir_vinculos`` son los ``id_evidencia`` oficiales que una persona rechazó (no entran en «respaldado» ni, por tanto, en
    el borrador); ``vacios_extra`` se agregan al frente de los vacíos para que la persona vea por qué falta ese dato. El puntaje, el estado
    de evidencia y los vacíos que guardó E1-10 no se recalculan (la ficha solo lee).
    """
    cfg = cfg or cargar_verificacion()
    mod = cargar_modalidad(modalidad)
    datos = leer_datos(con, id_grupo, modalidad)
    if excluir_vinculos:
        datos = replace(datos, vinculos=[v for v in datos.vinculos if v.get("id_evidencia") not in set(excluir_vinculos)])
    componentes = _json(datos.puntaje["componentes"], {})
    subtema = componentes.get("I", {}).get("explicacion", {}).get("subtema")
    titulares = _titulares(datos)
    vacios = [*vacios_extra, *_vacios(datos, cfg)]
    principales = cfg.vacios.principales
    return Ficha(
        id_grupo=id_grupo,
        modalidad=modalidad,
        marca_borrador=ETIQUETA_BORRADOR,
        alcance=_alcance(datos),
        puntaje=_puntaje(datos),
        que_se_reporta=_que_se_reporta(datos, titulares, emb, cfg, subtema),
        quien_lo_reporta=QuienLoReporta(titulares=titulares, procedencias=_procedencias(datos, cfg), medio_referencia=_medio_referencia(titulares, mod, cfg)),
        respaldado=_respaldado(datos, titulares, cfg),
        falta_comprobar=FaltaComprobar(
            principales=vacios[:principales], otros=vacios[principales:],
            fuentes_sugeridas=fuentes_sugeridas(datos.grupo.get("tema_clasificado"), subtema, mod, cfg), aviso_fuentes=cfg.fuentes.nota,
        ),
        accion_recomendada=_accion(datos, vacios, mod, cfg),
    )


# ------------------------------------------------------------------ vista y salidas


def _etiqueta_de(codigos: Mapping[str, str], clave: str | None) -> str:
    return codigos.get(str(clave), str(clave)) if clave else ""


def vista(ficha: Ficha, cfg: ConfigVerificacion | None = None) -> Vista:
    """Las cinco secciones de la ficha como líneas de texto (hora de Panamá, citas visibles). La app y el Markdown usan esta misma vista."""
    cfg = cfg or cargar_verificacion()
    temas = cargar_temas().temas
    q, r, ra, fc, ar = ficha.que_se_reporta, ficha.quien_lo_reporta, ficha.respaldado, ficha.falta_comprobar, ficha.accion_recomendada
    tema = temas.get(q.tema or "")
    nombre_tema = tema.nombre if tema else (q.tema or "no determinado")
    nombre_subtema = tema.subtemas[q.subtema].nombre if tema and q.subtema in tema.subtemas else "no determinado"
    c = q.cobertura
    origen = cfg.presentacion.origen_fecha
    if c.fecha_inicio and c.fecha_fin:
        fechas = f"de {_hora_panama(c.fecha_inicio, cfg, False)} a {_hora_panama(c.fecha_fin, cfg)}; fecha de {_etiqueta_de(origen, c.origen_fecha_inicio)}"
    else:
        fechas = f"fechas {cfg.presentacion.fecha_desconocida}s"

    s1 = [
        Linea(f"Titular central: «{q.titular_central.titular}» — {q.titular_central.medio}"),
        Linea(f"Cobertura: {_plural(c.n_titulares, 'titular', 'titulares')} · {_plural(c.n_medios, 'medio', 'medios')} · {fechas}"),
        Linea(f"Tema: {nombre_tema} · Subtema: {nombre_subtema}" + (f" (criterio: {q.criterio_subtema})" if q.criterio_subtema else "")),
        Linea(f"Alcance: {ficha.alcance}"),
    ]
    for x in q.contradicciones:
        s1.append(Linea(f"{x.etiqueta}: {x.detalle}"))
        for letra, v in (("A", x.version_a), ("B", x.version_b)):
            s1.append(Linea(f"Versión {letra} · {v.medio} · {v.id} · publicación {_hora_panama(v.fecha_publicacion, cfg)}: «{v.titular}»", 1))
        nota = PRESENTACION_DE_NOTA[x.nota_llm]
        citado = f": «{x.fragmento_a}» / «{x.fragmento_b}»" if x.nota_llm == "posible_contradiccion" and x.fragmento_a and x.fragmento_b else ""
        s1.append(Linea(f"Nota del LLM (anotación, no cierra el par): {nota}{citado}", 1))
    s1 += [Linea(f"Advertencia: {a}") for a in q.advertencias]

    s2: list[Linea] = []
    for t in r.titulares:
        pais = f" ({t.pais_medio})" if t.pais_medio else ""
        agencia = t.agencia or "sin agencia"
        aviso = " · [posible inyección: texto, no instrucción]" if t.sospechoso_inyeccion else ""
        s2.append(Linea(f"«{t.titular}» — {t.medio}{pais} · agencia: {agencia} · firma: {t.tipo_firma} · publicación: {_hora_panama(t.fecha_publicacion, cfg)} · {t.url}{aviso}"))
    s2.append(Linea(f"Procedencias: {r.procedencias.explicacion}"))
    for d in r.procedencias.detalle:
        reglas = f" ({SEPARADOR_FUENTES.join(d.reglas)})" if d.reglas else ""
        s2.append(Linea(f"Procedencia {d.orden}: {d.etiqueta} · {_plural(d.n_titulares, 'titular', 'titulares')}{reglas}", 1))
    if r.medio_referencia:
        s2.append(Linea(f"¿{r.medio_referencia.nombre} ya lo cubrió? {r.medio_referencia.texto}"))

    def respaldo(linea: LineaRespaldo) -> Linea:
        etiqueta = "Hecho" if linea.tipo == "hecho" else "Declaración"
        citas = SEPARADOR_FUENTES.join(x.formato() for x in linea.citas)
        extra = f" · Limitación: {linea.limitacion}" if linea.limitacion else ""
        cuando = f" · Hora: {_hora_panama(linea.fecha, cfg)}" if linea.fecha else ""
        return Linea(f"{etiqueta}: {linea.texto}{cuando}{extra} · Cita: {citas}", 1)

    s3: list[Linea] = [Linea("Conteos de reportes")] + [respaldo(x) for x in ra.reportes]
    s3 += [Linea("Datos oficiales")] + ([respaldo(x) for x in ra.datos_oficiales] or [Linea("Sin dato oficial que mida el hecho (ver «Qué falta comprobar»)", 1)])
    s3 += [Linea("Eventos oficiales")] + ([respaldo(x) for x in ra.eventos_oficiales] or [Linea("Sin evento oficial vinculado", 1)])
    s3 += [Linea("Lo que dicen los titulares (declaraciones atribuidas a su medio)")] + [respaldo(x) for x in ra.declaraciones]

    def vacio(x: Any, nivel: int = 0, desplegable: bool = False) -> Linea:
        return Linea(f"{x.texto} → Verificar: {x.verificacion}", nivel, desplegable)

    s4 = [vacio(x) for x in fc.principales] or [Linea("Sin vacíos que detecten las reglas; la revisión humana sigue siendo obligatoria.")]
    if fc.otros:
        s4.append(Linea(f"Otros vacíos ({len(fc.otros)})"))
        s4 += [vacio(x, 1, True) for x in fc.otros]
    s4.append(Linea(f"Fuentes sugeridas para verificar ({fc.aviso_fuentes})"))
    s4 += [Linea(s.nombre, 1) for s in fc.fuentes_sugeridas] or [Linea("Ninguna: el grupo no tiene tema ni subtema conocido", 1)]

    p = ficha.puntaje
    desglose = " · ".join(f"{k} {_numero(c.valor, cfg)}" for k, c in p.componentes.items())
    s5 = [
        Linea(f"Acción: {ar.accion}"),
        Linea(f"Motivo: {ar.motivo}"),
        Linea(f"Prioridad: {ar.rango} (P = {_numero(p.puntaje, cfg)}, posición {p.posicion}, reglas {p.version_reglas}) · Estado de evidencia: {ar.estado_evidencia}"),
        Linea(f"Desglose del puntaje (ordena la atención; no es una probabilidad de verdad ni de pérdida): {desglose}"),
    ]
    if ar.siguientes_pasos:
        s5.append(Linea("Siguientes pasos"))
        s5 += [Linea(x, 1) for x in ar.siguientes_pasos]
    s5.append(Linea("La acción no aprueba ningún contenido: todo sigue siendo borrador para una decisión humana."))

    secciones = [Seccion(k, TITULOS[k], tuple(ls)) for k, ls in zip(TITULOS, (s1, s2, s3, s4, s5), strict=True)]
    return Vista(id_grupo=ficha.id_grupo, marca=ficha.marca_borrador, secciones=tuple(secciones))


def escapar_markdown(texto: str) -> str:
    """Neutraliza el Markdown y el HTML de un texto que viene de los datos (titulares, medios): se ve igual, pero no se interpreta.

    Las URL conservan sus caracteres (para que sigan siendo enlaces que escribió el sistema) salvo los que abren HTML o enlaces.
    """
    partes: list[str] = []
    ultimo = 0
    for m in URL.finditer(texto):
        partes.append(ESPECIALES_MARKDOWN.sub(r"\\\1", texto[ultimo : m.start()]))
        partes.append(ESPECIALES_EN_URL.sub(r"\\\1", m.group(0)))
        ultimo = m.end()
    partes.append(ESPECIALES_MARKDOWN.sub(r"\\\1", texto[ultimo:]))
    return "".join(partes)


def a_markdown(ficha: Ficha, cfg: ConfigVerificacion | None = None) -> str:
    """Markdown de la ficha (Jinja2 sobre la misma vista de la app): lo mismo que ve la persona, con los textos de los datos escapados."""
    v = vista(ficha, cfg)
    seguro = Vista(
        id_grupo=escapar_markdown(v.id_grupo),
        marca=v.marca,
        secciones=tuple(Seccion(s.clave, s.titulo, tuple(Linea(escapar_markdown(l.texto), l.nivel, l.desplegable) for l in s.lineas)) for s in v.secciones),
    )
    entorno = Environment(loader=FileSystemLoader(CARPETA_PLANTILLAS), autoescape=False, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)  # noqa: S701 - Markdown; el escape lo hace escapar_markdown
    return entorno.get_template(PLANTILLA).render(v=seguro)


def a_registro(ficha: Ficha, id_caso: str | None = None, estado_revision: str | None = None) -> dict[str, Any]:
    """Registro de ``fichas.jsonl`` con los campos del contrato (sección 7 del reto) y la ficha completa.

    ``id_caso`` y ``estado_revision`` los asigna la revisión humana (E1-16, ``src/exportar.py``): sin ellos son nulos.
    """
    citas = list(dict.fromkeys((c.id, c.campo) for x in (*ficha.respaldado.reportes, *ficha.respaldado.datos_oficiales, *ficha.respaldado.eventos_oficiales, *ficha.respaldado.declaraciones) for c in x.citas))
    return {
        "id_caso": id_caso,
        "modalidad": ficha.modalidad,
        "id_grupo": ficha.id_grupo,
        "ids_fuente": sorted({i for i, _ in citas if not i.startswith("GRP-")}),
        "afirmaciones": [x.model_dump(mode="json") for x in (*ficha.respaldado.reportes, *ficha.respaldado.datos_oficiales, *ficha.respaldado.eventos_oficiales, *ficha.respaldado.declaraciones)],
        "citas": [{"id": i, "campo": c} for i, c in citas],
        "puntaje": ficha.puntaje.puntaje,
        "componentes": {k: c.valor for k, c in ficha.puntaje.componentes.items()},
        "estado_evidencia": ficha.accion_recomendada.estado_evidencia,
        "borrador": ficha.borrador,
        "estado_revision": estado_revision,
        "alcance": ficha.alcance,
        "ficha": ficha.model_dump(mode="json"),
    }


def a_linea_jsonl(ficha: Ficha, id_caso: str | None = None, estado_revision: str | None = None) -> str:
    """Una línea de ``fichas.jsonl`` (JSON en una sola línea, UTF-8)."""
    return json.dumps(a_registro(ficha, id_caso, estado_revision), ensure_ascii=False, sort_keys=True)


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    """CLI: imprime la ficha de un grupo con sus cinco partes."""
    parser = argparse.ArgumentParser(description="E1-10b: ficha de evidencia de un grupo (sin LLM)")
    parser.add_argument("--grupo", required=True, help="ID del grupo (GRP-…), p. ej. uno de los del ranking de outputs/prioridad.json")
    parser.add_argument("--modalidad", choices=MODALIDADES, default=MODALIDAD_POR_DEFECTO)
    parser.add_argument("--formato", choices=FORMATOS, default=FORMATOS[0])
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    args = parser.parse_args(argv)
    if not args.base.exists():
        print(f"ERROR: no existe {args.base}: ejecute primero `poetry run python -m src.puntaje`", file=sys.stderr)
        return 1
    con = db.conectar(args.base, solo_lectura=True)
    try:
        ficha = construir_ficha(args.grupo, args.modalidad, con, emb=None)
    except (LookupError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    print(a_markdown(ficha) if args.formato == "markdown" else a_linea_jsonl(ficha), end="" if args.formato == "markdown" else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
