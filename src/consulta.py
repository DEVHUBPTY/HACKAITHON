"""Consulta en español sobre el corpus, con abstención cuando no hay evidencia suficiente (E1-11, CU-04, T06, D-66).

Qué hace y qué no:

* **Recupera** por similitud semántica (embeddings locales, ``src/embeddings.py``) o por palabras clave (BM25, el
  baseline de D-66) sobre el MISMO corpus: titulares útiles (no ruido), indicadores del Banco Mundial y sismos de USGS.
* **Decide la abstención ANTES de cualquier llamada a un LLM**, en este orden (todo en ``config/consulta.yaml``):
  1. la consulta se sanea: un fragmento ``<evidencia>…</evidencia>`` es dato pegado, se descarta y la entrada queda marcada;
  2. patrones de instrucción (D-69) y reglas por patrón (leer el artículo, autoría, cifra de periodo relativo);
  3. cifra de un indicador oficial: si falta el país, el indicador o el año exactos, se abstiene y se ofrece el último
     dato disponible; un periodo de sismos fuera de la cobertura de USGS también se rechaza;
  4. similitud máxima bajo el umbral del método.
* **Redacta sin LLM.** La respuesta con contenido es extractiva y determinista: cada oración es una ``Afirmacion``
  (``src/esquemas.py``) con su cita ID + campo. Un titular es una *declaración* atribuida al medio; solo los datos
  oficiales son *hechos*. Ningún LLM interviene en esta tarea. ``responder(..., validador=...)`` recibe cualquier ``Validador`` y, si
  devuelve problemas, **la respuesta no se emite** (se abstiene). El validador por defecto (``validar_citas``) solo
  comprueba que cada cita exista en el corpus, que el campo sea citable y que el tipo sea coherente con el registro. Como la respuesta
  es extractiva (no la redacta un modelo), no pasa por las reglas de redacción de ``src/validador.py``; sí pasa por su regla de leyenda (D-51):
  ``Consultor`` no se construye con una leyenda que ``validar_leyenda_texto`` rechace frente a la de ``config/restricciones.yaml``.
* Toda salida lleva la leyenda de alcance de D-51 y es un BORRADOR.

Uso: ``poetry run python -m src.consulta "¿Qué medios reportaron …?" [--metodo semantica|bm25] [--json]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from src import db
from src.configuracion import (
    RAIZ,
    ConfigConsulta,
    ConfigRestricciones,
    cargar_clasificacion,
    cargar_consulta,
    cargar_fuentes,
    cargar_restricciones,
)
from src.embeddings import Embeddings, crear
from src.esquemas import Afirmacion, Cita
from src.limpieza import plano
from src.validador import validar_leyenda_texto

logger = logging.getLogger(__name__)

Metodo = Literal["semantica", "bm25"]
METODOS: tuple[Metodo, ...] = ("semantica", "bm25")
TipoDocumento = Literal["noticia", "indicador", "sismo"]
Estado = Literal["responde", "abstencion"]
RUTA_SINTETICOS = RAIZ / "benchmark" / "sinteticos.csv"

# Campos que una cita puede nombrar por tipo de registro (CLAUDE.md: cita válida = ID + campo).
CAMPOS_CITABLES: dict[str, frozenset[str]] = {
    "noticia": frozenset({"titulo_original", "titulo_limpio", "medio", "fecha_publicacion"}),
    "indicador": frozenset({"valor", "anio", "unidad"}),
    "sismo": frozenset({"magnitude", "place", "time"}),
}
CAMPOS_TITULAR = ("titulo_original", "titulo_limpio")   # campos cuyo valor debe aparecer literal en la afirmación
TIPO_POR_PREFIJO = {"NOT-": "noticia", "SYN-": "noticia", "IND-": "indicador", "SIS-": "sismo"}
PATRON_ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
PATRON_TOKEN = re.compile(r"\w+")


# ------------------------------------------------------------------ corpus


@dataclass(frozen=True)
class Documento:
    """Un registro buscable. ``texto`` es lo que se indexa; ``datos`` conserva los campos citables."""

    id: str
    tipo: TipoDocumento
    texto: str
    datos: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


@dataclass
class Corpus:
    """Documentos buscables más las tablas oficiales completas (el resolutor de cifras necesita las que no se indexan)."""

    documentos: list[Documento]
    nombres_indicador: dict[str, tuple[str, str]]   # indicador_id -> (nombre, unidad)
    indicadores: dict[tuple[str, str, int], dict[str, Any]]
    sismos: list[dict[str, Any]]
    paises_del_mundo: tuple[tuple[str, str], ...] = ()   # (nombre en español, sin tildes) de fuentes.yaml `paises_es`

    def __post_init__(self) -> None:
        self.por_id = {d.id: d for d in self.documentos}

    def ultimo_indicador(self, pais: str, indicador: str) -> dict[str, Any] | None:
        """Fila más reciente con valor no nulo (los nulos son nulos: nunca se rellenan)."""
        filas = [f for (p, i, _), f in self.indicadores.items() if p == pais and i == indicador and f["valor"] is not None]
        return max(filas, key=lambda f: f["anio"]) if filas else None


def _texto_noticia(fila: dict[str, Any]) -> str:
    return f"{fila['titulo_limpio']}. Medio: {fila['medio']}."


def cargar_corpus(
    ruta_base: Path | None = None, sinteticos: Path | None = None, cfg_fuentes: Any = None
) -> Corpus:
    """Lee la base DuckDB: noticias NO ruido (marcar, no borrar: el ruido queda fuera de la búsqueda), indicadores y sismos.

    Nunca se usa la descripción del RSS (D-31): solo titular y metadatos, así que la leyenda es ``titular_metadatos``.
    ``sinteticos`` (solo la evaluación) agrega los casos alterados de ``benchmark/sinteticos.csv``.
    """
    fuentes = cfg_fuentes or cargar_fuentes()
    nombres = {i: (v.nombre, v.unidad) for i, v in fuentes.banco_mundial.indicadores.items()}
    paises = {p: p for p in fuentes.banco_mundial.paises}
    con = db.conectar(ruta_base or db.RUTA_BASE, solo_lectura=True)
    try:
        noticias = db.leer_tabla(con, "noticias", "id_noticia")
        ind = db.leer_tabla(con, "indicadores", "id_indicador")
        sis = db.leer_tabla(con, "sismos", "id")
    finally:
        con.close()
    docs: list[Documento] = []
    for f in noticias:
        if f.get("es_ruido"):
            continue
        f = {**f, "titulo_limpio": f.get("titulo_limpio") or f["titulo"]}
        docs.append(Documento(f["id_noticia"], "noticia", _texto_noticia(f), {
            "titulo_limpio": f["titulo_limpio"], "titulo_original": f.get("titulo_original") or f["titulo"], "medio": f["medio"], "fecha_publicacion": f.get("fecha_publicacion"),
            "sospechoso_inyeccion": bool(f.get("sospechoso_inyeccion")),
        }))
    if sinteticos and sinteticos.exists():
        import csv

        with sinteticos.open(encoding="utf-8", newline="") as h:
            for f in csv.DictReader(h):
                f["titulo_limpio"] = f["titulo"]
                docs.append(Documento(f["id_noticia"], "noticia", _texto_noticia(f), {
                    "titulo_limpio": f["titulo"], "titulo_original": f["titulo"], "medio": f["medio"], "fecha_publicacion": f["fecha_publicacion"],
                    "sospechoso_inyeccion": False,
                }))
    tabla_ind: dict[tuple[str, str, int], dict[str, Any]] = {}
    for f in ind:
        tabla_ind[(f["pais_iso3"], f["indicador_id"], f["anio"])] = f
        nombre, unidad = nombres.get(f["indicador_id"], (f["indicador_id"], f.get("unidad") or ""))
        # El valor NO entra en el texto indexado: el índice solo localiza el registro, no rellena ni inventa cifras.
        docs.append(Documento(f["id_indicador"], "indicador",
                              f"Indicador oficial del Banco Mundial: {nombre} de {paises.get(f['pais_iso3'], f['pais_iso3'])}, año {f['anio']} ({unidad}).",
                              {"valor": f["valor"], "anio": f["anio"], "unidad": f.get("unidad") or unidad,
                               "indicador_id": f["indicador_id"], "pais_iso3": f["pais_iso3"], "nombre": nombre}))
    for f in sis:
        docs.append(Documento(f["id"], "sismo",
                              f"Sismo registrado por USGS de magnitud {f['magnitude']}, {f['place']}, {(f['time'] or '')[:10]}.",
                              {"magnitude": f["magnitude"], "place": f["place"], "time": f["time"]}))
    mundo = tuple((n, plano(n)) for n in fuentes.paises_es.values())
    return Corpus(docs, nombres, tabla_ind, sis, mundo)


# ------------------------------------------------------------------ búsqueda


@dataclass(frozen=True)
class Resultado:
    documento: Documento
    puntaje: float


def tokenizar(texto: str, vacias: frozenset[str], largo_minimo: int) -> list[str]:
    """Palabras sin tildes y en minúsculas, sin palabras vacías ni más cortas que ``largo_minimo`` (para BM25)."""
    return [t for t in PATRON_TOKEN.findall(plano(texto)) if t not in vacias and len(t) >= largo_minimo]


class Indice:
    """Búsqueda semántica y BM25 sobre un mismo ``Corpus``.

    El documento es el pasaje y la consulta es la consulta (prefijos de e5); los vectores salen normalizados, así que el
    producto punto es la similitud coseno.
    """

    def __init__(self, corpus: Corpus, emb: Embeddings, cfg: ConfigConsulta) -> None:
        from rank_bm25 import BM25Okapi

        self.corpus, self.emb, self.cfg = corpus, emb, cfg
        self.vacias = frozenset(cfg.recuperacion.bm25.palabras_vacias)
        self.vectores = emb.codificar([d.texto for d in corpus.documentos], "tema")
        b = cfg.recuperacion.bm25
        self.bm25 = BM25Okapi([tokenizar(d.texto, self.vacias, b.largo_minimo_token) for d in corpus.documentos], k1=b.k1, b=b.b)

    def puntajes(self, consulta: str, metodo: Metodo) -> np.ndarray:
        if metodo == "semantica":
            return self.vectores @ self.emb.codificar([consulta], "titular")[0]
        if metodo == "bm25":
            return np.asarray(self.bm25.get_scores(tokenizar(consulta, self.vacias, self.cfg.recuperacion.bm25.largo_minimo_token)), dtype=float)
        raise ValueError(f"método desconocido: {metodo!r} (use {list(METODOS)})")

    def buscar(self, consulta: str, metodo: Metodo, k: int | None = None) -> list[Resultado]:
        """Los ``k`` mejores documentos (por defecto ``top_k``), de mayor a menor puntaje; desempata el orden del corpus."""
        k = k or self.cfg.recuperacion.top_k
        p = self.puntajes(consulta, metodo)
        orden = sorted(range(len(p)), key=lambda i: (-p[i], i))[:k]
        return [Resultado(self.corpus.documentos[i], float(p[i])) for i in orden]


# ------------------------------------------------------------------ análisis de la consulta


@dataclass(frozen=True)
class Analisis:
    original: str
    limpia: str
    plana: str
    entrada_sospechosa: bool


def sanear(consulta: str, cfg: ConfigConsulta) -> Analisis:
    """Descarta lo que venga entre las marcas de evidencia (dato pegado, nunca instrucción) y marca la entrada."""
    d = cfg.delimitador_evidencia
    patron = re.compile(re.escape(d.abre) + r".*?" + re.escape(d.cierra), re.S | re.I)
    limpia, cambios = patron.subn(" ", consulta)
    sobrantes = re.compile(re.escape(d.abre) + "|" + re.escape(d.cierra), re.I)
    limpia, extra = sobrantes.subn(" ", limpia)
    limpia = re.sub(r"\s+", " ", limpia).strip()
    return Analisis(consulta, limpia, plano(limpia), bool(cambios or extra))


def _coincide(patrones: Sequence[str], texto: str) -> bool:
    return any(re.search(p, texto) for p in patrones)


def _termino_presente(termino: str, texto: str) -> bool:
    return re.search(r"\b" + re.escape(termino) + r"\b", texto) is not None


# ------------------------------------------------------------------ respuesta


class Evidencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tipo: TipoDocumento
    puntaje: float | None = None


class RespuestaConsulta(BaseModel):
    """Salida de una consulta: respuesta con afirmaciones citadas o abstención que explica qué haría falta."""

    model_config = ConfigDict(extra="forbid")

    consulta: str = Field(description="La consulta ya saneada (sin fragmentos de evidencia pegados)")
    metodo: Metodo
    estado: Estado
    motivo: str = Field(description="Código: responde | regla:<id> | inyeccion | cifra_inexistente | pais_sin_datos | ...")
    mensaje: str
    falta: str | None = Field(default=None, description="Qué información haría falta (solo en abstención)")
    afirmaciones: list[Afirmacion] = Field(default_factory=list)
    ultimo_dato_disponible: list[Afirmacion] = Field(default_factory=list)
    evidencia: list[Evidencia] = Field(default_factory=list)
    similitud_maxima: float | None = None
    entrada_sospechosa: bool = False
    advertencias: list[str] = Field(default_factory=list)
    leyenda_alcance: str
    borrador: bool = True

    @property
    def abstiene(self) -> bool:
        return self.estado == "abstencion"


Validador = Callable[[list[Afirmacion], Corpus], list[str]]


def validar_citas(afirmaciones: list[Afirmacion], corpus: Corpus) -> list[str]:
    """Validador mínimo (el completo es E1-13): cita existente, campo citable, tipo coherente y titular literal."""
    problemas: list[str] = []
    for a in afirmaciones:
        for c in a.citas:
            doc = corpus.por_id.get(c.id)
            if doc is None:
                problemas.append(f"{a.id}: la cita {c.id} no existe en el corpus")
            elif c.campo not in CAMPOS_CITABLES[doc.tipo]:
                problemas.append(f"{a.id}: el campo {c.campo!r} no es citable en {c.id}")
            elif a.tipo == "hecho" and doc.tipo == "noticia":
                problemas.append(f"{a.id}: un titular es una declaración, no un hecho ({c.id})")
            elif a.tipo == "declaración" and doc.tipo != "noticia":
                problemas.append(f"{a.id}: una declaración solo cita titulares ({c.id})")
            elif doc.tipo == "noticia" and c.campo in CAMPOS_TITULAR and doc.datos[c.campo] not in a.texto:
                problemas.append(f"{a.id}: el titular citado no aparece literal en la afirmación")
            elif doc.tipo == "noticia" and c.campo == "medio" and doc.datos["medio"] not in a.texto:
                problemas.append(f"{a.id}: el medio citado no aparece en la afirmación")
            elif doc.tipo == "noticia" and c.campo == "fecha_publicacion" and (doc.datos["fecha_publicacion"] or "")[:10] not in a.texto:
                problemas.append(f"{a.id}: la fecha citada no aparece en la afirmación")
        if not a.citas:
            problemas.append(f"{a.id}: sin citas")
    return problemas


def _mostrar(v: float, decimales: int) -> str:
    """Valor para mostrar: entero sin decimales; si no, con ``decimales`` configurados. La cita conserva el valor crudo."""
    return str(int(v)) if float(v).is_integer() else f"{v:.{decimales}f}"


def _afirmacion_noticia(i: int, d: Documento) -> Afirmacion:
    fecha = (d.datos.get("fecha_publicacion") or "")[:10]
    cuando = f" ({fecha}, fecha de publicación en UTC)" if fecha else ""
    texto = f"{d.datos['medio']} titula: «{d.datos['titulo_original']}»{cuando}."
    campos = ["titulo_original", "medio", *(["fecha_publicacion"] if fecha else [])]
    return Afirmacion(id=f"A{i}", tipo="declaración", texto=texto, citas=[Cita(id=d.id, campo=c) for c in campos])


def _afirmacion_indicador(i: int, d: Documento, pais: str, dec: int) -> Afirmacion:
    dd = d.datos
    texto = f"{dd['nombre']} de {pais} en {dd['anio']}: {_mostrar(dd['valor'], dec)} {dd['unidad']} (Banco Mundial; dato anual)."
    return Afirmacion(id=f"A{i}", tipo="hecho", texto=texto, citas=[Cita(id=d.id, campo="valor")])


def _afirmacion_sismo(i: int, d: Documento, dec: int) -> Afirmacion:
    dd = d.datos
    texto = f"USGS registró un sismo de magnitud {_mostrar(dd['magnitude'], dec)} el {dd['time']}, «{dd['place']}»."
    return Afirmacion(id=f"A{i}", tipo="hecho", texto=texto, citas=[Cita(id=d.id, campo="magnitude")])


# ------------------------------------------------------------------ consulta de cifras oficiales


@dataclass
class Oficial:
    """Resultado de interpretar una consulta de cifra de un indicador del Banco Mundial."""

    registros: list[Documento] = field(default_factory=list)
    abstencion: tuple[str, str, str] | None = None     # (código, mensaje, falta)
    ultimos: list[Documento] = field(default_factory=list)


def _nombres_pais(cfg: ConfigConsulta) -> dict[str, list[str]]:
    return cfg.datos_oficiales.paises


def paises_no_cubiertos(texto_plano: str, cfg: ConfigConsulta, corpus: Corpus) -> list[str]:
    """Países de ``paises_es`` (fuentes.yaml) que la consulta nombra y que NO están en la cuadrícula del Banco Mundial."""
    cubiertos = {t for ts in cfg.datos_oficiales.paises.values() for t in ts}
    fuera = []
    for nombre, p in corpus.paises_del_mundo:
        if p not in cubiertos and _termino_presente(p, texto_plano):
            fuera.append(nombre)
    return fuera


def _indicadores_pedidos(texto: str, cfg: ConfigConsulta) -> list[str]:
    return [i for i, ts in cfg.datos_oficiales.indicadores.items() if any(_termino_presente(t, texto) for t in ts)]


def _paises_pedidos(texto: str, cfg: ConfigConsulta) -> list[str]:
    encontrados = [p for p, ts in _nombres_pais(cfg).items() if any(_termino_presente(t, texto) for t in ts)]
    return encontrados or [cfg.datos_oficiales.pais_por_defecto]


def _nombre_pais(iso3: str, cfg: ConfigConsulta) -> str:
    return cfg.datos_oficiales.nombres_pais[iso3]


def _es_consulta_de_noticias(texto: str, cfg: ConfigConsulta) -> bool:
    return _coincide(cfg.datos_oficiales.intencion_noticia, texto)


def _indicadores_relacionados(texto: str, cfg: ConfigConsulta) -> list[str]:
    return [i for i, ts in cfg.datos_oficiales.relacionados.items() if any(_termino_presente(t, texto) for t in ts)]


def _calificadores_pedidos(texto: str, cfg: ConfigConsulta) -> list[str]:
    """Calificadores (edad, sexo, territorio…) que la consulta nombra y que un total nacional no desagrega."""
    return [t for ts in cfg.datos_oficiales.calificadores.values() for t in ts if _termino_presente(t, texto)]


def _ofrecer(corpus: Corpus, paises: list[str], indicadores: list[str], anios: list[int]) -> list[Documento]:
    """Dato ofrecido como relacionado: el del año pedido si existe con valor; si no, el último disponible de la serie."""
    salida: dict[str, Documento] = {}
    for pais in paises:
        for ind in indicadores:
            fila = next((corpus.indicadores[(pais, ind, a)] for a in anios if corpus.indicadores.get((pais, ind, a), {}).get("valor") is not None), None)
            fila = fila or corpus.ultimo_indicador(pais, ind)
            if fila:
                salida[fila["id_indicador"]] = corpus.por_id[fila["id_indicador"]]
    return list(salida.values())


def resolver_cifra(an: Analisis, corpus: Corpus, cfg: ConfigConsulta) -> Oficial | None:
    """Interpreta una consulta de cifra de indicador (país, indicador, año). ``None`` si no es una consulta de ese tipo.

    Si falta alguno de los tres campos exactos, no se inventa ni se rellena: se abstiene y se ofrece el último dato
    disponible de esa serie.
    """
    if _es_consulta_de_noticias(an.plana, cfg):
        return None
    indicadores = _indicadores_pedidos(an.plana, cfg)
    relacionados = [] if indicadores else _indicadores_relacionados(an.plana, cfg)
    if not indicadores and not relacionados:
        return None
    pais_defecto = cfg.datos_oficiales.pais_por_defecto
    sin_datos = paises_no_cubiertos(an.plana, cfg, corpus)
    paises = _paises_pedidos(an.plana, cfg)
    anios = sorted({int(a) for a in PATRON_ANIO.findall(an.plana)})
    variacion = any(_termino_presente(v, an.plana) for v in cfg.datos_oficiales.variacion)

    if sin_datos:
        ultimos = [u for i in (indicadores or relacionados) if (u := corpus.ultimo_indicador(pais_defecto, i))]
        nombres = ", ".join(sin_datos)
        return Oficial(
            abstencion=("pais_sin_datos", f"El corpus no tiene datos de {nombres}: la cuadrícula del Banco Mundial cubre solo {', '.join(_nombre_pais(p, cfg) for p in cfg.datos_oficiales.paises)}.",
                        f"Una serie oficial de {nombres} para ese indicador; este corpus no la incluye."),
            ultimos=[corpus.por_id[u["id_indicador"]] for u in ultimos],
        )

    calificadores = _calificadores_pedidos(an.plana, cfg)
    if calificadores:
        nombres = ", ".join(calificadores)
        return Oficial(
            abstencion=("calificador_no_disponible",
                        f"Los indicadores del Banco Mundial son totales nacionales: no hay desagregación por «{nombres}»; la cifra nacional no responde lo que se pide.",
                        f"Una serie oficial desagregada por «{nombres}» (por ejemplo, de la encuesta de hogares del INEC); este corpus no la incluye."),
            ultimos=_ofrecer(corpus, paises, indicadores or relacionados, anios),
        )
    if relacionados:
        nombres = ", ".join(corpus.nombres_indicador[i][0] for i in relacionados)
        return Oficial(
            abstencion=("indicador_no_disponible",
                        f"El corpus no tiene esa magnitud: el indicador más cercano es «{nombres}» (variación anual, no el nivel); se ofrece solo como dato relacionado.",
                        "El nivel de esa magnitud en la serie oficial; este corpus no lo incluye."),
            ultimos=_ofrecer(corpus, paises, relacionados, anios),
        )

    registros: list[Documento] = []
    faltan: list[tuple[str, str, int]] = []
    ultimos: dict[str, Documento] = {}
    for pais in paises:
        for ind in indicadores:
            ultimo = corpus.ultimo_indicador(pais, ind)
            pedidos = list(anios)
            if not pedidos:
                if ultimo is None:
                    faltan.append((pais, ind, 0))
                    continue
                pedidos = [ultimo["anio"]]
            if variacion and len(pedidos) == 1:
                pedidos = [pedidos[0] - 1, *pedidos]
            for anio in pedidos:
                fila = corpus.indicadores.get((pais, ind, anio))
                if fila is not None and fila["valor"] is not None:
                    registros.append(corpus.por_id[fila["id_indicador"]])
                elif anio in anios or not variacion:   # el año previo de una variación es un extra: no obliga
                    faltan.append((pais, ind, anio))
            if ultimo is not None:
                ultimos[f"{pais}|{ind}"] = corpus.por_id[ultimo["id_indicador"]]
    if faltan:
        partes = []
        for pais, ind, anio in faltan:
            nombre = corpus.nombres_indicador[ind][0]
            partes.append(f"{nombre} de {_nombre_pais(pais, cfg)}" + (f" en {anio}" if anio else ""))
        ofrecidos = [ultimos[f"{p}|{i}"] for p, i, _ in faltan if f"{p}|{i}" in ultimos]
        unicos = list({d.id: d for d in ofrecidos}.values())
        cobertura = ", ".join(f"{d.datos['nombre']}: último año con dato {d.datos['anio']}" for d in unicos)
        return Oficial(
            abstencion=("cifra_inexistente", f"No hay dato de {'; '.join(partes)} en el Banco Mundial cargado (publica cifras anuales{'; ' + cobertura if cobertura else ''}).",
                        "El valor oficial de ese país, indicador y año; el corpus no lo tiene (no se estima ni se rellena)."),
            ultimos=unicos,
        )
    unicos_reg = list({d.id: d for d in registros}.values())
    return Oficial(registros=sorted(unicos_reg, key=lambda d: (d.datos["indicador_id"], d.datos["pais_iso3"], d.datos["anio"])))


def resolver_sismos(an: Analisis, corpus: Corpus, cfg: ConfigConsulta) -> Oficial | None:
    """Consulta de sismos con un año fuera de la cobertura de USGS: se abstiene y ofrece el último sismo registrado."""
    if _es_consulta_de_noticias(an.plana, cfg) or not corpus.sismos:
        return None
    if not any(_termino_presente(p, an.plana) for p in cfg.datos_oficiales.sismos.palabras):
        return None
    anios = sorted({int(a) for a in PATRON_ANIO.findall(an.plana)})
    tiempos = [s["time"] for s in corpus.sismos if s["time"]]
    desde, hasta = min(tiempos), max(tiempos)
    fuera = [a for a in anios if not int(desde[:4]) <= a <= int(hasta[:4])]
    if not fuera:
        return None
    ultimo = max(corpus.sismos, key=lambda s: s["time"] or "")
    return Oficial(
        abstencion=("periodo_fuera_de_cobertura",
                    f"El catálogo de USGS cargado cubre del {desde[:10]} al {hasta[:10]}; no hay datos de {', '.join(map(str, fuera))}.",
                    f"Sismos de {', '.join(map(str, fuera))}: requiere extraer ese periodo de USGS, que este corpus no incluye."),
        ultimos=[corpus.por_id[ultimo["id"]]],
    )


# ------------------------------------------------------------------ decisión


def regla_aplicable(an: Analisis, cfg: ConfigConsulta, restricciones: ConfigRestricciones) -> tuple[str, str, str] | None:
    """Primera regla de abstención por patrón que aplica: ``(código, motivo, necesita)``. Sin LLM ni embeddings."""
    if cfg.inyeccion.activa and _coincide(restricciones.inyeccion.patrones, an.plana):
        return "inyeccion", cfg.inyeccion.motivo, cfg.inyeccion.necesita
    for r in cfg.reglas:
        if _coincide(r.patrones, an.plana) and (not r.ademas or _coincide(r.ademas, an.plana)):
            return f"regla:{r.id}", r.motivo, r.necesita
    return None


class Consultor:
    """Responde consultas con abstención previa. Sin LLM: el único modelo es el de embeddings, local."""

    def __init__(
        self, indice: Indice, cfg: ConfigConsulta | None = None, restricciones: ConfigRestricciones | None = None,
        validador: Validador | None = validar_citas,
    ) -> None:
        self.indice = indice
        self.cfg = cfg or indice.cfg
        self.restricciones = restricciones or cargar_restricciones()
        self.validador = validador
        self.leyenda = self.restricciones.leyendas_alcance.titular_metadatos
        if problemas := validar_leyenda_texto(self.leyenda, uso_descripcion=False):
            raise ValueError("leyenda de alcance inválida para la consulta: " + "; ".join(r.mensaje for r in problemas))

    # -- abstención ------------------------------------------------------------------------------------

    def _abstencion(self, an: Analisis, metodo: Metodo, codigo: str, mensaje: str, falta: str,
                    ultimos: Sequence[Documento] = (), similitud: float | None = None) -> RespuestaConsulta:
        ofrecidos = []
        for i, d in enumerate(ultimos, 1):
            ofrecidos.append(_afirmacion_indicador(i, d, _nombre_pais(d.datos["pais_iso3"], self.cfg), self.cfg.respuesta.decimales_valor) if d.tipo == "indicador"
                             else _afirmacion_sismo(i, d, self.cfg.respuesta.decimales_valor))
        return RespuestaConsulta(
            consulta=an.limpia, metodo=metodo, estado="abstencion", motivo=codigo, mensaje=mensaje, falta=falta,
            ultimo_dato_disponible=ofrecidos, similitud_maxima=similitud, entrada_sospechosa=an.entrada_sospechosa,
            evidencia=[Evidencia(id=d.id, tipo=d.tipo) for d in ultimos], leyenda_alcance=self.leyenda,
            advertencias=self._advertencias(an, ultimos),
        )

    def _advertencias(self, an: Analisis, docs: Sequence[Documento]) -> list[str]:
        av = []
        if an.entrada_sospechosa:
            av.append("La consulta traía un fragmento de evidencia pegado: se descartó y no se obedeció.")
        if any(d.tipo == "noticia" for d in docs):
            av.append(self.cfg.respuesta.advertencia_titular)
        if any(d.tipo == "indicador" for d in docs):
            av.append(self.cfg.respuesta.advertencia_anual)
        if any(d.tipo == "noticia" and d.datos.get("sospechoso_inyeccion") for d in docs):
            av.append("Algún titular citado está marcado como posible inyección de instrucciones; se trata como dato.")
        return av

    def decidir_previa(self, consulta: str) -> tuple[Analisis, tuple[str, str, str, list[Documento]] | None, Oficial | None]:
        """Todo lo que se decide ANTES de buscar y de cualquier LLM: ``(análisis, abstención | None, cifra oficial | None)``."""
        an = sanear(consulta, self.cfg)
        if not an.limpia:
            return an, ("consulta_vacia", "La consulta no contiene una pregunta.", "Una pregunta en español sobre la evidencia disponible.", []), None
        regla = regla_aplicable(an, self.cfg, self.restricciones)
        if regla:
            return an, (*regla, []), None
        corpus = self.indice.corpus
        oficial = resolver_cifra(an, corpus, self.cfg) or resolver_sismos(an, corpus, self.cfg)
        if oficial and oficial.abstencion:
            codigo, mensaje, falta = oficial.abstencion
            return an, (codigo, mensaje, falta, oficial.ultimos), oficial
        return an, None, oficial

    # -- respuesta -------------------------------------------------------------------------------------

    def responder(self, consulta: str, metodo: Metodo = "semantica") -> RespuestaConsulta:
        an, previa, oficial = self.decidir_previa(consulta)
        if previa:
            codigo, mensaje, falta, ultimos = previa
            return self._abstencion(an, metodo, codigo, mensaje, falta, ultimos)
        if oficial and oficial.registros:                     # cifra oficial exacta: no depende de la similitud
            docs = oficial.registros
            afirmaciones = [_afirmacion_indicador(i, d, _nombre_pais(d.datos["pais_iso3"], self.cfg), self.cfg.respuesta.decimales_valor) for i, d in enumerate(docs, 1)]
            puntajes: dict[str, float | None] = {d.id: None for d in docs}
            similitud = None
        else:
            hallados = self.indice.buscar(an.limpia, metodo)
            similitud = hallados[0].puntaje if hallados else None
            umbral = self.cfg.abstencion.umbral_similitud[metodo]
            if similitud is None or similitud < umbral:
                return self._abstencion(
                    an, metodo, "similitud_baja",
                    f"No se responde: ningún registro del corpus se parece lo bastante a la consulta (similitud máxima {similitud:.3f}, umbral {umbral:.3f}, método {metodo}).",
                    "Titulares o datos oficiales que traten el tema de la consulta; el corpus no los tiene.", similitud=similitud)
            utiles = [r for r in hallados if r.puntaje >= umbral][: self.cfg.respuesta.maximo_afirmaciones]
            docs = [r.documento for r in utiles]
            puntajes = {r.documento.id: r.puntaje for r in utiles}
            afirmaciones = []
            for i, d in enumerate(docs, 1):
                if d.tipo == "noticia":
                    afirmaciones.append(_afirmacion_noticia(i, d))
                elif d.tipo == "indicador":
                    if d.datos["valor"] is None:
                        continue                              # un nulo es un nulo: no se cita ni se rellena
                    afirmaciones.append(_afirmacion_indicador(i, d, _nombre_pais(d.datos["pais_iso3"], self.cfg), self.cfg.respuesta.decimales_valor))
                else:
                    afirmaciones.append(_afirmacion_sismo(i, d, self.cfg.respuesta.decimales_valor))
            if not afirmaciones:
                return self._abstencion(an, metodo, "similitud_baja", "No se responde: lo recuperado no tiene contenido citable.",
                                        "Titulares o datos oficiales con valor para esa consulta.", similitud=similitud)
        if self.validador:
            problemas = self.validador(afirmaciones, self.indice.corpus)
            if problemas:                                     # lo que no valida, no se emite
                logger.warning("Respuesta no emitida por el validador: %s", problemas)
                return self._abstencion(an, metodo, "validador", "No se responde: las citas no pasaron la validación (" + "; ".join(problemas) + ").",
                                        "Evidencia con citas válidas (ID + campo).", similitud=similitud)
        citados = {c.id for a in afirmaciones for c in a.citas}
        evidencia = [Evidencia(id=d.id, tipo=d.tipo, puntaje=puntajes.get(d.id)) for d in docs if d.id in citados]
        return RespuestaConsulta(
            consulta=an.limpia, metodo=metodo, estado="responde", motivo="responde",
            mensaje=f"Se encontró evidencia en el corpus ({len(afirmaciones)} registro{'s' if len(afirmaciones) != 1 else ''}).",
            afirmaciones=afirmaciones, evidencia=evidencia, similitud_maxima=similitud, entrada_sospechosa=an.entrada_sospechosa,
            leyenda_alcance=self.leyenda, advertencias=self._advertencias(an, [d for d in docs if d.id in citados]),
        )


def crear_consultor(
    ruta_base: Path | None = None, cfg: ConfigConsulta | None = None, emb: Embeddings | None = None,
    sinteticos: Path | None = None, validador: Validador | None = validar_citas,
) -> Consultor:
    """Consultor con el corpus de la base, el modelo de embeddings activo de ``clasificacion.yaml`` y la configuración."""
    cfg = cfg or cargar_consulta()
    corpus = cargar_corpus(ruta_base, sinteticos)
    emb = emb or crear(cargar_clasificacion())
    return Consultor(Indice(corpus, emb, cfg), cfg, validador=validador)


# ------------------------------------------------------------------ CLI


def _imprimir(r: RespuestaConsulta) -> None:
    print(f"[{r.estado.upper()}] ({r.metodo}, {r.motivo}) {r.mensaje}")
    for a in r.afirmaciones:
        print(f"  - {a.texto}  <{', '.join(f'{c.id} · {c.campo}' for c in a.citas)}>")
    if r.falta:
        print(f"  Haría falta: {r.falta}")
    for a in r.ultimo_dato_disponible:
        print(f"  Último dato disponible: {a.texto}  <{', '.join(f'{c.id} · {c.campo}' for c in a.citas)}>")
    for av in r.advertencias:
        print(f"  Aviso: {av}")
    print(f"  Alcance: {r.leyenda_alcance} · BORRADOR")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m src.consulta "pregunta"``."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="E1-11: consulta en español con abstención")
    parser.add_argument("consulta", help="la pregunta, entre comillas")
    parser.add_argument("--metodo", choices=METODOS, default="semantica")
    parser.add_argument("--base", type=Path, default=db.RUTA_BASE)
    parser.add_argument("--json", action="store_true", help="salida JSON completa")
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero carga, normalización, limpieza y clasificación", args.base)
        return 1
    try:
        consultor = crear_consultor(args.base)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    r = consultor.responder(args.consulta, args.metodo)
    if args.json:
        print(json.dumps(r.model_dump(), ensure_ascii=False, indent=2))
    else:
        _imprimir(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
