"""Exploración OFFLINE de la muestra real (E0-09, fase Preparación).

Perfila ``data/processed/`` (y el crudo de Banco Mundial/USGS, y el RSS si existe en disco) y escribe
``docs/exploracion.md``. No llama a ninguna red. No muestra ni guarda descripciones del RSS (D-31, D-72) ni
nombres de autores (D-32). Todo lo que marca como ruido es CANDIDATO: el etiquetado es E1-03b / E1-06.

    poetry run python -m scripts.explorar
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from src.configuracion import RAIZ, ConfigExploracion, cargar_exploracion, cargar_fuentes

logger = logging.getLogger(__name__)

CAMPOS_TEXTO = {"titulo", "url", "medio", "nota", "place", "fuente_url", "licencia", "unidad"}
CAMPOS_ID = {"id_noticia", "id_indicador", "id"}


# ----------------------------------------------------------------------- utilidades


def wilson(k: int, n: int, z: float) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción k/n (n > 0)."""
    p = k / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centro - mitad), min(1.0, centro + mitad)


def prop(k: int, n: int, z: float) -> str:
    """``k/n = p % [IC 95 %: lo–hi %]`` (con n siempre visible)."""
    if n == 0:
        return "0/0 (sin datos)"
    lo, hi = wilson(k, n, z)
    return f"{k}/{n} = {100 * k / n:.1f} % [IC 95 %: {100 * lo:.1f}–{100 * hi:.1f} %]"


def forma(valor: Any) -> str:
    """Forma de un valor: dígitos -> 9, letras -> a, repeticiones colapsadas (para ver el formato)."""
    s = re.sub(r"\d", "9", str(valor))
    s = re.sub(r"[^\W\d_]", "a", s)
    return re.sub(r"(.)\1+", r"\1+", s)[:40]


def tabla(filas: list[list[Any]], cabecera: list[str]) -> str:
    """Tabla Markdown."""
    def esc(x: Any) -> str:
        return str(x).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(cabecera) + " |", "|" + "---|" * len(cabecera)]
    out += ["| " + " | ".join(esc(c) for c in f) + " |" for f in filas]
    return "\n".join(out)


def normalizar_titulo(t: str, sufijo: str) -> str:
    """Clave de comparación de titulares: sin sufijo de medio, sin HTML, solo alfanuméricos en minúscula."""
    t = html.unescape(re.sub(sufijo, "", t))
    return re.sub(r"[\W_]+", "", t.lower())


def coincide(texto: str, patrones: list[str]) -> bool:
    """Alguno de los términos aparece al inicio de una palabra (evita que ``amp`` coincida con ``campo``)."""
    t = texto.lower()
    return any(re.search(rf"\b{re.escape(p.lower())}", t) for p in patrones)


# ----------------------------------------------------------------------- carga


def cargar_datos(raiz: Path) -> dict[str, Any]:
    proc = raiz / "data" / "processed"
    noticias = pd.read_csv(proc / "noticias.csv", dtype=str, keep_default_na=False)
    noticias = noticias.replace({"": None})
    return {
        "noticias": noticias,
        "indicadores": pd.read_csv(proc / "indicadores.csv", dtype=str, keep_default_na=False).replace({"": None}),
        "eventos": json.loads((proc / "eventos.geojson").read_text("utf-8")),
        "fuentes": json.loads((proc / "fuentes.json").read_text("utf-8")),
        "manifest": json.loads((raiz / "data" / "manifest.json").read_text("utf-8")),
    }


# ----------------------------------------------------------------------- secciones


def perfil_campos(df: pd.DataFrame, nombre: str, z: float) -> str:
    n = len(df)
    filas = []
    for c in df.columns:
        serie = df[c]
        presentes = serie.dropna()
        k = len(presentes)
        if k == 0:
            fmt = "(sin valores)"
        elif c in CAMPOS_ID:
            pref = Counter(str(v).split("-")[0] + "-" for v in presentes)
            fmt = "prefijo " + " · ".join(f"`{k}` ×{m}" for k, m in pref.most_common(3)) + f"; únicos {presentes.nunique()}/{k}"
        elif c in CAMPOS_TEXTO:
            largos = [len(str(v)) for v in presentes]
            extra = ""
            if c == "url":
                extra = f"; https: {sum(str(v).startswith('https://') for v in presentes)}/{k}"
            fmt = f"texto, largo mín {min(largos)} · mediana {int(statistics.median(largos))} · máx {max(largos)}{extra}"
        else:
            fmt = " · ".join(f"`{f}` ×{m}" for f, m in Counter(forma(v) for v in presentes).most_common(2))
        filas.append([f"`{c}`", prop(k, n, z), prop(n - k, n, z), fmt])
    return f"**{nombre}** (n = {n})\n\n" + tabla(filas, ["Campo", "Presente", "Nulo", "Formato observado"])


def conteos(serie: pd.Series, top: int, etiqueta: str, z: float) -> str:
    n = int(serie.notna().sum())
    filas = [[f"`{k}`", v, prop(int(v), n, z)] for k, v in serie.value_counts().head(top).items()]
    resto = int(serie.nunique()) - len(filas)
    nota = f"\n\n_n = {n}; {serie.nunique()} valores distintos" + (f", se muestran {len(filas)}._" if resto > 0 else "._")
    return tabla(filas, [etiqueta, "n", "% (IC 95 %)"]) + nota


