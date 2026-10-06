"""Esquemas pydantic de las salidas del LLM y de los paquetes (editorial, investigación, boletín).

Por ahora solo existe el BORRADOR del paso 1 de la generación (afirmaciones citadas, E0-07).
Se completa en E1-12: citas por campo validadas contra la ficha, reglas por tipo (D-41) y los
límites de ``docs/salidas.md``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TipoAfirmacion = Literal["hecho", "declaración", "inferencia", "hipótesis"]


class Cita(BaseModel):
    """Cita válida = ID del registro + campo (ej. ``IND-PAN-FP.CPI.TOTL.ZG-2023`` · ``valor``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="ID del registro de evidencia, exacto")
    campo: str = Field(min_length=1, description="Campo del registro, exacto")


class Afirmacion(BaseModel):
    """Una afirmación atómica.

    hecho/declaración citan fuentes; inferencia/hipótesis citan las afirmaciones en que se basan.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="A1, A2, A3...")
    tipo: TipoAfirmacion
    texto: str = Field(min_length=1)
    citas: list[Cita] = Field(default_factory=list)
    base: list[str] = Field(default_factory=list, description="id de afirmaciones base")

    @model_validator(mode="after")
    def _reglas_por_tipo(self) -> Afirmacion:
        if self.tipo in ("hecho", "declaración") and not self.citas:
            raise ValueError(f"{self.id}: {self.tipo} requiere al menos una cita")
        if self.tipo in ("inferencia", "hipótesis") and not self.base:
            raise ValueError(f"{self.id}: {self.tipo} requiere afirmaciones base")
        return self


class AfirmacionesCitadas(BaseModel):
    """Salida del paso 1: lista de afirmaciones citadas (BORRADOR, E1-12 lo completa)."""

    model_config = ConfigDict(extra="forbid")

    afirmaciones: list[Afirmacion] = Field(min_length=1)


def esquema_json_afirmaciones() -> dict[str, Any]:
    """JSON Schema de ``AfirmacionesCitadas``, para el parámetro ``format`` de Ollama."""
    return AfirmacionesCitadas.model_json_schema()
