"""Puntaje de atención determinista (R, I, U, N, E y P) y ranking · E1-10, CU-01, T03, T08, PDF sección 4.

``P = 30R + 25I + 20U + 15N + 10E`` con las reglas v1.3 (``config/reglas_v1.3.yaml``; los parámetros que esas reglas no
fijan, en ``config/prioridad.yaml``). Es una herramienta de **ordenamiento**: no es una probabilidad de verdad ni de pérdida,
y **no habilita publicación** (``Puntaje.habilita_publicacion`` es siempre falso).

* **R** = ``peso_foco × foco × pertenencia`` (D-119; D-103 había quitado la parte temática porque usaba la confianza del
  clasificador). D-135: el foco es graduado por lo que dicen los titulares y vale el del titular que más foco tiene: 1.0 si nombra
  al país, un lugar o un actor panameño; 0.7 si solo lo publica un medio de Panamá;
  0.5 si es regional (D-84) o de un medio de otro país. Pertenencia: según la ETIQUETA, nunca la confianza (``tema_similitud``):
  1 si algún titular tiene un tema de la modalidad como ``tema_clasificado``, 0.6 si solo como ``tema_secundario``, 0.3 si ninguno.
* **I** = ``peso_tema × alcance(tema) + peso_geografico × alcance geográfico`` (D-125: el reto define 6 temas, sin subtemas; un grupo
  sin tema usa ``alcance_tema_desconocido``). Ni el dato oficial ni las
  procedencias suman aquí (D-15, D-35). El alcance geográfico es el más amplio que nombren los titulares; sin término
  explícito ni lugar concreto de Panamá, un país o ciudad del exterior lo hace ``exterior`` (D-115) y, si no hay, el país
  nombrado o su gentilicio lo hacen nacional (E1-10c, X42).
* **U**: lineal entre ``horas_pleno`` (U = 1; D-106: 0 h, sin meseta) y ``dias_nulo`` (U = 0) desde la publicación ORIGINAL más reciente del grupo,
  medida contra la fecha de referencia (el corte del snapshot). Si ningún titular trae ``fecha_publicacion`` se usa la
  detección como cota y se agrega el vacío «urgencia estimada: fecha de publicación desconocida»; nunca se sustituye en silencio.
  D-124: con esa fecha imputada U no pasa de ``urgencia.tope_fecha_imputada`` y la explicación lleva ``fecha_imputada: true``.
* **N** (D-124, reemplaza a D-103): ``s`` = similitud coseno entre el CENTROIDE del grupo y el de cada grupo que empezó
  antes (``fecha_publicacion`` y, si falta, ``fecha_deteccion``) y dentro de ``novedad.ventana_dias``; se toma la máxima.
  N = 1 si ``s <= ancla_baja``, 0 si ``s >= ancla_alta`` (= ``agrupacion.umbral_similitud``, el umbral con que se agrupa) y
  lineal entre ambas. Sin grupos previos en la ventana, ``novedad.sin_grupos_previos``. La duplicación no sube N.
* **E** = ``peso_procedencias × min(n, tope)/tope + peso_oficial × (hay dato oficial directo o evento) + peso_identificables × (titulares con
  medio y fecha de publicación conocidos / titulares)``. Cuenta **procedencias**, nunca titulares (``procedencias.fraccion_de_procedencias``).

Rango y desempate (mayor U, menor ID) salen de ``reglas.rangos`` y ``reglas.desempate``.
Cada componente guarda su explicación (de qué valores sale) para la ficha.

Uso: ``poetry run python -m src.puntaje`` (después de ``src.contexto``); ver ``src/prioridad.py``.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import numpy as np

from src.agrupacion import fecha_de, fecha_iso_de
from src.configuracion import ConfigModalidad, ConfigPrioridad, ReglasV13, cargar_temas
from src.evidencia import Vacio
from src.limpieza import plano
from src.procedencias import fraccion_de_procedencias
from src.sectores import sector_de_tema

COMPONENTES = ("R", "I", "U", "N", "E")
NIVELES_GEOGRAFICOS = ("nacional", "provincial", "local")   # de más a menos amplio; sin términos = desconocido
NIVEL_NACIONAL = NIVELES_GEOGRAFICOS[0]
NIVEL_DESCONOCIDO = "desconocido"
NIVEL_EXTERIOR = "exterior"   # D-115: países o ciudades extranjeras nombrados y ningún lugar de Panamá
SEGUNDOS_POR_HORA = 3600
HORAS_POR_DIA = 24
FORMATO_FECHA = "%Y-%m-%dT%H:%M:%SZ"
CAMPO_PUBLICACION = "fecha_publicacion"


def puntaje_total(componentes: dict[str, float], reglas: ReglasV13) -> float:
    """P = Σ peso × componente, con los componentes R, I, U, N, E en [0, 1] y los pesos de ``reglas``."""
    return sum(getattr(reglas.pesos, k) * componentes[k] for k in COMPONENTES)


def rango_de(p: float, reglas: ReglasV13) -> str:
    """Rango ``bajo``, ``medio`` o ``alto`` según ``reglas.rangos`` (el último incluye su límite superior)."""
    if p < reglas.rangos.bajo.hasta:
        return "bajo"
    return "medio" if p < reglas.rangos.medio.hasta else "alto"


# ------------------------------------------------------------------ tipos


@dataclass(frozen=True)
class EntradaGrupo:
    """Lo que el puntaje necesita de un grupo: sus titulares (filas de ``noticias``), vectores y contexto ya resuelto."""

    id_grupo: str
    miembros: tuple[Mapping[str, Any], ...]     # id_noticia, titulo_limpio, medio, fecha_publicacion, fecha_deteccion, es_recirculada, alcance_regional, tema_clasificado, tema_secundario
    vectores: np.ndarray | None                 # embeddings normalizados de los miembros (misma posición); necesarios para N
    n_procedencias: int
    tiene_oficial: bool
    motivo_sin_oficial: str | None = None
    solo_indirecto: bool = False                 # hay un vínculo con dato, pero indirecto (X22): no cuenta como dato oficial
    discrepancias: tuple[str, ...] = ()          # IDs de datos oficiales que la cifra de un titular contradice
    periodos_distintos: tuple[str, ...] = ()     # IDs de datos oficiales de otro período que la cifra de un titular
    eventos_sin_revisar: tuple[str, ...] = ()    # IDs de eventos oficiales con estado automático
    tema: str | None = None                      # ``tema_clasificado`` del grupo: lo usa el alcance por sector de la modalidad (E2-01)
    sintetico: bool = False                      # todos sus titulares son sintéticos (C-06, ``SYN-``): nunca cuentan como grupo anterior de uno real


@dataclass(frozen=True)
class Componente:
    """Valor en [0, 1] y de qué valores sale (para mostrarlo en la ficha)."""

    valor: float
    explicacion: dict[str, Any]


@dataclass(frozen=True)
class Puntaje:
    """Resultado de un grupo: componentes, P, rango, posición y vacíos que nacen del puntaje."""

    id_grupo: str
    posicion: int
    version_reglas: str
    fecha_referencia: str
    componentes: dict[str, Componente]
    puntaje: float
    rango: str
    vacios: tuple[Vacio, ...]
    recirculada: bool
    es_nueva: bool
    empate_con: int = 0      # D-105: cuántos OTROS grupos tienen el mismo P tal como se muestra (``comparacion.decimales_empate``)

    @property
    def habilita_publicacion(self) -> bool:
        """Una prioridad alta no habilita publicación (PDF sección 4): siempre falso."""
        return False

    def a_diccionario(self) -> dict[str, Any]:
        """Forma serializable (JSON) con todo lo que la ficha necesita."""
        return {
            "id_grupo": self.id_grupo,
            "posicion": self.posicion,
            "version_reglas": self.version_reglas,
            "fecha_referencia": self.fecha_referencia,
            "puntaje": self.puntaje,
            "rango": self.rango,
            "componentes": {k: {"valor": c.valor, "explicacion": c.explicacion} for k, c in self.componentes.items()},
            "vacios": [{"codigo": v.codigo, "texto": v.texto} for v in self.vacios],
            "recirculada": self.recirculada,
            "es_nueva": self.es_nueva,
            "empate_con": self.empate_con,
            "habilita_publicacion": self.habilita_publicacion,
        }


@dataclass(frozen=True)
class Alcance:
    """Alcance geográfico de un grupo: el más amplio que nombran sus titulares y los términos que lo dicen."""

    nivel: str
    valor: float
    terminos: tuple[str, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------ R · relevancia


NIVEL_PANAMA_SUJETO = "panama_sujeto"
NIVEL_PANAMA_IMPLICITO = "panama_implicito"
NIVEL_OTRO_PAIS = "otro_pais_afecta"


def nivel_de_foco(m: Mapping[str, Any], reglas: ReglasV13, cfg: ConfigPrioridad) -> tuple[str, list[str]]:
    """D-135: nivel de foco de UN titular y los nombres panameños que lo explican: ``(nivel, nombres)``.

    ``panama_sujeto``: el titular nombra al país (o un nombre propio con su nombre), un lugar concreto de Panamá o un actor de
    ``relevancia.panama_actores``. Como en el alcance de I (C-10, D6), Panamá como parte del hecho manda aunque el titular nombre
    también un lugar o país del exterior («Panamá reforzará su presencia en Vietnam»). ``panama_implicito``: lo publica un medio de
    Panamá, no es regional y no cumple lo anterior.
    ``otro_pais_afecta``: es regional (D-84) o lo publica un medio de otro país. Solo lee el texto, el medio y la marca regional:
    nunca la confianza del clasificador (D-103). Un lugar de ``panama_nombres_extranjeros`` («Panama City, Florida») no nombra al país.
    """
    g = reglas.geografia
    titular = str(m.get("titulo_limpio") or "")
    _, sin_extranjeros = exterior_en(titular, g.panama_nombres_extranjeros)
    nombres = [
        *terminos_sin_prefijo_excluido(sin_extranjeros, [*g.pais_terminos, *g.panama_nombres_propios], cfg.geografia.prefijos_excluidos),
        *terminos_presentes(
            sin_extranjeros,
            [*g.provincias, *g.comarcas, *g.distritos],
            cfg.geografia.prefijos_obligatorios,
            cfg.geografia.sufijos_excluidos,
            cfg.geografia.requieren_tilde,
            cfg.geografia.prefijos_excluidos_lugar,
        ),
        *terminos_sin_prefijo_excluido(sin_extranjeros, reglas.relevancia.panama_actores, {}),
    ]
    nombres = list(dict.fromkeys(nombres))
    if nombres:
        return NIVEL_PANAMA_SUJETO, nombres
    pais_medio = normalizar_geografia(str(m.get("pais_medio") or ""))
    de_otro_pais = bool(pais_medio) and pais_medio not in {normalizar_geografia(t) for t in g.pais_terminos}
    if m.get("alcance_regional") or de_otro_pais:
        return NIVEL_OTRO_PAIS, nombres
    return NIVEL_PANAMA_IMPLICITO, nombres


def foco_de(miembros: Sequence[Mapping[str, Any]], reglas: ReglasV13, cfg: ConfigPrioridad) -> tuple[float, dict[str, Any]]:
    """Foco del grupo (D-135) y su explicación: el del titular con más foco (el máximo; basta uno que trate a Panamá como sujeto).

    Los niveles y sus valores están en ``relevancia`` (``panama_sujeto`` ≥ ``panama_implicito`` ≥ ``otro_pais_afecta``). La explicación
    dice qué nivel es, qué titular y qué nombres lo causan, y cuántos titulares hay en cada nivel.
    """
    rel = reglas.relevancia
    valores = {NIVEL_PANAMA_SUJETO: rel.foco_panama_sujeto, NIVEL_PANAMA_IMPLICITO: rel.foco_panama_implicito, NIVEL_OTRO_PAIS: rel.foco_otro_pais_afecta}
    evaluados = [(m, *nivel_de_foco(m, reglas, cfg)) for m in miembros]
    por_nivel = {nivel: sum(1 for t in evaluados if t[1] == nivel) for nivel in valores}
    regionales = sum(1 for m in miembros if m.get("alcance_regional"))
    causa: Mapping[str, Any] | None = None
    nivel, nombres = NIVEL_OTRO_PAIS, []   # grupo sin titulares: no hay evidencia de que trate de Panamá
    if evaluados:
        causa, nivel, nombres = max(evaluados, key=lambda t: valores[t[1]])   # empate: el primero (los miembros vienen ordenados por ID)
    textos = cfg.relevancia
    titular = str(causa.get("titulo_limpio") or "") if causa else ""
    texto = getattr(textos, nivel).format(terminos=", ".join(nombres), titular=titular)
    detalle = {
        "foco": valores[nivel], "foco_motivo": nivel, "foco_texto": texto, "foco_terminos": nombres,
        "foco_titular": None if causa is None else str(causa.get("id_noticia")),
        "titulares_por_nivel": por_nivel, "titulares_regionales": regionales, "titulares": len(miembros),
    }
    return valores[nivel], detalle


def pertenencia_de(
    miembros: Sequence[Mapping[str, Any]], temas: Collection[str], reglas: ReglasV13, tema_grupo: str | None = None
) -> tuple[float, dict[str, Any]]:
    """Pertenencia temática del grupo (D-119) y su explicación. Lee solo las etiquetas, jamás la confianza del clasificador.

    ``temas`` son los temas de la modalidad. Una etiqueta nula o fuera de ellos (``no_es_panama``, ``fuera_de_temas``…) no cuenta.
    """
    valores = reglas.relevancia.pertenencia_tematica
    principales = sorted({str(m["tema_clasificado"]) for m in miembros if m.get("tema_clasificado") in temas})
    secundarios = sorted({str(m["tema_secundario"]) for m in miembros if m.get("tema_secundario") in temas} - set(principales))
    if principales:
        valor, motivo, coinciden = valores.tema_principal, "tema_principal", principales
    elif secundarios:
        valor, motivo, coinciden = valores.solo_secundario, "solo_secundario", secundarios
    else:
        valor, motivo, coinciden = valores.sin_tema, "sin_tema", []
    return valor, {"pertenencia": valor, "pertenencia_motivo": motivo, "temas_coincidentes": coinciden}


# ------------------------------------------------------------------ I · impacto


NO_ALFANUMERICO = re.compile(r"[\W_]+")


def normalizar_geografia(texto: str) -> str:
    """Sin tildes ni mayúsculas, y con guiones, rayas y espacios repetidos reducidos a un espacio («Ngäbe-Buglé» = «ngabe bugle»)."""
    return NO_ALFANUMERICO.sub(" ", plano(texto)).strip()


@lru_cache(maxsize=None)
def _patron_termino(termino: str, prefijos: tuple[str, ...], sufijos: tuple[str, ...] = ()) -> re.Pattern[str]:
    """Palabra completa, sin tildes ni mayúsculas; con ``prefijos`` solo cuenta si la precede alguno; con ``sufijos``, si no lo sigue ninguno."""
    cuerpo = re.escape(normalizar_geografia(termino))
    if prefijos:
        cuerpo = r"(?:" + "|".join(re.escape(normalizar_geografia(p)) for p in prefijos) + r")\s+" + cuerpo
    if sufijos:
        cuerpo += r"(?!\s+(?:" + "|".join(re.escape(normalizar_geografia(s)) for s in sufijos) + r")(?!\w))"
    return re.compile(rf"(?<!\w){cuerpo}(?!\w)")


@lru_cache(maxsize=None)
def _patron_con_tilde(termino: str) -> re.Pattern[str]:
    """El término tal como se escribe (con sus tildes), palabra completa y sin distinguir mayúsculas."""
    return re.compile(rf"(?<!\w){re.escape(termino.casefold())}(?!\w)")


def _con_tilde_sin_prefijo_excluido(texto: str, termino: str, excluidos: Sequence[str]) -> bool:
    """X66: el término escrito con su tilde aparece al menos una vez **sin** uno de sus prefijos excluidos delante («Cristóbal Colón»)."""
    bajo = texto.casefold()
    previos = [normalizar_geografia(p) for p in excluidos]
    for m in _patron_con_tilde(termino).finditer(bajo):
        antes = normalizar_geografia(bajo[: m.start()])
        if not any(antes == p or antes.endswith(" " + p) for p in previos):
            return True
    return False


def terminos_presentes(
    texto: str,
    terminos: Sequence[str],
    prefijos: Mapping[str, Sequence[str]],
    sufijos_excluidos: Mapping[str, Sequence[str]] | None = None,
    requieren_tilde: Sequence[str] = (),
    prefijos_excluidos_lugar: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Términos de ``terminos`` que aparecen en ``texto`` (en el orden dado).

    X51: un término con ``sufijos_excluidos`` no cuenta sin tilde si lo sigue una de esas palabras («pese a»); escrito con su
    tilde («Pesé») siempre cuenta.

    X66: un término de ``requieren_tilde`` solo cuenta escrito con su tilde («Colón»; «colon» es el órgano) y, si tiene
    ``prefijos_excluidos_lugar``, no cuenta precedido de ellos («Cristóbal Colón»).
    """
    plano_texto = normalizar_geografia(texto)
    sufijos = sufijos_excluidos or {}
    excluidos_lugar = prefijos_excluidos_lugar or {}
    presentes = []
    for t in terminos:
        if t in requieren_tilde:
            if _con_tilde_sin_prefijo_excluido(texto, t, excluidos_lugar.get(t, ())):
                presentes.append(t)
            continue
        excluir = tuple(sufijos.get(t, ()))
        if _patron_termino(t, tuple(prefijos.get(t, ())), excluir).search(plano_texto) or (
            excluir and _patron_con_tilde(t).search(texto.casefold())
        ):
            presentes.append(t)
    return presentes


