"""Esquemas pydantic de las salidas del LLM y de los paquetes (editorial, investigación, boletín).

Por ahora solo existe el BORRADOR del paso 1 de la generación (afirmaciones citadas, E0-07).
Se completa en E1-12: citas por campo validadas contra la ficha, reglas por tipo (D-41) y los
límites de ``docs/salidas.md``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TipoAfirmacion = Literal["hecho", "declaración", "inferencia", "hipótesis"]

# Prefijos de ID estables (CLAUDE.md, D-63). El patrón se valida en código y no en el JSON Schema
# que se pasa a Ollama, para no depender del soporte de ``pattern`` en su gramática.
PATRON_ID_REGISTRO = re.compile(r"^(NOT-[0-9a-f]{10}|IND-[A-Z]{3}-[^\s]+-\d{4}|SIS-\S+|SBP-\S+|GRP-\S+|CASO-\d+|SYN-\S+)$")


class Cita(BaseModel):
    """Cita válida = ID del registro + campo (ej. ``IND-PAN-FP.CPI.TOTL.ZG-2023`` · ``valor``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="ID del registro de evidencia, exacto")
    campo: str = Field(min_length=1, description="Campo del registro, exacto")

    @field_validator("id")
    @classmethod
    def _id_con_prefijo(cls, valor: str) -> str:
        if not PATRON_ID_REGISTRO.match(valor):
            raise ValueError(f"ID sin prefijo estable válido: {valor!r}")
        return valor


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


class ParComparado(BaseModel):
    """Resultado de comparar dos titulares candidatos a contradicción (D-23).

    El LLM solo dice si el par es una **posible** contradicción y cita, literalmente, el fragmento de cada titular en que se
    nota. No hay texto libre: lo que se muestra al usuario es la etiqueta fija de ``config/prioridad.yaml``.
    """

    model_config = ConfigDict(extra="forbid")

    id_a: str = Field(min_length=1, description="ID de la noticia A, exacto")
    id_b: str = Field(min_length=1, description="ID de la noticia B, exacto")
    posible_contradiccion: bool
    fragmento_a: str = Field(default="", description="Fragmento literal del titular A; vacío si no hay posible contradicción")
    fragmento_b: str = Field(default="", description="Fragmento literal del titular B; vacío si no hay posible contradicción")

    @model_validator(mode="after")
    def _con_fragmentos(self) -> ParComparado:
        if self.posible_contradiccion and not (self.fragmento_a.strip() and self.fragmento_b.strip()):
            raise ValueError(f"{self.id_a}/{self.id_b}: una posible contradicción cita un fragmento literal de cada titular")
        return self


class ComparacionContradicciones(BaseModel):
    """Salida de la comparación de los pares candidatos de un grupo (uno por par, en cualquier orden)."""

    model_config = ConfigDict(extra="forbid")

    pares: list[ParComparado] = Field(min_length=1)


def esquema_json_comparacion() -> dict[str, Any]:
    """JSON Schema de ``ComparacionContradicciones``, para el parámetro ``format`` de Ollama."""
    return ComparacionContradicciones.model_json_schema()
