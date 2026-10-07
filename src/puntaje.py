"""Puntaje de atención determinista (R, I, U, N, E y P) y ranking · E1-10, CU-01, T03, T08, PDF sección 4.

``P = 30R + 25I + 20U + 15N + 10E`` con las reglas v1.3 (``config/reglas_v1.3.yaml``; los parámetros que esas reglas no
fijan, en ``config/prioridad.yaml``). Es una herramienta de **ordenamiento**: no es una probabilidad de verdad ni de pérdida,
y **no habilita publicación** (``Puntaje.habilita_publicacion`` es siempre falso).

* **R** = ``peso_foco × foco + peso_tematica × percentil(similitud temática)``. Foco: 1 si algún titular del grupo trata a
  Panamá como sujeto; 0.5 si todos son notas regionales o de otro país que afectan a Panamá (``alcance_regional``, D-84).
  La similitud temática de un grupo es la media de ``tema_similitud`` de sus titulares.
* **I** = ``peso_subtema × alcance(subtema) + peso_geografico × alcance geográfico``. Ni el dato oficial ni las
  procedencias suman aquí (D-15, D-35). El alcance geográfico es el más amplio que nombren los titulares; sin término
  explícito ni lugar concreto, el país nombrado o una institución nacional lo hacen nacional (E1-10c, X42).
* **U**: lineal entre ``horas_pleno`` (U = 1) y ``dias_nulo`` (U = 0) desde la publicación ORIGINAL más reciente del grupo,
  medida contra la fecha de referencia (el corte del snapshot). Si ningún titular trae ``fecha_publicacion`` se usa la
  detección como cota y se agrega el vacío «urgencia estimada: fecha de publicación desconocida»; nunca se sustituye en silencio.
* **N** = ``1 − percentil(similitud máxima con grupos anteriores)``; anterior = empezó antes (``fecha_publicacion`` y, si falta,
  ``fecha_deteccion``). El primer grupo no tiene con qué compararse (``novedad.sin_grupos_previos``). La duplicación no sube N.
* **E** = ``peso_procedencias × min(n, tope)/tope + peso_oficial × (hay dato oficial directo o evento) + peso_identificables × (titulares con
  medio y fecha de publicación conocidos / titulares)``. Cuenta **procedencias**, nunca titulares (``procedencias.fraccion_de_procedencias``).

Las similitudes se convierten a **percentil dentro del snapshot** (los embeddings dan valores comprimidos): el rango
completo 0–1 se usa siempre. Rango y desempate (mayor U, menor ID) salen de ``reglas.rangos`` y ``reglas.desempate``.
Cada componente guarda su explicación (de qué valores sale) para la ficha.

Uso: ``poetry run python -m src.puntaje`` (después de ``src.contexto``); ver ``src/prioridad.py``.
"""

from __future__ import annotations

import re
import sys
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import numpy as np

from src.agrupacion import fecha_de, fecha_iso_de
from src.configuracion import ConfigPrioridad, ReglasV13
from src.evidencia import Vacio
from src.limpieza import plano
from src.procedencias import fraccion_de_procedencias

COMPONENTES = ("R", "I", "U", "N", "E")
NIVELES_GEOGRAFICOS = ("nacional", "provincial", "local")   # de más a menos amplio; sin términos = desconocido
NIVEL_NACIONAL = NIVELES_GEOGRAFICOS[0]
NIVEL_DESCONOCIDO = "desconocido"
PERCENTIL_NEUTRO = 0.5          # rango medio de [0, 1]: lo que vale un percentil con un solo valor (definición, no parámetro)
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
    miembros: tuple[Mapping[str, Any], ...]     # id_noticia, titulo_limpio, medio, fecha_publicacion, fecha_deteccion, es_recirculada, alcance_regional, tema_similitud
    vectores: np.ndarray | None                 # embeddings normalizados de los miembros (misma posición); necesarios para N
    subtema: str | None
    n_procedencias: int
    tiene_oficial: bool
    motivo_sin_oficial: str | None = None
    solo_indirecto: bool = False                 # hay un vínculo con dato, pero indirecto (X22): no cuenta como dato oficial
    discrepancias: tuple[str, ...] = ()          # IDs de datos oficiales que la cifra de un titular contradice
    periodos_distintos: tuple[str, ...] = ()     # IDs de datos oficiales de otro período que la cifra de un titular
    eventos_sin_revisar: tuple[str, ...] = ()    # IDs de eventos oficiales con estado automático


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
            "habilita_publicacion": self.habilita_publicacion,
        }


