"""Generación del borrador en dos pasos (etapa 6, E1-12; D-17, D-22, D-41 a D-45, D-51).

**Entrada única: la ficha.** Este módulo no conoce la ``Ficha`` completa (E1-10b): trabaja con ``EntradaFicha``, la forma
mínima de lo que necesita, y un adaptador (``desde_ficha``, en la integración) convierte la ficha real en ella. El LLM solo ve
lo que hay en ``EntradaFicha``, delimitado como dato dentro de ``<evidencia>…</evidencia>``.

**Qué se genera según la acción (D-42):** ``config/generacion.yaml`` · ``acciones``. «Archivar» no llama al LLM; sin evidencia
tampoco (abstención antes de llamar).

**Paso 1 · afirmaciones (1 llamada).** El LLM propone afirmaciones citadas; el código descarta toda la que no pasa la validación
(cita inexistente, tipo mal usado, comillas inventadas, frases prohibidas…) y renumera las válidas (A1, A2…). Las dos versiones
de una contradicción abierta entran como declaraciones armadas **por código** (no dependen de que el LLM las incluya).

**Paso 2 · redacción (4 llamadas, bajo demanda, D-44).** Cada grupo —título+titulares+copy · brief+enfoque+preguntas · guion ·
resumen web— se redacta con solo las afirmaciones válidas. Cada oración debe citar al menos una de ellas. Una sección que no
pasa tras el reintento se entrega **vacía** con el motivo en ``vacios``: nunca se rellena. Fuentes y verificaciones se copian de
la ficha sin LLM (D-43).

**VALIDACIÓN MÍNIMA.** Las funciones de la sección «Validación mínima» cubren solo lo que esta spec necesita (citas existentes,
tipos de afirmación, límites de ``config/salidas.yaml``, frases de ``config/restricciones.yaml``, comillas literales, fuga del
system prompt). ``src/validador.py`` (E1-13) las reemplaza y amplía; la interfaz que usa el resto del módulo son ``validar_afirmaciones``
y ``validar_seccion``.

CLI: ``python -m src.generacion --ficha-json ruta.json`` (la forma ``--grupo GRP-001`` llega con la integración de E1-10b).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.configuracion import (
    RAIZ,
    ConfigGeneracionBorrador,
    ConfigRestricciones,
    ConfigSalidas,
    cargar_consulta,
    cargar_generacion,
    cargar_modalidad,
    cargar_normalizacion,
    cargar_restricciones,
    cargar_salidas,
)
from src.esquemas import (
    Afirmacion,
    Ficha,
    AfirmacionSalida,
    CitaSalida,
    Oracion,
    OracionLlm,
    PaqueteEditorial,
    PaqueteInvestigacion,
    PreguntaInvestigacion,
    SalidaBrief,
    SalidaGuion,
    SalidaInvestigacion,
    SalidaResumen,
    SalidaTitulos,
    Vacio,
    esquema_json_afirmaciones,
)
from src.cache import (
    CacheLlm,
    Identidad,
    ProveedorConCache,
    ProveedorSoloCache,
    SinBorrador,
    SinCache,
    identidad_de,
    modo_offline,
    red_disponible,
)
from src.limpieza import plano
from src.llm.costo import TopeDeCostoAlcanzado
from src.llm.proveedor import ErrorProveedor, Proveedor
from src.registro import MARCA_REDACCION, valores_sensibles

logger = logging.getLogger(__name__)

CARPETA_PROMPTS = RAIZ / "prompts"
ESPACIOS = re.compile(r"\s+")
COMILLAS = re.compile(r"[\"“«](.+?)[\"”»]")
HASHTAG = re.compile(r"#\w+")
NUMERO = re.compile(r"\d+(?:[.,]\d+)?")

Tipo = Literal["editorial", "investigacion", "nada"]
MARCA_EXCESO = "supera el máximo"


# ============================================================================================ entrada: la ficha (forma mínima)


class RegistroEvidencia(BaseModel):
    """Un registro citable de la ficha: un titular (``NOT-``) o un dato oficial (``IND-``, ``SIS-``, ``SBP-``).

    ``campos`` son **solo** los campos que la ficha cita (``titulo_limpio``, ``valor``, ``magnitude``, ``n_titulares``…): una cita
    válida es (``id``, un nombre de ``campos``). ``contexto`` (medio, fecha, año, indicador) se muestra al LLM pero no se puede
    citar. ``idioma`` solo aplica a titulares (D-45).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    campos: dict[str, str]
    contexto: dict[str, str] = Field(default_factory=dict)
    idioma: str | None = None
    campo_texto: str = "titulo"  # campo que guarda el texto del titular (en la ficha real, ``titulo_limpio``)


class VacioFicha(BaseModel):
    """Un vacío de la ficha (qué falta para sostener el caso)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    descripcion: str


class ContradiccionFicha(BaseModel):
    """Una posible contradicción entre dos titulares del grupo, con el fragmento literal de cada uno (E1-10)."""

    model_config = ConfigDict(extra="forbid")

    id_a: str
    id_b: str
    fragmento_a: str
    fragmento_b: str
    abierta: bool = True


class EntradaFicha(BaseModel):
    """Todo lo que la generación toma de la ficha (E1-10b la construye con ``desde_ficha``)."""

    model_config = ConfigDict(extra="forbid")

    id_caso: str
    version: int = 1
    modalidad: str = "editorial"
    accion: str
    uso_descripcion: bool = False
    registros: list[RegistroEvidencia] = Field(default_factory=list)
    vacios: list[VacioFicha] = Field(default_factory=list)
    fuentes_verificaciones: list[str] = Field(default_factory=list)
    contradicciones: list[ContradiccionFicha] = Field(default_factory=list)


# ============================================================================================ resultado y registro de llamadas


@dataclass
class RegistroLlamada:
    """Una llamada al LLM: solo cifras y versión del prompt, nunca su contenido (D-69)."""

    paso: str
    intento: int
    proveedor: str
    modelo: str
    version_prompt: str
    tokens_entrada: int
    tokens_salida: int
    latencia_s: float
    valida: bool = False


@dataclass
class ResultadoGeneracion:
    """Qué se generó y cómo: el paquete (si hay), el motivo de no generar, las llamadas y lo descartado por la validación."""

    tipo: Tipo
    paquete: PaqueteEditorial | PaqueteInvestigacion | None
    motivo: str | None = None
    llamadas: list[RegistroLlamada] = field(default_factory=list)
    descartadas: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Plan:
    """Decisión de qué generar (D-42) y por qué."""

    tipo: Tipo
    forzado: bool = False
    motivo: str | None = None


# ============================================================================================ prompts versionados


def cargar_prompt(nombre: str) -> tuple[str, str]:
    """``(versión, texto)`` de ``prompts/<nombre>.txt``. La versión sale de la línea ``# version: X.Y`` del encabezado."""
    bruto = (CARPETA_PROMPTS / f"{nombre}.txt").read_text(encoding="utf-8")
    version = ""
    cuerpo: list[str] = []
    en_encabezado = True
    for linea in bruto.splitlines():
        if en_encabezado and linea.startswith("#") and not linea.startswith("##"):
            if m := re.match(r"#\s*version:\s*(\S+)", linea):
                version = m.group(1)
            continue
        en_encabezado = False
        cuerpo.append(linea)
    if not version:
        raise ValueError(f"prompts/{nombre}.txt no declara su versión (# version: X.Y)")
    return version, "\n".join(cuerpo).strip() + "\n"


