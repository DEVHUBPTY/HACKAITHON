"""Herramienta de etiquetado humano (E1-06): tema, grupo de evento y ruido de ~100 titulares.

La herramienta **no etiqueta**: arma la muestra, muestra los titulares y guarda lo que decide cada persona.

* Interfaz:   ``poetry run streamlit run eval/etiquetar.py``
* Muestra:    ``poetry run python -m eval.etiquetar --muestra``
* Validar:    ``poetry run python -m eval.etiquetar --validar``
* Acuerdo:    ``poetry run python -m eval.etiquetar --acuerdo`` (kappa de Cohen sobre los titulares dobles, D-71)
* Consolidar: ``poetry run python -m eval.etiquetar --consolidar`` (escribe ``eval/etiquetas.csv``)
* Ampliar:    ``poetry run python -m eval.etiquetar --incorporar-hoja --hoja RUTA`` (C-12; escribe ``eval/etiquetas_ampliadas.csv``)

Cada persona escribe su propia hoja ``eval/etiquetas/<nombre>.csv`` (así no se pisan en git). La muestra es
aleatoria con la semilla de ``config/etiquetado.yaml``; los primeros ``tamano_acuerdo`` titulares los etiquetan dos
personas por separado y el resto se reparte (``--parte K/N``). Nunca se muestra la descripción del RSS (D-31), ni la
decisión del filtro de ruido, ni las etiquetas de otra persona sobre un titular doble.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import random
import re
import sys
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # `streamlit run eval/etiquetar.py` o `python eval/etiquetar.py`: la raíz no está en sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import origen_etiquetas as oe  # noqa: E402
from src import db  # noqa: E402
from src.carga import intervalo_wilson  # noqa: E402
from src.configuracion import (  # noqa: E402
    RAIZ,
    ConfigEtiquetado,
    ConjuntoAmpliado,
    ConfigTemas,
    cargar_carga,
    cargar_clasificacion,
    cargar_etiquetado,
    cargar_normalizacion,
    cargar_temas,
)

COLUMNAS = (
    "id_noticia",
    "titulo",
    "tema_principal",
    "tema_secundario",
    "ruido",
    "grupo",
    "alcance_regional",
    "nota",
    "etiquetado_por",
    "fecha_etiquetado",
)
COLUMNAS_CONSOLIDADO = (*COLUMNAS, "estrato", "peso_muestreo", "n_etiquetadores", oe.COLUMNA_ORIGEN)   # origen: E1-07b, D-101
SI = "si"  # valor de alcance_regional marcado; vacío = no
PATRON_GRUPO = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PATRON_NOMBRE = re.compile(r"^[^\W\d_]+(?:[ .'-][^\W\d_]+)*\.?$")
GUIA = RAIZ / "docs" / "guia_temas.md"
ARCHIVO_AMPLIADO = Path("eval") / "etiquetas_ampliadas.csv"     # C-12: salida de --incorporar-hoja
SIN_TEMA = "sin_tema"       # convención de la hoja de confirmación (D-87) para un titular que una persona marcó como ruido
CAMPOS_HOJA = (
    "id_noticia", "titulo", "tema_humano", "ruido_humano", "tema_secundario", "grupo", "alcance_regional", "nota",
    "etiquetado_por", "fecha_etiquetado",
)
FORMATO_DIA = "%Y-%m-%d"    # la hoja fecha la decisión con el día; el consolidado la guarda en ISO 8601 UTC con Z
DECIMALES = 3  # presentación de los reportes, no un parámetro de decisión

Fila = dict[str, str]


class ErrorEtiquetado(ValueError):
    """Dato de etiquetado inválido (nombre, fila o archivo)."""


# ------------------------------------------------------------------ nombres


def plano(texto: str) -> str:
    """Minúsculas y sin tildes."""
    sin_marcas = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return sin_marcas.casefold()


def validar_nombre(nombre: str, cfg: ConfigEtiquetado) -> str:
    """Nombre normalizado de una persona. Rechaza vacíos, números y marcadores de IA (ver ``nombres.marcadores_ia``)."""
    limpio = re.sub(r"\s+", " ", unicodedata.normalize("NFC", nombre or "")).strip()
    if len(limpio) < cfg.nombres.longitud_minima or not PATRON_NOMBRE.match(limpio):
        raise ErrorEtiquetado(f"nombre inválido {limpio!r}: use el nombre de una persona (solo letras, mínimo {cfg.nombres.longitud_minima})")
    palabras = set(re.findall(r"[^\W\d_]+", plano(limpio)))
    marcadores = palabras & {plano(m) for m in cfg.nombres.marcadores_ia}
    if plano(limpio) in {plano(m) for m in cfg.nombres.marcadores_ia_nombre_completo}:  # solo el nombre completo: "Ai Lin" pasa
        marcadores.add(plano(limpio))
    if marcadores:
        raise ErrorEtiquetado(f"nombre inválido {limpio!r}: las etiquetas las ponen personas, no herramientas ({sorted(marcadores)})")
    return limpio


def slug_nombre(nombre: str) -> str:
    """Nombre de archivo de la hoja de una persona."""
    return re.sub(r"[^a-z0-9]+", "_", plano(nombre)).strip("_")


def normalizar_grupo(texto: str) -> str:
    """Grupo en minúsculas sin tildes, con guiones (``Sismo Chiriquí`` -> ``sismo-chiriqui``). Vacío = titular suelto."""
    return re.sub(r"[^a-z0-9]+", "-", plano(texto)).strip("-")


# ------------------------------------------------------------------ muestra


def cargar_excluidos(ruta: Path) -> set[str]:
    """IDs de ``ejemplos_excluidos.txt``: nunca entran en la evaluación."""
    ids: set[str] = set()
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.startswith("#"):
            ids.add(linea.split("\t", 1)[0].strip())
    return ids


def leer_noticias(ruta_base: Path) -> list[dict[str, Any]]:
    """Campos de las noticias. La descripción del RSS no se lee (D-31). ``es_ruido`` sirve solo para estratificar:
    la interfaz no lo muestra (no sesgar a la persona). Falla si la limpieza (E1-03b) no se ha corrido."""
    con = db.conectar(ruta_base, solo_lectura=True)
    try:
        cur = con.execute(
            "SELECT id_noticia, titulo, medio, url, fecha_publicacion, fecha_deteccion, es_ruido FROM noticias ORDER BY id_noticia"
        )
        nombres = [d[0] for d in cur.description]
        filas = [dict(zip(nombres, f, strict=True)) for f in cur.fetchall()]
    finally:
        con.close()
    if any(f["es_ruido"] is None for f in filas):
        raise ErrorEtiquetado("la base no tiene la marca de ruido: ejecute `poetry run python -m src.limpieza` primero")
    return filas


ESTRATOS = ("no_ruido", "ruido")


def _cuotas(poblacion: dict[str, int], cfg: ConfigEtiquetado) -> dict[str, int]:
    """Tamaño de muestra por estrato: la cuota, o todo el estrato si es menor; el faltante pasa al otro estrato."""
    e = cfg.muestra.estratos
    cuota = {"no_ruido": e.no_ruido.cuota, "ruido": e.ruido.cuota}
    n = {k: min(cuota[k], poblacion[k]) for k in ESTRATOS}
    falta = cfg.muestra.tamano - sum(n.values())
    for k in ESTRATOS:
        extra = min(falta, poblacion[k] - n[k])
        n[k] += extra
        falta -= extra
    return n


def construir_muestra(noticias: list[dict[str, Any]], excluidos: set[str], cfg: ConfigEtiquetado) -> list[dict[str, Any]]:
    """Muestra estratificada y reproducible (mismas noticias y semilla = misma lista y orden).

    Estratos según el filtro automático (``es_ruido``; el alcance regional cuenta como no ruido). Dentro de cada
    estrato la selección es aleatoria. Cada fila lleva ``estrato``, ``poblacion`` (noticias elegibles del estrato),
    ``n_estrato`` y ``peso`` = población / muestra, para reponderar las métricas a la población. Los ``dobles``
    de cada estrato (los etiquetan dos personas) van primero; ``doble`` marca esos titulares. Excluye los ejemplos
    de ``temas.yaml``.
    """
    elegibles = sorted((n for n in noticias if n["id_noticia"] not in excluidos), key=lambda n: n["id_noticia"])
    por_estrato = {
        "no_ruido": [n for n in elegibles if not n["es_ruido"]],
        "ruido": [n for n in elegibles if n["es_ruido"]],
    }
    poblacion = {k: len(v) for k, v in por_estrato.items()}
    tamanos = _cuotas(poblacion, cfg)
    rng = random.Random(cfg.muestra.semilla)
    dobles_cfg = {"no_ruido": cfg.muestra.estratos.no_ruido.dobles, "ruido": cfg.muestra.estratos.ruido.dobles}
    dobles: list[dict[str, Any]] = []
    resto: list[dict[str, Any]] = []
    for k in ESTRATOS:
        elegidas = rng.sample(por_estrato[k], tamanos[k])
        for pos, n in enumerate(elegidas):
            fila = {**n, "estrato": k, "poblacion": poblacion[k], "n_estrato": tamanos[k], "peso": poblacion[k] / tamanos[k],
                    "doble": pos < dobles_cfg[k]}
            (dobles if fila["doble"] else resto).append(fila)
    rng.shuffle(dobles)
    rng.shuffle(resto)
    return [{**m, "orden": i + 1} for i, m in enumerate(dobles + resto)]


def n_efectivo(muestra: list[dict[str, Any]]) -> float:
    """n efectivo de Kish de la muestra ponderada: (suma de pesos)^2 / suma de pesos^2."""
    pesos = [m["peso"] for m in muestra]
    return sum(pesos) ** 2 / sum(p * p for p in pesos) if pesos else 0.0


def composicion(muestra: list[dict[str, Any]]) -> list[str]:
    """Líneas legibles: composición por estrato, pesos, dobles y n efectivo."""
    lineas = []
    for k in ESTRATOS:
        m = [x for x in muestra if x["estrato"] == k]
        if m:
            lineas.append(
                f"{k}: población {m[0]['poblacion']} · muestra {len(m)} (dobles {sum(x['doble'] for x in m)}) · peso {m[0]['peso']:.3f}"
            )
    lineas.append(f"n efectivo de Kish con pesos = {n_efectivo(muestra):.1f} de {len(muestra)}")
    return lineas


def asignadas(muestra: list[dict[str, Any]], parte: int, partes: int) -> list[dict[str, Any]]:
    """Titulares de la persona ``parte`` de ``partes``: todos los dobles más su porción de los demás (por posición)."""
    if not 1 <= parte <= partes:
        raise ErrorEtiquetado(f"parte {parte} fuera de 1..{partes}")
    simples = [m for m in muestra if not m["doble"]]
    mias = {m["id_noticia"] for i, m in enumerate(simples) if i % partes == parte - 1}
    return [m for m in muestra if m["doble"] or m["id_noticia"] in mias]


# ------------------------------------------------------------------ validación de filas


def temas_validos(temas: ConfigTemas) -> list[str]:
    return list(temas.temas)


def validar_fila(fila: Fila, cfg: ConfigEtiquetado, temas: ConfigTemas) -> list[str]:
    """Errores de una etiqueta (lista vacía = válida)."""
    e: list[str] = []
    ruido, principal, secundario = fila.get("ruido", ""), fila.get("tema_principal", ""), fila.get("tema_secundario", "")
    validos = temas_validos(temas)
    if not fila.get("id_noticia"):
        e.append("falta id_noticia")
    if ruido != cfg.ruido.sin_ruido and ruido not in cfg.ruido.motivos:
        e.append(f"ruido {ruido!r} no es {cfg.ruido.sin_ruido!r} ni {cfg.ruido.motivos}")
    elif ruido == cfg.ruido.sin_ruido:
        if principal not in validos:
            e.append(f"tema_principal {principal!r} debe ser uno de {validos}")
        if secundario and secundario not in validos:
            e.append(f"tema_secundario {secundario!r} debe ser vacío o uno de {validos}")
        if secundario and secundario == principal:
            e.append("tema_secundario no puede repetir el principal")
    else:
        if principal or secundario:
            e.append("un titular de ruido no lleva tema principal ni secundario")
        if fila.get("grupo"):
            e.append("un titular de ruido no lleva grupo")
    if fila.get("alcance_regional", "") not in ("", SI):
        e.append(f"alcance_regional {fila.get('alcance_regional')!r} debe ser vacío o {SI!r}")
    if fila.get("alcance_regional") and ruido != cfg.ruido.sin_ruido:
        e.append("alcance_regional (D-84) solo aplica a un titular que no es ruido")
    grupo = fila.get("grupo", "")
    if grupo and not PATRON_GRUPO.match(grupo):
        e.append(f"grupo {grupo!r}: use minúsculas, dígitos y guiones (ej. sismo-chiriqui)")
    for persona in fila.get("etiquetado_por", "").split("; "):  # el consolidado une a quienes coinciden con "; "
        try:
            validar_nombre(persona, cfg)
        except ErrorEtiquetado as exc:
            e.append(str(exc))
    try:
        datetime.strptime(fila.get("fecha_etiquetado", ""), cargar_normalizacion().fechas.formato_salida)
    except ValueError:
        e.append(f"fecha_etiquetado {fila.get('fecha_etiquetado')!r} no es ISO 8601 UTC con Z")
    return e


# ------------------------------------------------------------------ CSV


def leer_csv(ruta: Path) -> list[Fila]:
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "") for k, v in fila.items()} for fila in csv.DictReader(f)]


def escribir_csv(ruta: Path, filas: list[Fila], columnas: tuple[str, ...] = COLUMNAS) -> None:
    """Escritura atómica (archivo temporal y renombrado): una caída no deja el CSV a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with temporal.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    os.replace(temporal, ruta)


