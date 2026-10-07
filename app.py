"""Interfaz Streamlit · E1-15: las seis pantallas (Calidad, Bandeja, Ficha, Consulta, Paquete y Revisión).

Capa de presentación delgada: toda la lógica (ranking, vista de la ficha, citas, hora de Panamá, enganche con la generación)
vive en ``src/interfaz.py`` y se prueba sin Streamlit. Esta capa solo pinta.

Uso:
    poetry run streamlit run app.py              # snapshot (data/senales.duckdb)
    poetry run streamlit run app.py -- --demo    # base de demo (data/demo.duckdb, la crea C-06) y pasos del guion
    http://localhost:8501/?caso=GRP-…            # atajo: abre la ficha del grupo (o de la posición N de la bandeja)

Todo lo que se ve es BORRADOR para una decisión humana. No existe ninguna acción de publicar: el estado máximo es
«aprobado como borrador» (E1-16). Funciona sin red: los embeddings y la caché son locales y la generación solo lee caché.
"""

from __future__ import annotations

import os

# Antes de importar nada que cargue modelos: sin red, nunca (la demo corre con el Wi-Fi apagado).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import logging  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import db, interfaz as ui  # noqa: E402
from src.configuracion import MODALIDADES, RAIZ, cargar_modalidad, cargar_temas  # noqa: E402
from src.consulta import RespuestaConsulta, crear_consultor  # noqa: E402
from src.esquemas import ETIQUETA_BORRADOR, Ficha  # noqa: E402
from src.ficha import Linea, construir_ficha, escapar_markdown, vista  # noqa: E402

logger = logging.getLogger("app")
MANIFEST = RAIZ / "data" / "manifest.json"
REPORTE_CARGA = RAIZ / "outputs" / "reporte_calidad.json"


# ------------------------------------------------------------------ recursos cacheados (locales, sin red)


@st.cache_resource(show_spinner=False)
def abrir_base(ruta: str) -> Any:
    """Una conexión de solo lectura por base; cada ejecución usa su propio cursor."""
    return db.conectar(ruta, solo_lectura=True)


@st.cache_resource(show_spinner="Cargando el índice de consulta (modelo local)…")
def abrir_consultor(ruta: str) -> Any:
    return crear_consultor(RAIZ / ruta if not os.path.isabs(ruta) else ruta)


@st.cache_data(show_spinner=False)
def ficha_de(ruta: str, id_grupo: str, modalidad: str) -> Ficha:
    return construir_ficha(id_grupo, modalidad, abrir_base(ruta).cursor())


@st.cache_data(show_spinner=False)
def reporte_de_carga() -> dict[str, Any]:
    return ui.reporte_de_carga(REPORTE_CARGA)


# ------------------------------------------------------------------ piezas comunes


def pie(ctx: ui.Contexto) -> None:
    """Toda salida lleva la marca de borrador y la leyenda de alcance (D-51)."""
    st.divider()
    st.caption(f"**{ETIQUETA_BORRADOR}** · Alcance: {ui.leyenda_de_alcance()}")


def insignia_sintetico(ctx: ui.Contexto) -> None:
    st.markdown(f":orange-badge[{ctx.cfg.textos.sintetico}]", help=ctx.cfg.textos.sintetico_ayuda)


def linea(texto: str, nivel: int = 0) -> None:
    """Un texto de los datos se pinta escapado: se ve igual, pero no se interpreta como Markdown ni HTML."""
    st.markdown("    " * nivel + "- " + escapar_markdown(texto))


def lineas(ls: tuple[Linea, ...] | list[Linea]) -> None:
    for x in ls:
        linea(x.texto, x.nivel)


def citas_clicables(ctx: ui.Contexto, citas: list[tuple[str, str]], titulo: str = "Citas (clic para ver el registro)") -> None:
    """Cada cita ``ID · campo`` abre un recuadro con el valor, la fecha en hora de Panamá y la URL."""
    if not citas:
        return
    st.caption(titulo)
    columnas = st.columns(min(len(citas), ctx.cfg.ficha.citas_por_fila))
    for i, (id_registro, campo) in enumerate(citas):
        with columnas[i % len(columnas)], st.popover(f"{id_registro} · {campo}", width="stretch"):
            d = ui.detalle_cita(ctx.con, id_registro, campo, ctx.cfg, ctx.cfg_ver)
            st.markdown(f"**ID:** `{d.id}`  \n**Campo:** `{d.campo}`")
            if d.encontrada:
                st.markdown(f"**Valor:** {escapar_markdown(d.valor)}")
                for etiqueta, dato in d.filas:
                    st.markdown(f"**{etiqueta}:** {escapar_markdown(dato)}")
                if d.url:
                    st.markdown(f"**URL:** {d.url}")
                if d.sintetico:
                    insignia_sintetico(ctx)
            else:
                st.markdown(d.nota or "Registro no encontrado.")


