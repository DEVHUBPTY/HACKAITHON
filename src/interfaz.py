"""Lógica de presentación de la interfaz Streamlit · E1-15 (etapa 7 del reto, demo de 4 minutos).

``app.py`` solo pinta: todo lo que se puede decidir sin Streamlit vive aquí, en funciones puras y probables:

* **Bandeja:** el ranking leído de ``puntajes`` + ``evidencia`` (``config/modalidad_*.yaml`` fija la acción), reordenado con la
  misma regla de desempate de E1-10 (P descendente, mayor U, menor ID) para comprobar que la app muestra el ranking.
* **Ficha:** ``src.ficha.vista`` es la única fuente del texto (la app y el Markdown de Notion dicen lo mismo); aquí solo se
  reparte esa vista en «resumen» y «detalle desplegable» sin agregar, quitar ni reescribir ninguna línea.
* **Citas:** ``ID + campo`` -> valor, fecha, URL (hora de Panamá solo al mostrar; los datos siguen en UTC). Nunca la descripción
  del RSS (D-31) ni el nombre de un autor (D-32).
* **Enganche con E1-12:** ``cargar_generador`` busca la función de generación por configuración; si no existe todavía, la app
  lo dice y no inventa un borrador.

Sin red: ninguna función de este módulo abre una conexión ni descarga un modelo.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src import db
from src.cache import SinBorrador
from src.carga import intervalo_wilson
from src.configuracion import (
    RAIZ,
    ConfigInterfaz,
    ConfigModalidad,
    ConfigPrioridad,
    ConfigRestricciones,
    ConfigRevision,
    ConfigVerificacion,
    ReglasV13,
    cargar_carga,
    cargar_interfaz,
    cargar_modalidad,
    cargar_prioridad,
    cargar_reglas,
    cargar_restricciones,
    cargar_revision,
    cargar_temas,
    cargar_verificacion,
)
from src.esquemas import Cita, Ficha
from src.ficha import Linea, Seccion, Vista, texto_empate
from src.puntaje import COMPONENTES
from src.sectores import horizonte_de_grupo, sector_de_tema

logger = logging.getLogger(__name__)
PARAMETRO_DEMO = "--demo"
COLUMNA_COMPONENTE = {"R": "relevancia", "I": "impacto", "U": "urgencia", "N": "novedad", "E": "evidencia"}
ORIGEN_SINTETICO = "sintetico"
SIN_TEMA = "sin tema"
# Prefijo de ID -> (tabla, columna del ID, columna de URL, datos que acompañan a la cita como (etiqueta, columna, clase)).
# Cada fecha lleva SU etiqueta (de qué es): nunca una «Fecha» genérica ni una por otra (publicación ≠ detección; el año ≠ la extracción).
# Es un mapa fijo: nunca se arma SQL con texto del usuario. Clases: texto | fecha (UTC -> hora de Panamá).
Extra = tuple[str, str, str]
REGISTROS_CITABLES: dict[str, tuple[str, str, str | None, tuple[Extra, ...]]] = {
    "NOT-": ("noticias", "id_noticia", "url", (("Medio", "medio", "texto"), ("Publicación", "fecha_publicacion", "fecha"), ("Detección", "fecha_deteccion", "fecha"))),
    "SYN-": ("noticias", "id_noticia", "url", (("Medio", "medio", "texto"), ("Publicación", "fecha_publicacion", "fecha"), ("Detección", "fecha_deteccion", "fecha"))),
    "IND-": ("indicadores", "id_indicador", "fuente_url", (
        ("País", "pais_iso3", "texto"), ("Indicador", "indicador_id", "texto"), ("Año del dato", "anio", "texto"),
        ("Unidad", "unidad", "texto"), ("Fecha de extracción", "fecha_extraccion", "fecha"))),
    "SIS-": ("sismos", "id", "url", (("Hora del evento", "time", "fecha"), ("Estado", "status", "texto"), ("Lugar", "place", "texto"))),
    "GRP-": ("grupos", "id_grupo", None, (("Inicio del grupo", "fecha_inicio", "fecha"), ("Fin del grupo", "fecha_fin", "fecha"))),
}
PATRON_FILA_DEMO = re.compile(r"^\|(?P<celdas>.+)\|\s*$")


# ------------------------------------------------------------------ arranque: argumentos, base y hora


def modo_demo(argv: Sequence[str] | None = None) -> bool:
    """``streamlit run app.py -- --demo``: Streamlit pasa lo que sigue a ``--`` en ``sys.argv[1:]``."""
    return PARAMETRO_DEMO in (sys.argv[1:] if argv is None else argv)


def elegir_base(demo: bool, cfg: ConfigInterfaz, base_normal: Path = db.RUTA_BASE) -> tuple[Path, str | None]:
    """Ruta de la base y un aviso. El modo demo usa ``data/demo.duckdb``; si C-06 todavía no la creó, cae al snapshot y lo avisa."""
    if not demo:
        return base_normal, None
    ruta = RAIZ / cfg.demo.ruta_base
    if ruta.exists():
        return ruta, None
    return base_normal, cfg.textos.sin_demo


def hora_panama(valor: str | datetime | None, cfg: ConfigVerificacion, con_zona: bool = True) -> str:
    """ISO 8601 UTC (o ``datetime`` con zona) -> hora de Panamá para mostrar; nulo -> «desconocida». Los datos nunca se transforman."""
    p = cfg.presentacion
    if valor is None or valor == "":
        return p.fecha_desconocida
    fecha = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    if fecha.tzinfo is None:
        raise ValueError(f"la fecha necesita zona horaria (UTC): {valor!r}")
    local = fecha.astimezone(ZoneInfo(p.zona_horaria)).strftime(p.formato_fecha)
    return f"{local} ({p.sufijo_zona})" if con_zona else local


def fecha_de_corte(ruta_manifest: Path) -> str | None:
    """``fecha_corte_UTC`` del manifest tal como está (ISO UTC) o ``None`` si el archivo no existe."""
    if not ruta_manifest.exists():
        return None
    with ruta_manifest.open(encoding="utf-8") as f:
        return json.load(f).get("fecha_corte_UTC")


def leyenda_de_alcance(restricciones: ConfigRestricciones | None = None) -> str:
    """Leyenda D-51 de toda salida: sin descripción del RSS, siempre «basado únicamente en titular/metadatos»."""
    return (restricciones or cargar_restricciones()).leyendas_alcance.titular_metadatos


# ------------------------------------------------------------------ bandeja


@dataclass(frozen=True)
class FilaBandeja:
    """Una fila de la bandeja: lo que pide la spec (posición, tema, titular, P y rango, R·I·U·N·E, estado y acción)."""

    posicion: int
    id_grupo: str
    tema: str
    titular: str
    puntaje: float
    rango: str
    componentes: Mapping[str, float]
    estado_evidencia: str
    accion: str
    sintetico: bool = False
    sector: str | None = None       # E2-01: sector del tema según la modalidad (``None``: la modalidad no puntúa por sector o el tema no tiene sector)
    horizonte: str | None = None    # E2-01: inmediato · corto plazo · estructural (``None``: la modalidad no tiene escala)
    empate_con: int = 0             # D-105: cuántos otros grupos tienen el mismo P tal como se muestra


def leer_bandeja(con: Any, modalidad: str, nombres_de_tema: Mapping[str, str] | None = None) -> list[FilaBandeja]:
    """Filas de la bandeja de ``modalidad`` en el orden guardado por E1-10 (columna ``posicion``).

    La acción y el estado salen de ``evidencia`` (ya aplican la tabla de la modalidad); la app no recalcula nada.
    """
    nombres = nombres_de_tema if nombres_de_tema is not None else {k: t.nombre for k, t in cargar_temas().temas.items()}
    cfg_modalidad = cargar_modalidad(modalidad)
    cur = con.execute(
        "SELECT p.id_grupo, p.posicion, p.puntaje, p.rango, p.relevancia, p.impacto, p.urgencia, p.novedad, p.evidencia AS e_valor, "
        "COALESCE(p.empate_con, 0) AS empate_con, "
        "p.fecha_referencia, g.titular_central, g.tema_clasificado, e.estado, e.accion, "
        "EXISTS (SELECT 1 FROM noticias n WHERE n.id_grupo = p.id_grupo AND n.origen = ?) AS sintetico "
        "FROM puntajes p JOIN grupos g USING (id_grupo) JOIN evidencia e USING (id_grupo) "
        "WHERE e.modalidad = ? ORDER BY p.posicion",
        [ORIGEN_SINTETICO, modalidad],
    )
    nombres_col = [d[0] for d in cur.description]
    registros = [dict(zip(nombres_col, valores, strict=True)) for valores in cur.fetchall()]
    miembros = _fechas_de_titulares(con) if cfg_modalidad.horizonte is not None and registros else {}
    reglas = cargar_reglas()
    filas = []
    for f in registros:
        tema = f["tema_clasificado"]
        referencia = datetime.fromisoformat(str(f["fecha_referencia"]).replace("Z", "+00:00"))
        filas.append(
            FilaBandeja(
                posicion=int(f["posicion"]), id_grupo=f["id_grupo"], tema=nombres.get(tema, tema) if tema else SIN_TEMA,
                titular=f["titular_central"], puntaje=float(f["puntaje"]), rango=f["rango"],
                componentes={"R": f["relevancia"], "I": f["impacto"], "U": f["urgencia"], "N": f["novedad"], "E": f["e_valor"]},
                estado_evidencia=f["estado"], accion=f["accion"], sintetico=bool(f["sintetico"]),
                sector=sector_de_tema(tema, cfg_modalidad),
                horizonte=horizonte_de_grupo(miembros.get(f["id_grupo"], []), referencia, cfg_modalidad, reglas),
                empate_con=int(f["empate_con"]),
            )
        )
    return filas


def _fechas_de_titulares(con: Any) -> dict[str, list[dict[str, Any]]]:
    """Fechas de publicación y detección de los titulares de cada grupo (para el horizonte)."""
    cur = con.execute("SELECT id_grupo, fecha_publicacion, fecha_deteccion FROM noticias WHERE id_grupo IS NOT NULL")
    por_grupo: dict[str, list[dict[str, Any]]] = {}
    for id_grupo, publicacion, deteccion in cur.fetchall():
        por_grupo.setdefault(str(id_grupo), []).append({"fecha_publicacion": publicacion, "fecha_deteccion": deteccion})
    return por_grupo


@dataclass(frozen=True)
class BloqueSector:
    """Un bloque de la bandeja bancaria: las filas de un sector (``sector`` ``None``: grupos sin sector) en el orden de E1-10."""

    sector: str | None
    etiqueta: str
    filas: tuple[FilaBandeja, ...]
    total: int = 0      # filas del sector antes de limitar (0: igual a ``len(filas)``)


def agrupar_por_sector(filas: Sequence[FilaBandeja], modalidad: ConfigModalidad, cfg: ConfigPrioridad | None = None) -> list[BloqueSector] | None:
    """Agrupa la bandeja por sector (E2-01); ``None`` si la modalidad no puntúa por sector (bandeja plana).

    Las filas conservan su orden dentro del bloque (el de E1-10). Los sectores se ordenan por el mayor P de sus grupos
    (comparado a ``decimales_p``) y, en un empate, por el orden de ``sectores_validos``; los grupos sin sector van al final.
    """
    if modalidad.bandeja is None:
        return None
    d = (cfg or cargar_prioridad()).comparacion.decimales_empate      # D-105: P tal como se muestra
    declarados = {s: i for i, s in enumerate(cargar_temas().sectores_validos)}
    por_sector: dict[str | None, list[FilaBandeja]] = {}
    for f in filas:
        por_sector.setdefault(f.sector, []).append(f)
    con_sector = sorted(
        (s for s in por_sector if s is not None),
        key=lambda s: (-max(round(f.puntaje, d) for f in por_sector[s]), declarados.get(s, len(declarados)), s),
    )
    bloques = [BloqueSector(s, modalidad.bandeja.etiquetas_sector[s], tuple(por_sector[s]), len(por_sector[s])) for s in con_sector]
    if None in por_sector:
        bloques.append(BloqueSector(None, modalidad.bandeja.sin_sector, tuple(por_sector[None]), len(por_sector[None])))
    return bloques


def limitar_por_sector(bloques: Sequence[BloqueSector], maximo: int) -> list[BloqueSector]:
    """Primero se agrupa y después se limita: cada sector conserva sus primeras ``maximo`` filas y ninguno se oculta (X40)."""
    return [BloqueSector(b.sector, b.etiqueta, b.filas[:maximo], b.total or len(b.filas)) for b in bloques]


def etiqueta_de_horizonte(horizonte: str | None, modalidad: ConfigModalidad) -> str | None:
    """Texto del horizonte para la persona (YAML de la modalidad); el código si la modalidad no define su etiqueta."""
    if horizonte is None or modalidad.horizonte is None:
        return horizonte
    return modalidad.horizonte.etiquetas.get(horizonte, horizonte)


def lineas_de_bandeja(filas: Sequence[FilaBandeja], modalidad: ConfigModalidad, cfg: ConfigInterfaz | None = None) -> list[str] | None:
    """La bandeja por sector en texto (para la CLI de ``src.puntaje``); ``None`` si la modalidad no puntúa por sector."""
    bloques = agrupar_por_sector(filas, modalidad)
    if bloques is None:
        return None
    cfg = cfg or cargar_interfaz()
    ancho, decimales = cfg.bandeja.ancho_titular_cli, cfg.bandeja.decimales_puntaje
    lineas = []
    for b in bloques:
        lineas.append(f"{b.etiqueta} ({len(b.filas)})")
        lineas += [
            f"  {f.posicion}. {f.id_grupo} · P={f.puntaje:.{decimales}f} ({f.rango}) · {etiqueta_de_horizonte(f.horizonte, modalidad) or '-'} · {f.accion} · {f.titular[:ancho]}"
            + (f" · {texto_empate(f.empate_con)}" if f.empate_con else "")
            for f in b.filas
        ]
    return lineas


def ordenar_bandeja(filas: Sequence[FilaBandeja], reglas: ReglasV13 | None = None, cfg: ConfigPrioridad | None = None) -> list[FilaBandeja]:
    """Reordena con la regla del reto (E1-10, D-105): P tal como se muestra descendente y desempate de ``reglas.desempate`` (mayor U, luego ID)."""
    reglas = reglas or cargar_reglas()
    cfg = cfg or cargar_prioridad()
    d = cfg.comparacion.decimales_p

    def clave(f: FilaBandeja) -> tuple[Any, ...]:
        partes: list[Any] = [-round(f.puntaje, cfg.comparacion.decimales_empate)]
        for criterio in reglas.desempate:
            partes.append(-round(f.componentes["U"], d) if criterio == "u_desc" else f.id_grupo)
        return tuple(partes)

    return sorted(filas, key=clave)


def comprobar_orden(filas: Sequence[FilaBandeja], reglas: ReglasV13 | None = None, cfg: ConfigPrioridad | None = None) -> bool:
    """¿La bandeja leída de la base coincide con el ranking recalculado con el desempate? Si no, la base está desactualizada."""
    return [f.id_grupo for f in filas] == [f.id_grupo for f in ordenar_bandeja(filas, reglas, cfg)]


def encabezado_bandeja(con: Any, ruta_manifest: Path, cfg_ver: ConfigVerificacion | None = None) -> dict[str, str]:
    """Versión de reglas y **fecha de corte del snapshot** (hora de Panamá) que van arriba de la bandeja."""
    cfg_ver = cfg_ver or cargar_verificacion()
    fila = con.execute("SELECT version_reglas FROM puntajes LIMIT 1").fetchone()
    corte = fecha_de_corte(ruta_manifest)
    return {
        "version_reglas": fila[0] if fila else "sin puntajes",
        "fecha_corte": hora_panama(corte, cfg_ver) if corte else "desconocida (sin manifest)",
    }


def resolver_caso(valor: str | None, filas: Sequence[FilaBandeja], casos: Mapping[str, str] | None = None) -> str | None:
    """Atajo ``?caso=``: acepta un ID ``GRP-…``, la posición en la bandeja o un ``CASO-…`` (``casos``: ``CASO-`` -> ``GRP-``, E1-16)."""
    if not valor:
        return None
    valor = valor.strip()
    if casos and valor in casos:
        return casos[valor] if any(f.id_grupo == casos[valor] for f in filas) else None
    for f in filas:
        if f.id_grupo == valor:
            return f.id_grupo
    if valor.isdigit():
        return next((f.id_grupo for f in filas if f.posicion == int(valor)), None)
    return None


# ------------------------------------------------------------------ ficha


@dataclass(frozen=True)
class PlanFicha:
    """La vista de la ficha repartida para pintarla: resumen arriba y detalle desplegable. Es un reparto: no cambia el texto."""

    resumen: tuple[Seccion, ...]
    desglose: tuple[Linea, ...]
    detalle: tuple[Seccion, ...]


def plan_de_ficha(vista: Vista, cfg: ConfigInterfaz | None = None) -> PlanFicha:
    """Reparte ``vista`` según ``config/interfaz.yaml``: resumen = qué se reporta + acción (sin el desglose); el resto, desplegable."""
    cfg = cfg or cargar_interfaz()
    resumen: list[Seccion] = []
    desglose: list[Linea] = []
    detalle: list[Seccion] = []
    for s in vista.secciones:
        if s.clave in cfg.ficha.secciones_resumen:
            en_desglose = [x for x in s.lineas if x.texto.startswith(cfg.ficha.prefijo_desglose)]
            desglose += en_desglose
            resto = tuple(x for x in s.lineas if x not in en_desglose)
            resumen.append(Seccion(s.clave, s.titulo, resto))
        elif s.clave in cfg.ficha.secciones_desplegables:
            detalle.append(s)
        else:
            raise ValueError(f"sección sin ubicar en la interfaz: {s.clave}")
    return PlanFicha(tuple(resumen), tuple(desglose), tuple(detalle))


def lineas_de_plan(plan: PlanFicha) -> list[str]:
    """Todos los textos del plan: debe ser, sin sobrar ni faltar, el texto de ``vista`` (la prueba lo comprueba)."""
    return [x.texto for s in (*plan.resumen, *plan.detalle) for x in s.lineas] + [x.texto for x in plan.desglose]


def citas_de_ficha(ficha: Ficha) -> list[Cita]:
    """Citas únicas de «qué está respaldado», en el orden en que aparecen (las que la app vuelve clicables)."""
    r = ficha.respaldado
    vistas: dict[tuple[str, str], Cita] = {}
    for x in (*r.reportes, *r.datos_oficiales, *r.contexto_oficial, *r.eventos_oficiales, *r.declaraciones):
        for c in x.citas:
            vistas.setdefault((c.id, c.campo), c)
    return list(vistas.values())


# ------------------------------------------------------------------ citas clicables


@dataclass(frozen=True)
class DetalleCita:
    """Lo que muestra una cita al hacer clic: ID, campo, valor y los datos que la acompañan, cada uno con su etiqueta, más la URL."""

    id: str
    campo: str
    valor: str
    url: str | None
    encontrada: bool = True
    sintetico: bool = False
    nota: str | None = None
    filas: tuple[tuple[str, str], ...] = ()


def _no_encontrada(id_registro: str, campo: str, nota: str) -> DetalleCita:
    return DetalleCita(id_registro, campo, "", None, False, nota=nota)


def detalle_cita(con: Any, id_registro: str, campo: str, cfg: ConfigInterfaz | None = None, cfg_ver: ConfigVerificacion | None = None) -> DetalleCita:
    """Resuelve ``ID + campo`` contra la base. Un registro o campo inexistente se dice; un campo oculto (descripción del RSS) no se muestra.

    Un indicador trae país, indicador, **año del dato**, unidad y la **fecha de extracción** por separado, con el aviso de que es un dato anual;
    una noticia, su publicación y su detección por separado; un sismo, la hora del evento en Panamá y su estado.
    """
    cfg = cfg or cargar_interfaz()
    cfg_ver = cfg_ver or cargar_verificacion()
    if campo in cfg.ficha.campos_ocultos:
        return _no_encontrada(id_registro, campo, "Campo no disponible en la interfaz (redistribución restringida).")
    destino = next((v for k, v in REGISTROS_CITABLES.items() if id_registro.startswith(k)), None)
    if destino is None:
        return _no_encontrada(id_registro, campo, "Este tipo de registro todavía no está en la base.")
    tabla, col_id, col_url, extras = destino
    if campo not in db.columnas(tabla):
        return _no_encontrada(id_registro, campo, f"El registro no tiene el campo «{campo}».")
    columnas = [campo, col_url or "NULL", *(c for _, c, _ in extras)]
    pide_origen = tabla == "noticias"
    cur = con.execute(
        f"SELECT {', '.join(columnas)}{', origen' if pide_origen else ''} FROM {tabla} WHERE {col_id} = ?",  # noqa: S608 - nombres de un mapa fijo y validados contra el esquema
        [id_registro],
    )
    fila = cur.fetchone()
    if fila is None:
        return _no_encontrada(id_registro, campo, "El registro no existe en esta base.")
    valor, url, datos = fila[0], fila[1], fila[2 : 2 + len(extras)]
    texto = "sin dato" if valor is None else str(valor)    # un nulo es un nulo: nunca 0
    filas: list[tuple[str, str]] = []
    for (etiqueta, _, clase), dato in zip(extras, datos, strict=True):
        if clase == "fecha":
            filas.append((etiqueta, hora_panama(str(dato) if dato else None, cfg_ver)))
        else:
            filas.append((etiqueta, "sin dato" if dato is None else str(dato)))
    if tabla == "indicadores":
        unidad = dict(filas).get("Unidad", "")
        if campo == "valor" and valor is not None:
            texto = f"{float(valor):.{cfg.citas.decimales_valor}f}" + (f" {unidad}" if unidad and unidad != "sin dato" else "")
        filas.append(("Aviso", cfg.citas.aviso_anual))
    sintetico = (pide_origen and fila[-1] == ORIGEN_SINTETICO) or id_registro.startswith("SYN-")
    return DetalleCita(id_registro, campo, texto, url, True, bool(sintetico), filas=tuple(filas))


# ------------------------------------------------------------------ calidad (pantalla 1)


@dataclass(frozen=True)
class Proporcion:
    """Una proporción con su n y su intervalo de Wilson del 95 % (toda proporción reportada los lleva)."""

    k: int
    n: int
    proporcion: float | None
    ic95: tuple[float, float] | None


def proporcion(k: int, n: int, z: float | None = None) -> Proporcion:
    z = z if z is not None else cargar_carga().salida.z_intervalo_confianza
    return Proporcion(k, n, (k / n) if n else None, intervalo_wilson(k, n, z))


def resumen_de_calidad(con: Any) -> dict[str, Any]:
    """Conteos de la base: titulares totales, ruido marcado (no borrado) por motivo, duplicados eliminados y origen sintético."""
    total = con.execute("SELECT count(*) FROM noticias").fetchone()[0]
    por_motivo = dict(con.execute("SELECT motivo_ruido, count(*) FROM noticias WHERE es_ruido GROUP BY 1 ORDER BY 2 DESC, 1").fetchall())
    ruido = sum(por_motivo.values())
    return {
        "titulares": total,
        "ruido": proporcion(ruido, total),
        "ruido_por_motivo": por_motivo,
        "en_bandeja": total - ruido,
        "duplicados_eliminados": con.execute("SELECT count(*) FROM duplicados_eliminados").fetchone()[0],
        "sinteticos": con.execute("SELECT count(*) FROM noticias WHERE origen = ?", [ORIGEN_SINTETICO]).fetchone()[0],
        "grupos": con.execute("SELECT count(*) FROM grupos").fetchone()[0],
        "indicadores": con.execute("SELECT count(*), count(valor) FROM indicadores").fetchone(),
        "sismos": con.execute("SELECT count(*) FROM sismos").fetchone()[0],
    }


def reporte_de_carga(ruta_reporte: Path, procesados: Path | None = None) -> dict[str, Any]:
    """Reporte de carga (E1-02): el ``reporte_calidad.json`` si existe; si no, se recalcula del snapshot (local, sin red)."""
    if ruta_reporte.exists():
        return json.loads(ruta_reporte.read_text(encoding="utf-8"))
    from src.carga import CARPETA_PROCESADOS, cargar_todo, construir_reporte   # import tardío: pandera pesa

    config = cargar_carga()
    return construir_reporte(cargar_todo(procesados or CARPETA_PROCESADOS, config), config)


# ------------------------------------------------------------------ consulta y revisión


def ids_sinteticos(con: Any, ids: Sequence[str]) -> set[str]:
    """Cuáles de ``ids`` son registros sintéticos (``origen = sintetico`` o prefijo ``SYN-``)."""
    if not ids:
        return set()
    marcas = ",".join("?" for _ in ids)
    filas = con.execute(f"SELECT id_noticia FROM noticias WHERE origen = ? AND id_noticia IN ({marcas})", [ORIGEN_SINTETICO, *ids]).fetchall()  # noqa: S608 - solo marcadores
    return {f[0] for f in filas} | {i for i in ids if i.startswith("SYN-")}


def estado_de_revision(con: Any, id_grupo: str, cfg: ConfigInterfaz | None = None, revisiones: Any = None, modalidad: str = "editorial") -> str:
    """Estado de revisión de un grupo: la última fila de ``revisiones`` de su caso (E1-16); sin caso, el estado inicial ``nuevo``."""
    if revisiones is None:
        return (cfg or cargar_interfaz()).revision.estado_inicial
    return revisiones.estado_de_grupo(id_grupo, modalidad)


# ------------------------------------------------------------------ revisión humana (pantalla 6, E1-16)


def ruta_de_revision(demo: bool, cfg: ConfigRevision | None = None) -> Path:
    """Base de las revisiones: la real o, en modo demo, la de la demo (nunca se mezclan)."""
    from src.revision import ruta_de_revision as ruta

    return ruta(demo, cfg)


def revisores_de(modalidad: str, cfg: ConfigRevision | None = None) -> list[str]:
    """Nombres de los revisores de la modalidad (``config/revision.yaml``; sin autenticación, D-49)."""
    return [r.nombre for r in (cfg or cargar_revision()).revisores if r.modalidad == modalidad]


def rol_de(revisor: str, modalidad: str, cfg: ConfigRevision | None = None) -> str:
    return next((r.rol for r in (cfg or cargar_revision()).revisores if r.nombre == revisor and r.modalidad == modalidad), "")


def acciones_disponibles(estado: str, cfg: ConfigRevision | None = None) -> dict[str, bool]:
    """Para cada acción, si parte del estado actual (las transiciones de ``config/revision.yaml``): los botones se habilitan con esto."""
    cfg = cfg or cargar_revision()
    return {nombre: estado in a.desde for nombre, a in cfg.acciones.items()}


def es_provisional(revisor: str, modalidad: str | None = None, cfg: ConfigRevision | None = None) -> bool:
    """El revisor está declarado ``provisional`` en ``config/revision.yaml`` (D-112)."""
    return (cfg or cargar_revision()).es_provisional(revisor, modalidad)


def tabla_historial(filas: Sequence[Any], cfg_ver: ConfigVerificacion | None = None, modalidad: str | None = None, cfg_rev: ConfigRevision | None = None) -> list[dict[str, Any]]:
    """El historial de un caso como filas para mostrar, con la fecha en hora de Panamá (los datos siguen en UTC).

    Si el revisor es provisional (D-112), su celda lleva la marca de ``textos.marca_provisional``."""
    cfg_ver = cfg_ver or cargar_verificacion()
    cfg_rev = cfg_rev or cargar_revision()
    return [
        {
            "#": f.id_revision, "Fecha": hora_panama(f.fecha_utc, cfg_ver), "Acción": f.accion, "De": f.estado_anterior, "A": f.estado_nuevo,
            "Revisor": f"{f.revisor} ({f.rol})" + (f" · {cfg_rev.textos.marca_provisional}" if es_provisional(f.revisor, modalidad, cfg_rev) else ""),
            "Versión": f.version, "Motivo": f.motivo or "", "Comentario": f.comentario or "",
        }
        for f in filas
    ]


def tabla_versiones(versiones: Sequence[Any], cfg_ver: ConfigVerificacion | None = None) -> list[dict[str, Any]]:
    cfg_ver = cfg_ver or cargar_verificacion()
    return [{"Versión": v.version, "Origen": v.origen, "Base": v.version_base, "Fecha": hora_panama(v.fecha_utc, cfg_ver), "Revisor": v.revisor} for v in versiones]


def vinculos_oficiales_de(ficha: Ficha) -> list[str]:
    """Los IDs oficiales (``IND-``, ``SIS-``, ``SBP-``) que respaldan la ficha y que una persona puede rechazar."""
    ids = [c.id for x in (*ficha.respaldado.datos_oficiales, *ficha.respaldado.contexto_oficial, *ficha.respaldado.eventos_oficiales) for c in x.citas]
    return list(dict.fromkeys(ids))


def rotulo_de_elemento(clave: str, etiquetas: Mapping[str, str] | None = None) -> str:
    """Cómo se nombra un texto corregible para una persona: el rótulo de su sección y su posición (desde 1).

    Con ``etiquetas`` (``config/interfaz.yaml`` · ``paquete.etiquetas``) ``observaciones.0`` se ve «Resumen · Observaciones · 1» y
    ``afirmaciones.A1`` «Afirmaciones validadas · A1»; una sección sin rótulo conserva su clave.
    """
    seccion, _, resto = clave.partition(".")
    rotulo = (etiquetas or {}).get(seccion)
    return clave if rotulo is None else " · ".join(p for p in (rotulo, str(int(resto) + 1) if resto.isdigit() else resto) if p)


def etiqueta_de_elemento(clave: str, texto: str, largo: int, etiquetas: Mapping[str, str] | None = None) -> str:
    """Etiqueta del selector de corrección: el rótulo del elemento (``rotulo_de_elemento``) y el principio del texto."""
    return f"{rotulo_de_elemento(clave, etiquetas)} · {texto[:largo]}" + ("…" if len(texto) > largo else "")


# ------------------------------------------------------------------ modo demo: pasos del guion


@dataclass(frozen=True)
class PasoDemo:
    tiempo: str
    pantalla: str
    accion: str
    dialogo: str


def pasos_de_demo(texto: str) -> list[PasoDemo]:
    """Filas de la tabla «Recorrido cronometrado» de ``docs/demo.md`` (tiempo · pantalla · qué se hace · qué se dice)."""
    pasos: list[PasoDemo] = []
    for linea in texto.splitlines():
        m = PATRON_FILA_DEMO.match(linea.strip())
        if not m:
            continue
        celdas = [c.strip() for c in m.group("celdas").split("|")]
        if len(celdas) < 4 or not re.match(r"^\d+:\d{2}", celdas[0]):
            continue
        pasos.append(PasoDemo(celdas[0], celdas[1], celdas[2], celdas[3].strip('"“”')))
    return pasos


def leer_guion(cfg: ConfigInterfaz | None = None) -> list[PasoDemo]:
    cfg = cfg or cargar_interfaz()
    ruta = RAIZ / cfg.demo.guion
    return pasos_de_demo(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


# ------------------------------------------------------------------ enganche con la generación (E1-12)


@dataclass
class EstadoPaquete:
    """Resultado de pedir el borrador: ``disponible`` (hay ``paquete``), ``sin_integrar`` (E1-12 no está) o ``sin_cache``."""

    estado: str
    paquete: Any = None
    motivo: str | None = None


class ErrorDeIntegracion(RuntimeError):
    """La generación existe pero no se puede usar: falla al importarla o su contrato no coincide. No es «sin integrar»."""


def cargar_generador(cfg: ConfigInterfaz | None = None) -> Callable[..., Any] | None:
    """La función de generación de E1-12 (``config/interfaz.yaml:generacion``, lista cerrada) o ``None`` si todavía no existe.

    «Ausente» = el módulo no existe o no define la función. Cualquier otro fallo al importar (una dependencia interna que no está,
    un error de sintaxis) lanza ``ErrorDeIntegracion``: se registra y se dice, no se confunde con que falte.
    Integrada en E1-14: ``src.generacion.generar_paquete`` (el nombre está fijado en el ``Literal`` de ``GeneracionInterfaz``).
    Contrato esperado: ``funcion(id_grupo, modalidad, *, solo_cache=True) -> mapa | modelo pydantic | None``.
    """
    g = (cfg or cargar_interfaz()).generacion
    try:
        modulo = importlib.import_module(g.modulo)
    except ModuleNotFoundError as exc:
        if exc.name == g.modulo:
            return None
        logger.exception("Error al importar %s: falta %s", g.modulo, exc.name)
        raise ErrorDeIntegracion(f"error al importar {g.modulo}: falta el módulo «{exc.name}»") from exc
    except Exception as exc:  # noqa: BLE001 - cualquier fallo del módulo de otra tarea se informa, no rompe la pantalla
        logger.exception("Error al importar %s", g.modulo)
        raise ErrorDeIntegracion(f"error al importar {g.modulo}: {type(exc).__name__}: {exc}") from exc
    funcion = getattr(modulo, g.funcion, None)
    return funcion if callable(funcion) else None


def obtener_paquete(
    id_grupo: str, modalidad: str, cfg: ConfigInterfaz | None = None, generador: Callable[..., Any] | None = None, ruta_base: Path | None = None
) -> EstadoPaquete:
    """Pide el borrador al generador **solo desde caché** (``solo_cache``): la interfaz nunca espera al modelo ni usa la red.

    Estados: ``disponible``; ``sin_integrar`` (el módulo o la función no existen); ``error_integracion`` (falla al importar o el
    contrato no coincide); ``sin_cache`` (no hay borrador guardado o el generador no pudo leerlo).
    """
    cfg = cfg or cargar_interfaz()
    try:
        generador = generador or cargar_generador(cfg)
    except ErrorDeIntegracion as exc:
        return EstadoPaquete("error_integracion", motivo=f"Error de integración con la generación: {exc}")
    if generador is None:
        return EstadoPaquete("sin_integrar", motivo=cfg.textos.sin_borrador)
    try:
        extra = {} if ruta_base is None else {"base": ruta_base}  # la base que muestra la interfaz (snapshot o demo) es la de la ficha
        paquete = generador(id_grupo, modalidad, solo_cache=cfg.generacion.solo_cache, **extra)
    except TypeError as exc:
        logger.exception("El contrato de la generación no coincide")
        return EstadoPaquete("error_integracion", motivo=f"Error de integración con la generación: el contrato no coincide ({exc}); se esperaba solo_cache=")
    except SinBorrador as exc:  # sin caché o acción que no genera borrador (E1-14): mensaje honesto, sin LLM ni red
        return EstadoPaquete("sin_cache", motivo=str(exc))
    except Exception as exc:  # noqa: BLE001 - un fallo del LLM o de la red nunca debe romper la pantalla
        logger.warning("La generación falló: %s", type(exc).__name__)
        return EstadoPaquete("sin_cache", motivo=f"{cfg.textos.borrador_no_listo} ({type(exc).__name__})")
    if paquete is None:
        return EstadoPaquete("sin_cache", motivo=cfg.textos.borrador_no_listo)
    return EstadoPaquete("disponible", paquete)


def _texto_de_elemento(x: Any) -> str:
    """Un elemento de lista del paquete como texto: oración con sus afirmaciones, vacío con su motivo, afirmación con su tipo."""
    if isinstance(x, str):
        return x
    if isinstance(x, Mapping):
        if "tipo" in x and "texto" in x and "id" in x:  # afirmación validada
            citas = ", ".join(f"{c.get('id')} · {c.get('campo')}" for c in x.get("citas", []))
            base = ", ".join(x.get("base") or [])  # una inferencia o hipótesis cita sus afirmaciones base (CLAUDE.md)
            return f"{x['id']} [{x['tipo']}] {x['texto']}" + (f" (base: {base})" if base else "") + (f" ({citas})" if citas else "")
        if "texto" in x and "vacio" in x:  # pregunta de investigación
            return f"{x['texto']} (vacío: {x['vacio']})"
        if "texto" in x:  # oración: se muestran las afirmaciones en que se apoya
            apoyo = ", ".join(x.get("afirmaciones") or [])
            parte = f"{x['parte']}: " if x.get("parte") else ""
            return f"{parte}{x['texto']}" + (f" [{apoyo}]" if apoyo else "")
        if "motivo" in x and "referencia" in x:  # vacío
            return f"{x['referencia']}: {x['motivo']}"
        if "sector" in x and "motivo" in x:  # sector del boletín bancario (E2-02)
            return f"{x['sector']}: {x['motivo']}"
    return json.dumps(x, ensure_ascii=False)


def secciones_de_paquete(paquete: Any, etiquetas: Mapping[str, str] | None = None) -> list[tuple[str, list[str]]]:
    """Aplana un paquete (mapa o modelo pydantic) en ``(título, párrafos)``: oraciones con sus afirmaciones, vacíos con su motivo.

    Con ``etiquetas`` las secciones salen en el orden en que ``config/interfaz.yaml`` las declara (E2-04): una versión guardada ordena sus
    claves alfabéticamente y el boletín mostraría la hipótesis de impacto antes que las observaciones. Las claves sin rótulo van al final.
    """
    datos = paquete.model_dump(mode="json") if hasattr(paquete, "model_dump") else dict(paquete)
    if etiquetas:
        orden = {k: i for i, k in enumerate(etiquetas)}
        datos = dict(sorted(datos.items(), key=lambda kv: orden.get(kv[0], len(orden))))
    salida: list[tuple[str, list[str]]] = []
    for clave, valor in datos.items():
        if isinstance(valor, bool):
            parrafos = ["Sí" if valor else "No"]
        elif isinstance(valor, str):
            parrafos = [valor]
        elif isinstance(valor, (list, tuple)):
            parrafos = [_texto_de_elemento(x) for x in valor]
        elif isinstance(valor, Mapping) and "texto" in valor:
            parrafos = [_texto_de_elemento(valor)]
        elif isinstance(valor, Mapping):
            parrafos = [f"{k}: {v}" for k, v in valor.items()]
        elif valor is None:
            parrafos = []
        else:
            parrafos = [str(valor)]
        if parrafos:
            salida.append(((etiquetas or {}).get(clave) or clave.replace("_", " ").capitalize(), parrafos))
    return salida


@dataclass
class Contexto:
    """Lo que comparten las pantallas en una ejecución: configuración, modalidad y la conexión de solo lectura."""

    cfg: ConfigInterfaz
    cfg_ver: ConfigVerificacion
    con: Any
    modalidad: str
    demo: bool = False
    aviso_base: str | None = None
    filas: list[FilaBandeja] = field(default_factory=list)
    ruta_base: Path = db.RUTA_BASE
    revisiones: Any = None          # ``src.revision.Revisiones`` (E1-16): la base de revisiones; se abre aparte de la de solo lectura