def _bloques(texto: str) -> dict[str, str]:
    """Divide un prompt en bloques por líneas ``## nombre``."""
    bloques: dict[str, list[str]] = {}
    actual: str | None = None
    for linea in texto.splitlines():
        if linea.startswith("## "):
            actual = linea[3:].strip()
            bloques[actual] = []
        elif actual is not None:
            bloques[actual].append(linea)
    return {k: "\n".join(v).strip() for k, v in bloques.items()}


# ============================================================================================ grupos de redacción (D-44)


@dataclass(frozen=True)
class GrupoRedaccion:
    modelo: type[BaseModel]
    secciones: tuple[str, ...]
    bloque: str  # nombre del bloque en prompts/paquete_editorial.txt


GRUPOS: dict[str, GrupoRedaccion] = {
    "titulos": GrupoRedaccion(SalidaTitulos, ("titulo", "titulares", "copy_digital"), "grupo titulos"),
    "brief": GrupoRedaccion(SalidaBrief, ("brief", "enfoque", "preguntas"), "grupo brief"),
    "guion": GrupoRedaccion(SalidaGuion, ("guion",), "grupo guion"),
    "resumen": GrupoRedaccion(SalidaResumen, ("resumen_web",), "grupo resumen"),
    "investigacion": GrupoRedaccion(SalidaInvestigacion, ("titulo_trabajo", "enfoque", "preguntas"), "grupo investigacion"),
}


# ============================================================================================ validación mínima (E1-13 la reemplaza)


def _palabras(texto: str, marcador: str) -> int:
    return len(re.findall(r"\S+", texto.replace(marcador, " ")))


def _ids_con_prefijo(citas: Sequence[Any], prefijos: tuple[str, ...]) -> set[str]:
    return {c.id for c in citas if c.id.startswith(prefijos)}


class _Contexto:
    """Lo que necesitan las validaciones: la ficha indexada, las afirmaciones válidas, la configuración y el system prompt."""

    def __init__(
        self,
        ficha: EntradaFicha,
        cfg: ConfigGeneracionBorrador,
        salidas: ConfigSalidas,
        restricciones: ConfigRestricciones,
        atribucion: Sequence[str],
        grupos_restricciones: Sequence[str],
    ) -> None:
        self.ficha, self.cfg, self.salidas, self.restricciones = ficha, cfg, salidas, restricciones
        self.registros = {r.id: r for r in ficha.registros}
        self.vacios = {v.id for v in ficha.vacios}
        self.atribucion = [plano(m) for m in atribucion]
        frases: list[str] = []
        for g in grupos_restricciones:
            for lista in restricciones.grupos[g].values():
                frases.extend(lista)
        self.frases_prohibidas = [plano(f) for f in frases]
        self.afirmaciones: dict[str, AfirmacionSalida] = {}
        self.system = ""

    # ---- texto

    def texto_registro(self, id_: str) -> str:
        r = self.registros.get(id_)
        return " ".join(r.campos.values()) if r else ""

    def frase_prohibida(self, texto: str, ids_citados: Sequence[str]) -> str | None:
        """Primera frase prohibida del texto que no esté literalmente en un registro citado (D-25, D-51)."""
        p = plano(texto)
        permitido = plano(" ".join(self.texto_registro(i) for i in ids_citados))
        for f in self.frases_prohibidas:
            if re.search(rf"(?<!\w){re.escape(f)}(?!\w)", p) and f not in permitido:
                return f
        return None

    def comilla_inventada(self, texto: str, ids_citados: Sequence[str]) -> str | None:
        fuente = ESPACIOS.sub(" ", plano(" ".join(self.texto_registro(i) for i in ids_citados)))
        for m in COMILLAS.finditer(texto):
            if ESPACIOS.sub(" ", plano(m.group(1))).strip() not in fuente:
                return m.group(1)
        return None

    def revela_system(self, texto: str) -> bool:
        """El texto repite ``n`` palabras consecutivas del system prompt (T07: no revelar las instrucciones)."""
        n = self.cfg.fuga_prompt.palabras_por_fragmento
        base = re.findall(r"\w+", plano(self.system))
        huella = {tuple(base[i : i + n]) for i in range(len(base) - n + 1)}
        dicho = re.findall(r"\w+", plano(texto))
        return any(tuple(dicho[i : i + n]) in huella for i in range(len(dicho) - n + 1))

    def revela_secreto(self, texto: str) -> bool:
        return any(v in texto for v in valores_sensibles()) or MARCA_REDACCION in texto

    def revisar(self, texto: str, ids_citados: Sequence[str]) -> list[str]:
        """Problemas de un texto libre del LLM, comunes a afirmaciones y oraciones."""
        errores: list[str] = []
        if self.revela_secreto(texto):
            errores.append("el texto contiene un secreto o un valor redactado")
        if self.revela_system(texto):
            errores.append("el texto repite fragmentos del system prompt")
        if f := self.frase_prohibida(texto, ids_citados):
            errores.append(f"frase prohibida: «{f}»")
        if c := self.comilla_inventada(texto, ids_citados):
            errores.append(f"comillas que no son literales del titular citado: «{c}»")
        return errores


def _anio_del_id(id_: str, ctx: _Contexto) -> str | None:
    """Año de un ID anual (``IND-PAN-…-2024`` → ``2024``); ``None`` si el ID no es anual."""
    m = re.search(ctx.cfg.patron_anio_en_id, id_) if id_.startswith(tuple(ctx.cfg.prefijos.hecho_oficial)) else None
    return m.group(1) if m else None


def _cita_ok(ctx: _Contexto, id_: str, campo: str) -> bool:
    r = ctx.registros.get(id_)
    return r is not None and campo in r.campos