def ruta_persona(nombre: str, cfg: ConfigEtiquetado, raiz: Path = RAIZ) -> Path:
    return raiz / cfg.archivos.carpeta_personas / f"{slug_nombre(nombre)}.csv"


def guardar_etiqueta(
    ruta: Path, cfg: ConfigEtiquetado, temas: ConfigTemas, noticia: dict[str, Any], datos: dict[str, str], nombre: str
) -> Fila:
    """Valida y guarda (o reemplaza) la etiqueta de ``nombre`` sobre ``noticia`` en su hoja. Devuelve la fila."""
    fila: Fila = {
        "id_noticia": noticia["id_noticia"],
        "titulo": noticia["titulo"],
        "tema_principal": datos.get("tema_principal", ""),
        "tema_secundario": datos.get("tema_secundario", ""),
        "ruido": datos.get("ruido", ""),
        "grupo": normalizar_grupo(datos.get("grupo", "")),
        "alcance_regional": SI if datos.get("alcance_regional") in (True, SI) else "",
        "nota": re.sub(r"\s+", " ", datos.get("nota", "")).strip(),
        "etiquetado_por": validar_nombre(nombre, cfg),
        "fecha_etiquetado": datetime.now(UTC).strftime(cargar_normalizacion().fechas.formato_salida),
    }
    errores = validar_fila(fila, cfg, temas)
    if errores:
        raise ErrorEtiquetado("; ".join(errores))
    existentes = [f for f in leer_csv(ruta) if f["id_noticia"] != fila["id_noticia"]]
    escribir_csv(ruta, [*existentes, fila])
    return fila