def selector_de_grupo(ctx: ui.Contexto, clave: str) -> str | None:
    """Selector de grupo compartido por Ficha, Paquete y Revisión (el grupo elegido sobrevive al cambio de pantalla)."""
    if not ctx.filas:
        st.info(ctx.cfg.textos.banca_parcial if cargar_modalidad(ctx.modalidad).parcial else ctx.cfg.textos.sin_puntajes)
        return None
    ids = [f.id_grupo for f in ctx.filas]
    if st.session_state.get("id_grupo") not in ids:
        st.session_state["id_grupo"] = ids[0]
    por_id = {f.id_grupo: f for f in ctx.filas}

    def etiqueta(i: str) -> str:
        f = por_id[i]
        return f"#{f.posicion} · {f.titular[:ctx.cfg.bandeja.largo_titular_selector]}"

    # El valor del widget parte del grupo compartido; al elegir otro, on_change (que corre ANTES de volver a ejecutar el script)
    # actualiza el grupo compartido, así que lo de arriba ya no pisa la elección.
    st.session_state[clave] = st.session_state["id_grupo"]
    return st.selectbox("Grupo", ids, key=clave, format_func=etiqueta, on_change=sincronizar_grupo, args=(clave,))


def sincronizar_grupo(clave: str) -> None:
    st.session_state["id_grupo"] = st.session_state[clave]


def ir_a(pantalla: str, id_grupo: str | None = None) -> None:
    st.session_state["pantalla"] = pantalla
    if id_grupo:
        st.session_state["id_grupo"] = id_grupo


# ------------------------------------------------------------------ 1 · Calidad