def _errores_de_afirmacion(a: Afirmacion, ctx: _Contexto) -> list[str]:
    """Reglas propias de una afirmación (sin mirar su base)."""
    errores: list[str] = []
    for c in a.citas:
        if not _cita_ok(ctx, c.id, c.campo):
            errores.append(f"cita inexistente en la ficha: {c.id} · {c.campo}")
    if errores:
        return errores
    ids = [c.id for c in a.citas]
    if a.tipo == "hecho":
        p = ctx.cfg.prefijos
        for c in a.citas:
            oficial = c.id.startswith(tuple(p.hecho_oficial))
            conteo = c.id.startswith(tuple(p.hecho_conteo)) and c.campo in ctx.cfg.campos_conteo
            if not (oficial or conteo):
                errores.append(
                    f"un hecho solo cita datos oficiales ({', '.join(p.hecho_oficial)}) o el conteo del grupo ({', '.join(p.hecho_conteo)}); "
                    f"{c.id} es lo que reporta un medio: una declaración"
                )
                break
    if a.tipo == "declaración" and not _ids_con_prefijo(a.citas, tuple(ctx.cfg.prefijos.reportes)):
        errores.append("una declaración cita lo que reporta un medio (un titular)")
    for id_ in ids:
        r = ctx.registros[id_]
        if anio := _anio_del_id(id_, ctx):
            if anio not in a.texto:
                errores.append(f"un dato oficial anual incluye su año ({anio}) en el texto")
            if any(re.search(rf"\b{re.escape(p)}\b", plano(a.texto)) for p in ctx.cfg.volatiles):
                errores.append("un dato oficial anual no se describe como actual ni de hoy")
    errores += ctx.revisar(a.texto, ids)
    return errores


def validar_afirmaciones(
    crudas: Sequence[Afirmacion], ctx: _Contexto, maximo: int
) -> tuple[list[AfirmacionSalida], list[str]]:
    """Conserva las afirmaciones válidas (con su base también válida), las renumera A1, A2… y devuelve lo descartado y por qué.

    Una inferencia o hipótesis no puede traer cifras que no estén en las afirmaciones en que se apoya.
    """
    descartadas: list[str] = []
    propias: dict[str, Afirmacion] = {}
    for a in crudas:
        if a.id in propias:
            descartadas.append(f"{a.id}: id repetido")
            continue
        errores = _errores_de_afirmacion(a, ctx)
        if errores:
            descartadas.append(f"{a.id}: " + "; ".join(errores))
        else:
            propias[a.id] = a
    cambio = True
    while cambio:  # una inferencia cae si cae su base
        cambio = False
        for id_, a in list(propias.items()):
            if a.base and (id_ in a.base or any(b not in propias for b in a.base)):
                descartadas.append(f"{id_}: su base no existe o no es válida")
                del propias[id_]
                cambio = True
    for id_, a in list(propias.items()):
        if a.base:
            permitidas = {n for b in a.base for n in NUMERO.findall(propias[b].texto)}
            if any(n not in permitidas for n in NUMERO.findall(a.texto)):
                descartadas.append(f"{id_}: una {a.tipo} no puede traer cifras nuevas")
                del propias[id_]
    for id_ in list(propias):  # de nuevo: la caída de una puede arrastrar a otra
        if any(b not in propias for b in propias[id_].base):
            descartadas.append(f"{id_}: su base no existe o no es válida")
            del propias[id_]
    elegidas = list(propias.values())[:maximo]
    nuevo = {a.id: f"A{n}" for n, a in enumerate(elegidas, start=1)}
    validas = [
        AfirmacionSalida(
            id=nuevo[a.id],
            tipo=a.tipo,
            texto=a.texto,
            citas=[_cita_salida(c.id, c.campo, ctx) for c in a.citas],
            base=[nuevo[b] for b in a.base],
        )
        for a in elegidas
    ]
    return validas, descartadas


def _cita_salida(id_: str, campo: str, ctx: _Contexto) -> CitaSalida:
    """Marca como traducida la cita de un titular que no está en el idioma base (D-45); lo decide el código, no el LLM."""
    idioma = ctx.registros[id_].idioma
    return CitaSalida(id=id_, campo=campo, traducido=bool(idioma) and idioma != ctx.cfg.traducido.idioma_base)


def _citadas(oracion: OracionLlm, ctx: _Contexto) -> list[AfirmacionSalida]:
    return [ctx.afirmaciones[i] for i in oracion.afirmaciones if i in ctx.afirmaciones]


def _errores_de_oracion(o: OracionLlm, ctx: _Contexto, permite_marcador: bool = False) -> list[str]:
    marcador = ctx.restricciones.marcador_visual
    if o.texto.strip() == marcador:
        if not permite_marcador:
            return [f"el marcador {marcador} solo se permite en el guion"]
        return [] if not o.afirmaciones else ["un marcador visual no lleva afirmaciones"]
    errores: list[str] = []
    if "[VISUAL" in o.texto:
        errores.append(f"el único marcador visual permitido es {marcador}, como oración propia")
    if not o.afirmaciones:
        errores.append(f"oración sin afirmaciones: «{o.texto[: ctx.cfg.texto.vista_previa_caracteres]}»")
    desconocidas = [i for i in o.afirmaciones if i not in ctx.afirmaciones]
    if desconocidas:
        errores.append(f"cita afirmaciones que no existen o no se validaron: {', '.join(desconocidas)}")
    ids = [c.id for a in _citadas(o, ctx) for c in a.citas]
    errores += ctx.revisar(o.texto, ids)
    return errores


def _atribuido(o: OracionLlm, ctx: _Contexto) -> bool:
    """Una oración basada solo en declaraciones lleva atribución: verbo de reporte o nombre del medio."""
    citadas = _citadas(o, ctx)
    if not citadas or any(a.tipo != "declaración" for a in citadas):
        return True
    p = plano(o.texto)
    medios = [plano(ctx.registros[c.id].contexto.get("medio", "")) for a in citadas for c in a.citas if c.id in ctx.registros]
    return any(re.search(rf"\b{re.escape(m)}\b", p) for m in ctx.atribucion) or any(m and m in p for m in medios)


def _oraciones(
    seccion: str, valor: Sequence[OracionLlm], ctx: _Contexto, *, minimo: int = 1, maximo: int | None = None, permite_marcador: bool = False
) -> list[str]:
    errores: list[str] = []
    if len(valor) < minimo or (maximo is not None and len(valor) > maximo):
        rango = f"{minimo}" if maximo == minimo else f"{minimo} a {maximo}" if maximo else f"al menos {minimo}"
        errores.append(f"se esperaban {rango} oraciones y hay {len(valor)}")
    for o in valor:
        errores += _errores_de_oracion(o, ctx, permite_marcador)
    return errores


def _limite(seccion: str, valor: Sequence[OracionLlm], ctx: _Contexto, maximo: int) -> list[str]:
    n = sum(_palabras(o.texto, ctx.restricciones.marcador_visual) for o in valor)
    if n <= maximo:
        return []
    objetivo = int(maximo * ctx.cfg.objetivo_fraccion_limite)
    return [f"{seccion} tiene {n} palabras y {MARCA_EXCESO} ({maximo}): recórtala a unas {objetivo} palabras (quita {n - objetivo})"]


