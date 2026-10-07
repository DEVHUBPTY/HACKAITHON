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
from collections.abc import Sequence  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import db, exportar, interfaz as ui, revision as rv  # noqa: E402
from src.configuracion import MODALIDADES, RAIZ, cargar_modalidad, cargar_temas  # noqa: E402
from src.cache import SinBorrador  # noqa: E402
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


def pie(ctx: ui.Contexto, alcance: str | None = None) -> None:
    """Toda salida lleva la marca de borrador y la leyenda de alcance (D-51): la de su propia ficha si la hay, la común si no."""
    st.divider()
    st.caption(f"**{ETIQUETA_BORRADOR}** · Alcance: {alcance or ui.leyenda_de_alcance()}")


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
        st.info(ctx.cfg.textos.banca_parcial if cargar_modalidad(ctx.modalidad).parcial else ctx.cfg.textos.sin_puntajes.format(modalidad=ctx.modalidad))
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
    c2.metric("Titulares que entran en la bandeja", f"{r['en_bandeja']} (en {r['grupos']} grupos)")
    ic = f"IC 95 %: {ruido.ic95[0]:.1%}–{ruido.ic95[1]:.1%}" if ruido.ic95 else "sin intervalo"
    c3.metric("Ruido marcado", f"{ruido.k} de {ruido.n}", help=ic)
    c4.metric("Duplicados eliminados", r["duplicados_eliminados"])
    st.caption(f"Ruido: {ruido.proporcion:.1%} de {ruido.n} titulares ({ic})." if ruido.proporcion is not None else "Sin titulares.")
    if r["ruido_por_motivo"]:
        st.subheader("Ruido por motivo")
        st.dataframe(pd.DataFrame({"Motivo": list(r["ruido_por_motivo"]), "Titulares": list(r["ruido_por_motivo"].values())}), hide_index=True)
    n_ind, n_con_valor = r["indicadores"]
    st.write(
        f"**Datos oficiales:** {n_ind} filas del Banco Mundial ({n_ind - n_con_valor} sin dato: los nulos son nulos, nunca cero) · "
        f"{r['sismos']} eventos sísmicos de USGS"
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


def tabla_de_bandeja(ctx: ui.Contexto, filas: Sequence[ui.FilaBandeja], modalidad: Any) -> None:
    """Una tabla de la bandeja (la bandeja entera, o el bloque de un sector); con ``Horizonte`` si la modalidad lo calcula."""
    tabla = pd.DataFrame(
        [
            {
                "#": f.posicion, "Tema": f.tema, "Titular representativo": f.titular, "P": round(f.puntaje, ctx.cfg.bandeja.decimales_puntaje), "Rango": f.rango,
                **{k: f.componentes[k] for k in ui.COMPONENTES}, "Evidencia": f.estado_evidencia, "Acción": f.accion,
                **({"Horizonte": ui.etiqueta_de_horizonte(f.horizonte, modalidad)} if f.horizonte else {}),
                "Empate": ui.texto_empate(f.empate_con, ctx.cfg),       # D-105: el empate en P se muestra
                "Origen": ctx.cfg.textos.sintetico if f.sintetico else "",
            }
            for f in filas
        ]
    )
    st.dataframe(
        tabla, hide_index=True, width="stretch", height=(len(tabla) + 1) * ctx.cfg.bandeja.alto_filas_px,
        column_config={k: st.column_config.ProgressColumn(k, help=f"Componente {k} (0 a 1)", min_value=0.0, max_value=1.0, format=f"%.{ctx.cfg.bandeja.decimales_puntaje + 1}f") for k in ui.COMPONENTES}
        | {"P": st.column_config.NumberColumn("P", format=f"%.{ctx.cfg.bandeja.decimales_puntaje}f"), "Titular representativo": st.column_config.TextColumn(width="large")},
    )


def escenario_de_pesos_ui(ctx: ui.Contexto) -> list[ui.FilaBandeja]:
    """E3-04: pesos editables. Un escenario de esta sesión; no escribe en config ni en el registro y nada que se genere o exporte lo usa."""
    cfg = ctx.cfg.pesos_editables
    oficiales = ui.pesos_oficiales()
    with st.expander("Pesos editables: ¿y si los pesos fueran otros? (escenario, no oficial)", expanded=False):
        columnas = st.columns(len(oficiales))
        pesos = {
            k: c.number_input(f"Peso {k}", min_value=0.0, max_value=100.0, value=oficiales[k], step=cfg.paso, key=f"peso_{k}", help=f"Oficial: {ui._numero(oficiales[k])}. Permitido: {ui._numero(cfg.minimo)} a {ui._numero(cfg.maximo)}.")
            for (k, c) in zip(oficiales, columnas, strict=True)
        }
        st.button("Volver a los pesos oficiales", key="pesos_restablecer", on_click=lambda: [st.session_state.pop(f"peso_{k}", None) for k in oficiales])
        st.caption(f"Suma: {ui._numero(sum(pesos.values()))} de {ui._numero(sum(oficiales.values()))}.")
        errores = ui.validar_pesos(pesos, cfg)
        for e in errores:
            st.error(e)
        if errores or ui.es_oficial(pesos):
            if not errores:
                st.caption(cfg.textos.sin_cambios)
            return ctx.filas
        modalidad = cargar_modalidad(ctx.modalidad)
        escenario = ui.escenario_de_pesos(ctx.filas, pesos, modalidad, cfg=cfg)
        comparacion = ui.comparar_con_oficial(ctx.filas, escenario)
        st.markdown(f"**{comparacion.se_mueven} de {len(escenario)} grupos cambian de puesto**, {comparacion.cambian_rango} de rango y {comparacion.cambian_accion} de acción. "
                    f"Top {comparacion.tamano_top}: entran {', '.join(comparacion.entran_al_top) or 'ninguno'}; salen {', '.join(comparacion.salen_del_top) or 'ninguno'}; "
                    f"{'cambia' if comparacion.cambia_el_orden_del_top else 'no cambia'} el orden.")
        if comparacion.empate_en_el_corte:
            e = comparacion.empate_en_el_corte
            st.caption(f"El corte del top {comparacion.tamano_top} parte un empate en P ({e['empatados']} grupos con P {e['valor']}); lo decide la regla del reto (mayor U, luego ID).")
        movimientos = ui.mayores_movimientos(comparacion, cfg.movimientos_mostrados)
        if movimientos:
            st.dataframe(
                pd.DataFrame([{"Tema": m.tema, "Titular": m.titular, "# oficial": m.posicion_oficial, "# escenario": m.posicion_escenario, "Puestos": m.puestos,
                               "P oficial": round(m.p_oficial, ctx.cfg.bandeja.decimales_puntaje), "P escenario": round(m.p_escenario, ctx.cfg.bandeja.decimales_puntaje),
                               "Rango": m.rango_oficial if m.rango_oficial == m.rango_escenario else f"{m.rango_oficial} → {m.rango_escenario}",
                               "Acción": m.accion_oficial if m.accion_oficial == m.accion_escenario else f"{m.accion_oficial} → {m.accion_escenario}"} for m in movimientos]),
                hide_index=True, width="stretch",
            )
        justificacion = st.text_area("Justificación del cambio de pesos", key="pesos_justificacion", help="El reto pide poder justificar los cambios de pesos.")
        try:
            propuesta = ui.propuesta_de_pesos(pesos, justificacion, comparacion, cfg=cfg)
        except ValueError as exc:
            st.caption(str(exc))
        else:
            st.download_button("Descargar la propuesta de pesos (JSON)", ui.propuesta_a_json(propuesta), file_name="propuesta_pesos.json", mime="application/json", key="pesos_descargar")
            st.caption("La descarga es un documento: no cambia la configuración. Adoptar unos pesos como oficiales es una decisión del dueño (nueva versión de reglas).")
    enc = ui.encabezado_bandeja(ctx.con, MANIFEST, ctx.cfg_ver)
    st.warning(cfg.textos.aviso.format(version=enc["version_reglas"]), icon=":material/science:")
    return escenario


def pantalla_bandeja(ctx: ui.Contexto) -> None:
    st.header("Bandeja de temas priorizados")
    enc = ui.encabezado_bandeja(ctx.con, MANIFEST, ctx.cfg_ver)
    st.markdown(f"**Reglas v{enc['version_reglas']}** · **Corte del snapshot:** {enc['fecha_corte']} · Modalidad: {cargar_modalidad(ctx.modalidad).nombre}")
    st.caption("P ordena la atención; no es una probabilidad de verdad ni de pérdida. " + ctx.cfg.textos.alerta)
    if not ctx.filas:
        st.info(ctx.cfg.textos.banca_parcial if cargar_modalidad(ctx.modalidad).parcial else ctx.cfg.textos.sin_puntajes.format(modalidad=ctx.modalidad))
        pie(ctx)
        return
    if not ui.comprobar_orden(ctx.filas):
        st.warning("El orden guardado no coincide con la regla de desempate: vuelva a ejecutar `python -m src.puntaje`.")
    filas = escenario_de_pesos_ui(ctx)      # E3-04: el escenario de pesos (en la sesión) o, sin él, la bandeja oficial
    total = len(filas)
    todas = st.checkbox(f"Mostrar las {total} filas", value=False, key="bandeja_todas")
    modalidad = cargar_modalidad(ctx.modalidad)
    bloques = ui.agrupar_por_sector(filas, modalidad)      # E2-01: solo si la modalidad declara sectores (YAML); si no, bandeja plana
    if bloques is None:
        visibles = filas if todas else filas[: ctx.cfg.bandeja.filas_iniciales]
        tabla_de_bandeja(ctx, visibles, modalidad)
    else:
        # X40: primero se agrupa y después se limita por sector, para que ningún sector (p. ej. logística, CU-05) quede oculto
        if not todas:
            bloques = ui.limitar_por_sector(bloques, ctx.cfg.bandeja.filas_iniciales_por_sector)
        for bloque in bloques:
            st.subheader(bloque.etiqueta)
            tabla_de_bandeja(ctx, bloque.filas, modalidad)
            st.caption(f"{len(bloque.filas)} de {bloque.total or len(bloque.filas)} grupos de este sector.")
        visibles = [f for b in bloques for f in b.filas]
    st.caption(f"Se muestran {len(visibles)} de {total} grupos.")
    ids = [f.id_grupo for f in filas]
    por_id = {f.id_grupo: f for f in filas}
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
    pie(ctx, ficha.alcance)


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
    estado = ui.obtener_paquete(id_grupo, ctx.modalidad, ctx.cfg, ruta_base=ctx.ruta_base)
    if estado.estado == "disponible":
        st.markdown(f"**{ETIQUETA_BORRADOR}**")
        for titulo, parrafos in ui.secciones_de_paquete(estado.paquete, ctx.cfg.paquete.etiquetas):
            with st.expander(titulo, expanded=True):
                for p in parrafos:
                    st.markdown(escapar_markdown(p))
    else:
        (st.info if estado.estado == "sin_integrar" else st.error if estado.estado == "error_integracion" else st.warning)(estado.motivo)
        if estado.estado == "sin_integrar":
            st.caption(ctx.cfg.textos.sin_borrador_ayuda)
    pie(ctx, ficha.alcance)


# ------------------------------------------------------------------ 6 · Revisión (E1-16)


def avisar(clave: str = "revision_aviso") -> None:
    """Un aviso de la acción anterior (la pantalla se vuelve a ejecutar tras cada acción)."""
    if (a := st.session_state.pop(clave, None)) is not None:
        (st.success if a[0] == "ok" else st.warning)(a[1])


def actuar(texto_ok: str, accion: Any, *args: Any, **kwargs: Any) -> None:
    """Ejecuta una acción de revisión: éxito -> aviso y se vuelve a pintar; una regla que la rechaza se muestra tal cual, sin escribir nada."""
    try:
        accion(*args, **kwargs)
    except rv.AdvertenciasSinConfirmar as exc:
        st.session_state["revision_aviso"] = ("aviso", f"Falta confirmar: {'; '.join(a.id for a in exc.advertencias)}")
    except (rv.ErrorDeRevision, SinBorrador) as exc:
        st.session_state["revision_aviso"] = ("aviso", str(exc))
    else:
        st.session_state["revision_aviso"] = ("ok", texto_ok)
        st.session_state.pop("revision_advertencias", None)
    st.rerun()


@st.cache_data(show_spinner=False)
def ficha_del_caso(ruta_base: str, ruta_rev: str, id_caso: str, rechazados: tuple[str, ...]) -> Ficha:
    """La ficha del caso sin los vínculos rechazados (la clave incluye los rechazados: un rechazo nuevo invalida la ficha)."""
    rev = rv.Revisiones(ruta_rev, ruta_base)
    return rev.ficha_del_caso(rev.caso(id_caso))


def etiqueta(accion: str) -> str:
    return ui.cargar_revision().acciones[accion].etiqueta


def pantalla_revision(ctx: ui.Contexto) -> None:
    st.header("Revisión humana")
    id_grupo = selector_de_grupo(ctx, "revision_grupo")
    if id_grupo is None:
        pie(ctx)
        return
    rev, cfg_rev = ctx.revisiones, ui.cargar_revision()
    _huerfanos(ctx)
    caso = rev.caso_de_grupo(id_grupo, ctx.modalidad)
    actual = ui.estado_de_revision(ctx.con, id_grupo, ctx.cfg, rev, ctx.modalidad)
    avisar()
    marca = f" · **{cfg_rev.textos.marca_provisional}**" if caso and rev.vigente_provisional(caso.id_caso) else ""  # D-112
    st.markdown(f"**Estado actual:** {actual}{marca}" + (f" · **Caso:** {caso.id_caso}" if caso else ""))
    st.dataframe(
        pd.DataFrame({"Estados del reto": ctx.cfg.revision.estados, "Actual": ["●" if e == actual else "" for e in ctx.cfg.revision.estados]}),
        hide_index=True,
    )
    revisores = ui.revisores_de(ctx.modalidad, cfg_rev)
    revisor = st.selectbox("Quién revisa", revisores, index=None, placeholder="Elija a la persona que revisa", key="revision_revisor")
    st.caption(cfg_rev.limitacion_revisor + (f" Rol: {ui.rol_de(revisor, ctx.modalidad, cfg_rev)}." if revisor else "")
               + (f" Revisor {cfg_rev.textos.marca_provisional}: una persona rehace la aprobación en C-09." if revisor and ui.es_provisional(revisor, ctx.modalidad, cfg_rev) else ""))
    if caso is None:
        ficha = ficha_de(str(ctx.ruta_base), id_grupo, ctx.modalidad)
        _que_comprobar(ctx, ficha)
        st.info(ctx.cfg.textos.sin_revision)
        if st.button(etiqueta("abrir"), key="revision_abrir", disabled=revisor is None, type="primary"):
            paquete = ui.obtener_paquete(id_grupo, ctx.modalidad, ctx.cfg, ruta_base=ctx.ruta_base)  # el borrador de la caché, si hay (sin LLM ni red)
            actuar("Caso abierto: la revisión queda registrada.", rev.abrir, id_grupo, ctx.modalidad, revisor, paquete=paquete.paquete if paquete.estado == "disponible" else None)
        st.caption(ctx.cfg.textos.aprobar_aviso)
        pie(ctx, ficha.alcance)
        return
    rechazados = tuple(sorted(rev.vinculos_rechazados(caso.id_caso)))
    try:
        ficha = ficha_del_caso(str(ctx.ruta_base), str(rev.ruta), caso.id_caso, rechazados)
    except rv.ErrorDeRevision as exc:  # el grupo ya no está en la base de hoy: se muestra la última ficha revisada, sin inventar nada
        st.warning(str(exc))
        ficha = rev.ficha_revisada(caso.id_caso)
        if ficha is None:
            pie(ctx)
            return
    _que_comprobar(ctx, ficha)
    disponibles = ui.acciones_disponibles(actual, cfg_rev)
    version = rev.version_actual(caso.id_caso)
    _borrador(ctx, caso, version)
    st.subheader("Acciones")
    comentario = st.text_area("Comentario (opcional)", key="revision_comentario")
    sin_revisor = revisor is None
    a1, a2 = st.columns(2)
    with a1:
        if st.button(etiqueta("aceptar"), key="revision_aceptar", disabled=sin_revisor or not disponibles["aceptar"], type="primary"):
            actuar("Aprobado como borrador (sigue marcado BORRADOR).", rev.aceptar, caso.id_caso, revisor, comentario)
        st.caption(ctx.cfg.textos.aprobar_aviso)
        vacios = [v.codigo for v in (*ficha.falta_comprobar.principales, *ficha.falta_comprobar.otros)]
        elegidos = st.multiselect("Vacíos que motivan pedir evidencia (al menos uno)", vacios, key="revision_vacios")
        motivo_evidencia = st.text_input("Motivo (obligatorio si la ficha no tiene vacíos que enlazar)", key="revision_motivo_evidencia")
        if st.button(etiqueta("pedir_evidencia"), key="revision_pedir", disabled=sin_revisor or not (elegidos or motivo_evidencia.strip()) or not disponibles["pedir_evidencia"]):
            actuar("Pasa a «requiere evidencia».", rev.pedir_evidencia, caso.id_caso, revisor, elegidos, comentario, motivo=motivo_evidencia)
    with a2:
        motivo = st.selectbox("Motivo del descarte (obligatorio)", cfg_rev.motivos_descarte, index=None, placeholder="Elija un motivo", key="revision_motivo_descarte")
        if st.button(etiqueta("descartar"), key="revision_descartar", disabled=sin_revisor or not disponibles["descartar"]):
            actuar("Caso descartado.", rev.descartar, caso.id_caso, revisor, motivo, comentario)
        motivo_reabrir = st.text_input("Motivo para reabrir (obligatorio)", key="revision_motivo_reabrir")
        if st.button(etiqueta("reabrir"), key="revision_reabrir", disabled=sin_revisor or not disponibles["reabrir"]):
            actuar("Caso reabierto: vuelve a «en revisión».", rev.reabrir, caso.id_caso, revisor, motivo_reabrir, comentario)
    _vinculos(ctx, caso, ficha, rechazados, revisor, disponibles)
    _correccion(ctx, caso, version, revisor, comentario, disponibles)
    if st.button(etiqueta("regenerar"), key="revision_regenerar", disabled=sin_revisor or not disponibles["regenerar"],
                 help="Nunca sobrescribe una versión: crea otra. Usa solo la caché del borrador (sin LLM ni red)."):
        actuar("Borrador regenerado como una versión nueva.", rev.regenerar, caso.id_caso, revisor, comentario=comentario)
    st.subheader("Historial de revisión")
    st.caption(cfg_rev.textos.limitacion_historial)
    st.dataframe(pd.DataFrame(ui.tabla_historial(rev.historial(caso.id_caso), ctx.cfg_ver, caso.modalidad, cfg_rev)), hide_index=True)
    st.subheader("Exportar")
    if st.button("Exportar a Notion", key="revision_exportar", help="Genera el Markdown y la fila CSV de «Casos y evidencias» desde la ficha revisada; si el caso ya se exportó, actualiza esa fila del CSV local (en Notion hay que reemplazarla: docs/notion.md)."):
        _exportar(rev, caso.id_caso)
    if (x := st.session_state.get("revision_exportacion")) and x[0] == caso.id_caso:
        st.success(f"{x[0]}: {'actualizado' if x[4] else 'exportado'} en {x[2]} y {x[3]}.")
        st.download_button("Descargar el Markdown", x[1], file_name=f"{x[0]}.md", key="revision_descarga")
    pie(ctx, ficha.alcance)


def _exportar(rev: Any, id_caso: str) -> None:
    """Exporta un caso desde su ficha revisada; un fallo se dice con claridad, nunca como traceback."""
    try:
        e = exportar.exportar_caso(rev, id_caso)
    except (rv.ErrorDeRevision, LookupError, ValueError, OSError) as exc:
        st.session_state.pop("revision_exportacion", None)
        st.error(f"No se pudo exportar {id_caso}: {exc}")
        return
    st.session_state["revision_exportacion"] = (e.id_caso, e.markdown, str(e.ruta_markdown), str(e.ruta_csv), e.actualizada)


def _huerfanos(ctx: ui.Contexto) -> None:
    """Casos cuyo grupo ya no está en la base de hoy (el pipeline lo volvió a agrupar): se conservan y se pueden exportar desde su ficha guardada."""
    vivos = {f.id_grupo for f in ctx.filas}
    perdidos = [c for c in ctx.revisiones.casos() if c.modalidad == ctx.modalidad and c.id_grupo not in vivos]
    if not perdidos or not ctx.filas:
        return
    st.warning("Casos cuyo grupo ya no está en la base actual: " + ", ".join(f"{c.id_caso} ({c.id_grupo})" for c in perdidos)
               + ". Se conservan con su última ficha revisada; no se pueden regenerar ni cambiar sus vínculos.")
    for i, c in enumerate(perdidos):
        if st.button(f"Exportar {c.id_caso} a Notion", key=f"revision_exportar_huerfano_{i}"):
            _exportar(ctx.revisiones, c.id_caso)
            if (x := st.session_state.get("revision_exportacion")) and x[0] == c.id_caso:
                st.success(f"{x[0]}: {'actualizado' if x[4] else 'exportado'} en {x[2]} y {x[3]}.")


def _que_comprobar(ctx: ui.Contexto, ficha: Ficha) -> None:
    st.subheader("Qué debe comprobar la persona")
    st.markdown(f"**Acción recomendada:** {escapar_markdown(ficha.accion_recomendada.accion)}")
    for x in ficha.falta_comprobar.principales:
        linea(f"{x.texto} → Verificar: {x.verificacion}")
    if not ficha.falta_comprobar.principales:
        st.write("Las reglas no detectan vacíos; la revisión humana sigue siendo obligatoria.")


def _borrador(ctx: ui.Contexto, caso: Any, version: Any) -> None:
    st.subheader("Borrador")
    versiones = ctx.revisiones.versiones(caso.id_caso)
    if version is None:
        st.info("Este caso no tiene borrador: regenere el borrador (usa solo la caché) para poder corregirlo.")
        return
    st.markdown(f"**{ETIQUETA_BORRADOR}** · versión {version.version} ({version.origen})")
    with st.expander(f"Borrador vigente · versión {version.version}", expanded=False):
        for titulo, parrafos in ui.secciones_de_paquete(version.contenido, ctx.cfg.paquete.etiquetas):
            st.markdown(f"**{titulo}**")
            for p in parrafos:
                linea(p)
    if len(versiones) > 1:
        st.dataframe(pd.DataFrame(ui.tabla_versiones(versiones, ctx.cfg_ver)), hide_index=True)


def _vinculos(ctx: ui.Contexto, caso: Any, ficha: Ficha, rechazados: tuple[str, ...], revisor: str | None, disponibles: dict[str, bool]) -> None:
    activos = ui.vinculos_oficiales_de(ficha)
    if not activos and not rechazados:
        return
    st.subheader("Vínculos oficiales")
    st.caption("Si un dato oficial está mal aplicado, se rechaza: queda registrado y no entra en el borrador que se regenere.")
    motivo = st.text_input("Motivo (obligatorio) para rechazar o restaurar", key="revision_motivo_vinculo")
    for i, id_evidencia in enumerate(activos):
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"`{id_evidencia}`")
        if c2.button(etiqueta("rechazar_vinculo"), key=f"revision_rechazar_{i}", disabled=revisor is None or not disponibles["rechazar_vinculo"]):
            actuar(f"Vínculo {id_evidencia} rechazado.", ctx.revisiones.rechazar_vinculo, caso.id_caso, revisor, id_evidencia, motivo)
    for i, id_evidencia in enumerate(rechazados):
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"~~`{id_evidencia}`~~ rechazado")
        if c2.button(etiqueta("restaurar_vinculo"), key=f"revision_restaurar_{i}", disabled=revisor is None or not disponibles["restaurar_vinculo"]):
            actuar(f"Vínculo {id_evidencia} restaurado.", ctx.revisiones.restaurar_vinculo, caso.id_caso, revisor, id_evidencia, motivo)