def leer_hojas(raiz: Path, cfg: ConfigEtiquetado) -> dict[str, list[Fila]]:
    """``etiquetado_por -> filas`` de todas las hojas de ``eval/etiquetas/``."""
    carpeta = raiz / cfg.archivos.carpeta_personas
    hojas: dict[str, list[Fila]] = {}
    for ruta in sorted(carpeta.glob("*.csv")):
        filas = leer_csv(ruta)
        if filas:
            hojas[filas[0]["etiquetado_por"]] = filas
    return hojas


def validar_hoja(ruta: Path, cfg: ConfigEtiquetado, temas: ConfigTemas, ids_muestra: set[str] | None = None) -> list[str]:
    """Problemas de una hoja o del consolidado (lista vacía = válida)."""
    problemas: list[str] = []
    with ruta.open(encoding="utf-8", newline="") as f:
        campos = tuple(csv.DictReader(f).fieldnames or ())
    if campos not in (COLUMNAS, COLUMNAS_CONSOLIDADO):
        return [f"{ruta.name}: columnas {campos} no son las esperadas {COLUMNAS}"]
    # Las filas ``asistente_provisional`` (D-101) no son de una persona ni de la muestra de E1-06: su contrato es otro y lo
    # valida ``eval/origen_etiquetas.py``. Aquí solo se validan las humanas.
    filas = [f for f in leer_csv(ruta) if oe.normalizar_origen(f.get(oe.COLUMNA_ORIGEN)) != oe.ASISTENTE_PROVISIONAL]
    vistos: Counter[str] = Counter(f["id_noticia"] for f in filas)
    for i, fila in enumerate(filas, start=2):
        problemas += [f"{ruta.name}:{i} ({fila['id_noticia']}): {m}" for m in validar_fila(fila, cfg, temas)]
        if ids_muestra is not None and fila["id_noticia"] not in ids_muestra:
            problemas.append(f"{ruta.name}:{i}: {fila['id_noticia']} no está en la muestra (ni excluido ni inexistente)")
    problemas += [f"{ruta.name}: id repetido {i} ({n} filas)" for i, n in vistos.items() if n > 1]
    if campos == COLUMNAS and ruta.parent.name == Path(cfg.archivos.carpeta_personas).name:
        personas = {f["etiquetado_por"] for f in filas}
        if len(personas) > 1 or any(slug_nombre(p) != ruta.stem for p in personas):
            problemas.append(f"{ruta.name}: una hoja es de una sola persona y se llama como ella ({sorted(personas)})")
    return problemas


# ------------------------------------------------------------------ acuerdo (kappa de Cohen)