def _contradicciones_cubiertas(valor: Sequence[OracionLlm], ctx: _Contexto) -> list[str]:
    """Con una contradicción abierta, el texto debe apoyarse en ambas versiones (cada una citada por alguna afirmación)."""
    errores: list[str] = []
    citados = {c.id for o in valor for a in _citadas(o, ctx) for c in a.citas}
    for c in ctx.ficha.contradicciones:
        if c.abierta and not {c.id_a, c.id_b} <= citados:
            errores.append(f"hay una contradicción abierta entre {c.id_a} y {c.id_b}: presenta ambas versiones")
    return errores


def validar_seccion(seccion: str, valor: Any, ctx: _Contexto) -> list[str]:
    """Problemas de una sección redactada por el LLM (lista vacía = válida)."""
    e = ctx.salidas.editorial
    marcador = ctx.restricciones.marcador_visual
    if seccion in ("titulo", "titulo_trabajo"):
        oraciones = [valor]
        errores = _oraciones(seccion, oraciones, ctx, maximo=1) + _limite(seccion, oraciones, ctx, e.titulo_max_palabras)
        return errores + ([] if _atribuido(valor, ctx) else [f"una declaración se titula con atribución o verbo de reporte: «{valor.texto}»"])
    if seccion == "titulares":
        errores = _oraciones(seccion, valor, ctx, minimo=e.titulares_min, maximo=e.titulares_max)
        for o in valor:
            errores += _limite(seccion, [o], ctx, e.titular_max_palabras)
            errores += [] if _atribuido(o, ctx) else [f"un titular basado en una declaración lleva atribución o verbo de reporte: «{o.texto}»"]
        return errores
    if seccion == "enfoque":
        errores = _oraciones(seccion, valor, ctx, minimo=e.enfoque_oraciones_min, maximo=e.enfoque_oraciones_max)
        for o in valor:
            if not any(a.tipo in ("inferencia", "hipótesis") for a in _citadas(o, ctx)):
                errores.append("el enfoque se apoya en una inferencia o hipótesis, nunca se presenta como hecho")
        return errores
    if seccion == "brief":
        return _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, e.brief_max_palabras) + _contradicciones_cubiertas(valor, ctx)
    if seccion == "resumen_web":
        return _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, e.resumen_web_max_palabras)
    if seccion == "copy_digital":
        errores = _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, e.copy_max_palabras)
        texto = " ".join(o.texto for o in valor)
        if len(HASHTAG.findall(texto)) > e.copy_max_hashtags:
            errores.append(f"el copy tiene más de {e.copy_max_hashtags} hashtags")
        if any(unicodedata.category(c) == "So" for c in texto):
            errores.append("el copy no lleva emojis")
        return errores
    if seccion == "guion":
        errores = _oraciones(seccion, valor, ctx, permite_marcador=True)
        n = sum(_palabras(o.texto, marcador) for o in valor)
        if not e.guion_palabras_min <= n <= e.guion_palabras_max:
            errores.append(f"el guion tiene {n} palabras y debe tener entre {e.guion_palabras_min} y {e.guion_palabras_max}")
        partes = [o.parte for o in valor]
        if set(partes) != {"entrada", "desarrollo", "cierre"} or partes != sorted(partes, key=("entrada", "desarrollo", "cierre").index):
            errores.append("el guion tiene entrada, desarrollo y cierre, en ese orden")
        return errores
    if seccion == "preguntas":
        errores = []
        if len(valor) != e.preguntas:
            errores.append(f"se esperaban exactamente {e.preguntas} preguntas y hay {len(valor)}")
        for q in valor:
            if q.vacio not in ctx.vacios:
                errores.append(f"la pregunta referencia un vacío que no existe en la ficha: {q.vacio}")
            errores += ctx.revisar(q.texto, [])
        return errores
    raise ValueError(f"sección desconocida: {seccion}")


# ============================================================================================ el generador


def _neutralizar(texto: str) -> str:
    """La evidencia es dato: ``<`` y ``>`` pasan a sus homólogos tipográficos ``‹`` y ``›``, así que ningún texto de la ficha o
    del LLM puede formar una etiqueta (ni la de cierre) por mucho que la parta, la anide o varíe espacios y mayúsculas (X27)."""
    return texto.replace("<", "‹").replace(">", "›")


