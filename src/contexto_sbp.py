"""Vínculo de un grupo con las series agregadas de la SBP · E3-02, fuente D (solo banca).

Un dato de la SBP es **contexto** del tema bancario, nunca prueba de causa, de pérdida ni de riesgo de una entidad. Reglas:

* **Solo reglas de vínculo con ``fuente: sbp``** en ``vinculos.yaml`` (hoy ``banca``, D-125). Las demás devuelven ``None`` y el
  llamador sigue con su regla de indicadores.
* **Qué se vincula:** de cada serie agregada de ``sbp_series.csv`` el último período con valor. Es un dato **mensual de 2024**: no
  es el mes de la noticia, y la nota de cada fila lo dice (no se sustituye un período por otro en silencio).
* **Sin dato:** si ninguna serie tiene un valor (todo nulo) o no hay archivo, el grupo queda ``sin_dato_en_periodo``; nunca se
  rellena con 0.
* **Resultado:** una fila de ``vinculos`` por serie (``fuente = 'sbp'``, ``rol = 'sistema'``, ``tipo`` = la relación declarada en
  ``vinculos.yaml``) con ``id_evidencia = SBP-<serie>-<período>``, valor, unidad, período, informe y página de origen.

Este módulo es puro (solo lee el CSV): ``src.contexto`` elige la regla de vínculo del grupo y escribe las filas en ``vinculos``.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import db
from src.configuracion import ConfigFuentes, ConfigVinculos

logger = logging.getLogger(__name__)

FUENTE_SBP = "sbp"                 # valor de ``fuente`` en vinculos.yaml y de ``vinculos.fuente``
ROL_SISTEMA = "sistema"            # ``vinculos.rol`` de un dato agregado del sistema bancario
SIN_DATO_EN_PERIODO = "sin_dato_en_periodo"
COLUMNAS = (
    "id_serie", "nombre_serie", "periodo", "valor", "unidad", "informe", "pagina", "url", "fecha_extraccion", "condiciones",
)


class ErrorSbp(ValueError):
    """``sbp_series.csv`` no tiene la forma del contrato."""


@dataclass(frozen=True)
class DatoSbp:
    """Una fila de ``sbp_series.csv``; ``valor`` nulo = la SBP no lo trae (nunca 0)."""

    id_serie: str
    nombre_serie: str
    periodo: str
    valor: float | None
    unidad: str
    informe: str
    pagina: str
    url: str
    fecha_extraccion: str

    @property
    def id(self) -> str:
        """``SBP-<serie>-<período>`` (``id_serie`` ya lleva el prefijo ``SBP-``)."""
        return f"{self.id_serie}-{self.periodo}"


def cargar_series(ruta: Path) -> list[DatoSbp]:
    """Las filas de ``sbp_series.csv``, ordenadas por serie y período. Falla si faltan columnas o un valor no es un número."""
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        if tuple(lector.fieldnames or ()) != COLUMNAS:
            raise ErrorSbp(f"{ruta.name}: columnas {lector.fieldnames}; se esperaban {list(COLUMNAS)}")
        filas = list(lector)
    datos = []
    for f in filas:
        try:
            valor = float(f["valor"]) if f["valor"] != "" else None   # un nulo es nulo, nunca 0
        except ValueError as exc:
            raise ErrorSbp(f"{f['id_serie']} {f['periodo']}: valor no numérico {f['valor']!r}") from exc
        datos.append(DatoSbp(f["id_serie"], f["nombre_serie"], f["periodo"], valor, f["unidad"], f["informe"], f["pagina"], f["url"], f["fecha_extraccion"]))
    return sorted(datos, key=lambda d: (d.id_serie, d.periodo))


def aplica(regla_vinculo: str | None, vinculos: ConfigVinculos) -> bool:
    """``True`` solo si la regla de vínculo se vincula a la SBP según ``vinculos.yaml``."""
    regla = vinculos.reglas_vinculo.get(regla_vinculo) if regla_vinculo else None
    return regla is not None and regla.fuente == FUENTE_SBP


def ultimos_por_serie(datos: Sequence[DatoSbp]) -> list[DatoSbp]:
    """El último período con valor de cada serie (una serie sin ningún valor no aporta)."""
    ultimo: dict[str, DatoSbp] = {}
    for d in datos:
        if d.valor is not None and (d.id_serie not in ultimo or d.periodo > ultimo[d.id_serie].periodo):
            ultimo[d.id_serie] = d
    return [ultimo[k] for k in sorted(ultimo)]


def _fila(id_grupo: str, **campos: Any) -> dict[str, Any]:
    fila = dict.fromkeys(db.columnas("vinculos"))
    fila.update(id_grupo=id_grupo, fuente=FUENTE_SBP, rol=ROL_SISTEMA, **campos)
    return fila


def vincular_grupo(
    id_grupo: str,
    nombre_regla: str | None,
    datos: Sequence[DatoSbp],
    vinculos: ConfigVinculos,
    fuentes: ConfigFuentes,
) -> list[dict[str, Any]] | None:
    """Filas de ``vinculos`` de un grupo bancario; ``None`` si su regla de vínculo no se vincula a la SBP."""
    if not aplica(nombre_regla, vinculos):
        return None
    regla_vinculo = vinculos.reglas_vinculo[str(nombre_regla)]
    regla = vinculos.sbp.plantilla_regla.format(regla=nombre_regla)
    elegidos = ultimos_por_serie(datos)
    if not elegidos:
        return [_fila(id_grupo, regla=regla, motivo_sin_vinculo=SIN_DATO_EN_PERIODO)]
    filas = []
    for d in elegidos:
        nota = vinculos.sbp.nota_periodo.format(periodo=d.periodo)
        filas.append(
            _fila(
                id_grupo,
                id_evidencia=d.id,
                tipo=regla_vinculo.relacion,
                regla=regla,
                limitacion=" ".join([regla_vinculo.limitacion, nota, fuentes.sbp.limitacion.strip()]),
                indicador_id=d.id_serie,
                unidad=d.unidad,
                valor=d.valor,
                fecha_extraccion=d.fecha_extraccion,
                periodo=d.periodo,
                informe=d.informe,
                pagina=d.pagina,
                url_fuente=d.url,
            )
        )
    return filas