def kappa_cohen(a: list[str], b: list[str]) -> float | None:
    """Kappa de Cohen entre dos listas de categorías alineadas. ``None`` si no está definido (sin datos o pe = 1 con po < 1)."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[c] * cb[c] for c in ca.keys() | cb.keys()) / (n * n)
    if pe == 1:
        return 1.0 if po == 1 else None
    return (po - pe) / (1 - pe)


def categoria(fila: Fila, cfg: ConfigEtiquetado) -> str:
    """Categoría de clasificación: el tema principal o, si es ruido, su motivo."""
    return fila["tema_principal"] if fila["ruido"] == cfg.ruido.sin_ruido else fila["ruido"]


def _pares_mismo_grupo(filas: list[Fila], ids: list[str]) -> list[str]:
    por_id = {f["id_noticia"]: f["grupo"] for f in filas}
    return ["si" if por_id[i] and por_id[i] == por_id[j] else "no" for i, j in itertools.combinations(ids, 2)]


def _proporcion(k: int, n: int, z: float) -> dict[str, Any]:
    ic = intervalo_wilson(k, n, z)
    return {
        "n": k,
        "de": n,
        "proporcion": None if n == 0 else round(k / n, DECIMALES),
        "ic95": None if ic is None else [round(ic[0], DECIMALES), round(ic[1], DECIMALES)],
    }


def acuerdo(hojas: dict[str, list[Fila]], cfg: ConfigEtiquetado) -> list[dict[str, Any]]:
    """Acuerdo entre cada par de personas sobre los titulares que etiquetaron ambas.

    Por par: kappa de la categoría (tema o motivo de ruido), kappa del ruido y kappa de los pares de titulares
    "mismo grupo / distinto grupo" (los nombres de grupo de cada persona no se comparan: solo qué titulares juntó).
    El acuerdo observado lleva su n e intervalo de Wilson al 95 %.
    """
    z = cargar_carga().salida.z_intervalo_confianza
    resultado = []
    for p, q in itertools.combinations(sorted(hojas), 2):
        fa = {f["id_noticia"]: f for f in hojas[p]}
        fb = {f["id_noticia"]: f for f in hojas[q]}
        ids = sorted(fa.keys() & fb.keys())
        cat_a, cat_b = [categoria(fa[i], cfg) for i in ids], [categoria(fb[i], cfg) for i in ids]
        rui_a, rui_b = [fa[i]["ruido"] for i in ids], [fb[i]["ruido"] for i in ids]
        gr_a, gr_b = _pares_mismo_grupo([fa[i] for i in ids], ids), _pares_mismo_grupo([fb[i] for i in ids], ids)
        k_cat = kappa_cohen(cat_a, cat_b)
        resultado.append(
            {
                "personas": [p, q],
                "n_comunes": len(ids),
                "esperados": cfg.muestra.tamano_acuerdo,
                "kappa_categoria": k_cat,
                "kappa_ruido": kappa_cohen(rui_a, rui_b),
                "kappa_pares_grupo": kappa_cohen(gr_a, gr_b),
                "acuerdo_categoria": _proporcion(sum(x == y for x, y in zip(cat_a, cat_b, strict=True)), len(ids), z),
                "desacuerdos": [i for i, x, y in zip(ids, cat_a, cat_b, strict=True) if x != y],
                "bajo": k_cat is None or k_cat < cfg.acuerdo.kappa_minimo,
            }
        )
    return resultado


def texto_acuerdo(resultados: list[dict[str, Any]], cfg: ConfigEtiquetado) -> list[str]:
    """Líneas legibles del acuerdo; avisa si es bajo (D-71)."""
    if not resultados:
        return ["SIN ACUERDO: se necesitan al menos dos hojas con titulares en común (aún no hay dos personas)."]
    f = lambda v: "no definido" if v is None else f"{v:.{DECIMALES}f}"  # noqa: E731
    lineas = []
    for r in resultados:
        a = r["acuerdo_categoria"]
        ic = "—" if a["ic95"] is None else f"{a['ic95'][0]}–{a['ic95'][1]}"
        lineas += [
            f"{r['personas'][0]} y {r['personas'][1]}: {r['n_comunes']} titulares en común (se esperan {r['esperados']})",
            f"  kappa categoría = {f(r['kappa_categoria'])} · kappa ruido = {f(r['kappa_ruido'])} · kappa pares de grupo = {f(r['kappa_pares_grupo'])}",
            f"  acuerdo observado de categoría: {a['n']}/{a['de']} = {a['proporcion']} [IC 95 %: {ic}]",
            f"  desacuerdos: {', '.join(r['desacuerdos']) or 'ninguno'}",
        ]
        if r["n_comunes"] < r["esperados"]:
            lineas.append(f"  INCOMPLETO: faltan {r['esperados'] - r['n_comunes']} titulares dobles.")
        if r["bajo"]:
            lineas.append(f"  ACUERDO BAJO (kappa < {cfg.acuerdo.kappa_minimo}): revisar docs/guia_temas.md antes de usar las etiquetas (D-71).")
    return lineas


# ------------------------------------------------------------------ consolidación, disputas y grupos


def _por_id(hojas: dict[str, list[Fila]]) -> dict[str, list[Fila]]:
    por_id: dict[str, list[Fila]] = {}
    for nombre in sorted(hojas):
        for f in hojas[nombre]:
            por_id.setdefault(f["id_noticia"], []).append(f)
    return por_id


def _veredicto(filas: list[Fila]) -> list[Fila] | None:
    """Etiquetas ganadoras de un titular: mayoría absoluta en (ruido, tema_principal); ``None`` si está en disputa."""
    conteo = Counter((f["ruido"], f["tema_principal"]) for f in filas)
    clave, votos = conteo.most_common(1)[0]
    if votos * 2 <= len(filas):
        return None
    return [f for f in filas if (f["ruido"], f["tema_principal"]) == clave]


def en_disputa(hojas: dict[str, list[Fila]]) -> dict[str, list[str]]:
    """``id_noticia -> personas que ya lo etiquetaron`` de los titulares sin mayoría (necesitan una tercera persona)."""
    return {
        i: sorted(f["etiquetado_por"] for f in filas)
        for i, filas in sorted(_por_id(hojas).items())
        if len(filas) > 1 and _veredicto(filas) is None
    }


def consolidar(
    hojas: dict[str, list[Fila]], cfg: ConfigEtiquetado, muestra: list[dict[str, Any]] | None = None
) -> tuple[list[Fila], list[str]]:
    """Una fila por titular. Un titular con varias personas se acepta si la mayoría absoluta coincide en
    ``ruido`` y ``tema_principal``; si no (p. ej. 2 personas en desacuerdo) queda **en disputa** y se excluye hasta
    que una tercera persona lo etiquete (``--desempate``). De las personas que coinciden, el secundario, el grupo y
    el alcance regional son los de la primera (orden alfabético); el secundario y el alcance regional solo se
    conservan si todas coinciden. Con ``muestra`` agrega ``estrato`` y ``peso_muestreo``.

    Devuelve ``(filas, ids_en_disputa)``; quien llama debe informar las disputas, nunca callarlas.
    """
    info = {m["id_noticia"]: m for m in muestra or []}
    finales: list[Fila] = []
    disputas: list[str] = []
    for id_noticia, filas in sorted(_por_id(hojas).items()):
        ganadoras = _veredicto(filas)
        if ganadoras is None:
            disputas.append(id_noticia)
            continue
        base = dict(ganadoras[0])
        if len({f["tema_secundario"] for f in ganadoras}) > 1:
            base["tema_secundario"] = ""
        if len({f["alcance_regional"] for f in ganadoras}) > 1:
            base["alcance_regional"] = ""
        base["etiquetado_por"] = "; ".join(f["etiquetado_por"] for f in ganadoras)
        base["fecha_etiquetado"] = max(f["fecha_etiquetado"] for f in ganadoras)
        base["n_etiquetadores"] = str(len(ganadoras))
        base[oe.COLUMNA_ORIGEN] = oe.HUMANO
        m = info.get(id_noticia)
        base["estrato"] = m["estrato"] if m else ""
        base["peso_muestreo"] = f"{m['peso']:.6g}" if m else ""
        finales.append(base)
    return finales, disputas


def cargar_etiquetas_finales(ruta: Path) -> dict[str, Fila]:
    """``id_noticia -> fila`` del consolidado (la entrada de E1-07, E1-08 y ``eval.ruido``)."""
    return {f["id_noticia"]: f for f in leer_csv(ruta)}


def grupos_usados(hojas: dict[str, list[Fila]]) -> dict[str, list[tuple[str, str, str]]]:
    """``grupo -> [(id_noticia, titulo, persona)]`` de todas las hojas, para conciliar nombres antes de consolidar."""
    grupos: dict[str, list[tuple[str, str, str]]] = {}
    for nombre in sorted(hojas):
        for f in hojas[nombre]:
            if f["grupo"]:
                grupos.setdefault(f["grupo"], []).append((f["id_noticia"], f["titulo"], nombre))
    return dict(sorted(grupos.items()))


def texto_grupos(hojas: dict[str, list[Fila]]) -> list[str]:
    """Líneas legibles de ``--grupos``: cada grupo con sus titulares y quién lo usó."""
    grupos = grupos_usados(hojas)
    if not grupos:
        return ["SIN GRUPOS: ninguna hoja tiene titulares agrupados."]
    lineas = [f"{len(grupos)} grupos. Si dos nombres cuentan el mismo hecho, unifíquelos con --renombrar VIEJO NUEVO --persona NOMBRE.", ""]
    for g, miembros in grupos.items():
        personas = sorted({p for _, _, p in miembros})
        aviso = "  (UN SOLO TITULAR: ¿va suelto?)" if len(miembros) == 1 else ""
        lineas.append(f"[{g}] {len(miembros)} titulares · {', '.join(personas)}{aviso}")
        lineas += [f"    {i} · {t[:110]} ({p})" for i, t, p in miembros]
    return lineas


def renombrar_grupo(ruta: Path, viejo: str, nuevo: str) -> int:
    """Cambia el nombre de un grupo en una hoja. Devuelve cuántos titulares cambió."""
    nuevo_n = normalizar_grupo(nuevo)
    if not nuevo_n:
        raise ErrorEtiquetado("el nombre nuevo del grupo está vacío")
    filas = leer_csv(ruta)
    n = 0
    for f in filas:
        if f["grupo"] == viejo:
            f["grupo"], n = nuevo_n, n + 1
    if n:
        escribir_csv(ruta, filas)
    return n


# ------------------------------------------------------------------ conjunto ampliado (C-12)


def _fecha_consolidada(texto: str) -> str:
    """Una fecha de la hoja (``AAAA-MM-DD``) pasa a ISO 8601 UTC a medianoche; una que ya es ISO con Z se conserva; otra, tal cual."""
    formato = cargar_normalizacion().fechas.formato_salida
    for f in (formato, FORMATO_DIA):
        try:
            return datetime.strptime(texto, f).strftime(formato)
        except ValueError:
            continue
    return texto


def _fila_de_la_hoja(h: Fila, cfg: ConfigEtiquetado, ampliado: ConjuntoAmpliado) -> Fila:
    """Una fila decidida de la hoja, con las columnas del consolidado (la convención ``sin_tema`` pasa a ``ruido`` + tema vacío)."""
    limpia = {k: re.sub(r"\s+", " ", h.get(k, "")).strip() for k in CAMPOS_HOJA}
    ruido = limpia["ruido_humano"]
    return {
        "id_noticia": limpia["id_noticia"],
        "titulo": h.get("titulo", ""),
        "tema_principal": "" if ruido or limpia["tema_humano"] == SIN_TEMA else limpia["tema_humano"],
        "tema_secundario": limpia["tema_secundario"],
        "ruido": ruido or cfg.ruido.sin_ruido,
        "grupo": limpia["grupo"],
        "alcance_regional": limpia["alcance_regional"],
        "nota": limpia["nota"],
        "etiquetado_por": limpia["etiquetado_por"],
        "fecha_etiquetado": _fecha_consolidada(limpia["fecha_etiquetado"]),
        "estrato": ampliado.estrato_hoja,
        "peso_muestreo": "",      # sin peso propio: no salen de la muestra estratificada (los lectores le dan 1; ver docs/etiquetado.md)
        "n_etiquetadores": str(ampliado.n_etiquetadores_hoja),
        oe.COLUMNA_ORIGEN: oe.HUMANO,
    }


def incorporar_hoja(
    ruta_hoja: Path,
    ruta_etiquetas: Path,
    cfg: ConfigEtiquetado,
    temas: ConfigTemas,
    ampliado: ConjuntoAmpliado,
    avisos: list[str] | None = None,
) -> list[Fila]:
    """Filas de ``eval/etiquetas_ampliadas.csv``: las ``origen = humano`` de ``ruta_etiquetas`` y, detrás, las de la hoja.

    Todo o nada: cada fila de la hoja debe estar decidida (``tema_humano``, ``etiquetado_por`` y fecha ISO) y ser válida según
    ``validar_fila`` (D-87); si una no lo es, se lanza ``ErrorEtiquetado`` con TODOS los problemas y no se devuelve nada. Las
    ``asistente_provisional`` de ``ruta_etiquetas`` nunca entran: una provisional solo aparece si la hoja la decidió. Las filas
    nuevas van ordenadas por ``id_noticia`` (la salida no depende del orden de la hoja). No escribe ni modifica nada.

    Un titular de ruido no lleva grupo en el consolidado (``validar_fila``): si la hoja le puso uno, se descarta y se deja
    constancia en ``avisos`` (no se calla ni se rechaza toda la hoja por eso).
    """
    with ruta_hoja.open(encoding="utf-8", newline="") as f:
        campos = tuple(csv.DictReader(f).fieldnames or ())
    faltan = [c for c in CAMPOS_HOJA if c not in campos]
    if faltan:
        raise ErrorEtiquetado(f"{ruta_hoja.name}: faltan las columnas {faltan}")
    hoja = leer_csv(ruta_hoja)
    if not hoja:
        raise ErrorEtiquetado(f"{ruta_hoja.name}: no tiene filas")
    humanas = [{c: f.get(c, "") or "" for c in COLUMNAS_CONSOLIDADO} for f in oe.leer_filas(ruta_etiquetas, oe.SOLO_HUMANOS)]
    ids_humanos = {f["id_noticia"] for f in humanas}
    vistos: Counter[str] = Counter(h["id_noticia"].strip() for h in hoja)
    problemas: list[str] = []
    nuevas: list[Fila] = []
    for n, h in enumerate(hoja, start=2):
        i = h["id_noticia"].strip() or "?"
        errores: list[str] = []
        tema, ruido = h["tema_humano"].strip(), h["ruido_humano"].strip()
        if not tema:
            errores.append("sin decidir (tema_humano vacío)")
        elif ruido and tema != SIN_TEMA:
            errores.append(f"con ruido {ruido!r} el tema_humano es {SIN_TEMA!r} (D-87), no {tema!r}")
        elif not ruido and tema == SIN_TEMA:
            errores.append(f"{SIN_TEMA!r} sin motivo de ruido (ruido_humano vacío)")
        if vistos[h["id_noticia"].strip()] > 1:
            errores.append("id repetido en la hoja")
        if i in ids_humanos:
            errores.append("ya tiene una etiqueta humana en el archivo base")
        fila = _fila_de_la_hoja(h, cfg, ampliado)
        if ruido and fila["grupo"]:
            if avisos is not None:
                avisos.append(f"{ruta_hoja.name}:{n} ({i}): titular de ruido con grupo {fila['grupo']!r}: el grupo se descarta (un ruido no lleva grupo)")
            fila["grupo"] = ""
        errores += [m for m in validar_fila(fila, cfg, temas) if not (not tema and "tema_principal" in m)]
        problemas += [f"{ruta_hoja.name}:{n} ({i}): {m}" for m in errores]
        nuevas.append(fila)
    if problemas:
        raise ErrorEtiquetado("\n".join(problemas))
    return [*humanas, *sorted(nuevas, key=lambda f: f["id_noticia"])]


# ------------------------------------------------------------------ CLI


def _base_por_defecto() -> Path:
    return RAIZ / "data" / cargar_normalizacion().salida.base_de_datos


def muestra_desde_base(ruta_base: Path, cfg: ConfigEtiquetado) -> list[dict[str, Any]]:
    excluidos = cargar_excluidos(RAIZ / cfg.archivos.ejemplos_excluidos)
    return construir_muestra(leer_noticias(ruta_base), excluidos, cfg)


def _texto_disputas(disputas: dict[str, list[str]], titulos: dict[str, str]) -> list[str]:
    return [f"  {i} · {titulos.get(i, '')[:100]} (etiquetaron: {', '.join(p)})" for i, p in disputas.items()]


def _incorporar_hoja_cli(args: argparse.Namespace, cfg: ConfigEtiquetado, temas: ConfigTemas) -> int:
    """``--incorporar-hoja``: valida la hoja y escribe el conjunto ampliado. No comprueba la muestra de E1-06 (ver docs/etiquetado.md)."""
    if args.hoja is None:
        print("--incorporar-hoja necesita --hoja RUTA", file=sys.stderr)
        return 1
    consolidado = args.raiz / cfg.archivos.consolidado
    etiquetas = args.etiquetas or consolidado
    salida = args.salida or args.raiz / ARCHIVO_AMPLIADO
    protegidos = {p.resolve() for p in (consolidado, etiquetas, args.hoja)}
    if salida.resolve() in protegidos:
        print(f"Se niega a escribir sobre {salida}: la salida no puede ser el consolidado, la base ni la hoja.", file=sys.stderr)
        return 1
    for ruta in (args.hoja, etiquetas):
        if not ruta.exists():
            print(f"No existe {ruta}", file=sys.stderr)
            return 1
    avisos: list[str] = []
    try:
        filas = incorporar_hoja(args.hoja, etiquetas, cfg, temas, cargar_clasificacion().ampliado, avisos)
    except (ErrorEtiquetado, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        print("No se escribió nada: corrija la hoja y vuelva a correr --incorporar-hoja.", file=sys.stderr)
        return 1
    escribir_csv(salida, filas, COLUMNAS_CONSOLIDADO)
    for aviso in avisos:
        print(f"AVISO: {aviso}", file=sys.stderr)
    nuevas = sum(1 for f in filas if f["estrato"] == cargar_clasificacion().ampliado.estrato_hoja)
    print(f"Escrito {salida}: {len(filas)} titulares humanos ({len(filas) - nuevas} de {etiquetas.name} + {nuevas} de la hoja)")
    print("AVISO: las filas de la hoja no vienen de la muestra estratificada y no llevan peso_muestreo: no se mezclan en estimaciones ponderadas.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E1-06: etiquetado humano (la interfaz es `streamlit run eval/etiquetar.py`)")
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--muestra", action="store_true", help="imprime la composición y la muestra (id, orden, doble, estrato)")
    modo.add_argument("--validar", action="store_true", help="valida las hojas por persona y el consolidado")
    modo.add_argument("--acuerdo", action="store_true", help="kappa de Cohen sobre los titulares dobles")
    modo.add_argument("--grupos", action="store_true", help="lista los grupos usados en todas las hojas, con sus titulares")
    modo.add_argument("--renombrar", nargs=2, metavar=("VIEJO", "NUEVO"), help="renombra un grupo en la hoja de --persona")
    modo.add_argument("--desempate", action="store_true", help="lista los titulares en disputa (los etiqueta una tercera persona en la interfaz)")
    modo.add_argument("--consolidar", action="store_true", help="escribe eval/etiquetas.csv")
    modo.add_argument("--incorporar-hoja", action="store_true", help="C-12: escribe eval/etiquetas_ampliadas.csv = humanas + filas decididas de --hoja")
    parser.add_argument("--hoja", type=Path, help="con --incorporar-hoja: CSV con las decisiones de una persona (obligatorio)")
    parser.add_argument("--etiquetas", type=Path, help="con --incorporar-hoja: consolidado base (por defecto eval/etiquetas.csv)")
    parser.add_argument("--salida", type=Path, help=f"con --incorporar-hoja: archivo a escribir (por defecto {ARCHIVO_AMPLIADO})")
    parser.add_argument("--persona", help="con --renombrar: nombre de la persona dueña de la hoja")
    parser.add_argument("--base", type=Path, default=_base_por_defecto())
    parser.add_argument("--raiz", type=Path, default=RAIZ, help="carpeta que contiene eval/etiquetas (por defecto, el repo)")
    parser.add_argument("--forzar", action="store_true", help="con --consolidar: escribir aunque el acuerdo sea bajo o falte")
    args = parser.parse_args(argv)
    cfg, temas = cargar_etiquetado(), cargar_temas()

    if args.muestra:
        if not args.base.exists():
            print(f"No existe {args.base}: ejecute `poetry run python -m src.normalizacion` y luego `python -m src.limpieza`.", file=sys.stderr)
            return 1
        try:
            muestra = muestra_desde_base(args.base, cfg)
        except ErrorEtiquetado as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"# semilla {cfg.muestra.semilla} · n = {len(muestra)} · dobles = {sum(m['doble'] for m in muestra)}")
        print("\n".join(f"# {linea}" for linea in composicion(muestra)))
        print("orden\tdoble\testrato\tpeso\tid_noticia\tmedio")
        for m in muestra:
            print(f"{m['orden']}\t{'si' if m['doble'] else 'no'}\t{m['estrato']}\t{m['peso']:.3f}\t{m['id_noticia']}\t{m['medio']}")
        return 0

    if args.incorporar_hoja:
        return _incorporar_hoja_cli(args, cfg, temas)

    carpeta_hojas = args.raiz / cfg.archivos.carpeta_personas
    if args.renombrar:
        if not args.persona:
            print("--renombrar necesita --persona NOMBRE", file=sys.stderr)
            return 1
        ruta = ruta_persona(args.persona, cfg, args.raiz)
        if not ruta.exists():
            print(f"No existe la hoja {ruta}", file=sys.stderr)
            return 1
        try:
            n = renombrar_grupo(ruta, args.renombrar[0], args.renombrar[1])
        except ErrorEtiquetado as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"{n} titulares pasaron de {args.renombrar[0]!r} a {normalizar_grupo(args.renombrar[1])!r} en {ruta.name}")
        return 0 if n else 1

    hojas_en_disco = sorted(carpeta_hojas.glob("*.csv"))
    try:
        muestra_completa = muestra_desde_base(args.base, cfg) if args.base.exists() else None
    except ErrorEtiquetado as exc:
        print(str(exc), file=sys.stderr)
        return 1
    ids_muestra = {m["id_noticia"] for m in muestra_completa} if muestra_completa is not None else None
    problemas: list[str] = []
    for ruta in hojas_en_disco:
        problemas += validar_hoja(ruta, cfg, temas, ids_muestra)
    consolidado = args.raiz / cfg.archivos.consolidado
    if args.validar:
        if consolidado.exists():
            problemas += validar_hoja(consolidado, cfg, temas, ids_muestra)
        if ids_muestra is None:
            print("AVISO: sin base de datos, no se comprueba que los IDs estén en la muestra.", file=sys.stderr)
        if not hojas_en_disco and not consolidado.exists():
            print("SIN ETIQUETAS: no hay hojas en eval/etiquetas/ ni eval/etiquetas.csv.", file=sys.stderr)
            return 2
        for p in problemas:
            print(p, file=sys.stderr)
        print(f"{'ERROR' if problemas else 'OK'}: {len(hojas_en_disco)} hojas, {len(problemas)} problemas")
        return 1 if problemas else 0
    if problemas:
        print("\n".join(problemas), file=sys.stderr)
        print("Corrija las hojas (--validar) antes de continuar.", file=sys.stderr)
        return 1
    hojas = leer_hojas(args.raiz, cfg)
    if not hojas:
        print("SIN ETIQUETAS: no hay hojas en eval/etiquetas/.", file=sys.stderr)
        return 2
    titulos = {f["id_noticia"]: f["titulo"] for filas in hojas.values() for f in filas}
    if args.grupos:
        print("\n".join(texto_grupos(hojas)))
        return 0
    if args.desempate:
        disputas = en_disputa(hojas)
        print(f"{len(disputas)} titulares en disputa (los debe etiquetar una tercera persona: interfaz, opción «Desempate»)")
        print("\n".join(_texto_disputas(disputas, titulos)))
        return 0
    resultados = acuerdo(hojas, cfg)
    if args.acuerdo:
        print("\n".join(texto_acuerdo(resultados, cfg)))
        return 3 if any(r["bajo"] for r in resultados) else 0
    # --consolidar
    print("\n".join(texto_acuerdo(resultados, cfg)))
    if (not resultados or any(r["bajo"] for r in resultados)) and not args.forzar:
        print("NO se escribe eval/etiquetas.csv: acuerdo ausente o bajo (D-71). Use --forzar solo después de revisar la guía.", file=sys.stderr)
        return 3
    if muestra_completa is None:
        print(f"No existe {args.base}: sin la base no se pueden registrar el estrato ni los pesos de muestreo.", file=sys.stderr)
        return 1
    finales, disputas_ids = consolidar(hojas, cfg, muestra_completa)
    provisionales: list[Fila] = []
    if consolidado.exists() and oe.tiene_columna_origen(consolidado):     # las provisionales (D-101) no salen de las hojas: se conservan, nunca se borran en silencio
        provisionales = [f for f in oe.leer_filas(consolidado, (oe.ASISTENTE_PROVISIONAL,)) if f["id_noticia"] not in {x["id_noticia"] for x in finales}]
    escribir_csv(consolidado, [*finales, *provisionales], COLUMNAS_CONSOLIDADO)
    print(f"Escrito {consolidado}: {len(finales)} titulares humanos")
    if provisionales:
        print(f"Se conservaron {len(provisionales)} filas provisionales (D-101) del consolidado anterior: no vienen de las hojas.")
    if disputas_ids:
        todas = en_disputa(hojas)
        print(f"EXCLUIDOS POR DISPUTA: {len(disputas_ids)} titulares (fuera del consolidado hasta que una tercera persona los etiquete con --desempate):")
        print("\n".join(_texto_disputas({i: todas[i] for i in disputas_ids}, titulos)))
    else:
        print("Excluidos por disputa: 0")
    if len(finales) < cfg.muestra.tamano:
        print(f"AVISO: {len(finales)} < {cfg.muestra.tamano} titulares de la muestra.", file=sys.stderr)
    return 0


# ------------------------------------------------------------------ interfaz Streamlit


def _seccion_guia() -> str:
    """Tema y reglas de la guía (única fuente: docs/guia_temas.md), sin la parte de implementación del clasificador."""
    texto = GUIA.read_text(encoding="utf-8")
    return texto.split("## Cómo se clasifica")[0]


def _fecha_panama(iso: str | None, cfg: ConfigEtiquetado) -> str:
    from zoneinfo import ZoneInfo

    if not iso:
        return "sin dato"
    fecha = datetime.strptime(iso, cargar_normalizacion().fechas.formato_salida).replace(tzinfo=UTC)
    return fecha.astimezone(ZoneInfo(cfg.interfaz.zona_horaria)).strftime(cfg.interfaz.formato_fecha) + " (hora de Panamá)"


def grupos_sugeridos(hojas: dict[str, list[Fila]], yo: str, ids_dobles: set[str]) -> list[str]:
    """Grupos ya usados: los míos y los de otras personas, salvo en titulares dobles (para no sesgar el acuerdo)."""
    grupos = {f["grupo"] for f in hojas.get(yo, []) if f["grupo"]}
    for nombre, filas in hojas.items():
        if nombre != yo:
            grupos |= {f["grupo"] for f in filas if f["grupo"] and f["id_noticia"] not in ids_dobles}
    return sorted(grupos)


def interfaz() -> None:  # pragma: no cover - se prueba a mano y con AppTest
    import streamlit as st

    cfg, temas = cargar_etiquetado(), cargar_temas()
    st.set_page_config(page_title="Etiquetado de titulares", layout="wide")
    st.title("Etiquetado de titulares")
    st.caption("Etiqueta con tu criterio y la guía de la izquierda. Esta herramienta no sugiere ninguna respuesta.")

    ruta_base = Path(os.environ.get("HACKIA_BASE", _base_por_defecto()))
    raiz_etq = Path(os.environ.get("HACKIA_RAIZ", RAIZ))  # dónde viven las hojas (inyectable para pruebas)
    if not ruta_base.exists():
        st.error(f"No existe {ruta_base}. Ejecuta `poetry run python -m src.normalizacion` y luego `python -m src.limpieza`.")
        st.stop()

    with st.sidebar:
        st.header("Quién etiqueta")
        nombre_crudo = st.text_input("Tu nombre (persona real)", key="nombre")
        c1, c2 = st.columns(2)
        parte = c1.number_input("Tu parte", min_value=1, value=1, step=1)
        partes = c2.number_input("de cuántas personas", min_value=1, value=2, step=1)
        desempate = st.checkbox(
            "Desempate",
            help="Para una tercera persona: muestra solo los titulares en disputa entre otras dos personas (sin mostrar sus etiquetas).",
        )
        with st.expander("Guía de temas y reglas de frontera", expanded=True):
            st.markdown(_seccion_guia())

    try:
        nombre = validar_nombre(nombre_crudo, cfg)
    except ErrorEtiquetado as exc:
        if nombre_crudo:
            st.sidebar.error(str(exc))
        st.info("Escribe tu nombre en la barra lateral para empezar.")
        st.stop()
    if parte > partes:
        st.error("Tu parte no puede ser mayor que el número de personas.")
        st.stop()

    muestra = muestra_desde_base(ruta_base, cfg)
    ruta = ruta_persona(nombre, cfg, raiz_etq)
    hojas = leer_hojas(raiz_etq, cfg)
    if desempate:
        disputados = en_disputa({k: v for k, v in hojas.items() if k != nombre})
        por_id = {m["id_noticia"]: m for m in muestra}
        mias = [por_id[i] for i in disputados if i in por_id]
        if not mias:
            st.success("No hay titulares en disputa para desempatar.")
            st.stop()
    else:
        mias = asignadas(muestra, int(parte), int(partes))
    hechas = {f["id_noticia"]: f for f in leer_csv(ruta)}
    pendientes = [m for m in mias if m["id_noticia"] not in hechas]
    st.progress((len(mias) - len(pendientes)) / len(mias) if mias else 0.0)
    st.write(f"**{nombre}**: {len(mias) - len(pendientes)} de {len(mias)} titulares etiquetados (hoja `{ruta.name}`).")

    etiquetas_lista = [f"{'✓' if m['id_noticia'] in hechas else '·'} {m['orden']:>3} · {m['titulo'][:90]}" for m in mias]
    por_defecto = mias.index(pendientes[0]) if pendientes else 0
    elegido = st.selectbox("Titular", range(len(mias)), index=por_defecto, format_func=lambda i: etiquetas_lista[i], key=f"sel-{len(pendientes)}")
    noticia = mias[elegido]
    previa = hechas.get(noticia["id_noticia"])
    nid = noticia["id_noticia"]

    st.subheader(f"Titular {noticia['orden']} de {len(muestra)}" + ("  ·  lo etiquetan dos personas por separado" if noticia["doble"] and not desempate else "  ·  desempate" if desempate else ""))
    st.code(noticia["titulo"], language=None, wrap_lines=True)  # texto plano: un titular nunca se interpreta como Markdown/HTML
    st.caption(
        f"Medio: {noticia['medio']} · Publicado: {_fecha_panama(noticia['fecha_publicacion'], cfg)} · "
        f"Detectado: {_fecha_panama(noticia['fecha_deteccion'], cfg)}"
    )
    st.code(noticia["url"], language=None, wrap_lines=True)

    opciones_ruido = [cfg.ruido.sin_ruido, *cfg.ruido.motivos]
    ruido = st.radio(
        "¿Es ruido?",
        opciones_ruido,
        index=opciones_ruido.index(previa["ruido"]) if previa else 0,
        horizontal=True,
        key=f"ruido-{nid}",
        help="no_es_panama: no trata ni afecta a Panamá. fuera_de_temas: es de Panamá pero de un área que el reto no cubre. "
        "no_es_noticia: titular sin contenido (portada, solo el nombre del medio, promoción). "
        "D-84: una nota de la región o de un fenómeno regional que afecta a Panamá NO es ruido: elige ninguno y marca alcance regional.",
    )
    es_ruido = ruido != cfg.ruido.sin_ruido
    lista_temas = list(temas.temas)
    nombre_tema = lambda t: f"{temas.temas[t].nombre} ({t})" if t else "— ninguno —"  # noqa: E731
    principal = secundario = ""
    grupo_final = ""
    regional = False
    if not es_ruido:
        regional = st.checkbox(
            "Alcance regional (D-84)",
            value=bool(previa and previa["alcance_regional"]),
            key=f"reg-{nid}",
            help="Marca si la nota trata de la región (Centroamérica, América Latina, Caribe) o de un fenómeno regional "
            "(El Niño, rutas marítimas) que afecta a Panamá. Sigue siendo una noticia útil, no ruido.",
        )
        c1, c2 = st.columns(2)
        principal = c1.selectbox(
            "Tema principal", lista_temas, index=lista_temas.index(previa["tema_principal"]) if previa and previa["tema_principal"] in lista_temas else 0,
            format_func=nombre_tema, key=f"tp-{nid}",
        )
        sec_opts = ["", *[t for t in lista_temas if t != principal]]
        secundario = c2.selectbox(
            "Tema secundario (opcional)", sec_opts,
            index=sec_opts.index(previa["tema_secundario"]) if previa and previa["tema_secundario"] in sec_opts else 0,
            format_func=nombre_tema, key=f"ts-{nid}",
        )
        ids_dobles = {m["id_noticia"] for m in muestra if m["doble"]}
        existentes = grupos_sugeridos(hojas, nombre, ids_dobles)
        previo_g = previa["grupo"] if previa else ""
        opciones_g = ["", *existentes, "__nuevo__"]
        indice_g = opciones_g.index(previo_g) if previo_g in opciones_g else (len(opciones_g) - 1 if previo_g else 0)
        elegido_g = st.selectbox(
            "Grupo de evento",
            opciones_g,
            index=indice_g,
            format_func=lambda g: {"": "— ninguno: titular suelto —", "__nuevo__": "➕ nuevo grupo…"}.get(g, g),
            key=f"g-{nid}",
            help="Titulares que cuentan el mismo hecho comparten grupo. Un titular que no repite el hecho de otro va suelto.",
        )
        if elegido_g == "__nuevo__":
            nuevo = st.text_input("Nombre del nuevo grupo (corto y descriptivo, ej. sismo-chiriqui)", value=previo_g if previo_g not in existentes else "", key=f"gn-{nid}")
            grupo_final = normalizar_grupo(nuevo)
            if grupo_final:
                st.caption(f"Se guardará como `{grupo_final}`.")
        else:
            grupo_final = elegido_g
    nota = st.text_input(
        "Nota (opcional: dudas, por qué)",
        value=previa["nota"] if previa else "",
        key=f"nota-{nid}",
        help="No escribas datos personales (nombres de personas, contactos) en la nota.",
    )

    if st.button("Guardar y seguir", type="primary", key=f"guardar-{nid}"):
        try:
            guardar_etiqueta(
                ruta, cfg, temas, noticia,
                {"ruido": ruido, "tema_principal": principal, "tema_secundario": secundario, "grupo": grupo_final, "alcance_regional": regional, "nota": nota},
                nombre,
            )
        except ErrorEtiquetado as exc:
            st.error(str(exc))
        else:
            st.success("Guardado.")
            st.rerun()


def _en_streamlit() -> bool:
    try:
        from streamlit import runtime

        return runtime.exists()
    except Exception:  # noqa: BLE001 - sin streamlit instalado o fuera de su runtime
        return False


if __name__ == "__main__":
    if _en_streamlit():
        interfaz()
    else:
        sys.exit(main())