class Generador:
    """Genera un paquete paso a paso: ``generar_grupo`` solo llama al LLM la primera vez que se pide cada grupo (D-44)."""

    def __init__(
        self,
        ficha: EntradaFicha,
        proveedor: Proveedor | None,
        forzar_completo: bool = False,
        cfg: ConfigGeneracionBorrador | None = None,
    ) -> None:
        self.ficha, self.proveedor = ficha, proveedor
        self.cfg = cfg or cargar_generacion()
        self.restricciones, self.salidas = cargar_restricciones(), cargar_salidas()
        self.plan = planificar(ficha, forzar_completo, self.cfg)
        grupos_restr = cargar_modalidad(ficha.modalidad).grupos_restricciones if self.plan.tipo != "nada" else []
        self.ctx = _Contexto(ficha, self.cfg, self.salidas, self.restricciones, self.cfg.atribucion.marcadores, grupos_restr)
        self.llamadas: list[RegistroLlamada] = []
        self.descartadas: list[str] = []
        self._afirmaciones: list[AfirmacionSalida] | None = None
        self._secciones: dict[str, Any] = {}
        self._vacios: list[Vacio] = []
        self._hechos: set[str] = set()
        self._v_afirm, self._t_afirm = cargar_prompt(self.cfg.prompts.afirmaciones)
        self._v_red, self._t_red = cargar_prompt(self.cfg.prompts.redaccion)

    # ---- grupos de este paquete

    @property
    def grupos(self) -> list[str]:
        if self.plan.tipo == "editorial":
            return list(self.cfg.grupos.editorial)
        if self.plan.tipo == "investigacion":
            return list(self.cfg.grupos.investigacion)
        return []

    # ---- una llamada al LLM

    def _llamar(self, paso: str, intento: int, version: str, system: str, usuario: str, esquema: dict[str, Any]) -> tuple[str, RegistroLlamada]:
        assert self.proveedor is not None
        inicio = time.perf_counter()
        versionado = getattr(self.proveedor, "generar_json_versionado", None)  # proveedores con caché (E1-14): la versión entra en la clave
        crudo = versionado(version, system, usuario, esquema) if versionado else self.proveedor.generar_json(system, usuario, esquema)
        transcurrido = time.perf_counter() - inicio
        uso = getattr(self.proveedor, "ultimo_uso", None)
        registro = RegistroLlamada(
            paso, intento, self.proveedor.nombre, self.proveedor.modelo, version,
            uso.tokens_entrada if uso else 0, uso.tokens_salida if uso else 0, uso.latencia_s if uso else transcurrido,
        )
        self.llamadas.append(registro)
        logger.info("generación paso=%s intento=%d prompt=%s", paso, intento, version)
        return crudo, registro

    # ---- paso 1

    def _mensaje_ficha(self) -> str:
        d = cargar_consulta().delimitador_evidencia
        n = _neutralizar
        lineas = [f"caso: {n(self.ficha.id_caso)}", "registros:"]
        for r in self.ficha.registros:
            lineas.append(f"registro {n(r.id)}" + (f" (idioma: {n(r.idioma)})" if r.idioma else ""))
            lineas += [f"  campo citable {n(k)}: {n(v)}" for k, v in r.campos.items()]
            lineas += [f"  contexto (no se cita) {n(k)}: {n(v)}" for k, v in r.contexto.items()]
        if self.ficha.vacios:
            lineas.append("vacíos de la ficha:")
            lineas += [f"  {n(v.id)}: {n(v.descripcion)}" for v in self.ficha.vacios]
        abiertas = [c for c in self.ficha.contradicciones if c.abierta]
        if abiertas:
            lineas.append("contradicciones abiertas (presenta ambas versiones como declaraciones separadas):")
            lineas += [f"  {n(c.id_a)}: «{n(c.fragmento_a)}» frente a {n(c.id_b)}: «{n(c.fragmento_b)}»" for c in abiertas]
        return f"{d.abre}\n" + "\n".join(lineas) + f"\n{d.cierra}\n\nExtrae las afirmaciones citadas de la evidencia y responde con el JSON."

    def _afirmaciones_de_contradicciones(self) -> list[AfirmacionSalida]:
        """Las dos versiones de cada contradicción abierta como declaraciones armadas por código (D-23)."""
        salida: list[AfirmacionSalida] = []
        for c in self.ficha.contradicciones:
            if not c.abierta:
                continue
            for id_, frag in ((c.id_a, c.fragmento_a), (c.id_b, c.fragmento_b)):
                r = self.ctx.registros.get(id_)
                if r is None or r.campo_texto not in r.campos or frag.strip() not in r.campos[r.campo_texto]:
                    continue
                medio = r.contexto.get("medio", "un medio")
                salida.append(AfirmacionSalida(id="", tipo="declaración", texto=f"{medio} reporta «{frag.strip()}»", citas=[_cita_salida(id_, r.campo_texto, self.ctx)]))
        return salida

    def generar_afirmaciones(self) -> list[AfirmacionSalida]:
        """Paso 1: una llamada (más el reintento si hace falta). Devuelve las afirmaciones válidas, renumeradas."""
        if self._afirmaciones is not None:
            return self._afirmaciones
        self._afirmaciones = []
        if self.proveedor is None or self.plan.tipo == "nada":
            return self._afirmaciones
        system = self._t_afirm.replace("{esquema}", json.dumps(esquema_json_afirmaciones(), ensure_ascii=False))
        self.ctx.system = system
        base_usuario = self._mensaje_ficha()
        motivo = "no hubo afirmaciones válidas"
        validas: list[AfirmacionSalida] = []
        for intento in range(1 + self.cfg.reintentos):
            usuario = base_usuario + ("" if intento == 0 else _retroalimentacion([motivo]))
            try:
                crudo, registro = self._llamar("afirmaciones", intento, self._v_afirm, system, usuario, esquema_json_afirmaciones())
            except (TopeDeCostoAlcanzado, SinCache):
                raise  # D-95: la generación se detiene; quien llama muestra el mensaje
            except ErrorProveedor as exc:
                motivo = f"proveedor no disponible: {exc}"
                break
            try:
                crudas, mal_formadas = _leer_afirmaciones(crudo)
            except ValueError:
                motivo = "salida inválida: no cumple el esquema de afirmaciones"
                continue
            validas, descartadas = validar_afirmaciones(crudas, self.ctx, self.cfg.afirmaciones.maximas)
            descartadas = mal_formadas + descartadas
            self.descartadas += descartadas
            if len(validas) >= self.cfg.afirmaciones.minimas_validas:
                registro.valida = True
                break
            motivo = "no hubo afirmaciones válidas: " + "; ".join(descartadas)[: self.cfg.texto.motivo_max_caracteres]
            validas = []
        if validas:
            self._afirmaciones = self._con_contradicciones(validas)
            self.ctx.afirmaciones = {a.id: a for a in self._afirmaciones}
        else:
            self._vacios.append(Vacio(origen="seccion", referencia="afirmaciones", motivo=motivo))
        return self._afirmaciones

    def _con_contradicciones(self, validas: list[AfirmacionSalida]) -> list[AfirmacionSalida]:
        extra = self._afirmaciones_de_contradicciones()
        numeradas = list(validas)
        for a in extra:
            numeradas.append(a.model_copy(update={"id": f"A{len(numeradas) + 1}"}))
        return numeradas

    # ---- paso 2

    def _mensaje_redaccion(self, grupo: str) -> str:
        d = cargar_consulta().delimitador_evidencia
        n = _neutralizar
        lineas = ["afirmaciones validadas:"]
        for a in self._afirmaciones or []:
            citas = ", ".join(f"{n(c.id)} · {n(c.campo)}" for c in a.citas) or "sin cita directa"
            base = f"; se apoya en {', '.join(n(b) for b in a.base)}" if a.base else ""
            medios = sorted({n(self.ctx.registros[c.id].contexto["medio"]) for c in a.citas if "medio" in self.ctx.registros[c.id].contexto})
            medio = f"; medio: {', '.join(medios)}" if medios else ""
            lineas.append(f"{n(a.id)} [{a.tipo}] {n(a.texto)} (citas: {citas}{base}{medio})")
        if grupo in ("brief", "investigacion"):
            lineas.append("vacíos de la ficha:")
            lineas += [f"  {n(v.id)}: {n(v.descripcion)}" for v in self.ficha.vacios] or ["  (ninguno)"]
        abiertas = [c for c in self.ficha.contradicciones if c.abierta]
        if abiertas:
            lineas.append("contradicciones abiertas: presenta ambas versiones apoyándote en las afirmaciones de cada una.")
        return f"{d.abre}\n" + "\n".join(lineas) + f"\n{d.cierra}\n\n{self._limites(grupo)}Redacta las secciones del grupo y responde con el JSON."

    def _limites(self, grupo: str) -> str:
        """Los máximos de palabras de las secciones del grupo, con el objetivo de longitud, para pedirlos de forma explícita."""
        e, f = self.salidas.editorial, self.cfg.objetivo_fraccion_limite
        maximos = {
            "titulo": e.titulo_max_palabras, "titulo_trabajo": e.titulo_max_palabras, "titulares": e.titular_max_palabras,
            "copy_digital": e.copy_max_palabras, "brief": e.brief_max_palabras, "resumen_web": e.resumen_web_max_palabras,
        }
        partes = [f"{s} ≤ {m} palabras (apunta a {int(m * f)})" for s in GRUPOS[grupo].secciones if (m := maximos.get(s))]
        if "guion" in GRUPOS[grupo].secciones:
            partes.append(f"guion entre {e.guion_palabras_min} y {e.guion_palabras_max} palabras (sin contar los marcadores)")
        return ("Límites estrictos de palabras: " + "; ".join(partes) + ". Cuéntalas antes de responder.\n\n") if partes else ""

    def _system_redaccion(self, grupo: str) -> str:
        g = GRUPOS[grupo]
        bloques = _bloques(self._t_red)
        texto = bloques["comunes"] + "\n\n" + bloques[g.bloque]
        esquema = json.dumps(g.modelo.model_json_schema(), ensure_ascii=False)
        return texto.replace("{esquema}", esquema).replace("{marcador_visual}", self.restricciones.marcador_visual)

    def generar_grupo(self, grupo: str) -> None:
        """Redacta un grupo de secciones (una llamada, más el reintento). No repite un grupo ya generado."""
        if grupo not in self.grupos:
            raise ValueError(f"el grupo {grupo!r} no corresponde a este paquete ({self.plan.tipo}): {self.grupos}")
        if grupo in self._hechos:
            return
        self._hechos.add(grupo)
        if not self.generar_afirmaciones():
            return  # sin afirmaciones válidas no se redacta nada; el motivo ya está en ``vacios``
        g = GRUPOS[grupo]
        system = self._system_redaccion(grupo)
        self.ctx.system = system
        base_usuario = self._mensaje_redaccion(grupo)
        pendientes = list(g.secciones)
        errores: dict[str, list[str]] = {}
        ultimos: dict[str, Any] = {}
        for intento in range(1 + self.cfg.reintentos):
            usuario = base_usuario if intento == 0 else base_usuario + _retroalimentacion(sum(errores.values(), []))
            try:
                crudo, registro = self._llamar(grupo, intento, self._v_red, system, usuario, g.modelo.model_json_schema())
            except (TopeDeCostoAlcanzado, SinCache):
                raise
            except ErrorProveedor as exc:
                errores = {s: [f"proveedor no disponible: {exc}"] for s in pendientes}
                break
            try:
                salida = g.modelo.model_validate_json(crudo)
            except (ValidationError, ValueError):
                errores = {s: ["salida inválida: no cumple el esquema de la sección"] for s in pendientes}
                continue
            errores = {}
            for s in list(pendientes):
                valor = getattr(salida, s)
                ultimos[s] = valor
                problemas = validar_seccion(s, valor, self.ctx)
                if problemas:
                    errores[s] = problemas
                else:
                    self._secciones[s] = valor
                    pendientes.remove(s)
            registro.valida = not pendientes
            if not pendientes:
                break
        for s in list(pendientes):
            if recortada := self._recortar(s, ultimos.get(s), errores.get(s, [])):
                self._secciones[s], quitadas = recortada
                self._vacios.append(Vacio(origen="seccion", referencia=s, motivo=f"recortada: se quitaron {quitadas} oraciones del final por superar el máximo de palabras"))
                pendientes.remove(s)
        for s in pendientes:
            self._vacios.append(Vacio(origen="seccion", referencia=s, motivo="; ".join(errores.get(s, ["sin respuesta"]))[: self.cfg.texto.motivo_max_caracteres]))

    def _recortar(self, seccion: str, valor: Any, errores: Sequence[str]) -> tuple[list[OracionLlm], int] | None:
        """Quita oraciones del final hasta que la sección cabe. Solo si el único problema es el exceso de palabras."""
        if seccion not in self.cfg.recortables or not isinstance(valor, list) or not errores:
            return None
        if any(MARCA_EXCESO not in e for e in errores):
            return None
        for n in range(1, len(valor)):
            candidata = valor[: len(valor) - n]
            if not validar_seccion(seccion, candidata, self.ctx):
                return list(candidata), n
        return None

    def generar_todo(self) -> None:
        for g in self.grupos:
            self.generar_grupo(g)

    # ---- ensamblado

    def _oracion(self, o: OracionLlm) -> Oracion:
        parte = getattr(o, "parte", None)
        return Oracion(texto=o.texto.strip(), afirmaciones=list(o.afirmaciones), parte=parte)

    def _lista(self, seccion: str) -> list[Oracion]:
        return [self._oracion(o) for o in self._secciones.get(seccion, [])]

    def _uno(self, seccion: str) -> Oracion | None:
        o = self._secciones.get(seccion)
        return self._oracion(o) if o else None

    def _preguntas(self) -> list[PreguntaInvestigacion]:
        return [PreguntaInvestigacion(texto=q.texto.strip(), vacio=q.vacio) for q in self._secciones.get("preguntas", [])]

    def paquete(self) -> PaqueteEditorial | PaqueteInvestigacion | None:
        """El paquete con lo generado hasta ahora (lo que no se generó queda vacío, sin motivo: está pendiente)."""
        if self.plan.tipo == "nada":
            return None
        vacios = list(self._vacios)
        if self.ficha.accion in self.cfg.acciones.completo_con_vacios:
            vacios = [Vacio(origen="ficha", referencia=v.id, motivo=v.descripcion) for v in self.ficha.vacios] + vacios
        comunes: dict[str, Any] = {
            "marca": self.restricciones.marca_borrador,
            "id_caso": self.ficha.id_caso,
            "version": self.ficha.version,
            "leyenda_alcance": (
                self.restricciones.leyendas_alcance.con_descripcion if self.ficha.uso_descripcion else self.restricciones.leyendas_alcance.titular_metadatos
            ),
            "accion": self.ficha.accion,
            "forzado": self.plan.forzado,
            "vacios": vacios,
            "afirmaciones": self._afirmaciones or [],
            "fuentes_verificaciones": list(self.ficha.fuentes_verificaciones),
            "enfoque": self._lista("enfoque"),
            "preguntas": self._preguntas(),
        }
        if self.plan.tipo == "investigacion":
            return PaqueteInvestigacion(titulo_trabajo=self._uno("titulo_trabajo"), **comunes)
        return PaqueteEditorial(
            titulo=self._uno("titulo"),
            titulares=self._lista("titulares"),
            brief=self._lista("brief"),
            guion=self._lista("guion"),
            resumen_web=self._lista("resumen_web"),
            copy_digital=self._lista("copy_digital"),
            **comunes,
        )

    def resultado(self) -> ResultadoGeneracion:
        return ResultadoGeneracion(self.plan.tipo, self.paquete(), self.plan.motivo, self.llamadas, self.descartadas)