def pantalla_calidad(ctx: ui.Contexto) -> None:
    st.header("Calidad de los datos")
    st.caption("Lo que no sirve se marca, no se borra: el ruido se conserva y se cuenta, pero no entra en la bandeja.")
    r = ui.resumen_de_calidad(ctx.con)
    ruido: ui.Proporcion = r["ruido"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Titulares en la base", r["titulares"])
    c2.metric("Entran en la bandeja", r["en_bandeja"])
    ic = f"IC 95 %: {ruido.ic95[0]:.1%}–{ruido.ic95[1]:.1%}" if ruido.ic95 else "sin intervalo"
    c3.metric("Ruido marcado", f"{ruido.k} de {ruido.n}", help=ic)
    c4.metric("Grupos", r["grupos"])
    st.caption(f"Ruido: {ruido.proporcion:.1%} de {ruido.n} titulares ({ic})." if ruido.proporcion is not None else "Sin titulares.")
    if r["ruido_por_motivo"]:
        st.subheader("Ruido por motivo")
        st.dataframe(pd.DataFrame({"Motivo": list(r["ruido_por_motivo"]), "Titulares": list(r["ruido_por_motivo"].values())}), hide_index=True)
    n_ind, n_con_valor = r["indicadores"]
    st.write(
        f"**Datos oficiales:** {n_ind} filas del Banco Mundial ({n_ind - n_con_valor} sin dato: los nulos son nulos, nunca cero) · "
        f"{r['sismos']} eventos sísmicos de USGS · duplicados eliminados: {r['duplicados_eliminados']}"
    )
    if r["sinteticos"]:
        insignia_sintetico(ctx)
        st.caption(f"{r['sinteticos']} registros de la base son de prueba.")
    st.subheader("Reporte de carga (E1-02)")
    try:
        carga = reporte_de_carga()
    except Exception as exc:  # noqa: BLE001 - la pantalla debe abrir aunque falten los archivos del snapshot
        st.warning(f"No se pudo leer el reporte de carga ({type(exc).__name__}).")
        carga = None
    if carga:
        archivos = carga["archivos"]
        st.dataframe(
            pd.DataFrame(
                [{"Archivo": a, "Leídas": v["leidas"], "Válidas": v["validas"], "Rechazadas": v["rechazadas"]} for a, v in archivos.items()]
            ),
            hide_index=True,
        )
        medios = carga.get("distribucion_noticias_validas", {}).get("por_medio", {})
        if medios:
            top = dict(list(medios.items())[: ctx.cfg.calidad.top_medios])
            st.write("**Medios con más titulares válidos:** " + " · ".join(f"{escapar_markdown(m)} ({n})" for m, n in top.items()))
    pie(ctx)


# ------------------------------------------------------------------ 2 · Bandeja


def pantalla_bandeja(ctx: ui.Contexto) -> None:
    st.header("Bandeja de temas priorizados")
    enc = ui.encabezado_bandeja(ctx.con, MANIFEST, ctx.cfg_ver)
    st.markdown(f"**Reglas v{enc['version_reglas']}** · **Corte del snapshot:** {enc['fecha_corte']} · Modalidad: {cargar_modalidad(ctx.modalidad).nombre}")
    st.caption("P ordena la atención; no es una probabilidad de verdad ni de pérdida. " + ctx.cfg.textos.alerta)
    if not ctx.filas:
        st.info(ctx.cfg.textos.banca_parcial if cargar_modalidad(ctx.modalidad).parcial else ctx.cfg.textos.sin_puntajes)
        pie(ctx)
        return
    if not ui.comprobar_orden(ctx.filas):
        st.warning("El orden guardado no coincide con la regla de desempate: vuelva a ejecutar `python -m src.puntaje`.")
    total = len(ctx.filas)
    todas = st.checkbox(f"Mostrar las {total} filas", value=False, key="bandeja_todas")
    visibles = ctx.filas if todas else ctx.filas[: ctx.cfg.bandeja.filas_iniciales]
    tabla = pd.DataFrame(
        [
            {
                "#": f.posicion, "Tema": f.tema, "Titular representativo": f.titular, "P": round(f.puntaje, ctx.cfg.bandeja.decimales_puntaje), "Rango": f.rango,
                **{k: f.componentes[k] for k in ui.COMPONENTES}, "Evidencia": f.estado_evidencia, "Acción": f.accion,
                "Origen": ctx.cfg.textos.sintetico if f.sintetico else "",
            }
            for f in visibles
        ]
    )
    st.dataframe(
        tabla, hide_index=True, width="stretch", height=(len(tabla) + 1) * ctx.cfg.bandeja.alto_filas_px,
        column_config={k: st.column_config.ProgressColumn(k, help=f"Componente {k} (0 a 1)", min_value=0.0, max_value=1.0, format=f"%.{ctx.cfg.bandeja.decimales_puntaje + 1}f") for k in ui.COMPONENTES}
        | {"P": st.column_config.NumberColumn("P", format=f"%.{ctx.cfg.bandeja.decimales_puntaje}f"), "Titular representativo": st.column_config.TextColumn(width="large")},
    )
    st.caption(f"Se muestran {len(visibles)} de {total} grupos.")
    ids = [f.id_grupo for f in ctx.filas]
    por_id = {f.id_grupo: f for f in ctx.filas}
    elegido = st.selectbox("Abrir la ficha de", ids, key="bandeja_grupo", format_func=lambda i: f"#{por_id[i].posicion} · {por_id[i].titular[:ctx.cfg.bandeja.largo_titular_selector]}")
    st.button("Abrir ficha", on_click=ir_a, args=("ficha", elegido), key="bandeja_abrir")
    pie(ctx)


# ------------------------------------------------------------------ 3 · Ficha


def pantalla_ficha(ctx: ui.Contexto) -> None:
    st.header("Ficha de evidencia")
    id_grupo = selector_de_grupo(ctx, "ficha_grupo")
    if id_grupo is None:
        pie(ctx)
        return
    try:
        ficha = ficha_de(str(ctx.ruta_base), id_grupo, ctx.modalidad)
    except (LookupError, RuntimeError, ValueError) as exc:
        st.error(f"No se pudo armar la ficha: {exc}")
        pie(ctx)
        return
    v = vista(ficha, ctx.cfg_ver)
    plan = ui.plan_de_ficha(v, ctx.cfg)
    st.markdown(f"**{v.marca}** · `{v.id_grupo}`")
    if any(f.sintetico for f in ctx.filas if f.id_grupo == id_grupo):
        insignia_sintetico(ctx)
    for s in plan.resumen:                                   # resumen: qué se reporta, estado y acción
        st.subheader(s.titulo)
        lineas(s.lineas)
    with st.expander("Desglose del puntaje (R · I · U · N · E)"):
        lineas(plan.desglose)
        st.caption("Ordena la atención; no es una probabilidad de verdad ni de pérdida.")
    for s in plan.detalle:                                   # detalle desplegable: quién lo reporta, respaldado, todos los vacíos
        with st.expander(s.titulo):
            lineas(s.lineas)
            if s.clave == "respaldado":
                citas_clicables(ctx, [(c.id, c.campo) for c in ui.citas_de_ficha(ficha)])
    st.caption(ctx.cfg.textos.alerta)
    pie(ctx)


# ------------------------------------------------------------------ 4 · Consulta


def lanzar_ejemplo(texto: str) -> None:
    st.session_state["consulta_texto"] = texto
    st.session_state["consulta_lanzar"] = True


def pintar_respuesta(ctx: ui.Contexto, r: RespuestaConsulta) -> None:
    abstiene = r.abstiene
    (st.warning if abstiene else st.success)(("Abstención. " if abstiene else "Respuesta. ") + r.mensaje)
    for a in r.afirmaciones:
        st.markdown(f"**{a.id} · {a.tipo}** — {escapar_markdown(a.texto)}")
        citas_clicables(ctx, [(c.id, c.campo) for c in a.citas], "Citas")
    if r.falta:
        st.markdown(f"**Haría falta:** {escapar_markdown(r.falta)}")
    if r.ultimo_dato_disponible:
        st.markdown("**Último dato disponible**")
        for a in r.ultimo_dato_disponible:
            st.markdown(f"- {escapar_markdown(a.texto)}")
            citas_clicables(ctx, [(c.id, c.campo) for c in a.citas], "Citas")
    for av in r.advertencias:
        st.info(av)
    sinteticos = ui.ids_sinteticos(ctx.con, [e.id for e in r.evidencia])
    if sinteticos:
        insignia_sintetico(ctx)
    if r.similitud_maxima is not None:
        st.caption(f"Método: {r.metodo} · similitud máxima: {r.similitud_maxima:.3f}")
    st.caption(f"**{ETIQUETA_BORRADOR}** · Alcance: {r.leyenda_alcance}")


def pantalla_consulta(ctx: ui.Contexto) -> None:
    st.header("Consulta en español")
    st.caption("Si no hay evidencia suficiente, el sistema se abstiene y dice qué haría falta. No hay modelo generativo en esta pantalla.")
    st.session_state.setdefault("consulta_texto", "")
    st.text_input("Pregunta", key="consulta_texto", max_chars=ctx.cfg.consulta.largo_maximo_caracteres)
    metodos = ["semantica", "bm25"]
    metodo = st.selectbox("Método", metodos, index=metodos.index(ctx.cfg.consulta.metodo_inicial), key="consulta_metodo")
    lanzar = st.button("Consultar", type="primary", key="consulta_boton")
    st.caption("Ejemplos")
    for i, ejemplo in enumerate(ctx.cfg.consulta.ejemplos):
        st.button(ejemplo, on_click=lanzar_ejemplo, args=(ejemplo,), key=f"consulta_ejemplo_{i}")
    pedido = lanzar or st.session_state.pop("consulta_lanzar", False)
    texto = st.session_state.get("consulta_texto", "").strip()
    if pedido and texto:
        try:
            respuesta = abrir_consultor(str(ctx.ruta_base)).responder(texto, metodo)
        except Exception as exc:  # noqa: BLE001 - sin el modelo local no hay consulta, pero la app sigue viva
            st.error(f"No se pudo consultar ({type(exc).__name__}: {exc}). Revise que el modelo de embeddings esté en `models/`.")
            pie(ctx)
            return
        pintar_respuesta(ctx, respuesta)
    else:
        pie(ctx)


# ------------------------------------------------------------------ 5 · Paquete


def pantalla_paquete(ctx: ui.Contexto) -> None:
    st.header("Paquete · borrador")
    id_grupo = selector_de_grupo(ctx, "paquete_grupo")
    if id_grupo is None:
        pie(ctx)
        return
    ficha = ficha_de(str(ctx.ruta_base), id_grupo, ctx.modalidad)
    a = ficha.accion_recomendada
    st.markdown(f"**Acción recomendada:** {escapar_markdown(a.accion)} · prioridad {a.rango} · evidencia {a.estado_evidencia}")
    # TODO(E1-12): al integrar src/generacion.py, fijar el nombre de la función en config/interfaz.yaml:generacion.funcion.
    estado = ui.obtener_paquete(id_grupo, ctx.modalidad, ctx.cfg)
    if estado.estado == "disponible":
        st.markdown(f"**{ETIQUETA_BORRADOR}**")
        for titulo, parrafos in ui.secciones_de_paquete(estado.paquete):
            with st.expander(titulo, expanded=True):
                for p in parrafos:
                    st.markdown(escapar_markdown(p))
    else:
        (st.info if estado.estado == "sin_integrar" else st.warning)(estado.motivo)
        if estado.estado == "sin_integrar":
            st.caption(ctx.cfg.textos.sin_borrador_ayuda)
    pie(ctx)


# ------------------------------------------------------------------ 6 · Revisión


def pantalla_revision(ctx: ui.Contexto) -> None:
    st.header("Revisión humana")
    id_grupo = selector_de_grupo(ctx, "revision_grupo")
    if id_grupo is None:
        pie(ctx)
        return
    actual = ui.estado_de_revision(ctx.con, id_grupo, ctx.cfg)
    st.markdown(f"**Estado actual:** {actual}")
    st.dataframe(
        pd.DataFrame({"Estados del reto": ctx.cfg.revision.estados, "Actual": ["●" if e == actual else "" for e in ctx.cfg.revision.estados]}),
        hide_index=True,
    )
    ficha = ficha_de(str(ctx.ruta_base), id_grupo, ctx.modalidad)
    st.subheader("Qué debe comprobar la persona")
    st.markdown(f"**Acción recomendada:** {escapar_markdown(ficha.accion_recomendada.accion)}")
    for x in ficha.falta_comprobar.principales:
        linea(f"{x.texto} → Verificar: {x.verificacion}")
    if not ficha.falta_comprobar.principales:
        st.write("Las reglas no detectan vacíos; la revisión humana sigue siendo obligatoria.")
    st.info(ctx.cfg.textos.sin_revision)
    st.caption(ctx.cfg.textos.aprobar_aviso)
    pie(ctx)


# ------------------------------------------------------------------ armado


PANTALLAS = {
    "calidad": pantalla_calidad, "bandeja": pantalla_bandeja, "ficha": pantalla_ficha,
    "consulta": pantalla_consulta, "paquete": pantalla_paquete, "revision": pantalla_revision,
}


def barra_lateral(cfg: Any, demo: bool) -> str:
    """Modalidad y pantalla (más, en modo demo, los pasos del guion)."""
    with st.sidebar:
        st.title(cfg.titulo_app)
        if demo:
            st.markdown(":red-badge[MODO DEMO]")
        modalidad = st.selectbox(
            "Modalidad", list(MODALIDADES), index=MODALIDADES.index(cfg.modalidad_inicial), key="modalidad",
            format_func=lambda m: cargar_modalidad(m).nombre + (" (parcial)" if cargar_modalidad(m).parcial else ""),
        )
        titulos = {p.clave: p.titulo for p in cfg.pantallas}
        st.session_state.setdefault("pantalla", cfg.pantalla_inicial)
        st.radio("Pantalla", list(titulos), format_func=titulos.get, key="pantalla")
        if demo:
            st.subheader("Guion de la demo")
            for p in ui.leer_guion(cfg):
                st.markdown(f"**{escapar_markdown(p.tiempo)}** · {escapar_markdown(p.pantalla)}  \n{escapar_markdown(p.accion)}")
    return modalidad


def aplicar_atajo(cfg: Any, filas: list[ui.FilaBandeja]) -> None:
    """``?caso=`` abre la ficha una sola vez por valor: después manda la persona."""
    valor = st.query_params.get(cfg.demo.parametro_caso)
    if valor and st.session_state.get("caso_aplicado") != valor:
        st.session_state["caso_aplicado"] = valor
        grupo = ui.resolver_caso(valor, filas)
        if grupo:
            st.session_state["id_grupo"] = grupo
            st.session_state["pantalla"] = "ficha"


def main() -> None:
    cfg = ui.cargar_interfaz()
    st.set_page_config(page_title=cfg.titulo_app, layout="wide")
    demo = ui.modo_demo()
    ruta, aviso = ui.elegir_base(demo, cfg)
    if aviso:
        st.warning(aviso)
    if not ruta.exists():
        st.error(cfg.textos.sin_base)
        st.stop()
    con = abrir_base(str(ruta)).cursor()
    nombres = {k: t.nombre for k, t in cargar_temas().temas.items()}
    previa = st.session_state.get("modalidad", cfg.modalidad_inicial)
    aplicar_atajo(cfg, ui.leer_bandeja(con, previa, nombres))      # antes de crear los widgets: así puede fijar la pantalla
    modalidad = barra_lateral(cfg, demo)
    ctx = ui.Contexto(cfg, ui.cargar_verificacion(), con, modalidad, demo, aviso, ui.leer_bandeja(con, modalidad, nombres), ruta)
    PANTALLAS[st.session_state["pantalla"]](ctx)


main()