def terminos_sin_prefijo_excluido(texto: str, terminos: Sequence[str], excluidos: Mapping[str, Sequence[str]]) -> list[str]:
    """Términos de ``terminos`` que aparecen en ``texto`` al menos una vez **sin** uno de sus prefijos excluidos delante."""
    plano_texto = normalizar_geografia(texto)
    presentes = []
    for t in terminos:
        prefijos = [normalizar_geografia(p) for p in excluidos.get(t, ())]
        for m in _patron_termino(t, ()).finditer(plano_texto):
            antes = plano_texto[: m.start()].rstrip()
            if not any(antes == p or antes.endswith(" " + p) for p in prefijos):
                presentes.append(t)
                break
    return presentes


@lru_cache(maxsize=None)
def _patron_exterior(terminos: tuple[str, ...]) -> re.Pattern[str]:
    """Alternancia de los términos del exterior (palabra completa, separadores flexibles); el más largo primero para que mande sobre el que contiene."""
    cuerpos = [
        r"[\W_]+".join(re.escape(palabra) for palabra in normalizar_geografia(t).split())
        for t in sorted(terminos, key=lambda t: -len(normalizar_geografia(t)))
    ]
    return re.compile(r"(?<!\w)(?:" + "|".join(cuerpos) + r")(?!\w)")


