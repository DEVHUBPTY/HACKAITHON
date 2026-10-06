"""Estimación OFFLINE de las consultas de GDELT sobre los crudos ya descargados (E0-04, seguimiento).

No hace red. Para cada tema pregunta: de los artículos que bajaron las consultas anteriores, ¿qué
fracción habría coincidido con los términos nuevos en el TÍTULO, y qué fracción viene de medios de
Panamá? Es solo una estimación: GDELT busca en el cuerpo del artículo y aquí solo hay título y país
de la fuente, así que el título subestima la coincidencia real.

Uso: ``poetry run python -m scripts.estimar_consultas_gdelt [carpeta_gdelt]``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from scripts import conversion
from src import configuracion, consultas_gdelt


def leer_articulos(carpeta: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """``{tema: {url: articulo}}`` deduplicado por URL, de los crudos ``gdelt_*.json`` válidos."""
    por_tema: dict[str, dict[str, dict[str, Any]]] = {}
    for ruta in sorted(carpeta.glob("gdelt_*.json")):
        m = conversion.PATRON_ARCHIVO_GDELT.match(ruta.name)
        if not m:
            continue
        datos = json.loads(ruta.read_text("utf-8"), strict=False)
        if not isinstance(datos, dict):
            continue
        for a in datos.get("articles") or []:
            por_tema.setdefault(m["tema"], {}).setdefault(a.get("url", ""), a)
    return por_tema


def estimar(por_tema: dict[str, dict[str, dict[str, Any]]], consultas: dict[str, Any]) -> dict[str, Any]:
    """Fracciones por tema: fuente en Panamá, título con frases de la pata internacional y con ambas patas."""
    salida: dict[str, Any] = {}
    for tema, arts in sorted(por_tema.items()):
        definicion = consultas.get(tema)
        if not isinstance(definicion, dict):
            continue
        locales = definicion["locales"]["terminos"]
        inter = definicion["internacional"]["terminos"]
        n = len(arts)
        de_panama = {u for u, a in arts.items() if (a.get("sourcecountry") or "").lower() == "panama"}
        con_inter = {u for u, a in arts.items() if consultas_gdelt.titulo_coincide(a.get("title", ""), inter)}
        con_local = {u for u in de_panama if consultas_gdelt.titulo_coincide(arts[u].get("title", ""), locales)}
        # Lo que las consultas nuevas habrían devuelto (aprox. por título): pata local sobre medios de
        # Panamá + pata internacional sobre el resto.
        nuevos = con_local | (con_inter - de_panama)
        salida[tema] = {
            "n_articulos_unicos": n,
            "fuente_en_panama": len(de_panama),
            "titulo_coincide_pata_internacional": len(con_inter),
            "titulo_coincide_pata_local_en_medios_de_panama": len(con_local),
            "habrian_pasado_aprox": len(nuevos),
            "fraccion_que_habria_pasado": round(len(nuevos) / n, 3) if n else None,
        }
    return salida


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    carpeta = Path(args[0]) if args else conversion.RAIZ / "data" / "raw" / "gdelt"
    consultas = configuracion.cargar_fuentes().model_dump()["gdelt"]["consultas"]
    res = estimar(leer_articulos(carpeta), consultas)
    print(json.dumps({"nota": (
                "Estimación por título. Solo mide artículos que las consultas ANTERIORES ya devolvieron: dice cuánto "
                "ruido se filtraría, no cuántos artículos relevantes nuevos aparecerían (el recall nuevo no se puede "
                "medir offline). No sustituye una corrida real."
            ),
            "temas": res}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
