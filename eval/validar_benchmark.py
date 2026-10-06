"""Validador del benchmark de desarrollo (E0-06).

Uso::

    poetry run python -m eval.validar_benchmark [--ruta benchmark/benchmark_dev.jsonl] \
        [--snapshot data/processed]

Valida cada línea con un modelo pydantic estricto, las reglas cruzadas por tipo,
el total y la proporción de tipos (``config/benchmark.yaml``) y, si hay snapshot,
que los IDs de evidencia existan. Imprime el conteo por tipo y sale con código
distinto de cero ante cualquier error.

También comprueba que ningún archivo versionado referencie un conjunto
reservado (D-64): el equipo nunca lo crea, lo pide ni lo lee.

Nota: las metas se leen aquí con ``yaml.safe_load`` y un modelo pydantic local;
al integrarse ``src.configuracion`` en main, la carga debe moverse allí.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config" / "benchmark.yaml"
RUTA_BENCHMARK = RAIZ / "benchmark" / "benchmark_dev.jsonl"

TipoConsulta = Literal[
    "respuesta_sustentada", "contradiccion_ambiguedad", "sin_respuesta", "adversarial"
]
PREFIJOS_ID = ("NOT-", "IND-", "SIS-", "SBP-", "GRP-", "SYN-")
PREFIJOS_EN_SNAPSHOT = ("NOT-", "IND-", "SIS-")
PATRON_ID = re.compile(r"^BDEV-\d{3}$")
# Las etiquetas las ponen personas (E0-06): se rechazan marcadores de IA.
PATRON_IA = re.compile(
    r"\b(claude|ia|ai|asistente|assistant|gpt|chatgpt|llm|modelo|bot|copilot|gemini|deepseek|ollama)\b",
    re.IGNORECASE,
)
# Textos provisorios de una propuesta sin revisar: no cuentan como etiqueta humana.
PATRON_PENDIENTE = re.compile(r"pendiente|por\s*asignar|sin\s*etiquetar|tbd|todo|xxx", re.IGNORECASE)


class Metas(BaseModel):
    """Total y proporción de tipos del benchmark de desarrollo."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(gt=0)
    tipos: dict[TipoConsulta, int]

    def model_post_init(self, _contexto: object) -> None:
        if set(self.tipos) != set(get_args(TipoConsulta)):
            raise ValueError("deben estar los cuatro tipos")
        if sum(self.tipos.values()) != self.total:
            raise ValueError("la suma de tipos no coincide con el total")