def exterior_en(titular: str, terminos: Sequence[str]) -> tuple[list[str], str]:
    """D-115: términos del exterior que nombra ``titular`` y el titular con esos tramos en blanco.

    El tramo en blanco evita que un nombre extranjero más largo cuente también como el lugar panameño que contiene
    («Santiago de Chile» no es el distrito de Santiago). El resto del texto no cambia, tildes incluidas.
    """
    piezas = [plano(c) for c in titular]
    llano = "".join(piezas)
    origen = [i for i, p in enumerate(piezas) for _ in p]   # posición del carácter original de cada carácter de ``llano``
    halladas: list[str] = []
    borrar: set[int] = set()
    for m in _patron_exterior(tuple(terminos)).finditer(llano):
        halladas.append(normalizar_geografia(m.group()))
        borrar.update(origen[k] for k in range(m.start(), m.end()))
    return halladas, "".join(" " if i in borrar else c for i, c in enumerate(titular))


def nombra_al_pais(titular: str, reglas: ReglasV13, cfg: ConfigPrioridad) -> bool:
    """C-10 (D3, D6): el titular nombra a Panamá, el país, por su nombre o por un nombre propio de ``panama_nombres_propios``.

    No cuenta el gentilicio («panameños»), un prefijo excluido («Ciudad de Panamá» es el lugar, no el país) ni un lugar extranjero
    de ``panama_nombres_extranjeros`` («Panama City, Florida»).
    """
    g = reglas.geografia
    _, titular = exterior_en(titular, g.panama_nombres_extranjeros)
    return bool(terminos_sin_prefijo_excluido(titular, [*g.pais_terminos, *g.panama_nombres_propios], cfg.geografia.prefijos_excluidos))