@dataclass(frozen=True)
class Alcance:
    """Alcance geográfico de un grupo: el más amplio que nombran sus titulares y los términos que lo dicen."""

    nivel: str
    valor: float
    terminos: tuple[str, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------ percentil


def percentiles(valores: Sequence[float]) -> list[float]:
    """Percentil de cada valor dentro de ``valores``: ``(rango medio) / (n − 1)``, de 0 (el menor) a 1 (el mayor).

    Los empates comparten el rango medio. Con un solo valor es ``PERCENTIL_NEUTRO``. Así el rango 0–1 se usa completo
    aunque las similitudes estén comprimidas.
    """
    n = len(valores)
    if n == 0:
        return []
    if n == 1:
        return [PERCENTIL_NEUTRO]
    orden = sorted(valores)
    return [((bisect_left(orden, v) + bisect_right(orden, v) - 1) / 2) / (n - 1) for v in valores]


# ------------------------------------------------------------------ R · relevancia


def foco_de(miembros: Sequence[Mapping[str, Any]], reglas: ReglasV13) -> tuple[float, dict[str, Any]]:
    """Foco del grupo y su explicación: 1 si algún titular trata a Panamá como sujeto, 0.5 si todos son regionales."""
    regionales = sum(1 for m in miembros if m.get("alcance_regional"))
    todos_regionales = regionales == len(miembros) and len(miembros) > 0
    foco = reglas.relevancia.foco_otro_pais_afecta if todos_regionales else reglas.relevancia.foco_panama_sujeto
    motivo = "otro_pais_afecta" if todos_regionales else "panama_sujeto"
    return foco, {"foco": foco, "foco_motivo": motivo, "titulares_regionales": regionales, "titulares": len(miembros)}


def similitud_tematica(miembros: Sequence[Mapping[str, Any]]) -> float:
    """Media de ``tema_similitud`` de los titulares del grupo (similitud con su tema clasificado)."""
    valores = [float(m["tema_similitud"]) for m in miembros if m.get("tema_similitud") is not None]
    if not valores:
        raise ValueError("grupo sin similitud temática: ejecute `poetry run python -m src.clasificacion`")
    return float(np.mean(valores))


# ------------------------------------------------------------------ I · impacto


NO_ALFANUMERICO = re.compile(r"[\W_]+")


def normalizar_geografia(texto: str) -> str:
    """Sin tildes ni mayúsculas, y con guiones, rayas y espacios repetidos reducidos a un espacio («Ngäbe-Buglé» = «ngabe bugle»)."""
    return NO_ALFANUMERICO.sub(" ", plano(texto)).strip()


@lru_cache(maxsize=None)
def _patron_termino(termino: str, prefijos: tuple[str, ...]) -> re.Pattern[str]:
    """Palabra completa, sin tildes ni mayúsculas; con ``prefijos`` solo cuenta si la precede alguno."""
    cuerpo = re.escape(normalizar_geografia(termino))
    if prefijos:
        cuerpo = r"(?:" + "|".join(re.escape(normalizar_geografia(p)) for p in prefijos) + r")\s+" + cuerpo
    return re.compile(rf"(?<!\w){cuerpo}(?!\w)")


def terminos_presentes(texto: str, terminos: Sequence[str], prefijos: Mapping[str, Sequence[str]]) -> list[str]:
    """Términos de ``terminos`` que aparecen en ``texto`` (en el orden dado)."""
    plano_texto = normalizar_geografia(texto)
    return [t for t in terminos if _patron_termino(t, tuple(prefijos.get(t, ()))).search(plano_texto)]


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


def alcance_geografico(miembros: Sequence[Mapping[str, Any]], reglas: ReglasV13, cfg: ConfigPrioridad) -> Alcance:
    """Alcance más amplio que nombran los titulares: nacional, provincial (provincias y comarcas) o local (distritos).

    Si ningún titular nombra un término explícito ni un lugar concreto, el país nombrado o una institución nacional
    (``nacional_implicito_terminos``) dan alcance nacional (E1-10c, X42); si tampoco, el alcance es desconocido.
    """
    g = reglas.geografia
    listas = {"nacional": g.nacional_terminos, "provincial": [*g.provincias, *g.comarcas], "local": g.distritos}
    prefijos = cfg.geografia.prefijos_obligatorios
    hallados: dict[str, list[str]] = {nivel: [] for nivel in NIVELES_GEOGRAFICOS}
    implicitos: list[str] = []
    for m in miembros:
        titular = str(m.get("titulo_limpio") or "")
        for nivel in NIVELES_GEOGRAFICOS:
            hallados[nivel].extend(terminos_presentes(titular, listas[nivel], prefijos))
        implicitos.extend(terminos_sin_prefijo_excluido(titular, g.nacional_implicito_terminos, cfg.geografia.prefijos_excluidos))
    for nivel in NIVELES_GEOGRAFICOS:
        if hallados[nivel]:
            return Alcance(nivel, getattr(reglas.impacto.alcance_geografico, nivel), tuple(sorted(set(hallados[nivel]))))
    if implicitos:
        return Alcance(NIVEL_NACIONAL, reglas.impacto.alcance_geografico.nacional, tuple(sorted(set(implicitos))))
    return Alcance(NIVEL_DESCONOCIDO, reglas.impacto.alcance_geografico.desconocido)


def impacto(entrada: EntradaGrupo, reglas: ReglasV13, cfg: ConfigPrioridad) -> tuple[Componente, list[Vacio]]:
    """I del grupo. Ni el dato oficial ni las procedencias entran (D-15, D-35)."""
    vacios: list[Vacio] = []
    if entrada.subtema is None:
        alcance_subtema = cfg.impacto.alcance_subtema_desconocido
        vacios.append(Vacio("subtema_desconocido", cfg.vacios.subtema_desconocido))
    else:
        alcance_subtema = reglas.impacto.alcance_subtema[entrada.subtema]
    geo = alcance_geografico(entrada.miembros, reglas, cfg)
    valor = reglas.impacto.peso_subtema * alcance_subtema + reglas.impacto.peso_geografico * geo.valor
    return Componente(
        valor,
        {
            "subtema": entrada.subtema,
            "alcance_subtema": alcance_subtema,
            "nivel_geografico": geo.nivel,
            "alcance_geografico": geo.valor,
            "terminos_geograficos": list(geo.terminos),
            "peso_subtema": reglas.impacto.peso_subtema,
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
    return Componente(
        valor,
        {"fecha": texto, "fecha_origen": origen, "edad_horas": edad_horas, "horas_pleno": u.horas_pleno, "dias_nulo": u.dias_nulo},
    ), vacios


# ------------------------------------------------------------------ N · novedad


def _fecha_de_inicio(entrada: EntradaGrupo, reglas: ReglasV13) -> datetime | None:
    fechas = [f for f in (fecha_de(m, reglas.agrupacion.campos_fecha) for m in entrada.miembros) if f is not None]
    return min(fechas) if fechas else None


def _similitudes_maximas(entradas: Sequence[EntradaGrupo], reglas: ReglasV13) -> list[tuple[float, str, int] | None]:
    """Por grupo: (similitud máxima con un titular de un grupo anterior, ese grupo, cuántos grupos anteriores); ``None`` si no hay."""
    sin_fecha = datetime.max.replace(tzinfo=UTC)
    inicio = [_fecha_de_inicio(e, reglas) or sin_fecha for e in entradas]
    orden = sorted(range(len(entradas)), key=lambda i: (inicio[i], entradas[i].id_grupo))
    resultado: list[tuple[float, str, int] | None] = [None] * len(entradas)
    for pos, i in enumerate(orden):
        mejor: tuple[float, str] | None = None
        for j in orden[:pos]:
            a, b = entradas[i].vectores, entradas[j].vectores
            if a is None or b is None:
                raise ValueError("novedad: faltan los vectores de un grupo")
            s = float((a @ b.T).max())
            if mejor is None or s > mejor[0]:
                mejor = (s, entradas[j].id_grupo)
        resultado[i] = None if mejor is None else (mejor[0], mejor[1], pos)
    return resultado


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


def ordenar(puntajes: Sequence[Puntaje], reglas: ReglasV13, cfg: ConfigPrioridad) -> list[Puntaje]:
    """Ordena por P descendente y desempata con ``reglas.desempate`` (mayor U, luego menor ID); asigna ``posicion`` desde 1.

    P y U se comparan redondeados a ``comparacion.decimales_p`` para que el ruido de coma flotante no decida un empate.
    """
    d = cfg.comparacion.decimales_p

    def clave(p: Puntaje) -> tuple[Any, ...]:
        partes: list[Any] = [-round(p.puntaje, d)]
        for criterio in reglas.desempate:
            partes.append(-round(p.componentes["U"].valor, d) if criterio == "u_desc" else p.id_grupo)
        return tuple(partes)

    return [replace(p, posicion=i) for i, p in enumerate(sorted(puntajes, key=clave), start=1)]


def calcular_puntajes(
    entradas: Sequence[EntradaGrupo], reglas: ReglasV13, cfg: ConfigPrioridad, ahora: datetime
) -> list[Puntaje]:
    """R, I, U, N, E, P, rango y posición de cada grupo. Determinista: no depende del orden de ``entradas``.

    ``ahora`` es la fecha de referencia (el corte del snapshot, UTC): U se mide contra ella, nunca contra el reloj.
    """
    entradas = sorted(entradas, key=lambda e: e.id_grupo)
    ids = [e.id_grupo for e in entradas]
    if len(set(ids)) != len(ids):
        raise ValueError("id_grupo repetido en la entrada")
    ahora = ahora.astimezone(UTC)
    similitudes = [similitud_tematica(e.miembros) for e in entradas]
    percentil_r = percentiles(similitudes)
    maximas = _similitudes_maximas(entradas, reglas)
    con_previos = [i for i, m in enumerate(maximas) if m is not None]
    percentil_n: dict[int, float] = dict(zip(con_previos, percentiles([maximas[i][0] for i in con_previos]), strict=True))  # type: ignore[index]
    rel = reglas.relevancia
    resultado: list[Puntaje] = []
    for i, e in enumerate(entradas):
        foco, detalle_foco = foco_de(e.miembros, reglas)
        r = Componente(
            rel.peso_foco * foco + rel.peso_tematica * percentil_r[i],
            {**detalle_foco, "similitud_tematica": similitudes[i], "percentil_similitud_tematica": percentil_r[i],
             "peso_foco": rel.peso_foco, "peso_tematica": rel.peso_tematica},
        )
        c_i, vacios_i = impacto(e, reglas, cfg)
        c_u, vacios_u = urgencia(e.miembros, ahora, reglas)
        if maximas[i] is None:
            c_n = Componente(reglas.novedad.sin_grupos_previos, {"grupos_previos": 0, "similitud_maxima": None, "percentil_similitud_maxima": None, "grupo_mas_parecido": None})
        else:
            sim, parecido, previos = maximas[i]  # type: ignore[misc]
            c_n = Componente(
                1.0 - percentil_n[i],
                {"grupos_previos": previos, "similitud_maxima": sim, "percentil_similitud_maxima": percentil_n[i], "grupo_mas_parecido": parecido},
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