def _correccion(ctx: ui.Contexto, caso: Any, version: Any, revisor: str | None, comentario: str, disponibles: dict[str, bool]) -> None:
    if version is None:
        return
    st.subheader("Corregir el borrador")
    st.caption("Se corrige el texto de una afirmación o de una oración. El texto corregido se revalida: las advertencias se muestran y la persona debe confirmarlas.")
    editables = rv.elementos_editables(version.contenido)
    clave = st.selectbox("Qué texto corregir", list(editables), key="revision_elemento", format_func=lambda k: ui.etiqueta_de_elemento(k, editables[k].texto, 70, ctx.cfg.paquete.etiquetas))
    if clave is None:
        return
    texto = st.text_area("Texto corregido", value=editables[clave].texto, key=f"revision_texto_{version.version}_{clave}")
    if st.button("Revisar corrección", key="revision_revisar_correccion", disabled=not disponibles["corregir"]):
        try:
            st.session_state["revision_advertencias"] = (clave, texto, [a.id for a in ctx.revisiones.revisar_correccion(caso.id_caso, {clave: texto})])
        except rv.ErrorDeRevision as exc:
            st.session_state.pop("revision_advertencias", None)
            st.warning(str(exc))
    estado = st.session_state.get("revision_advertencias")
    confirmadas: list[str] = []
    if estado and estado[0] == clave and estado[1] == texto:
        if estado[2]:
            st.warning("El validador encontró advertencias. Para guardar la corrección, confirme cada una.")
        else:
            st.success("Sin advertencias del validador.")
        for i, aviso in enumerate(estado[2]):
            if st.checkbox(f"Confirmo: {aviso}", key=f"revision_confirmar_{i}"):
                confirmadas.append(aviso)
    if st.button(etiqueta("corregir"), key="revision_guardar_correccion", disabled=revisor is None or not disponibles["corregir"]):
        actuar("Corrección guardada como una versión nueva (la anterior se conserva).", ctx.revisiones.corregir, caso.id_caso, revisor, {clave: texto}, confirmadas=confirmadas, comentario=comentario)


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


def aplicar_atajo(cfg: Any, filas: list[ui.FilaBandeja], revisiones: Any) -> None:
    """``?caso=`` (un ``GRP-…``, una posición o un ``CASO-…``) abre la ficha una sola vez por valor: después manda la persona."""
    valor = st.query_params.get(cfg.demo.parametro_caso)
    if valor and st.session_state.get("caso_aplicado") != valor:
        st.session_state["caso_aplicado"] = valor
        grupo = ui.resolver_caso(valor, filas, {c.id_caso: c.id_grupo for c in revisiones.casos()})
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
    revisiones = rv.Revisiones(ui.ruta_de_revision(demo), ruta, demo=demo, huellas=rv.huellas_de_exportacion(demo))  # aparte: la base de las pantallas es de solo lectura
    aplicar_atajo(cfg, ui.leer_bandeja(con, previa, nombres), revisiones)      # antes de crear los widgets: así puede fijar la pantalla
    modalidad = barra_lateral(cfg, demo)
    ctx = ui.Contexto(cfg, ui.cargar_verificacion(), con, modalidad, demo, aviso, ui.leer_bandeja(con, modalidad, nombres), ruta, revisiones)
    PANTALLAS[st.session_state["pantalla"]](ctx)


main()