def alcance_geografico(miembros: Sequence[Mapping[str, Any]], reglas: ReglasV13, cfg: ConfigPrioridad) -> Alcance:
    """Alcance más amplio que nombran los titulares: nacional, provincial (provincias y comarcas) o local (distritos).

    Si ningún titular nombra un término explícito ni un lugar concreto de Panamá, un país o ciudad del exterior da alcance
    ``exterior`` (D-115); si tampoco, el país nombrado o su gentilicio dan alcance nacional (E1-10c, X42); si tampoco, el alcance
    es desconocido. Precedencia: frase nacional > provincia o comarca > distrito > exterior > país nombrado > desconocido.

    C-10 (D6): un titular que nombra a Panamá como parte del hecho no aporta su lugar o contraparte extranjera al exterior;
    el grupo recibe el nivel que tendría sin ella (el país nombrado da ``nacional``).
    """
    g = reglas.geografia
    listas = {"nacional": g.nacional_terminos, "provincial": [*g.provincias, *g.comarcas], "local": g.distritos}
    prefijos = cfg.geografia.prefijos_obligatorios
    hallados: dict[str, list[str]] = {nivel: [] for nivel in NIVELES_GEOGRAFICOS}
    implicitos: list[str] = []
    exteriores: list[str] = []
    for m in miembros:
        crudo = str(m.get("titulo_limpio") or "")
        del_exterior, titular = exterior_en(crudo, [*g.exterior_terminos, *g.panama_nombres_extranjeros])   # «Panama City, Florida» es exterior
        if not nombra_al_pais(titular, reglas, cfg):   # C-10 (D6): Panamá como parte del hecho manda sobre el lugar o la contraparte extranjera
            exteriores.extend(del_exterior)
        for nivel in NIVELES_GEOGRAFICOS:
            hallados[nivel].extend(terminos_presentes(
                    titular,
                    listas[nivel],
                    prefijos,
                    cfg.geografia.sufijos_excluidos,
                    cfg.geografia.requieren_tilde,
                    cfg.geografia.prefijos_excluidos_lugar,
                )
            )
        implicitos.extend(terminos_sin_prefijo_excluido(titular, g.nacional_implicito_terminos, cfg.geografia.prefijos_excluidos))
    for nivel in NIVELES_GEOGRAFICOS:
        if hallados[nivel]:
            return Alcance(nivel, getattr(reglas.impacto.alcance_geografico, nivel), tuple(sorted(set(hallados[nivel]))))
    if exteriores:
        return Alcance(NIVEL_EXTERIOR, reglas.impacto.alcance_geografico.exterior, tuple(sorted(set(exteriores))))
    if implicitos:
        return Alcance(NIVEL_NACIONAL, reglas.impacto.alcance_geografico.nacional, tuple(sorted(set(implicitos))))
    return Alcance(NIVEL_DESCONOCIDO, reglas.impacto.alcance_geografico.desconocido)