def fecha_base(df: pd.DataFrame) -> pd.Series:
    """fecha_deteccion; fecha_publicacion si no hay detección (misma base que la ventana, D-74)."""
    return pd.to_datetime(df["fecha_deteccion"].fillna(df["fecha_publicacion"]), utc=True)


def seccion_conteos(d: dict[str, Any], cfg: ConfigExploracion) -> str:
    nt, top, z = d["noticias"], cfg.estadistica.top_n, cfg.estadistica.z_95
    n = len(nt)
    tvn = int((nt["origen"] == "TVN RSS").sum())
    paises = {f["dominio"]: f["pais"] for f in d["fuentes"]}
    nt = nt.assign(dominio=nt["url"].str.extract(r"https?://(?:www\.)?([^/]+)")[0])
    pais = nt["dominio"].map(paises).fillna(nt["medio"].map(lambda m: "Panamá" if m == "TVN Panamá" else None))
    rss = nt[nt["origen"].str.contains("RSS")]
    temas_gdelt = nt[nt["origen"].str.contains("GDELT")]["tema"].str.split("|").explode()
    dias = fecha_base(nt).dt.strftime("%Y-%m-%d")
    por_dia = pd.crosstab(dias, nt["origen"])
    filas_dia = [[dia, *[int(v) for v in fila]] for dia, fila in por_dia.iterrows()]
    out = [
        f"Noticias en el snapshot: **{n}**. TVN RSS: **{prop(tvn, n, z)}**.",
        "### Por medio\n\n" + conteos(nt["medio"], top, "Medio", z),
        "### Por idioma\n\n" + conteos(nt["idioma"], top, "Idioma (ISO 639-1)", z)
        + f"\n\nEspañol: {prop(int((nt['idioma'] == 'es').sum()), n, z)}.",
        "### Por país del medio (`fuentes.json`)\n\n" + conteos(pais.fillna("(sin país)"), top, "País", z)
        + f"\n\nSin país conocido: {prop(int(pais.isna().sum()), n, z)}.",
        "### Por categoría del RSS (tema de origen de TVN = primera sección de la URL)\n\n"
        + conteos(rss["tema"], top, "Sección RSS", z),
        "### Por tema de origen de GDELT (una URL puede salir en varios temas)\n\n"
        + conteos(temas_gdelt, top, "Consulta GDELT", z),
        "### Por día (fecha base: detección; publicación si no hay detección; UTC)\n\n"
        + tabla(filas_dia, ["Día", *list(por_dia.columns)])
        + f"\n\n_Días con datos: {len(filas_dia)}. La hora de Panamá solo se usa en la interfaz._",
    ]
    return "\n\n".join(out)


def datos_rss_crudo(crudos: Path, cfg: ConfigExploracion) -> dict[str, Any] | None:
    """Perfil de firma y categorías del RSS crudo (solo lectura; fuera del repositorio, D-72). Nunca devuelve nombres."""
    carpeta = crudos / cfg.rss.carpeta_cruda
    archivos = sorted(carpeta.glob("rss_tvn_*.xml")) if carpeta.exists() else []
    if not archivos:
        return None
    import feedparser

    tipos: Counter[str] = Counter()
    agencias: Counter[str] = Counter()
    claves: Counter[str] = Counter()
    categorias: Counter[str] = Counter()
    con_categoria = 0
    n = 0
    for ruta in archivos:
        for e in feedparser.parse(ruta.read_bytes()).entries:
            n += 1
            for c in e.keys():
                if c not in cfg.rss.claves_excluidas:
                    claves[c] += 1
            etiquetas = [str(t.get("term", "")).strip() for t in e.get("tags", []) if t.get("term")]
            con_categoria += bool(etiquetas)
            categorias.update(etiquetas)
            firma = next((str(e[c]).strip() for c in cfg.rss.campos_firma if e.get(c)), "")
            if not firma:
                tipos["sin firma"] += 1
                continue
            bajo = firma.lower()
            ag = next((a for a in cfg.rss.agencias if a.lower() in bajo), None)
            if ag:
                tipos["agencia"] += 1
                agencias[ag] += 1
            elif bajo in cfg.rss.redaccion:
                tipos["redacción/medio"] += 1
            else:
                tipos["persona (nombre no guardado)"] += 1
    return {"n": n, "archivos": len(archivos), "tipos": tipos, "agencias": agencias, "claves": claves,
            "categorias": categorias, "con_categoria": con_categoria}


def datos_gdelt_crudo(crudos: Path, cfg: ConfigExploracion) -> dict[str, Any] | None:
    """Perfil de campos de los artículos del crudo de GDELT (solo claves y conteos; nunca valores)."""
    carpeta = crudos / cfg.rss.carpeta_gdelt
    archivos = sorted(carpeta.glob("gdelt_*.json")) if carpeta.exists() else []
    if not archivos:
        return None
    claves: Counter[str] = Counter()
    n = 0
    for ruta in archivos:
        texto = ruta.read_text(encoding="utf-8")
        datos = json.loads(texto, strict=False) if texto.strip() else {}
        for a in datos.get("articles", []):
            n += 1
            claves.update(k for k, v in a.items() if v not in (None, ""))
    return {"n": n, "archivos": len(archivos), "claves": claves}


