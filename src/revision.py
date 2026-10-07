"""Revisión humana de fichas: estados, versiones y registro de solo agregar · E1-16, etapa 7 del reto, D-46 a D-50.

Una persona **acepta, corrige o descarta** cada caso y todo queda escrito. El estado máximo es «aprobado como borrador»: no existe
ninguna acción ni estado de publicar (CLAUDE.md), y un caso aprobado conserva la marca BORRADOR.

* **Caso** (D-63): un grupo ``GRP-`` pasa a caso ``CASO-001``, ``CASO-002``… cuando se abre para revisar. El ID es correlativo, estable
  y persistente: abrir otra vez el mismo grupo devuelve el mismo caso. Un grupo sin caso está en el estado ``nuevo``.
* **Acciones y transiciones (D-46):** las de ``config/revision.yaml`` (única fuente). Cualquier otra se rechaza con
  ``TransicionNoPermitida``. Descartar exige un motivo de la lista; reabrir y rechazar un vínculo exigen un motivo escrito.
* **Registro de solo agregar (D-47):** la tabla ``revisiones`` (y ``casos`` y ``versiones``) solo recibe ``INSERT``. Este módulo no
  contiene ningún ``UPDATE`` ni ``DELETE`` (lo vigila una prueba) y el estado actual es la **última fila** de ``revisiones``.
  Las tablas viven en ``data/revision.duckdb``, aparte de ``senales.duckdb``: esa base se regenera en cada corrida del pipeline y
  borraría las revisiones.
* **Versiones (D-48):** la versión 1 es el borrador generado; cada corrección y cada regeneración crea **otra** versión y nunca
  sobrescribe una anterior (regenerar tampoco pisa una versión corregida). El estado vigente apunta a la última.
* **Corrección (D-48):** solo se edita el texto de afirmaciones y oraciones. El texto corregido se **revalida**
  (``revalidar_correccion``); cada advertencia debe ser **confirmada** por la persona o la corrección se rechaza, y las confirmadas
  quedan en el registro junto con las diferencias (antes y después).
* **Vínculo oficial rechazado:** la persona puede rechazar un vínculo mal aplicado; queda registrado, no entra en el borrador que se
  regenere y la ficha agrega un vacío que lo dice. El puntaje y el estado de evidencia no se recalculan (los guarda E1-10).
* **Revisor (D-49):** se elige de ``config/revision.yaml`` con su rol. **No hay autenticación** (fuera de alcance del reto): es una
  limitación declarada, no un control de seguridad.

Uso: ``poetry run python -m src.revision --abrir GRP-… --revisor "Nombre" [--modalidad editorial]`` · ``--estado GRP-…`` ·
``--historial CASO-001``. La exportación (Markdown, CSV de Notion, ``fichas.jsonl``) vive en ``src/exportar.py``.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import logging
import re
import sys
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel

from src import db
from src.configuracion import (
    MODALIDADES,
    RAIZ,
    ConfigRevision,
    cargar_modalidad,
    cargar_normalizacion,
    cargar_restricciones,
    cargar_revision,
)
from src.esquemas import PATRON_ID_REGISTRO, Afirmacion, AfirmacionSalida, Cita, Ficha, Oracion, PreguntaInvestigacion, VacioFicha

logger = logging.getLogger(__name__)

PREFIJOS_OFICIALES = ("IND-", "SIS-", "SBP-")
SECCIONES_DE_LISTA = ("titulares", "enfoque", "brief", "guion", "resumen_web", "copy_digital", "preguntas")
SECCIONES_UNICAS = ("titulo", "titulo_trabajo")
ORIGEN_GENERADA, ORIGEN_CORREGIDA = "generada", "corregida"
FORMATO_FECHA = "%Y-%m-%dT%H:%M:%SZ"

TABLAS = {
    "casos": """CREATE TABLE IF NOT EXISTS casos (
        id_caso VARCHAR PRIMARY KEY, id_grupo VARCHAR NOT NULL, modalidad VARCHAR NOT NULL, fecha_apertura_utc VARCHAR NOT NULL,
        UNIQUE (id_grupo, modalidad))""",
    "versiones": """CREATE TABLE IF NOT EXISTS versiones (
        id_caso VARCHAR NOT NULL, version INTEGER NOT NULL, origen VARCHAR NOT NULL, version_base INTEGER, contenido VARCHAR NOT NULL,
        fecha_utc VARCHAR NOT NULL, revisor VARCHAR NOT NULL, PRIMARY KEY (id_caso, version))""",
    "fichas_revisadas": """CREATE TABLE IF NOT EXISTS fichas_revisadas (
        id_instantanea BIGINT PRIMARY KEY, id_caso VARCHAR NOT NULL, id_revision BIGINT NOT NULL, version INTEGER, accion VARCHAR NOT NULL,
        fecha_utc VARCHAR NOT NULL, ficha VARCHAR NOT NULL)""",
    "revisiones": """CREATE TABLE IF NOT EXISTS revisiones (
        id_revision BIGINT PRIMARY KEY, id_caso VARCHAR NOT NULL, version INTEGER, accion VARCHAR NOT NULL, estado_anterior VARCHAR NOT NULL,
        estado_nuevo VARCHAR NOT NULL, revisor VARCHAR NOT NULL, rol VARCHAR NOT NULL, fecha_utc VARCHAR NOT NULL, comentario VARCHAR,
        motivo VARCHAR, diferencias VARCHAR, detalle VARCHAR)""",
}
COLUMNAS_REVISIONES = (
    "id_revision", "id_caso", "version", "accion", "estado_anterior", "estado_nuevo", "revisor", "rol", "fecha_utc", "comentario",
    "motivo", "diferencias", "detalle",
)


# ------------------------------------------------------------------ errores


class ErrorDeRevision(ValueError):
    """Una acción de revisión que no se puede aplicar."""


class ConflictoDeConcurrencia(ErrorDeRevision):
    """Otra sesión escribió en el registro al mismo tiempo: no se guardó nada y hay que recargar (L1)."""


class TransicionNoPermitida(ErrorDeRevision):
    """La acción no parte del estado actual del caso (``config/revision.yaml``)."""


class MotivoObligatorio(ErrorDeRevision):
    """Falta el motivo (o el comentario que exige) una acción que lo requiere, o el motivo no está en la lista."""


class RevisorDesconocido(ErrorDeRevision):
    """El revisor no está en la lista de ``config/revision.yaml`` para la modalidad del caso (D-49)."""


class AdvertenciasSinConfirmar(ErrorDeRevision):
    """La corrección trae advertencias del validador que la persona no confirmó (D-48)."""

    def __init__(self, advertencias: Sequence[Advertencia]) -> None:
        self.advertencias = list(advertencias)
        super().__init__("la corrección tiene advertencias sin confirmar: " + " | ".join(a.id for a in advertencias))


# ------------------------------------------------------------------ modelos


@dataclass(frozen=True)
class Caso:
    id_caso: str
    id_grupo: str
    modalidad: str
    fecha_apertura_utc: str


@dataclass(frozen=True)
class Fila:
    """Una fila de ``revisiones``: lo que hizo una persona, cuándo y qué estado produjo."""

    id_revision: int
    id_caso: str
    version: int | None
    accion: str
    estado_anterior: str
    estado_nuevo: str
    revisor: str
    rol: str
    fecha_utc: str
    comentario: str | None
    motivo: str | None
    diferencias: list[dict[str, str]]
    detalle: dict[str, Any]


@dataclass(frozen=True)
class Instantanea:
    """La ``Ficha`` tal como estaba cuando una acción la revisó (M2): lo que se exporta es esto, no lo que diga la base de hoy."""

    id_instantanea: int
    id_caso: str
    id_revision: int
    version: int | None
    accion: str
    fecha_utc: str
    ficha: Ficha


@dataclass(frozen=True)
class Version:
    id_caso: str
    version: int
    origen: str
    version_base: int | None
    contenido: dict[str, Any]
    fecha_utc: str
    revisor: str


@dataclass(frozen=True)
class Advertencia:
    """Un problema que el validador ve en un texto corregido; la persona decide si lo confirma."""

    clave: str
    mensaje: str

    @property
    def id(self) -> str:
        return f"{self.clave}: {self.mensaje}"


@dataclass(frozen=True)
class Elemento:
    """Un texto editable de un borrador: su clave, el texto y a qué afirmaciones o registros se apoya."""

    clave: str
    texto: str
    afirmaciones: tuple[str, ...] = ()
    citas: tuple[tuple[str, str], ...] = ()


@dataclass
class _Resumen:
    estado: str
    version: int | None
    filas: list[Fila] = field(default_factory=list)


# ------------------------------------------------------------------ utilidades


def ahora_utc() -> datetime:
    return datetime.now(UTC)


def _iso(fecha: datetime) -> str:
    return fecha.astimezone(UTC).strftime(FORMATO_FECHA)


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


def _a_dict(paquete: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    return paquete.model_dump(mode="json") if isinstance(paquete, BaseModel) else copy.deepcopy(dict(paquete))


def ruta_de_revision(demo: bool, cfg: ConfigRevision | None = None) -> Path:
    """Dónde viven las revisiones: la base real, o la de la demo (que nunca se mezcla con la real)."""
    cfg = cfg or cargar_revision()
    return RAIZ / (cfg.almacen.base_demo if demo else cfg.almacen.base)


def rutas_de_exportacion(demo: bool, cfg: ConfigRevision | None = None, raiz: Path = RAIZ) -> tuple[Path, Path]:
    """``(carpeta de Markdown y CSV, fichas.jsonl)`` de la exportación real o de la demo (X31: nunca las mismas)."""
    e = (cfg or cargar_revision()).exportacion
    return (raiz / (e.carpeta_demo if demo else e.carpeta), raiz / (e.fichas_jsonl_demo if demo else e.fichas_jsonl))


def huellas_de_exportacion(demo: bool, cfg: ConfigRevision | None = None, raiz: Path = RAIZ) -> list[Path]:
    """Lo ya exportado que recuerda qué ``CASO-`` existieron, aunque se borre la base de revisiones (M1)."""
    return list(rutas_de_exportacion(demo, cfg, raiz))


# ------------------------------------------------------------------ elementos editables y revalidación (D-48)


def elementos_editables(contenido: Mapping[str, Any]) -> dict[str, Elemento]:
    """Los textos de un borrador que una persona puede corregir, por clave estable.

    ``afirmaciones.A1`` (cita registros) · ``titulo`` / ``titulo_trabajo`` · ``titulares.0`` … ``copy_digital.2`` (citan afirmaciones)
    · ``preguntas.0``. Los marcadores ``[VISUAL: …]`` del guion no se editan: los pone el código (CLAUDE.md).
    """
    editables: dict[str, Elemento] = {}
    marcador = cargar_restricciones().marcador_visual
    for a in contenido.get("afirmaciones") or []:
        editables[f"afirmaciones.{a['id']}"] = Elemento(f"afirmaciones.{a['id']}", a["texto"], citas=tuple((c["id"], c["campo"]) for c in a.get("citas", [])))
    for clave in SECCIONES_UNICAS:
        o = contenido.get(clave)
        if o:
            editables[clave] = Elemento(clave, o["texto"], afirmaciones=tuple(o.get("afirmaciones", [])))
    for seccion in SECCIONES_DE_LISTA:
        for i, o in enumerate(contenido.get(seccion) or []):
            if marcador in o["texto"]:
                continue
            editables[f"{seccion}.{i}"] = Elemento(f"{seccion}.{i}", o["texto"], afirmaciones=tuple(o.get("afirmaciones", [])))
    return editables


def aplicar_ediciones(contenido: Mapping[str, Any], cambios: Mapping[str, str]) -> dict[str, Any]:
    """Copia del borrador con los textos nuevos; el original no se toca."""
    nuevo = copy.deepcopy(dict(contenido))
    for clave, texto in cambios.items():
        if clave.startswith("afirmaciones."):
            for a in nuevo["afirmaciones"]:
                if f"afirmaciones.{a['id']}" == clave:
                    a["texto"] = texto
        elif clave in SECCIONES_UNICAS:
            nuevo[clave]["texto"] = texto
        else:
            seccion, i = clave.rsplit(".", 1)
            nuevo[seccion][int(i)]["texto"] = texto
    return nuevo


def _paquete_ligero(contenido: Mapping[str, Any]) -> tuple[list[AfirmacionSalida], dict[str, Any]]:
    """Las afirmaciones y las secciones de un borrador como los objetos que valida ``src/validador.py`` (sin más reglas que las suyas)."""
    afirmaciones = [AfirmacionSalida.model_validate(a) for a in contenido.get("afirmaciones") or []]
    secciones: dict[str, Any] = {}
    for nombre in SECCIONES_UNICAS:
        if contenido.get(nombre):
            secciones[nombre] = Oracion.model_validate(contenido[nombre])
    for nombre in SECCIONES_DE_LISTA:
        if contenido.get(nombre):
            secciones[nombre] = [PreguntaInvestigacion.model_validate(x) if nombre == "preguntas" else Oracion.model_validate(x) for x in contenido[nombre]]
    return afirmaciones, secciones


def _rechazos_del_borrador(entrada: Any, contenido: Mapping[str, Any], secciones_a_revisar: Collection[str]) -> list[tuple[str, Rechazo]]:
    """``(clave, rechazo)`` de ``src/validador.py`` sobre las afirmaciones del borrador y sobre las secciones pedidas."""
    from src import validador as v

    ctx = v.Contexto(entrada, cargar_modalidad(entrada.modalidad).grupos_restricciones)
    afirmaciones, secciones = _paquete_ligero(contenido)
    crudas = [Afirmacion(id=a.id, tipo=a.tipo, texto=a.texto, citas=[Cita(id=c.id, campo=c.campo) for c in a.citas], base=a.base) for a in afirmaciones if a.texto.strip()]   # un texto vacío ya es una advertencia propia
    salida = [(f"afirmaciones.{r.item}", r) for r in v.validar_afirmaciones(crudas, ctx).rechazos]
    ctx.afirmaciones = {a.id: a for a in afirmaciones}              # las afirmaciones tal como quedaron, para juzgar las oraciones que las citan
    for nombre in secciones_a_revisar:
        if nombre in secciones:
            salida += [(nombre, r) for r in v.validar_seccion(nombre, secciones[nombre], ctx)]
    return salida


def revalidar_correccion(
    entrada: Any, antes: Mapping[str, Any], despues: Mapping[str, Any], claves: Collection[str], cfg: ConfigRevision | None = None
) -> list[Advertencia]:
    """Revalida el texto corregido con ``src/validador.py`` y devuelve las advertencias que la persona debe confirmar (D-48).

    Es el **único** punto de la revisión que llama a la validación. Cada rechazo del validador (cita, cifras y fechas contra la evidencia,
    comillas literales, causalidad, acusaciones, frases prohibidas, atribución, límites de la sección…) se muestra como advertencia con su
    mensaje; la persona la confirma o la corrección no se guarda. Solo cuentan los rechazos **nuevos**: los que el borrador no tenía antes de
    la corrección. Se revisan las afirmaciones, las secciones editadas y las que citan una afirmación editada (su texto ya no
    necesariamente cabe en lo que ahora dice). Lista vacía = nada que confirmar.
    """
    cfg = cfg or cargar_revision()
    claves = set(claves)
    editadas = {k.split(".", 1)[1] for k in claves if k.startswith("afirmaciones.")}
    secciones = {k.rsplit(".", 1)[0] if "." in k else k for k in claves if not k.startswith("afirmaciones.")}
    for nombre in (*SECCIONES_UNICAS, *SECCIONES_DE_LISTA):
        valor = despues.get(nombre)
        valor = [valor] if isinstance(valor, Mapping) else valor or []
        if editadas & {i for o in valor if isinstance(o, Mapping) for i in o.get("afirmaciones", [])}:
            secciones.add(nombre)
    previos = {(c, r.regla, r.motivo) for c, r in _rechazos_del_borrador(entrada, antes, secciones)}
    primera_clave = {s: next((k for k in sorted(claves) if k == s or k.startswith(f"{s}.")), s) for s in secciones}
    avisos: list[Advertencia] = []
    for texto_vacio in [k for k, e in elementos_editables(despues).items() if k in claves and not e.texto.strip()]:
        avisos.append(Advertencia(texto_vacio, cfg.correccion.advertencia_vacio))
    for clave, r in _rechazos_del_borrador(entrada, despues, secciones):
        if (clave, r.regla, r.motivo) in previos:
            continue
        aviso = Advertencia(primera_clave.get(clave, clave), f"[{r.regla}] {r.mensaje}")
        if aviso not in avisos:
            avisos.append(aviso)
    return avisos


# ------------------------------------------------------------------ el registro


class Revisiones:
    """Las revisiones de una base DuckDB: casos, versiones y el registro de solo agregar.

    ``ruta`` es ``data/revision.duckdb`` (o la de la demo). ``base_fichas`` es ``senales.duckdb`` (para armar la ficha de un caso al
    revalidar o regenerar). ``ahora`` se inyecta en las pruebas. Cada acción es una transacción: o queda escrita entera o no queda.
    """

    def __init__(
        self, ruta: Path | str, base_fichas: Path | str | None = None, cfg: ConfigRevision | None = None, ahora: Callable[[], datetime] | None = None,
        *, demo: bool = False, huellas: Sequence[Path] = (),
    ) -> None:
        self.ruta = Path(ruta)
        self.demo = demo                                   # la demo exporta a otras rutas (X31)
        self.huellas = [Path(p) for p in huellas]          # lo ya exportado: también recuerda qué CASO- existieron (M1)
        self.registro = self.ruta.with_suffix(".casos.csv")  # registro de casos de solo agregar, aparte de la base (M1)
        self.base_fichas = Path(base_fichas) if base_fichas else RAIZ / "data" / cargar_normalizacion().salida.base_de_datos
        self.cfg = cfg or cargar_revision()
        self.ahora = ahora or ahora_utc
        self._transiciones = self.cfg.transiciones()

    # ---- conexión

    @contextmanager
    def _conexion(self, escribir: bool = False) -> Iterator[Any]:
        if not escribir and not self.ruta.exists():
            yield None
            return
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self.ruta))
        try:
            for ddl in TABLAS.values():
                con.execute(ddl)
            yield con
        finally:
            con.close()

    @contextmanager
    def _transaccion(self) -> Iterator[Any]:
        with self._conexion(True) as con:
            con.execute("BEGIN TRANSACTION")
            try:
                yield con
                con.execute("COMMIT")
            except (duckdb.TransactionException, duckdb.ConstraintException) as exc:
                self._deshacer(con)
                raise ConflictoDeConcurrencia("Otra persona actuó sobre este caso al mismo tiempo: no se guardó nada. Recargue la pantalla y vuelva a intentar.") from exc
            except BaseException:
                self._deshacer(con)
                raise

    @staticmethod
    def _deshacer(con: Any) -> None:
        try:
            con.execute("ROLLBACK")
        except duckdb.Error:  # una transacción abortada puede haberse deshecho sola
            logger.debug("rollback innecesario")

    @staticmethod
    def _filas(con: Any, sql: str, parametros: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = con.execute(sql, list(parametros))
        nombres = [d[0] for d in cur.description]
        return [dict(zip(nombres, f, strict=True)) for f in cur.fetchall()]

    # ---- lectura

    def casos(self) -> list[Caso]:
        with self._conexion() as con:
            return [] if con is None else [Caso(**f) for f in self._filas(con, "SELECT * FROM casos ORDER BY id_caso")]

    def caso(self, id_caso: str) -> Caso:
        with self._conexion() as con:
            filas = [] if con is None else self._filas(con, "SELECT * FROM casos WHERE id_caso = ?", [id_caso])
        if not filas:
            raise ErrorDeRevision(f"{id_caso}: no existe ese caso")
        return Caso(**filas[0])

    def caso_de_grupo(self, id_grupo: str, modalidad: str) -> Caso | None:
        with self._conexion() as con:
            filas = [] if con is None else self._filas(con, "SELECT * FROM casos WHERE id_grupo = ? AND modalidad = ?", [id_grupo, modalidad])
        return Caso(**filas[0]) if filas else None

    def historial(self, id_caso: str) -> list[Fila]:
        with self._conexion() as con:
            filas = [] if con is None else self._filas(con, "SELECT * FROM revisiones WHERE id_caso = ? ORDER BY id_revision", [id_caso])
        return [_fila(f) for f in filas]

    def todas_las_filas(self) -> list[Fila]:
        with self._conexion() as con:
            filas = [] if con is None else self._filas(con, "SELECT * FROM revisiones ORDER BY id_revision")
        return [_fila(f) for f in filas]

    def estado(self, id_caso: str) -> str:
        """El estado actual de un caso: ``estado_nuevo`` de su última fila de ``revisiones``."""
        historial = self.historial(id_caso)
        return historial[-1].estado_nuevo if historial else self.cfg.estado_inicial

    def estado_de_grupo(self, id_grupo: str, modalidad: str) -> str:
        """Estado de un grupo: el de su caso, o ``nuevo`` si todavía no se abrió."""
        caso = self.caso_de_grupo(id_grupo, modalidad)
        return self.estado(caso.id_caso) if caso else self.cfg.estado_inicial

    def versiones(self, id_caso: str) -> list[Version]:
        with self._conexion() as con:
            filas = [] if con is None else self._filas(con, "SELECT * FROM versiones WHERE id_caso = ? ORDER BY version", [id_caso])
        return [Version(**{**f, "contenido": json.loads(f["contenido"])}) for f in filas]

    def version_actual(self, id_caso: str) -> Version | None:
        versiones = self.versiones(id_caso)
        return versiones[-1] if versiones else None

    def vinculos_rechazados(self, id_caso: str) -> set[str]:
        """Los vínculos oficiales que la persona rechazó y no restauró (se obtienen plegando el registro, fila por fila)."""
        rechazados: set[str] = set()
        for f in self.historial(id_caso):
            if f.accion == "rechazar_vinculo":
                rechazados.add(f.detalle["id_evidencia"])
            elif f.accion == "restaurar_vinculo":
                rechazados.discard(f.detalle["id_evidencia"])
        return rechazados

    # ---- reglas comunes

    def _rol(self, revisor: str, modalidad: str) -> str:
        for r in self.cfg.revisores:
            if r.nombre == revisor and r.modalidad == modalidad:
                return r.rol
        raise RevisorDesconocido(f"«{revisor}» no está en la lista de revisores de la modalidad {modalidad} (config/revision.yaml)")

    def _comprobar(self, accion: str, estado: str, motivo: str | None, comentario: str | None) -> str:
        """Valida transición y motivo; devuelve el estado al que llega la acción."""
        a = self.cfg.acciones[accion]
        if (estado, a.hacia) not in self._transiciones[accion]:
            raise TransicionNoPermitida(f"«{a.etiqueta}» no se puede aplicar a un caso «{estado}» (solo desde: {', '.join(a.desde)})")
        if a.motivo == "lista":
            if not motivo or motivo not in self.cfg.motivos_descarte:
                raise MotivoObligatorio(f"«{a.etiqueta}» exige un motivo de la lista: {' · '.join(self.cfg.motivos_descarte)}")
            if motivo in self.cfg.motivos_con_comentario and not (comentario or "").strip():
                raise MotivoObligatorio(f"el motivo «{motivo}» exige un comentario que explique")
        elif a.motivo == "texto" and not (motivo or "").strip():
            raise MotivoObligatorio(f"«{a.etiqueta}» exige un motivo escrito")
        return a.hacia

    def _estado_en(self, con: Any, id_caso: str) -> str:
        f = self._filas(con, "SELECT estado_nuevo FROM revisiones WHERE id_caso = ? ORDER BY id_revision DESC LIMIT 1", [id_caso])
        return f[0]["estado_nuevo"] if f else self.cfg.estado_inicial

    def _insertar(
        self, con: Any, caso: Caso, accion: str, revisor: str, *, estado: str, hacia: str, version: int | None, comentario: str | None = None,
        motivo: str | None = None, diferencias: Sequence[Mapping[str, str]] = (), detalle: Mapping[str, Any] | None = None, ficha: Ficha | None = None,
    ) -> None:
        siguiente = int(con.execute("SELECT coalesce(max(id_revision), 0) + 1 FROM revisiones").fetchone()[0])
        con.execute(
            "INSERT INTO revisiones VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                siguiente, caso.id_caso, version, accion, estado, hacia, revisor, self._rol(revisor, caso.modalidad), _iso(self.ahora()),
                (comentario or "").strip() or None, (motivo or "").strip() or None, _json(list(diferencias)), _json(dict(detalle or {})),
            ],
        )
        if ficha is not None:                                # la ficha que esta acción revisó, guardada tal cual (M2)
            n = int(con.execute("SELECT coalesce(max(id_instantanea), 0) + 1 FROM fichas_revisadas").fetchone()[0])
            con.execute("INSERT INTO fichas_revisadas VALUES (?,?,?,?,?,?,?)", [n, caso.id_caso, siguiente, version, accion, _iso(self.ahora()), ficha.model_dump_json()])

    def _insertar_version(self, con: Any, caso: Caso, contenido: Mapping[str, Any], origen: str, revisor: str, base: int | None) -> int:
        n = int(con.execute("SELECT coalesce(max(version), 0) + 1 FROM versiones WHERE id_caso = ?", [caso.id_caso]).fetchone()[0])
        etiquetado = {**contenido, "id_caso": caso.id_caso, "version": n}      # el paquete lleva el CASO- y su versión (docs/salidas.md)
        con.execute("INSERT INTO versiones VALUES (?,?,?,?,?,?,?)", [caso.id_caso, n, origen, base, _json(etiquetado), _iso(self.ahora()), revisor])
        return n

    def _version_en(self, con: Any, id_caso: str) -> int | None:
        f = self._filas(con, "SELECT max(version) AS v FROM versiones WHERE id_caso = ?", [id_caso])
        return f[0]["v"] if f else None

    def _accion_simple(
        self, id_caso: str, accion: str, revisor: str, *, comentario: str | None = None, motivo: str | None = None,
        detalle: Mapping[str, Any] | None = None, ficha: Ficha | None = None,
    ) -> Fila:
        caso = self.caso(id_caso)
        with self._transaccion() as con:
            estado = self._estado_en(con, id_caso)
            hacia = self._comprobar(accion, estado, motivo, comentario)
            self._rol(revisor, caso.modalidad)
            self._insertar(con, caso, accion, revisor, estado=estado, hacia=hacia, version=self._version_en(con, id_caso), comentario=comentario, motivo=motivo, detalle=detalle, ficha=ficha)
        return self.historial(id_caso)[-1]

    # ---- acciones (D-46)

    def abrir(self, id_grupo: str, modalidad: str, revisor: str, *, paquete: BaseModel | Mapping[str, Any] | None = None, comentario: str | None = None) -> Caso:
        """Abre un grupo para revisar: nace el ``CASO-`` (estado «en revisión»). Si ya estaba abierto devuelve el mismo caso.

        ``paquete`` es el borrador generado (si hay): queda como la versión 1.
        """
        if modalidad not in MODALIDADES:
            raise ErrorDeRevision(f"modalidad desconocida: {modalidad}")
        self._rol(revisor, modalidad)
        if (existente := self.caso_de_grupo(id_grupo, modalidad)) is not None:
            return existente
        ficha = self._construir(id_grupo, modalidad, ())          # un grupo que no existe no se abre: la ficha queda guardada desde el inicio (M2)
        try:
            with self._transaccion() as con:
                hacia = self._comprobar("abrir", self.cfg.estado_inicial, None, comentario)
                n = self._siguiente_numero(con)
                caso = Caso(f"{self.cfg.casos.prefijo}{n:0{self.cfg.casos.ancho}d}", id_grupo, modalidad, _iso(self.ahora()))
                con.execute("INSERT INTO casos VALUES (?,?,?,?)", [caso.id_caso, caso.id_grupo, caso.modalidad, caso.fecha_apertura_utc])
                version = self._insertar_version(con, caso, _a_dict(paquete), ORIGEN_GENERADA, revisor, None) if paquete is not None else None
                self._insertar(con, caso, "abrir", revisor, estado=self.cfg.estado_inicial, hacia=hacia, version=version, comentario=comentario, ficha=ficha)
        except ConflictoDeConcurrencia:
            if (existente := self.caso_de_grupo(id_grupo, modalidad)) is not None:  # otra sesión abrió el mismo grupo: es ese caso
                return existente
            raise
        self._registrar(caso)                                  # solo después del COMMIT: un conflicto o un fallo nunca deja una fila fantasma
        return caso

    # ---- numeración: un CASO- nunca se reutiliza (M1)

    def _numeros_conocidos(self, con: Any) -> list[int]:
        """Todos los números de caso que se conocen: la base, el registro de casos y lo que ya se exportó (CSV, JSONL y ``CASO-NNN.md``)."""
        patron = re.compile(rf"{re.escape(self.cfg.casos.prefijo)}(\d+)")
        textos: list[str] = [id_caso for (id_caso,) in con.execute("SELECT id_caso FROM casos").fetchall()]
        for ruta in [self.registro, *self.huellas]:
            if ruta.is_dir():
                textos += [p.name for p in ruta.iterdir()]
                textos += [p.read_text(encoding="utf-8", errors="ignore") for p in ruta.glob("*.csv")]
            elif ruta.is_file():
                textos.append(ruta.read_text(encoding="utf-8", errors="ignore"))
        return [int(n) for t in textos for n in patron.findall(t)]

    def _siguiente_numero(self, con: Any) -> int:
        """Máximo de los números conocidos + 1: sigue valiendo aunque se borre ``data/revision.duckdb``."""
        return max(self._numeros_conocidos(con), default=0) + 1

    def _registrar(self, caso: Caso) -> None:
        """Agrega el caso al registro (CSV de solo agregar, junto a la base), **después** de confirmar la transacción.

        Si el proceso muere entre el ``COMMIT`` y esta línea, el caso existe en la base pero no en el registro: la numeración sigue a salvo
        mientras la base exista, y el próximo número sale del máximo de lo conocido.
        """
        nuevo = not self.registro.exists()
        self.registro.parent.mkdir(parents=True, exist_ok=True)
        with self.registro.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            if nuevo:
                w.writerow(["id_caso", "id_grupo", "modalidad", "fecha_apertura_utc"])
            w.writerow([caso.id_caso, caso.id_grupo, caso.modalidad, caso.fecha_apertura_utc])

    def aceptar(self, id_caso: str, revisor: str, comentario: str | None = None) -> Fila:
        """«Aprobar como borrador»: el estado máximo. La ficha y el borrador conservan la marca BORRADOR.

        Guarda la ficha tal como se aprobó; si el grupo ya no existe en la base actual (huérfano) queda la última ficha revisada.
        """
        caso = self.caso(id_caso)
        try:
            ficha: Ficha | None = self._construir(caso.id_grupo, caso.modalidad, sorted(self.vinculos_rechazados(id_caso)))
        except ErrorDeRevision:
            ficha = None
        return self._accion_simple(id_caso, "aceptar", revisor, comentario=comentario, ficha=ficha)

    def pedir_evidencia(self, id_caso: str, revisor: str, vacios: Sequence[str], comentario: str | None = None, motivo: str | None = None) -> Fila:
        """Pasa a «requiere evidencia». Enlaza los vacíos de la ficha que lo motivan (sus códigos); si la ficha no tiene ninguno, exige un motivo escrito."""
        enlazados = [v for v in vacios if str(v).strip()]
        if not enlazados and not (motivo or "").strip():
            raise MotivoObligatorio(f"«{self.cfg.acciones['pedir_evidencia'].etiqueta}» exige enlazar al menos un vacío de la ficha o, si no tiene ninguno, un motivo escrito")
        return self._accion_simple(id_caso, "pedir_evidencia", revisor, comentario=comentario, motivo=motivo, detalle={"vacios": enlazados})

    def descartar(self, id_caso: str, revisor: str, motivo: str | None, comentario: str | None = None) -> Fila:
        """Descarta el caso; el motivo es obligatorio y de la lista de ``config/revision.yaml``."""
        return self._accion_simple(id_caso, "descartar", revisor, comentario=comentario, motivo=motivo)

    def reabrir(self, id_caso: str, revisor: str, motivo: str | None, comentario: str | None = None) -> Fila:
        """Vuelve a «en revisión» un caso que estaba pidiendo evidencia, aprobado o descartado; el motivo es obligatorio."""
        return self._accion_simple(id_caso, "reabrir", revisor, comentario=comentario, motivo=motivo)

    def rechazar_vinculo(self, id_caso: str, revisor: str, id_evidencia: str, motivo: str | None, comentario: str | None = None) -> Fila:
        """La persona rechaza un vínculo oficial mal aplicado: queda registrado y se excluye de los borradores que se regeneren."""
        self._comprobar("rechazar_vinculo", self.estado(id_caso), motivo, comentario)
        if not PATRON_ID_REGISTRO.match(id_evidencia) or not id_evidencia.startswith(PREFIJOS_OFICIALES):
            raise ErrorDeRevision(f"{id_evidencia}: no es un dato oficial (IND-, SIS- o SBP-)")
        if id_evidencia in self.vinculos_rechazados(id_caso):
            raise ErrorDeRevision(f"{id_evidencia}: ya estaba rechazado")
        caso = self.caso(id_caso)
        ficha = self._construir(caso.id_grupo, caso.modalidad, sorted({*self.vinculos_rechazados(id_caso), id_evidencia}))
        return self._accion_simple(id_caso, "rechazar_vinculo", revisor, comentario=comentario, motivo=motivo, detalle={"id_evidencia": id_evidencia}, ficha=ficha)

    def restaurar_vinculo(self, id_caso: str, revisor: str, id_evidencia: str, motivo: str | None, comentario: str | None = None) -> Fila:
        """Deshace un rechazo (queda como una fila más: el registro no se edita)."""
        self._comprobar("restaurar_vinculo", self.estado(id_caso), motivo, comentario)
        if id_evidencia not in self.vinculos_rechazados(id_caso):
            raise ErrorDeRevision(f"{id_evidencia}: no estaba rechazado")
        caso = self.caso(id_caso)
        ficha = self._construir(caso.id_grupo, caso.modalidad, sorted(self.vinculos_rechazados(id_caso) - {id_evidencia}))
        return self._accion_simple(id_caso, "restaurar_vinculo", revisor, comentario=comentario, motivo=motivo, detalle={"id_evidencia": id_evidencia}, ficha=ficha)

    # ---- ficha del caso

    def ficha_del_caso(self, caso: Caso, emb: Any = None) -> Ficha:
        """La ficha del grupo sin los vínculos que la persona rechazó, con el vacío que lo dice."""
        return self._construir(caso.id_grupo, caso.modalidad, sorted(self.vinculos_rechazados(caso.id_caso)), emb)

    def _construir(self, id_grupo: str, modalidad: str, rechazados: Sequence[str], emb: Any = None) -> Ficha:
        """Arma la ficha desde la base de señales de hoy. Si el grupo ya no existe (el pipeline lo volvió a agrupar), lo dice con claridad."""
        from src.ficha import construir_ficha

        vc = self.cfg.vinculo_rechazado
        extra = [VacioFicha(codigo=vc.codigo, texto=vc.texto.format(n=len(rechazados)), verificacion=vc.verificacion)] if rechazados else []
        try:
            con = db.conectar(self.base_fichas, solo_lectura=True)
            try:
                return construir_ficha(id_grupo, modalidad, con, emb=emb, excluir_vinculos=list(rechazados), vacios_extra=extra)
            finally:
                con.close()
        except (LookupError, duckdb.Error) as exc:
            raise ErrorDeRevision(
                f"{id_grupo}: el grupo ya no existe en la base de señales actual (el pipeline volvió a agrupar los titulares). "
                "El caso se conserva con su última ficha revisada: se puede exportar, aprobar, descartar o reabrir, pero no regenerar ni cambiar vínculos."
            ) from exc

    def instantaneas(self, id_caso: str) -> list[Instantanea]:
        """Las fichas guardadas del caso, de la más vieja a la más nueva (solo se agregan)."""
        with self._conexion() as con:
            filas = [] if con is None else self._filas(con, "SELECT * FROM fichas_revisadas WHERE id_caso = ? ORDER BY id_instantanea", [id_caso])
        return [Instantanea(**{**f, "ficha": Ficha.model_validate_json(f["ficha"])}) for f in filas]

    def ficha_revisada(self, id_caso: str) -> Ficha | None:
        """La última ficha que una persona revisó (la que se exporta); ``None`` si el caso no tiene ninguna guardada."""
        guardadas = self.instantaneas(id_caso)
        return guardadas[-1].ficha if guardadas else None

    def entrada_del_caso(self, caso: Caso, emb: Any = None) -> Any:
        """La entrada de la generación (``EntradaFicha``) de la ficha del caso, sin los vínculos rechazados."""
        from src.generacion import desde_ficha

        return desde_ficha(self.ficha_del_caso(caso, emb))

    # ---- versiones: corregir y regenerar (D-48)

    def revisar_correccion(self, id_caso: str, ediciones: Mapping[str, str], entrada: Any = None) -> list[Advertencia]:
        """Las advertencias que produciría una corrección, sin guardar nada (la pantalla las muestra para que la persona las confirme)."""
        caso = self.caso(id_caso)
        v = self._version_para_corregir(id_caso)
        cambios = self._cambios(v, ediciones)
        return revalidar_correccion(entrada if entrada is not None else self.entrada_del_caso(caso), v.contenido, aplicar_ediciones(v.contenido, cambios), cambios)

    def _version_para_corregir(self, id_caso: str) -> Version:
        v = self.version_actual(id_caso)
        if v is None:
            raise ErrorDeRevision(f"{id_caso}: no hay borrador que corregir; regenere el borrador primero")
        return v

    @staticmethod
    def _cambios(v: Version, ediciones: Mapping[str, str]) -> dict[str, str]:
        editables = elementos_editables(v.contenido)
        desconocidas = sorted(set(ediciones) - set(editables))
        if desconocidas:
            raise ErrorDeRevision(f"no se puede corregir: {', '.join(desconocidas)}")
        cambios = {k: t.strip() for k, t in ediciones.items() if t.strip() != editables[k].texto}
        if not cambios:
            raise ErrorDeRevision("la corrección no cambia ningún texto")
        return cambios

    def corregir(
        self, id_caso: str, revisor: str, ediciones: Mapping[str, str], *, confirmadas: Collection[str] = (), comentario: str | None = None, entrada: Any = None
    ) -> Version:
        """Guarda una corrección como **nueva versión** (la original se conserva) y el caso sigue «en revisión».

        El texto corregido se revalida; cada advertencia debe venir en ``confirmadas`` (sus ``id``) o se lanza ``AdvertenciasSinConfirmar``.
        Quedan en el registro las diferencias (antes y después) y las advertencias que la persona confirmó.
        """
        caso = self.caso(id_caso)
        self._comprobar("corregir", self.estado(id_caso), None, comentario)
        v = self._version_para_corregir(id_caso)
        cambios = self._cambios(v, ediciones)
        nuevo = aplicar_ediciones(v.contenido, cambios)
        avisos = revalidar_correccion(entrada if entrada is not None else self.entrada_del_caso(caso), v.contenido, nuevo, cambios)
        if pendientes := [a for a in avisos if a.id not in set(confirmadas)]:
            raise AdvertenciasSinConfirmar(pendientes)
        antes = elementos_editables(v.contenido)
        diferencias = [{"clave": k, "antes": antes[k].texto, "despues": t} for k, t in cambios.items()]
        prefijo = f"{self.cfg.correccion.prefijo_afirmaciones}."
        detalle = {
            "version_base": v.version,
            "n_afirmaciones": len(v.contenido.get("afirmaciones") or []),
            "afirmaciones_editadas": sum(1 for k in cambios if k.startswith(prefijo)),
            "advertencias_confirmadas": [a.id for a in avisos],
        }
        with self._transaccion() as con:
            estado = self._estado_en(con, id_caso)
            hacia = self._comprobar("corregir", estado, None, comentario)
            n = self._insertar_version(con, caso, nuevo, ORIGEN_CORREGIDA, revisor, v.version)
            self._insertar(con, caso, "corregir", revisor, estado=estado, hacia=hacia, version=n, comentario=comentario, diferencias=diferencias, detalle=detalle)
        return self.version_actual(id_caso)  # type: ignore[return-value]

    def regenerar(
        self, id_caso: str, revisor: str, *, generador: Callable[..., Any] | None = None, solo_cache: bool = True, comentario: str | None = None, **opciones: Any
    ) -> Version:
        """Regenera el borrador **sin** los vínculos rechazados y lo guarda como una versión nueva.

        Nunca sobrescribe una versión (tampoco una corregida): la anterior sigue en ``versiones``. ``generador`` por defecto es
        ``generacion.generar_paquete``; si no hay borrador en caché o la acción no genera, su excepción sube sin escribir nada.
        """
        from src.generacion import generar_paquete

        caso = self.caso(id_caso)
        self._comprobar("regenerar", self.estado(id_caso), None, comentario)
        self._rol(revisor, caso.modalidad)
        from src.generacion import desde_ficha

        ficha = self.ficha_del_caso(caso)
        entrada = desde_ficha(ficha)
        generador = generador or generar_paquete
        paquete = generador(caso.id_grupo, caso.modalidad, solo_cache=solo_cache, base=self.base_fichas, entrada=entrada, **opciones)
        previa = self.version_actual(id_caso)
        with self._transaccion() as con:
            estado = self._estado_en(con, id_caso)
            hacia = self._comprobar("regenerar", estado, None, comentario)
            n = self._insertar_version(con, caso, _a_dict(paquete), ORIGEN_GENERADA, revisor, previa.version if previa else None)
            detalle = {"version_base": previa.version if previa else None, "vinculos_excluidos": sorted(self.vinculos_rechazados(id_caso)), "solo_cache": solo_cache}
            self._insertar(con, caso, "regenerar", revisor, estado=estado, hacia=hacia, version=n, comentario=comentario, detalle=detalle, ficha=ficha)
        return self.version_actual(id_caso)  # type: ignore[return-value]


def _fila(f: Mapping[str, Any]) -> Fila:
    return Fila(**{**f, "diferencias": json.loads(f["diferencias"] or "[]"), "detalle": json.loads(f["detalle"] or "{}")})


# ------------------------------------------------------------------ CLI


def principal(argv: list[str] | None = None) -> int:
    """CLI mínima: abrir un grupo como caso, ver el estado de un grupo o el historial de un caso."""
    cfg = cargar_revision()
    parser = argparse.ArgumentParser(description="E1-16: revisión humana (la revisión se hace en la app; esta CLI solo abre y consulta)")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--abrir", metavar="GRP-…", help="abre el grupo como caso (CASO-…)")
    grupo.add_argument("--estado", metavar="GRP-…", help="estado de revisión del grupo")
    grupo.add_argument("--historial", metavar="CASO-…", help="filas de la tabla revisiones del caso")
    parser.add_argument("--modalidad", choices=MODALIDADES, default="editorial")
    parser.add_argument("--revisor", help=f"uno de: {', '.join(sorted({r.nombre for r in cfg.revisores}))} (sin autenticación, D-49)")
    parser.add_argument("--demo", action="store_true", help="usa la base de revisiones de la demo (aparte de la real)")
    parser.add_argument("--revision", type=Path, default=None, help="por defecto la real, o la de la demo con --demo")
    parser.add_argument("--base", type=Path, default=None, help="senales.duckdb (por defecto la del pipeline)")
    args = parser.parse_args(argv)
    rev = Revisiones(args.revision or ruta_de_revision(args.demo, cfg), args.base, cfg, demo=args.demo, huellas=huellas_de_exportacion(args.demo, cfg))
    try:
        if args.abrir:
            if not args.revisor:
                parser.error("--abrir exige --revisor")
            caso = rev.abrir(args.abrir, args.modalidad, args.revisor)
            print(f"{caso.id_caso} · {caso.id_grupo} · {rev.estado(caso.id_caso)}")
        elif args.estado:
            print(rev.estado_de_grupo(args.estado, args.modalidad))
        else:
            for f in rev.historial(args.historial):
                print(f"{f.id_revision}\t{f.fecha_utc}\t{f.accion}\t{f.estado_anterior} -> {f.estado_nuevo}\t{f.revisor} ({f.rol})\tv{f.version}\t{f.motivo or ''}")
    except ErrorDeRevision as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(principal())