def impacto(
    entrada: EntradaGrupo, reglas: ReglasV13, cfg: ConfigPrioridad, modalidad: ConfigModalidad | None = None
) -> tuple[Componente, list[Vacio]]:
    """I del grupo. Ni el dato oficial ni las procedencias entran (D-15, D-35).

    Si la modalidad declara ``alcance_por_sector`` (banca, E2-01), el alcance sale del sector del tema y sustituye al del tema.
    """
    vacios: list[Vacio] = []
    explicacion_alcance: dict[str, Any]
    if modalidad is not None and modalidad.alcance_por_sector:
        sector = sector_de_tema(entrada.tema, modalidad)
        if sector is None:
            alcance_tema = cfg.impacto.alcance_tema_desconocido
            vacios.append(Vacio("sector_desconocido", cfg.vacios.sector_desconocido))
        else:
            alcance_tema = modalidad.alcance_por_sector[sector]
        explicacion_alcance = {"sector": sector, "alcance_sector": alcance_tema}
    elif entrada.tema not in reglas.impacto.alcance_tema:
        alcance_tema = cfg.impacto.alcance_tema_desconocido
        vacios.append(Vacio("tema_desconocido", cfg.vacios.tema_desconocido))
        explicacion_alcance = {"tema": entrada.tema, "alcance_tema": alcance_tema}
    else:
        alcance_tema = reglas.impacto.alcance_tema[entrada.tema]
        explicacion_alcance = {"tema": entrada.tema, "alcance_tema": alcance_tema}
    geo = alcance_geografico(entrada.miembros, reglas, cfg)
    valor = reglas.impacto.peso_tema * alcance_tema + reglas.impacto.peso_geografico * geo.valor
    return Componente(
        valor,
        {
            **explicacion_alcance,
            "nivel_geografico": geo.nivel,
            "alcance_geografico": geo.valor,
            "terminos_geograficos": list(geo.terminos),
            "peso_tema": reglas.impacto.peso_tema,
            "peso_geografico": reglas.impacto.peso_geografico,
        },
    ), vacios


