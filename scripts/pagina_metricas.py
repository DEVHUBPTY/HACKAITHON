"""C-02 · Página de métricas: Markdown generado a partir de las salidas de evaluación, listo para pegar o importar en Notion.

Uso: ``poetry run python -m scripts.pagina_metricas [--salida outputs/pagina_metricas.md]``.

Reglas (``specs/C-02.md``):

* **Ninguna cifra se escribe a mano.** Cada número sale de un archivo de ``outputs/`` o de ``data/manifest.json`` (rutas en
  ``config/pagina_metricas.yaml``) y se imprime con su fuente, la fecha de la medición y el commit de la fuente.
* **Toda proporción lleva numerador, denominador e IC 95 %.** Una proporción sin denominador o sin intervalo hace fallar el generador
  (``ProporcionIncompleta``). Con denominador 0 la métrica dice «sin datos» y no lleva cifra.
* **El origen del juicio se deriva de la fuente**, nunca se pasa a mano: ``humano``, ``asistente_provisional`` (D-101) o ``automático``.
  Una métrica provisional que se rotulara humana hace fallar el generador (``OrigenIncoherente``).
* La revisión humana separa las tasas de personas de las del revisor provisional (X71).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval import origen_etiquetas
from src.configuracion import RAIZ, ConfigPaginaMetricas, cargar_clasificacion, cargar_origen_juicio, cargar_pagina_metricas

HUMANO = "humano"
PROVISIONAL = "asistente_provisional"
AUTOMATICO = "automatico"
ORIGENES = (HUMANO, PROVISIONAL, AUTOMATICO)
CLAVES_FECHA = ("fecha_utc", "generado_utc", "fecha_referencia", "fecha_corte_UTC")


class ErrorPagina(ValueError):
    """La página no se puede generar con garantías."""


class FuenteFaltante(ErrorPagina):
    """Falta una fuente obligatoria."""


class ProporcionIncompleta(ErrorPagina):
    """Una proporción sin numerador, denominador o intervalo de confianza."""


class OrigenIncoherente(ErrorPagina):
    """El origen del juicio de una métrica contradice lo que declara su fuente."""


# ---------------------------------------------------------------------------------------------- lectura de proporciones


@dataclass(frozen=True)
class Prop:
    """Una proporción k / n con su IC 95 %. ``n == 0`` es «sin datos»: ni cifra ni intervalo."""

    k: int
    n: int
    proporcion: float | None
    ic: tuple[float, float] | None
    ic_wilson: tuple[float, float] | None = None

    @property
    def sin_datos(self) -> bool:
        return self.n == 0


def _par(valor: Any) -> tuple[float, float] | None:
    if (
        isinstance(valor, (list, tuple))
        and len(valor) == 2
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in valor)
    ):
        return (float(valor[0]), float(valor[1]))
    return None


def _entero(valor: Any) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0 else None


def leer_proporcion(obj: Any, donde: str) -> Prop:
    """Normaliza las tres formas que usan las salidas: ``{n, de}`` (n = numerador), ``{k, n}`` y ``{k, n, tasa}``.

    Falla con ``ProporcionIncompleta`` nombrando ``donde`` si falta el numerador, el denominador, la proporción o el intervalo.
    """
    if not isinstance(obj, dict):
        raise ProporcionIncompleta(f"{donde}: no es una proporción")
    if "k" in obj:
        k, n = _entero(obj.get("k")), _entero(obj.get("n"))
    elif "de" in obj:
        k, n = _entero(obj.get("n")), _entero(obj.get("de"))
    else:
        raise ProporcionIncompleta(f"{donde}: falta el denominador (se esperaba «de», o «k» y «n»)")
    if k is None or n is None:
        raise ProporcionIncompleta(f"{donde}: numerador o denominador ausente o inválido")
    if k > n:
        raise ProporcionIncompleta(f"{donde}: numerador {k} mayor que el denominador {n}")
    if n == 0:
        return Prop(k=0, n=0, proporcion=None, ic=None)
    p = obj.get("proporcion", obj.get("tasa"))
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        raise ProporcionIncompleta(f"{donde}: falta la proporción")
    ic = _par(obj.get("ic95"))
    if ic is None:
        raise ProporcionIncompleta(f"{donde}: falta el intervalo de confianza del 95 % (ic95)")
    return Prop(k=k, n=n, proporcion=float(p), ic=ic, ic_wilson=_par(obj.get("ic95_wilson")))


def leer_estimacion(obj: Any, clave_valor: str, donde: str) -> tuple[int, float, tuple[float, float]]:
    """Un valor con su n y su IC 95 % (mediana, F1, diferencia…): ``(n, valor, ic)``."""
    if not isinstance(obj, dict):
        raise ProporcionIncompleta(f"{donde}: no es una estimación")
    n, v, ic = _entero(obj.get("n")), obj.get(clave_valor), _par(obj.get("ic95"))
    if n is None or n == 0:
        raise ProporcionIncompleta(f"{donde}: falta n")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ProporcionIncompleta(f"{donde}: falta {clave_valor!r}")
    if ic is None:
        raise ProporcionIncompleta(f"{donde}: falta el intervalo de confianza del 95 % (ic95)")
    return n, float(v), ic


# ---------------------------------------------------------------------------------------------- origen del juicio


@dataclass(frozen=True)
class Origen:
    """Quién hizo el juicio que alimenta una métrica. Solo se construye con las funciones de abajo, a partir de la fuente."""

    tipo: str
    juicio_humano: bool | None   # lo que declaró la fuente; None si no hay juicio humano de por medio (automático)

    def __post_init__(self) -> None:
        if self.tipo not in ORIGENES:
            raise OrigenIncoherente(f"origen desconocido: {self.tipo!r}")
        esperado = {HUMANO: True, PROVISIONAL: False, AUTOMATICO: None}[self.tipo]
        if self.juicio_humano is not esperado:
            raise OrigenIncoherente(
                f"origen {self.tipo!r} incompatible con juicio_humano={self.juicio_humano!r} de la fuente: "
                "un juicio provisional nunca se rotula como humano (D-101)"
            )


ORIGEN_AUTOMATICO = Origen(AUTOMATICO, None)


def origen_de_juicio(fuente: dict[str, Any], donde: str) -> Origen:
    """Deriva el origen de ``juicio_humano`` y ``origen_juicio`` (D-101). Si los dos se contradicen, falla."""
    cfg = cargar_origen_juicio()
    if "juicio_humano" not in fuente:
        raise OrigenIncoherente(f"{donde}: la fuente no declara juicio_humano; no se puede rotular")
    humano = fuente["juicio_humano"]
    if not isinstance(humano, bool):
        raise OrigenIncoherente(f"{donde}: juicio_humano debe ser true o false")
    etiqueta = fuente.get("origen_juicio")
    if etiqueta is not None and (etiqueta == cfg.origenes[cfg.humano]) != humano:
        raise OrigenIncoherente(f"{donde}: juicio_humano={humano} contradice origen_juicio={etiqueta!r}")
    return Origen(HUMANO if humano else PROVISIONAL, humano)


def origen_de_etiquetas(origenes: Any, donde: str) -> Origen:
    """Origen de las etiquetas de clasificación y agrupación: humano solo si **ninguna** fila es provisional (D-85, D-101)."""
    validos = origen_etiquetas.validar_origenes(origenes)
    return Origen(PROVISIONAL, False) if origen_etiquetas.usa_provisionales(validos) else Origen(HUMANO, True)


def _origen_declarado(bloque: dict[str, Any], usados: Any, conteo_csv: dict[str, int], donde: str) -> Origen:
    """Origen de las etiquetas que **declara el mismo bloque que da la cifra** (``origenes`` y ``usa_etiquetas_provisionales``).

    Si lo declarado es «humano» pero la cifra usó más titulares que filas humanas hay en ``eval/etiquetas.csv``, la salida
    es incoherente consigo misma: falla en vez de rotular «humano».
    """
    if "origenes" not in bloque or "usa_etiquetas_provisionales" not in bloque:
        raise OrigenIncoherente(f"{donde}: no declara el origen de las etiquetas (origenes / usa_etiquetas_provisionales); "
                                "volver a correr la evaluación que la genera")
    org = origen_de_etiquetas(bloque["origenes"], f"{donde}.origenes")
    if (org.tipo == PROVISIONAL) != bool(bloque["usa_etiquetas_provisionales"]):
        raise OrigenIncoherente(f"{donde}: usa_etiquetas_provisionales contradice los orígenes declarados")
    humanas = conteo_csv.get(origen_etiquetas.HUMANO, 0)
    if org.tipo == HUMANO and isinstance(usados, int) and usados > humanas:
        raise OrigenIncoherente(f"{donde}: declara etiquetas humanas pero usó {usados} titulares y eval/etiquetas.csv solo tiene {humanas} humanas")
    return org


def origen_clasificacion(bloque: dict[str, Any], conteo_csv: dict[str, int]) -> Origen:
    """Origen de la clasificación: lo declara ``ia_vs_baseline.json:clasificacion``, el mismo bloque del que sale la cifra."""
    return _origen_declarado(bloque, bloque.get("vista_pipeline", {}).get("n"), conteo_csv, "ia_vs_baseline.json:clasificacion")


def origen_agrupacion(bloque: dict[str, Any], conteo_csv: dict[str, int]) -> Origen:
    """Origen de la agrupación: lo declara ``ia_vs_baseline.json:agrupacion``, el mismo bloque del que sale la cifra."""
    return _origen_declarado(bloque, bloque.get("titulares_etiquetados"), conteo_csv, "ia_vs_baseline.json:agrupacion")


# ---------------------------------------------------------------------------------------------- métricas


@dataclass(frozen=True)
class Metrica:
    """Una fila de la página: cifra, n, IC, fuente y origen del juicio. No existe sin n ni IC (salvo «sin datos»)."""

    seccion: str
    nombre: str
    valor: str
    n: str
    ic: str
    fuente: str
    origen: Origen
    sin_datos: bool = False
    fallos: str = ""
    nota: str = ""
    destacada: bool = False

    def __post_init__(self) -> None:
        if not self.sin_datos and (not self.n.strip() or not self.ic.strip()):
            raise ProporcionIncompleta(f"{self.fuente} · {self.nombre}: toda métrica lleva n e IC 95 %")
        if not isinstance(self.origen, Origen):
            raise OrigenIncoherente(f"{self.fuente} · {self.nombre}: el origen no viene de la fuente")
        Origen(self.origen.tipo, self.origen.juicio_humano)   # revalida por si se construyó a mano un valor incoherente


def porcentaje(x: float, dec: int) -> str:
    return f"{x * 100:.{dec}f} %"


@dataclass
class Contexto:
    """Todo lo que lee la página: configuración, raíz del repo y fuentes ya cargadas."""

    cfg: ConfigPaginaMetricas
    raiz: Path
    datos: dict[str, Any]
    ausentes: dict[str, str] = field(default_factory=dict)   # opcional que falta -> comando que la genera

    @property
    def dp(self) -> int:
        return self.cfg.presentacion.decimales_porcentaje

    @property
    def dv(self) -> int:
        return self.cfg.presentacion.decimales_valor

    def dec_latencia(self, segundos: float) -> int:
        """Decimales de una latencia según su magnitud: pocos desde el umbral de la configuración, más por debajo (X104)."""
        pres = self.cfg.presentacion
        return pres.decimales_latencia_segundos if segundos >= pres.umbral_latencia_s else pres.decimales_latencia

    def ruta(self, clave: str) -> str:
        return self.cfg.fuentes.get(clave) or self.cfg.opcionales[clave].ruta

    def prop(self, seccion: str, nombre: str, obj: Any, clave_fuente: str, donde: str, origen: Origen = ORIGEN_AUTOMATICO,
             fallos: str = "", nota: str = "", destacada: bool = False) -> Metrica:
        p = leer_proporcion(obj, f"{self.ruta(clave_fuente)}:{donde}")
        if p.sin_datos:
            return Metrica(seccion, nombre, "sin datos", "n = 0", "", self.ruta(clave_fuente), origen, sin_datos=True, nota=nota)
        ic = f"{porcentaje(p.ic[0], self.dp)} – {porcentaje(p.ic[1], self.dp)}"
        if p.ic_wilson and p.ic_wilson != p.ic:
            ic += f" (Wilson {porcentaje(p.ic_wilson[0], self.dp)} – {porcentaje(p.ic_wilson[1], self.dp)})"
        return Metrica(seccion, nombre, porcentaje(p.proporcion, self.dp), f"{p.k} de {p.n}", ic,
                       self.ruta(clave_fuente), origen, fallos=fallos, nota=nota, destacada=destacada)

    def est(self, seccion: str, nombre: str, obj: Any, clave_valor: str, clave_fuente: str, donde: str, unidad: str = "",
            origen: Origen = ORIGEN_AUTOMATICO, nota: str = "", destacada: bool = False, dec: int | None = None) -> Metrica:
        n, v, ic = leer_estimacion(obj, clave_valor, f"{self.ruta(clave_fuente)}:{donde}")
        sufijo = f" {unidad}" if unidad else ""
        d = self.dv if dec is None else dec
        return Metrica(seccion, nombre, f"{v:.{d}f}{sufijo}", f"n = {n}",
                       f"{ic[0]:.{d}f} – {ic[1]:.{d}f}{sufijo}", self.ruta(clave_fuente), origen, nota=nota,
                       destacada=destacada)


def formatear_fallos(fallos: Any) -> str:
    """IDs de los fallos: lista de IDs, lista de objetos con ``id`` o dict ``consulta -> evidencias faltantes``."""
    if not fallos:
        return "ninguno"
    if isinstance(fallos, dict):
        return ", ".join(f"{k} ({len(v)})" if isinstance(v, list) else str(k) for k, v in fallos.items())
    return ", ".join(str(f.get("id", f)) if isinstance(f, dict) else str(f) for f in fallos)


def veredicto(v: str) -> str:
    """El veredicto de la fuente en lenguaje corriente («gana_ia» → «gana la IA»)."""
    return {"gana_ia": "gana la IA", "gana_baseline": "gana el baseline"}.get(v, v.replace("_", " "))


def solapan(a: tuple[float, float] | None, b: tuple[float, float] | None) -> bool:
    return bool(a and b and a[0] <= b[1] and b[0] <= a[1])


# ---------------------------------------------------------------------------------------------- secciones


def seccion_benchmark(c: Contexto) -> list[Metrica]:
    m, s = c.datos["metricas"], "Benchmark de desarrollo: citas y abstención"
    o: list[Metrica] = []
    ab = m["abstencion_correcta"]
    o.append(c.prop(s, "Abstención correcta (consultas sin respuesta)", ab["sin_respuesta"], "metricas", "abstencion_correcta.sin_respuesta",
                    fallos=formatear_fallos(ab["sin_respuesta"].get("fallos")), destacada=True,
                    nota=f"meta {porcentaje(ab['meta'], c.dp)}"))
    o.append(c.prop(s, "Abstención correcta (incluye adversariales que debían abstenerse)", ab["todas_las_que_debian"], "metricas",
                    "abstencion_correcta.todas_las_que_debian", fallos=formatear_fallos(ab["todas_las_que_debian"].get("fallos"))))
    ai = m["abstenciones_incorrectas"]
    o.append(c.prop(s, "Abstenciones incorrectas (respondibles rechazadas)", ai["respondibles"], "metricas",
                    "abstenciones_incorrectas.respondibles", fallos=formatear_fallos(ai["respondibles"].get("ids")),
                    nota="sin meta; se reporta", destacada=True))
    cc = m["cobertura_de_citas"]
    o.append(c.prop(s, "Cobertura de citas (respuestas de la consulta)", cc["consultas"], "metricas", "cobertura_de_citas.consultas",
                    fallos=formatear_fallos(cc["consultas"].get("fallos")), nota="meta 100 %", destacada=True))
    o.append(c.prop(s, "Cobertura de citas (con validador de citas)", cc["consultas_con_validador_de_citas"], "metricas",
                    "cobertura_de_citas.consultas_con_validador_de_citas",
                    fallos=formatear_fallos(cc["consultas_con_validador_de_citas"].get("fallos"))))
    for clave, nombre in (("factuales_con_cita_valida", "Borradores: afirmaciones factuales con cita válida"),
                          ("factuales_que_pasan_el_validador", "Borradores: afirmaciones factuales que pasan el validador"),
                          ("derivadas_con_base_valida", "Borradores: inferencias e hipótesis con base válida")):
        o.append(c.prop(s, nombre, cc["borradores"][clave], "metricas", f"cobertura_de_citas.borradores.{clave}",
                        fallos=formatear_fallos(cc["borradores"][clave].get("fallos"))))
    return o


def seccion_busqueda(c: Contexto) -> tuple[list[Metrica], list[str]]:
    b, s = c.datos["metricas"]["busqueda"]["metodos"], "Búsqueda: semántica contra BM25"
    iv = c.datos["ia_vs_baseline"]["busqueda"]
    o = []
    for clave, rotulo in (("semantica", "semántica (IA)"), ("bm25", "BM25 (baseline)")):
        o.append(c.prop(s, f"Recall@5 por evidencias esperadas · {rotulo}", b[clave]["por_ids"], "metricas",
                        f"busqueda.metodos.{clave}.por_ids", destacada=True))
        o.append(c.prop(s, f"Consultas con todas sus evidencias en el top 5 · {rotulo}", b[clave]["consultas_completas"], "metricas",
                        f"busqueda.metodos.{clave}.consultas_completas", fallos=formatear_fallos(b[clave].get("fallos"))))
    d = iv["diferencia_ia_menos_baseline"]
    ic = _par(d.get("ic95"))
    if ic is None or not isinstance(d.get("diferencia"), (int, float)):
        raise ProporcionIncompleta("ia_vs_baseline.json:busqueda.diferencia_ia_menos_baseline: falta diferencia o ic95")
    lineas = [f"Diferencia semántica − BM25 en la fracción de evidencias recuperadas: {d['diferencia']:.{c.dv}f} "
              f"(n = {d['n_consultas']} consultas, IC 95 % {ic[0]:.{c.dv}f} – {ic[1]:.{c.dv}f}); veredicto de la fuente: "
              f"**{veredicto(d['veredicto'])}**."]
    return o, lineas


def seccion_sustento(c: Contexto) -> tuple[list[Metrica], list[str]]:
    v, s = c.datos["metricas"]["validez_sustento"], "Validez de sustento (revisión de afirmaciones)"
    org = origen_de_juicio(v, "metricas.json:validez_sustento")
    o = [
        c.prop(s, "Afirmaciones sustentadas", v["sustentadas"], "metricas", "validez_sustento.sustentadas", org,
               fallos=formatear_fallos(v.get("fallos")), nota="meta 90 % sobre la estimación puntual", destacada=True),
        c.prop(s, "Afirmaciones parcialmente sustentadas", v["parciales"], "metricas", "validez_sustento.parciales", org),
        c.prop(s, "Afirmaciones con tipo incorrecto", v["tipo_incorrecto"], "metricas", "validez_sustento.tipo_incorrecto", org),
    ]
    mv = v["meta_validez"]
    cumple = v.get("cumple_meta_provisional")
    lineas = [f"Meta de {porcentaje(mv['meta'], c.dp)}: {'cumple' if cumple else 'no cumple'} con la estimación puntual "
              f"({porcentaje(mv['estimacion_puntual'], c.dp)}), "
              f"{'cumple' if mv['cumple_con_limite_inferior_wilson'] else 'no cumple'} con el límite inferior de Wilson "
              f"({porcentaje(mv['limite_inferior_wilson'], c.dp)}). El criterio oficial es la estimación puntual (protocolo, sección 4); "
              "el resultado es **provisional** mientras los veredictos los haya dado el asistente."]
    return o, lineas


def seccion_baseline(c: Contexto) -> tuple[list[Metrica], list[str]]:
    iv, s = c.datos["ia_vs_baseline"], "Clasificación y agrupación: IA contra baseline"
    org = origen_clasificacion(iv["clasificacion"], c.datos["origenes_etiquetas"])
    org_ag = origen_agrupacion(iv["agrupacion"], c.datos["origenes_etiquetas"])
    cl = iv["clasificacion"]["vista_pipeline"]
    medido = f"({iv['clasificacion']['modelo']}/{iv['clasificacion']['metodo']})"   # modelo/método que midió ia_vs_baseline.json
    o = [
        c.est(s, f"Macro-F1 de clasificación · IA {medido}", cl["macro_f1_ia"], "macro_f1", "ia_vs_baseline", "clasificacion.vista_pipeline.macro_f1_ia",
              origen=org, destacada=True),
        c.est(s, "Macro-F1 de clasificación · baseline", cl["macro_f1_baseline"], "macro_f1", "ia_vs_baseline",
              "clasificacion.vista_pipeline.macro_f1_baseline", origen=org, destacada=True),
        c.est(s, "Macro-F1: diferencia IA − baseline", cl["diferencia_macro_f1"], "diferencia_macro_f1", "ia_vs_baseline",
              "clasificacion.vista_pipeline.diferencia_macro_f1", origen=org),
    ]
    vc = iv["clasificacion"]["vista_clasificador"]
    o += [c.prop(s, f"Exactitud del clasificador · IA {medido}", vc["exactitud_ia"], "ia_vs_baseline", "clasificacion.vista_clasificador.exactitud_ia", org),
          c.prop(s, "Exactitud del clasificador · baseline", vc["exactitud_baseline"], "ia_vs_baseline",
                 "clasificacion.vista_clasificador.exactitud_baseline", org)]
    cv = iv["agrupacion"]["validacion_cruzada_agrupada"]
    for lado, rotulo in (("ia", "IA"), ("baseline", "baseline")):
        d = cv[lado]
        for medida, den, nombre in (("precision", "pares_predichos", "Precisión de pares"), ("recall", "pares_positivos", "Recall de pares")):
            ic = _par(d[medida].get("ic95"))
            if ic is None:
                raise ProporcionIncompleta(f"ia_vs_baseline.json:agrupacion.validacion_cruzada_agrupada.{lado}.{medida}: falta ic95")
            o.append(c.prop(s, f"{nombre} (validación cruzada) · {rotulo}",
                            {"n": d["tp"], "de": d[den], "proporcion": d[medida]["valor"], "ic95": ic}, "ia_vs_baseline",
                            f"agrupacion.validacion_cruzada_agrupada.{lado}.{medida}", org_ag,
                            nota="IC por remuestreo de titulares", destacada=False))
    veredictos = [f"- Clasificación (macro-F1): **{veredicto(cl['veredicto'])}**; discordantes: solo IA {cl['discordantes_conteo']['solo_ia']}, "
                  f"solo baseline {cl['discordantes_conteo']['solo_baseline']} (n = {cl['discordantes_conteo']['n']})."]
    for medida in ("precision", "recall", "f1"):
        dd = cv["diferencia_ia_menos_baseline"][medida]
        ic = _par(dd.get("ic95"))
        if ic is None:
            raise ProporcionIncompleta(f"ia_vs_baseline.json:agrupacion…diferencia_ia_menos_baseline.{medida}: falta ic95")
        veredictos.append(f"- Agrupación, diferencia IA − baseline en {medida} (n = {cv['n_titulares']} titulares): {dd['valor']:.{c.dv}f}, "
                          f"IC 95 % {ic[0]:.{c.dv}f} – {ic[1]:.{c.dv}f} → **{veredicto(dd['veredicto'])}**.")
    return o, veredictos


def seccion_ranking(c: Contexto) -> tuple[list[Metrica], list[str]]:
    p, s = c.datos["precision"], "Ranking: Precision@5, estabilidad y distribución"
    org = origen_de_juicio(p, "precision_at_5.json")
    o = [
        c.prop(s, "Precision@5 · sistema", p["sistema"], "precision", "sistema", org, destacada=True,
               fallos=formatear_fallos(p["cortes"][0]["sistema"].get("ids_fallidos"))),
        c.prop(s, "Precision@5 · baseline por fecha de publicación", p["baseline"], "precision", "baseline", org, destacada=True,
               fallos=formatear_fallos(p["cortes"][0]["baseline"].get("ids_fallidos"))),
    ]
    sn = c.datos["sensibilidad"]
    for clave, nombre in (("top_sin_cambio", "Variantes cuyo top 5 no cambia de temas"), ("mismo_orden", "Variantes que conservan el mismo orden"),
                          ("temas_retenidos", "Temas del top 5 que se conservan (sobre todas las variantes)")):
        o.append(c.prop(s, nombre, sn[clave], "sensibilidad", clave, destacada=(clave == "top_sin_cambio"),
                        nota="cada peso ±5 puntos y cada supuesto ±20 %" if clave == "top_sin_cambio" else ""))
    pz = c.datos["puntaje"]
    for clave in ("alto", "medio", "bajo"):
        o.append(c.prop(s, f"Grupos con rango de prioridad «{clave}»", pz["por_rango"][clave], "puntaje", f"por_rango.{clave}"))
    ps = pz["puntaje"]
    casi = [k for k, v in pz["componentes"].items() if v.get("casi_constante")]
    lineas = [
        f"Precision@5: sistema {p['sistema']['k']} de {p['sistema']['n']}, baseline {p['baseline']['k']} de {p['baseline']['n']}; "
        f"{'los IC se solapan: **sin diferencia demostrable**' if solapan(_par(p['sistema']['ic95']), _par(p['baseline']['ic95'])) else 'los IC no se solapan'}. "
        f"Pruebas: {p['pruebas']} (fecha de corte {p['cortes'][0]['corte']}, {p['cortes'][0]['candidatos']} candidatos); "
        f"{'exploratoria' if p['exploratoria'] else 'no exploratoria'}; especialista: {'sí' if p['especialista'] else 'no'}.",
        f"Distribución del puntaje P (n = {ps['n']} grupos): mínimo {ps['min']:.{c.dv}f}, mediana {ps['mediana']:.{c.dv}f}, máximo {ps['max']:.{c.dv}f}, "
        f"desviación {ps['desviacion']:.{c.dv}f}. Componentes casi constantes: {', '.join(casi) if casi else 'ninguno'}.",
    ]
    return o, lineas


def _valor_de(est: Any, donde: str) -> float:
    """El ``valor`` de una estimación, para decidir cuántos decimales lleva; la validación completa la hace ``leer_estimacion``."""
    v = est.get("valor") if isinstance(est, dict) else None
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ProporcionIncompleta(f"metricas.json:{donde}: falta 'valor'")
    return float(v)


def seccion_eficiencia(c: Contexto) -> tuple[list[Metrica], list[str]]:
    m, s = c.datos["metricas"], "Eficiencia, tokens y costo"
    lat = m["latencia"]
    o: list[Metrica] = []
    for clave, rotulo in (("consulta", "Consulta (punta a punta, local, sin LLM)"), ("primera_respuesta_borrador", "Primera respuesta del borrador"),
                          ("paquete_completo", "Paquete completo de borrador"), ("llamada_llm", "Llamada al LLM")):
        for pct in ("p50", "p95"):
            o.append(c.est(s, f"Latencia {pct} · {rotulo}", lat[clave][pct], "valor", "metricas", f"latencia.{clave}.{pct}", "s",
                           destacada=(pct == "p50" and clave in ("consulta", "paquete_completo")),
                           dec=c.dec_latencia(_valor_de(lat[clave][pct], f"latencia.{clave}.{pct}"))))
    for tipo, d in lat["paquete_por_tipo"].items():
        o.append(c.est(s, f"Latencia p50 del paquete {tipo} (n pequeño)", d["p50"], "valor", "metricas", f"latencia.paquete_por_tipo.{tipo}.p50", "s",
                       dec=c.dec_latencia(_valor_de(d["p50"], f"latencia.paquete_por_tipo.{tipo}.p50"))))
    b = m["tokens_y_costo"]["borradores"]
    if b.get("estado") != "medido":
        raise ErrorPagina("metricas.json:tokens_y_costo.borradores no está medido")
    tp = b["tokens_por_paquete"]
    o.append(c.est(s, "Tokens de entrada por paquete (mediana)", tp["entrada"], "valor", "metricas", "tokens_y_costo.borradores.tokens_por_paquete.entrada", dec=c.cfg.presentacion.decimales_tokens))
    o.append(c.est(s, "Tokens de salida por paquete (mediana)", tp["salida"], "valor", "metricas", "tokens_y_costo.borradores.tokens_por_paquete.salida", dec=c.cfg.presentacion.decimales_tokens))
    o.append(c.est(s, "Costo por paquete (mediana, cota superior)", b["costo_usd"]["por_paquete_mediana"], "valor", "metricas",
                   "tokens_y_costo.borradores.costo_usd.por_paquete_mediana", "USD", destacada=True, dec=c.cfg.presentacion.decimales_usd,
                   nota=f"{b['proveedor']}/{b['modelo']}, medido {b['fecha_utc']}"))
    mt = lat["meta_sugerida"]
    lineas = [
        f"Meta sugerida: mediana ≤ {mt['mediana_s']:.0f} s. Consulta: {'cumple' if mt['consulta_cumple'] else 'no cumple'}; paquete por tipo: "
        + ", ".join(f"{k} {'cumple' if v else 'no cumple'}" for k, v in mt["paquete_cumple_por_tipo"].items()) + ".",
        f"Costo total estimado de la corrida de {b['n_paquetes']} paquetes: USD {b['costo_usd']['total_estimado']:.4f}; tokens totales "
        f"{b['tokens_totales']['entrada']} de entrada y {b['tokens_totales']['salida']} de salida.",
        f"**Supuesto del proyecto (D-97):** el contador de costo sobreestima ≈ {c.cfg.sobreestimacion_contador_costo:g} × respecto de la consola del proveedor "
        "(una comparación puntual); las cifras de USD son una cota superior conservadora, no la factura.",
    ]
    cl = c.datos.get("costo_llm")
    if cl is not None:
        lineas.append(f"Contador acumulado del proyecto: {cl['tokens']} tokens y USD {cl['usd']:.4f} (local, ignorado por git).")
    else:
        lineas.append(f"Contador acumulado: fuente no disponible ({c.cfg.opcionales['costo_llm'].ruta}).")
    return o, lineas


def seccion_rechazos(c: Contexto) -> tuple[list[Metrica], list[str]]:
    r, s = c.datos["metricas"]["rechazos_previos"]["tasas"], "Rechazos del validador"
    o = []
    for modelo, d in r["por_modelo"].items():
        o.append(c.prop(s, f"Unidades rechazadas · {modelo}", d, "metricas", f"rechazos_previos.tasas.por_modelo.{modelo}", destacada=True,
                        nota="afirmaciones y secciones, re-validadas con el validador actual"))
    for regla, por_modelo in r["por_regla"].items():
        for modelo, por_unidad in por_modelo.items():
            for unidad, d in por_unidad.items():
                o.append(c.prop(s, f"Regla «{regla}» · {unidad} · {modelo}", d, "metricas", f"rechazos_previos.tasas.por_regla.{regla}.{unidad}"))
    b = c.datos["metricas"]["borradores"]
    lineas = [f"Borradores del benchmark: modo {b['modo']}, {b['grupos']} grupos; estados "
              + ", ".join(f"{k} {v}" for k, v in b["estados"].items()) + f". Grupos con fallo: {formatear_fallos(b['fallos'])}."]
    return o, lineas


def seccion_revision(c: Contexto) -> tuple[list[Metrica], list[str]]:
    s = "Revisión humana: personas y revisor provisional"
    r = c.datos.get("revision")
    if r is None:
        cmd = c.cfg.opcionales["revision"].comando
        return [], [f"Fuente no disponible ({c.cfg.opcionales['revision'].ruta}). Generar con `{cmd}`."]
    o: list[Metrica] = []
    org_h = origen_de_juicio(r, "revision.json")
    if not org_h.juicio_humano:
        raise OrigenIncoherente("revision.json: el bloque principal debe contar solo decisiones de personas (X71)")
    nombres = {"aceptacion": "Tasa de aceptación (aprobados como borrador)", "correccion": "Tasa de corrección", "descarte": "Tasa de descarte"}
    for clave, nombre in nombres.items():
        o.append(c.prop(s, f"{nombre} · personas", r["tasas"][clave], "revision", f"tasas.{clave}", org_h))
    o.append(c.prop(s, "Afirmaciones editadas · personas", r["afirmaciones_editadas"], "revision", "afirmaciones_editadas", org_h))
    lineas = [f"Casos abiertos: {r['casos_abiertos']}. Decididos por una persona: {r['casos_decididos']}. "
              f"Decididos por el revisor provisional: {r['casos_decididos_provisionales']}."]
    prov = r.get("provisionales")
    if prov:
        org_p = origen_de_juicio(prov, "revision.json:provisionales")
        if org_p.juicio_humano:
            raise OrigenIncoherente("revision.json:provisionales: el bloque provisional no puede declararse humano")
        for clave, nombre in nombres.items():
            o.append(c.prop(s, f"{nombre} · PROVISIONAL (asistente)", prov["tasas"][clave], "revision", f"provisionales.tasas.{clave}", org_p))
        o.append(c.prop(s, "Afirmaciones editadas · PROVISIONAL (asistente)", prov["afirmaciones_editadas"], "revision",
                        "provisionales.afirmaciones_editadas", org_p))
        lineas.append(f"**{prov['aviso_origen']}**")
    return o, lineas


# ---------------------------------------------------------------------------------------------- pruebas, reproducibilidad, coherencia


def seccion_pruebas(c: Contexto) -> list[str]:
    filas = c.datos["pruebas"]
    conteo: dict[str, int] = {}
    for f in filas:
        conteo[f["Estado"]] = conteo.get(f["Estado"], 0) + 1
    out = [f"Pruebas de aceptación T01–T10: {', '.join(f'{k} {v}' for k, v in sorted(conteo.items()))} (de {len(filas)}). "
           "Es una matriz de aceptación, no una muestra: no lleva IC.", "",
           "| Prueba | Estado | Resultado observado |", "|---|---|---|"]
    out += [f"| {f['Prueba']} | {f['Estado']} | {f['Resultado observado'].replace('|', '/')} |" for f in filas]
    return out


def seccion_reproducibilidad(c: Contexto, head: str) -> list[str]:
    r = c.datos["manifest"]["reproducibilidad"]
    e = r["ejecucion"]
    reg = e["commit"][:7]
    out = [f"- Registro del manifest: commit `{reg}`, árbol con cambios al registrar: **{'sí' if e['arbol_con_cambios'] else 'no'}**; "
           f"corte del snapshot {c.datos['manifest']['fecha_corte_UTC']}; hash del snapshot `{c.datos['manifest']['hash_snapshot'][:12]}`.",
           f"- Commit desde el que se generó: `{head}`" + (" (árbol con cambios sin commitear)" if _arbol_con_cambios(c) else "") + ". "
           + ("El registro corresponde a ese commit." if head.startswith(reg) or reg.startswith(head)
              else "El registro es de otro commit: confirmar con `--verificar` antes de afirmar que se reproduce."),
           f"- LLM: {e['llm']['proveedor']}/{e['llm']['modelo']}, temperatura {e['llm']['temperatura']}, semilla {e['llm']['semilla']}; "
           f"embeddings {e['embeddings']['clave']} y {e['embeddings_clasificacion']['clave']} con revisión fijada.",
           f"- Salidas deterministas con hash: {len(r['salidas_deterministas'])}. Borradores en caché: "
           + ", ".join(f"{k} {v}" for k, v in _contar(d["estado"] for d in r["borradores_cache"].values()).items()) + ".",
           "- Comprobación: `HF_HUB_OFFLINE=1 poetry run python -m scripts.reproducir --verificar` (sale con 1 si algo difiere)."]
    out += [f"- Limitación declarada: {x}" for x in r.get("limitaciones", [])]
    return out


def _arbol_con_cambios(c: Contexto) -> bool:
    """¿Alguna fuente de la página (obligatoria u opcional) tiene cambios sin commitear? Mismo criterio que ``arbol_con_cambios`` del manifest."""
    rutas = [c.ruta(k) for k in c.cfg.fuentes] + [o.ruta for o in c.cfg.opcionales.values()]
    return bool(_git(c.raiz, "status", "--porcelain", "--", *rutas))


def _contar(it: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def coherencia(c: Contexto) -> list[str]:
    """Discrepancias entre fuentes que se miden sobre el mismo snapshot. Solo avisa: no corrige ni oculta."""
    p, iv, pz, sn = c.datos["precision"], c.datos["ia_vs_baseline"], c.datos["puntaje"], c.datos["sensibilidad"]
    avisos = []
    grupos = {"puntaje.json (grupos)": pz.get("grupos"), "ia_vs_baseline.json (ranking.grupos)": iv["ranking"].get("grupos"),
              "precision_at_5.json (candidatos)": p["cortes"][0].get("candidatos")}
    if len({v for v in grupos.values()}) > 1:
        avisos.append("Distinto número de grupos entre fuentes: " + "; ".join(f"{k} = {v}" for k, v in grupos.items())
                      + ". Alguna salida es anterior a un cambio de la base: volver a correrla antes de citarla.")
    if sn.get("fecha_referencia") != p["cortes"][0].get("corte"):
        avisos.append(f"Fecha de corte distinta: sensibilidad.json {sn.get('fecha_referencia')} contra precision_at_5.json {p['cortes'][0].get('corte')}.")
    top_p = p["cortes"][0]["sistema"]["top"]
    top_i = [x if isinstance(x, str) else x.get("id", x.get("grupo")) for x in iv["ranking"].get("top_sistema", [])]
    if top_i and set(top_p) != set(top_i):
        avisos.append("El top 5 del sistema difiere entre precision_at_5.json e ia_vs_baseline.json: una de las dos salidas es anterior a un cambio del ranking.")
    avisos += _coherencia_clasificacion(c)
    return avisos


def _coherencia_clasificacion(c: Contexto) -> list[str]:
    """La clasificación de ``ia_vs_baseline.json`` contra la de ``clasificacion.json`` para el modelo y método que midió,
    y que ese modelo y método sean los activos de ``config/clasificacion.yaml`` (X103).

    Si difieren, una de las dos salidas es de otro clasificador o de otra base. Según la configuración avisa o hace fallar.
    """
    iv_c, cl = c.datos["ia_vs_baseline"]["clasificacion"], c.datos["clasificacion"]["datos_reales"]
    clave = f"{iv_c['modelo']}/{iv_c['metodo']}"
    activa = cargar_clasificacion()
    activo = f"{activa.modelo_activo}/{activa.metodo_activo}"
    tol = c.cfg.coherencia.tolerancia_macro_f1
    try:
        pipe = cl["pipeline"]["configuraciones"]
        pares = [
            ("macro-F1 de la IA", iv_c["vista_pipeline"]["macro_f1_ia"]["macro_f1"], pipe[clave]["sin_ponderar"]["macro_f1"]["macro_f1"], tol),
            ("macro-F1 del baseline", iv_c["vista_pipeline"]["macro_f1_baseline"]["macro_f1"], pipe["baseline"]["sin_ponderar"]["macro_f1"]["macro_f1"], tol),
            ("n de la vista del pipeline", iv_c["vista_pipeline"]["n"], cl["pipeline"]["conteo"]["evaluados"], 0),
            ("aciertos de la exactitud de la IA", iv_c["vista_clasificador"]["exactitud_ia"]["n"], cl["configuraciones"][clave]["exactitud_principal"]["n"], 0),
            ("total de la exactitud de la IA", iv_c["vista_clasificador"]["exactitud_ia"]["de"], cl["configuraciones"][clave]["exactitud_principal"]["de"], 0),
        ]
    except KeyError as e:
        raise ErrorPagina(f"coherencia de la clasificación: falta {e} en ia_vs_baseline.json o clasificacion.json (configuración {clave})") from e
    difieren = [f"{n}: ia_vs_baseline.json {a} contra clasificacion.json {b}" for n, a, b, t in pares if abs(a - b) > t]
    if clave != activo:
        difieren.insert(0, f"ia_vs_baseline.json midió {clave} pero config/clasificacion.yaml activa {activo}")
    if not difieren:
        return []
    msg = (f"La clasificación ({clave}) difiere entre salidas — " + "; ".join(difieren)
           + ". Una es anterior a un cambio del clasificador o de la base: volver a correr eval.ia_vs_baseline y eval.clasificacion antes de citarla.")
    if c.cfg.coherencia.ante_discrepancia_clasificacion == "falla":
        raise ErrorPagina(msg)
    return [msg]


# ---------------------------------------------------------------------------------------------- git y carga


def _git(raiz: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=raiz, capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def procedencia(raiz: Path, ruta: str, fecha_archivo: str | None) -> tuple[str, str, str]:
    """(commit, fecha del commit, fecha dentro del archivo) de una fuente. «sin commitear» si el archivo cambió o no está versionado."""
    sucio = _git(raiz, "status", "--porcelain", "--", ruta)
    log = _git(raiz, "log", "-1", "--format=%h|%cI", "--", ruta)
    if log:
        commit, fecha = log.split("|", 1)
        if sucio:
            commit += " + cambios sin commitear"
    else:
        commit, fecha = "sin versionar (generado en local)", "—"
    return commit, fecha, fecha_archivo or "—"


def _fecha_archivo(datos: Any) -> str | None:
    if isinstance(datos, dict):
        for k in CLAVES_FECHA:
            if isinstance(datos.get(k), str):
                return datos[k]
        cortes = datos.get("cortes")
        if isinstance(cortes, list) and cortes and isinstance(cortes[0], dict):
            return cortes[0].get("corte")
    return None


def cargar_contexto(raiz: Path = RAIZ, cfg: ConfigPaginaMetricas | None = None) -> Contexto:
    cfg = cfg or cargar_pagina_metricas()
    datos: dict[str, Any] = {}
    for clave, ruta in cfg.fuentes.items():
        p = raiz / ruta
        if not p.exists():
            raise FuenteFaltante(f"falta la fuente obligatoria {ruta} (clave {clave})")
        if p.suffix == ".json":
            datos[clave] = json.loads(p.read_text(encoding="utf-8"))
        elif p.suffix == ".csv" and clave == "pruebas":
            with p.open(encoding="utf-8", newline="") as f:
                datos[clave] = list(csv.DictReader(f))
        elif clave == "prueba_tiempo":
            datos[clave] = p.read_text(encoding="utf-8")
    datos["origenes_etiquetas"] = _origenes_etiquetas(raiz / cfg.fuentes["etiquetas"])
    ausentes: dict[str, str] = {}
    for clave, op in cfg.opcionales.items():
        p = raiz / op.ruta
        if p.exists():
            datos[clave] = json.loads(p.read_text(encoding="utf-8"))
        else:
            ausentes[clave] = op.comando
    return Contexto(cfg=cfg, raiz=raiz, datos=datos, ausentes=ausentes)


def _origenes_etiquetas(ruta: Path) -> dict[str, int]:
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        col = origen_etiquetas.columna_de_origen(lector.fieldnames or [])
        if col is None:
            raise ErrorPagina(f"{ruta}: sin columna de origen; no se puede rotular el origen de las etiquetas")
        return _contar(origen_etiquetas.normalizar_origen(fila[col]) for fila in lector)


# ---------------------------------------------------------------------------------------------- render


def _tabla(ms: list[Metrica], cfg: ConfigPaginaMetricas) -> list[str]:
    cfg_o = cargar_origen_juicio()
    rot = {HUMANO: cfg_o.origenes[HUMANO], PROVISIONAL: f"**PROVISIONAL** · {cfg_o.origenes[PROVISIONAL]}", AUTOMATICO: "automático"}
    out = ["| Métrica | Valor | Numerador / denominador | IC 95 % | Origen del juicio | Fuente | Fallos (IDs) · nota |", "|---|---|---|---|---|---|---|"]
    for m in ms:
        extra = " · ".join(x for x in (m.fallos and f"fallos: {m.fallos}", m.nota) if x)
        out.append(f"| {m.nombre} | {m.valor} | {m.n} | {m.ic or '—'} | {rot[m.origen.tipo]} | `{Path(m.fuente).name}` | {extra or '—'} |")
    return out


def limitaciones(c: Contexto, todas: list[Metrica]) -> list[str]:
    p = c.datos["precision"]
    ic_s, ic_b = _par(p["sistema"]["ic95"]), _par(p["baseline"]["ic95"])
    provisionales = sorted({m.seccion for m in todas if m.origen.tipo == PROVISIONAL})
    tiempo = re.search(r"Pruebas realizadas hasta hoy:\s*\**(\d+)", c.datos["prueba_tiempo"])
    sbp_ok = "sbp" in json.dumps(c.datos["manifest"].get("licencias", {})).lower()
    out = [
        f"- **Precision@5 con n = {p['sistema']['n']} temas** en {p['pruebas']} fecha de corte, sin especialista editorial: es exploratoria. "
        f"Los IC (sistema {ic_s[0]:.{c.dv}f}–{ic_s[1]:.{c.dv}f}; baseline {ic_b[0]:.{c.dv}f}–{ic_b[1]:.{c.dv}f}) "
        f"{'se solapan: no hay diferencia demostrable.' if solapan(ic_s, ic_b) else 'no se solapan, pero con tan pocos temas no se generaliza.'} "
        f"Los temas de un mismo corte no son independientes (nota de la fuente).",
        "- **Selección ciega solo a medias:** quien eligió los temas conocía la selección y el resultado anteriores (revisión D-78 de E1-19). "
        "No es la selección independiente de un editor.",
        f"- **Juicios provisionales del asistente (D-101), pendientes de C-09:** secciones: {', '.join(provisionales) if provisionales else 'ninguna en esta corrida'}. "
        "Se rehacen a mano; hasta entonces no se reportan como juicio de una persona.",
        "- **Recalcular tras C-10:** cualquier mejora de ranking, clasificación o generación cambia estas cifras; hay que volver a correr los módulos de "
        "`eval/` y regenerar esta página (nueva corrida).",
        f"- **Benchmark de desarrollo (n = {c.datos['metricas']['benchmark']['n']} consultas):** " + " ".join(c.datos["metricas"]["avisos"]),
        "- **Baselines:** el veredicto «sin diferencia demostrable» significa que los IC se solapan, no que los métodos sean iguales.",
        f"- **Ahorro de tiempo: no medido.** Pruebas realizadas: {tiempo.group(1) if tiempo else 'no consta'} (`docs/prueba_tiempo.md`); "
        "mide a una persona y queda para C-09.",
        f"- **Costo:** el contador sobreestima ≈ {c.cfg.sobreestimacion_contador_costo:g} × (supuesto del proyecto, D-97); las cifras de USD son cota superior.",
        "- **Revisión humana:** " + ("sin casos decididos por una persona; las tasas humanas están en «sin datos»."
                                    if c.datos.get("revision", {}).get("casos_decididos") == 0 else "las tasas dependen de pocos casos; ver n.")
        if "revision" in c.datos else "- **Revisión humana:** fuente no disponible.",
        "- **SBP (D-116):** la fuente D se versiona con riesgo aceptado (el aviso legal de la SBP restringe la reproducción y la redistribución sin "
        "autorización escrita). Esta página no usa cifras de la SBP, pero si el repositorio o el paquete de entrega se hacen públicos hay que pedir "
        "la autorización o retirar esos valores." + ("" if sbp_ok else " (el manifest no registra su licencia)"),
        "- No se infiere audiencia, rentabilidad ni reducción de riesgo; un titular es lo que un medio reporta, no un hecho.",
    ]
    return out


PREGUNTAS_ABIERTAS = [
    "**¿Se publica ya en Notion como borrador o se espera a C-09 y C-10?** Recomendación: publicarla una vez ahora marcada «BORRADOR — métricas "
    "provisionales» y actualizar esa misma página al regenerarla; así el equipo ve el estado real y nada provisional se presenta como humano.",
    "**¿Qué hacer si una salida de `eval/` es anterior a un cambio de la base?** La sección «Coherencia entre fuentes» lo avisa pero no lo corrige. "
    "Recomendación: antes de la entrega, volver a correr los módulos de `eval/` y regenerar la página en una sola pasada (condición de C-02 tras C-10).",
]


def generar(c: Contexto | None = None, ahora: datetime | None = None) -> str:
    """El Markdown completo de la página. Falla (``ErrorPagina``) si alguna proporción no lleva n e IC o un origen es incoherente."""
    c = c or cargar_contexto()
    ahora = ahora or datetime.now(timezone.utc)
    secciones: list[tuple[str, list[Metrica], list[str]]] = []
    bm, lb = seccion_busqueda(c)
    sus, ls = seccion_sustento(c)
    bas, lbas = seccion_baseline(c)
    rk, lrk = seccion_ranking(c)
    ef, lef = seccion_eficiencia(c)
    rz, lrz = seccion_rechazos(c)
    rv, lrv = seccion_revision(c)
    secciones += [("Benchmark de desarrollo: citas y abstención", seccion_benchmark(c), []),
                  ("Búsqueda: semántica contra BM25", bm, lb),
                  ("Validez de sustento (revisión de afirmaciones)", sus, ls),
                  ("Clasificación y agrupación: IA contra baseline", bas, lbas),
                  ("Ranking: Precision@5, estabilidad y distribución", rk, lrk),
                  ("Eficiencia, tokens y costo", ef, lef),
                  ("Rechazos del validador", rz, lrz),
                  ("Revisión humana: personas y revisor provisional", rv, lrv)]
    todas = [m for _, ms, _ in secciones for m in ms]
    head = _git(c.raiz, "rev-parse", "--short", "HEAD") or "sin git"
    cfg_o = cargar_origen_juicio()
    hay_prov = any(m.origen.tipo == PROVISIONAL for m in todas)
    L: list[str] = [f"# {c.cfg.titulo}", "", f"> **{c.cfg.etiqueta_borrador}**" + (f" · {cfg_o.aviso_provisional}" if hay_prov else ""), "",
                    f"Generada el {ahora.strftime('%Y-%m-%dT%H:%M:%SZ')} desde el commit `{head}` con "
                    "`poetry run python -m scripts.pagina_metricas`. Ninguna cifra está escrita a mano: cada una sale del archivo que se indica. "
                    "Toda proporción lleva numerador, denominador e IC 95 %.", "",
                    "**Origen del juicio:** `humano` = lo decidió una persona (las etiquetas de clasificación y agrupación las propone el asistente y una persona las revisa y aprueba una por una, D-85) · **PROVISIONAL** = lo decidió el asistente (D-101) y se rehace en C-09 · "
                    f"`automático` = {c.cfg.etiqueta_automatico}.", "", "## Resumen", ""]
    L += _tabla([m for m in todas if m.destacada], c.cfg) + [""]
    L += ["## Pruebas de aceptación", ""] + seccion_pruebas(c) + [""]
    for titulo, ms, lineas in secciones:
        L += [f"## {titulo}", ""]
        if ms:
            L += _tabla(ms, c.cfg) + [""]
        L += [x if x.startswith("- ") else f"- {x}" for x in lineas] + ([""] if lineas else [])
    L += ["## Reproducibilidad", ""] + seccion_reproducibilidad(c, head) + [""]
    L += ["## Coherencia entre fuentes", ""]
    av = coherencia(c)
    L += [f"- {a}" for a in av] if av else ["- Sin discrepancias entre las fuentes revisadas."]
    L += ["", "## Fuentes", "", "| Archivo | Commit | Fecha del commit | Fecha dentro del archivo |", "|---|---|---|---|"]
    claves = list(c.cfg.fuentes) + [k for k in c.cfg.opcionales if k in c.datos]
    for k in claves:
        ruta = c.ruta(k)
        commit, fecha, dentro = procedencia(c.raiz, ruta, _fecha_archivo(c.datos.get(k)))
        L.append(f"| `{ruta}` | {commit} | {fecha} | {dentro} |")
    for k, cmd in c.ausentes.items():
        L.append(f"| `{c.ruta(k)}` | no disponible | — | — |")
    L += ["", "## Limitaciones", ""] + limitaciones(c, todas) + ["", "## Preguntas abiertas", ""]
    L += [f"{i}. {q}" for i, q in enumerate(PREGUNTAS_ABIERTAS, 1)]
    return "\n".join(L) + "\n"


def principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C-02: genera la página de métricas en Markdown")
    parser.add_argument("--salida", type=Path, default=None, help="ruta del Markdown (por defecto config/pagina_metricas.yaml: salida)")
    args = parser.parse_args(argv)
    try:
        c = cargar_contexto()
        texto = generar(c)
    except ErrorPagina as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    salida = args.salida or RAIZ / c.cfg.salida
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(texto, encoding="utf-8")
    print(f"Página de métricas escrita en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
