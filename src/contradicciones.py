"""Posibles contradicciones entre titulares de un grupo · E1-10, T05, CU-04, D-23.

Dos pasos, y el segundo nunca decide solo:

1. **Candidatos por reglas** (determinista, sin LLM): dos titulares de **procedencias distintas** del mismo grupo que dan
   **cifras distintas** sobre lo mismo (misma unidad) o usan **verbos opuestos** (``config/prioridad.yaml``).
2. **Comparación con el LLM**, solo de esos pares: devuelve si es una *posible* contradicción y un fragmento literal de cada
   titular (``src/esquemas.py``). No hay texto libre ni veredicto: lo que se muestra es la etiqueta fija «posible
   contradicción, verificar» con **ambas versiones y su fuente**. Los fragmentos se validan como subcadenas del titular.

**El LLM nunca cierra un par** (X21): todo candidato detectado por reglas queda ABIERTO para el estado de evidencia, diga lo que
diga el LLM. Su resultado es solo una **nota** para la persona (``nota_llm``: ``posible_contradiccion``, ``compatible`` o
``pendiente``, más los fragmentos literales). Solo una persona podrá cerrar un par (revisión, E1-16). Sin candidatos no se llama
al LLM (abstención antes de llamar). Si el proveedor no está configurado, no responde o devuelve algo inválido, la nota es
``pendiente`` y se registra el motivo; nunca se rompe el puntaje.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from src.configuracion import RAIZ, ConfigPrioridad, cargar_consulta
from src.esquemas import ComparacionContradicciones, esquema_json_comparacion
from src.evidencia import extraer_cifras
from src.limpieza import plano
from src.llm.proveedor import ErrorProveedor, Proveedor

logger = logging.getLogger(__name__)

REGLA_CIFRAS = "cifras_distintas"
REGLA_VERBOS = "verbos_opuestos"
ESTADO_VERIFICAR = "verificar"         # el único estado: detectada por reglas, abierta hasta que una persona la cierre
NOTA_POSIBLE = "posible_contradiccion"  # nota del LLM: también ve una posible contradicción (con fragmentos literales)
NOTA_COMPATIBLE = "compatible"          # nota del LLM: las versiones le parecen compatibles (el par sigue abierto)
NOTA_PENDIENTE = "pendiente"            # sin nota: no hay LLM, falló, o respondió algo inválido
CARPETA_PROMPTS = RAIZ / "prompts"
SEPARADOR_DETALLE = "; "
ESPACIOS = re.compile(r"\s+")


@dataclass(frozen=True)
class Candidato:
    """Un par de titulares candidato a contradicción, con la fuente de cada versión."""

    id_a: str
    id_b: str
    medio_a: str
    medio_b: str
    titular_a: str
    titular_b: str
    fecha_a: str | None
    fecha_b: str | None
    reglas: tuple[str, ...]
    detalle: str


@dataclass(frozen=True)
class Contradiccion:
    """Un candidato y la nota del LLM; el par está siempre abierto."""

    candidato: Candidato
    estado: str
    etiqueta: str
    nota_llm: str
    fragmento_a: str = ""
    fragmento_b: str = ""
    proveedor: str | None = None
    modelo: str | None = None
    motivo_pendiente: str | None = None

    @property
    def abierta(self) -> bool:
        """Siempre abierta: el LLM no la cierra (X21); solo una persona, en la revisión."""
        return True


# ------------------------------------------------------------------ candidatos por reglas


def _palabras(titulo: str) -> set[str]:
    return set(re.findall(r"\w+", plano(titulo)))


def _por_cifras(a: str, b: str, cfg: ConfigPrioridad) -> list[str]:
    """Detalle de cada par de cifras con la misma unidad y valor distinto."""
    detalles = []
    for ca in extraer_cifras(a, cfg):
        for cb in extraer_cifras(b, cfg):
            if ca.unidad and ca.unidad == cb.unidad and not math.isclose(ca.valor, cb.valor):
                detalles.append(f"{ca.texto} / {cb.texto}")
    return detalles


def _por_verbos(a: str, b: str, cfg: ConfigPrioridad) -> list[str]:
    """Detalle de cada par de verbos opuestos repartidos entre los dos titulares."""
    pa, pb = _palabras(a), _palabras(b)
    detalles = []
    for par in cfg.contradicciones.pares_opuestos:
        lado_a, lado_b = set(par.a), set(par.b)
        if (pa & lado_a and pb & lado_b) or (pa & lado_b and pb & lado_a):
            detalles.append(par.nombre)
    return detalles


def candidatos_de(
    miembros: Sequence[Mapping[str, object]], procedencia_de: Mapping[str, object], cfg: ConfigPrioridad
) -> list[Candidato]:
    """Pares de titulares del grupo con cifras distintas o verbos opuestos, ordenados por (id_a, id_b).

    ``procedencia_de`` asigna a cada ``id_noticia`` su procedencia: con ``solo_entre_procedencias`` los titulares de una misma
    procedencia (misma agencia o medio) no se comparan, porque son la misma versión.
    """
    filas = sorted(miembros, key=lambda m: str(m["id_noticia"]))
    candidatos: list[Candidato] = []
    for i, a in enumerate(filas):
        for b in filas[i + 1 :]:
            ia, ib = str(a["id_noticia"]), str(b["id_noticia"])
            if cfg.contradicciones.solo_entre_procedencias and procedencia_de.get(ia) is not None and procedencia_de.get(ia) == procedencia_de.get(ib):
                continue
            ta, tb = str(a.get("titulo_limpio") or ""), str(b.get("titulo_limpio") or "")
            reglas: list[str] = []
            detalles: list[str] = []
            if d := _por_cifras(ta, tb, cfg):
                reglas.append(REGLA_CIFRAS)
                detalles.extend(d)
            if d := _por_verbos(ta, tb, cfg):
                reglas.append(REGLA_VERBOS)
                detalles.extend(d)
            if reglas:
                candidatos.append(
                    Candidato(
                        ia, ib, str(a.get("medio") or ""), str(b.get("medio") or ""), ta, tb,
                        str(a.get("fecha_publicacion") or "") or None, str(b.get("fecha_publicacion") or "") or None,
                        tuple(reglas), SEPARADOR_DETALLE.join(detalles),
                    )
                )
    return candidatos


# ------------------------------------------------------------------ comparación con el LLM


def cargar_system(nombre: str) -> str:
    """Prompt de sistema con el JSON Schema de la salida incrustado."""
    plantilla = (CARPETA_PROMPTS / f"{nombre}.txt").read_text(encoding="utf-8")
    return plantilla.replace("{esquema}", json.dumps(esquema_json_comparacion(), ensure_ascii=False))


def _neutralizar(texto: str) -> str:
    """La evidencia es dato: se quitan las marcas de apertura y cierre de la etiqueta delimitadora."""
    d = cargar_consulta().delimitador_evidencia
    marcas = re.compile(re.escape(d.abre) + "|" + re.escape(d.cierra), re.IGNORECASE)
    return marcas.sub("", texto)


def mensaje_de_usuario(candidatos: Sequence[Candidato]) -> str:
    """Mensaje de usuario: los pares dentro de ``<evidencia>…</evidencia>``; las reglas van solo en el system prompt."""
    d = cargar_consulta().delimitador_evidencia
    bloques = []
    for n, c in enumerate(candidatos, start=1):
        bloques.append(
            f"par {n}\n"
            f"  id_a: {c.id_a}\n  medio_a: {_neutralizar(c.medio_a)}\n  fecha_publicacion_a: {c.fecha_a or 'desconocida'}\n  titulo_a: {_neutralizar(c.titular_a)}\n"
            f"  id_b: {c.id_b}\n  medio_b: {_neutralizar(c.medio_b)}\n  fecha_publicacion_b: {c.fecha_b or 'desconocida'}\n  titulo_b: {_neutralizar(c.titular_b)}"
        )
    return f"{d.abre}\n" + "\n".join(bloques) + f"\n{d.cierra}\n\nCompara cada par y responde con el JSON."


def _literal(fragmento: str, titular: str) -> bool:
    """El fragmento es subcadena exacta del titular (espacios en blanco normalizados)."""
    f, t = ESPACIOS.sub(" ", fragmento).strip(), ESPACIOS.sub(" ", titular)
    return bool(f) and f in t


def _pendiente(c: Candidato, cfg: ConfigPrioridad, motivo: str, proveedor: Proveedor | None) -> Contradiccion:
    return Contradiccion(
        c, ESTADO_VERIFICAR, cfg.contradicciones.etiqueta, NOTA_PENDIENTE,
        proveedor=proveedor.nombre if proveedor else None, modelo=proveedor.modelo if proveedor else None, motivo_pendiente=motivo,
    )


def comparar(
    candidatos: Sequence[Candidato], proveedor: Proveedor | None, cfg: ConfigPrioridad, system: str | None = None
) -> list[Contradiccion]:
    """Compara los candidatos de un grupo con el LLM; devuelve un resultado por candidato, en el mismo orden.

    Sin candidatos no hay llamada. Ante cualquier fallo del proveedor o de la salida, la nota es ``pendiente`` y el par sigue abierto.
    """
    if not candidatos:
        return []
    if proveedor is None:
        return [_pendiente(c, cfg, "sin proveedor de LLM configurado", None) for c in candidatos]
    tope = cfg.contradicciones.maximo_candidatos_por_grupo
    enviados, sobrantes = list(candidatos[:tope]), list(candidatos[tope:])
    resultados: dict[tuple[str, str], Contradiccion] = {(c.id_a, c.id_b): _pendiente(c, cfg, "sobre el tope de pares por grupo", proveedor) for c in sobrantes}
    try:
        crudo = proveedor.generar_json(system or cargar_system(cfg.contradicciones.prompt), mensaje_de_usuario(enviados), esquema_json_comparacion())
        salida = ComparacionContradicciones.model_validate_json(crudo)
    except ErrorProveedor as exc:
        logger.warning("LLM no disponible (%s): %d pares quedan sin nota del LLM", exc, len(enviados))
        resultados.update({(c.id_a, c.id_b): _pendiente(c, cfg, f"proveedor no disponible: {exc}", proveedor) for c in enviados})
    except (ValidationError, ValueError) as exc:
        logger.warning("Salida del LLM inválida (%s): %d pares quedan sin nota del LLM", str(exc).splitlines()[0], len(enviados))
        resultados.update({(c.id_a, c.id_b): _pendiente(c, cfg, "salida del LLM inválida", proveedor) for c in enviados})
    else:
        for c in enviados:
            resultados[(c.id_a, c.id_b)] = _resolver(c, salida, proveedor, cfg)
    return [resultados[(c.id_a, c.id_b)] for c in candidatos]


def _resolver(c: Candidato, salida: ComparacionContradicciones, proveedor: Proveedor, cfg: ConfigPrioridad) -> Contradiccion:
    """Resultado de un par: exactamente una respuesta para sus IDs y, si marca contradicción, fragmentos literales."""
    propias = [p for p in salida.pares if {p.id_a, p.id_b} == {c.id_a, c.id_b}]
    if len(propias) != 1:
        return _pendiente(c, cfg, "el LLM no respondió este par exactamente una vez", proveedor)
    p = propias[0]
    if not p.posible_contradiccion:
        return Contradiccion(c, ESTADO_VERIFICAR, cfg.contradicciones.etiqueta, NOTA_COMPATIBLE, proveedor=proveedor.nombre, modelo=proveedor.modelo)
    frag_a, frag_b = (p.fragmento_a, p.fragmento_b) if p.id_a == c.id_a else (p.fragmento_b, p.fragmento_a)
    if not (_literal(frag_a, c.titular_a) and _literal(frag_b, c.titular_b)):
        return _pendiente(c, cfg, "los fragmentos citados no son literales del titular", proveedor)
    return Contradiccion(c, ESTADO_VERIFICAR, cfg.contradicciones.etiqueta, NOTA_POSIBLE, frag_a.strip(), frag_b.strip(), proveedor.nombre, proveedor.modelo)


def evaluar_grupo(
    miembros: Sequence[Mapping[str, object]],
    procedencia_de: Mapping[str, object],
    proveedor: Proveedor | None,
    cfg: ConfigPrioridad,
    system: str | None = None,
) -> list[Contradiccion]:
    """Candidatos por reglas del grupo y su comparación con el LLM (que degrada a «pendiente» si falla)."""
    return comparar(candidatos_de(miembros, procedencia_de, cfg), proveedor, cfg, system)


def abiertas(contradicciones: Sequence[Contradiccion]) -> int:
    """Cuántas contradicciones siguen abiertas: todas las que detectaron las reglas (el LLM solo anota; no cierra un par, X21)."""
    return sum(1 for c in contradicciones if c.abierta)