# ------------------------------------------------------------------ U · urgencia


def _fecha_mas_reciente(miembros: Sequence[Mapping[str, Any]], campo: str) -> tuple[datetime, str] | None:
    """La fecha más reciente de ``campo`` entre los titulares y su texto ISO original."""
    fechas = [(fecha_de(m, [campo]), fecha_iso_de(m, [campo])) for m in miembros]
    fechas = [(f, t) for f, t in fechas if f is not None and t is not None]
    return max(fechas, key=lambda ft: ft[0]) if fechas else None


def urgencia(
    miembros: Sequence[Mapping[str, Any]], ahora: datetime, reglas: ReglasV13
) -> tuple[Componente, list[Vacio]]:
    """U según la publicación original más reciente; sin publicación, la detección más reciente y el vacío correspondiente."""
    u = reglas.urgencia
    vacios: list[Vacio] = []
    elegida = _fecha_mas_reciente(miembros, CAMPO_PUBLICACION)
    origen = "publicacion"
    if elegida is None:
        elegida = _fecha_mas_reciente(miembros, u.fecha_sin_publicacion)
        origen = u.fecha_sin_publicacion.removeprefix("fecha_")
        if elegida is None:
            raise ValueError("grupo sin ninguna fecha (publicación ni detección): el contrato de datos las exige")
        vacios.append(Vacio("urgencia_sin_publicacion", u.vacio_sin_publicacion))
    fecha, texto = elegida
    edad_horas = (ahora - fecha).total_seconds() / SEGUNDOS_POR_HORA
    limite = u.dias_nulo * HORAS_POR_DIA
    valor = 1.0 if edad_horas <= u.horas_pleno else 0.0 if edad_horas >= limite else (limite - edad_horas) / (limite - u.horas_pleno)
    imputada = origen != "publicacion"
    sin_tope = valor
    if imputada:    # D-124: la detección no es la publicación; U no pasa del tope
        valor = min(valor, u.tope_fecha_imputada)
    return Componente(
        valor,
        {
            "fecha": texto, "fecha_origen": origen, "edad_horas": edad_horas, "horas_pleno": u.horas_pleno, "dias_nulo": u.dias_nulo,
            "fecha_imputada": imputada, "tope_fecha_imputada": u.tope_fecha_imputada if imputada else None, "valor_sin_tope": sin_tope,
        },
    ), vacios


# ------------------------------------------------------------------ N · novedad


def _fecha_de_inicio(entrada: EntradaGrupo, reglas: ReglasV13) -> datetime | None:
    fechas = [f for f in (fecha_de(m, reglas.agrupacion.campos_fecha) for m in entrada.miembros) if f is not None]
    return min(fechas) if fechas else None


def _centroide(entrada: EntradaGrupo) -> np.ndarray:
    """Centroide normalizado de los vectores del grupo (la media de vectores unitarios no es unitaria: se normaliza)."""
    if entrada.vectores is None:
        raise ValueError("novedad: faltan los vectores de un grupo")
    media = entrada.vectores.mean(axis=0)
    norma = float(np.linalg.norm(media))
    return media / norma if norma else media


