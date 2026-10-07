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
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src import db
from src.carga import intervalo_wilson
from src.configuracion import (
    RAIZ,
    ConfigInterfaz,
    ConfigPrioridad,
    ConfigRestricciones,
    ConfigVerificacion,
    ReglasV13,
    cargar_carga,
    cargar_interfaz,
    cargar_prioridad,
    cargar_reglas,
    cargar_restricciones,
    cargar_temas,
    cargar_verificacion,
)
from src.esquemas import Cita, Ficha
from src.ficha import Linea, Seccion, Vista
from src.puntaje import COMPONENTES

PARAMETRO_DEMO = "--demo"
COLUMNA_COMPONENTE = {"R": "relevancia", "I": "impacto", "U": "urgencia", "N": "novedad", "E": "evidencia"}
ORIGEN_SINTETICO = "sintetico"
SIN_TEMA = "sin tema"
# Prefijo de ID -> (tabla, columna del ID, columna de fecha, columna de URL). Es un mapa fijo: nunca se arma SQL con texto del usuario.
REGISTROS_CITABLES: dict[str, tuple[str, str, str | None, str | None]] = {
    "NOT-": ("noticias", "id_noticia", "fecha_publicacion", "url"),
    "SYN-": ("noticias", "id_noticia", "fecha_publicacion", "url"),
    "IND-": ("indicadores", "id_indicador", "fecha_extraccion", "fuente_url"),
    "SIS-": ("sismos", "id", "time", "url"),
    "GRP-": ("grupos", "id_grupo", "fecha_fin", None),
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


def leer_bandeja(con: Any, modalidad: str, nombres_de_tema: Mapping[str, str] | None = None) -> list[FilaBandeja]:
    """Filas de la bandeja de ``modalidad`` en el orden guardado por E1-10 (columna ``posicion``).

    La acción y el estado salen de ``evidencia`` (ya aplican la tabla de la modalidad); la app no recalcula nada.
    """
    nombres = nombres_de_tema if nombres_de_tema is not None else {k: t.nombre for k, t in cargar_temas().temas.items()}
    cur = con.execute(
        "SELECT p.id_grupo, p.posicion, p.puntaje, p.rango, p.relevancia, p.impacto, p.urgencia, p.novedad, p.evidencia AS e_valor, "
        "g.titular_central, g.tema_clasificado, e.estado, e.accion, "
        "EXISTS (SELECT 1 FROM noticias n WHERE n.id_grupo = p.id_grupo AND n.origen = ?) AS sintetico "
        "FROM puntajes p JOIN grupos g USING (id_grupo) JOIN evidencia e USING (id_grupo) "
        "WHERE e.modalidad = ? ORDER BY p.posicion",
        [ORIGEN_SINTETICO, modalidad],
    )
    nombres_col = [d[0] for d in cur.description]
    filas = []
    for valores in cur.fetchall():
        f = dict(zip(nombres_col, valores, strict=True))
        tema = f["tema_clasificado"]
        filas.append(
            FilaBandeja(
                posicion=int(f["posicion"]), id_grupo=f["id_grupo"], tema=nombres.get(tema, tema) if tema else SIN_TEMA,
                titular=f["titular_central"], puntaje=float(f["puntaje"]), rango=f["rango"],
                componentes={"R": f["relevancia"], "I": f["impacto"], "U": f["urgencia"], "N": f["novedad"], "E": f["e_valor"]},
                estado_evidencia=f["estado"], accion=f["accion"], sintetico=bool(f["sintetico"]),
            )
        )
    return filas


def ordenar_bandeja(filas: Sequence[FilaBandeja], reglas: ReglasV13 | None = None, cfg: ConfigPrioridad | None = None) -> list[FilaBandeja]:
    """Reordena con la regla de E1-10: P descendente (a ``decimales_p``) y desempate de ``reglas.desempate`` (mayor U, menor ID)."""
    reglas = reglas or cargar_reglas()
    d = (cfg or cargar_prioridad()).comparacion.decimales_p

    def clave(f: FilaBandeja) -> tuple[Any, ...]:
        partes: list[Any] = [-round(f.puntaje, d)]
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


def resolver_caso(valor: str | None, filas: Sequence[FilaBandeja]) -> str | None:
    """Atajo ``?caso=``: acepta un ID ``GRP-…`` o la posición en la bandeja. Un ``CASO-`` aún no existe (lo asigna E1-16)."""
    if not valor:
        return None
    valor = valor.strip()
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
    for x in (*r.reportes, *r.datos_oficiales, *r.eventos_oficiales, *r.declaraciones):
        for c in x.citas:
            vistas.setdefault((c.id, c.campo), c)
    return list(vistas.values())


# ------------------------------------------------------------------ citas clicables


@dataclass(frozen=True)
class DetalleCita:
    """Lo que muestra una cita al hacer clic: ID, campo, valor, fecha (hora de Panamá) y URL."""

    id: str
    campo: str
    valor: str
    fecha: str
    url: str | None
    encontrada: bool = True
    sintetico: bool = False
    nota: str | None = None


def detalle_cita(con: Any, id_registro: str, campo: str, cfg: ConfigInterfaz | None = None, cfg_ver: ConfigVerificacion | None = None) -> DetalleCita:
    """Resuelve ``ID + campo`` contra la base. Un registro o campo inexistente se dice; un campo oculto (descripción del RSS) no se muestra."""
    cfg = cfg or cargar_interfaz()
    cfg_ver = cfg_ver or cargar_verificacion()
    desconocida = cfg_ver.presentacion.fecha_desconocida
    if campo in cfg.ficha.campos_ocultos:
        return DetalleCita(id_registro, campo, "", desconocida, None, False, nota="Campo no disponible en la interfaz (redistribución restringida).")
    destino = next((v for k, v in REGISTROS_CITABLES.items() if id_registro.startswith(k)), None)
    if destino is None:
        return DetalleCita(id_registro, campo, "", desconocida, None, False, nota="Este tipo de registro todavía no está en la base.")
    tabla, col_id, col_fecha, col_url = destino
    if campo not in db.columnas(tabla):
        return DetalleCita(id_registro, campo, "", desconocida, None, False, nota=f"El registro no tiene el campo «{campo}».")
    extra = ", origen" if tabla == "noticias" else ""
    cur = con.execute(
        f"SELECT {campo} AS valor, {col_fecha or 'NULL'} AS fecha, {col_url or 'NULL'} AS url{extra} FROM {tabla} WHERE {col_id} = ?",  # noqa: S608 - nombres de un mapa fijo y validados contra el esquema
        [id_registro],
    )
    fila = cur.fetchone()
    if fila is None:
        return DetalleCita(id_registro, campo, "", desconocida, None, False, nota="El registro no existe en esta base.")
    valor, fecha, url = fila[0], fila[1], fila[2]
    sintetico = tabla == "noticias" and fila[3] == ORIGEN_SINTETICO or id_registro.startswith("SYN-")
    texto = "sin dato" if valor is None else str(valor)    # un nulo es un nulo: nunca 0
    return DetalleCita(id_registro, campo, texto, hora_panama(str(fecha) if fecha else None, cfg_ver), url, True, sintetico)


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


def estado_de_revision(con: Any, id_grupo: str, cfg: ConfigInterfaz | None = None) -> str:
    """Estado de revisión de un grupo. TODO(E1-16): leer la última fila de la tabla ``revisiones``; hoy todo grupo está en el estado inicial."""
    return (cfg or cargar_interfaz()).revision.estado_inicial


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


def cargar_generador(cfg: ConfigInterfaz | None = None) -> Callable[..., Any] | None:
    """La función de generación de E1-12 (``config/interfaz.yaml:generacion``) o ``None`` si todavía no existe.

    TODO(E1-12): al integrar esa tarea, el nombre real de la función va en el YAML; la app no cambia.
    Contrato esperado: ``funcion(id_grupo, modalidad, *, solo_cache=True) -> mapa | modelo pydantic | None``.
    """
    g = (cfg or cargar_interfaz()).generacion
    try:
        modulo = importlib.import_module(g.modulo)
    except ImportError:
        return None
    funcion = getattr(modulo, g.funcion, None)
    return funcion if callable(funcion) else None


def obtener_paquete(id_grupo: str, modalidad: str, cfg: ConfigInterfaz | None = None, generador: Callable[..., Any] | None = None) -> EstadoPaquete:
    """Pide el borrador al generador **solo desde caché** (``solo_cache``): la interfaz nunca espera al modelo ni usa la red."""
    cfg = cfg or cargar_interfaz()
    generador = generador or cargar_generador(cfg)
    if generador is None:
        return EstadoPaquete("sin_integrar", motivo=cfg.textos.sin_borrador)
    try:
        paquete = generador(id_grupo, modalidad, solo_cache=cfg.generacion.solo_cache)
    except Exception as exc:  # noqa: BLE001 - un fallo del LLM o de la red nunca debe romper la pantalla
        return EstadoPaquete("sin_cache", motivo=f"{cfg.textos.borrador_no_listo} ({type(exc).__name__})")
    if paquete is None:
        return EstadoPaquete("sin_cache", motivo=cfg.textos.borrador_no_listo)
    return EstadoPaquete("disponible", paquete)


def secciones_de_paquete(paquete: Any) -> list[tuple[str, list[str]]]:
    """Aplana un paquete (mapa o modelo pydantic) en ``(título, párrafos)``: genérico hasta que E1-12 fije su esquema."""
    datos = paquete.model_dump(mode="json") if hasattr(paquete, "model_dump") else dict(paquete)
    salida: list[tuple[str, list[str]]] = []
    for clave, valor in datos.items():
        if isinstance(valor, str):
            parrafos = [valor]
        elif isinstance(valor, (list, tuple)):
            parrafos = [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in valor]
        elif isinstance(valor, Mapping):
            parrafos = [f"{k}: {v}" for k, v in valor.items()]
        else:
            parrafos = [str(valor)]
        if parrafos:
            salida.append((clave.replace("_", " ").capitalize(), parrafos))
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
