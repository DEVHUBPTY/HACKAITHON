"""Puntaje determinista, estado de evidencia, vacíos y contradicciones; pesos y umbrales en config/*.yaml."""

from __future__ import annotations

from src.configuracion import ReglasV13

COMPONENTES = ("R", "I", "U", "N", "E")


def puntaje_total(componentes: dict[str, float], reglas: ReglasV13) -> float:
    """P = Σ peso × componente, con los componentes R, I, U, N, E en [0, 1] y los pesos de ``reglas``."""
    return sum(getattr(reglas.pesos, k) * componentes[k] for k in COMPONENTES)


def rango_de(p: float, reglas: ReglasV13) -> str:
    """Rango ``bajo``, ``medio`` o ``alto`` según ``reglas.rangos`` (el último incluye su límite superior)."""
    if p < reglas.rangos.bajo.hasta:
        return "bajo"
    return "medio" if p < reglas.rangos.medio.hasta else "alto"
