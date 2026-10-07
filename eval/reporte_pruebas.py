"""Reporte de las pruebas de aceptación T01–T10 (E1-17), importable en la base *Pruebas* de Notion.

Corre cada prueba por su marcador de pytest (``-m t01`` … ``-m t10``), lee el resultado del JUnit XML y escribe
``outputs/pruebas.csv`` con las columnas exactas de la base de Notion (``notion/bases/Pruebas.csv``). Los datos descriptivos
(caso de uso, entrada, resultado esperado, tareas, archivo) salen de esa exportación; el estado y lo observado, de la ejecución.

Reglas del estado:

* **Pasa:** el marcador tiene al menos una prueba, y ninguna falla, da error ni se omite.
* **Falla:** cualquier otra cosa (incluido «0 pruebas» o un error de colección). Nunca se rebaja a Pendiente para taparla.
* **Pendiente:** el test pasa, pero queda una parte que solo hace una persona (T09: boletín bancario de E2-02; T10: ensayo C-04).
  Se dice en *Resultado observado*; la prueba no se da por cerrada.

Una prueba que falla se registra en Notion (estado *Falla*) **antes** de corregirla (docs/REVISION.md, paso 3): este reporte no
escribe en Notion; la persona lo importa.

Uso: ``poetry run python -m eval.reporte_pruebas [--salida outputs/pruebas.csv]``.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from src.configuracion import RAIZ

PLANTILLA = RAIZ / "notion" / "bases" / "Pruebas.csv"
SALIDA = RAIZ / "outputs" / "pruebas.csv"
COLUMNAS = (
    "Prueba", "ID", "Caso de uso", "Entrada", "Resultado esperado", "Resultado observado",
    "Evidencia de ejecución", "Estado", "Corrección aplicada", "Tareas relacionadas", "Archivo de test",
)
IDS = tuple(f"T{n:02d}" for n in range(1, 11))
PENDIENTES = {
    "T09": "pendiente la parte del boletín bancario (E2-02); el test cubre solo el brief editorial",
    "T10": "pendiente el ensayo C-04 con Wi-Fi apagado y su evidencia en Notion; el test cubre el recorrido con snapshot y caché",
}
ESTADO_PASA, ESTADO_FALLA, ESTADO_PENDIENTE = "Pasa", "Falla", "Pendiente"


@dataclass(frozen=True)
class ResultadoPrueba:
    """Conteo de un marcador de pytest."""

    total: int
    fallidas: int = 0
    errores: int = 0
    omitidas: int = 0

    @property
    def pasan(self) -> int:
        return self.total - self.fallidas - self.errores - self.omitidas

    @property
    def limpio(self) -> bool:
        return self.total > 0 and self.fallidas == 0 and self.errores == 0 and self.omitidas == 0


def leer_plantilla(ruta: Path = PLANTILLA) -> list[dict[str, str]]:
    """Las filas T01–T10 de la exportación de la base *Pruebas* (se descartan las X0n)."""
    with ruta.open(encoding="utf-8", newline="") as f:
        filas = [fila for fila in csv.DictReader(f) if fila["ID"] in IDS]
    return sorted(filas, key=lambda fila: IDS.index(fila["ID"]))


def leer_junit(ruta: Path) -> ResultadoPrueba:
    """Cuenta pruebas, fallas, errores y omitidas de un JUnit XML; falla si no es uno."""
    raiz = ET.parse(ruta).getroot()
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    if not suites:
        raise ValueError(f"{ruta} no es un JUnit XML de pytest")
    suma = lambda atributo: sum(int(s.get(atributo, 0)) for s in suites)  # noqa: E731
    return ResultadoPrueba(suma("tests"), suma("failures"), suma("errors"), suma("skipped"))


def comando(id_prueba: str) -> list[str]:
    """El comando que ejecuta una prueba por su marcador."""
    return ["pytest", "-q", "tests/", "-m", id_prueba.lower()]


def ejecutar(id_prueba: str) -> ResultadoPrueba:
    """Corre el marcador de ``id_prueba`` en un proceso aparte y devuelve su conteo."""
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        orden = [sys.executable, "-m", *comando(id_prueba), "-p", "no:cacheprovider", f"--junitxml={xml}"]
        subprocess.run(orden, cwd=RAIZ, capture_output=True, check=False)
        if not xml.exists():
            return ResultadoPrueba(total=0, errores=1)
        return leer_junit(xml)


def _observado(r: ResultadoPrueba) -> str:
    partes = [f"{r.pasan} de {r.total} pruebas pasan"]
    for n, singular, plural in ((r.fallidas, "fallida", "fallidas"), (r.errores, "con error", "con error"), (r.omitidas, "omitida", "omitidas")):
        if n:
            partes.append(f"{n} {singular if n == 1 else plural}")
    return "; ".join(partes)


def construir_filas(plantilla: list[dict[str, str]], resultados: dict[str, ResultadoPrueba], pendientes: dict[str, str]) -> list[dict[str, str]]:
    """Mezcla la plantilla de Notion con lo observado; el estado sale solo de la ejecución."""
    filas: list[dict[str, str]] = []
    for base in plantilla:
        id_prueba = base["ID"]
        r = resultados[id_prueba]
        fila = {c: base.get(c, "") for c in COLUMNAS}
        observado = _observado(r)
        if not r.limpio:
            estado = ESTADO_FALLA
        elif id_prueba in pendientes:
            estado, observado = ESTADO_PENDIENTE, f"{observado}; {pendientes[id_prueba]}"
        else:
            estado = ESTADO_PASA
        fila.update({
            "Resultado observado": observado,
            "Evidencia de ejecución": "poetry run " + " ".join(comando(id_prueba)),
            "Estado": estado,
        })
        filas.append(fila)
    return filas


def escribir_csv(filas: list[dict[str, str]], destino: Path) -> None:
    """Escribe el CSV con las columnas de Notion, en UTF-8."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(COLUMNAS))
        escritor.writeheader()
        escritor.writerows(filas)


def main(argv: list[str] | None = None) -> int:
    """CLI: ejecuta T01–T10 y escribe el reporte; sale con 1 si alguna falla."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", type=Path, default=SALIDA)
    args = ap.parse_args(argv)
    plantilla = leer_plantilla()
    filas = construir_filas(plantilla, {f["ID"]: ejecutar(f["ID"]) for f in plantilla}, PENDIENTES)
    escribir_csv(filas, args.salida)
    for f in filas:
        print(f"{f['ID']}  {f['Estado']:<9} {f['Resultado observado']}")
    print(f"→ {args.salida}")
    return 1 if any(f["Estado"] == ESTADO_FALLA for f in filas) else 0


if __name__ == "__main__":
    raise SystemExit(main())
