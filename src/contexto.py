"""Contextualización de grupos con indicadores del Banco Mundial · E1-09, etapa 3, CU-02, T04.

Cada grupo (``GRP-``) se vincula con el indicador que le corresponde **por subtema** y solo según
``config/vinculos.yaml``; nada fuera de esa tabla. El resultado va a la tabla ``vinculos`` (``src/db.py``).

* **Subtema:** el subtema más cercano dentro del tema asignado al grupo (método B de ``src/clasificacion.py``, tabla
  ``similitud_tema``), aunque el método activo sea el A. Voto de los titulares del grupo; desempata la suma de similitudes.
  **Solo si** lo respalda un criterio de ``vinculos.subtema.criterios``: el único subtema del tema que nombran los titulares
  (``terminos_por_subtema``, criterio ``lexico``, X53: aunque no sea el más cercano) o, si se activa, el más cercano con margen
  ``margen_minimo`` (criterio ``margen``, D-92; inactivo desde E1-10c). Si los titulares nombran dos subtemas del tema, es ambiguo. Sin respaldo, el grupo queda sin subtema y recibe el vínculo por tema o ``tema_sin_indicador``.
* **Vínculo:** primero ``vinculos`` (por subtema), después ``vinculos_por_tema``; si no hay, ``tema_sin_indicador``.
  Un indicador sin ningún valor no nulo de Panamá es ``sin_dato_en_periodo``.
* **Panamá:** el último año con valor no nulo, declarado en la limitación junto con los años posteriores sin valor.
  **Comparables:** los demás países de la cuadrícula en **ese mismo año**, solo los que tienen dato. **Tendencia:** los
  últimos ``tendencia_anios`` años de Panamá hasta el declarado; los nulos siguen siendo nulos (nunca 0).
* **Cifra del titular:** si el titular trae su propia cifra (%) del mismo indicador, se compara con la oficial sin corregir
  al medio: mismo año -> «posible discrepancia, verificar»; otro período -> «período distinto, no comparable».
* **USGS (sismos):** lo resuelve ``src/contexto_sismos.py`` (E1-09b). Aquí un vínculo cuya ``fuente`` no es ``indicador`` se
  deja pasar y se cuenta como ``delegados``: no se inventa un vínculo del Banco Mundial para un sismo. La CLI también
  vincula USGS **por defecto** (``--eventos``, por defecto ``data/processed/eventos.geojson``): ``aplicar_sismos`` vincula esos
  grupos con ``eventos.geojson`` (mismo subtema, ``fuente = 'usgs'``). Si el archivo falta, se borran las filas ``usgs`` viejas
  y el reporte lo declara. Toda la reescritura de ``vinculos`` es una sola transacción (todo o nada).

Los datos son anuales: ningún texto de salida usa la palabra «actual» (``palabras_prohibidas``). Cada fila guarda la
``regla`` que la generó y ``fuente = 'indicador'``; ``src.contexto`` reemplaza solo sus propias filas al volver a correr.

Uso: ``poetry run python -m src.contexto`` (después de ``src.agrupacion``; vincula Banco Mundial y USGS).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src import contexto_sismos, db
from src.clasificacion import proporcion
from src.configuracion import (
    RAIZ,
    ConfigVinculos,
    SubtemaVinculo,
    Vinculo,
    cargar_carga,
    cargar_fuentes,
    cargar_normalizacion,
    cargar_reglas,
    cargar_temas,
    cargar_vinculos,
)
from src.registro import configurar_logging

logger = logging.getLogger(__name__)

FUENTE_INDICADOR = "indicador"   # valor de ``vinculos.fuente`` de las filas que escribe este módulo
METODO_SUBTEMA = "B"             # el subtema solo existe en el método B (prototipos por subtema)
ROL_PANAMA, ROL_COMPARABLE, ROL_TENDENCIA = "panama", "comparable", "tendencia"
CRITERIO_MARGEN, CRITERIO_LEXICO = "margen", "lexico"   # D-92: por qué se aceptó el subtema
REGLA_SUBTEMA = "vinculo_por_subtema"
REGLA_TEMA = "vinculo_por_tema"
REGLA_SIN_ENTRADA = "sin_vinculo_en_tabla"
MOTIVO_SIN_DATO = "sin_dato_en_periodo"
REGLA_SIN_DATO = MOTIVO_SIN_DATO
SEPARADOR_ANIOS = ", "
REPORTE = "reporte_vinculos.json"
EVENTOS = Path("processed") / "eventos.geojson"   # bajo ``data/``
POSICION_ANIO = slice(0, 4)      # ``YYYY`` de una fecha ISO 8601


# ------------------------------------------------------------------ subtema


def subtema_del_grupo(candidatos: Sequence[tuple[str, float]]) -> str | None:
    """Subtema más cercano de un grupo a partir de ``(subtema, similitud)`` de sus titulares (método B, tema del grupo).

    Gana el subtema con más titulares; empata la suma de similitudes y, si sigue el empate, el nombre (determinista).
    """
    if not candidatos:
        return None
    votos: Counter[str] = Counter(s for s, _ in candidatos)
    suma: defaultdict[str, float] = defaultdict(float)
    for subtema, similitud in candidatos:
        suma[subtema] += similitud
    return min(votos, key=lambda s: (-votos[s], -suma[s], s))


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con los espacios colapsados."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sin_acentos.casefold().split())


def menciona_termino(titular: str, terminos: Sequence[str]) -> bool:
    """``True`` si ``titular`` contiene alguno de ``terminos`` como palabra completa, sin importar mayúsculas ni acentos."""
    texto = _normalizar(titular)
    return any(re.search(r"(?<!\w)" + re.escape(_normalizar(t)) + r"(?!\w)", texto) for t in terminos if t.strip())


def subtemas_nombrados(titulares: Sequence[str], subtemas: Sequence[str], terminos: Mapping[str, Sequence[str]]) -> set[str]:
    """Subtemas de ``subtemas`` que algún titular nombra (palabra completa, sin mayúsculas ni acentos).

    X53: una coincidencia contenida dentro de otra más larga del mismo titular no cuenta («inversión» dentro de «grado de
    inversión» no nombra el subtema de inversión).
    """
    nombrados: set[str] = set()
    for titular in titulares:
        texto = _normalizar(titular)
        tramos = [
            (m.start(), m.end(), s)
            for s in subtemas
            for t in terminos.get(s, [])
            if t.strip()
            for m in re.finditer(r"(?<!\w)" + re.escape(_normalizar(t)) + r"(?!\w)", texto)
        ]
        for ini, fin, s in tramos:
            contenido = any(i <= ini and fin <= f and (f - i) > (fin - ini) for i, f, _ in tramos)
            if not contenido:
                nombrados.add(s)
    return nombrados


def decidir_subtema(
    candidatos: Sequence[tuple[str, float, float | None]],
    titulares: Sequence[str],
    cfg: SubtemaVinculo,
    subtemas_del_tema: Sequence[str] = (),
) -> tuple[str | None, str | None]:
    """``(subtema, criterio)`` del grupo, o ``(None, None)`` si el subtema es dudoso (D-92, E1-10c).

    Se buscan en los titulares los términos (``terminos_por_subtema``) de los subtemas de ``subtemas_del_tema`` (el tema del
    grupo); sin tema conocido, solo los del subtema más cercano (``subtema_del_grupo``). Si los titulares nombran **dos o más**
    subtemas, el subtema es ambiguo y no se afirma (X41: «exdirector de la CSS» aprehendido nombra salud y seguridad). Si no,
    se acepta por el primero de ``cfg.criterios`` que lo respalde:

    * ``lexico`` (X53): el **único** subtema nombrado, sea o no el más cercano por embeddings («Minsa: vacunación…» → salud
      pública aunque el más cercano sea agua potable).
    * ``margen`` (D-92, inactivo desde E1-10c): el más cercano, si el margen promedio de los titulares (1.º − 2.º subtema del
      tema) alcanza ``margen_minimo`` y ningún titular nombra otro subtema. Un titular sin margen guardado no lo respalda.
    """
    elegido = subtema_del_grupo([(s, sim) for s, sim, _ in candidatos])
    universo = list(subtemas_del_tema) or ([elegido] if elegido else [])
    nombrados = subtemas_nombrados(titulares, universo, cfg.terminos_por_subtema)
    if len(nombrados) > 1:
        return None, None
    margenes = [m for _, _, m in candidatos]
    for criterio in cfg.criterios:
        if criterio == CRITERIO_LEXICO and nombrados:
            return next(iter(nombrados)), CRITERIO_LEXICO
        if (
            criterio == CRITERIO_MARGEN and elegido is not None and nombrados <= {elegido}
            and all(m is not None for m in margenes) and sum(margenes) / len(margenes) >= cfg.margen_minimo   # type: ignore[arg-type]
        ):
            return elegido, CRITERIO_MARGEN
    return None, None


# ------------------------------------------------------------------ cifra del titular


def _numero(texto: str) -> float:
    return float(texto.replace(",", ".").replace("−", "-"))


def _alternativa(palabras: Sequence[str]) -> re.Pattern[str]:
    """Patrón que reconoce cualquiera de ``palabras`` como palabra completa (mayor longitud primero)."""
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in sorted(palabras, key=len, reverse=True)) + r")(?!\w)", re.IGNORECASE)


def _cifra_con_contexto(cifra: float, entre: str, indicador_id: str, cfg: ConfigVinculos) -> float | None:
    """Interpreta ``cifra`` según lo que la precede (``entre`` = texto entre la palabra clave y la cifra).

    * Verbo de cambio + «a»/«hasta» («cae a 0,7 %»): es el **nivel alcanzado**; conserva su signo (X19).
    * Verbo de cambio sin «a» («cae 2 %»): es una **variación**. Solo se compara si el indicador oficial es una tasa de
      cambio (``indicadores_de_variacion``, p. ej. el PIB), y entonces la baja invierte el signo (X17). Contra el nivel
      oficial de inflación o desempleo no es comparable: ``None``. «baja» es ambigua y nunca se asume como verbo.
    * Palabra de cota o aproximación («bajo», «menos de», «casi», «cerca del», «hasta» suelto): ``None``.
    * Palabra tipo verbo fuera de las listas (futuro o condicional «caería», infinitivo «caer», «se desploma»): el signo es
      incierto, ``None``. Las proyecciones se descartan antes, en ``extraer_cifra_titular``.
    * Sin ninguna de ellas («fue de 3,2 %»): es un nivel y se compara tal cual.
    """
    c = cfg.cifra_titular
    cambios = [*c.palabras_de_baja, *c.palabras_de_baja_ambiguas, *c.palabras_de_alza]
    ultimo = None
    for ultimo in _alternativa(cambios).finditer(entre):
        pass
    if ultimo is not None:
        if _alternativa(c.palabras_de_nivel).fullmatch(entre[ultimo.end() :].strip()):
            return cifra
        if _alternativa(c.palabras_de_cota).search(entre):
            return None
        if indicador_id not in c.indicadores_de_variacion or _alternativa(c.palabras_de_baja_ambiguas).fullmatch(ultimo.group(0)):
            return None
        return -cifra if cifra > 0 and _alternativa(c.palabras_de_baja).fullmatch(ultimo.group(0)) else cifra
    if _alternativa(c.palabras_de_cota).search(entre) or _verbo_no_listado(entre, cfg):
        return None
    return cifra


def _verbo_no_listado(entre: str, cfg: ConfigVinculos) -> bool:
    """Hay en ``entre`` una palabra tipo verbo que ninguna lista conoce (``patrones_de_verbo_no_listado``)."""
    return any(re.search(rf"(?<!\w)(?:{p})(?!\w)", entre, re.IGNORECASE) for p in cfg.cifra_titular.patrones_de_verbo_no_listado)


def extraer_cifra_titular(titulo: str, indicador_id: str, cfg: ConfigVinculos) -> tuple[float, int | None] | None:
    """Cifra (%) que el titular da sobre ``indicador_id`` y el año que declara, o ``None`` si no hay una clara.

    Conservador: la palabra clave del indicador debe preceder a la cifra a no más de ``ventana_caracteres`` caracteres
    sin otras cifras ni ``%`` en medio; el titular no puede traer otra cifra en %; lo que precede a la cifra decide si es nivel, variación o cota (``_cifra_con_contexto``, X17/X19); y a lo sumo un año en el titular (si hay varios, el
    período es ambiguo y el año queda en ``None``).
    """
    c = cfg.cifra_titular
    palabras = c.palabras_clave.get(indicador_id)
    if not palabras or _alternativa(c.palabras_de_proyeccion).search(titulo):  # una proyección no es un dato observado
        return None
    clave = "|".join(re.escape(p) for p in palabras)
    patron = re.compile(rf"(?<!\w)(?:{clave})(?!\w)(?P<entre>[^\d%]{{0,{c.ventana_caracteres}}}?){c.patron_numero}", re.IGNORECASE)
    todas = {_numero(m.group(1)) for m in re.finditer(c.patron_numero, titulo)}
    ligadas = list(patron.finditer(titulo))
    cifras = {_numero(m.group(patron.groups)) for m in ligadas}
    if len(todas) != 1 or cifras != todas:  # una sola cifra en el titular y ligada a la palabra clave
        return None
    cifra = next(iter(cifras))
    for m in ligadas:
        cifra = _cifra_con_contexto(cifra, m.group("entre"), indicador_id, cfg)
        if cifra is None:
            return None  # variación de un indicador de nivel, cota o palabra ambigua: no se compara
    anios = {int(a) for a in re.findall(c.patron_anio, titulo)}
    return cifra, (next(iter(anios)) if len(anios) == 1 else None)


def decimales(cifra_texto: float) -> int:
    """Decimales con que se escribe ``cifra_texto`` (``2.3`` -> 1)."""
    texto = repr(float(cifra_texto))
    return len(texto.split(".")[1].rstrip("0")) if "." in texto else 0


def comparar_cifra(
    cifra: float, anio_titular: int | None, anio_publicacion: int | None, oficial: float, anio_oficial: int, cfg: ConfigVinculos
) -> str | None:
    """Etiqueta de la comparación entre la cifra del titular y la oficial; ``None`` si no se puede afirmar nada.

    Año del titular igual al oficial: coincide (redondeando la oficial a los decimales del titular) o posible discrepancia.
    Año distinto: período distinto. Titular sin año: solo si su año de publicación difiere del oficial se puede afirmar
    «período distinto»; si coincide no se sabe a qué período se refiere y no se compara.
    """
    etiquetas = cfg.cifra_titular.etiquetas
    periodo = anio_titular if anio_titular is not None else anio_publicacion
    if periodo is None:
        return None
    if periodo != anio_oficial:
        return etiquetas.periodo_distinto
    if anio_titular is None:
        return None
    return etiquetas.coincide if round(oficial, decimales(cifra)) == cifra else etiquetas.discrepancia


# ------------------------------------------------------------------ vínculo de un grupo


def elegir_vinculo(tema: str | None, subtema: str | None, cfg: ConfigVinculos) -> tuple[Vinculo | None, str]:
    """Vínculo definido en la tabla para (tema, subtema) y la regla que lo eligió; sin entrada -> ``(None, regla)``."""
    if subtema and subtema in cfg.vinculos:
        return cfg.vinculos[subtema], f"{REGLA_SUBTEMA}:{subtema}"
    if tema and tema in cfg.vinculos_por_tema:
        return cfg.vinculos_por_tema[tema], f"{REGLA_TEMA}:{tema}"
    return None, f"{REGLA_SIN_ENTRADA}:{tema or 'sin_tema'}/{subtema or 'sin_subtema'}"


def _fila(id_grupo: str, **campos: Any) -> dict[str, Any]:
    """Fila de ``vinculos`` con todas las columnas (lo no dado es NULL)."""
    fila = dict.fromkeys(db.columnas("vinculos"))
    fila.update(id_grupo=id_grupo, fuente=FUENTE_INDICADOR, **campos)
    return fila


def _fila_dato(
    id_grupo: str, dato: Mapping[str, Any], vinculo: Vinculo, regla: str, rol: str, subtema: str | None, nota: str, criterio: str | None = None
) -> dict[str, Any]:
    return _fila(
        id_grupo,
        id_evidencia=dato["id_indicador"],
        tipo=vinculo.relacion,
        regla=regla,
        limitacion=f"{vinculo.limitacion} {nota}",
        rol=rol,
        subtema=subtema,
        criterio_subtema=criterio,
        pais_iso3=dato["pais_iso3"],
        indicador_id=dato["indicador_id"],
        anio=dato["anio"],
        unidad=dato["unidad"],
        valor=dato["valor"],
        fecha_extraccion=dato["fecha_extraccion"],
    )


def vincular_grupo(
    id_grupo: str,
    tema: str | None,
    subtema: str | None,
    titular: str | None,
    anio_publicacion: int | None,
    indicadores: Sequence[Mapping[str, Any]],
    cfg: ConfigVinculos,
    criterio_subtema: str | None = None,
) -> list[dict[str, Any]] | None:
    """Filas de ``vinculos`` de un grupo; ``None`` si el vínculo no es del Banco Mundial (lo resuelve otro módulo).

    ``indicadores`` son las filas de la tabla ``indicadores`` (la cuadrícula completa, con nulos explícitos).
    """
    vinculo, regla = elegir_vinculo(tema, subtema, cfg)
    if vinculo is not None and vinculo.fuente != FUENTE_INDICADOR:
        return None  # gancho E1-09b: sismos y demás fuentes no son del Banco Mundial
    if vinculo is None:
        return [_fila(id_grupo, regla=regla, motivo_sin_vinculo=cfg.motivo_por_defecto, subtema=subtema, criterio_subtema=criterio_subtema)]
    serie = {
        d["anio"]: d for d in indicadores if d["indicador_id"] == vinculo.id and d["pais_iso3"] == cfg.pais_por_defecto
    }
    con_valor = sorted(a for a, d in serie.items() if d["valor"] is not None)
    if not con_valor:
        return [_fila(id_grupo, regla=f"{REGLA_SIN_DATO}:{vinculo.id}", motivo_sin_vinculo=MOTIVO_SIN_DATO, subtema=subtema, criterio_subtema=criterio_subtema)]
    ultimo = con_valor[-1]
    sin_valor = sorted(a for a in serie if a > ultimo)
    nota = cfg.notas.ultimo_anio.format(anio=ultimo)
    if sin_valor:
        nota += " " + cfg.notas.anios_sin_valor.format(anios=SEPARADOR_ANIOS.join(map(str, sin_valor)))
    principal = _fila_dato(id_grupo, serie[ultimo], vinculo, regla, ROL_PANAMA, subtema, nota, criterio_subtema)
    if titular:
        cifra = extraer_cifra_titular(titular, vinculo.id or "", cfg)
        if cifra is not None:
            etiqueta = comparar_cifra(cifra[0], cifra[1], anio_publicacion, serie[ultimo]["valor"], ultimo, cfg)
            if etiqueta is not None:
                principal.update(cifra_titular=cifra[0], anio_titular=cifra[1], comparacion_titular=etiqueta)
    filas = [principal]
    for d in sorted((d for d in indicadores if d["indicador_id"] == vinculo.id and d["anio"] == ultimo), key=lambda d: d["pais_iso3"]):
        if d["pais_iso3"] != cfg.pais_por_defecto and d["valor"] is not None:  # solo los que tienen dato, el mismo año
            filas.append(_fila_dato(id_grupo, d, vinculo, regla, ROL_COMPARABLE, subtema, nota, criterio_subtema))
    for anio in sorted(a for a in serie if ultimo - cfg.tendencia_anios < a <= ultimo):
        filas.append(
            _fila_dato(id_grupo, serie[anio], vinculo, regla, ROL_TENDENCIA, subtema, cfg.notas.serie.format(anio=anio, n=cfg.tendencia_anios), criterio_subtema)
        )
    return filas


def verificar_texto(filas: Sequence[Mapping[str, Any]], cfg: ConfigVinculos) -> None:
    """Falla si algún texto de salida contiene una palabra prohibida (p. ej. «actual»): el dato es anual."""
    for palabra in cfg.palabras_prohibidas:
        patron = re.compile(rf"\b{re.escape(palabra)}\b", re.IGNORECASE)
        for f in filas:
            for campo in ("limitacion", "comparacion_titular", "regla", "motivo_sin_vinculo"):
                if f.get(campo) and patron.search(str(f[campo])):
                    raise ValueError(f"{f['id_grupo']}: {campo} contiene la palabra prohibida {palabra!r}")


# ------------------------------------------------------------------ base


def _anio_de(fecha: str | None) -> int | None:
    return int(fecha[POSICION_ANIO]) if fecha and fecha[POSICION_ANIO].isdigit() else None


def leer_grupos(con: Any, cfg: SubtemaVinculo | None = None) -> list[dict[str, Any]]:
    """Cada grupo con su tema, el subtema más cercano (método B) si lo respalda un criterio (D-92, E1-10c), su criterio,
    el titular central y el año. Sin ``cfg`` usa ``vinculos.subtema`` de la configuración."""
    cfg = cfg or cargar_vinculos().subtema
    catalogo = {t: list(d.subtemas) for t, d in cargar_temas().temas.items()}
    titulares: defaultdict[str, list[str]] = defaultdict(list)
    for id_grupo, titulo in con.execute("SELECT id_grupo, COALESCE(titulo_limpio, titulo) FROM noticias WHERE id_grupo IS NOT NULL").fetchall():
        if titulo:
            titulares[id_grupo].append(titulo)
    votos: defaultdict[str, list[tuple[str, float, float | None]]] = defaultdict(list)
    columnas = {f[0] for f in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'similitud_tema'").fetchall()}
    if "margen_subtema" not in columnas:
        logger.warning("similitud_tema no tiene margen_subtema (base anterior a D-92): ningún grupo se acepta por margen; ejecute `python -m src.clasificacion`")
    margen_sql = "s.margen_subtema" if "margen_subtema" in columnas else "NULL"
    for id_grupo, subtema, similitud, margen in con.execute(
        f"""SELECT n.id_grupo, s.subtema, s.similitud, {margen_sql} FROM noticias n
           JOIN grupos g ON g.id_grupo = n.id_grupo
           JOIN similitud_tema s ON s.id_noticia = n.id_noticia AND s.tema = g.tema_clasificado AND s.metodo = ?
           WHERE s.subtema IS NOT NULL""",
        [METODO_SUBTEMA],
    ).fetchall():
        votos[id_grupo].append((subtema, similitud, margen))
    grupos = []
    for id_grupo, tema, titular, publicacion, deteccion in con.execute(
        """SELECT g.id_grupo, g.tema_clasificado, g.titular_central, n.fecha_publicacion, n.fecha_deteccion
           FROM grupos g LEFT JOIN noticias n ON n.id_noticia = g.id_noticia_central ORDER BY g.id_grupo"""
    ).fetchall():
        subtema, criterio = decidir_subtema(votos.get(id_grupo, []), titulares.get(id_grupo, []), cfg, catalogo.get(tema, []))
        grupos.append(
            {
                "id_grupo": id_grupo,
                "tema": tema,
                "subtema": subtema,
                "criterio_subtema": criterio,
                "titular": titular,
                "anio_publicacion": _anio_de(publicacion or deteccion),
            }
        )
    return grupos


def construir_vinculos(
    grupos: Sequence[Mapping[str, Any]], indicadores: Sequence[Mapping[str, Any]], cfg: ConfigVinculos
) -> tuple[list[dict[str, Any]], list[str]]:
    """Filas de ``vinculos`` de todos los grupos y los IDs de los delegados a otra fuente (sismos)."""
    filas: list[dict[str, Any]] = []
    delegados: list[str] = []
    for g in grupos:
        resultado = vincular_grupo(g["id_grupo"], g["tema"], g["subtema"], g["titular"], g["anio_publicacion"], indicadores, cfg, g.get("criterio_subtema"))
        if resultado is None:
            delegados.append(g["id_grupo"])
            continue
        verificar_texto(resultado, cfg)
        filas.extend(resultado)
    return filas, delegados


def aplicar_a_base(ruta_base: Path, cfg: ConfigVinculos, con: Any | None = None) -> tuple[list[dict[str, Any]], list[str], int]:
    """Calcula los vínculos y reemplaza en ``vinculos`` solo las filas de ``fuente = 'indicador'``.

    Con ``con`` (conexión con una transacción abierta) escribe dentro de ella y no confirma: así ``ejecutar`` reescribe
    todo o nada. Devuelve ``(filas, delegados, total_grupos)``.
    """
    propia = con is None
    if propia:
        con = db.conectar(ruta_base)
    try:
        if propia:
            db.asegurar_esquema(con)
        grupos = leer_grupos(con, cfg.subtema)
        indicadores = db.leer_tabla(con, "indicadores")
        filas, delegados = construir_vinculos(grupos, indicadores, cfg)
        _reemplazar(con, FUENTE_INDICADOR, filas, propia)
        return filas, delegados, len(grupos)
    finally:
        if propia:
            con.close()


def _reemplazar(con: Any, fuente: str, filas: Sequence[Mapping[str, Any]], propia: bool) -> None:
    """Borra las filas de ``vinculos`` de ``fuente`` e inserta ``filas``; con ``propia`` abre y confirma su transacción."""
    if propia:
        con.begin()
    try:
        con.execute("DELETE FROM vinculos WHERE fuente = ?", [fuente])
        db.insertar(con, "vinculos", [{**dict.fromkeys(db.columnas("vinculos")), **f} for f in filas])
        if propia:
            con.commit()
    except BaseException:
        if propia:
            con.rollback()
        raise


def aplicar_sismos(
    ruta_base: Path, ruta_eventos: Path, cfg: ConfigVinculos, con: Any | None = None
) -> tuple[list[contexto_sismos.ResultadoSismos], list[dict[str, Any]], int]:
    """Vincula con USGS los grupos que ``vinculos.yaml`` delega a esa fuente y reemplaza solo las filas ``fuente = 'usgs'``.

    El subtema es el de ``leer_grupos`` (el mismo de los vínculos del Banco Mundial). Con ``con`` escribe dentro de la
    transacción abierta del llamador (ver ``aplicar_a_base``). Devuelve ``(resultados, filas, eventos_sin_magnitud)``.
    """
    fuentes, campos_fecha = cargar_fuentes(), cargar_reglas().agrupacion.campos_fecha
    eventos = contexto_sismos.cargar_eventos(ruta_eventos)
    sin_magnitud = contexto_sismos.contar_sin_magnitud(eventos)
    propia = con is None
    if propia:
        con = db.conectar(ruta_base)
    try:
        if propia:
            db.asegurar_esquema(con)
        fechas = contexto_sismos.leer_noticias_por_grupo(con)
        resultados = []
        criterios: dict[str, str | None] = {}
        for g in leer_grupos(con, cfg.subtema):
            vinculo, _ = elegir_vinculo(g["tema"], g["subtema"], cfg)
            if vinculo is None or vinculo.fuente != contexto_sismos.FUENTE_USGS:
                continue
            r = contexto_sismos.vincular_grupo(g["id_grupo"], g["subtema"], fechas.get(g["id_grupo"], []), eventos, cfg, fuentes, campos_fecha)
            if r is not None:
                resultados.append(r)
                criterios[g["id_grupo"]] = g["criterio_subtema"]
        filas = [{**f, "criterio_subtema": criterios[r.id_grupo]} for r in resultados for f in contexto_sismos.a_filas_vinculo(r, cfg)]
        verificar_texto(filas, cfg)
        _reemplazar(con, contexto_sismos.FUENTE_VINCULO, filas, propia)
        return resultados, filas, sin_magnitud
    finally:
        if propia:
            con.close()


def quitar_filas_usgs(con: Any) -> None:
    """Borra las filas ``fuente = 'usgs'`` (dentro de la transacción del llamador): sin eventos no queda vínculo viejo."""
    con.execute("DELETE FROM vinculos WHERE fuente = ?", [contexto_sismos.FUENTE_VINCULO])


# ------------------------------------------------------------------ reporte


def construir_reporte_usgs(
    resultados: Sequence[contexto_sismos.ResultadoSismos], filas: Sequence[Mapping[str, Any]], eventos_sin_magnitud: int, z: float
) -> dict[str, Any]:
    """Grupos de sismos por resultado (vinculado o motivo), con n e IC de Wilson de los vinculados."""
    por_estado = Counter(r.estado for r in resultados)
    return {
        "nota": "Eventos de USGS como contexto; no informan daños ni pérdidas. Solo cubre el periodo extraído de USGS (fuentes.yaml).",
        "grupos_de_sismos": len(resultados),
        "vinculados": proporcion(por_estado[contexto_sismos.VINCULADO], len(resultados), z),
        "por_resultado": dict(sorted(por_estado.items())),
        "filas_en_vinculos": len(filas),
        "eventos_sin_magnitud": eventos_sin_magnitud,
    }


def construir_reporte(filas: Sequence[Mapping[str, Any]], delegados: Sequence[str], total_grupos: int, z: float) -> dict[str, Any]:
    """Grupos con y sin vínculo (por motivo), con n e IC de Wilson sobre los grupos que resuelve el Banco Mundial."""
    sin = {f["id_grupo"]: f["motivo_sin_vinculo"] for f in filas if f["motivo_sin_vinculo"]}
    con = {f["id_grupo"]: f for f in filas if f["rol"] == ROL_PANAMA}
    propios = len(sin) + len(con)
    return {
        "nota": "Contexto anual del Banco Mundial; un vínculo no prueba causa. Sismos (USGS) los resuelve E1-09b.",
        "grupos_en_base": total_grupos,
        "grupos_del_banco_mundial": propios,
        "grupos_delegados_a_otra_fuente": len(delegados),
        "con_vinculo": proporcion(len(con), propios, z),
        "sin_vinculo": proporcion(len(sin), propios, z),
        "sin_vinculo_por_motivo": dict(sorted(Counter(sin.values()).items())),
        "con_vinculo_por_relacion": dict(sorted(Counter(f["tipo"] for f in con.values()).items())),
        "con_vinculo_por_subtema": dict(sorted(Counter(f["subtema"] or "sin_subtema" for f in con.values()).items())),
        "con_vinculo_por_indicador": dict(sorted(Counter(f["indicador_id"] for f in con.values()).items())),
        "comparacion_con_cifra_del_titular": dict(sorted(Counter(f["comparacion_titular"] for f in con.values() if f["comparacion_titular"]).items())),
        "filas_en_vinculos": len(filas),
    }


ESTADO_SIN_EVENTOS = "no ejecutado: falta eventos.geojson"


def ejecutar(ruta_base: Path, ruta_reporte: Path, ruta_eventos: Path | None = None) -> dict[str, Any]:
    """Vincula los grupos de la base y escribe ``outputs/reporte_vinculos.json``. Devuelve el reporte.

    Con ``ruta_eventos`` también vincula los grupos de sismos con USGS (``reporte["usgs"]``); sin ella no toca filas ``usgs``.
    Si ``ruta_eventos`` no existe se borran las filas ``usgs`` viejas y el reporte lo declara (``ESTADO_SIN_EVENTOS``).
    La reescritura de ``vinculos`` es una sola transacción: si algo falla, la tabla queda como estaba y no se escribe reporte.
    """
    cfg = cargar_vinculos()
    z = cargar_carga().salida.z_intervalo_confianza
    usgs: dict[str, Any] | None = None
    con = db.conectar(ruta_base)
    try:
        db.asegurar_esquema(con)
        con.begin()
        try:
            filas, delegados, total = aplicar_a_base(ruta_base, cfg, con)
            if ruta_eventos is not None:
                if ruta_eventos.exists():
                    resultados, filas_usgs, sin_magnitud = aplicar_sismos(ruta_base, ruta_eventos, cfg, con)
                    usgs = construir_reporte_usgs(resultados, filas_usgs, sin_magnitud, z)
                else:
                    logger.warning("No existe %s: se borran las filas usgs viejas", ruta_eventos)
                    quitar_filas_usgs(con)
                    usgs = {"estado": ESTADO_SIN_EVENTOS, "filas_en_vinculos": 0}
            con.commit()
        except BaseException:
            con.rollback()
            raise
    finally:
        con.close()
    reporte = construir_reporte(filas, delegados, total, z)
    if usgs is not None:
        reporte["usgs"] = usgs
    ruta_reporte.parent.mkdir(parents=True, exist_ok=True)
    with ruta_reporte.open("w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return reporte


def main(argv: list[str] | None = None) -> int:
    """CLI: vincula los grupos de ``data/senales.duckdb`` y escribe ``outputs/reporte_vinculos.json``."""
    configurar_logging()
    parser = argparse.ArgumentParser(description="E1-09/E1-09b: contexto por subtema con el Banco Mundial y, por defecto, los sismos de USGS (--eventos)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--reporte", type=Path, default=RAIZ / "outputs" / REPORTE)
    parser.add_argument("--eventos", type=Path, default=RAIZ / "data" / EVENTOS, help="eventos.geojson de USGS (E1-09b)")
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero `normalizacion`, `limpieza`, `clasificacion` y `agrupacion`", args.base)
        return 1
    try:
        r = ejecutar(args.base, args.reporte, args.eventos)
    except Exception as exc:  # noqa: BLE001 - CLI: reportar y salir con error
        logger.error("%s", exc)
        return 1
    logger.info("%d grupos: %d con vínculo, %d sin vínculo, %d delegados", r["grupos_en_base"], r["con_vinculo"]["n"], r["sin_vinculo"]["n"], r["grupos_delegados_a_otra_fuente"])
    logger.info("sin vínculo por motivo: %s", r["sin_vinculo_por_motivo"])
    if "usgs" in r:
        if "estado" in r["usgs"]:
            logger.info("sismos (USGS): %s", r["usgs"]["estado"])
        else:
            logger.info("sismos (USGS): %d grupos; resultado: %s", r["usgs"]["grupos_de_sismos"], r["usgs"]["por_resultado"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