def _similitudes_maximas(
    entradas: Sequence[EntradaGrupo], reglas: ReglasV13
) -> list[tuple[float, str, int] | None]:
    """Por grupo: (similitud máxima entre centroides con un grupo que empezó ANTES y dentro de ``novedad.ventana_dias``, ese
    grupo, cuántos grupos había en la ventana); ``None`` si no hay ninguno (o el grupo no tiene fecha).

    Un grupo sintético (C-06) nunca es «anterior» de uno real: los casos de la demo no alteran el puntaje de los casos reales."""
    inicio = [_fecha_de_inicio(e, reglas) for e in entradas]
    ventana = timedelta(days=reglas.novedad.ventana_dias)
    centroides = [_centroide(e) for e in entradas]
    resultado: list[tuple[float, str, int] | None] = [None] * len(entradas)
    for i, e in enumerate(entradas):
        if inicio[i] is None:
            continue
        # «antes» = (inicio, id) estrictamente menor: dos grupos con el mismo inicio no se descuentan entre sí a la vez
        anteriores = [
            j for j, otro in enumerate(entradas)
            if inicio[j] is not None and (inicio[j], otro.id_grupo) < (inicio[i], e.id_grupo) and inicio[i] - inicio[j] <= ventana
            and (e.sintetico or not otro.sintetico)
        ]
        if not anteriores:
            continue
        sims = [(float(centroides[i] @ centroides[j]), entradas[j].id_grupo) for j in anteriores]
        mejor = max(sims, key=lambda t: (t[0], t[1]))
        resultado[i] = (mejor[0], mejor[1], len(anteriores))
    return resultado


def umbral_novedad(reglas: ReglasV13) -> float:
    """``ancla_alta`` de N: ``agrupacion.umbral_similitud``, el mismo con que se agrupa (D-103, D-124)."""
    umbral = reglas.agrupacion.umbral_similitud
    if umbral is None:
        raise ValueError("agrupacion.umbral_similitud sin calibrar: N lo necesita (D-103); ejecute `python -m eval.agrupacion`")
    return umbral


def novedad_de(similitud: float, ancla_baja: float, ancla_alta: float) -> float:
    """N (D-124): 1 si ``similitud <= ancla_baja``, 0 si ``>= ancla_alta`` y lineal entre ambas (si ``ancla_alta <= ancla_baja``
    no hay tramo lineal: N salta de 1 a 0 en ``ancla_baja``)."""
    if similitud <= ancla_baja:
        return 1.0
    if similitud >= ancla_alta:
        return 0.0
    return (ancla_alta - similitud) / (ancla_alta - ancla_baja)


# ------------------------------------------------------------------ E · evidencia


def es_identificable(fila: Mapping[str, Any], cfg: ConfigPrioridad) -> bool:
    """Titular con medio y fecha de publicación conocidos."""
    medio = str(fila.get("medio") or "").strip().lower()
    return medio not in cfg.medios.desconocidos and bool(fila.get(CAMPO_PUBLICACION))


def evidencia_e(entrada: EntradaGrupo, reglas: ReglasV13, cfg: ConfigPrioridad) -> Componente:
    """E: procedencias independientes (no titulares), dato oficial y proporción de titulares identificables (D-56)."""
    e = reglas.evidencia
    n_titulares = len(entrada.miembros)
    n_identificables = sum(1 for m in entrada.miembros if es_identificable(m, cfg))
    proporcion = n_identificables / n_titulares if n_titulares else 0.0
    fraccion = fraccion_de_procedencias(entrada.n_procedencias, reglas)
    valor = e.peso_procedencias * fraccion + e.peso_oficial * (1.0 if entrada.tiene_oficial else 0.0) + e.peso_identificables * proporcion
    return Componente(
        valor,
        {
            "n_titulares": n_titulares,
            "n_procedencias": entrada.n_procedencias,
            "tope_procedencias": e.tope_procedencias,
            "fraccion_procedencias": fraccion,
            "tiene_oficial": entrada.tiene_oficial,
            "n_identificables": n_identificables,
            "proporcion_identificables": proporcion,
            "peso_procedencias": e.peso_procedencias,
            "peso_oficial": e.peso_oficial,
            "peso_identificables": e.peso_identificables,
        },
    )


# ------------------------------------------------------------------ ranking


def p_para_empate(p: float, cfg: ConfigPrioridad) -> float:
    """P tal como se muestra (``comparacion.decimales_empate``, D-105): dos grupos con el mismo valor están empatados."""
    return round(p, cfg.comparacion.decimales_empate)


def ordenar(puntajes: Sequence[Puntaje], reglas: ReglasV13, cfg: ConfigPrioridad) -> list[Puntaje]:
    """Ordena por P descendente y desempata con ``reglas.desempate`` (PDF sección 4: mayor U, luego ID); asigna ``posicion`` desde 1.

    D-105: P se compara tal como se muestra (``comparacion.decimales_empate``), así un empate visible siempre lo decide la regla
    del reto; U se compara a ``comparacion.decimales_p`` para que el ruido de coma flotante no decida. Cada puntaje lleva
    ``empate_con``: cuántos otros grupos tienen su mismo P.
    """
    d = cfg.comparacion.decimales_p

    def clave(p: Puntaje) -> tuple[Any, ...]:
        partes: list[Any] = [-p_para_empate(p.puntaje, cfg)]
        for criterio in reglas.desempate:
            partes.append(-round(p.componentes["U"].valor, d) if criterio == "u_desc" else p.id_grupo)
        return tuple(partes)

    cuantos = Counter(p_para_empate(p.puntaje, cfg) for p in puntajes)
    return [
        replace(p, posicion=i, empate_con=cuantos[p_para_empate(p.puntaje, cfg)] - 1)
        for i, p in enumerate(sorted(puntajes, key=clave), start=1)
    ]


