"""Validador de citas (etapa 6, E1-13; D-18, D-25, D-41, D-45, D-51, D-53, D-68).

**Toda afirmación factual pasa por aquí. Lo que no valida, no se emite.** Es código determinista: ningún LLM interviene. Cada
regla es una comprobación con nombre que devuelve un ``Rechazo`` tipado (``regla``, ``motivo``, ``fragmento``); la generación
(E1-12) descarta lo que no pasa, reintenta una vez y, si sigue fallando, entrega la sección vacía con el motivo.

Dos niveles:

- **Afirmaciones (paso 1)** — ``validar_afirmaciones``: la cita existe (ID + campo), reglas por tipo (D-41), cifras y fechas contra
  el campo citado (D-45), comillas literales, causalidad y acusaciones (D-68), frases prohibidas (D-25, D-51, D-53).
- **Secciones (paso 2)** — ``validar_seccion``: cada oración cita afirmaciones ya validadas y no agrega cifras, fechas ni nombres
  que ellas no traigan; límites y cantidades de ``config/salidas.yaml``; transiciones sin cita (D-41); atribución; contradicción
  abierta con ambas versiones; guion y copy.

Más ``validar_paquete`` (un paquete ya armado: leyenda D-51, marca de borrador y todas sus secciones) y ``validar_leyenda`` (cualquier
salida de texto: consulta, boletín, exportación).

**Registro.** ``RegistroRechazos`` agrega a ``outputs/rechazos.jsonl`` una línea por rechazo y una por unidad evaluada (afirmación o
sección), con el proveedor y el modelo: con ambas se calcula la tasa de rechazo por regla y por modelo (``--tasas``). Nunca se
escribe el valor de un secreto ni el system prompt.

Las listas y los umbrales viven en ``config/validador.yaml``, ``config/restricciones.yaml`` y ``config/salidas.yaml`` (D-79).

CLI: ``python -m src.validador --tasas`` resume el registro con n e intervalo de Wilson al 95 %.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.configuracion import (
    RAIZ,
    ConfigGeneracionBorrador,
    ConfigRestricciones,
    ConfigSalidas,
    ConfigValidador,
    cargar_consulta,
    cargar_generacion,
    cargar_restricciones,
    cargar_salidas,
    cargar_validador,
)
from src.limpieza import plano
from src.registro import MARCA_REDACCION, valores_sensibles

logger = logging.getLogger(__name__)

ESPACIOS = re.compile(r"\s+")
COMILLAS = re.compile(r"[\"“«](.+?)[\"”»]")
COMILLAS_SIMPLES = re.compile(r"(?<!\w)'(.+?)'(?!\w)")  # un apóstrofo («L'Équipe») no abre una cita
HASHTAG = re.compile(r"#\w+")
ID_EN_TEXTO = re.compile(r"\b(?:not|ind|grp|sis|sbp|syn|caso)-[\w.\-]+")  # sobre texto ya sin tildes ni mayúsculas
ENV_REGISTRO = "RECHAZOS_JSONL"  # sobrescribe la ruta del registro (las pruebas no escriben en outputs/)
MARCA_EXCESO = "supera el máximo"
SECCIONES_TITULAR = ("titulo", "titulo_trabajo", "titulares")

# Nombres de las reglas (los que aparecen en ``outputs/rechazos.jsonl``).
CITA_INEXISTENTE = "cita_inexistente"
HECHO_SIN_CITA = "hecho_sin_cita"
HECHO_NO_OFICIAL = "hecho_no_oficial"
DECLARACION_SIN_NOTICIA = "declaracion_sin_noticia"
SIN_ATRIBUCION = "sin_atribucion"
TITULAR_SIN_ATRIBUCION = "titular_sin_atribucion"
IND_SIN_ANIO = "ind_sin_anio"
IND_VOLATIL = "ind_volatil"
CIFRA_NO_COINCIDE = "cifra_no_coincide"
FECHA_NO_COINCIDE = "fecha_no_coincide"
COMILLAS_NO_LITERALES = "comillas_no_literales"
INFERENCIA_SIN_BASE = "inferencia_sin_base"
BASE_INVALIDA = "base_invalida"
NOMBRE_NUEVO = "nombre_nuevo"
HIPOTESIS_SIN_CONDICIONAL = "hipotesis_sin_condicional"
CAUSALIDAD = "causalidad"
ACUSACION = "acusacion"
DETALLE_SIN_CITA = "detalle_sin_cita"
IDS_REPETIDOS = "id_repetido"
FUGA_PROMPT = "fuga_prompt"
SECRETO = "secreto"
SIN_AFIRMACION = "oracion_sin_afirmacion"
AFIRMACION_DESCONOCIDA = "afirmacion_desconocida"
TRANSICION_NO_PERMITIDA = "transicion_no_permitida"
EXCESO_TRANSICIONES = "exceso_transiciones"
MARCADOR_VISUAL = "marcador_visual"
LIMITE_PALABRAS = "limite_palabras"
CANTIDAD = "cantidad"
ENFOQUE_COMO_HECHO = "enfoque_como_hecho"
CONTRADICCION_UNA_VERSION = "contradiccion_una_version"
GUION_ESTRUCTURA = "guion_estructura"
COPY_HASHTAGS = "copy_hashtags"
COPY_EMOJIS = "copy_emojis"
PREGUNTA_SIN_VACIO = "pregunta_sin_vacio"
LEYENDA = "leyenda_alcance"
MARCA = "marca_borrador"
SECCION_DESCONOCIDA = "seccion_desconocida"
ATRIBUCION_INCORRECTA = "atribucion_incorrecta"
OBSERVACION_CON_HIPOTESIS = "observacion_con_hipotesis"   # E2-02: una observación del boletín se apoya en una inferencia o hipótesis
IMPACTO_COMO_HECHO = "impacto_como_hecho"                 # E2-02: una hipótesis de impacto se apoya en un hecho o una declaración
IMPACTO_SIN_CONDICIONAL = "impacto_sin_condicional"       # E2-02: una hipótesis de impacto no está en condicional
AVISO = "aviso_banca"                                     # E2-02: el boletín lleva el aviso fijo de restricciones.yaml
OBSERVACION_CONDICIONAL = "observacion_condicional"       # X49: una observación no se redacta en condicional

# E2-02 · Los dos bloques del resumen del boletín (docs/salidas.md §2): su límite de palabras es conjunto.
BLOQUES_RESUMEN = ("observaciones", "hipotesis_impacto")


# ============================================================================================ el rechazo


@dataclass(frozen=True)
class Rechazo:
    """Un motivo por el que algo no se emite: qué regla, por qué y qué fragmento del texto la disparó."""

    regla: str
    motivo: str
    fragmento: str = ""
    seccion: str = ""
    item: str = ""

    @property
    def mensaje(self) -> str:
        """El motivo para una persona o para el aviso del reintento (con el fragmento si el motivo no lo trae)."""
        if self.fragmento and self.fragmento not in self.motivo:
            return f"{self.motivo}: «{self.fragmento}»"
        return self.motivo


def mensajes(rechazos: Iterable[Rechazo]) -> list[str]:
    return [r.mensaje for r in rechazos]


# ============================================================================================ texto, números y fechas


@lru_cache(maxsize=4096)
def _patron_frase(frase_plana: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(frase_plana)}(?!\w)")


def contiene(texto_plano: str, frase: str) -> bool:
    """La frase (sin tildes ni mayúsculas) está en el texto ya normalizado, como palabras completas."""
    return _patron_frase(plano(frase)).search(texto_plano) is not None


def contar_palabras(texto: str, ctx: Contexto | None = None) -> int:
    """Palabras de un texto. El marcador visual y la leyenda de alcance no cuentan (D-51)."""
    r = ctx.restricciones if ctx else cargar_restricciones()
    for fijo in (r.marcador_visual, r.leyendas_alcance.titular_metadatos, r.leyendas_alcance.con_descripcion):
        texto = texto.replace(fijo, " ")
    return len(re.findall(r"\S+", texto))


_NUM = re.compile(
    r"(?<![\w#.,])\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?(?!\w)|(?<![\w#.,])\d+(?:[.,]\d+)?(?!\w)"
)
Fecha = tuple[int | None, int | None, int | None]  # (año, mes, día); lo que no se dice es None


def _numero_de_mes(meses: Sequence[str]) -> dict[str, int]:
    tabla: dict[str, int] = {}
    n = 0
    for m in meses:
        if plano(m) == "setiembre":
            tabla[plano(m)] = 9
            continue
        n += 1
        tabla[plano(m)] = n
    return tabla


def extraer_fechas(texto: str, meses: Sequence[str]) -> tuple[list[Fecha], str]:
    """Fechas que dice el texto (ISO, «5 de octubre de 2026», «octubre de 2026», un año, un mes) y el texto sin ellas (en minúsculas)."""
    t = ID_EN_TEXTO.sub(" ", plano(texto))  # el ID de una cita («GRP-0123456789») no trae cifras ni fechas
    tabla = _numero_de_mes(meses)
    alt = "|".join(sorted(tabla, key=len, reverse=True))
    fechas: list[Fecha] = []

    def sacar(patron: str, convertir: Any) -> None:
        nonlocal t
        for m in re.finditer(patron, t):
            fechas.append(convertir(m))
        t = re.sub(patron, " ", t)

    sacar(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: (int(m[1]), int(m[2]), int(m[3])))
    sacar(rf"\b(\d{{1,2}}) de ({alt})(?: de (\d{{4}}))?\b", lambda m: (int(m[3]) if m[3] else None, tabla[m[2]], int(m[1])))
    sacar(rf"\b({alt}) de (\d{{4}})\b", lambda m: (int(m[2]), tabla[m[1]], None))
    sacar(r"(?<![\d.,])((?:19|20)\d{2})(?!\d)(?![.,]\d)", lambda m: (int(m[1]), None, None))
    sacar(rf"\b({alt})\b", lambda m: (None, tabla[m[1]], None))
    return fechas, t


def _fecha_respaldada(f: Fecha, evidencia: Iterable[Fecha]) -> bool:
    return any(all(fc is None or (ec is not None and fc == ec) for fc, ec in zip(f, e)) for e in evidencia)


def _candidatos(token: str) -> set[Decimal]:
    """Valores posibles de una cifra escrita con coma o punto: «1,5» y «1.5» son 1.5; «1.234» puede ser 1.234 o 1234."""
    t = token.replace(" ", "").replace(" ", "")
    seps = [c for c in t if c in ".,"]
    if not seps:
        return {Decimal(t)}
    if len(seps) == 1:
        ent, fra = t.split(seps[0])
        valores = {Decimal(f"{ent}.{fra}")}
        if len(fra) == 3 and len(ent) <= 3:
            valores.add(Decimal(ent + fra))
        return valores
    if len(set(seps)) == 1:
        return {Decimal(t.replace(seps[0], ""))}
    ultimo = max(t.rfind("."), t.rfind(","))
    return {Decimal(re.sub(r"[.,]", "", t[:ultimo]) + "." + t[ultimo + 1 :])}


def _numero_en_palabras(run: list[str], cfg: ConfigValidador) -> Decimal:
    """Valor de una secuencia de palabras numéricas («dos mil quinientos», «dos coma nueve»)."""
    total, actual, decimales = 0, 0, None
    unidades = {**cfg.palabras_numero, **cfg.numerales_en_compuesto}
    for w in run:
        if w == "y":
            continue
        if w == "coma":
            decimales = []
            continue
        if decimales is not None:
            decimales.append(str(unidades[w]))
        elif w in cfg.multiplicadores:
            if cfg.multiplicadores[w] >= 1_000_000:
                total, actual = total + max(actual, 1) * cfg.multiplicadores[w], 0
            else:
                actual = max(actual, 1) * cfg.multiplicadores[w]
        else:
            actual += unidades[w]
    valor = Decimal(total + actual)
    return valor + Decimal("0." + "".join(decimales)) if decimales else valor


def _numeros_en_palabras(texto_plano: str, cfg: ConfigValidador) -> list[tuple[str, set[Decimal]]]:
    """Cifras escritas con palabras: «tres», «mil quinientos», «dos coma nueve». «un»/«una» solos no cuentan."""
    simples = set(cfg.palabras_numero) | set(cfg.multiplicadores)
    compuestos = set(cfg.numerales_en_compuesto)
    tokens = re.findall(r"[a-z]+", re.sub(r"\bpor ciento\b", " ", texto_plano))  # «por ciento» es el %, no la cifra 100
    salida: list[tuple[str, set[Decimal]]] = []
    i = 0
    while i < len(tokens):
        if tokens[i] not in simples:
            i += 1
            continue
        run = [tokens[i]]
        j = i + 1
        while j < len(tokens):
            t = tokens[j]
            if t in simples or (t in compuestos and run[-1] in ("y", *cfg.palabras_numero)) :
                run.append(t)
            elif t == "y" and j + 1 < len(tokens) and (tokens[j + 1] in simples or tokens[j + 1] in compuestos):
                run.append(t)
            elif t == "coma" and j + 1 < len(tokens) and (tokens[j + 1] in cfg.palabras_numero or tokens[j + 1] in compuestos):
                run.append(t)
            else:
                break
            j += 1
        try:
            salida.append((" ".join(run), {_numero_en_palabras(run, cfg)}))
        except (KeyError, ArithmeticError):
            pass
        i = j
    return salida


def numeros_de(texto: str, cfg: ConfigValidador) -> list[tuple[str, set[Decimal]]]:
    """Cifras del texto (sin las fechas), en dígitos o en palabras, cada una con sus valores posibles. «1,5 %» y «1.5» dan el mismo valor."""
    _, resto = extraer_fechas(texto, cfg.meses)
    for f in cfg.frases_sin_cifra:
        resto = re.sub(rf"(?<!\w){re.escape(plano(f))}(?!\w)", " ", resto)
    return [(m.group(0), _candidatos(m.group(0))) for m in _NUM.finditer(resto)] + _numeros_en_palabras(resto, cfg)


def cantidades_vagas_de(texto: str, cfg: ConfigValidador) -> list[str]:
    """«Miles de», «decenas de», «la mitad»…: cantidades que no se pueden comparar con una cifra."""
    p = plano(texto)
    return [c for c in cfg.cantidades_vagas if contiene(p, c)]


def _coincide(valor: Decimal, otro: Decimal, cfg: ConfigValidador) -> bool:
    """La cifra del texto respalda el valor citado: igual, o redondeada a los decimales que escribe (al menos ``decimales_minimos``) y
    dentro de la tolerancia relativa. «2 %» no respalda 1.5; «1,5 %» y «1,49 %» sí."""
    n = cfg.numeros
    if abs(valor - otro) <= Decimal(str(n.tolerancia_absoluta)):
        return True
    d = max(0, -int(valor.as_tuple().exponent))  # type: ignore[arg-type]
    if d < n.decimales_minimos or d > n.decimales_maximos:
        return False
    if n.redondeo_permitido and otro.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP) == valor:
        return True
    return otro != 0 and abs(valor - otro) / abs(otro) <= Decimal(str(n.tolerancia_relativa))


def cifras_sin_respaldo(texto: str, fuentes: Iterable[str], cfg: ConfigValidador) -> list[str]:
    """Cifras del texto que ninguna fuente trae (normalizadas: coma o punto decimal, %, separador de miles, palabras)."""
    respaldo = [c for f in fuentes for _, c in numeros_de(f, cfg)]
    faltan = []
    for token, candidatos in numeros_de(texto, cfg):
        if not any(_coincide(v, o, cfg) for v in candidatos for conj in respaldo for o in conj):
            faltan.append(token)
    return faltan


_PALABRA = re.compile(r"[^\W\d_][\w'’-]*")


def nombres_propios(texto: str, ctx: Contexto) -> list[str]:
    """Palabras con mayúscula que no abren oración (nombres, entidades, siglas). Si una oración abre con dos mayúsculas seguidas
    («Juan Pérez …») también cuentan. Hashtags y marcadores visuales se ignoran."""
    t = HASHTAG.sub(" ", texto.replace(ctx.restricciones.marcador_visual, " "))
    m_min = ctx.val.nombre_min_caracteres
    palabras = list(_PALABRA.finditer(t))
    salida: list[str] = []
    for i, m in enumerate(palabras):
        w = m.group(0)
        if len(w) < m_min or not w[0].isupper():
            continue
        antes = t[: m.start()].rstrip()
        inicial = not antes or antes[-1] in ".?!:;¿¡«\"“(—-[" or antes[-1] == "\n"
        if inicial:
            if plano(w) in {plano(x) for x in ctx.val.transiciones.inicio_no_entidad} or plano(w) in ctx.atribucion:
                continue
            sig = palabras[i + 1].group(0) if i + 1 < len(palabras) else ""
            if not (sig and sig[0].isupper() and len(sig) >= m_min and t[m.end() : palabras[i + 1].start()].strip() == ""):
                continue
        salida.append(w)
    return salida


# ============================================================================================ el contexto


class Contexto:
    """Lo que necesita el validador: la ficha indexada, las afirmaciones ya validadas, la configuración y el system prompt.

    ``ficha`` es cualquiera con ``registros`` (``id``, ``campos``, ``contexto``, ``idioma``, ``campo_texto``), ``vacios`` (``id``),
    ``contradicciones`` (``id_a``, ``id_b``, ``abierta``) y ``uso_descripcion``.
    """

    def __init__(
        self,
        ficha: Any,
        grupos_restricciones: Sequence[str] = (),
        *,
        cfg: ConfigGeneracionBorrador | None = None,
        salidas: ConfigSalidas | None = None,
        restricciones: ConfigRestricciones | None = None,
        val: ConfigValidador | None = None,
    ) -> None:
        self.ficha = ficha
        self.cfg = cfg or cargar_generacion()
        self.salidas = salidas or cargar_salidas()
        self.restricciones = restricciones or cargar_restricciones()
        self.val = val or cargar_validador()
        self.registros = {r.id: r for r in ficha.registros}
        self.vacios = {v.id for v in ficha.vacios}
        self.atribucion = [plano(m) for m in self.cfg.atribucion.marcadores]
        self.listas: dict[str, list[str]] = {}
        self.listas_originales: dict[str, list[str]] = {}  # con tildes, para las listas que se comparan así (X50)
        for g in grupos_restricciones:
            for nombre, lista in self.restricciones.grupos[g].items():
                self.listas.setdefault(nombre, []).extend(plano(f) for f in lista)
                self.listas_originales.setdefault(nombre, []).extend(lista)
        self.afirmaciones: dict[str, Any] = {}
        self.system = ""
        self._condicionales = [plano(c) for c in self.val.condicionales]
        # Límites de la modalidad de la ficha (bloque homónimo de salidas.yaml); sin bloque propio, los de la editorial.
        bloque = getattr(self.salidas, str(getattr(ficha, "modalidad", "")), None)
        self.n_preguntas: int = getattr(bloque, "preguntas", self.salidas.editorial.preguntas)

    # ---- evidencia

    def valor(self, id_: str, campo: str) -> str:
        r = self.registros.get(id_)
        return r.campos.get(campo, "") if r else ""

    def medio(self, id_: str) -> str:
        r = self.registros.get(id_)
        return r.contexto.get("medio", "") if r else ""

    def texto_citado(self, citas: Iterable[tuple[str, str]]) -> str:
        """Solo los campos citados (la spec dice «el titular citado»), no todo el registro."""
        return " ".join(self.valor(i, c) for i, c in citas)

    def traducido(self, id_: str) -> bool:
        r = self.registros.get(id_)
        return bool(r and r.idioma and r.idioma != self.cfg.traducido.idioma_base)

    def texto_registro(self, id_: str) -> str:
        r = self.registros.get(id_)
        return " ".join(r.campos.values()) if r else ""

    def es_anual(self, id_: str) -> str | None:
        """Año de un ID de dato oficial anual (``IND-PAN-…-2024`` → ``2024``); ``None`` si no lo es."""
        if not id_.startswith(tuple(self.cfg.prefijos.hecho_oficial)):
            return None
        m = re.search(self.cfg.patron_anio_en_id, id_)
        return m.group(1) if m else None

    def fechas_de(self, citas: Iterable[tuple[str, str]]) -> list[Fecha]:
        """Fechas de la evidencia citada: sus campos de fecha, el año del ID y las fechas que el propio texto citado dice (D-45)."""
        meses = self.val.meses
        fechas: list[Fecha] = []
        for id_, campo in citas:
            r = self.registros.get(id_)
            if r is None:
                continue
            if anio := self.es_anual(id_):
                fechas.append((int(anio), None, None))
            for clave, v in {**r.contexto, **r.campos}.items():
                if any(plano(f) in plano(clave) for f in self.val.campos_fecha):
                    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", v):
                        fechas.append((int(m[1]), int(m[2]), int(m[3])))
                    else:
                        fechas += extraer_fechas(v, meses)[0]
            fechas += extraer_fechas(r.campos.get(campo, ""), meses)[0]
        return fechas

    def fuentes_de(self, citas: Iterable[tuple[str, str]]) -> list[str]:
        """Los valores de los campos citados (lo que respalda una cifra o una comilla)."""
        return [self.valor(i, c) for i, c in citas]

    # ---- atribución y condicionales

    def atribuido(self, texto: str, ids: Iterable[str]) -> bool:
        p = plano(texto)
        medios = [plano(self.medio(i)) for i in ids]
        return any(contiene(p, m) for m in self.atribucion) or any(m and contiene(p, m) for m in medios)

    def condicional(self, texto: str) -> bool:
        p = plano(texto)
        return any(contiene(p, c) for c in self._condicionales)


# ============================================================================================ reglas sobre un texto


@dataclass
class Soporte:
    """En qué se apoya un texto: las citas (ID + campo) de sus afirmaciones, sus textos y sus tipos."""

    citas: list[tuple[str, str]] = field(default_factory=list)
    textos: list[str] = field(default_factory=list)
    tipos: list[str] = field(default_factory=list)
    directas: list[Any] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return list(dict.fromkeys(i for i, _ in self.citas))


def _clausura(directas: Sequence[Any], mapa: dict[str, Any]) -> list[Any]:
    """Las afirmaciones citadas y, de forma transitiva, las de su base (una inferencia se apoya en ellas)."""
    vistas: dict[str, Any] = {}
    pendientes = list(directas)
    while pendientes:
        a = pendientes.pop()
        if a.id in vistas:
            continue
        vistas[a.id] = a
        pendientes += [mapa[b] for b in getattr(a, "base", []) if b in mapa]
    return list(vistas.values())


def _soporte(directas: Sequence[Any], mapa: dict[str, Any]) -> Soporte:
    todas = _clausura(directas, mapa)
    return Soporte(
        citas=list(dict.fromkeys((c.id, c.campo) for a in todas for c in a.citas)),
        textos=[a.texto for a in todas],
        tipos=[a.tipo for a in directas],
        directas=list(directas),
    )


def _fragmento_en(p: str, frase: str, original: str) -> str:
    """El trozo del texto original que corresponde a la frase (para el registro); si no se ubica, la frase."""
    m = _patron_frase(plano(frase)).search(p)
    return original[m.start() : m.end()] if m and len(plano(original)) == len(p) else frase


def _literal_en(ctx: Contexto, frase: str, citas: Iterable[tuple[str, str]]) -> bool:
    """La frase está literalmente en el campo citado (sin distinguir mayúsculas ni tildes)."""
    return contiene(plano(ctx.texto_citado(citas)), frase)


def _tokens(texto_plano: str) -> list[str]:
    return re.findall(r"\w+", texto_plano)


def _sublista(parte: Sequence[str], todo: Sequence[str]) -> bool:
    n = len(parte)
    return any(list(todo[i : i + n]) == list(parte) for i in range(len(todo) - n + 1))


def fragmento_literal(texto_plano: str, frase: str, citado_plano: str, ventana: int) -> bool:
    """X49: cada aparición de la frase en el texto, con ``ventana`` palabras a cada lado (las que haya), está literal en el texto citado.
    Comparación por palabras, sin tildes ni mayúsculas ni puntuación. Sin ninguna aparición devuelve ``False``."""
    t, f, c = _tokens(texto_plano), _tokens(plano(frase)), _tokens(citado_plano)
    apariciones = [i for i in range(len(t) - len(f) + 1) if f and t[i : i + len(f)] == f]
    return bool(apariciones) and all(_sublista(t[max(0, i - ventana) : i + len(f) + ventana], c) for i in apariciones)


def _excepcion_literal(ctx: Contexto, texto_plano: str, frase: str, citas: Iterable[tuple[str, str]], ventana: int) -> bool:
    """La frase prohibida se admite si está literal en el campo citado: con ``ventana`` > 0, también el fragmento que la rodea (X49)."""
    citas = list(citas)
    if not ventana:
        return _literal_en(ctx, frase, citas)
    return fragmento_literal(texto_plano, frase, plano(ctx.texto_citado(citas)), ventana)


def _acento(texto: str) -> str:
    return unicodedata.normalize("NFC", texto).casefold()


def _contiene_acento(texto: str, frase: str) -> bool:
    """Como ``contiene`` pero conservando las tildes: «robó» (verbo) y «robo» (sustantivo) son palabras distintas (L4)."""
    return re.search(rf"(?<!\w){re.escape(_acento(frase))}(?!\w)", _acento(texto)) is not None


def _reglas_de_texto(
    texto: str, s: Soporte, ctx: Contexto, seccion: str, *, numerico: bool, tipo_propio: str | None = None
) -> list[Rechazo]:
    """Reglas comunes a una afirmación y a una oración: secretos, frases prohibidas, comillas, causalidad, acusaciones, detalles sin
    cita y (si ``numerico``) cifras, fechas y nombres que el soporte no trae."""
    out: list[Rechazo] = []
    ids = s.ids
    p = plano(texto)
    if any(v in texto for v in valores_sensibles()) or MARCA_REDACCION in texto:
        out.append(Rechazo(SECRETO, "el texto contiene un secreto o un valor redactado"))
    if _revela_system(texto, ctx):
        out.append(Rechazo(FUGA_PROMPT, "el texto repite fragmentos del system prompt"))
    tipos = set(s.tipos)
    for nombre, frases in ctx.listas.items():
        conf = ctx.val.listas.get(nombre)
        if conf and conf.tipos and not tipos & set(conf.tipos):
            continue
        if conf and conf.con_tildes:  # X50: «bajará» (futuro) no es «bajara» (subjuntivo)
            encontradas = [f for f in ctx.listas_originales.get(nombre, []) if _contiene_acento(texto, f)]
        else:
            encontradas = [f for f in frases if contiene(p, f)]
        encontradas += [m.group(0).strip(" .;:!?¿¡") for pat in ctx.val.patrones.get(nombre, []) if (m := re.search(pat, p))]
        for f in dict.fromkeys(encontradas):
            tipos_ok = not conf or not conf.excepcion_tipos or (bool(tipos) and tipos <= set(conf.excepcion_tipos))
            if conf and conf.excepcion_literal and tipos_ok and seccion not in conf.sin_excepcion_en and _excepcion_literal(ctx, p, f, s.citas, conf.ventana_literal):
                continue
            out.append(Rechazo(nombre, f"frase prohibida ({nombre}): «{f}»", f))
    for f in ctx.val.detalle_sin_cita:
        if contiene(p, f) and not _literal_en(ctx, f, s.citas):
            out.append(Rechazo(DETALLE_SIN_CITA, f"detalle que la evidencia citada no trae: «{f}»", f))
    fuente = ESPACIOS.sub(" ", plano(ctx.texto_citado(s.citas)))
    for m in [*COMILLAS.finditer(texto), *COMILLAS_SIMPLES.finditer(texto)]:
        if ESPACIOS.sub(" ", plano(m.group(1))).strip() not in fuente:
            out.append(Rechazo(COMILLAS_NO_LITERALES, f"comillas que no son literales del titular citado: «{m.group(1)}»", m.group(1)))
    out += _causalidad(texto, p, s, ctx)
    out += _acusaciones(texto, p, s, ctx)
    if numerico:
        out += _numerico(texto, s, ctx)
    return out


def _sin_fugas(rechazos: list[Rechazo]) -> list[Rechazo]:
    """Si un texto trae un secreto o el system prompt, solo se informa eso: ningún otro motivo cita ese texto."""
    return [r for r in rechazos if r.regla in (SECRETO, FUGA_PROMPT)] or rechazos


def _revela_system(texto: str, ctx: Contexto) -> bool:
    """El texto repite ``n`` palabras consecutivas del system prompt (T07: no revelar las instrucciones)."""
    if not ctx.system:
        return False
    n = ctx.cfg.fuga_prompt.palabras_por_fragmento
    base = re.findall(r"\w+", plano(ctx.system))
    huella = {tuple(base[i : i + n]) for i in range(len(base) - n + 1)}
    dicho = re.findall(r"\w+", plano(texto))
    return any(tuple(dicho[i : i + n]) in huella for i in range(len(dicho) - n + 1))


def _causal_permitido(c: str, texto: str, s: Soporte, ctx: Contexto) -> bool:
    """Una declaración lo permite si el conector está literal en su titular; una hipótesis, si el texto es condicional; nada más."""
    if s.directas:
        for a in s.directas:
            if a.tipo == "declaración":
                if not _literal_en(ctx, c, [(x.id, x.campo) for x in a.citas]):
                    return False
            elif a.tipo == "hipótesis":
                if not ctx.condicional(texto):
                    return False
            else:
                return False
        return True
    if s.tipos == ["declaración"]:  # afirmación suelta: el tipo es el propio
        return _literal_en(ctx, c, s.citas)
    return s.tipos == ["hipótesis"] and ctx.condicional(texto)


def _causalidad(texto: str, p: str, s: Soporte, ctx: Contexto) -> list[Rechazo]:
    """D-68: un conector causal solo aparece literal en el titular citado (declaración atribuida) o en una hipótesis condicional."""
    return [
        Rechazo(CAUSALIDAD, f"causalidad que la evidencia no trae: «{c}» (solo en una declaración literal del titular o en una hipótesis condicional)", c)
        for c in ctx.val.causales
        if contiene(p, c) and not _causal_permitido(c, texto, s, ctx)
    ]


def _acusaciones(texto: str, p: str, s: Soporte, ctx: Contexto) -> list[Rechazo]:
    """D-68: una acusación (verbo, participio, sustantivo o forma condicional) es siempre una declaración atribuida a un medio y presente
    literal en el campo citado. Se compara con tildes: «robó» y «robo» son entradas distintas."""
    out: list[Rechazo] = []
    citado = ctx.texto_citado(s.citas)
    for a in ctx.val.acusaciones:
        if not _contiene_acento(texto, a):
            continue
        if s.directas:
            tipos_ok = all(x.tipo == "declaración" for x in s.directas)
        else:
            tipos_ok = bool(s.tipos) and s.tipos[0] == "declaración"
        if tipos_ok and ctx.atribuido(texto, s.ids) and _contiene_acento(citado, a):
            continue
        out.append(Rechazo(ACUSACION, f"acusación fuera de una declaración atribuida a un medio y literal del titular: «{a}»", a))
    return out


def _numerico(texto: str, s: Soporte, ctx: Contexto) -> list[Rechazo]:
    """Cifras, fechas y nombres del texto que ni la evidencia citada ni las afirmaciones de apoyo traen (D-41, D-45)."""
    out: list[Rechazo] = []
    fuentes = [*ctx.fuentes_de(s.citas), *s.textos]
    for c in cifras_sin_respaldo(texto, fuentes, ctx.val):
        out.append(Rechazo(CIFRA_NO_COINCIDE, f"la cifra «{c}» no coincide con el valor de la evidencia citada", c))
    respaldo = plano(" ".join(fuentes))
    for q in cantidades_vagas_de(texto, ctx.val):
        if not contiene(respaldo, q):
            out.append(Rechazo(CIFRA_NO_COINCIDE, f"una cantidad sin cifra exacta («{q}») que la evidencia citada no trae", q))
    meses = ctx.val.meses
    fechas, _ = extraer_fechas(texto, meses)
    if fechas:
        evidencia = ctx.fechas_de(s.citas) + [f for t in s.textos for f in extraer_fechas(t, meses)[0]]
        for f in fechas:
            if not _fecha_respaldada(f, evidencia):
                out.append(Rechazo(FECHA_NO_COINCIDE, f"la fecha {_fecha_texto(f)} no coincide con ningún campo de fecha de la evidencia citada", _fecha_texto(f)))
    return out


def _fecha_texto(f: Fecha) -> str:
    y, m, d = f
    return "-".join(str(x).zfill(2) if i else str(x) for i, x in enumerate((y, m, d)) if x is not None) or "?"


def _traducciones(texto_fuente: str, ctx: Contexto) -> tuple[set[str], set[str]]:
    """De un titular en otro idioma: las palabras que una traducción legítima agrega (equivalencias de ``validador.yaml``) y las palabras
    de la fuente, para reconocer cognados (Singapur / Singapore). Una entidad ausente de ambas sigue rechazándose."""
    p = plano(texto_fuente)
    extra: set[str] = set()
    for es, ingles in ctx.val.equivalencias_traduccion.items():
        if any(contiene(p, i) for i in ingles):
            extra |= set(re.findall(r"\w+", plano(es)))
    return extra, set(re.findall(r"\w+", p))


def _pais_y_fuente(ids: Iterable[str], ctx: Contexto) -> list[str]:
    """X33: de un ID oficial salen el país (``IND-COL-…`` → Colombia, nombres de ``consulta.yaml``) y la fuente por prefijo (IND- → Banco Mundial)."""
    nombres = cargar_consulta().datos_oficiales.nombres_pais
    salida: list[str] = []
    for i in ids:
        prefijo = i.split("-", 1)[0]
        if prefijo in ctx.val.fuentes_por_prefijo:
            salida.append(ctx.val.fuentes_por_prefijo[prefijo])
        if m := re.match(r"IND-([A-Z]{3})-", i):
            salida.append(nombres.get(m.group(1), ""))
    return salida


def _nombres_nuevos(texto: str, s: Soporte, ctx: Contexto) -> list[Rechazo]:
    """Nombres propios que ni los campos citados, su contexto (medio, indicador), ni las afirmaciones de apoyo traen (D-41, D-51)."""
    ids = s.ids
    contexto = [v for i in ids for v in (ctx.registros[i].contexto.values() if i in ctx.registros else [])]
    permitido = " ".join([*s.textos, ctx.texto_citado(s.citas), *contexto, *ids, *_pais_y_fuente(ids, ctx), *ctx.val.nombres_permitidos])  # el ID citado es el ancla de la cita
    tokens = set(re.findall(r"\w+", plano(permitido)))
    traducidos = [i for i in ids if ctx.traducido(i)]
    palabras_fuente: set[str] = set()
    if traducidos:
        extra, palabras_fuente = _traducciones(ctx.texto_citado(c for c in s.citas if c[0] in traducidos), ctx)
        tokens |= extra
    k = ctx.val.cognados_prefijo_min
    out: list[Rechazo] = []
    for n in nombres_propios(texto, ctx):
        partes = re.findall(r"\w+", plano(n))
        conocido = all(x in tokens or (palabras_fuente and len(x) >= k and any(w[:k] == x[:k] for w in palabras_fuente if len(w) >= k)) for x in partes)
        if partes and not conocido:
            out.append(Rechazo(NOMBRE_NUEVO, f"el nombre «{n}» no está en las afirmaciones ni en la evidencia citadas", n))
    return out


def _atribucion_incorrecta(texto: str, s: Soporte, ctx: Contexto) -> list[Rechazo]:
    """Una declaración no nombra a un medio de la ficha que no es el de sus citas («Reuters reporta» sobre un titular de TVN)."""
    propios = {plano(ctx.medio(i)) for i in s.ids}
    p = plano(texto)
    return [
        Rechazo(ATRIBUCION_INCORRECTA, f"la declaración se atribuye a «{r.contexto['medio']}», que no es el medio del registro citado", r.contexto["medio"])
        for r in ctx.registros.values()
        if r.contexto.get("medio") and plano(r.contexto["medio"]) not in propios and contiene(p, r.contexto["medio"])
    ]


def _anio_y_volatiles(texto: str, directas: Sequence[Any], ctx: Contexto, *, todos_los_anios: bool = True) -> list[Rechazo]:
    """Una cita ``IND-`` exige el año en el texto y prohíbe «actual», «hoy» y «actualmente» (CLAUDE.md).

    Una afirmación lleva el año de cada ID que cita; una oración que resume varias, al menos uno (cada cifra ya se compara con la afirmación)."""
    out: list[Rechazo] = []
    p = plano(texto)
    anuales = {i: y for a in directas for c in a.citas if (y := ctx.es_anual(c.id)) for i in [c.id]}
    esta = {id_: bool(re.search(rf"(?<!\d){anio}(?!\d)", texto)) for id_, anio in anuales.items()}
    for id_, anio in anuales.items():
        if not esta[id_] and (todos_los_anios or not any(esta.values())):
            out.append(Rechazo(IND_SIN_ANIO, f"un dato oficial anual incluye su año ({anio}) en el texto", id_))
    if anuales:
        for v in ctx.cfg.volatiles:
            if contiene(p, v):
                out.append(Rechazo(IND_VOLATIL, f"un dato oficial anual no se describe como actual ni de hoy: «{v}»", v))
    return out


# ============================================================================================ afirmaciones (paso 1)


@dataclass
class ResultadoAfirmaciones:
    """Las afirmaciones que pasaron (en su orden, con su base también válida) y todo lo rechazado con su regla."""

    validas: list[Any]
    rechazos: list[Rechazo]

    @property
    def descartadas(self) -> list[str]:
        """«A3: motivo; motivo» por cada afirmación descartada (formato de ``ResultadoGeneracion.descartadas``)."""
        por_item: dict[str, list[str]] = defaultdict(list)
        for r in self.rechazos:
            por_item[r.item].append(r.mensaje)
        return [f"{item}: " + "; ".join(ms) for item, ms in por_item.items()]


def _errores_de_afirmacion(a: Any, ctx: Contexto) -> list[Rechazo]:
    """Reglas propias de una afirmación (sin mirar su base, que se resuelve después)."""
    out: list[Rechazo] = []
    for c in a.citas:
        r = ctx.registros.get(c.id)
        if r is None or c.campo not in r.campos:
            out.append(Rechazo(CITA_INEXISTENTE, f"cita inexistente en la ficha: {c.id} · {c.campo}", f"{c.id} · {c.campo}"))
    if out:
        return out
    ids = [c.id for c in a.citas]
    p = ctx.cfg.prefijos
    if a.tipo == "hecho":
        if not a.citas:
            return [Rechazo(HECHO_SIN_CITA, "todo hecho tiene al menos una cita")]
        for c in a.citas:
            oficial = c.id.startswith(tuple(p.hecho_oficial))
            conteo = c.id.startswith(tuple(p.hecho_conteo)) and c.campo in ctx.cfg.campos_conteo
            if not (oficial or conteo):
                out.append(
                    Rechazo(
                        HECHO_NO_OFICIAL,
                        f"un hecho solo cita datos oficiales ({', '.join(p.hecho_oficial)}) o el conteo del grupo ({', '.join(p.hecho_conteo)}); "
                        f"{c.id} es lo que reporta un medio: una declaración",
                        c.id,
                    )
                )
                break
    if a.tipo == "declaración":
        if not any(c.id.startswith(tuple(p.reportes)) for c in a.citas):
            out.append(Rechazo(DECLARACION_SIN_NOTICIA, "una declaración cita lo que reporta un medio (un titular)"))
        if not ctx.atribuido(a.texto, ids):
            out.append(Rechazo(SIN_ATRIBUCION, "una declaración lleva atribución en el texto: el nombre del medio o un verbo de reporte"))
    if a.tipo == "hipótesis" and not ctx.condicional(a.texto):
        out.append(Rechazo(HIPOTESIS_SIN_CONDICIONAL, "una hipótesis se redacta en condicional («podría», «es posible», «a verificar»…)"))
    if a.tipo in ("hecho", "declaración"):
        out += _anio_y_volatiles(a.texto, [a], ctx)
    s = Soporte(citas=[(c.id, c.campo) for c in a.citas], textos=[], tipos=[a.tipo])
    out += _reglas_de_texto(a.texto, s, ctx, "afirmaciones", numerico=a.tipo in ("hecho", "declaración"))
    if a.tipo in ("hecho", "declaración"):
        out += _nombres_nuevos(a.texto, s, ctx)
    if a.tipo == "declaración":
        out += _atribucion_incorrecta(a.texto, s, ctx)
    return _sin_fugas(out)


def validar_afirmaciones(crudas: Sequence[Any], ctx: Contexto, maximo: int | None = None) -> ResultadoAfirmaciones:
    """Conserva las afirmaciones válidas (con su base también válida) y devuelve cada rechazo con su regla.

    Una inferencia o una hipótesis cita las afirmaciones en que se apoya y no trae cifras, fechas ni nombres que ellas no traigan.
    ``maximo`` (opcional) deja solo las primeras que no dependen de una base descartada por el recorte.
    """
    rechazos: list[Rechazo] = []
    propias: dict[str, Any] = {}

    def rechazar(a: Any, nuevos: Iterable[Rechazo]) -> None:
        rechazos.extend(replace(r, item=a.id, seccion="afirmaciones") for r in nuevos)

    for a in crudas:
        if a.id in propias:
            rechazar(a, [Rechazo(IDS_REPETIDOS, "id repetido")])
            continue
        errores = _errores_de_afirmacion(a, ctx)
        if errores:
            rechazar(a, errores)
        else:
            propias[a.id] = a
    cambio = True
    while cambio:  # una inferencia cae si cae su base
        cambio = False
        for id_, a in list(propias.items()):
            if a.tipo in ("inferencia", "hipótesis") and not a.base:
                rechazar(a, [Rechazo(INFERENCIA_SIN_BASE, f"una {a.tipo} cita las afirmaciones en que se basa")])
                del propias[id_]
                cambio = True
            elif a.base and (id_ in a.base or any(b not in propias for b in a.base)):
                rechazar(a, [Rechazo(BASE_INVALIDA, "su base no existe o no es válida")])
                del propias[id_]
                cambio = True
    for id_, a in list(propias.items()):
        if a.tipo in ("inferencia", "hipótesis"):
            s = _soporte([propias[b] for b in a.base], propias)
            s = replace(s, tipos=[a.tipo], directas=[])
            nuevos = [
                replace(r, motivo=r.motivo.replace("la cifra", f"una {a.tipo} no puede traer cifras nuevas: la cifra"))
                for r in _numerico(a.texto, s, ctx)
            ] + _nombres_nuevos(a.texto, s, ctx)
            if nuevos:
                rechazar(a, nuevos)
                del propias[id_]
    while True:  # la caída de una puede arrastrar a otra
        caidas = [i for i, a in propias.items() if any(b not in propias for b in a.base)]
        if not caidas:
            break
        for i in caidas:
            rechazar(propias[i], [Rechazo(BASE_INVALIDA, "su base no existe o no es válida")])
            del propias[i]
    elegidas = list(propias.values())
    if maximo is not None:
        elegidas = elegidas[:maximo]
        while True:  # el recorte no deja una inferencia sin su base
            ids = {a.id for a in elegidas}
            quedan = [a for a in elegidas if all(b in ids for b in a.base)]
            if len(quedan) == len(elegidas):
                break
            elegidas = quedan
    return ResultadoAfirmaciones(elegidas, rechazos)


# ============================================================================================ secciones (paso 2)


def _citadas(o: Any, ctx: Contexto) -> list[Any]:
    return [ctx.afirmaciones[i] for i in o.afirmaciones if i in ctx.afirmaciones]


def _es_transicion(texto: str, ctx: Contexto) -> list[str]:
    """Por qué una oración sin cita NO es una transición permitida (D-41): vacío si lo es."""
    t = ctx.val.transiciones
    problemas: list[str] = []
    if contar_palabras(texto, ctx) > t.max_palabras:
        problemas.append(f"más de {t.max_palabras} palabras")
    if any(c.isdigit() for c in texto) or numeros_de(texto, ctx.val) or cantidades_vagas_de(texto, ctx.val):
        problemas.append("trae cifras o fechas")
    p = plano(texto)
    if juicios := [j for j in ctx.val.juicios_transicion if contiene(p, j)]:
        problemas.append(f"lleva un juicio de valor sin cita ({', '.join(juicios)})")
    fechas, _ = extraer_fechas(texto, ctx.val.meses)
    if fechas and "trae cifras o fechas" not in problemas:
        problemas.append("trae fechas")
    conocidas = {w for r in ctx.registros.values() for w in re.findall(r"\w+", plano(" ".join([*r.campos.values(), *r.contexto.values()])))}
    nombres = nombres_propios(texto, ctx)
    primera = _PALABRA.search(texto)
    if primera and primera.group(0)[0].isupper():  # la primera palabra solo es entidad si la evidencia la trae y no es de las comunes
        w = plano(primera.group(0))
        if w in conocidas and w not in {plano(x) for x in t.inicio_no_entidad}:
            nombres.append(primera.group(0))
    if nombres:
        problemas.append(f"nombra entidades ({', '.join(dict.fromkeys(nombres))})")
    return problemas


def _revisar_oracion(o: Any, ctx: Contexto, seccion: str, *, permite_marcador: bool = False) -> tuple[list[Rechazo], bool]:
    """Reglas de una oración. Devuelve los rechazos y si fue una transición sin cita permitida."""
    marcador = ctx.restricciones.marcador_visual
    if o.texto.strip() == marcador:
        if not permite_marcador:
            return [Rechazo(MARCADOR_VISUAL, f"el marcador {marcador} solo se permite en el guion", marcador)], False
        if o.afirmaciones:
            return [Rechazo(MARCADOR_VISUAL, "un marcador visual no lleva afirmaciones", marcador)], False
        return [], False
    out: list[Rechazo] = []
    if "[VISUAL" in o.texto:
        out.append(Rechazo(MARCADOR_VISUAL, f"el único marcador visual permitido es {marcador}, como oración propia", o.texto))
    desconocidas = [i for i in o.afirmaciones if i not in ctx.afirmaciones]
    if desconocidas:
        out.append(Rechazo(AFIRMACION_DESCONOCIDA, f"cita afirmaciones que no existen o no se validaron: {', '.join(desconocidas)}", ", ".join(desconocidas)))
    citadas = _citadas(o, ctx)
    vista = o.texto[: ctx.cfg.texto.vista_previa_caracteres]
    transicion = False
    if not o.afirmaciones:
        if seccion in ctx.val.transiciones.secciones:
            problemas = _es_transicion(o.texto, ctx)
            if problemas:
                out.append(Rechazo(TRANSICION_NO_PERMITIDA, f"una oración sin cita solo es una transición sin cifras, fechas ni entidades ({'; '.join(problemas)}): «{vista}»", o.texto))
            else:
                transicion = True
        else:
            out.append(Rechazo(SIN_AFIRMACION, f"oración sin afirmaciones: «{vista}»", o.texto))
    s = _soporte(citadas, ctx.afirmaciones)
    out += _reglas_de_texto(o.texto, s, ctx, seccion, numerico=bool(citadas))
    if citadas:
        out += _nombres_nuevos(o.texto, s, ctx)
        out += _anio_y_volatiles(o.texto, citadas, ctx, todos_los_anios=False)
        decl = [a for a in citadas if a.tipo == "declaración"]
        solo_hashtags = not HASHTAG.sub(" ", o.texto).strip(" .,;:!?¡¿")
        if decl and not solo_hashtags and not ctx.atribuido(o.texto, [c.id for a in decl for c in a.citas]):
            if seccion in SECCIONES_TITULAR:
                out.append(Rechazo(TITULAR_SIN_ATRIBUCION, f"un título o titular basado en una declaración lleva atribución o verbo de reporte: «{o.texto}»", o.texto))
            else:
                out.append(Rechazo(SIN_ATRIBUCION, f"una oración basada en una declaración lleva atribución (medio o verbo de reporte): «{vista}»", o.texto))
        if any(a.tipo == "hipótesis" for a in citadas) and not ctx.condicional(o.texto):
            out.append(Rechazo(HIPOTESIS_SIN_CONDICIONAL, f"una oración basada en una hipótesis se redacta en condicional: «{vista}»", o.texto))
    return _sin_fugas(out), transicion


def _oraciones(
    seccion: str, valor: Sequence[Any], ctx: Contexto, *, minimo: int = 1, maximo: int | None = None, permite_marcador: bool = False
) -> list[Rechazo]:
    out: list[Rechazo] = []
    if len(valor) < minimo or (maximo is not None and len(valor) > maximo):
        rango = f"{minimo}" if maximo == minimo else f"{minimo} a {maximo}" if maximo else f"al menos {minimo}"
        out.append(Rechazo(CANTIDAD, f"se esperaban {rango} oraciones y hay {len(valor)}"))
    transiciones = 0
    for o in valor:
        r, es_transicion = _revisar_oracion(o, ctx, seccion, permite_marcador=permite_marcador)
        out += r
        transiciones += es_transicion
    tope = ctx.salidas.editorial.transiciones_sin_cita_max_por_seccion
    if transiciones > tope:
        out.append(Rechazo(EXCESO_TRANSICIONES, f"{seccion} tiene {transiciones} oraciones de transición sin cita y el máximo es {tope}"))
    return out


def _limite(seccion: str, valor: Sequence[Any], ctx: Contexto, maximo: int) -> list[Rechazo]:
    n = sum(contar_palabras(o.texto, ctx) for o in valor)
    if n <= maximo:
        return []
    objetivo = int(maximo * ctx.cfg.objetivo_fraccion_limite)
    return [Rechazo(LIMITE_PALABRAS, f"{seccion} tiene {n} palabras y {MARCA_EXCESO} ({maximo}): recórtala a unas {objetivo} palabras (quita {n - objetivo})")]


def _contradicciones_cubiertas(valor: Sequence[Any], ctx: Contexto) -> list[Rechazo]:
    """Con una contradicción abierta, el texto debe apoyarse en ambas versiones (cada una citada por alguna afirmación)."""
    citados = {c.id for o in valor for a in _citadas(o, ctx) for c in a.citas}
    return [
        Rechazo(CONTRADICCION_UNA_VERSION, f"hay una contradicción abierta entre {c.id_a} y {c.id_b}: presenta ambas versiones", f"{c.id_a} / {c.id_b}")
        for c in ctx.ficha.contradicciones
        if c.abierta and not {c.id_a, c.id_b} <= citados
    ]


def _tipos_citados(o: Any, ctx: Contexto) -> set[str]:
    return {a.tipo for a in _citadas(o, ctx)}


def _observacion_con_hipotesis(valor: Sequence[Any], ctx: Contexto) -> list[Rechazo]:
    """E2-02: una observación del boletín solo se apoya en hechos y declaraciones (``bloques_boletin.observaciones``)."""
    permitidos = set(ctx.val.bloques_boletin.observaciones)
    return [
        Rechazo(OBSERVACION_CON_HIPOTESIS, f"una observación solo cita {', '.join(sorted(permitidos))}; esta se apoya en {', '.join(sorted(otros))}", o.texto)
        for o in valor
        if (otros := _tipos_citados(o, ctx) - permitidos)
    ]


def _observacion_condicional(valor: Sequence[Any], ctx: Contexto) -> list[Rechazo]:
    """X49: una observación es un hecho o una declaración atribuida, nunca hipotética. Un marcador condicional solo se admite si él y
    ``ventana_literal_condicional`` palabras a cada lado son literales del titular citado (el medio lo dijo así)."""
    ventana = ctx.val.bloques_boletin.ventana_literal_condicional
    out: list[Rechazo] = []
    for o in valor:
        p = plano(o.texto)
        citado = plano(ctx.texto_citado(_soporte(_citadas(o, ctx), ctx.afirmaciones).citas))
        for c in ctx.val.condicionales:
            if contiene(p, c) and not fragmento_literal(p, c, citado, ventana):
                out.append(Rechazo(OBSERVACION_CONDICIONAL, f"una observación no se redacta en condicional: «{c}» (va en las hipótesis de impacto)", c))
    return out


def _impacto_como_hecho(valor: Sequence[Any], ctx: Contexto) -> list[Rechazo]:
    """E2-02: una hipótesis de impacto solo se apoya en inferencias e hipótesis (``bloques_boletin.hipotesis_impacto``), nunca en un hecho."""
    permitidos = set(ctx.val.bloques_boletin.hipotesis_impacto)
    return [
        Rechazo(IMPACTO_COMO_HECHO, f"una hipótesis de impacto solo cita {', '.join(sorted(permitidos))}; esta se apoya en {', '.join(sorted(otros))}", o.texto)
        for o in valor
        if (otros := _tipos_citados(o, ctx) - permitidos)
    ]


def _impacto_sin_condicional(valor: Sequence[Any], ctx: Contexto) -> list[Rechazo]:
    """E2-02: toda hipótesis de impacto se redacta en condicional (marcadores de ``condicionales``), también si cita una inferencia."""
    vista = ctx.cfg.texto.vista_previa_caracteres
    return [
        Rechazo(IMPACTO_SIN_CONDICIONAL, f"una hipótesis de impacto se redacta en condicional («podría», «a verificar»…): «{o.texto[:vista]}»", o.texto)
        for o in valor
        if not ctx.condicional(o.texto)
    ]


def validar_conjunto(secciones: Mapping[str, Sequence[Any]], ctx: Contexto) -> list[Rechazo]:
    """Reglas que cruzan secciones (E2-02): observaciones e hipótesis de impacto forman el resumen del boletín y su límite de palabras
    (``salidas.yaml`` · ``banca.resumen_max_palabras``) es la suma de ambos. Cada rechazo lleva la sección a la que toca. Con un solo
    bloque presente no hay nada que cruzar: su límite ya lo revisa ``validar_seccion``."""
    presentes = [s for s in BLOQUES_RESUMEN if secciones.get(s)]
    if len(presentes) < len(BLOQUES_RESUMEN):
        return []
    maximo = ctx.salidas.banca.resumen_max_palabras
    n = sum(contar_palabras(o.texto, ctx) for s in presentes for o in secciones[s])
    if n <= maximo:
        return []
    objetivo = int(maximo * ctx.cfg.objetivo_fraccion_limite)
    motivo = f"el resumen (observaciones e hipótesis de impacto) tiene {n} palabras y {MARCA_EXCESO} ({maximo}): recórtalo a unas {objetivo} palabras en total"
    return [Rechazo(LIMITE_PALABRAS, motivo, seccion=s) for s in presentes]


def _uno_o_lista(valor: Any) -> list[Any]:
    return [valor] if hasattr(valor, "texto") else list(valor)


def validar_seccion(seccion: str, valor: Any, ctx: Contexto) -> list[Rechazo]:
    """Rechazos de una sección redactada por el LLM (lista vacía = válida)."""
    e = ctx.salidas.editorial
    marcador = ctx.restricciones.marcador_visual
    if seccion in ("titulo", "titulo_trabajo"):
        oraciones = [valor]
        return _oraciones(seccion, oraciones, ctx, maximo=1) + _limite(seccion, oraciones, ctx, e.titulo_max_palabras)
    if seccion == "titulares":
        out = _oraciones(seccion, valor, ctx, minimo=e.titulares_min, maximo=e.titulares_max)
        for o in valor:
            out += _limite(seccion, [o], ctx, e.titular_max_palabras)
        return out
    if seccion == "enfoque":
        out = _oraciones(seccion, valor, ctx, minimo=e.enfoque_oraciones_min, maximo=e.enfoque_oraciones_max)
        for o in valor:
            if not any(a.tipo in ("inferencia", "hipótesis") for a in _citadas(o, ctx)):
                out.append(Rechazo(ENFOQUE_COMO_HECHO, "el enfoque se apoya en una inferencia o hipótesis, nunca se presenta como hecho", o.texto))
        return out
    if seccion == "brief":
        return _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, e.brief_max_palabras) + _contradicciones_cubiertas(valor, ctx)
    if seccion == "resumen_web":
        return _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, e.resumen_web_max_palabras) + _contradicciones_cubiertas(valor, ctx)
    if seccion == "copy_digital":
        out = _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, e.copy_max_palabras)
        texto = " ".join(o.texto for o in valor)
        if len(HASHTAG.findall(texto)) > e.copy_max_hashtags:
            out.append(Rechazo(COPY_HASHTAGS, f"el copy tiene más de {e.copy_max_hashtags} hashtags"))
        if any(unicodedata.category(c) == "So" for c in texto):
            out.append(Rechazo(COPY_EMOJIS, "el copy no lleva emojis"))
        return out
    if seccion == "guion":
        out = _oraciones(seccion, valor, ctx, permite_marcador=True) + _contradicciones_cubiertas(valor, ctx)
        n = sum(contar_palabras(o.texto.replace(marcador, " "), ctx) for o in valor)
        if not e.guion_palabras_min <= n <= e.guion_palabras_max:
            out.append(Rechazo(LIMITE_PALABRAS, f"el guion tiene {n} palabras y debe tener entre {e.guion_palabras_min} y {e.guion_palabras_max}"))
        partes = [o.parte for o in valor]
        orden = ("entrada", "desarrollo", "cierre")
        if set(partes) != set(orden) or partes != sorted(partes, key=orden.index):
            out.append(Rechazo(GUION_ESTRUCTURA, "el guion tiene entrada, desarrollo y cierre, en ese orden"))
        return out
    if seccion in BLOQUES_RESUMEN:
        out = _oraciones(seccion, valor, ctx) + _limite(seccion, valor, ctx, ctx.salidas.banca.resumen_max_palabras)
        if seccion == BLOQUES_RESUMEN[0]:
            return out + _observacion_con_hipotesis(valor, ctx) + _observacion_condicional(valor, ctx) + _contradicciones_cubiertas(valor, ctx)
        return out + _impacto_como_hecho(valor, ctx) + _impacto_sin_condicional(valor, ctx)
    if seccion == "preguntas":
        out = []
        if len(valor) != ctx.n_preguntas:
            out.append(Rechazo(CANTIDAD, f"se esperaban exactamente {ctx.n_preguntas} preguntas y hay {len(valor)}"))
        for q in valor:
            if q.vacio not in ctx.vacios:
                out.append(Rechazo(PREGUNTA_SIN_VACIO, f"la pregunta referencia un vacío que no existe en la ficha: {q.vacio}", q.vacio))
            out += _reglas_de_texto(q.texto, Soporte(), ctx, seccion, numerico=False)
        return out
    raise ValueError(f"sección desconocida: {seccion}")


# ============================================================================================ leyenda y paquete


def leyenda_esperada(ctx: Contexto) -> str:
    """La leyenda de alcance que corresponde (D-51): la de titular y metadatos, o la que dice que se usó la descripción del RSS."""
    ley = ctx.restricciones.leyendas_alcance
    return ley.con_descripcion if ctx.ficha.uso_descripcion else ley.titular_metadatos


def validar_leyenda_texto(texto: str, uso_descripcion: bool, restricciones: ConfigRestricciones | None = None) -> list[Rechazo]:
    """Toda salida (ficha, sección, consulta, boletín, exportación) lleva la leyenda correcta; la otra la delataría como falsa."""
    ley = (restricciones or cargar_restricciones()).leyendas_alcance
    esperada = ley.con_descripcion if uso_descripcion else ley.titular_metadatos
    otra = ley.titular_metadatos if uso_descripcion else ley.con_descripcion
    p = plano(texto)
    out: list[Rechazo] = []
    if plano(esperada) not in p:
        out.append(Rechazo(LEYENDA, f"falta la leyenda de alcance: «{esperada}»", esperada))
    if plano(otra) in p:
        out.append(Rechazo(LEYENDA, f"la leyenda no corresponde a lo que se usó (descripción del RSS: {'sí' if uso_descripcion else 'no'}): «{otra}»", otra))
    return out


def validar_leyenda(texto: str, ctx: Contexto) -> list[Rechazo]:
    return validar_leyenda_texto(texto, bool(ctx.ficha.uso_descripcion), ctx.restricciones)


_SECCIONES_PAQUETE = ("titulo", "titulo_trabajo", "titulares", "enfoque", "brief", "guion", "resumen_web", "copy_digital", *BLOQUES_RESUMEN, "preguntas")


def validar_paquete(paquete: Any, ctx: Contexto) -> list[Rechazo]:
    """Un paquete ya armado: marca de borrador, leyenda y cada sección contra las afirmaciones del propio paquete."""
    out: list[Rechazo] = []
    if paquete.marca != ctx.restricciones.marca_borrador:
        out.append(Rechazo(MARCA, f"el paquete lleva la marca «{ctx.restricciones.marca_borrador}»", paquete.marca))
    out += validar_leyenda(paquete.leyenda_alcance, ctx)
    if "aviso" in type(paquete).model_fields and paquete.aviso != ctx.restricciones.aviso_banca:  # E2-02: el boletín y su aviso fijo
        out.append(Rechazo(AVISO, f"el boletín lleva el aviso fijo «{ctx.restricciones.aviso_banca}»", paquete.aviso))
    ctx.afirmaciones = {a.id: a for a in paquete.afirmaciones}
    system, ctx.system = ctx.system, ""  # la fuga del system prompt ya se revisó al generar cada sección, con el prompt que le tocaba
    try:
        for s in _SECCIONES_PAQUETE:
            valor = getattr(paquete, s, None)
            if valor in (None, [], ""):
                continue
            out += [replace(r, seccion=s) for r in validar_seccion(s, valor, ctx)]
        out += validar_conjunto({s: getattr(paquete, s, None) or [] for s in BLOQUES_RESUMEN}, ctx)
    finally:
        ctx.system = system
    return out


# ============================================================================================ registro de rechazos


def ruta_registro(cfg: ConfigValidador | None = None) -> Path:
    if env := os.environ.get(ENV_REGISTRO):
        return Path(env)
    return RAIZ / (cfg or cargar_validador()).registro


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class RegistroRechazos:
    """Agrega a ``outputs/rechazos.jsonl``: una línea ``rechazo`` por cada rechazo y una ``evaluacion`` por unidad evaluada.

    Con las dos se calcula la tasa de rechazo por regla y por modelo (``calcular_tasas``). Un fallo al escribir se avisa y no
    interrumpe la generación.
    """

    def __init__(self, ruta: Path | None = None, *, proveedor: str = "", modelo: str = "", id_caso: str = "") -> None:
        self.ruta = ruta or ruta_registro()
        self.proveedor, self.modelo, self.id_caso = proveedor, modelo, id_caso

    def _escribir(self, lineas: list[dict[str, Any]]) -> None:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            with self.ruta.open("a", encoding="utf-8") as f:
                f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in lineas)
        except OSError as exc:  # el registro no debe tumbar la generación
            logger.warning("no se pudo escribir %s: %s", self.ruta, exc)

    def evaluacion(self, unidad: str, seccion: str, item: str, rechazos: Sequence[Rechazo], intento: int = 0) -> None:
        """Registra una unidad evaluada (``afirmacion`` o ``seccion``) y sus rechazos."""
        base = {
            "ts": _ahora(), "proveedor": self.proveedor, "modelo": self.modelo, "id_caso": self.id_caso,
            "unidad": unidad, "seccion": seccion, "item": item, "intento": intento,
        }
        lineas = [{**base, "evento": "evaluacion", "resultado": "rechazada" if rechazos else "ok", "n_rechazos": len(rechazos)}]
        for r in rechazos:
            # el fragmento de un secreto o del system prompt nunca se escribe
            fragmento = "" if r.regla in (SECRETO, FUGA_PROMPT) else r.fragmento
            lineas.append({**base, "evento": "rechazo", "regla": r.regla, "motivo": r.motivo, "fragmento": fragmento})
        self._escribir(lineas)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson al 95 % de una proporción k/n (CLAUDE.md: toda proporción lleva su n y su intervalo)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _proporcion(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "tasa": (k / n) if n else None, "ic95": [round(lo, 4), round(hi, 4)]}


def _clave_unidad(x: dict[str, Any]) -> str:
    """Tipo de unidad: «afirmacion» o «seccion:<nombre>» (cada sección tiene su propio denominador)."""
    return "afirmacion" if x["unidad"] == "afirmacion" else f"seccion:{x['seccion']}"


def calcular_tasas(ruta: Path | None = None) -> dict[str, Any]:
    """Tasas de rechazo, cada una con su n y su IC de Wilson al 95 %:

    - ``por_modelo``: unidades rechazadas / evaluadas del modelo;
    - ``por_unidad``: lo mismo por tipo de unidad (``afirmacion``, ``seccion:brief``…);
    - ``por_regla``: unidades en que la regla rechazó (una vez por unidad aunque dispare varias veces) / evaluadas **de ese tipo de unidad**.
    """
    ruta = ruta or ruta_registro()
    evaluadas: Counter[str] = Counter()
    rechazadas: Counter[str] = Counter()
    eval_u: Counter[tuple[str, str]] = Counter()
    rech_u: Counter[tuple[str, str]] = Counter()
    por_regla: Counter[tuple[str, str, str]] = Counter()
    vistos: set[tuple[Any, ...]] = set()
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            x = json.loads(linea)
            modelo = f"{x.get('proveedor', '')}/{x.get('modelo', '')}"
            u = _clave_unidad(x)
            if x["evento"] == "evaluacion":
                evaluadas[modelo] += 1
                rechazadas[modelo] += x["resultado"] == "rechazada"
                eval_u[(modelo, u)] += 1
                rech_u[(modelo, u)] += x["resultado"] == "rechazada"
            elif x["evento"] == "rechazo":
                clave = (x["ts"], x["id_caso"], x["unidad"], x["seccion"], x["item"], x["intento"], x["regla"], modelo)
                if clave not in vistos:
                    vistos.add(clave)
                    por_regla[(x["regla"], modelo, u)] += 1
    reglas = sorted({r for r, _, _ in por_regla})
    return {
        "unidades_evaluadas": sum(evaluadas.values()),
        "por_modelo": {m: _proporcion(rechazadas[m], n) for m, n in sorted(evaluadas.items())},
        "por_unidad": {
            m: {u: _proporcion(rech_u[(mm, u)], n) for (mm, u), n in sorted(eval_u.items()) if mm == m} for m in sorted(evaluadas)
        },
        "por_regla": {
            r: {
                m: {u: _proporcion(c, eval_u[(m, u)]) for (rr, mm, u), c in sorted(por_regla.items()) if rr == r and mm == m}
                for m in sorted({mm for (rr, mm, _) in por_regla if rr == r})
            }
            for r in reglas
        },
    }


def principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validador de citas (E1-13)")
    parser.add_argument("--tasas", action="store_true", help="resume outputs/rechazos.jsonl: tasa de rechazo por modelo y por regla, con n e IC 95 %")
    parser.add_argument("--ruta", type=Path, help="registro a leer (por defecto, el de config/validador.yaml)")
    args = parser.parse_args(argv)
    if not args.tasas:
        parser.error("indique --tasas")
    print(json.dumps(calcular_tasas(args.ruta), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
