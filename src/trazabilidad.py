"""Cinco fichas trazables · C-01: selección determinista y comprobación de la trazabilidad de punta a punta.

* ``seleccionar``: la regla de ``config/fichas_trazables.yaml`` (una ficha por caso de uso del reto, D-118, recorriendo el ranking oficial). Nadie elige
  a mano las fichas (D-101).
* ``verificar_ficha``: comprueba una ficha **contra los datos**, no contra sí misma: cada afirmación cita ``ID + campo``; cada ID existe en
  ``senales.duckdb`` (o en el CSV de la fuente) con ese campo y un valor; hay URL; las declaraciones son comillas literales del campo
  citado; hay procedencias, estado de evidencia, leyenda de alcance y marca BORRADOR; la descripción del RSS no sale (D-31) y no hay
  nombres de autores (D-32).
* ``informe``: conteos por regla con n y, cuando es una proporción, su IC de Wilson al 95 %.

Sin LLM y sin red: es código determinista sobre lo ya calculado. Lo corre ``python -m scripts.fichas_trazables``.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src import db
from src.carga import intervalo_wilson
from src.configuracion import (
    RAIZ,
    ConfigFichasTrazables,
    CriterioFichaTrazable,
    RegistroTrazable,
    cargar_normalizacion,
    cargar_restricciones,
    cargar_verificacion,
)
from src.esquemas import Ficha, RegistroFichasJsonl
from src.ficha import a_markdown, a_registro, vista

COMILLAS = re.compile(r"«([^»]+)»")
URL_VALIDA = re.compile(r"^https?://\S+$")
PARTES_DE_LA_FICHA = ("que_se_reporta", "quien_lo_reporta", "respaldado", "falta_comprobar", "accion_recomendada")

# Nombre de cada comprobación (clave del informe). El orden es el de la tabla del índice.
REGLAS = (
    "afirmacion_con_cita",
    "cita_con_id_en_datos",
    "cita_con_campo_y_valor",
    "cifra_de_conteo_coincide",
    "declaracion_literal",
    "url_presente",
    "procedencias_y_estado",
    "leyenda_de_alcance",
    "marca_borrador",
    "cinco_partes",
    "sin_descripcion_rss",
    "sin_nombres_de_autor",
    "contrato_fichas_jsonl",
    "revision_provisional_visible",
)


class ErrorDeTrazabilidad(ValueError):
    """No se puede seleccionar o comprobar (base de otra modalidad, estado sin fichas, dato ausente)."""


# ---------------------------------------------------------------------------------------------------- selección


@dataclass(frozen=True)
class Candidato:
    """Un grupo del ranking oficial con lo que necesitan los criterios de ``config/fichas_trazables.yaml`` (todo sale de ``senales.duckdb``)."""

    id_grupo: str
    posicion: int
    puntaje: float
    estado: str
    tema: str = ""
    n_titulares: int = 0
    n_procedencias: int = 0
    con_dato_oficial: bool = False
    contradicciones_abiertas: int = 0
    vacios: tuple[str, ...] = ()


@dataclass(frozen=True)
class Elegida:
    """La ficha elegida para un caso de uso y por qué: qué criterio la eligió (``criterio`` 0 = el principal; > 0 = respaldo declarado)."""

    caso_de_uso: str
    pregunta: str
    id_grupo: str
    candidato: Candidato | None        # ``None`` en un grupo fijo (su ficha sale del caso ya revisado, no del ranking de esta base)
    modalidad: str | None              # solo en un grupo fijo
    criterio: int
    criterio_texto: str
    garantia: bool = False             # se volvió a elegir para garantizar una ficha con evidencia insuficiente

    @property
    def es_respaldo(self) -> bool:
        return self.criterio > 0 or self.garantia


def candidatos(con: Any, modalidad: str) -> list[Candidato]:
    """Los grupos del ranking oficial en orden (posición, ID), con su estado de evidencia. Falla si la corrida es de otra modalidad."""
    db.exigir_modalidad_de_la_base(con, modalidad)
    filas = con.execute(
        "SELECT p.id_grupo, p.posicion, p.puntaje, e.estado, COALESCE(g.tema_clasificado, ''), g.n_titulares, e.n_procedencias, e.tiene_oficial, "
        "e.contradicciones_abiertas, e.vacios FROM puntajes p JOIN evidencia e USING (id_grupo) JOIN grupos g USING (id_grupo) "
        "WHERE e.modalidad = ? ORDER BY p.posicion, p.id_grupo",
        [modalidad],
    ).fetchall()
    return [
        Candidato(str(i), int(pos), float(p), str(e), str(tema), int(nt), int(npr), bool(of), int(ca), tuple(v["codigo"] for v in json.loads(vac or "[]")))
        for i, pos, p, e, tema, nt, npr, of, ca, vac in filas
    ]


def cumple(c: Candidato, criterio: CriterioFichaTrazable) -> bool:
    """``True`` si el grupo cumple TODAS las condiciones declaradas del criterio (un criterio vacío lo cumple cualquiera)."""
    return (
        (criterio.tema is None or c.tema == criterio.tema)
        and (criterio.estado is None or c.estado == criterio.estado)
        and (criterio.con_dato_oficial is None or c.con_dato_oficial == criterio.con_dato_oficial)
        and (criterio.contradiccion_abierta is None or (c.contradicciones_abiertas > 0) == criterio.contradiccion_abierta)
        and (criterio.mas_titulares_que_procedencias is None or (c.n_titulares > c.n_procedencias) == criterio.mas_titulares_que_procedencias)
        and (criterio.procedencias_minimas is None or c.n_procedencias >= criterio.procedencias_minimas)
        and (criterio.vacio is None or criterio.vacio in c.vacios)
    )


def _texto_criterio(criterio: CriterioFichaTrazable) -> str:
    partes = [f"{k}={v}" for k, v in criterio.model_dump(exclude_none=True).items()]
    return ", ".join(partes) if partes else "primero del ranking"


def _primero_que_cumple(ranking: Sequence[Candidato], criterios: Sequence[CriterioFichaTrazable], tomados: set[str]) -> tuple[Candidato, int] | None:
    """Prueba los criterios en orden; el primero que tiene algún grupo libre manda y gana el de mejor posición."""
    for i, criterio in enumerate(criterios):
        for c in ranking:
            if c.id_grupo not in tomados and cumple(c, criterio):
                return c, i
    return None


def seleccionar(ranking: Sequence[Candidato], cfg: ConfigFichasTrazables) -> list[Elegida]:
    """Una ficha por caso de uso (D-118), en el orden de ``cfg.seleccion.casos_de_uso``. Determinista: no depende del orden de entrada.

    Los grupos fijos (CU-05) se reservan antes; luego cada caso de uso toma el mejor grupo del ranking que cumple su primer criterio con
    candidatos, sin repetir grupos. Si ninguna ficha resulta con evidencia insuficiente, ``garantia_insuficiente`` vuelve a elegir un
    caso de uso (PDF sección 5). Falla con un mensaje si un caso de uso no tiene ningún grupo o si no queda ninguna ficha insuficiente.
    """
    reglas = cfg.seleccion
    ranking = sorted(ranking, key=lambda c: (c.posicion, c.id_grupo))     # el orden de entrada no importa: manda el del ranking oficial
    tomados: set[str] = {cu.grupo for cu in reglas.casos_de_uso if cu.grupo}
    elegidas: dict[str, Elegida] = {}
    for cu in reglas.casos_de_uso:
        if cu.grupo:
            elegidas[cu.id] = Elegida(cu.id, cu.pregunta, cu.grupo, None, cu.modalidad, 0, f"grupo fijo {cu.grupo} ({cu.modalidad})")
            continue
        hallado = _primero_que_cumple(ranking, cu.criterios, tomados)
        if hallado is None:
            raise ErrorDeTrazabilidad(f"{cu.id}: ningún grupo del ranking cumple sus criterios ({'; '.join(_texto_criterio(c) for c in cu.criterios)}); no se inventa uno")
        c, i = hallado
        tomados.add(c.id_grupo)
        elegidas[cu.id] = Elegida(cu.id, cu.pregunta, c.id_grupo, c, None, i, _texto_criterio(cu.criterios[i]))

    insuficientes = sum(e.candidato is not None and e.candidato.estado == "insuficiente" for e in elegidas.values())
    if insuficientes < reglas.minimo_insuficiente:
        g = reglas.garantia_insuficiente
        previo = elegidas[g.caso_de_uso]
        libres = tomados - ({previo.id_grupo} if previo.candidato else set())
        hallado = _primero_que_cumple(ranking, g.criterios, libres)
        if hallado is None:
            raise ErrorDeTrazabilidad("el ranking no tiene ninguna ficha con evidencia insuficiente; el reto pide al menos una (sección 5)")
        c, i = hallado
        elegidas[g.caso_de_uso] = Elegida(g.caso_de_uso, previo.pregunta, c.id_grupo, c, None, i, _texto_criterio(g.criterios[i]), garantia=True)
    resultado = [elegidas[cu.id] for cu in reglas.casos_de_uso]
    if len(resultado) < reglas.minimo_total:
        raise ErrorDeTrazabilidad(f"solo hay {len(resultado)} fichas seleccionables y se piden {reglas.minimo_total}")
    return resultado


# ---------------------------------------------------------------------------------------------------- resolución de citas


@dataclass(frozen=True)
class Registro:
    id: str
    valores: Mapping[str, Any]
    url: str | None


class Resolutor:
    """Busca un ID citado en los datos (tablas de ``senales.duckdb`` o CSV de ``data/processed``) según ``config.registros``."""

    def __init__(self, con: Any, cfg: ConfigFichasTrazables, raiz: Path = RAIZ) -> None:
        self.con = con
        self.reglas = {r.prefijo: r for r in cfg.registros}
        self.raiz = raiz
        self._csv: dict[str, dict[str, dict[str, str]]] = {}

    def regla(self, id_: str) -> RegistroTrazable | None:
        return next((r for p, r in self.reglas.items() if id_.startswith(p)), None)

    def _filas_csv(self, regla: RegistroTrazable) -> dict[str, dict[str, str]]:
        if regla.prefijo not in self._csv:
            ruta = self.raiz / regla.fuente
            indice: dict[str, dict[str, str]] = {}
            if ruta.exists():
                with ruta.open(encoding="utf-8", newline="") as f:
                    for fila in csv.DictReader(f):
                        indice[str(regla.plantilla_id).format(**fila)] = fila
            self._csv[regla.prefijo] = indice
        return self._csv[regla.prefijo]

    def buscar(self, id_: str) -> Registro | None:
        regla = self.regla(id_)
        if regla is None:
            return None
        if regla.origen == "csv":
            fila: Mapping[str, Any] | None = self._filas_csv(regla).get(id_)
        else:
            cur = self.con.execute(f'SELECT * FROM "{regla.fuente}" WHERE "{regla.columna_id}" = ?', [id_])
            nombres = [d[0] for d in cur.description]
            datos = cur.fetchone()
            fila = dict(zip(nombres, datos, strict=True)) if datos else None
        if fila is None:
            return None
        url = fila.get(regla.columna_url) if regla.columna_url else None
        return Registro(id_, fila, str(url) if url else None)


def _hay_valor(valor: Any) -> bool:
    return valor is not None and str(valor).strip() != ""


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados: para comparar un texto con el campo que lo respalda."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_marcas.casefold()).strip()


def _extracto(valor: Any, maximo: int = 160) -> str:
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


# ---------------------------------------------------------------------------------------------------- comprobación de una ficha


@dataclass
class Unidad:
    """Una comprobación concreta: su regla, si pasó y por qué no."""

    regla: str
    ok: bool
    detalle: str = ""


@dataclass
class Traza:
    """Una cita resuelta de punta a punta: ID, campo, lo que dicen los datos y de dónde sale."""

    id: str
    campo: str
    existe: bool
    valor: str
    url: str | None
    tipo: str          # tipo de la afirmación que la usa (hecho | declaración)


@dataclass
class ResultadoFicha:
    id_grupo: str
    id_caso: str | None
    unidades: list[Unidad] = field(default_factory=list)
    trazas: list[Traza] = field(default_factory=list)

    def fallos(self) -> list[Unidad]:
        return [u for u in self.unidades if not u.ok]

    def conteo(self, regla: str) -> tuple[int, int]:
        """``(ok, n)`` de una regla."""
        de_la_regla = [u for u in self.unidades if u.regla == regla]
        return sum(u.ok for u in de_la_regla), len(de_la_regla)


def _claves_de(obj: Any) -> Iterable[str]:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            yield str(k)
            yield from _claves_de(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _claves_de(v)


def verificar_ficha(
    ficha: Ficha,
    resolutor: Resolutor,
    cfg: ConfigFichasTrazables,
    *,
    id_caso: str | None = None,
    estado_revision: str | None = None,
    textos_extra: Sequence[str] = (),
    fila_notion: Mapping[str, str] | None = None,
    revision_provisional: bool | None = None,
    marca_provisional: str | None = None,
) -> ResultadoFicha:
    """Comprueba la ficha contra los datos. ``textos_extra`` son otras salidas de la misma ficha (el Markdown del caso, la fila de Notion)
    que también deben cumplir D-31 y D-32. ``revision_provisional`` y ``marca_provisional`` (si hay CASO-) comprueban que la revisión
    del asistente se vea rotulada."""
    res = ResultadoFicha(ficha.id_grupo, id_caso)
    registro = a_registro(ficha, id_caso, estado_revision)
    md = a_markdown(ficha)
    salidas = [md, str(registro), *textos_extra]
    u = res.unidades.append

    # --- afirmaciones y citas, resueltas contra los datos
    vistas: set[tuple[str, str]] = set()
    for a in registro["afirmaciones"]:
        citas = a.get("citas") or []
        u(Unidad("afirmacion_con_cita", bool(citas) and all(c.get("id") and c.get("campo") for c in citas), a["texto"][:80]))
        for c in citas:
            id_, campo = c["id"], c["campo"]
            reg = resolutor.buscar(id_)
            valor = reg.valores.get(campo) if reg else None
            if (id_, campo) not in vistas:
                vistas.add((id_, campo))
                u(Unidad("cita_con_id_en_datos", reg is not None, f"{id_}"))
                u(Unidad("cita_con_campo_y_valor", reg is not None and campo in reg.valores and _hay_valor(valor), f"{id_} · {campo}"))
                regla = resolutor.regla(id_)
                if regla is not None and regla.url_obligatoria:
                    u(Unidad("url_presente", bool(reg and reg.url and URL_VALIDA.match(reg.url)), f"{id_}: URL del registro"))
                res.trazas.append(Traza(id_, campo, reg is not None, _extracto(valor) if _hay_valor(valor) else "", reg.url if reg else None, a["tipo"]))
            if id_.startswith("GRP-") and campo.startswith("n_") and reg is not None:
                u(Unidad("cifra_de_conteo_coincide", re.search(rf"(?<!\d){re.escape(str(valor))}(?!\d)", a["texto"]) is not None, f"{id_} · {campo} = {valor}"))
        if a["tipo"] == "declaración":
            fuentes = [normalizar(str(resolutor.buscar(c["id"]).valores.get(c["campo"], ""))) for c in citas if resolutor.buscar(c["id"])]
            frases = COMILLAS.findall(a["texto"])
            u(Unidad("declaracion_literal", bool(frases) and all(any(normalizar(f) in fuente for fuente in fuentes) for f in frases), a["texto"][:80]))

    # --- cada titular de «quién lo reporta»: su URL es la de los datos
    for t in ficha.quien_lo_reporta.titulares:
        reg = resolutor.buscar(t.id_noticia)
        u(Unidad("url_presente", bool(reg and reg.url and URL_VALIDA.match(t.url) and reg.url == t.url), f"{t.id_noticia}: URL del titular"))

    # --- procedencias y estado de evidencia
    p = ficha.quien_lo_reporta.procedencias
    estado = ficha.accion_recomendada.estado_evidencia
    ok_proc = bool(p.explicacion.strip()) and p.n == len(p.detalle) and "Procedencias:" in md and f"Estado de evidencia: {estado}" in md
    u(Unidad("procedencias_y_estado", ok_proc, f"procedencias n={p.n}, estado={estado}"))

    # --- leyenda de alcance y marca de borrador
    restricciones = cargar_restricciones()
    leyendas = set(restricciones.leyendas_alcance.model_dump().values())
    u(Unidad("leyenda_de_alcance", ficha.alcance in leyendas and f"Alcance: {ficha.alcance}" in md, ficha.alcance))
    u(Unidad("marca_borrador", ficha.borrador is True and ficha.marca_borrador == restricciones.marca_borrador and restricciones.marca_borrador in md and ficha.accion_recomendada.habilita_publicar is False, ficha.marca_borrador))

    # --- cinco partes
    titulos = [s.titulo for s in vista(ficha, cargar_verificacion()).secciones]
    u(Unidad("cinco_partes", len(titulos) == len(PARTES_DE_LA_FICHA) and all(t in md for t in titulos) and all(k in registro["ficha"] for k in PARTES_DE_LA_FICHA), "; ".join(titulos)))

    # --- D-31: ninguna descripción del RSS en ninguna salida
    texto_de_salidas = normalizar(" ".join(salidas))
    for t in ficha.quien_lo_reporta.titulares:
        reg = resolutor.buscar(t.id_noticia)
        desc = normalizar(str(reg.valores.get("descripcion") or "")) if reg else ""
        titulo = normalizar(str(reg.valores.get("titulo_limpio") or reg.valores.get("titulo") or "")) if reg else ""
        evaluable = len(desc) >= cfg.descripcion_minimo_caracteres and desc not in titulo
        u(Unidad("sin_descripcion_rss", not (evaluable and desc in texto_de_salidas), f"{t.id_noticia}"))

    # --- D-32: ninguna clave de autor y solo agencia / tipo de firma permitidos
    cfg_norm = cargar_normalizacion()
    tipos = set(cfg_norm.firma.tipos.model_dump().values())
    claves = {k.casefold() for k in _claves_de(registro)}
    prohibidas = claves & {k.casefold() for k in cfg.claves_de_autor}
    agencias_ok = all((t.agencia is None or t.agencia in cfg_norm.firma.agencias) and t.tipo_firma in tipos for t in ficha.quien_lo_reporta.titulares)
    u(Unidad("sin_nombres_de_autor", not prohibidas and agencias_ok, f"claves prohibidas: {sorted(prohibidas)}" if prohibidas else "agencia y tipo_firma de las listas permitidas"))

    # --- contrato de fichas.jsonl (solo con CASO-)
    if id_caso is not None:
        try:
            RegistroFichasJsonl.model_validate({**registro, "version": None, "revision_provisional": bool(revision_provisional)})
            u(Unidad("contrato_fichas_jsonl", True, id_caso))
        except ValueError as exc:
            u(Unidad("contrato_fichas_jsonl", False, str(exc)[:200]))

    # --- la revisión del asistente se ve como provisional (D-112)
    if revision_provisional is not None and marca_provisional:
        visible = bool(revision_provisional) and any(marca_provisional in t for t in textos_extra) and (fila_notion is None or marca_provisional in fila_notion.get("Revisor", ""))
        u(Unidad("revision_provisional_visible", visible, marca_provisional))
    return res


# ---------------------------------------------------------------------------------------------------- informe


def _proporcion(ok: int, n: int, z: float) -> dict[str, Any]:
    ic = intervalo_wilson(ok, n, z)
    return {"n": n, "ok": ok, "proporcion": round(ok / n, 4) if n else None, "ic95": [round(ic[0], 4), round(ic[1], 4)] if ic else None, "metodo_ic": f"Wilson (z={z})"}


def informe(resultados: Sequence[ResultadoFicha], cfg: ConfigFichasTrazables) -> dict[str, Any]:
    """Conteos por regla (n, ok, proporción con IC 95 %) y el detalle por ficha. ``todo_ok`` es la compuerta del comando."""
    z = cfg.z_intervalo_confianza
    por_regla: dict[str, dict[str, Any]] = {}
    for regla in REGLAS:
        ok = sum(r.conteo(regla)[0] for r in resultados)
        n = sum(r.conteo(regla)[1] for r in resultados)
        por_regla[regla] = _proporcion(ok, n, z) if n else {"n": 0, "ok": 0, "proporcion": None, "ic95": None, "nota": "no aplica en esta corrida"}
    fichas = []
    for r in resultados:
        fichas.append({
            "id_grupo": r.id_grupo,
            "id_caso": r.id_caso,
            "comprobaciones": {regla: {"ok": r.conteo(regla)[0], "n": r.conteo(regla)[1]} for regla in REGLAS if r.conteo(regla)[1]},
            "fallos": [{"regla": f.regla, "detalle": f.detalle} for f in r.fallos()],
            "citas": [
                {"id": t.id, "campo": t.campo, "tipo": t.tipo, "existe_en_datos": t.existe, "valor": t.valor, "url": t.url}
                for t in r.trazas
            ],
        })
    return {"n_fichas": len(resultados), "z": z, "por_regla": por_regla, "fichas": fichas, "todo_ok": all(not r.fallos() for r in resultados)}