def _evidencia_gdelt(g: dict[str, Any] | None) -> str:
    if g is None:
        return ("_Evidencia y límite:_ la lectura de campos está en `scripts/conversion.py::_leer_gdelt` (usa solo `seendate`); "
                "el crudo de GDELT no estaba disponible en esta corrida, así que la lista de campos de la API **no se verificó**.")
    claves = ", ".join(f"`{k}` ×{v}" for k, v in g["claves"].most_common())
    return (f"**Verificado en el crudo** ({g['archivos']} archivos, {g['n']} artículos; los archivos pueden repetir artículos entre rangos): "
            f"campos con valor: {claves}. Ninguno es una fecha de publicación; `seendate` es la única fecha.")


def seccion_preguntas(d: dict[str, Any], cfg: ConfigExploracion, rss: dict[str, Any] | None,
                      gdelt: dict[str, Any] | None = None) -> str:
    nt, z = d["noticias"], cfg.estadistica.z_95
    solo_gdelt = nt[nt["origen"] == "GDELT"]
    k_pub = int(solo_gdelt["fecha_publicacion"].notna().sum())
    k_det = int(solo_gdelt["fecha_deteccion"].notna().sum())
    ambos = int((nt["origen"].str.contains("RSS") & nt["origen"].str.contains("GDELT")).sum())
    rss_filas = nt[nt["origen"] == "TVN RSS"]
    out = [
        "### ¿GDELT trae fecha de publicación?",
        f"**No.** GDELT DOC 2.0 (`mode=artlist`) entrega `seendate` (cuándo GDELT vio la noticia) y no la fecha en que el "
        f"medio la publicó. En el snapshot, de los registros que vinieron solo de GDELT (n = {len(solo_gdelt)}): "
        f"`fecha_publicacion` presente en {prop(k_pub, len(solo_gdelt), z)}; `fecha_deteccion` presente en "
        f"{prop(k_det, len(solo_gdelt), z)}. Registros presentes en el RSS **y** en GDELT: {ambos} de {len(nt)}.",
        _evidencia_gdelt(gdelt),
        "**Efecto:** U (urgencia) y T03 (noticia recirculada) no pueden usar GDELT como fecha del hecho; solo el RSS de "
        f"TVN la trae ({prop(len(rss_filas), len(nt), z)} de las noticias). Una fecha de detección reciente de una nota "
        "vieja es justo el caso de T03. Ver recomendaciones.",
        "### ¿El RSS de TVN trae autor o firma?",
    ]
    if rss is None:
        out.append(
            "**No verificable en este entorno.** El crudo del RSS está fuera del repositorio (D-72) y `processed/` no guarda autor "
            "(D-32), así que `data/processed/` no permite responder. El conteo de campos del RSS requiere el crudo: "
            "`poetry run python -m scripts.explorar` lo perfila solo si `data/raw/rss_tvn/rss_tvn_*.xml` existe "
            "(en la máquina donde se extrajo). **Pendiente de correr allí**; el informe reportará tipos de firma "
            "(agencia · redacción · persona · sin firma) y agencias, nunca nombres de personas."
        )
    else:
        n = rss["n"]
        z = cfg.estadistica.z_95
        filas = [[t, v, prop(v, n, z)] for t, v in rss["tipos"].most_common()]
        sin = rss["tipos"].get("sin firma", 0)
        veredicto = (f"**Verificado: el RSS de TVN no trae autor ni firma** ({sin}/{n} entradas sin ninguno de los campos buscados)."
                     if sin == n else "**El RSS trae firma en parte de las entradas** (ver tabla).")
        out.append(
            f"{veredicto} Entradas en {rss['archivos']} crudo(s): {n}. Campos de firma buscados: {', '.join(cfg.rss.campos_firma)}.\n\n"
            + tabla(filas, ["Tipo de firma", "n", "% (IC 95 %)"])
            + f"\n\nCategorías del RSS (`<category>`, solo conteos): {prop(rss['con_categoria'], n, z)} de las entradas traen alguna; "
            + (", ".join(f"`{c}` ×{v}" for c, v in rss["categorias"].most_common(cfg.estadistica.top_n)) or "ninguna categoría")
            + "."
            + "\n\nAgencias: " + (", ".join(f"{a} ×{v}" for a, v in rss["agencias"].most_common()) or "ninguna")
            + "\n\nClaves presentes en las entradas (sin descripción): "
            + ", ".join(f"`{c}` ×{v}" for c, v in rss["claves"].most_common())
        )
    return "\n\n".join(out)


def aplica(patron: str, t: str) -> bool:
    return re.search(patron, t) is not None


def candidatos_ruido(nt: pd.DataFrame, cfg: ConfigExploracion) -> pd.DataFrame:
    """Marca candidatos (booleanos por regla). No clasifica ni borra."""
    p = cfg.patrones
    es_tvn = nt["origen"] == "TVN RSS"
    t = nt["titulo"].fillna("")
    res = pd.DataFrame(index=nt.index)
    res["generico"] = t.map(lambda x: any(aplica(r, x.lower()) for r in p.titulo_generico))
    res["no_menciona_panama"] = ~es_tvn & ~t.map(lambda x: coincide(x, p.menciones_panama))
    res["falso_panama"] = t.map(lambda x: coincide(x, p.falso_panama))
    res["deportes"] = t.map(lambda x: coincide(x, p.deportes))
    res["farandula"] = t.map(lambda x: coincide(x, p.farandula))
    res["autopromocion_tvn"] = es_tvn & t.map(lambda x: coincide(x, p.autopromocion_tvn))
    res["sospechoso"] = res.any(axis=1)
    return res


