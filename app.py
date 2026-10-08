"""Interfaz Streamlit · E1-15 / D-128: las siete etapas del reto (PDF sección 3: Cargar, Organizar, Contextualizar, Priorizar, Explicar,
Producir y Revisar) y, aparte, la Consulta.

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

import contextlib  # noqa: E402
import io  # noqa: E402
import logging  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import corrida as co, db, exportar, interfaz as ui, revision as rv  # noqa: E402
from src.configuracion import CLAVE_INICIO, MODALIDADES, RAIZ, cargar_carga, cargar_corrida, cargar_modalidad, cargar_temas, leer_local_env  # noqa: E402
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
def reporte_de_carga(ruta: str = str(REPORTE_CARGA)) -> dict[str, Any]:
    """El reporte de carga de la app o, al explorar una corrida (D-130), el de esa corrida."""
    return ui.reporte_de_carga(Path(ruta))


# ------------------------------------------------------------------ piezas comunes


def pie(ctx: ui.Contexto, alcance: str | None = None) -> None:
    """Toda salida lleva la marca de borrador y la leyenda de alcance (D-51): la de su propia ficha si la hay, la común si no."""
    st.divider()
    st.caption(f"**{ETIQUETA_BORRADOR}** · Alcance: {alcance or ui.leyenda_de_alcance()}")


def indicador_de_etapas(ctx: ui.Contexto, clave: str) -> None:
    """D-131: la secuencia siempre a la vista: las siete etapas en fila, la actual resaltada (color principal) y cada una con su salto."""
    etapas = ui.etapas_del_reto(ctx.cfg)
    for e, col in zip(etapas, st.columns(len(etapas)), strict=True):
        with col:
            st.button(
                e.titulo, key=f"paso_{e.clave}", on_click=ir_a, args=(e.clave,), width="stretch", type="primary" if e.clave == clave else "secondary",
                help=ctx.cfg.navegacion.ayuda_paso.format(titulo=e.titulo),
            )


def encabezado(ctx: ui.Contexto, clave: str) -> None:
    """D-128: cada pantalla lleva el nombre de su etapa del PDF y lo que el PDF pide en ella.
    D-131: antes va el indicador de etapas y después, la guía (qué hace, cómo leerla y qué caso de uso demuestra)."""
    p = next(x for x in ctx.cfg.pantallas if x.clave == clave)
    if not p.separada:
        indicador_de_etapas(ctx, clave)
    st.header(p.titulo)
    st.caption(p.descripcion)
    nav = ctx.cfg.navegacion
    with st.container(key="guia_etapa"):
        st.markdown(f"**{nav.que_hace}.** {p.guia.que_hace}")
        st.markdown(f"**{nav.como_leer}.** {p.guia.como_leer}")
        st.markdown(f"**{nav.caso_de_uso}.** {p.guia.caso_de_uso}")


def navegacion_inferior(ctx: ui.Contexto, clave: str) -> None:
    """D-131: al pie de cada etapa, ir a la anterior o a la siguiente (la 1 no tiene anterior y la 7 no tiene siguiente). El grupo elegido se conserva."""
    anterior, siguiente = ui.vecinas_de_etapa(ctx.cfg, clave)
    if anterior is None and siguiente is None:
        return
    nav = ctx.cfg.navegacion
    with st.container(key="navegacion_pie"):
        izquierda, derecha = st.columns(2)
        if anterior is not None:
            izquierda.button(nav.anterior.format(titulo=anterior.titulo), key="nav_anterior", on_click=ir_a, args=(anterior.clave,), width="stretch")
        if siguiente is not None:
            derecha.button(nav.siguiente.format(titulo=siguiente.titulo), key="nav_siguiente", on_click=ir_a, args=(siguiente.clave,), type="primary", width="stretch")


def pantalla_inicio(ctx: ui.Contexto) -> None:
    """D-131: «Cómo funciona», la entrada: para qué sirve, quién la usa, las siete etapas con lo que entra y sale de cada una, y tres reglas de la casa."""
    ini = ctx.cfg.inicio
    st.header(ini.titulo)
    st.caption(ini.descripcion)
    st.markdown(ini.proposito)
    st.subheader(ini.titulo_modalidades)
    st.markdown(ini.texto_cita)
    for m in ini.modalidades:
        st.markdown(f"- **{m.nombre}** · {m.quien}: {m.obtiene} {m.alcance}")
    st.subheader(ini.titulo_etapas)
    st.caption(ini.ayuda_etapas)
    etapas = ui.etapas_de_inicio(ctx.con, ctx.cfg, carga_activa(), ctx.revisiones, ctx.demo)
    for e, col in zip(etapas, st.columns(len(etapas)), strict=True):
        with col, st.container(key=f"etapa_{e.clave}"):
            st.metric(e.titulo, ini.sin_dato if e.cuenta is None else f"{e.cuenta:,}".replace(",", " "), help=e.unidad)
            st.caption(e.unidad)
            st.markdown(f"**{ini.etiqueta_entra}:** {e.entra}")
            st.markdown(f"**{ini.etiqueta_sale}:** {e.sale}")
            st.button(ini.boton_abrir.format(titulo=e.titulo), key=f"inicio_{e.clave}", on_click=ir_a, args=(e.clave,), width="stretch")
    st.subheader(ini.titulo_reglas)
    for i, (regla, col) in enumerate(zip(ini.reglas, st.columns(len(ini.reglas)), strict=True)):
        with col, st.container(key=f"regla_{i}"):
            st.markdown(f"**{regla.titulo}**")
            st.markdown(regla.texto)
    st.caption(ini.texto_arquitectura)
    st.button(ini.boton_arquitectura, key="inicio_arquitectura", on_click=ir_a, args=(ctx.cfg.pantallas[0].clave,))
    pie(ctx)


def titulo_de(ctx: ui.Contexto, clave: str) -> str:
    return next(x.titulo for x in ctx.cfg.pantallas if x.clave == clave)


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
                if d.enlace_humano:
                    st.markdown(f"[{ctx.cfg.citas.etiqueta_enlace_humano}]({d.enlace_humano})")
                if d.url:
                    etiqueta = ctx.cfg.citas.etiqueta_url_api if d.id.startswith("IND-") else "URL"
                    st.markdown(f"**{etiqueta}:** {d.url}")
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


def arquitectura(ctx: ui.Contexto, carga: dict[str, Any] | None) -> None:
    """D-128: la arquitectura mínima del PDF (sección 8) con la cuenta real de cada paso y el acceso a la pantalla donde se ve."""
    pasos = ui.pasos_de_arquitectura(ctx.con, ctx.cfg, carga, ctx.revisiones, ctx.demo)
    st.subheader(ctx.cfg.cargar.titulo_arquitectura)
    st.caption(ctx.cfg.cargar.ayuda_arquitectura)
    por_fila = 3
    for inicio in range(0, len(pasos), por_fila):
        columnas = st.columns(por_fila)
        for i, (paso, col) in enumerate(zip(pasos[inicio : inicio + por_fila], columnas, strict=False), start=inicio):
            with col, st.container(border=True):
                st.metric(f"{i + 1} · {paso.etiqueta}", "sin dato" if paso.cuenta is None else f"{paso.cuenta:,}".replace(",", " "), help=paso.unidad)
                st.caption(paso.unidad + (" →" if i + 1 < len(pasos) else ""))
                if paso.ancla:    # D-130: el paso se ve más abajo, en esta misma pantalla
                    st.markdown(f"[Ir a este paso, más abajo ↓](#{paso.ancla})")
                for destino in paso.pantallas:
                    st.button(f"Ver en {titulo_de(ctx, destino)}", key=f"arq_{i}_{destino}", on_click=ir_a, args=(destino,), width="stretch")


# ------------------------------------------------------------------ 1 · Cargar en vivo y prueba T01 (D-130)

COLUMNAS_POR_FILA = 4


def reporte_activo() -> Path:
    """El reporte de carga de la app, o el de la corrida que se está explorando en esta sesión."""
    base = st.session_state.get("base_explorada")
    if base:
        r = Path(base).parent / cargar_corrida().corridas.subcarpeta_salida / cargar_carga().salida.reporte
        if r.exists():
            return r
    return REPORTE_CARGA


def pintar_paso(paso: co.Paso) -> None:
    """Explicación, cifras reales, tablas y mensajes de un paso (los mismos en vivo y al volver a pintar la corrida guardada)."""
    st.caption(paso.explicacion)
    numericas = {k: v for k, v in paso.cifras.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    items = list(numericas.items())
    for inicio in range(0, len(items), COLUMNAS_POR_FILA):
        for (k, v), col in zip(items[inicio : inicio + COLUMNAS_POR_FILA], st.columns(COLUMNAS_POR_FILA), strict=False):
            col.metric(k, f"{v:,}".replace(",", " ") if isinstance(v, int) else v)
    for k, v in paso.cifras.items():
        if k not in numericas:
            st.markdown(f"**{escapar_markdown(k)}:** {escapar_markdown(str(v))}")
    for nombre, filas in paso.tablas.items():
        if filas:
            st.markdown(f"**{nombre}**")
            st.dataframe(pd.DataFrame(filas), hide_index=True)
    for m in paso.mensajes:
        (st.error if paso.estado == co.ESTADO_FALLA else st.warning)(m)


def etiqueta_de_paso(paso: co.Paso) -> str:
    marca = {co.ESTADO_OK: "✓", co.ESTADO_AVISO: "⚠", co.ESTADO_FALLA: "✗", co.ESTADO_OMITIDO: "–"}[paso.estado]
    return f"{marca} {paso.titulo} · {paso.segundos:.1f} s"


def explorar_corrida(ruta: str) -> None:
    st.session_state["base_explorada"] = ruta


def volver_a_la_base() -> None:
    st.session_state.pop("base_explorada", None)


def pintar_comparacion(c: co.Comparacion, cfg: Any) -> None:
    st.subheader("Esta carga vs. la base de la app", anchor="comparacion")
    (st.success if c.iguales else st.warning)(cfg.textos.iguales if c.iguales else cfg.textos.distintas)
    st.dataframe(
        pd.DataFrame([{"Concepto": f.etiqueta, "Esta carga": f.corrida, "Base de la app": f.viva, "Coincide": co.MARCA_OK if f.igual else co.MARCA_MAL} for f in c.filas]),
        hide_index=True,
    )


def carga_en_vivo(ctx: ui.Contexto) -> None:
    """Botón «Cargar el paquete congelado»: corre la etapa 1 y las siguientes sobre una base propia, mostrando cada paso (D-130)."""
    cfg = cargar_corrida()
    st.subheader(cfg.textos.titulo, anchor="cargar")
    st.write(cfg.textos.explicacion)
    st.caption(cfg.textos.sin_red)
    pedido = st.button(cfg.textos.boton, type="primary", key="corrida_cargar")
    barra = st.empty()
    contenedores: dict[str, Any] = {}
    for p in cfg.pasos:
        st.subheader(p.titulo, anchor=p.clave)
        contenedores[p.clave] = st.container()
    zona_final = st.container()
    guardada = st.session_state.get("corrida")
    if pedido:
        corrida = co.Corrida(cfg)
        total = len(cfg.pasos)
        for i, p in enumerate(cfg.pasos):
            barra.progress(i / total, text=f"{p.titulo}…")
            with contenedores[p.clave], st.status(f"{p.titulo}…", expanded=True) as estado:
                paso = corrida.ejecutar_paso(p.clave)
                pintar_paso(paso)
                estado.update(label=etiqueta_de_paso(paso), state="error" if paso.estado == co.ESTADO_FALLA else "complete")
        barra.progress(1.0, text="Listo")
        comparacion = None
        if all(x.estado in {co.ESTADO_OK, co.ESTADO_AVISO} for x in corrida.pasos.values()):
            comparacion = corrida.comparar(db.RUTA_BASE)
        guardada = st.session_state["corrida"] = {
            "carpeta": str(corrida.carpeta), "base": str(corrida.base), "pasos": list(corrida.pasos.values()), "comparacion": comparacion,
        }
        st.session_state.pop("base_explorada", None)
    elif guardada:
        for paso in guardada["pasos"]:
            with contenedores[paso.clave], st.expander(etiqueta_de_paso(paso), expanded=False):
                pintar_paso(paso)
    else:
        for p in cfg.pasos:
            with contenedores[p.clave]:
                st.caption(p.explicacion)
                st.caption(f"Pendiente: pulse «{cfg.textos.boton}».")
    if guardada:
        with zona_final:
            st.caption(f"Carpeta de la corrida (fuera del repositorio): {guardada['carpeta']} · tiempo total {sum(p.segundos for p in guardada['pasos']):.1f} s")
            if guardada["comparacion"] is None:
                st.warning("La corrida no terminó bien: no se compara con la base de la app.")
            else:
                pintar_comparacion(guardada["comparacion"], cfg)
                if Path(guardada["base"]).exists():
                    if st.session_state.get("base_explorada") == guardada["base"]:
                        st.button(cfg.textos.volver, key="corrida_volver", on_click=volver_a_la_base)
                    else:
                        st.button(cfg.textos.explorar, key="corrida_explorar", on_click=explorar_corrida, args=(guardada["base"],))


def archivo_propio() -> None:
    """T01: valida solo la etapa 1 sobre un CSV subido, fila por fila. Nunca alimenta la base de la app (D-130)."""
    cfg = cargar_corrida()
    st.subheader(cfg.textos.titulo_propio, anchor="archivo-propio")
    st.write(cfg.textos.explicacion_propio)
    c1, c2 = st.columns(2)
    for tipo, nombre, col in (("noticias", cfg.archivo_propio.nombre_descarga_noticias, c1), ("indicadores", cfg.archivo_propio.nombre_descarga_indicadores, c2)):
        ejemplo = co.ejemplo_con_errores(tipo, cfg)
        if ejemplo:
            col.download_button(f"Descargar un ejemplo de {tipo} con errores", ejemplo, file_name=nombre, mime="text/csv", key=f"t01_ejemplo_{tipo}")
    noticias = c1.file_uploader("CSV de noticias", type="csv", key="t01_noticias")
    indicadores = c2.file_uploader("CSV de indicadores (opcional)", type="csv", key="t01_indicadores")
    if st.button(cfg.textos.boton_propio, key="t01_validar", disabled=not (noticias or indicadores)):
        carpeta = co.crear_carpeta_de_corrida(cfg, subcarpeta=cfg.corridas.subcarpeta_propio)
        resultados, errores = [], []
        for tipo, archivo in (("noticias", noticias), ("indicadores", indicadores)):
            if archivo is None:
                continue
            try:
                resultados.append(co.validar_archivo_propio(archivo.getvalue(), tipo, carpeta, cfg))
            except co.ErrorDeCorrida as exc:
                errores.append(f"{archivo.name}: {exc}")
        st.session_state["t01_resultados"], st.session_state["t01_errores"] = resultados, errores
    for e in st.session_state.get("t01_errores", []):
        st.error(e)
    resultados = st.session_state.get("t01_resultados")
    if not resultados:
        st.caption(cfg.textos.sin_archivo)
        return
    for r in resultados:
        pintar_resultado_propio(r, cfg)


def pintar_resultado_propio(r: co.ResultadoPropio, cfg: Any) -> None:
    st.markdown(f"**Reporte de calidad de {r.archivo}**")
    a, b, c = st.columns(3)
    a.metric("Leídas", r.leidas)
    b.metric("Aceptadas", r.validas)
    c.metric("Rechazadas", r.rechazadas)
    for e in r.errores_de_archivo:
        st.error(f"{e['campo']}: {e['motivo']}")
    if r.errores_por_tipo:
        st.dataframe(pd.DataFrame({"Tipo de error": list(r.errores_por_tipo), "Filas": list(r.errores_por_tipo.values())}), hide_index=True)
    if r.coinciden_con_lo_esperado:
        k, n = r.coinciden_con_lo_esperado
        st.caption(f"El archivo declara el error esperado de cada fila ({cfg.archivo_propio.columna_esperado}): el resultado coincide en {k} de {n} filas.")
    filas = [
        {"Fila": f.posicion, "ID": f.id, "Veredicto": "✓ aceptada" if f.estado == "aceptada" else "✗ rechazada", "Motivo": f.motivos, "Valor rechazado": f.valor_rechazado,
         **({"Esperado": f.esperado or ""} if r.columna_esperado else {}), **f.campos}
        for f in r.filas[: cfg.archivo_propio.filas_visibles]
    ]
    if len(r.filas) > len(filas):
        st.caption(f"Se listan {len(filas)} de {len(r.filas)} filas; el CSV descargable lleva todas.")
    st.dataframe(pd.DataFrame(filas), hide_index=True)
    if r.nulos_en_validas:
        st.caption("Nulos conservados como nulos en las filas aceptadas (nunca se rellenan con cero): " + " · ".join(f"{k}: {v}" for k, v in r.nulos_en_validas.items()))
    st.download_button("Descargar el veredicto de cada fila (CSV)", r.csv_de_filas, file_name=f"veredicto_{r.tipo}.csv", mime="text/csv", key=f"t01_veredicto_{r.tipo}")


def carga_activa() -> dict[str, Any] | None:
    """El reporte de carga de la base activa, o ``None`` si no se puede leer (la cuenta queda «sin dato», nunca inventada)."""
    try:
        return reporte_de_carga(str(reporte_activo()))
    except Exception:  # noqa: BLE001 - la pantalla debe abrir aunque falten los archivos del snapshot
        return None


def pantalla_calidad(ctx: ui.Contexto) -> None:
    encabezado(ctx, "calidad")
    carga = carga_activa()
    if carga is None:
        st.warning("No se pudo leer el reporte de carga.")
    arquitectura(ctx, carga)
    carga_en_vivo(ctx)
    archivo_propio()
    st.subheader("Calidad de los datos")
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
    st.subheader("Reporte de carga")
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


# ------------------------------------------------------------------ 2 · Organizar (D-128)


def pantalla_organizar(ctx: ui.Contexto) -> None:
    encabezado(ctx, "organizar")
    nombres = {k: t.nombre for k, t in cargar_temas().temas.items()}
    r = ui.resumen_de_organizacion(ctx.con, nombres)
    st.subheader("Titulares útiles por tema")
    columnas = st.columns(len(r.por_tema))
    for (tema, n), col in zip(r.por_tema.items(), columnas, strict=True):
        col.metric(tema, n, help=f"{r.grupos_por_tema[tema]} grupos")
    st.caption(f"{r.utiles} titulares útiles en {r.grupos} grupos; la salida son solo los seis temas del reto.")
    st.subheader("Ruido: se marca, no se borra")
    if r.ruido_por_motivo:
        st.dataframe(
            pd.DataFrame([{"Motivo": ui.nombre_de_motivo_ruido(m, ctx.cfg), "Código": m, "Titulares": n} for m, n in r.ruido_por_motivo.items()]),
            hide_index=True, width="stretch",
        )
    st.caption(f"{r.ruido} titulares marcados como ruido: se conservan y se cuentan, pero no entran en la bandeja.")
    st.subheader("Grupos de noticias sobre el mismo evento")
    st.caption(ctx.cfg.organizar.ayuda_grupos)
    filas = ui.tabla_de_grupos(ctx.con, nombres)
    if not filas:
        st.info(ctx.cfg.textos.sin_base)
        pie(ctx)
        return
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch", column_config={"Titular central": st.column_config.TextColumn(width="large")})
    ids = [f["Grupo"] for f in filas]
    por_id = {f["Grupo"]: f for f in filas}
    largo = ctx.cfg.bandeja.largo_titular_selector
    elegido = st.selectbox(
        "Abrir los titulares y las procedencias de un grupo", ids, key="organizar_grupo",
        format_func=lambda i: f"{i} · {por_id[i]['Titulares']} titulares, {por_id[i]['Procedencias']} procedencias · {por_id[i]['Titular central'][:largo]}",
    )
    d = ui.detalle_de_grupo(ctx.con, elegido, nombres, ctx.cfg_ver, ctx.cfg.organizar.titulares_visibles)
    if d is not None:
        st.markdown(f"**{escapar_markdown(d.titular_central)}** · `{d.id_grupo}` · {d.tema}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Titulares", d.n_titulares)
        c2.metric("Medios", d.n_medios)
        c3.metric("Procedencias independientes", d.n_procedencias)
        st.caption(f"{d.n_titulares} titulares, {d.n_medios} medios, {d.n_procedencias} procedencia{'s' if d.n_procedencias != 1 else ''}. " + ctx.cfg.organizar.ayuda_procedencias)
        st.markdown("**Procedencias**")
        st.dataframe(pd.DataFrame(d.procedencias), hide_index=True, width="stretch")
        st.markdown("**Titulares del grupo**")
        st.dataframe(pd.DataFrame(d.titulares), hide_index=True, width="stretch", column_config={"Titular": st.column_config.TextColumn(width="large")})
        if d.n_titulares > len(d.titulares):
            st.caption(f"Se muestran {len(d.titulares)} de {d.n_titulares} titulares.")
        st.button("Abrir la ficha de este grupo", key="organizar_abrir", on_click=ir_a, args=("ficha", d.id_grupo))
    pie(ctx)


# ------------------------------------------------------------------ 3 · Contextualizar (D-128)


def pantalla_contextualizar(ctx: ui.Contexto) -> None:
    encabezado(ctx, "contextualizar")
    nombres = {k: t.nombre for k, t in cargar_temas().temas.items()}
    vinculos, sin = ui.vinculos_oficiales(ctx.con, nombres, ctx.cfg)
    con_vinculo = {v.id_grupo for v in vinculos}
    por_motivo = ui.grupos_sin_vinculo_por_motivo(sin, con_vinculo)
    c1, c2, c3 = st.columns(3)
    c1.metric("Vínculos con dato oficial", len(vinculos))
    c2.metric("Grupos con vínculo", len(con_vinculo))
    c3.metric("Grupos sin vínculo", sum(len(g) for g in por_motivo.values()))
    st.caption(ctx.cfg.contextualizar.aviso_no_forzar)
    st.subheader("Noticias relacionadas con un dato oficial")
    if vinculos:
        st.dataframe(
            pd.DataFrame([{
                "Grupo": v.id_grupo, "Titular": v.titular, "Fuente": v.fuente, "Dato oficial": v.id_evidencia, "Relación": v.relacion, "Papel": v.papel,
                "Indicador o lugar": v.indicador, "Valor": v.valor, "Período": v.periodo, "Limitaciones": v.limitacion, "Regla que lo sustenta": v.regla,
            } for v in vinculos]),
            hide_index=True, width="stretch",
            column_config={"Titular": st.column_config.TextColumn(width="large"), "Limitaciones": st.column_config.TextColumn(width="large"),
                           "Regla que lo sustenta": st.column_config.TextColumn(width="large")},
        )
        st.caption(ctx.cfg.citas.aviso_anual + " " + ctx.cfg.contextualizar.aviso_usgs)
        st.markdown("**Citas (clic para ver el registro)**")
        for g in dict.fromkeys(v.id_grupo for v in vinculos):
            propios = [v for v in vinculos if v.id_grupo == g]
            with st.expander(f"{g} · {propios[0].titular[:ctx.cfg.bandeja.largo_titular_selector]} ({len(propios)} vínculos)"):
                citas_clicables(ctx, list(dict.fromkeys((v.id_evidencia, v.campo_cita) for v in propios)), "Datos oficiales")
                st.button("Abrir la ficha de este grupo", key=f"contexto_abrir_{g}", on_click=ir_a, args=("ficha", g))
    else:
        st.info("Ningún grupo tiene una relación sustentada con un dato oficial en esta base.")
    st.subheader("Grupos sin vínculo")
    for motivo, grupos in por_motivo.items():
        st.markdown(f"**{ctx.cfg.contextualizar.motivos_sin_vinculo.get(motivo, motivo)}** · {len(grupos)} grupos · `{motivo}`")
        st.dataframe(
            pd.DataFrame([{"Grupo": g.id_grupo, "Titular": g.titular, "Tema": g.tema, "Regla": g.regla} for g in grupos]),
            hide_index=True, width="stretch", column_config={"Titular": st.column_config.TextColumn(width="large")},
        )
    pie(ctx)


# ------------------------------------------------------------------ 4 · Priorizar (la bandeja)


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
    def con_significado(columna: str) -> Any:     # D-131: solo el rango y el estado de evidencia llevan color, y es el de su significado (alto, medio, insuficiente, suficiente)
        def pintar(valor: Any) -> str:
            color = ui.color_semantico(ctx.cfg, columna.lower(), str(valor))
            return f"color: {color}; font-weight: 600" if color else ""
        return pintar

    estilo = tabla.style.map(con_significado("Rango"), subset=["Rango"]).map(con_significado("Evidencia"), subset=["Evidencia"])
    st.dataframe(
        estilo, hide_index=True, width="stretch", height=(len(tabla) + 1) * ctx.cfg.bandeja.alto_filas_px,
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
        pesos = ui.redondear_pesos(pesos, cfg)      # X94: lo que se valida, se muestra y se usa es el valor redondeado
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
    encabezado(ctx, "bandeja")
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


# ------------------------------------------------------------------ 5 · Explicar (la ficha)


def pantalla_ficha(ctx: ui.Contexto) -> None:
    encabezado(ctx, "ficha")
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


# ------------------------------------------------------------------ Consulta (aparte de las siete etapas)


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
    encabezado(ctx, "consulta")
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


# ------------------------------------------------------------------ 6 · Producir (el paquete)


def pantalla_paquete(ctx: ui.Contexto) -> None:
    encabezado(ctx, "paquete")
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
                lector = ui.usuario_de_seccion(ctx.cfg, ctx.modalidad, titulo)      # D-131: a quién sirve esta sección
                if lector:
                    st.caption(ctx.cfg.paquete.etiqueta_usuario.format(usuario=lector))
                for p in parrafos:
                    st.markdown(escapar_markdown(p))
    else:
        (st.info if estado.estado == "sin_integrar" else st.error if estado.estado == "error_integracion" else st.warning)(estado.motivo)
        if estado.estado == "sin_integrar":
            st.caption(ctx.cfg.textos.sin_borrador_ayuda)
    pie(ctx, ficha.alcance)


# ------------------------------------------------------------------ 7 · Revisar (E1-16)


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
    encabezado(ctx, "revision")
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
               + (f" Revisor {cfg_rev.textos.marca_provisional}: una persona rehace la aprobación." if revisor and ui.es_provisional(revisor, ctx.modalidad, cfg_rev) else ""))
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
    rn = ctx.cfg.registro_notion
    st.subheader(rn.subtitulo)
    st.caption(rn.explicacion)
    if st.button(rn.boton_exportar, key="revision_exportar", help=rn.ayuda_exportar):
        _exportar(rev, caso.id_caso)
    if (x := st.session_state.get("revision_exportacion")) and x[0] == caso.id_caso:
        st.success(f"{x[0]}: {'actualizado' if x[4] else 'exportado'} en {x[2]} y {x[3]}.")
        st.download_button("Descargar el Markdown", x[1], file_name=f"{x[0]}.md", key="revision_descarga")
    _sincronizar_api(ctx, rev, caso.id_caso)
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


def _sincronizar_api(ctx: ui.Contexto, rev: Any, id_caso: str) -> None:
    """E3-03: crear o actualizar la ficha en Notion por la API, solo si hay token (y nunca desde la demo, que es sintética)."""
    rn = ctx.cfg.registro_notion
    if ctx.demo:
        return
    if not leer_local_env().get("NOTION_TOKEN", "").strip():
        st.caption(rn.sin_token.format(id_caso=id_caso))
        return
    if not st.button(rn.boton_api, key="revision_notion_api", help=rn.ayuda_api):
        return
    salida, avisos = io.StringIO(), io.StringIO()      # la sincronización informa por stdout al lograrlo y por stderr al degradar o fallar
    try:
        e = exportar.exportar_caso(rev, id_caso)
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(avisos):
            codigo = exportar.sincronizar_con_notion(e)
    except (rv.ErrorDeRevision, LookupError, ValueError, OSError, RuntimeError) as exc:
        st.error(rn.api_fallo.format(id_caso=id_caso, detalle=type(exc).__name__))
        return
    if codigo == 0 and salida.getvalue().strip():
        st.success(rn.api_ok.format(id_caso=id_caso))
    else:
        st.warning(rn.api_fallo.format(id_caso=id_caso, detalle=" ".join(avisos.getvalue().split())[:200] or "sin detalle"))


def _huerfanos(ctx: ui.Contexto) -> None:
    """Casos cuyo grupo ya no está en la base de hoy (el pipeline lo volvió a agrupar): se conservan y se pueden exportar desde su ficha guardada."""
    vivos = {f.id_grupo for f in ctx.filas}
    perdidos = [c for c in ctx.revisiones.casos() if c.modalidad == ctx.modalidad and c.id_grupo not in vivos]
    if not perdidos or not ctx.filas:
        return
    with st.expander(ctx.cfg.revision.titulo_huerfanos, expanded=False):   # D-129: no estorba arriba de la pantalla
        st.warning("Casos cuyo grupo ya no está en la base actual: " + ", ".join(f"{c.id_caso} ({c.id_grupo})" for c in perdidos)
                   + ". Se conservan con su última ficha revisada; no se pueden regenerar ni cambiar sus vínculos.")
        for i, c in enumerate(perdidos):
            if st.button(ctx.cfg.registro_notion.boton_exportar_huerfano.format(id_caso=c.id_caso), key=f"revision_exportar_huerfano_{i}"):
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
        en_cache = ui.borrador_en_cache_de_caso(version, caso.id_grupo, caso.modalidad, ctx.cfg, ruta_base=ctx.ruta_base)
        if en_cache is None:
            st.info("Este caso no tiene borrador y la caché tampoco: regenere el borrador (usa solo la caché) para poder corregirlo.")
            return
        st.markdown(f"**{ETIQUETA_BORRADOR}** · {ctx.cfg.revision.borrador_desde_cache}")
        with st.expander("Borrador desde la caché (solo lectura)", expanded=False):
            for titulo, parrafos in ui.secciones_de_paquete(en_cache, ctx.cfg.paquete.etiquetas):
                st.markdown(f"**{titulo}**")
                for p in parrafos:
                    linea(p)
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
    "inicio": pantalla_inicio, "calidad": pantalla_calidad, "organizar": pantalla_organizar, "contextualizar": pantalla_contextualizar, "bandeja": pantalla_bandeja,
    "ficha": pantalla_ficha, "paquete": pantalla_paquete, "revision": pantalla_revision, "consulta": pantalla_consulta,
}


def elegir_etapa() -> None:
    """Al elegir una etapa en la barra lateral, esa es la pantalla (la consulta tiene su propio botón)."""
    st.session_state["pantalla"] = st.session_state["pantalla_etapa"]


def barra_lateral(cfg: Any, demo: bool) -> str:
    """Modalidad y pantalla (más, en modo demo, los pasos del guion)."""
    with st.sidebar:
        st.title(cfg.titulo_app)
        if demo:
            st.markdown(":gray-badge[Modo demo]")
        modalidad = st.selectbox(
            "Modalidad", list(MODALIDADES), index=MODALIDADES.index(cfg.modalidad_inicial), key="modalidad",
            format_func=lambda m: cargar_modalidad(m).nombre + (" (parcial)" if cargar_modalidad(m).parcial else ""),
        )
        etapas = {p.clave: p.titulo for p in cfg.pantallas if not p.separada}
        st.session_state.setdefault("pantalla", cfg.pantalla_inicial)
        actual = st.session_state["pantalla"]
        st.button(cfg.inicio.titulo, key="pantalla_inicio", on_click=ir_a, args=(CLAVE_INICIO,), type="primary" if actual == CLAVE_INICIO else "secondary", width="stretch")
        st.session_state["pantalla_etapa"] = actual if actual in etapas else None     # en la consulta, ninguna etapa queda marcada
        st.radio("Etapas del reto", list(etapas), format_func=etapas.get, key="pantalla_etapa", index=None, on_change=elegir_etapa)
        st.divider()
        for p in (x for x in cfg.pantallas if x.separada):
            st.button(p.titulo, key=f"pantalla_{p.clave}", on_click=ir_a, args=(p.clave,), type="primary" if actual == p.clave else "secondary", width="stretch", help=p.descripcion)
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
    st.html(f"<style>{ui.css_de_la_interfaz(cfg)}</style>")      # D-131: CSS mínimo y local, sin recursos externos
    demo = ui.modo_demo()
    ruta, aviso = ui.elegir_base(demo, cfg)
    if aviso:
        st.warning(aviso)
    explorada = st.session_state.get("base_explorada")      # D-130: la base de una corrida, solo en esta sesión; nunca reemplaza el archivo vivo
    if explorada and not Path(explorada).exists():
        st.session_state.pop("base_explorada", None)
        explorada = None
    if explorada:
        ruta = Path(explorada)
        st.warning(cargar_corrida().textos.aviso_explorando)
        st.button(cargar_corrida().textos.volver, key="volver_a_la_base", on_click=volver_a_la_base)
    if not ruta.exists():
        st.error(cfg.textos.sin_base)
        st.stop()
    con = abrir_base(str(ruta)).cursor()
    nombres = {k: t.nombre for k, t in cargar_temas().temas.items()}
    previa = st.session_state.get("modalidad", cfg.modalidad_inicial)
    ruta_rev = ruta.parent / cargar_corrida().corridas.base_revision if explorada else ui.ruta_de_revision(demo)    # al explorar una corrida, las revisiones van a su carpeta
    revisiones = rv.Revisiones(ruta_rev, ruta, demo=demo, huellas=rv.huellas_de_exportacion(demo))  # aparte: la base de las pantallas es de solo lectura
    aplicar_atajo(cfg, ui.leer_bandeja(con, previa, nombres), revisiones)      # antes de crear los widgets: así puede fijar la pantalla
    modalidad = barra_lateral(cfg, demo)
    ctx = ui.Contexto(cfg, ui.cargar_verificacion(), con, modalidad, demo, aviso, ui.leer_bandeja(con, modalidad, nombres), ruta, revisiones)
    PANTALLAS[st.session_state["pantalla"]](ctx)
    navegacion_inferior(ctx, st.session_state["pantalla"])


main()
