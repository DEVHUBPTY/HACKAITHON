"""Vínculo de un grupo de sismos con eventos de USGS · E1-09b, etapa 3 del reto (D-33).

Un evento de USGS es **contexto** de la noticia, nunca prueba de daños ni de causa. Reglas:

* **Solo subtemas con ``fuente: usgs``** en ``vinculos.yaml`` (hoy ``sismos``). Lluvias, inundaciones o daños jamás se
  vinculan a USGS: ``vincular_grupo`` devuelve ``None`` y el llamador sigue con su regla de indicadores.
* **Coincidencia:** el evento queda a ``ventana_coincidencia_dias`` o menos de alguna noticia del grupo (en horas, no en
  días calendario) y su magnitud es al menos ``usgs.minmagnitude`` de ``fuentes.yaml``.
* **Fecha de la noticia:** ``campos_fecha`` de ``reglas_v1.3.yaml`` (publicación antes que detección, como en E1-08). Si una
  noticia solo tiene ``fecha_deteccion`` se usa, pero el resultado lo declara (``origenes_fecha``) y la regla lo dice:
  nunca se sustituye una por otra en silencio. Sin ninguna fecha: ``sin_dato_en_periodo``.
* **Resultado:** un candidato → ``vinculado``; varios → ``candidatos_ambiguos`` (se listan todos, ninguno se elige);
  ninguno → ``sin_evento_coincidente``; noticias fuera del periodo extraído → ``fuera_de_cobertura``.
* **Cobertura:** de ``usgs.starttime`` a ``usgs.endtime`` de ``fuentes.yaml`` (UTC). Las noticias fuera del periodo no se
  comparan; si todas están fuera, el motivo es ``fuera_de_cobertura``.

Las horas se guardan en UTC; ``hora_panama`` convierte solo para mostrar. Este módulo es puro: no escribe la tabla
``vinculos``; ``a_filas_vinculo`` deja el resultado listo para ella.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src import db
from src.agrupacion import fecha_de, origen_de_fecha
from src.configuracion import ConfigFuentes, ConfigVinculos

logger = logging.getLogger(__name__)

FUENTE_USGS = "usgs"            # valor de ``fuente`` en vinculos.yaml
TIPO_EVENTO = "evento"          # clave de ``tipos_relacion`` y valor de ``vinculos.tipo``
SEPARADOR_LISTA = ","           # listas dentro de una columna de texto (ids_noticia), igual que E1-08
SEGUNDOS_POR_HORA = 3_600
HORAS_POR_DIA = 24
ORIGEN_DETECCION = "deteccion"  # nombre de campo sin el prefijo ``fecha_`` (ver ``agrupacion.origen_de_fecha``)

VINCULADO = "vinculado"
CANDIDATOS_AMBIGUOS = "candidatos_ambiguos"
SIN_EVENTO = "sin_evento_coincidente"
FUERA_DE_COBERTURA = "fuera_de_cobertura"
SIN_DATO_EN_PERIODO = "sin_dato_en_periodo"
MOTIVOS_DEL_MODULO = (CANDIDATOS_AMBIGUOS, SIN_EVENTO, FUERA_DE_COBERTURA, SIN_DATO_EN_PERIODO)


# ------------------------------------------------------------------ datos


@dataclass(frozen=True)
class EventoUsgs:
    """Un evento de ``eventos.geojson``: ``place`` es el texto original de USGS, sin traducir ni recortar."""

    id: str                         # ``SIS-<id USGS>``
    magnitud: float
    profundidad_km: float | None
    place: str | None
    hora_utc: datetime
    estado: str | None              # ``automatic`` o ``reviewed``
    url: str

    def hora_panama(self, vinculos: ConfigVinculos) -> str:
        """Hora local para mostrar en la interfaz (``sismos.zona_horaria``); el dato sigue en UTC."""
        local = self.hora_utc.astimezone(ZoneInfo(vinculos.sismos.zona_horaria))
        return local.strftime(vinculos.sismos.formato_hora)


@dataclass(frozen=True)
class Candidato:
    """Un evento candidato y su distancia en horas a la noticia más cercana del grupo."""

    evento: EventoUsgs
    diferencia_horas: float


@dataclass(frozen=True)
class ResultadoSismos:
    """Lo que se sabe de un grupo de sismos frente a USGS; ``estado`` es ``vinculado`` o un motivo sin vínculo."""

    id_grupo: str
    estado: str
    candidatos: tuple[Candidato, ...]       # vacío salvo ``vinculado`` (uno) y ``candidatos_ambiguos`` (todos)
    origenes_fecha: tuple[str, ...]         # de qué campo salió cada fecha usada: ``publicacion`` o ``deteccion``
    regla: str
    limitacion: str

    @property
    def motivo_sin_vinculo(self) -> str | None:
        return None if self.estado == VINCULADO else self.estado


# ------------------------------------------------------------------ carga


def cargar_eventos(ruta: Path) -> list[EventoUsgs]:
    """Eventos de ``eventos.geojson`` (ya validado en la carga E1-02), ordenados por hora y luego por ID."""
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    eventos = []
    for rasgo in contenido.get("features", []):
        p = rasgo["properties"]
        hora = datetime.fromisoformat(p["time"].replace("Z", "+00:00"))
        eventos.append(
            EventoUsgs(
                id=p["id"],
                magnitud=float(p["magnitude"]),
                profundidad_km=None if p.get("depth") is None else float(p["depth"]),  # un nulo es nulo, nunca 0
                place=p.get("place"),
                hora_utc=hora if hora.tzinfo else hora.replace(tzinfo=UTC),
                estado=p.get("status"),
                url=p["url"],
            )
        )
    return sorted(eventos, key=lambda e: (e.hora_utc, e.id))


def _utc(texto: str) -> datetime:
    fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=UTC)


def cobertura(fuentes: ConfigFuentes) -> tuple[datetime, datetime]:
    """Periodo que cubrió la extracción de USGS, en UTC (``usgs.starttime`` a ``usgs.endtime``)."""
    return _utc(fuentes.usgs.starttime), _utc(fuentes.usgs.endtime)


def subtema_dominante(noticias: Sequence[Mapping[str, Any]]) -> str | None:
    """Subtema más frecuente entre las noticias del grupo; en empate, el primero por orden alfabético."""
    cuentas = Counter(n["subtema_clasificado"] for n in noticias if n.get("subtema_clasificado"))
    if not cuentas:
        return None
    mayor = max(cuentas.values())
    return sorted(s for s, c in cuentas.items() if c == mayor)[0]


# ------------------------------------------------------------------ vínculo


def limitacion_fija(vinculos: ConfigVinculos) -> str:
    """Texto fijo de limitaciones del vínculo (``sismos.limitaciones``)."""
    return " ".join(vinculos.sismos.limitaciones)


def aplica(subtema: str | None, vinculos: ConfigVinculos) -> bool:
    """``True`` solo si el subtema se vincula a USGS según ``vinculos.yaml``."""
    regla = vinculos.vinculos.get(subtema) if subtema else None
    return regla is not None and regla.fuente == FUENTE_USGS and regla.relacion == TIPO_EVENTO


def _regla(vinculos: ConfigVinculos, fuentes: ConfigFuentes, origenes: Sequence[str]) -> str:
    texto = vinculos.sismos.plantilla_regla.format(
        dias=vinculos.ventana_coincidencia_dias, magnitud_minima=fuentes.usgs.minmagnitude
    )
    if ORIGEN_DETECCION in origenes:
        texto = f"{texto} {vinculos.sismos.nota_fecha_deteccion}"
    return texto


def vincular_grupo(
    id_grupo: str,
    subtema: str | None,
    noticias: Sequence[Mapping[str, Any]],
    eventos: Sequence[EventoUsgs],
    vinculos: ConfigVinculos,
    fuentes: ConfigFuentes,
    campos_fecha: Sequence[str],
) -> ResultadoSismos | None:
    """Vincula un grupo con eventos de USGS; ``None`` si su subtema no se vincula a USGS (lluvias, daños, etc.).

    ``noticias`` son las filas del grupo con ``fecha_publicacion`` y ``fecha_deteccion``; ``campos_fecha`` fija cuál se usa
    primero (``reglas_v1.3.yaml``). Una noticia sin ninguna fecha no aporta. No elige entre candidatos.
    """
    if not aplica(subtema, vinculos):
        return None

    inicio, fin = cobertura(fuentes)
    fechas = [(fecha_de(n, campos_fecha), origen_de_fecha(n, campos_fecha)) for n in noticias]
    fechas = [(f, o) for f, o in fechas if f is not None and o is not None]
    dentro = [(f, o) for f, o in fechas if inicio <= f <= fin]
    origenes = tuple(sorted({o for _, o in dentro}))
    limitacion = limitacion_fija(vinculos)

    def resultado(estado: str, candidatos: Sequence[Candidato] = ()) -> ResultadoSismos:
        return ResultadoSismos(id_grupo, estado, tuple(candidatos), origenes, _regla(vinculos, fuentes, origenes), limitacion)

    if not fechas:
        return resultado(SIN_DATO_EN_PERIODO)
    if not dentro:
        return resultado(FUERA_DE_COBERTURA)

    ventana = timedelta(days=vinculos.ventana_coincidencia_dias)
    candidatos = []
    for evento in eventos:
        if evento.magnitud < fuentes.usgs.minmagnitude:
            continue
        distancia = min(abs(evento.hora_utc - f) for f, _ in dentro)
        if distancia <= ventana:
            candidatos.append(Candidato(evento, round(distancia.total_seconds() / SEGUNDOS_POR_HORA, 2)))
    candidatos.sort(key=lambda c: (c.diferencia_horas, c.evento.id))

    if not candidatos:
        return resultado(SIN_EVENTO)
    return resultado(VINCULADO if len(candidatos) == 1 else CANDIDATOS_AMBIGUOS, candidatos)


# ------------------------------------------------------------------ salida para la tabla ``vinculos``


def a_filas_vinculo(resultado: ResultadoSismos) -> list[dict[str, Any]]:
    """Filas con las columnas ``id_grupo, id_evidencia, tipo, regla, limitacion, motivo_sin_vinculo``.

    * ``vinculado``: una fila con el ``SIS-`` y ``motivo_sin_vinculo`` nulo.
    * ``candidatos_ambiguos``: una fila por candidato, todas con ``motivo_sin_vinculo = candidatos_ambiguos``
      (ninguno está elegido; el motivo avisa que no son un vínculo firme).
    * Sin vínculo: una fila con ``id_evidencia`` nulo y el motivo.
    """
    base = {
        "id_grupo": resultado.id_grupo,
        "tipo": TIPO_EVENTO,
        "regla": resultado.regla,
        "limitacion": resultado.limitacion,
        "motivo_sin_vinculo": resultado.motivo_sin_vinculo,
    }
    if not resultado.candidatos:
        return [{**base, "id_evidencia": None}]
    return [{**base, "id_evidencia": c.evento.id} for c in resultado.candidatos]


def ficha_de_evento(candidato: Candidato, vinculos: ConfigVinculos) -> dict[str, Any]:
    """Campos para mostrar un evento: ``place`` original, magnitud, profundidad, hora de Panamá y estado."""
    e = candidato.evento
    return {
        "id": e.id,
        "place": e.place,
        "magnitud": e.magnitud,
        "profundidad_km": e.profundidad_km,
        "hora_utc": e.hora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hora_panama": e.hora_panama(vinculos),
        "estado": e.estado,
        "url": e.url,
        "diferencia_horas": candidato.diferencia_horas,
    }


# ------------------------------------------------------------------ sobre la base


def vincular_base(
    ruta_base: Path,
    eventos: Sequence[EventoUsgs],
    vinculos: ConfigVinculos,
    fuentes: ConfigFuentes,
    campos_fecha: Sequence[str],
) -> list[ResultadoSismos]:
    """Resultado de cada grupo de ``senales.duckdb`` cuyo subtema dominante se vincula a USGS (solo lectura)."""
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        grupos = db.leer_tabla(con, "grupos", "id_grupo")
        por_id = {n["id_noticia"]: n for n in db.leer_tabla(con, "noticias")}
    finally:
        con.close()
    resultados = []
    for g in grupos:
        filas = [por_id[i] for i in str(g["ids_noticia"]).split(SEPARADOR_LISTA) if i in por_id]
        r = vincular_grupo(g["id_grupo"], subtema_dominante(filas), filas, eventos, vinculos, fuentes, campos_fecha)
        if r is not None:
            resultados.append(r)
    logger.info("grupos vinculables a USGS: %d", len(resultados))
    return resultados