def seccion_calidad_titulares(d: dict[str, Any], cfg: ConfigExploracion) -> tuple[str, pd.DataFrame]:
    nt, z, p = d["noticias"], cfg.estadistica.z_95, cfg.patrones
    t = nt["titulo"].fillna("")
    n = len(nt)
    es_tvn = nt["origen"] == "TVN RSS"
    ng, nn = int((~es_tvn).sum()), int(es_tvn.sum())
    reglas = [
        ("Sufijo de medio (` - Medio`, ` | Medio`)", t.map(lambda x: aplica(p.sufijo_medio, x))),
        ("Entidad HTML sin decodificar (`&amp;`, `&#39;`)", t.map(lambda x: aplica(p.entidad_html, x))),
        ("Espacio antes de puntuación (tokenización de GDELT: `21 , 2 %`)", t.map(lambda x: aplica(p.espacio_antes_de_puntuacion, x))),
        ("Barra pegada a la palabra (`resultados| texto`, estilo TVN)", t.map(lambda x: aplica(p.separador_barra_tvn, x))),
        ("Titular sin contenido (solo dominio, `Inicio |`, `Preview -`)", t.map(lambda x: any(aplica(r, x.lower()) for r in p.titulo_generico))),
    ]
    filas = []
    for nombre, m in reglas:
        filas.append([nombre, prop(int(m.sum()), n, z), prop(int((m & es_tvn).sum()), nn, z), prop(int((m & ~es_tvn).sum()), ng, z)])
    texto = tabla(filas, ["Señal (candidata)", "Todas", "TVN RSS", "GDELT"])
    ruido = candidatos_ruido(nt, cfg)
    return texto, ruido


def seccion_ruido(d: dict[str, Any], ruido: pd.DataFrame, cfg: ConfigExploracion) -> str:
    nt, z = d["noticias"], cfg.estadistica.z_95
    n = len(nt)
    es_tvn = nt["origen"] == "TVN RSS"
    filas = []
    for col, desc, base in [
        ("generico", "Titular sin contenido", n),
        ("no_menciona_panama", "Medio no TVN cuyo titular no nombra Panamá ni un término panameño", int((~es_tvn).sum())),
        ("falso_panama", "Falso Panamá conocido (Panama City Beach…)", n),
        ("deportes", "Palabras de deportes", n),
        ("farandula", "Palabras de farándula", n),
        ("autopromocion_tvn", "Autopromoción de TVN", int(es_tvn.sum())),
    ]:
        filas.append([desc, prop(int(ruido[col].sum()), base, z)])
    filas.append(["Cualquiera de las señales", prop(int(ruido["sospechoso"].sum()), n, z)])
    return tabla(filas, ["Señal", "Candidatos / base"]) + (
        "\n\nSon **candidatos por palabras clave** (listas en `config/exploracion.yaml`). No miden precisión; la medición "
        "contra etiquetas humanas es `eval.ruido` (E1-03b)."
    )


def duplicados(nt: pd.DataFrame, cfg: ConfigExploracion) -> list[dict[str, Any]]:
    """Grupos de titulares casi idénticos (clave normalizada o contenida en otra). Pistas de agrupación."""
    suf, minimo = cfg.patrones.sufijo_medio, cfg.duplicados.min_caracteres_contencion
    claves = nt["titulo"].fillna("").map(lambda x: normalizar_titulo(x, suf))
    grupos: dict[str, list[int]] = {}
    for i, k in claves.items():
        if k:
            grupos.setdefault(k, []).append(i)
    ordenadas = sorted(grupos, key=len)
    destino: dict[str, str] = {}
    for k in ordenadas:
        base = next((o for o in ordenadas if o != k and len(o) >= minimo and o in k and destino.get(o) == o), None)
        destino[k] = base or k
    fusion: dict[str, list[int]] = {}
    for k, idx in grupos.items():
        fusion.setdefault(destino[k], []).extend(idx)
    out = []
    for k, idx in fusion.items():
        if len(idx) < 2:
            continue
        sub = nt.loc[idx]
        out.append({"clave": k, "n": len(idx), "medios": int(sub["medio"].nunique()), "idiomas": sorted(sub["idioma"].unique()),
                    "titulo": sub["titulo"].iloc[0], "ids": sub["id_noticia"].tolist(), "tema": sub["tema"].iloc[0]})
    return sorted(out, key=lambda g: (-g["n"], g["clave"]))


def seccion_duplicados(nt: pd.DataFrame, cfg: ConfigExploracion) -> tuple[str, list[dict[str, Any]]]:
    g = duplicados(nt, cfg)
    z = cfg.estadistica.z_95
    n = len(nt)
    en_grupos = sum(x["n"] for x in g)
    filas = [[x["n"], x["medios"], ",".join(x["idiomas"]), x["titulo"][:110]] for x in g[: cfg.estadistica.top_n]]
    t = (
        f"Grupos de ≥ 2 titulares casi idénticos (texto normalizado, sin sufijo de medio): **{len(g)}**; cubren "
        f"{prop(en_grupos, n, z)} de los registros.\n\n" + tabla(filas, ["Registros", "Medios", "Idiomas", "Titular (primero)"])
        + "\n\n_No detecta traducciones: «Trump streicht Europa-Hilfe…» (de) y «Допомога США Європі…» (uk) son el mismo evento y "
        "quedan en grupos distintos. Eso lo cubre la similitud semántica (E1-08)._"
    )
    return t, g


