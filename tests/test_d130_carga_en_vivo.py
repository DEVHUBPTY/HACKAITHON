"""D-130 · Carga en vivo de la etapa 1 (``src/corrida.py``) y prueba T01 con un archivo propio.

Las pruebas rápidas usan un paquete mínimo armado con los fixtures T01 (sin embeddings). Las que usan el snapshot real corren sobre
``data/senales.duckdb`` y se omiten si ese archivo generado no existe en la máquina. Sin red y sin LLM.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import corrida as co
from src import db, interfaz as ui
from src.configuracion import RAIZ, cargar_corrida
from tests.navegacion_ayuda import ir_a_pantalla

FIXTURES = RAIZ / "tests" / "fixtures"
BASE_REAL = RAIZ / "data" / "senales.duckdb"
CFG = cargar_corrida()
requiere_snapshot = pytest.mark.skipif(not BASE_REAL.exists(), reason="no hay snapshot (data/senales.duckdb)")


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def arbol(carpeta: Path) -> dict[str, str]:
    return {p.relative_to(carpeta).as_posix(): sha(p) for p in sorted(carpeta.rglob("*")) if p.is_file()}


def vivos() -> dict[str, tuple[int, int]]:
    """mtime y tamaño de los archivos vivos que la corrida no puede tocar."""
    rutas = [BASE_REAL, RAIZ / "data" / "revision.duckdb", RAIZ / "outputs" / "reporte_calidad.json", RAIZ / "outputs" / "errores.csv",
             RAIZ / "outputs" / "reporte_vinculos.json", RAIZ / "outputs" / "prioridad.json", RAIZ / "data" / "manifest.json"]
    return {r.name: (r.stat().st_mtime_ns, r.stat().st_size) for r in rutas if r.exists()}


@pytest.fixture
def paquete(tmp_path: Path) -> Path:
    """Raíz mínima: data/processed con los fixtures T01 (noticias con filas inválidas, indicadores con nulos), manifest y un crudo."""
    raiz = tmp_path / "repo"
    procesados = raiz / "data" / "processed"
    procesados.mkdir(parents=True)
    shutil.copy(FIXTURES / "t01_noticias_invalidas.csv", procesados / "noticias.csv")
    shutil.copy(FIXTURES / "t01_indicadores_nulos.csv", procesados / "indicadores.csv")
    crudo = raiz / "data" / "raw" / "demo" / "a.json"
    crudo.parent.mkdir(parents=True)
    crudo.write_text('{"a": 1}\n', encoding="utf-8")
    (procesados / "eventos.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    (procesados / "fuentes.json").write_text("[]\n", encoding="utf-8")
    archivos = ("noticias.csv", "indicadores.csv", "eventos.geojson", "fuentes.json")
    manifest = {
        "version": "0.1", "fecha_corte_UTC": "2025-09-30T12:00:00Z",
        "sha256": {f"processed/{a}": sha(procesados / a) for a in archivos},
        "cantidad_por_archivo": {a: co.contar_registros(procesados / a) for a in archivos},
        "crudos": {"raw/demo/a.json": {"bytes": crudo.stat().st_size, "sha256": sha(crudo)}},
        "transformaciones": ["GDELT: seendate -> fecha_deteccion (nunca fecha_publicacion)."],
    }
    (raiz / "data" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return raiz


def corrida_minima(paquete: Path, tmp_path: Path) -> co.Corrida:
    return co.Corrida(CFG, raiz=paquete, carpeta=tmp_path / "corrida")


def pasos_hasta_almacenamiento(c: co.Corrida) -> list[co.Paso]:
    return [c.ejecutar_paso(k) for k in ("fuentes", "validacion", "normalizacion", "almacenamiento")]


# ------------------------------------------------------------------ la corrida solo escribe en su carpeta


def test_la_corrida_solo_escribe_dentro_de_su_carpeta_y_no_toca_lo_vivo(paquete: Path, tmp_path: Path) -> None:
    antes_paquete, antes_vivos = arbol(paquete), vivos()
    c = corrida_minima(paquete, tmp_path)
    pasos = pasos_hasta_almacenamiento(c)
    assert [p.estado for p in pasos] == [co.ESTADO_OK, co.ESTADO_AVISO, co.ESTADO_OK, co.ESTADO_OK]   # la validación avisa: hay filas rechazadas a propósito
    assert arbol(paquete) == antes_paquete                      # data/raw, data/processed y manifest: byte a byte iguales
    assert vivos() == antes_vivos                               # senales.duckdb, revision.duckdb y outputs/ del repo real, intactos
    nuevos = {p.relative_to(c.carpeta).as_posix() for p in c.carpeta.rglob("*") if p.is_file()}
    assert {"senales.duckdb", "salida/errores.csv", "salida/reporte_calidad.json", "validos/noticias.csv", "validos/indicadores.csv"} <= nuevos
    fuera = {p.name for p in tmp_path.iterdir()}
    assert fuera == {"repo", "corrida"}                         # nada más en el árbol de la prueba


def test_cada_paso_trae_explicacion_cifras_y_tiempo(paquete: Path, tmp_path: Path) -> None:
    c = corrida_minima(paquete, tmp_path)
    for paso in pasos_hasta_almacenamiento(c):
        definicion = c.definicion(paso.clave)
        assert paso.explicacion == definicion.explicacion and paso.titulo == definicion.titulo
        assert paso.explicacion.strip() and paso.cifras and paso.segundos >= 0, paso.clave
    assert {"Reglas aplicadas (config/carga.yaml y config/contrato.yaml)", "Por archivo", "Rechazos por tipo de error"} <= set(c.pasos["validacion"].tablas)


def test_la_validacion_cuenta_los_rechazos_del_reporte_real_y_conserva_los_nulos(paquete: Path, tmp_path: Path) -> None:
    c = corrida_minima(paquete, tmp_path)
    pasos_hasta_almacenamiento(c)
    with (FIXTURES / "t01_noticias_invalidas.csv").open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    rechazadas = sum(1 for r in filas if r["error_esperado"])
    v = c.pasos["validacion"]
    por_tipo = {r["Tipo de error"]: r["Filas con ese error"] for r in v.tablas["Rechazos por tipo de error"]}
    esperado = {t: sum(1 for r in filas if r["error_esperado"] == t) for t in {r["error_esperado"] for r in filas if r["error_esperado"]}}
    assert {t: n for t, n in por_tipo.items() if n} == esperado
    assert por_tipo["columna_faltante"] == 0                    # el vocabulario completo se lista, con sus ceros
    por_archivo = {r["Archivo"]: r for r in v.tablas["Por archivo"]}
    assert por_archivo["noticias.csv"]["Leídas"] == len(filas) and por_archivo["noticias.csv"]["Rechazadas"] == rechazadas
    assert por_archivo["indicadores.csv"]["Rechazadas"] == 0     # el valor nulo de un indicador es válido
    nulos = {(r["Archivo"], r["Campo"]): r for r in v.tablas["Nulos conservados como nulos (nunca se rellenan con cero)"]}
    assert nulos[("indicadores.csv", "valor")]["Nulos en las válidas"] > 0
    con = db.conectar(c.base, solo_lectura=True)
    try:
        assert con.execute("SELECT count(*) FROM indicadores WHERE valor IS NULL").fetchone()[0] == nulos[("indicadores.csv", "valor")]["Nulos en las válidas"]
        assert con.execute("SELECT count(*) FROM indicadores WHERE valor = 0").fetchone()[0] == 0   # nunca se rellena con cero
    finally:
        con.close()


def test_un_hash_que_no_coincide_con_el_manifest_se_marca_con_x(paquete: Path, tmp_path: Path) -> None:
    ruta = paquete / "data" / "manifest.json"
    manifest = json.loads(ruta.read_text(encoding="utf-8"))
    manifest["sha256"]["processed/noticias.csv"] = "0" * 64
    ruta.write_text(json.dumps(manifest), encoding="utf-8")
    paso = corrida_minima(paquete, tmp_path).ejecutar_paso("fuentes")
    coincide = {r["Archivo"]: r["Coincide"] for r in paso.tablas["Archivos del snapshot (data/processed)"]}
    assert coincide["processed/noticias.csv"] == co.MARCA_MAL and {v for k, v in coincide.items() if k != "processed/noticias.csv"} == {co.MARCA_OK}
    assert paso.estado == co.ESTADO_AVISO and paso.cifras["Archivos con el hash del manifest"] == len(coincide) - 1


def test_si_data_processed_cambia_durante_la_corrida_el_almacenamiento_falla(paquete: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = corrida_minima(paquete, tmp_path)
    for k in ("fuentes", "validacion", "normalizacion"):
        c.ejecutar_paso(k)
    guardar = db.guardar_todo

    def guardar_y_ensuciar(ruta, tablas):   # simula que algo escribe en data/processed mientras se guarda
        (paquete / "data" / "processed" / "intruso.csv").write_text("x\n", encoding="utf-8")
        return guardar(ruta, tablas)

    monkeypatch.setattr(db, "guardar_todo", guardar_y_ensuciar)
    paso = c.ejecutar_paso("almacenamiento")
    assert paso.estado == co.ESTADO_FALLA and "cambiaron" in paso.mensajes[0]
    assert c.ejecutar_paso("limpieza").estado == co.ESTADO_OMITIDO    # tras una falla, los pasos siguientes no corren


def test_un_paso_no_corre_sin_los_anteriores(paquete: Path, tmp_path: Path) -> None:
    paso = corrida_minima(paquete, tmp_path).ejecutar_paso("normalizacion")
    assert paso.estado == co.ESTADO_FALLA and "antes hay que ejecutar" in paso.mensajes[0]


def test_la_carpeta_de_corrida_conserva_solo_las_ultimas_y_nunca_borra_otras_carpetas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    raiz = co.raiz_de_corridas(CFG)
    ajena = raiz / "otra_cosa"
    ajena.mkdir(parents=True)
    inicio = datetime(2026, 1, 1, tzinfo=timezone.utc)
    creadas = [co.crear_carpeta_de_corrida(CFG, inicio + timedelta(seconds=i)) for i in range(CFG.corridas.conservar_ultimas + 3)]
    quedan = sorted(p.name for p in raiz.iterdir() if p.name != "otra_cosa")
    assert quedan == sorted(c.name for c in creadas[-CFG.corridas.conservar_ultimas :]) and ajena.exists()
    repetida = co.crear_carpeta_de_corrida(CFG, inicio + timedelta(seconds=len(creadas) - 1))   # el mismo segundo no pisa la anterior
    assert repetida.name.endswith("-2") and repetida.exists()


# ------------------------------------------------------------------ T01 con un archivo propio


def test_el_archivo_t01_de_noticias_reporta_cada_rechazo_con_su_motivo(tmp_path: Path) -> None:
    contenido = co.ejemplo_con_errores("noticias")
    assert contenido is not None
    r = co.validar_archivo_propio(contenido, "noticias", tmp_path)
    with (FIXTURES / "t01_noticias_invalidas.csv").open(encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    assert r.leidas == len(filas) and r.validas + r.rechazadas == r.leidas
    assert r.coinciden_con_lo_esperado == (len(filas), len(filas))     # cada fila coincide con su error_esperado
    rechazadas = {f.posicion: f for f in r.filas if f.estado == "rechazada"}
    assert set(rechazadas) == {i for i, row in enumerate(filas, start=1) if row["error_esperado"]}
    assert rechazadas[7].tipos == "fecha_invalida" and "fecha" in rechazadas[7].motivos and rechazadas[7].valor_rechazado == "2024-13-45T10:00:00Z"
    assert rechazadas[10].tipos == "id_duplicado" and rechazadas[11].tipos == "url_mal_formada"
    assert rechazadas[14].tipos == "obligatorio_vacio" and rechazadas[14].campos["titulo"] is None   # el nulo se muestra como nulo
    assert "id_noticia" in rechazadas[16].motivos and rechazadas[16].id == ""
    assert r.errores_por_tipo == {t: n for t, n in r.errores_por_tipo.items() if n} and sum(r.errores_por_tipo.values()) >= r.rechazadas
    assert "id_duplicado" in r.csv_de_filas and r.csv_de_filas.count("\n") == len(filas) + 1


def test_el_archivo_propio_queda_en_su_carpeta_y_no_toca_lo_vivo(tmp_path: Path) -> None:
    antes = vivos()
    r = co.validar_archivo_propio(co.ejemplo_con_errores("noticias") or b"", "noticias", tmp_path)
    assert vivos() == antes
    assert r.carpeta.parent == tmp_path
    escritos = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert escritos == {"noticias/subido/noticias.csv", "noticias/validos/noticias.csv", "noticias/errores.csv", "noticias/reporte_calidad.json"}
    validos = (tmp_path / "noticias" / "validos" / "noticias.csv").read_text(encoding="utf-8")
    assert "SYN-T01-001" in validos and "SYN-T01-007" not in validos      # solo las filas válidas pasan


def test_los_nulos_de_un_indicador_propio_se_aceptan_y_siguen_siendo_nulos(tmp_path: Path) -> None:
    r = co.validar_archivo_propio(co.ejemplo_con_errores("indicadores") or b"", "indicadores", tmp_path)
    assert r.rechazadas == 0 and r.validas == r.leidas
    assert r.nulos_en_validas["valor"] > 0
    assert all(f.campos["valor"] is None for f in r.filas if f.campos["valor"] in (None, ""))
    escritos = (tmp_path / "indicadores" / "validos" / "indicadores.csv").read_text(encoding="utf-8")
    assert ",0," not in escritos.replace(",0.", "")                          # ningún nulo se volvió 0


def test_una_columna_obligatoria_ausente_es_un_error_de_archivo(tmp_path: Path) -> None:
    r = co.validar_archivo_propio("id_noticia,titulo\nNOT-0123456789,Hola\n".encode(), "noticias", tmp_path)
    assert r.errores_de_archivo and r.errores_de_archivo[0]["tipo_error"] == "columna_faltante"
    assert r.validas == 0 and all(f.estado == "rechazada" for f in r.filas)


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [(b"\xff\xfe\x00 no es utf-8", "UTF-8"), (b"x" * (CFG.archivo_propio.maximo_bytes + 1), "tope")],
)
def test_un_archivo_inutilizable_se_rechaza_con_un_error_claro(tmp_path: Path, contenido: bytes, mensaje: str) -> None:
    with pytest.raises(co.ErrorDeCorrida, match=mensaje):
        co.validar_archivo_propio(contenido, "noticias", tmp_path)
    with pytest.raises(co.ErrorDeCorrida, match="no admitido"):
        co.validar_archivo_propio(b"a\n", "eventos", tmp_path)


# ------------------------------------------------------------------ comparación con la base de la app


def base_mínima(ruta: Path, *, rango: str = "alto", puntaje: float = 0.5, ruido: bool = False, sin_vinculos: bool = False) -> Path:
    con = duckdb.connect(str(ruta))
    con.execute("CREATE TABLE noticias (id_noticia VARCHAR, es_ruido BOOLEAN)")
    con.execute(f"INSERT INTO noticias VALUES ('NOT-1', false), ('NOT-2', {str(ruido).lower()})")
    for t in ("indicadores", "sismos"):
        con.execute(f"CREATE TABLE {t} (x INTEGER)")
    con.execute("CREATE TABLE grupos (id_grupo VARCHAR)")
    con.execute("INSERT INTO grupos VALUES ('GRP-1')")
    if not sin_vinculos:
        con.execute("CREATE TABLE vinculos (id_grupo VARCHAR, tipo VARCHAR, regla VARCHAR, fuente VARCHAR)")
        con.execute("INSERT INTO vinculos VALUES ('GRP-1', 'directa', 'r1', 'indicador')")
    con.execute("CREATE TABLE puntajes (id_grupo VARCHAR, puntaje DOUBLE, rango VARCHAR)")
    con.execute(f"INSERT INTO puntajes VALUES ('GRP-1', {puntaje}, '{rango}')")
    con.close()
    return ruta


def test_dos_bases_iguales_se_reconocen_aunque_el_ruido_flotante_sea_menor_al_redondeo(tmp_path: Path) -> None:
    a = base_mínima(tmp_path / "a.duckdb", puntaje=0.5)
    b = base_mínima(tmp_path / "b.duckdb", puntaje=0.5 + 1e-9)
    c = co.comparar_bases(a, b, CFG)
    assert c.iguales and not c.diferencias
    etiquetas = {f.etiqueta for f in c.filas}
    assert {"Titulares en la base", "Grupos por rango · alto", "Puntaje y rango de cada grupo"} <= etiquetas


def test_las_diferencias_se_listan_una_por_una_con_los_dos_valores(tmp_path: Path) -> None:
    a = base_mínima(tmp_path / "a.duckdb")
    b = base_mínima(tmp_path / "b.duckdb", rango="medio", ruido=True)
    c = co.comparar_bases(a, b, CFG)
    assert not c.iguales
    dif = {f.etiqueta: (f.corrida, f.viva) for f in c.diferencias}
    assert dif["Titulares marcados como ruido"] == (0, 1)
    assert dif["Grupos por rango · alto"] == (1, 0) and dif["Grupos por rango · medio"] == (0, 1)     # un rango ausente cuenta 0
    assert "Puntaje y rango de cada grupo" in dif and "Identificadores de los grupos" not in dif       # lo que coincide no se lista


def test_una_tabla_ausente_en_un_lado_es_una_diferencia_y_no_un_cero(tmp_path: Path) -> None:
    a = base_mínima(tmp_path / "a.duckdb")
    b = base_mínima(tmp_path / "b.duckdb", sin_vinculos=True)
    c = co.comparar_bases(a, b, CFG)
    dif = {f.etiqueta: (f.corrida, f.viva) for f in c.diferencias}
    assert dif["Vínculos con datos oficiales"][0] == 1 and "no disponible" in str(dif["Vínculos con datos oficiales"][1])


# ------------------------------------------------------------------ sobre el snapshot real


@requiere_snapshot
def test_la_corrida_completa_sobre_los_datos_reales_reproduce_la_base_de_la_app(tmp_path: Path) -> None:
    antes = vivos()
    c = co.Corrida(CFG, carpeta=tmp_path / "corrida")
    pasos = c.ejecutar_todo()
    assert [p.estado for p in pasos if p.estado == co.ESTADO_FALLA] == [], [(p.clave, p.mensajes) for p in pasos]
    assert [p.clave for p in pasos] == c.claves() and all(p.explicacion and p.cifras for p in pasos)
    assert vivos() == antes                                    # la base de la app, la revisión y los reportes: ni un byte
    comparacion = c.comparar(BASE_REAL)
    assert comparacion.iguales, [(f.etiqueta, f.corrida, f.viva) for f in comparacion.diferencias]
    assert c.pasos["fuentes"].cifras["Archivos con el hash del manifest"] == c.pasos["fuentes"].cifras["Archivos procesados leídos"]
    assert c.pasos["almacenamiento"].cifras["Archivos de data/raw antes y después"].endswith("idénticos " + co.MARCA_OK)
    assert c.pasos["puntaje"].cifras["Modelo de lenguaje"].startswith("no se usó")


@requiere_snapshot
def test_la_pantalla_carga_en_vivo_explora_la_corrida_y_vuelve_a_la_base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("sys.argv", ["app.py"])
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))      # la corrida se crea en la carpeta de la prueba
    st.cache_resource.clear()
    st.cache_data.clear()
    antes = vivos()
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180).run()
    ir_a_pantalla(at, "calidad")      # D-131: la aplicación abre en «Cómo funciona»; D-133: cada pantalla tiene su URL
    assert not at.exception
    assert "Pendiente" in "\n".join(str(c.value) for c in at.caption)         # antes de pulsar, cada paso dice que está pendiente
    at.button(key="corrida_cargar").click().run()
    assert not at.exception
    assert [s.value for s in at.success] and any("reproduce la base de la app" in str(s.value) for s in at.success)
    assert at.session_state["corrida"]["comparacion"].iguales
    assert {p.clave for p in at.session_state["corrida"]["pasos"]} == {p.clave for p in CFG.pasos}
    at.button(key="corrida_explorar").click().run()
    base = Path(at.session_state["base_explorada"])
    assert not at.exception and base.is_file() and base.parent.parent == tmp_path / CFG.corridas.carpeta
    assert any(CFG.textos.aviso_explorando == str(w.value) for w in at.warning)          # el aviso de que no es la base de la app
    for pantalla in ("organizar", "bandeja", "revision"):                                # las demás pantallas leen la base de la corrida
        ir_a_pantalla(at, pantalla)
        assert not at.exception, pantalla
    at.button(key="volver_a_la_base").click().run()
    assert "base_explorada" not in at.session_state and not at.exception
    assert vivos() == antes


@requiere_snapshot
def test_la_pantalla_valida_un_archivo_propio_sin_tocar_la_base(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui, "ruta_de_revision", lambda demo, cfg=None: tmp_path / "revision.duckdb")
    monkeypatch.setattr("sys.argv", ["app.py"])
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    st.cache_resource.clear()
    st.cache_data.clear()
    antes = vivos()
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120).run()
    ir_a_pantalla(at, "calidad")      # D-131: la aplicación abre en «Cómo funciona»; D-133: cada pantalla tiene su URL
    assert not at.exception and [b for b in at.button if b.key == "t01_validar"][0].disabled   # sin archivo no hay nada que validar
    assert any(d for d in at.get("download_button"))                                          # el ejemplo con errores se puede descargar
    assert vivos() == antes