def _leer_afirmaciones(crudo: str) -> tuple[list[Afirmacion], list[str]]:
    """Lee la salida del paso 1 afirmación por afirmación: una mal formada se descarta sin tirar las demás.

    Lanza ``ValueError`` si no es JSON o no trae la lista ``afirmaciones`` (eso sí es una salida inválida).
    """
    datos = json.loads(crudo)
    if not isinstance(datos, dict) or not isinstance(datos.get("afirmaciones"), list):
        raise ValueError("la salida no trae la lista afirmaciones")
    buenas: list[Afirmacion] = []
    descartes: list[str] = []
    for n, item in enumerate(datos["afirmaciones"], start=1):
        try:
            buenas.append(Afirmacion.model_validate(item))
        except ValidationError as exc:
            id_ = item.get("id", f"#{n}") if isinstance(item, dict) else f"#{n}"
            descartes.append(f"{id_}: mal formada ({exc.errors()[0]['msg']})")
    return buenas, descartes


def _retroalimentacion(problemas: Sequence[str]) -> str:
    """Aviso del reintento, **fuera** de la evidencia: qué falló en la respuesta anterior."""
    lista = "\n".join(f"- {_neutralizar(p)}" for p in problemas)
    return f"\n\nLa respuesta anterior tuvo estos problemas; corrígelos sin inventar nada:\n{lista}\nResponde de nuevo solo con el JSON."


