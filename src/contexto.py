"""Contextualización de grupos con indicadores del Banco Mundial · E1-09, etapa 3, CU-02, T04.

Cada grupo (``GRP-``) se vincula con el indicador que le corresponde según su **tema** y las **reglas internas de vínculo**
de ``config/vinculos.yaml``; nada fuera de esa tabla. El resultado va a la tabla ``vinculos`` (``src/db.py``).

* **Reglas de vínculo (D-125):** el reto define 6 temas y ningún subtema. Una regla (``reglas_vinculo``) se dispara si el tema del
  grupo es el suyo y algún titular contiene uno de sus términos (palabra completa, sin mayúsculas ni acentos) o patrones, salvo
  que lleve una exclusión. Las reglas NO son categorías: no se guardan en la base como tema ni subtema y la ficha no las muestra
  como tales; solo dejan su texto en ``vinculos.regla``. Si se disparan dos o más del mismo tema, el vínculo es ambiguo: no se
  elige ninguno (``candidatos_ambiguos``).
* **Vínculo (D-127):** solo lo da una regla disparada por un término literal; no hay vínculo por tema. Sin regla disparada:
  ``sin_relacion_sustentada`` (el tema tiene reglas y ningún titular las sustenta; el PDF pide no forzar la relación) o
  ``tema_sin_indicador`` (el tema no tiene reglas).
  Un indicador sin ningún valor no nulo de Panamá es ``sin_dato_en_periodo``.
* **Panamá:** el último año con valor no nulo, declarado en la limitación junto con los años posteriores sin valor.
  **Comparables:** los demás países de la cuadrícula en **ese mismo año**, solo los que tienen dato. **Tendencia:** los
  últimos ``tendencia_anios`` años de Panamá hasta el declarado; los nulos siguen siendo nulos (nunca 0).
* **Cifra del titular:** si el titular trae su propia cifra (%) del mismo indicador, se compara con la oficial sin corregir
  al medio: mismo año -> «posible discrepancia, verificar»; otro período -> «período distinto, no comparable».
* **USGS (sismos):** lo resuelve ``src/contexto_sismos.py`` (E1-09b). Aquí un vínculo cuya ``fuente`` no es ``indicador`` se
  deja pasar y se cuenta como ``delegados``: no se inventa un vínculo del Banco Mundial para un sismo. La CLI también
  vincula USGS **por defecto** (``--eventos``, por defecto ``data/processed/eventos.geojson``): ``aplicar_sismos`` vincula esos
  grupos con ``eventos.geojson`` (misma regla de vínculo, ``fuente = 'usgs'``). Si el archivo falta, se borran las filas ``usgs`` viejas
  y el reporte lo declara. Toda la reescritura de ``vinculos`` es una sola transacción (todo o nada).

* **SBP (banca):** lo resuelve ``src/contexto_sbp.py`` (E3-02), igual que USGS: una regla de vínculo con ``fuente: sbp`` en ``vinculos.yaml``
  recibe una fila por serie agregada del sistema bancario (``sbp_series.csv``, ``fuente = 'sbp'``). La CLI lo hace **por defecto**
  (``--sbp``); si el archivo falta, se borran las filas ``sbp`` viejas y el reporte lo declara.

Los datos son anuales: ningún texto de salida usa la palabra «actual» (``palabras_prohibidas``). Cada fila guarda la
``regla`` que la generó y ``fuente = 'indicador'``; ``src.contexto`` reemplaza solo sus propias filas al volver a correr.

Uso: ``poetry run python -m src.contexto`` (después de ``src.agrupacion``; vincula Banco Mundial, USGS y SBP).
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

from src import contexto_sbp, contexto_sismos, db
from src.clasificacion import proporcion
from src.configuracion import (
    RAIZ,
    ConfigVinculos,
    ReglaVinculo,
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
ROL_PANAMA, ROL_COMPARABLE, ROL_TENDENCIA = "panama", "comparable", "tendencia"
MOTIVO_AMBIGUO = "candidatos_ambiguos"
REGLA_VINCULO = "vinculo_por_regla"
REGLA_SIN_ENTRADA = "sin_vinculo_en_tabla"
MOTIVO_SIN_DATO = "sin_dato_en_periodo"
REGLA_SIN_DATO = MOTIVO_SIN_DATO
SEPARADOR_ANIOS = ", "
REPORTE = "reporte_vinculos.json"
EVENTOS = Path("processed") / "eventos.geojson"   # bajo ``data/``
SERIES_SBP = Path("processed") / "sbp_series.csv"   # bajo ``data/`` (fuente D, E3-02)
POSICION_ANIO = slice(0, 4)      # ``YYYY`` de una fecha ISO 8601


# ------------------------------------------------------------------ reglas de vínculo (D-125)


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con los espacios colapsados."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sin_acentos.casefold().split())


def _palabra_completa(termino: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(_normalizar(termino)) + r"(?!\w)")


def menciona_termino(titular: str, terminos: Sequence[str]) -> bool:
    """``True`` si ``titular`` contiene alguno de ``terminos`` como palabra completa, sin importar mayúsculas ni acentos."""
    texto = _normalizar(titular)
    return any(_palabra_completa(t).search(texto) for t in terminos if t.strip())


def termino_que_dispara(titulares: Sequence[str], regla: ReglaVinculo) -> str | None:
    """Primer término (o patrón) de ``regla`` que algún titular contiene, o ``None`` si no se dispara.

    Un titular con un marcador de ``exclusiones`` no cuenta («juez imputa a funcionarios del MOP»). El orden de la lista de
    términos manda, así que el resultado es determinista.
    """
    textos = [_normalizar(t) for t in titulares]
    textos = [x for x in textos if not any(m.strip() and _palabra_completa(m).search(x) for m in regla.exclusiones)]
    for termino in regla.terminos:
        if any(_palabra_completa(termino).search(x) for x in textos):
            return termino
    for patron in regla.patrones:
        if any(re.search(patron, x) for x in textos):
            return patron
    return None


def reglas_disparadas(titulares: Sequence[str], tema: str | None, cfg: ConfigVinculos) -> dict[str, str]:
    """Reglas de vínculo del ``tema`` que dispara algún titular, con el término que las disparó (ordenadas por nombre).

    Sin tema (nulo o ``sin_tema``) ninguna regla se dispara: una regla exige el tema del grupo. Las reglas sin tema (D-127,
    ``reglas_contextuales``) no entran aquí: no compiten con las del tema ni son nunca el vínculo principal.
    """
    disparadas = {}
    for nombre, regla in sorted(cfg.reglas_vinculo.items()):
        if regla.tema is not None and regla.tema == tema and (termino := termino_que_dispara(titulares, regla)) is not None:
            disparadas[nombre] = termino
    return disparadas


def reglas_contextuales(titulares: Sequence[str], cfg: ConfigVinculos) -> dict[str, str]:
    """D-127: reglas sin tema (hoy ``sismos``) que algún titular dispara con un término literal, con el término que las disparó.

    Un término sísmico literal es la evidencia que sustenta el contexto de USGS, sea cual sea el tema del grupo. Es un contexto
    aparte: un grupo puede tener su vínculo principal por tema y además este contexto.
    """
    return {
        nombre: termino
        for nombre, regla in sorted(cfg.reglas_vinculo.items())
        if regla.tema is None and (termino := termino_que_dispara(titulares, regla)) is not None
    }


def tema_con_reglas(tema: str | None, cfg: ConfigVinculos) -> bool:
    """``True`` si alguna regla de vínculo es del ``tema`` (un grupo de ese tema sin término que la sustente no tiene relación sustentada)."""
    return tema is not None and any(r.tema == tema for r in cfg.reglas_vinculo.values())


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


def elegir_vinculo(
    tema: str | None, disparadas: Mapping[str, str], cfg: ConfigVinculos
) -> tuple[Vinculo | None, str, str | None, str | None]:
    """Vínculo de un grupo, el texto de la regla que lo eligió, el motivo si no hay vínculo y el nombre de la regla de vínculo.

    Una regla disparada gana; dos o más del tema son ambiguas (sin vínculo, ``candidatos_ambiguos``). D-127: sin regla disparada
    no hay vínculo y nunca se fuerza por tema: ``sin_relacion_sustentada`` si el tema tiene reglas pero ningún titular las sustenta,
    ``tema_sin_indicador`` si el tema no tiene ninguna. Devuelve ``(vinculo, regla, motivo, nombre_de_regla)``.
    """
    textos = cfg.textos_regla
    if len(disparadas) > 1:
        return None, textos.ambigua.format(tema=tema, reglas=", ".join(sorted(disparadas))), MOTIVO_AMBIGUO, None
    if disparadas:
        ((nombre, termino),) = disparadas.items()
        return cfg.reglas_vinculo[nombre], textos.disparada.format(regla=nombre, termino=termino), None, nombre
    if tema_con_reglas(tema, cfg):
        return None, textos.sin_relacion.format(tema=tema), cfg.motivo_sin_relacion, None
    return None, f"{REGLA_SIN_ENTRADA}:{tema or 'sin_tema'}", cfg.motivo_por_defecto, None


def _fila(id_grupo: str, **campos: Any) -> dict[str, Any]:
    """Fila de ``vinculos`` con todas las columnas (lo no dado es NULL)."""
    fila = dict.fromkeys(db.columnas("vinculos"))
    fila.update(id_grupo=id_grupo, fuente=FUENTE_INDICADOR, **campos)
    return fila


def _fila_dato(id_grupo: str, dato: Mapping[str, Any], vinculo: Vinculo, regla: str, rol: str, nota: str) -> dict[str, Any]:
    return _fila(
        id_grupo,
        id_evidencia=dato["id_indicador"],
        tipo=vinculo.relacion,
        regla=regla,
        limitacion=f"{vinculo.limitacion} {nota}",
        rol=rol,
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
    disparadas: Mapping[str, str],
    titular: str | None,
    anio_publicacion: int | None,
    indicadores: Sequence[Mapping[str, Any]],
    cfg: ConfigVinculos,
) -> list[dict[str, Any]] | None:
    """Filas de ``vinculos`` de un grupo; ``None`` si el vínculo no es del Banco Mundial (lo resuelve otro módulo).

    ``disparadas`` son las reglas de vínculo del grupo (``reglas_disparadas``). ``indicadores`` son las filas de la tabla
    ``indicadores`` (la cuadrícula completa, con nulos explícitos).
    """
    vinculo, regla, motivo, _ = elegir_vinculo(tema, disparadas, cfg)
    if vinculo is not None and vinculo.fuente != FUENTE_INDICADOR:
        return None  # gancho E1-09b: sismos y demás fuentes no son del Banco Mundial
    if vinculo is None:
        return [_fila(id_grupo, regla=regla, motivo_sin_vinculo=motivo)]
    serie = {
        d["anio"]: d for d in indicadores if d["indicador_id"] == vinculo.id and d["pais_iso3"] == cfg.pais_por_defecto
    }
    con_valor = sorted(a for a, d in serie.items() if d["valor"] is not None)
    if not con_valor:
        return [_fila(id_grupo, regla=f"{REGLA_SIN_DATO}:{vinculo.id}", motivo_sin_vinculo=MOTIVO_SIN_DATO)]
    ultimo = con_valor[-1]
    sin_valor = sorted(a for a in serie if a > ultimo)
    nota = cfg.notas.ultimo_anio.format(anio=ultimo)
    if sin_valor:
        nota += " " + cfg.notas.anios_sin_valor.format(anios=SEPARADOR_ANIOS.join(map(str, sin_valor)))
    principal = _fila_dato(id_grupo, serie[ultimo], vinculo, regla, ROL_PANAMA, nota)
    if titular:
        cifra = extraer_cifra_titular(titular, vinculo.id or "", cfg)
        if cifra is not None:
            etiqueta = comparar_cifra(cifra[0], cifra[1], anio_publicacion, serie[ultimo]["valor"], ultimo, cfg)
            if etiqueta is not None:
                principal.update(cifra_titular=cifra[0], anio_titular=cifra[1], comparacion_titular=etiqueta)
    filas = [principal]
    for d in sorted((d for d in indicadores if d["indicador_id"] == vinculo.id and d["anio"] == ultimo), key=lambda d: d["pais_iso3"]):
        if d["pais_iso3"] != cfg.pais_por_defecto and d["valor"] is not None:  # solo los que tienen dato, el mismo año
            filas.append(_fila_dato(id_grupo, d, vinculo, regla, ROL_COMPARABLE, nota))
    for anio in sorted(a for a in serie if ultimo - cfg.tendencia_anios < a <= ultimo):
        filas.append(
            _fila_dato(id_grupo, serie[anio], vinculo, regla, ROL_TENDENCIA, cfg.notas.serie.format(anio=anio, n=cfg.tendencia_anios))
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


def leer_grupos(con: Any, cfg: ConfigVinculos | None = None) -> list[dict[str, Any]]:
    """Cada grupo con su tema, las reglas de vínculo que disparan sus titulares (D-125), el titular central y el año.

    Sin ``cfg`` usa la configuración de ``vinculos.yaml``.
    """
    cfg = cfg or cargar_vinculos()
    titulares: defaultdict[str, list[str]] = defaultdict(list)
    for id_grupo, titulo in con.execute("SELECT id_grupo, COALESCE(titulo_limpio, titulo) FROM noticias WHERE id_grupo IS NOT NULL").fetchall():
        if titulo:
            titulares[id_grupo].append(titulo)
    grupos = []
    for id_grupo, tema, titular, publicacion, deteccion in con.execute(
        """SELECT g.id_grupo, g.tema_clasificado, g.titular_central, n.fecha_publicacion, n.fecha_deteccion
           FROM grupos g LEFT JOIN noticias n ON n.id_noticia = g.id_noticia_central ORDER BY g.id_grupo"""
    ).fetchall():
        grupos.append(
            {
                "id_grupo": id_grupo,
                "tema": tema,
                "reglas": reglas_disparadas(titulares.get(id_grupo, []), tema, cfg),
                "contextuales": reglas_contextuales(titulares.get(id_grupo, []), cfg),
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
        resultado = vincular_grupo(g["id_grupo"], g["tema"], g["reglas"], g["titular"], g["anio_publicacion"], indicadores, cfg)
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
        grupos = leer_grupos(con, cfg)
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

    D-127: un titular con un término sísmico literal basta (cualquier tema). Si algún evento coincide en el tiempo, es el vínculo de
    siempre (``evento``); si no, el catálogo de USGS del periodo extraído se muestra como contexto histórico (``indirecta``). Con ``con`` escribe dentro de la
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
        for g in leer_grupos(con, cfg):
            for nombre in g["contextuales"]:   # D-127: la regla de sismos no tiene tema: la sustenta un término sísmico literal
                if not contexto_sismos.aplica(nombre, cfg):
                    continue
                r = contexto_sismos.vincular_grupo(g["id_grupo"], nombre, fechas.get(g["id_grupo"], []), eventos, cfg, fuentes, campos_fecha)
                if r is not None and r.estado not in contexto_sismos.ESTADOS_DE_EVENTO:
                    r = contexto_sismos.contexto_historico(g["id_grupo"], nombre, eventos, cfg, fuentes)   # sin coincidencia en el tiempo
                if r is not None:
                    resultados.append(r)
        filas = [f for r in resultados for f in contexto_sismos.a_filas_vinculo(r, cfg)]
        verificar_texto(filas, cfg)
        _reemplazar(con, contexto_sismos.FUENTE_VINCULO, filas, propia)
        return resultados, filas, sin_magnitud
    finally:
        if propia:
            con.close()


def quitar_filas_usgs(con: Any) -> None:
    """Borra las filas ``fuente = 'usgs'`` (dentro de la transacción del llamador): sin eventos no queda vínculo viejo."""
    con.execute("DELETE FROM vinculos WHERE fuente = ?", [contexto_sismos.FUENTE_VINCULO])


def aplicar_sbp(
    ruta_base: Path, ruta_series: Path, cfg: ConfigVinculos, con: Any | None = None
) -> tuple[list[str], list[dict[str, Any]]]:
    """Vincula con las series de la SBP los grupos que ``vinculos.yaml`` delega a esa fuente y reemplaza solo las filas ``fuente = 'sbp'``.

    Misma regla de vínculo que los demás vínculos (``leer_grupos``). Con ``con`` escribe dentro de la transacción abierta del llamador.
    Devuelve ``(ids de los grupos de banca, filas)``.
    """
    fuentes = cargar_fuentes()
    datos = contexto_sbp.cargar_series(ruta_series)
    propia = con is None
    if propia:
        con = db.conectar(ruta_base)
    try:
        if propia:
            db.asegurar_esquema(con)
        filas: list[dict[str, Any]] = []
        grupos_banca: list[str] = []
        for g in leer_grupos(con, cfg):
            _, _, _, nombre = elegir_vinculo(g["tema"], g["reglas"], cfg)
            resultado = contexto_sbp.vincular_grupo(g["id_grupo"], nombre, datos, cfg, fuentes)
            if resultado is not None:
                grupos_banca.append(g["id_grupo"])
                filas.extend(resultado)
        verificar_texto(filas, cfg)
        _reemplazar(con, contexto_sbp.FUENTE_SBP, filas, propia)
        return grupos_banca, filas
    finally:
        if propia:
            con.close()


def quitar_filas_sbp(con: Any) -> None:
    """Borra las filas ``fuente = 'sbp'`` (dentro de la transacción del llamador): sin ``sbp_series.csv`` no queda vínculo viejo."""
    con.execute("DELETE FROM vinculos WHERE fuente = ?", [contexto_sbp.FUENTE_SBP])


def construir_reporte_sbp(grupos_banca: Sequence[str], filas: Sequence[Mapping[str, Any]], z: float) -> dict[str, Any]:
    """Grupos de banca con dato de la SBP y sin él (n e IC de Wilson), y las series vinculadas."""
    sin = {f["id_grupo"] for f in filas if f["motivo_sin_vinculo"]}
    con = len(grupos_banca) - len(sin)
    return {
        "nota": "Series agregadas mensuales de 2024 del sistema bancario (SBP) como contexto; el análisis es del equipo y no una opinión oficial de la SBP.",
        "grupos_de_banca": len(grupos_banca),
        "con_dato": proporcion(con, len(grupos_banca), z),
        "sin_dato": proporcion(len(sin), len(grupos_banca), z),
        "series_vinculadas": sorted({str(f["indicador_id"]) for f in filas if f["id_evidencia"]}),
        "filas_en_vinculos": len(filas),
    }


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
        "con_contexto_historico": proporcion(por_estado[contexto_sismos.CONTEXTO_HISTORICO], len(resultados), z),
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
        "con_vinculo_por_indicador": dict(sorted(Counter(f["indicador_id"] for f in con.values()).items())),
        "comparacion_con_cifra_del_titular": dict(sorted(Counter(f["comparacion_titular"] for f in con.values() if f["comparacion_titular"]).items())),
        "filas_en_vinculos": len(filas),
    }


ESTADO_SIN_EVENTOS = "no ejecutado: falta eventos.geojson"
ESTADO_SIN_SBP = "no ejecutado: falta sbp_series.csv"


def ejecutar(ruta_base: Path, ruta_reporte: Path, ruta_eventos: Path | None = None, ruta_sbp: Path | None = None) -> dict[str, Any]:
    """Vincula los grupos de la base y escribe ``outputs/reporte_vinculos.json``. Devuelve el reporte.

    Con ``ruta_eventos`` también vincula los grupos de sismos con USGS (``reporte["usgs"]``); sin ella no toca filas ``usgs``.
    Si ``ruta_eventos`` no existe se borran las filas ``usgs`` viejas y el reporte lo declara (``ESTADO_SIN_EVENTOS``).
    Con ``ruta_sbp`` también vincula los grupos de banca con las series de la SBP (``reporte["sbp"]``); igual que USGS, sin ella no toca
    filas ``sbp`` y si no existe se borran las viejas (``ESTADO_SIN_SBP``).
    La reescritura de ``vinculos`` es una sola transacción: si algo falla, la tabla queda como estaba y no se escribe reporte.
    """
    cfg = cargar_vinculos()
    z = cargar_carga().salida.z_intervalo_confianza
    usgs: dict[str, Any] | None = None
    sbp: dict[str, Any] | None = None
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
            if ruta_sbp is not None:
                if ruta_sbp.exists():
                    grupos_banca, filas_sbp = aplicar_sbp(ruta_base, ruta_sbp, cfg, con)
                    sbp = construir_reporte_sbp(grupos_banca, filas_sbp, z)
                else:
                    logger.warning("No existe %s: se borran las filas sbp viejas", ruta_sbp)
                    quitar_filas_sbp(con)
                    sbp = {"estado": ESTADO_SIN_SBP, "filas_en_vinculos": 0}
            con.commit()
        except BaseException:
            con.rollback()
            raise
    finally:
        con.close()
    reporte = construir_reporte(filas, delegados, total, z)
    if usgs is not None:
        reporte["usgs"] = usgs
    if sbp is not None:
        reporte["sbp"] = sbp
    ruta_reporte.parent.mkdir(parents=True, exist_ok=True)
    with ruta_reporte.open("w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return reporte


def main(argv: list[str] | None = None) -> int:
    """CLI: vincula los grupos de ``data/senales.duckdb`` y escribe ``outputs/reporte_vinculos.json``."""
    configurar_logging()
    parser = argparse.ArgumentParser(description="E1-09/E1-09b: contexto por tema y regla de vínculo con el Banco Mundial y, por defecto, los sismos de USGS (--eventos)")
    parser.add_argument("--base", type=Path, default=RAIZ / "data" / cargar_normalizacion().salida.base_de_datos)
    parser.add_argument("--reporte", type=Path, default=RAIZ / "outputs" / REPORTE)
    parser.add_argument("--eventos", type=Path, default=RAIZ / "data" / EVENTOS, help="eventos.geojson de USGS (E1-09b)")
    parser.add_argument("--sbp", type=Path, default=RAIZ / "data" / SERIES_SBP, help="sbp_series.csv de la SBP (E3-02)")
    args = parser.parse_args(argv)
    if not args.base.exists():
        logger.error("No existe %s: ejecute primero `normalizacion`, `limpieza`, `clasificacion` y `agrupacion`", args.base)
        return 1
    try:
        r = ejecutar(args.base, args.reporte, args.eventos, args.sbp)
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
    if "sbp" in r:
        if "estado" in r["sbp"]:
            logger.info("banca (SBP): %s", r["sbp"]["estado"])
        else:
            logger.info("banca (SBP): %d grupos; con dato: %d", r["sbp"]["grupos_de_banca"], r["sbp"]["con_dato"]["n"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