class LineaBenchmark(BaseModel):
    """Una línea de ``benchmark_dev.jsonl`` con exactamente los campos del spec."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    tipo: TipoConsulta
    consulta: str
    respuesta_esperada: str | None
    ids_evidencia: list[str]
    debe_abstenerse: bool
    sintetico: bool
    etiquetado_por: str

    @field_validator("id")
    @classmethod
    def _id_estable(cls, valor: str) -> str:
        if not PATRON_ID.match(valor):
            raise ValueError("el id debe tener la forma BDEV-NNN")
        return valor

    @field_validator("consulta", "etiquetado_por")
    @classmethod
    def _no_vacio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("no puede estar vacío")
        return valor

    @field_validator("etiquetado_por")
    @classmethod
    def _persona(cls, valor: str) -> str:
        if PATRON_IA.search(valor):
            raise ValueError("las etiquetas las ponen personas, no una IA")
        if PATRON_PENDIENTE.search(valor):
            raise ValueError("etiqueta pendiente de revisión humana")
        return valor

    @field_validator("ids_evidencia")
    @classmethod
    def _prefijos(cls, valores: list[str]) -> list[str]:
        for valor in valores:
            if not valor.startswith(PREFIJOS_ID) or valor in PREFIJOS_ID:
                raise ValueError(f"id de evidencia sin prefijo válido: {valor!r}")
        if len(set(valores)) != len(valores):
            raise ValueError("ids_evidencia repetidos")
        return valores

    def reglas_cruzadas(self) -> list[str]:
        """Devuelve los incumplimientos de las reglas entre campos."""
        errores: list[str] = []
        if self.tipo == "sin_respuesta":
            if not self.debe_abstenerse:
                errores.append("sin_respuesta exige debe_abstenerse=true")
            if self.respuesta_esperada is not None:
                errores.append("sin_respuesta exige respuesta_esperada=null")
        if self.tipo == "respuesta_sustentada":
            if self.debe_abstenerse:
                errores.append("respuesta_sustentada exige debe_abstenerse=false")
            if self.respuesta_esperada is None or not self.respuesta_esperada.strip():
                errores.append("respuesta_sustentada exige respuesta_esperada")
            if not self.ids_evidencia:
                errores.append("respuesta_sustentada exige ids_evidencia no vacío")
        if not self.sintetico and any(i.startswith("SYN-") for i in self.ids_evidencia):
            errores.append("ids SYN- solo se permiten con sintetico=true")
        return errores


def cargar_metas(ruta: Path = RUTA_CONFIG) -> Metas:
    """Lee y valida las metas de ``config/benchmark.yaml``."""
    return Metas.model_validate(yaml.safe_load(ruta.read_text(encoding="utf-8")))


def ids_del_snapshot(carpeta: Path) -> set[str]:
    """Reúne los IDs NOT-, IND- y SIS- presentes en los archivos del snapshot."""
    ids: set[str] = set()
    noticias = carpeta / "noticias.csv"
    if noticias.is_file():
        with noticias.open(encoding="utf-8", newline="") as f:
            ids.update(fila["id_noticia"] for fila in csv.DictReader(f))
    indicadores = carpeta / "indicadores.csv"
    if indicadores.is_file():
        with indicadores.open(encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                ids.add(f"IND-{fila['pais_iso3']}-{fila['indicador_id']}-{fila['anio']}")
    eventos = carpeta / "eventos.geojson"
    if eventos.is_file():
        datos = json.loads(eventos.read_text(encoding="utf-8"))
        for rasgo in datos.get("features", []):
            id_ = rasgo.get("id") or rasgo.get("properties", {}).get("id")
            if id_:
                ids.add(str(id_) if str(id_).startswith("SIS-") else f"SIS-{id_}")
    return ids


def validar_lineas(
    lineas: Iterable[str], metas: Metas, snapshot: set[str] | None = None
) -> tuple[Counter[str], list[str]]:
    """Valida las líneas JSONL; devuelve el conteo por tipo y la lista de errores."""
    errores: list[str] = []
    conteo: Counter[str] = Counter()
    vistos: set[str] = set()
    n = 0
    for numero, texto in enumerate(lineas, start=1):
        if not texto.strip():
            errores.append(f"línea {numero}: línea vacía")
            continue
        n += 1
        try:
            linea = LineaBenchmark.model_validate_json(texto, strict=True)
        except ValidationError as exc:
            for e in exc.errors():
                campo = ".".join(str(p) for p in e["loc"]) or "(línea)"
                errores.append(f"línea {numero}: {campo}: {e['msg']}")
            continue
        conteo[linea.tipo] += 1
        if linea.id in vistos:
            errores.append(f"línea {numero}: id duplicado {linea.id}")
        vistos.add(linea.id)
        errores.extend(f"línea {numero} ({linea.id}): {m}" for m in linea.reglas_cruzadas())
        if snapshot is not None:
            for id_ in linea.ids_evidencia:
                if id_.startswith(PREFIJOS_EN_SNAPSHOT) and id_ not in snapshot:
                    errores.append(f"línea {numero} ({linea.id}): {id_} no está en el snapshot")
    if n != metas.total:
        errores.append(f"total {n} distinto de {metas.total}")
    for tipo, meta in metas.tipos.items():
        if conteo[tipo] != meta:
            errores.append(f"tipo {tipo}: {conteo[tipo]} distinto de {meta}")
    return conteo, errores


# Las expresiones no se auto-coinciden: usan clases de caracteres.
PATRONES_RESERVADO = (
    re.compile(r"benchmark[_-]reservad[oa]", re.IGNORECASE),
    re.compile(r"reservad[oa]\.jsonl", re.IGNORECASE),
    re.compile(r"benchmark[/_-]test\b", re.IGNORECASE),
)
# Prosa que enuncia la regla; no cuenta como referencia.
PREFIJOS_EXCLUIDOS = ("specs/", "docs/", "notion/")
ARCHIVOS_EXCLUIDOS = ("CLAUDE.md", "README.md", "benchmark/README.md")


def archivos_versionados(raiz: Path = RAIZ) -> list[str]:
    """Lista los archivos versionados con ``git ls-files``."""
    salida = subprocess.run(
        ["git", "ls-files"], cwd=raiz, capture_output=True, text=True, check=True
    )
    return salida.stdout.splitlines()


def referencias_reservado(archivos: Iterable[str], raiz: Path = RAIZ) -> list[str]:
    """Busca referencias a un conjunto reservado en los archivos de texto dados."""
    hallazgos: list[str] = []
    for ruta in archivos:
        if ruta.startswith(PREFIJOS_EXCLUIDOS) or ruta in ARCHIVOS_EXCLUIDOS:
            continue
        if any(p.search(ruta) for p in PATRONES_RESERVADO):
            hallazgos.append(f"{ruta}: ruta que referencia un conjunto reservado")
        try:
            texto = (raiz / ruta).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binario o ilegible
        for numero, linea in enumerate(texto.splitlines(), start=1):
            if any(p.search(linea) for p in PATRONES_RESERVADO):
                hallazgos.append(f"{ruta}:{numero}: referencia a un conjunto reservado")
    return hallazgos


def main(argv: list[str] | None = None) -> int:
    """CLI: valida el benchmark e imprime el conteo por tipo."""
    parser = argparse.ArgumentParser(description="Valida el benchmark de desarrollo (E0-06).")
    parser.add_argument("--ruta", type=Path, default=RUTA_BENCHMARK)
    parser.add_argument("--snapshot", type=Path, default=None)
    args = parser.parse_args(argv)

    metas = cargar_metas()
    if not args.ruta.is_file():
        print(f"ERROR: no existe {args.ruta}", file=sys.stderr)
        return 1
    snapshot = None
    if args.snapshot is not None:
        if args.snapshot.exists():
            snapshot = ids_del_snapshot(args.snapshot)
        else:
            print(f"Aviso: no existe el snapshot {args.snapshot}; se omite ese chequeo")
    lineas = args.ruta.read_text(encoding="utf-8").splitlines()
    conteo, errores = validar_lineas(lineas, metas, snapshot)
    try:
        errores.extend(referencias_reservado(archivos_versionados()))
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Aviso: no es un repositorio git; se omite la búsqueda de referencias reservadas")

    print(f"Benchmark: {args.ruta}")
    for tipo, meta in metas.tipos.items():
        print(f"  {tipo}: {conteo[tipo]} / {meta}")
    print(f"  total: {sum(conteo.values())} / {metas.total}")
    if errores:
        print(f"\n{len(errores)} error(es):", file=sys.stderr)
        for e in errores:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