def seccion_cobertura(d: dict[str, Any], z: float) -> str:
    cob = d["manifest"]["cobertura_efectiva"]
    filas = [[t, v["dias_cubiertos"], v["dias_esperados"], prop(v["dias_cubiertos"], v["dias_esperados"], z)]
             for t, v in cob["gdelt_dias_por_tema"].items()]
    sin = Counter()
    for r in cob["gdelt_rangos_sin_resolver"]:
        sin[(r["tema"], r["motivo"])] += r["dias"]
    filas2 = [[t, m, v] for (t, m), v in sorted(sin.items())]
    return (
        tabla(filas, ["Tema GDELT", "Días cubiertos", "Días esperados", "Cobertura (IC 95 %)"])
        + "\n\nDías sin resolver (suma de rangos):\n\n" + tabla(filas2, ["Tema", "Motivo", "Días"])
        + f"\n\nRSS: de {cob.get('fecha_publicacion_inicial')} a {cob.get('fecha_publicacion_final')}; "
        f"detección GDELT: de {cob.get('fecha_deteccion_inicial')} a {cob.get('fecha_deteccion_final')}."
        "\n\n**`eventos_naturales` tiene 0 días cubiertos**: no hay ni un titular de GDELT en ese tema, y los sismos/lluvias "
        "son un tema central del reto. Los números de este informe no representan los 30 días de la ventana (D-74)."
    )


def seccion_banco_mundial(d: dict[str, Any], cfg: ConfigExploracion) -> str:
    z = cfg.estadistica.z_95
    ind = d["indicadores"].copy()
    ind["anio"] = ind["anio"].astype(int)
    ind["tiene"] = ind["valor"].notna()
    filas = []
    for iid, g in ind.groupby("indicador_id"):
        nulos = int((~g["tiene"]).sum())
        ultimo = g[g["tiene"]].groupby("pais_iso3")["anio"].max()
        ultimos = ", ".join(f"{p} {a}" for p, a in ultimo.items())
        sin_nada = sorted(set(g["pais_iso3"]) - set(ultimo.index))
        filas.append([f"`{iid}`", g["unidad"].iloc[0], prop(nulos, len(g), z), f"{int(ultimo.min())}–{int(ultimo.max())}" if len(ultimo) else "—",
                      ultimos + (f"; sin dato: {', '.join(sin_nada)}" if sin_nada else "")])
    esperado = cfg.indicadores.anio_fin_esperado
    pan = ind[(ind["pais_iso3"] == "PAN") & ~ind["tiene"]]
    texto = tabla(filas, ["Indicador", "Unidad", "Nulos", "Último año con dato (rango)", "Último año por país"])
    texto += (
        f"\n\nCuadrícula: {len(ind)} filas; valores nulos: {prop(int((~ind['tiene']).sum()), len(ind), z)}. Año final de la cuadrícula: {esperado}. Los nulos se conservan "
        "como nulos; los datos son **anuales** y nunca \"actuales\"."
    )
    if len(pan):
        texto += "\n\nPanamá sin dato: " + ", ".join(f"{r.indicador_id} {r.anio}" for r in pan.itertuples())
    return texto


def seccion_usgs(d: dict[str, Any], cfg: ConfigExploracion) -> str:
    props = [f["properties"] for f in d["eventos"]["features"]]
    n = len(props)
    z = cfg.estadistica.z_95
    lims = cfg.usgs.bins_magnitud
    bins = Counter()
    for p in props:
        m = p["magnitude"]
        sup = [b for b in lims if m >= b]
        bins[f"M ≥ {sup[-1]:g}" if sup else f"M < {lims[0]:g}"] += 1
    orden = [f"M < {lims[0]:g}"] + [f"M ≥ {b:g}" for b in lims]
    filas = [[b, bins.get(b, 0), prop(bins.get(b, 0), n, z)] for b in orden]
    mags = sorted(p["magnitude"] for p in props)
    sufijos = Counter(p["place"].split(", ")[-1] for p in props)
    con_panama = sum(coincide(p["place"], cfg.usgs.panama_en_place) for p in props)
    tiempos = sorted(p["time"] for p in props)
    return (
        f"Eventos: **{n}**, de {tiempos[0]} a {tiempos[-1]}. Magnitud: mín {mags[0]}, mediana {statistics.median(mags)}, máx {mags[-1]}.\n\n"
        + tabla(filas, ["Magnitud", "n", "% (IC 95 %)"])
        + "\n\nValores de `place` (texto tras la última coma):\n\n"
        + tabla([[f"`{k}`", v, prop(v, n, z)] for k, v in sufijos.most_common()], ["place (país/zona)", "n", "% (IC 95 %)"])
        + f"\n\n`place` menciona Panamá: {prop(con_panama, n, z)}. **La caja de USGS no es Panamá**: el resto cae en otros países; "
        "se muestra siempre el `place` original. "
        f"\n\n**Desfase temporal:** los sismos son de {tiempos[0][:4]} (intervalo del PDF) y las noticias de "
        "septiembre–octubre de 2026: ningún sismo coincide en el tiempo con ningún titular de este snapshot, así que la coincidencia "
        "de sismos (± 2 días) no se puede probar con esta muestra."
    )


