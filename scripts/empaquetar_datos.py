"""C-07 · Paquete de entrega de datos redistribuible (PDF sección 10).

    poetry run python -m scripts.empaquetar_datos            # construye entrega/datos/ y escribe outputs/entrega_manifest.json
    poetry run python -m scripts.empaquetar_datos --verificar  # no construye: revisa el paquete que ya existe

Qué entra (``config/entrega.yaml``, ``paquete``): el snapshot «Panamá · Señales y Evidencias v1», el manifest, el diccionario, las licencias y
condiciones, el benchmark de desarrollo, la **receta** de las fuentes con redistribución restringida (RSS de TVN, GDELT, SBP: D-72) y las
evidencias de la sección 5 (catálogo, fichas, matriz de pruebas, página de métricas). El CSV agregado de la SBP entra con su nota de riesgo (D-116).

Qué nunca entra: ``local.env``, bases ``.duckdb``, los crudos de RSS/GDELT/SBP, la revisión humana (``data/revision*``), el benchmark reservado
ni ningún campo restringido (descripción del RSS, ``socialimage``, extractos). Después de construir, el paquete se **revisa entero** (nombres, rutas,
columnas y claves, secretos); si algo prohibido llegó, se borra la carpeta y el script sale con 1.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.configuracion import RAIZ, ConfigEntrega, cargar_entrega


class ErrorPaquete(ValueError):
    """El paquete no se puede construir con garantías."""


@dataclass(frozen=True)
class Hallazgo:
    """Un problema del contenido de una carpeta: qué regla se rompió, en qué archivo y con qué evidencia."""

    regla: str
    archivo: str
    detalle: str

    def __str__(self) -> str:
        return f"[{self.regla}] {self.archivo}: {self.detalle}"


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _claves_json(valor: Any) -> set[str]:
    """Todas las claves de un JSON anidado."""
    if isinstance(valor, dict):
        return set(valor) | {k for v in valor.values() for k in _claves_json(v)}
    if isinstance(valor, list):
        return {k for v in valor for k in _claves_json(v)}
    return set()


def campos_de(ruta: Path) -> set[str]:
    """Columnas (CSV) o claves (JSON, JSONL, GeoJSON) de un archivo estructurado; vacío si no se puede leer."""
    try:
        if ruta.suffix == ".csv":
            with ruta.open(encoding="utf-8", newline="") as f:
                return {c.strip().lower() for c in next(csv.reader(f), [])}
        if ruta.suffix == ".jsonl":
            claves: set[str] = set()
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                if linea.strip():
                    claves |= _claves_json(json.loads(linea))
            return {c.lower() for c in claves}
        return {c.lower() for c in _claves_json(json.loads(ruta.read_text(encoding="utf-8")))}
    except (OSError, ValueError, UnicodeDecodeError):
        return set()


def normalizar_campo(nombre: str) -> str:
    """Nombre de columna o clave en minúsculas y sin tildes: «Descripción_RSS» y «descripcion_rss» son el mismo campo."""
    return "".join(c for c in unicodedata.normalize("NFKD", nombre.strip().lower()) if not unicodedata.combining(c))


def campos_restringidos_de(ruta: Path, cfg: ConfigEntrega) -> list[str]:
    """Columnas o claves del archivo cuyo nombre normalizado coincide con algún patrón de ``prohibido.campos`` (y no está permitido)."""
    p = cfg.paquete.prohibido
    permitidos = {normalizar_campo(x) for x in p.campos_permitidos}
    nombres = {normalizar_campo(c) for c in campos_de(ruta)}
    return sorted(n for n in nombres if n not in permitidos and any(fnmatch.fnmatchcase(n, normalizar_campo(pat)) for pat in p.campos))


def _normalizar_texto(texto: str) -> str:
    return " ".join(normalizar_campo(texto).split())


def _valores_json(valor: Any, claves: set[str]) -> list[str]:
    if isinstance(valor, dict):
        propios = [v for k, v in valor.items() if k.lower() in claves and isinstance(v, str)]
        return propios + [x for v in valor.values() for x in _valores_json(v, claves)]
    if isinstance(valor, list):
        return [x for v in valor for x in _valores_json(v, claves)]
    return []


def valores_restringidos(cfg: ConfigEntrega, raiz: Path) -> set[str]:
    """Descripciones del RSS y URLs ``socialimage`` crudas (normalizadas) que hay en ``data/raw/`` de ESTA máquina; vacío si no están (se omite el control)."""
    v = cfg.paquete.prohibido.valores_restringidos
    textos: list[str] = []
    for ruta in sorted(raiz.glob(v.rss.glob)):
        try:
            for el in ET.parse(ruta).getroot().iter():     # noqa: S314  (archivo propio de data/raw/)
                if el.tag.rsplit("}", 1)[-1] in v.rss.nombres and el.text:
                    textos.append(el.text)
        except (ET.ParseError, OSError):
            continue
    claves = {n.lower() for n in v.gdelt.nombres}
    for ruta in sorted(raiz.glob(v.gdelt.glob)):
        try:
            textos += _valores_json(json.loads(ruta.read_text(encoding="utf-8")), claves)
        except (OSError, ValueError):
            continue
    normalizados = (_normalizar_texto(t) for t in textos)
    return {t for t in normalizados if len(t) >= v.minimo_caracteres}


def buscar_secretos(ruta: Path, patrones: list[re.Pattern[str]]) -> list[str]:
    """Patrones de secreto que aparecen en un archivo de texto (se devuelve el patrón, nunca el valor)."""
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [p.pattern for p in patrones if p.search(texto)]


def revisar_carpeta(carpeta: Path, cfg: ConfigEntrega, *, omitir: set[str] | None = None, restringidos: set[str] | None = None) -> list[Hallazgo]:
    """Revisa un paquete ya construido: nombres, rutas, campos restringidos (por nombre y, con ``restringidos``, por valor) y secretos.
    ``omitir``: rutas relativas que no se escanean. El hallazgo nombra el archivo y la regla, nunca el valor encontrado."""
    p = cfg.paquete.prohibido
    patrones = [re.compile(x) for x in p.patrones_secretos]
    hallazgos: list[Hallazgo] = []
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file():
            continue
        rel = ruta.relative_to(carpeta).as_posix()
        if omitir and rel in omitir:
            continue
        if any(fnmatch.fnmatch(ruta.name, pat) for pat in p.nombres):
            hallazgos.append(Hallazgo("nombre_prohibido", rel, "el nombre coincide con la lista de prohibidos"))
        if any(rel.startswith(pre.removeprefix("data/")) or ("/" + pre) in "/" + rel for pre in p.prefijos_ruta):
            hallazgos.append(Hallazgo("ruta_prohibida", rel, "la ruta pertenece a una fuente restringida o a datos de la sesión"))
        if ruta.suffix in p.extensiones_estructuradas:
            for campo in campos_restringidos_de(ruta, cfg):
                hallazgos.append(Hallazgo("campo_restringido", rel, f"trae el campo «{campo}» (D-31, D-72)"))
        if restringidos:
            try:
                texto = _normalizar_texto(ruta.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                texto = ""
            n = sum(1 for valor in restringidos if valor in texto)
            if n:
                hallazgos.append(Hallazgo("valor_restringido", rel, f"contiene {n} valores crudos de descripción del RSS o socialimage (D-31, D-72)"))
        for patron in buscar_secretos(ruta, patrones):
            hallazgos.append(Hallazgo("secreto", rel, f"coincide con el patrón de secreto {patron!r}"))
    return hallazgos


def _plan(cfg: ConfigEntrega, raiz: Path) -> dict[str, Path]:
    """Destino (relativo al paquete) -> origen absoluto. Falla si algo de la lista no existe: un paquete incompleto no se entrega."""
    p = cfg.paquete
    plan: dict[str, Path] = {d: raiz / o for d, o in p.archivos.items()}
    for destino, origen in p.carpetas.items():
        base = raiz / origen
        if not base.is_dir():
            raise ErrorPaquete(f"falta la carpeta {origen}")
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix in p.extensiones_carpetas and not set(p.carpetas_excluidas) & set(f.relative_to(base).parts):
                plan.setdefault(f"{destino}/{f.relative_to(base).as_posix()}", f)
    if p.sbp.incluir:
        plan[p.sbp.destino] = raiz / p.sbp.origen
    faltan = sorted(str(o.relative_to(raiz)) for o in plan.values() if not o.is_file())
    if faltan:
        raise ErrorPaquete(f"faltan archivos del paquete: {faltan}")
    return plan


def _commit(raiz: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=raiz, capture_output=True, text=True, check=False)  # noqa: S603, S607
    return r.stdout.strip() or "sin git"


def _leeme(cfg: ConfigEntrega, version: str, n: int) -> str:
    sbp = cfg.paquete.sbp
    estado_sbp = (f"Incluye `{sbp.destino}` con su nota de riesgo en `{sbp.nota_destino}` (D-116)." if sbp.incluir
                  else "No incluye el CSV de la SBP (retirado por la visibilidad de la entrega).")
    return "\n".join([
        "# Paquete de datos · Panamá · Señales y Evidencias v1", "",
        f"Snapshot versión {version}, {n} archivos, cada uno con su SHA-256 en `{cfg.paquete.archivo_checksums}` "
        f"(verificar: `shasum -a 256 -c {cfg.paquete.archivo_checksums}`).", "",
        "## Qué contiene", "",
        "- `snapshot/`: noticias (solo metadatos), fuentes, indicadores del Banco Mundial y eventos de USGS.",
        "- `manifest/`, `diccionario/`, `licencias/`: manifest con su historial, diccionario de campos, licencias y condiciones de cada fuente.",
        "- `benchmark_dev/`: benchmark de desarrollo. El benchmark reservado no se entrega.",
        "- `receta/`: scripts y configuración para regenerar las fuentes con redistribución restringida.",
        "- `evidencias/`: catálogo de fuentes, fichas trazables, matriz de pruebas y página de métricas.", "",
        "## Qué NO contiene (D-72)", "",
        "- Descripciones del RSS de TVN, `socialimage` de GDELT ni extractos de artículos: de esas fuentes solo hay metadatos y la receta.",
        "- Crudos de RSS, GDELT ni SBP; bases `.duckdb`; revisiones humanas; claves ni `local.env`.", "",
        "## SBP", "", estado_sbp, "",
        "Todo lo que produce el sistema es BORRADOR. Los juicios marcados PROVISIONAL (D-101) los rehace una persona.", ""])


def construir(cfg: ConfigEntrega | None = None, raiz: Path = RAIZ, destino: Path | None = None) -> dict[str, Any]:
    """Construye el paquete, lo revisa entero y devuelve su índice. Ante un hallazgo borra la carpeta y lanza ``ErrorPaquete``."""
    cfg = cfg or cargar_entrega()
    p = cfg.paquete
    carpeta = destino or raiz / p.carpeta
    plan = _plan(cfg, raiz)
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    for rel, origen in sorted(plan.items()):
        out = carpeta / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, out)
    if p.sbp.incluir:
        nota = carpeta / p.sbp.nota_destino
        nota.parent.mkdir(parents=True, exist_ok=True)
        nota.write_text("# Nota de riesgo de la SBP (D-116)\n\n" + p.sbp.nota.strip() + "\n", encoding="utf-8")
    manifest = json.loads((raiz / "data" / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version", "?"))
    n_archivos = sum(1 for f in carpeta.rglob("*") if f.is_file()) + 1   # + LEEME
    (carpeta / p.archivo_leeme).write_text(_leeme(cfg, version, n_archivos), encoding="utf-8")
    hallazgos = revisar_carpeta(carpeta, cfg, restringidos=valores_restringidos(cfg, raiz))
    if hallazgos:
        shutil.rmtree(carpeta)
        raise ErrorPaquete("el paquete contiene material prohibido y se descartó:\n" + "\n".join(f"  {h}" for h in hallazgos))
    archivos = {f.relative_to(carpeta).as_posix(): {"sha256": sha256(f), "bytes": f.stat().st_size}
                for f in sorted(carpeta.rglob("*")) if f.is_file()}
    (carpeta / p.archivo_checksums).write_text("".join(f"{v['sha256']}  {k}\n" for k, v in archivos.items()), encoding="utf-8")
    indice = {"paquete": "Panamá · Señales y Evidencias v1", "version_snapshot": version, "commit": _commit(raiz),
              "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "n_archivos": len(archivos),
              "bytes_total": sum(v["bytes"] for v in archivos.values()), "sbp_incluida": p.sbp.incluir, "archivos": archivos}
    (carpeta / p.archivo_indice).write_text(json.dumps(indice, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return indice


def verificar(cfg: ConfigEntrega | None = None, raiz: Path = RAIZ, carpeta: Path | None = None) -> list[Hallazgo]:
    """Revisa un paquete existente: que esté, que los checksums coincidan y que no tenga material prohibido."""
    cfg = cfg or cargar_entrega()
    carpeta = carpeta or raiz / cfg.paquete.carpeta
    if not carpeta.is_dir():
        return [Hallazgo("paquete_ausente", str(carpeta), "no existe: correr `poetry run python -m scripts.empaquetar_datos`")]
    hallazgos = revisar_carpeta(carpeta, cfg, omitir={cfg.paquete.archivo_checksums}, restringidos=valores_restringidos(cfg, raiz))
    sumas = carpeta / cfg.paquete.archivo_checksums
    if not sumas.is_file():
        return [*hallazgos, Hallazgo("checksums_ausentes", cfg.paquete.archivo_checksums, "falta el archivo de checksums")]
    listados: set[str] = set()
    for linea in sumas.read_text(encoding="utf-8").splitlines():
        suma, _, rel = linea.partition("  ")
        listados.add(rel)
        f = carpeta / rel
        if not f.is_file():
            hallazgos.append(Hallazgo("archivo_faltante", rel, "está en los checksums pero no en el paquete"))
        elif sha256(f) != suma:
            hallazgos.append(Hallazgo("checksum", rel, "el SHA-256 no coincide"))
    propios = {cfg.paquete.archivo_checksums, cfg.paquete.archivo_indice}     # se escriben después de calcular las sumas
    for f in sorted(carpeta.rglob("*")):
        rel = f.relative_to(carpeta).as_posix()
        if f.is_file() and rel not in listados and rel not in propios:
            hallazgos.append(Hallazgo("archivo_no_listado", rel, "está en el paquete pero no en los checksums (agregado después de construir)"))
    return hallazgos


def escribir_manifest(indice: dict[str, Any], cfg: ConfigEntrega, raiz: Path = RAIZ) -> Path:
    """Escribe lo único que se versiona del paquete: su índice con checksums (sin la fecha, para que sea estable)."""
    ruta = raiz / cfg.paquete.manifest_salida
    ruta.parent.mkdir(parents=True, exist_ok=True)
    estable = {k: v for k, v in indice.items() if k not in ("generado_utc", "commit")}
    ruta.write_text(json.dumps(estable, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ruta


def principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C-07: construye y revisa el paquete de datos redistribuible")
    parser.add_argument("--verificar", action="store_true", help="no construye: revisa el paquete existente")
    args = parser.parse_args(argv)
    cfg = cargar_entrega()
    if args.verificar:
        hallazgos = verificar(cfg)
        for h in hallazgos:
            print(f"FALLA {h}", file=sys.stderr)
        print("Paquete OK" if not hallazgos else f"{len(hallazgos)} hallazgos")
        return 1 if hallazgos else 0
    try:
        indice = construir(cfg)
    except ErrorPaquete as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ruta = escribir_manifest(indice, cfg)
    print(f"Paquete en {RAIZ / cfg.paquete.carpeta}: {indice['n_archivos']} archivos, {indice['bytes_total'] / 1e6:.2f} MB, SBP incluida: {indice['sbp_incluida']}")
    print(f"Índice versionable: {ruta.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