def empate_en_el_corte(claves: Sequence[Any], k: int) -> dict[str, Any] | None:
    """Empate en el corte de un top ``k`` (D-105). ``claves`` va en el orden del ranking, ya comparable (P mostrado, fecha…).

    Devuelve el valor empatado en el puesto ``k``, cuántos grupos lo comparten y cuántos quedaron dentro y fuera del top;
    ``None`` si el corte no parte un empate (o hay ``k`` grupos o menos).
    """
    if len(claves) <= k:
        return None
    valor = claves[k - 1]
    if claves[k] != valor:
        return None
    empatados = [i for i, c in enumerate(claves) if c == valor]
    dentro = sum(1 for i in empatados if i < k)
    return {"valor": valor, "empatados": len(empatados), "dentro_del_top": dentro, "fuera_del_top": len(empatados) - dentro}


def calcular_puntajes(
    entradas: Sequence[EntradaGrupo],
    reglas: ReglasV13,
    cfg: ConfigPrioridad,
    ahora: datetime,
    modalidad: ConfigModalidad | None = None,
    temas: Collection[str] | None = None,
) -> list[Puntaje]:
    """R, I, U, N, E, P, rango y posición de cada grupo. Determinista: no depende del orden de ``entradas``.

    ``ahora`` es la fecha de referencia (el corte del snapshot, UTC): U se mide contra ella, nunca contra el reloj.
    ``temas`` son los temas de la modalidad para la pertenencia de R (D-119); por omisión, los 6 de ``config/temas.yaml``
    (las modalidades no declaran una lista propia).
    """
    temas = frozenset(cargar_temas().temas if temas is None else temas)
    entradas = sorted(entradas, key=lambda e: e.id_grupo)
    ids = [e.id_grupo for e in entradas]
    if len(set(ids)) != len(ids):
        raise ValueError("id_grupo repetido en la entrada")
    ahora = ahora.astimezone(UTC)
    maximas = _similitudes_maximas(entradas, reglas)
    umbral = umbral_novedad(reglas)
    rel = reglas.relevancia
    resultado: list[Puntaje] = []
    for i, e in enumerate(entradas):
        foco, detalle_foco = foco_de(e.miembros, reglas, cfg)
        pertenencia, detalle_pertenencia = pertenencia_de(e.miembros, temas, reglas, e.tema)
        r = Componente(rel.peso_foco * foco * pertenencia, {**detalle_foco, **detalle_pertenencia, "peso_foco": rel.peso_foco})
        c_i, vacios_i = impacto(e, reglas, cfg, modalidad)
        c_u, vacios_u = urgencia(e.miembros, ahora, reglas)
        if maximas[i] is None:
            c_n = Componente(
                reglas.novedad.sin_grupos_previos,
                {"grupos_previos": 0, "similitud_maxima": None, "umbral_similitud": umbral, "descuenta": False, "grupo_mas_parecido": None,
                 "ancla_baja": reglas.novedad.ancla_baja, "ancla_alta": umbral, "ventana_dias": reglas.novedad.ventana_dias},
            )
        else:
            sim, parecido, previos = maximas[i]  # type: ignore[misc]
            c_n = Componente(
                novedad_de(sim, reglas.novedad.ancla_baja, umbral),
                {"grupos_previos": previos, "similitud_maxima": sim, "umbral_similitud": umbral, "descuenta": sim > reglas.novedad.ancla_baja,
                 "grupo_mas_parecido": parecido, "ancla_baja": reglas.novedad.ancla_baja, "ancla_alta": umbral,
                 "ventana_dias": reglas.novedad.ventana_dias},
            )
        componentes = {"R": r, "I": c_i, "U": c_u, "N": c_n, "E": evidencia_e(e, reglas, cfg)}
        total = puntaje_total({k: c.valor for k, c in componentes.items()}, reglas)
        recirculada = bool(e.miembros) and all(m.get("es_recirculada") is True for m in e.miembros)
        vacios = [*vacios_i, *vacios_u]
        if recirculada:
            fecha = _fecha_mas_reciente(e.miembros, CAMPO_PUBLICACION)
            vacios.append(Vacio("noticia_recirculada", cfg.vacios.noticia_recirculada.format(fecha=fecha[1] if fecha else "fecha desconocida")))
        resultado.append(
            Puntaje(
                id_grupo=e.id_grupo,
                posicion=0,
                version_reglas=reglas.version,
                fecha_referencia=ahora.strftime(FORMATO_FECHA),
                componentes=componentes,
                puntaje=total,
                rango=rango_de(total, reglas),
                vacios=tuple(vacios),
                recirculada=recirculada,
                es_nueva=not recirculada,
            )
        )
    return ordenar(resultado, reglas, cfg)


if __name__ == "__main__":
    from src.prioridad import main

    sys.exit(main())