def seccion_revision(d: dict[str, Any], cfg: ConfigExploracion, raiz: Path) -> tuple[str, dict[str, int], list[str]]:
    ruta = raiz / cfg.revision_manual.archivo
    nt = d["noticias"].set_index("id_noticia")
    if not ruta.exists():
        return "_No hay `docs/exploracion_revision.csv`._", {}, []
    rev = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    fuentes_raras = sorted(set(rev["fuente"]) - {"propuesta_agente"})
    if fuentes_raras:
        raise ValueError(f"revisión manual inválida: fuente {fuentes_raras} (solo `propuesta_agente`; las etiquetas humanas son E1-06)")
    invalidos = sorted(set(rev["tema_propuesto"]) - set(cfg.revision_manual.temas_validos))
    desconocidos = sorted(set(rev["id_noticia"]) - set(nt.index))
    if invalidos or desconocidos:
        raise ValueError(f"revisión manual inválida: temas {invalidos}, ids desconocidos {desconocidos}")
    minimo = cfg.revision_manual.minimo_candidatos_por_tema
    palabras = cfg.temas_palabras
    temas = list(palabras)
    filas, cuenta = [], {}
    for t in temas:
        sub = rev[rev["tema_propuesto"] == t]
        claro = int((sub["ambiguo"] == "no").sum())
        kw = {i for i, tit in nt["titulo"].items() if coincide(str(tit), [w.lower() for w in palabras[t]])}
        # Candidatos = propuestos por palabra clave ∪ asignados a mano; revisados = todos (se revisaron las 186 filas).
        cand = kw | set(sub["id_noticia"])
        cuenta[t] = len(sub)
        filas.append([t, len(cand), len(sub), claro, int((sub["ejemplo"] == "si").sum()), "sí" if len(sub) >= minimo else f"**NO** (faltan {minimo - len(sub)})"])
    aparte = rev[~rev["tema_propuesto"].isin(temas)]["tema_propuesto"].value_counts()
    cuenta.update({f"_{k}": int(v) for k, v in aparte.items()})
    cuenta["_total"] = len(rev)
    z = cfg.estadistica.z_95
    pureza = []
    for q in cargar_fuentes().gdelt.consultas:
        ids = d["noticias"][d["noticias"]["origen"].str.contains("GDELT") & d["noticias"]["tema"].str.split("|").map(lambda x, q=q: q in x)]["id_noticia"]
        etiquetas = rev[rev["id_noticia"].isin(ids)]["tema_propuesto"]
        if len(etiquetas) == 0:
            pureza.append([q, 0, "sin registros (0 días cubiertos)", "—"])
            continue
        en_tema = int(etiquetas.isin(temas).sum())
        pureza.append([q, len(etiquetas), prop(en_tema, len(etiquetas), z), prop(int((etiquetas == q).sum()), len(etiquetas), z)])
    ejemplos = [f"{r.id_noticia}\t{nt.loc[r.id_noticia, 'titulo']}" for r in rev[rev["ejemplo"] == "si"].itertuples()]
    texto = (
        f"Se revisaron **a mano las {len(rev)} filas** del snapshot (no solo una muestra) y se les propuso un tema de la guía "
        "(`docs/exploracion_revision.csv`). **Es una propuesta del agente de desarrollo (`fuente = propuesta_agente`), pendiente de confirmación humana; no son "
        "etiquetas de evaluación (E1-06).** Las filas dudosas llevan `ambiguo = si`.\n\n"
        + tabla(filas, ["Tema", "Candidatos (palabra clave ∪ propuestos)", "Asignados al tema", "…sin ambigüedad", "Marcados como ejemplo", f"≥ {minimo} del spec"])
        + "\n\nFuera de los 6 temas: "
        + ", ".join(f"`{k}` {v}" for k, v in aparte.items())
        + f". Marcados como ejemplo para `temas.yaml`: {len(ejemplos)}."
        + "\n\n**Tema de origen vs. revisión manual (D-62).** Cuántos de los registros que devolvió cada consulta de GDELT caen en alguno "
        "de los 6 temas, y cuántos en el tema de la consulta (por titular):\n\n"
        + tabla(pureza, ["Consulta de GDELT", "Registros", "En alguno de los 6 temas", "En el tema de la consulta"])
        + "\n\nPor eso el tema de origen **nunca** sirve de etiqueta."
    )
    return texto, cuenta, ejemplos