# ============================================================================================ plan y API


def planificar(ficha: EntradaFicha, forzar_completo: bool, cfg: ConfigGeneracionBorrador) -> Plan:
    """Qué se genera según la acción de la ficha (D-42). La persona puede forzar el paquete completo (queda registrado)."""
    a = cfg.acciones
    if ficha.modalidad not in cfg.modalidades:
        return Plan("nada", motivo=f"la generación de la modalidad {ficha.modalidad!r} llega con su propia spec (E2-02)")
    if not ficha.registros:
        return Plan("nada", motivo="sin evidencia: la ficha no tiene registros que citar (abstención antes de llamar al LLM)")
    conocida = ficha.accion in (*a.completo, *a.completo_con_vacios, *a.investigacion, *a.nada)
    if not conocida:
        return Plan("nada", motivo=f"acción desconocida: «{ficha.accion}» (ni forzando se genera para una acción que no está en config/generacion.yaml)")
    if ficha.accion in a.completo or ficha.accion in a.completo_con_vacios:
        return Plan("editorial")
    if forzar_completo:  # D-42: la persona puede forzar el paquete completo y queda registrado
        return Plan("editorial", forzado=True)
    if ficha.accion in a.investigacion:
        return Plan("investigacion")
    return Plan("nada", motivo=f"la acción «{ficha.accion}» no genera borrador (D-42)")


def generar(ficha: EntradaFicha, proveedor: Proveedor | None, forzar_completo: bool = False) -> ResultadoGeneracion:
    """Genera todo el paquete que corresponde a la acción de la ficha: el paso 1 y todos los grupos del paso 2."""
    g = Generador(ficha, proveedor, forzar_completo)
    if g.plan.tipo != "nada" and proveedor is None:
        return ResultadoGeneracion("nada", None, "no hay proveedor de LLM configurado (LLM_PROVIDER)")
    g.generar_todo()
    return g.resultado()


# ============================================================================================ adaptador desde la Ficha real (E1-10b)


def fuentes_y_verificaciones(ficha: Ficha) -> list[str]:
    """«Fuentes y verificaciones pendientes» tal cual la ficha (D-37, D-43): cada vacío con su verificación, las fuentes sugeridas
    y el aviso de que son sugerencias y no evidencia. Se copia sin LLM."""
    f = ficha.falta_comprobar
    return [
        *(f"{v.texto} → {v.verificacion}" for v in [*f.principales, *f.otros]),
        *(f"Fuente sugerida: {x.nombre}" for x in f.fuentes_sugeridas),
        f.aviso_fuentes,
    ]


def desde_ficha(ficha: Ficha) -> EntradaFicha:
    """Convierte la ``Ficha`` real en la única entrada del LLM. Las citas conservan **ID + campo** tal como están en la ficha.

    - Titulares: un registro por titular citable (``campo_titular``, normalmente ``titulo_limpio``), con su medio e idioma.
    - Conteos del grupo (``GRP-``): los campos que citan las líneas «reportes».
    - Datos y eventos oficiales: el texto de la línea de la ficha en el campo que citan (``valor``, ``magnitude``) y el nombre del
      indicador; el año se toma de la línea cuando la línea cita un solo dato.
    - Vacíos: los de la ficha (principales y otros). Contradicciones: ambas versiones; sin fragmento literal se usa el titular.
    """
    registros: dict[str, RegistroEvidencia] = {}
    for t in ficha.quien_lo_reporta.titulares:
        contexto = {"medio": t.medio, **({"fecha_publicacion": t.fecha_publicacion} if t.fecha_publicacion else {})}
        registros[t.id_noticia] = RegistroEvidencia(
            id=t.id_noticia, idioma=t.idioma, campos={t.campo_titular: t.titular}, contexto=contexto, campo_texto=t.campo_titular
        )
    r = ficha.respaldado
    cfg = cargar_generacion()
    valor_por_anio = re.compile(cfg.patron_valor_por_anio)
    for linea in (*r.reportes, *r.datos_oficiales, *r.eventos_oficiales):
        valores = [m.group(1).strip() for m in valor_por_anio.finditer(linea.texto)] if linea.indicador else []
        for i, c in enumerate(linea.citas):
            reg = registros.setdefault(c.id, RegistroEvidencia(id=c.id, campos={}))
            # cada ID lleva SU valor (su segmento «PAÍS AAAA: valor»), no la línea entera de varios datos
            reg.campos.setdefault(c.campo, valores[i] if len(valores) == len(linea.citas) else linea.texto)  # la primera línea que lo cita manda
            if linea.indicador:
                reg.contexto["indicador"] = linea.indicador
            if m := re.search(cfg.patron_anio_en_id, c.id) if c.id.startswith(tuple(cfg.prefijos.hecho_oficial)) else None:
                reg.contexto["anio"] = m.group(1)
    abiertas = [
        ContradiccionFicha(
            id_a=c.version_a.id, id_b=c.version_b.id,
            fragmento_a=c.fragmento_a or c.version_a.titular, fragmento_b=c.fragmento_b or c.version_b.titular,
        )
        for c in ficha.que_se_reporta.contradicciones  # siempre abiertas: solo una persona las cierra (X21)
    ]
    f = ficha.falta_comprobar
    return EntradaFicha(
        id_caso=ficha.id_grupo,
        modalidad=ficha.modalidad,
        accion=ficha.accion_recomendada.accion,
        uso_descripcion=ficha.alcance == cargar_restricciones().leyendas_alcance.con_descripcion,
        registros=list(registros.values()),
        vacios=[VacioFicha(id=v.codigo, descripcion=v.texto) for v in [*f.principales, *f.otros]],
        fuentes_verificaciones=fuentes_y_verificaciones(ficha),
        contradicciones=abiertas,
    )


# ============================================================================================ entrada para la interfaz y la caché (E1-14)