def seccion_recomendaciones(d: dict[str, Any], ruido: pd.DataFrame, grupos: list[dict[str, Any]], cuenta: dict[str, int],
                            cfg: ConfigExploracion, rss: dict[str, Any] | None = None) -> str:
    nt = d["noticias"]
    n = len(nt)
    es_tvn = nt["origen"] == "TVN RSS"
    nm = int(ruido["no_menciona_panama"].sum())
    z = cfg.estadistica.z_95
    np_, ft_, sc_ = cuenta.get("_no_es_panama", 0), cuenta.get("_fuera_de_temas", 0), cuenta.get("_sin_contenido", 0)
    tot = cuenta.get("_total", n)
    if rss is None:
        agencias_txt = ("el RSS crudo no se pudo perfilar aquí; la lista `agencias` del YAML debe confirmarse con el perfil de firma "
                        "corrido donde está el crudo.")
    elif rss["tipos"].get("sin firma", 0) == rss["n"]:
        agencias_txt = (f"el RSS de TVN **no trae firma** ({rss['n']}/{rss['n']} entradas sin autor ni `dc:creator`), así que la lista "
                        "`agencias` no puede derivarse de él. Las procedencias independientes (CU-03) salen del dominio del medio y de "
                        "la repetición del titular, no de la firma; la lista de agencias solo serviría si un titular de GDELT la nombra "
                        "(`- EFE`, `Xinhua`) y eso se decide en E1-05/E1-08. No inventar agencias ni tipos de firma.")
    else:
        agencias_txt = "el RSS trae firma en parte de las entradas; confirmar la lista `agencias` con el perfil de la sección 3."
    return f"""### Para E1-03b (limpieza y ruido)

1. **Hipótesis: el mayor ruido sería "no es Panamá", no deportes ni farándula.** En la propuesta del agente (por titular, que es lo único que ve el
   sistema; no es una etiqueta humana): `no_es_panama` {prop(np_, tot, z)}, `fuera_de_temas` {prop(ft_, tot, z)}, sin contenido {prop(sc_, tot, z)}. Además, {nm} de
   {int((~es_tvn).sum())} registros no TVN no nombran Panamá ni un término panameño en el titular. Causa probable (según
   `config/fuentes.yaml`): las consultas de GDELT piden `Panama` más un término amplio (`port`, `cargo`, `hotel`, `economy`…) sin
   anclarlos al titular; GDELT puede resolverlas sobre el texto del artículo (no verificado aquí: el crudo no está en git), así que el
   titular puede no decir Panamá aunque el artículo sí. Como el sistema solo lee el titular, no puede
   distinguir esos casos, y es una decisión de producto qué hacer con ellos. Un patrón de menciones de Panamá sobre el titular es el primer
   filtro, **no** se aplica a TVN, y la regla de la guía manda: lo que afecta a Panamá no es ruido (p. ej. la nota sindicada sobre
   El Niño en Latinoamérica es dudosa; el aviso de que un capitán de remolcador del Canal murió, no).
2. **Titulares sin contenido** (solo dominio, `Inicio |`, `Preview -`): patrón de `titulo_generico` en `config/ruido.yaml`;
   hoy {int(ruido['generico'].sum())} de {n}.
3. **Falsos Panamá concretos:** `Panama City Beach` / `PCB` (turismo de Florida) cae en el tema Turismo. Lista en YAML, no en código.
4. **Limpieza:** sufijos de medio, espacios antes de puntuación (`21 , 2 %`, `US$84 . 000`; es la tokenización de GDELT, dañan
   los embeddings y las cifras), barra pegada de TVN (`resultados| texto`) y prefijos de sección de TVN (`Liga de Naciones … resultados|`).
5. **La sección de TVN es solo una señal CANDIDATA de `fuera_de_temas`; decide el titular.** `tvmax`, `entretenimiento`, `gente-tvn` y
   `videos` suelen ser deportes, farándula o cultura, pero varios de `tvmax`/`entretenimiento` tratan de otros países (`no_es_panama`:
   p. ej. Messi/Argentina, Pedro Pascal), y los de `contenido-exclusivo` son sobre Panamá y pueden estar en los temas (transporte público,
   sequía). Un patrón de URL no debe excluir ni etiquetar por sí solo: úsese para subir la sospecha y confirmar con el titular. `mundo` es
   noticia internacional: `no_es_panama` salvo que afecte a Panamá.
6. **Duplicados:** {len(grupos)} grupos de titulares casi idénticos; los sindicados (Xinhua, Trump/Europa) aparecen en decenas de
   dominios. Deduplicar por URL no los junta: hay que contar procedencias **independientes**, no republicaciones (E1-08).

### Para E1-05 (`reglas_v1.3.yaml`, `temas.yaml`)

1. **U (urgencia):** GDELT no trae `fecha_publicacion`. La regla debe usar `fecha_publicacion` solo cuando exista y, si no,
   tratar la detección como cota de "visto por GDELT" (nunca como publicación). Con esta muestra, solo
   {int(es_tvn.sum())} de {n} noticias tienen publicación: **U será desconocida para la mayoría de los grupos**; hay que definir
   su valor por defecto y decirlo en la ficha.
2. **E (evidencia):** el término "titulares con medio y fecha de publicación conocidos" (0.2) quedará bajo para todo lo que viene de GDELT.
3. **`temas.yaml`:** con esta muestra no se llega a ~10 ejemplos reales por tema en todos los temas
   (asignados: {', '.join(f'{t} {v}' for t, v in cuenta.items() if not t.startswith('_'))}). `eventos_naturales` no tiene cobertura de GDELT
   (0 días) y `turismo`/`regulacion` casi no tienen titulares propios. Completar con una extracción nueva cuando GDELT deje de limitar, o
   redactar esos ejemplos como ilustrativos (como en la guía) y **no** presentarlos como reales. Los ejemplos propuestos están en
   `config/ejemplos_excluidos.txt`; E1-05 agrega ahí los que sume y **elimina de ese archivo los que no use** (excluir de la evaluación
   un titular que no es ejemplo solo resta datos).
4. **Alcance geográfico (I):** los titulares de TVN nombran provincia/distrito (Chiriquí, Veraguas, Coclé, Colón, San Miguelito, La Chorrera);
   la lista de provincias y distritos del YAML tiene ejemplos reales para probarla.
5. **Agencias:** {agencias_txt}
6. **T01 (nulos):** la cuadrícula del Banco Mundial de esta corrida no tiene ningún nulo (0/540), contra lo que se esperaba; las
   pruebas de nulos (T01, T04) deben usar fixtures sintéticos (`SYN-`), no depender de este snapshot. Los sismos de USGS son de 2024 y las
   noticias de 2026: la coincidencia ± 2 días de E1-09 se prueba con datos sintéticos.
7. **Consultas de GDELT:** el desequilibrio de temas (`logistica` domina; `eventos_naturales` = 0) sugiere revisar las consultas antes
   del evento, no el clasificador.
"""


def perfil_wb_usgs_campos(d: dict[str, Any], z: float) -> str:
    ev = pd.DataFrame([f["properties"] for f in d["eventos"]["features"]]).astype({"magnitude": str, "depth": str, "longitude": str, "latitude": str}, errors="ignore")
    return perfil_campos(ev, "eventos.geojson (propiedades)", z)


# ----------------------------------------------------------------------- informe


def generar(raiz: Path = RAIZ, crudos: Path | None = None) -> tuple[str, list[str]]:
    """Devuelve (informe Markdown, líneas de ejemplos para ``ejemplos_excluidos.txt``)."""
    cfg = cargar_exploracion()
    d = cargar_datos(raiz)
    nt = d["noticias"]
    crudos = crudos or raiz / "data" / "raw"
    rss = datos_rss_crudo(crudos, cfg)
    gdelt = datos_gdelt_crudo(crudos, cfg)
    cal, ruido = seccion_calidad_titulares(d, cfg)
    dup_txt, grupos = seccion_duplicados(nt, cfg)
    rev_txt, cuenta, ejemplos = seccion_revision(d, cfg, raiz)
    man = d["manifest"]
    partes = [
        "# Exploración de la muestra real (E0-09)\n",
        "> Generado por `poetry run python -m scripts.explorar`. **Offline:** usa `data/processed/`, el crudo versionado de Banco Mundial y "
        "USGS y, en solo lectura (`--crudos`), los crudos de RSS y GDELT que no están en el repositorio (no se copian). "
        "Fase: Preparación (D-74). No muestra descripciones del RSS (D-31, D-72) ni nombres de autores (D-32). "
        "Los porcentajes llevan su n e intervalo de Wilson al 95 %. **" + cfg.estadistica.nota + "** "
        "Todo lo marcado como ruido es **candidato**: el etiquetado es E1-03b / E1-06.\n",
        f"**Muestra:** snapshot de E0-04 (`fecha_corte_UTC` {man.get('fecha_corte_UTC')}); no se descargó una muestra nueva "
        "porque GDELT está limitando las solicitudes (HTTP 429). **No es una muestra de 1–3 días con una consulta por tema**: "
        "es lo que quedó cubierto (ver Cobertura).\n",
        "## 1 · Perfil de campos\n",
        perfil_campos(nt, "noticias.csv", cfg.estadistica.z_95),
        perfil_campos(d["indicadores"], "indicadores.csv", cfg.estadistica.z_95),
        perfil_wb_usgs_campos(d, cfg.estadistica.z_95),
        "## 2 · Conteos\n",
        seccion_conteos(d, cfg),
        "## 3 · Preguntas del spec\n",
        seccion_preguntas(d, cfg, rss, gdelt),
        "## 4 · Calidad de los titulares\n",
        cal,
        "## 5 · Candidatos a ruido\n",
        seccion_ruido(d, ruido, cfg),
        "## 6 · Titulares casi duplicados (pistas de agrupación de eventos)\n",
        dup_txt,
        "## 7 · Cobertura y vacíos\n",
        seccion_cobertura(d, cfg.estadistica.z_95),
        "## 8 · Banco Mundial\n",
        seccion_banco_mundial(d, cfg),
        "## 9 · USGS\n",
        seccion_usgs(d, cfg),
        "## 10 · Revisión manual de titulares por tema\n",
        rev_txt,
        "## 11 · Recomendaciones (no implementadas aquí)\n",
        seccion_recomendaciones(d, ruido, grupos, cuenta, cfg, rss),
    ]
    # Archivos de trabajo fuera de git.
    muestra = raiz / cfg.salida.carpeta_muestra
    muestra.mkdir(parents=True, exist_ok=True)
    out = nt.assign(**{c: ruido[c] for c in ruido.columns})
    out.to_csv(muestra / "candidatos_ruido.csv", index=False)
    (muestra / "grupos_duplicados.json").write_text(json.dumps(grupos, ensure_ascii=False, indent=1), encoding="utf-8")
    return "\n\n".join(partes) + "\n", ejemplos


def escribir_ejemplos(ruta: Path, ejemplos: list[str]) -> None:
    cabecera = [
        "# Titulares usados como ejemplo en config/temas.yaml. NUNCA entran en la evaluación (F1 inflado si no).",
        "# Formato: id_noticia<TAB>titular. Los de E0-09 son propuestos desde docs/exploracion_revision.csv;",
        "# E1-05 agrega aquí cada titular nuevo que ponga en temas.yaml.",
    ]
    ya = ruta.read_text("utf-8").splitlines() if ruta.exists() else []
    existentes = {l.split("\t")[0] for l in ya if l and not l.startswith("#")}
    nuevas = [e for e in ejemplos if e.split("\t")[0] not in existentes]
    cuerpo = ya if ya else cabecera
    ruta.write_text("\n".join(cuerpo + nuevas) + "\n", encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raiz", type=Path, default=RAIZ)
    ap.add_argument("--crudos", type=Path, default=None, help="data/raw de solo lectura (RSS y GDELT); por defecto <raiz>/data/raw")
    args = ap.parse_args()
    cfg = cargar_exploracion()
    informe, ejemplos = generar(args.raiz, args.crudos)
    (args.raiz / cfg.salida.informe).write_text(informe, encoding="utf-8")
    escribir_ejemplos(args.raiz / cfg.salida.ejemplos_excluidos, ejemplos)
    logger.info("escrito %s (%d ejemplos propuestos)", cfg.salida.informe, len(ejemplos))


if __name__ == "__main__":
    main()