def generar_paquete(
    id_grupo: str,
    modalidad: str,
    *,
    solo_cache: bool = True,
    base: Path | None = None,
    proveedor: Proveedor | None = None,
    cache: CacheLlm | None = None,
    grupos: Sequence[str] | None = None,
    forzar_completo: bool = False,
    refrescar: bool = False,
) -> PaqueteEditorial | PaqueteInvestigacion:
    """El borrador del grupo, **desde la caché** (``solo_cache=True``, lo que usa la interfaz) o generándolo y guardándolo.

    - ``solo_cache=True``: nunca crea un proveedor ni abre una conexión. Rearma el paquete con las respuestas guardadas (la validación
      se repite sobre ellas). Un grupo de secciones sin respuesta guardada queda vacío con el motivo en ``vacios``; si no hay ninguno,
      lanza ``SinBorrador`` (también cuando la acción de la ficha no genera borrador).
    - ``solo_cache=False``: genera lo que falta (bajo demanda, D-44) y lo guarda. Sin red, con el modo offline o sin proveedor
      configurado se comporta como ``solo_cache=True``. Si se alcanza el tope de costo o se agota el saldo (D-98) lanza
      ``TopeDeCostoAlcanzado``/``SaldoAgotado``: lo ya guardado sigue disponible.
    - ``proveedor`` y ``cache`` se inyectan en las pruebas; ``grupos`` limita qué grupos se piden (por defecto, todos).
    """
    entrada = _entrada_desde_grupo(id_grupo, modalidad, base or RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    cache = cache if cache is not None else CacheLlm()
    cfg_cache = cache.cfg
    if not solo_cache and (modo_offline(cfg=cfg_cache) or (proveedor is None and not red_disponible(cfg=cfg_cache))):
        solo_cache = True
    if solo_cache:
        try:
            identidad = Identidad(proveedor.nombre, proveedor.modelo) if proveedor else identidad_de()
        except ErrorProveedor as exc:  # sin LLM_PROVIDER en local.env no se puede saber con qué se guardó: no hay borrador que mostrar
            raise SinBorrador(cfg_cache.textos.sin_cache) from exc
        prov: Any = ProveedorSoloCache(cache, identidad)
    else:
        from src.llm.proveedor import crear_proveedor

        prov = ProveedorConCache(proveedor or crear_proveedor(), cache, refrescar)
    g = Generador(entrada, prov, forzar_completo)
    if g.plan.tipo == "nada":
        raise SinBorrador(g.plan.motivo or cfg_cache.textos.sin_cache, por_accion=True)
    pedidos = [x for x in (grupos or g.grupos) if x in g.grupos]
    faltan: dict[str, str] = {}  # grupo -> motivo
    aciertos = lambda: getattr(prov, "aciertos", 0)  # noqa: E731
    motivo_falta = lambda antes: cfg_cache.textos.borrador_invalido if aciertos() > antes else cfg_cache.textos.sin_cache_grupo  # noqa: E731
    antes = aciertos()
    try:
        g.generar_afirmaciones()
    except SinCache:
        faltan = dict.fromkeys(pedidos, motivo_falta(antes))  # un acierto seguido de un fallo: lo guardado ya no pasa la validación
    for grupo in [] if faltan else pedidos:
        antes = aciertos()
        try:
            g.generar_grupo(grupo)
        except SinCache:
            faltan[grupo] = motivo_falta(antes)
    for grupo, motivo in faltan.items():
        for seccion in GRUPOS[grupo].secciones:
            if seccion not in g._secciones:
                g._vacios.append(Vacio(origen="seccion", referencia=seccion, motivo=motivo))
    if len(faltan) == len(pedidos):
        if solo_cache and (calentadas := cache.identidades()) and (prov.nombre, prov.modelo) not in calentadas:
            raise SinBorrador(cfg_cache.textos.desajuste_proveedor.format(
                calentado=" · ".join(f"{p}/{m}" for p, m in sorted(calentadas)), actual=f"{prov.nombre}/{prov.modelo}"))
        invalido = cfg_cache.textos.borrador_invalido in faltan.values()
        raise SinBorrador(cfg_cache.textos.borrador_invalido if invalido else cfg_cache.textos.sin_cache)
    paquete = g.paquete()
    assert paquete is not None
    return paquete


# ============================================================================================ CLI


def _entrada_desde_grupo(id_grupo: str, modalidad: str, base: Path) -> EntradaFicha:
    """Construye la ficha real del grupo (E1-10b) y la convierte en la entrada de la generación."""
    from src import db
    from src.ficha import construir_ficha

    con = db.conectar(base, solo_lectura=True)
    try:
        return desde_ficha(construir_ficha(id_grupo, modalidad, con, emb=None))
    finally:
        con.close()


def principal(argv: list[str] | None = None, crear: Callable[[], Proveedor] | None = None) -> int:
    """``python -m src.generacion --grupo GRP-…`` (ficha real) o ``--ficha-json ruta.json``: imprime el resultado en JSON."""
    from src.configuracion import MODALIDADES

    parser = argparse.ArgumentParser(description="Genera el borrador de un caso a partir de su ficha (E1-12)")
    parser.add_argument("--grupo", help="ID del grupo (GRP-…): construye la ficha con src/ficha.py y genera")
    parser.add_argument("--modalidad", choices=MODALIDADES, default="editorial")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--ficha-json", type=Path, help="EntradaFicha en JSON (alternativa a --grupo)")
    parser.add_argument("--forzar-completo", action="store_true", help="fuerza el paquete completo y lo deja registrado")
    parser.add_argument("--proveedor", choices=["ollama", "deepseek"], help="sobrescribe LLM_PROVIDER de local.env")
    args = parser.parse_args(argv)
    from src.registro import configurar_logging

    configurar_logging()
    if bool(args.grupo) == bool(args.ficha_json):
        parser.error("indique --grupo o --ficha-json (uno solo)")
    if args.grupo:
        if not args.base.exists():
            print(f"ERROR: no existe {args.base}: ejecute primero `poetry run python -m src.puntaje`", file=sys.stderr)
            return 1
        try:
            ficha = _entrada_desde_grupo(args.grupo, args.modalidad, args.base)
        except (LookupError, RuntimeError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    else:
        ficha = EntradaFicha.model_validate_json(args.ficha_json.read_text(encoding="utf-8"))
    try:
        if crear is None:
            from src.configuracion import leer_local_env
            from src.llm.proveedor import crear_proveedor

            env = {**leer_local_env(), **({"LLM_PROVIDER": args.proveedor} if args.proveedor else {})}
            crear = lambda: crear_proveedor(env)  # noqa: E731
        proveedor: Proveedor | None = crear() if planificar(ficha, args.forzar_completo, cargar_generacion()).tipo != "nada" else None
    except ErrorProveedor as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        r = generar(ficha, proveedor, args.forzar_completo)
    except TopeDeCostoAlcanzado as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    salida = {
        "tipo": r.tipo,
        "motivo": r.motivo,
        "paquete": r.paquete.model_dump() if r.paquete else None,
        "llamadas": [asdict(c) for c in r.llamadas],
        "descartadas": r.descartadas,
    }
    print(json.dumps(salida, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
