"""Normalización (E1-03): IDs estables, nulos, duplicados, procedencia sin datos personales e inmutabilidad."""

import csv
import hashlib
import json
import random
from pathlib import Path

import pytest

from src import carga, db, normalizacion
from src.configuracion import cargar_carga, cargar_contrato, cargar_fuentes, cargar_normalizacion

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
PROCESADOS = RAIZ / "data" / "processed"
CONFIG = cargar_normalizacion()
FUENTES = cargar_fuentes()
NOMBRES = cargar_carga().archivos


def _noticia(**campos: str) -> dict[str, str]:
    base = {
        "id_noticia": "",
        "titulo": "Titular",
        "url": "https://www.Ejemplo.com/a/b/?utm_source=x&id=1#frag",
        "medio": "Ejemplo",
        "idioma": "es",
        "fecha_publicacion": "",
        "fecha_deteccion": "2026-10-01T10:00:00Z",
        "fecha_extraccion": "2026-10-06T10:00:00Z",
        "tema": "economia",
        "origen": "GDELT",
        "alcance_texto": "basado únicamente en titular/metadatos",
    }
    return base | campos


def _normalizar(filas: list[dict], fuentes: list[dict] | None = None) -> tuple[list[dict], normalizacion.Registro]:
    registro = normalizacion.Registro()
    return normalizacion.normalizar_noticias(filas, fuentes or [], CONFIG, FUENTES, registro), registro


# ------------------------------------------------------------------ URL canónica e IDs


def test_url_canonica_sin_utm_barra_final_ni_mayusculas_en_el_dominio() -> None:
    esperada = "https://ejemplo.com/a/b?id=1"
    assert normalizacion.url_canonica("https://www.Ejemplo.com/a/b/?utm_source=x&id=1#frag", FUENTES) == esperada
    assert normalizacion.url_canonica("http://EJEMPLO.com/a/b?id=1&utm_campaign=y", FUENTES) == esperada


def test_id_noticia_es_sha1_de_diez_caracteres_de_la_url_canonica() -> None:
    canonica = "https://ejemplo.com/a/b?id=1"
    esperado = "NOT-" + hashlib.sha1(canonica.encode()).hexdigest()[:10]
    (fila,), _ = _normalizar([_noticia()])
    assert fila["id_noticia"] == esperado


def test_ids_de_indicador_y_sismo() -> None:
    assert normalizacion.id_indicador("PAN", "FP.CPI.TOTL.ZG", 2023, CONFIG) == "IND-PAN-FP.CPI.TOTL.ZG-2023"
    assert normalizacion.id_sismo("us6000m2a6", CONFIG) == "SIS-us6000m2a6"
    assert normalizacion.id_sismo("SIS-us6000m2a6", CONFIG) == "SIS-us6000m2a6"


@pytest.mark.skipif(not (PROCESADOS / NOMBRES.noticias).exists(), reason="snapshot no disponible")
def test_los_ids_recalculados_coinciden_con_los_del_snapshot() -> None:
    filas = normalizacion.leer_csv(PROCESADOS / NOMBRES.noticias)
    resultado, registro = _normalizar(filas)
    assert {f["id_noticia"] for f in resultado} == {f["id_noticia"] for f in filas}
    assert registro.duplicados == []


# ------------------------------------------------------------------ orden de carga


def _escribir_csv(ruta: Path, filas: list[dict]) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(filas)


def _copia_barajada(origen: Path, destino: Path, semilla: int) -> None:
    """Copia ``origen``  con filas, features y fuentes en otro orden."""
    destino.mkdir()
    azar = random.Random(semilla)
    for nombre in (NOMBRES.noticias, NOMBRES.indicadores):
        filas = normalizacion.leer_csv(origen / nombre)
        filas = [{k: "" if v is None else v for k, v in f.items()} for f in filas]
        azar.shuffle(filas)
        _escribir_csv(destino / nombre, filas)
    geo = json.loads((origen / NOMBRES.eventos).read_text(encoding="utf-8"))
    azar.shuffle(geo["features"])
    (destino / NOMBRES.eventos).write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    fuentes = json.loads((origen / NOMBRES.fuentes).read_text(encoding="utf-8"))
    azar.shuffle(fuentes)
    (destino / NOMBRES.fuentes).write_text(json.dumps(fuentes, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(scope="module")
def validos(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``validos/`` generado en una carpeta temporal (D-82): los tests no escriben en el repo."""
    base = tmp_path_factory.mktemp("carga")
    carga.main(["--validos", str(base / "validos"), "--salida", str(base / "outputs")])
    return base / "validos"


def test_cargar_el_mismo_snapshot_en_otro_orden_produce_los_mismos_ids(validos: Path, tmp_path: Path) -> None:
    normal = normalizacion.normalizar_carpeta(validos, CONFIG)
    for semilla in (1, 2):
        carpeta = tmp_path / f"orden{semilla}"
        _copia_barajada(validos, carpeta, semilla)
        barajado = normalizacion.normalizar_carpeta(carpeta, CONFIG)
        for tabla, clave in (("noticias", "id_noticia"), ("indicadores", "id_indicador"), ("sismos", "id")):
            assert [f[clave] for f in barajado[tabla]] == [f[clave] for f in normal[tabla]]
        assert barajado == normal  # y el resto del contenido también


def test_el_orden_no_cambia_que_duplicado_se_conserva() -> None:
    a = _noticia(url="https://ejemplo.com/x", titulo="A", origen="GDELT", tema="economia")
    b = _noticia(url="http://www.ejemplo.com/x/?utm_medium=z", titulo="B", origen="TVN RSS", tema="turismo",
                 fecha_publicacion="2026-09-30T10:00:00Z")  # fmt: skip
    directo, _ = _normalizar([a, b])
    inverso, _ = _normalizar([b, a])
    assert directo == inverso
    assert len(directo) == 1


# ------------------------------------------------------------------ duplicados


def test_duplicados_por_url_se_fusionan_y_se_registran_con_motivo() -> None:
    a = _noticia(url="https://ejemplo.com/x", origen="GDELT", tema="economia", fecha_deteccion="2026-10-01T10:00:00Z")
    b = _noticia(url="http://WWW.ejemplo.com/x/?utm_source=q", origen="TVN RSS", tema="turismo",
                 fecha_publicacion="2026-09-30T10:00:00Z", fecha_deteccion="")  # fmt: skip
    (fila,), registro = _normalizar([a, b])
    assert fila["origen"] == "TVN RSS · GDELT"
    assert fila["tema"] == "economia|turismo"
    assert fila["fecha_publicacion"] == "2026-09-30T10:00:00Z"
    assert fila["fecha_deteccion"] == "2026-10-01T10:00:00Z"
    (duplicado,) = registro.duplicados
    assert duplicado["motivo"] == normalizacion.MOTIVO_DUPLICADO_URL
    assert duplicado["tabla"] == "noticias"
    assert duplicado["clave"] == "https://ejemplo.com/x"


def test_indicadores_duplicados_se_registran() -> None:
    fila = {"pais_iso3": "PAN", "indicador_id": "X.Y", "anio": "2020", "valor": "1.5", "unidad": "%",
            "fuente_url": "https://x.example/", "fecha_extraccion": "2026-10-06T10:00:00Z", "licencia": "CC"}  # fmt: skip
    registro = normalizacion.Registro()
    resultado = normalizacion.normalizar_indicadores([fila, dict(fila)], CONFIG, registro)
    assert len(resultado) == 1
    assert registro.duplicados[0]["motivo"] == normalizacion.MOTIVO_DUPLICADO_CLAVE


# ------------------------------------------------------------------ nulos


def test_cadena_vacia_es_nulo_en_csv_y_en_json(tmp_path: Path) -> None:
    """Brecha de la revisión de E1-02: en JSON una cadena vacía opcional tampoco cuenta como valor."""
    registro = normalizacion.Registro()
    fuentes = normalizacion.normalizar_fuentes(
        [{"dominio": "WWW.Prueba.com", "nombre_legible": "Prueba", "pais": "", "origen": "GDELT", "condiciones": "  "}],
        registro,
    )
    assert fuentes[0]["dominio"] == "prueba.com"
    assert fuentes[0]["pais"] is None and fuentes[0]["condiciones"] is None
    sismos = normalizacion.normalizar_sismos(
        [{"id": "x1", "magnitude": 4.1, "time": "2024-01-01T00:00:00Z", "updated": "", "place": "", "depth": None}],
        CONFIG, registro,
    )  # fmt: skip
    assert sismos[0]["updated"] is None and sismos[0]["place"] is None and sismos[0]["depth"] is None
    ruta = tmp_path / "n.csv"
    _escribir_csv(ruta, [_noticia(idioma="", tema="")])
    (csv_fila,) = normalizacion.leer_csv(ruta)
    assert csv_fila["idioma"] is None and csv_fila["tema"] is None


def test_conteo_de_nulos_en_indicadores_identico_antes_y_despues(tmp_path: Path) -> None:
    entrada = FIXTURES / "t01_indicadores_nulos.csv"
    with entrada.open(encoding="utf-8", newline="") as f:
        antes = sum(1 for fila in csv.DictReader(f) if not fila["valor"].strip())
    assert antes > 0
    filas = normalizacion.leer_csv(entrada)
    resultado = normalizacion.normalizar_indicadores(filas, CONFIG, normalizacion.Registro())
    ruta = tmp_path / "n.duckdb"
    db.guardar_todo(ruta, {"indicadores": resultado})
    con = db.conectar(ruta, solo_lectura=True)
    assert db.contar_nulos(con, "indicadores", "valor") == antes
    assert con.execute("SELECT count(*) FROM indicadores WHERE valor = 0").fetchone()[0] == 0
    assert db.contar_filas(con, "indicadores") == len(filas)
    con.close()


def test_un_cero_real_se_conserva_y_un_texto_no_numerico_queda_nulo_no_cero() -> None:
    base = {"pais_iso3": "PAN", "indicador_id": "X.Y", "unidad": "%", "fuente_url": "https://x.example/",
            "fecha_extraccion": "2026-10-06T10:00:00Z", "licencia": "CC"}  # fmt: skip
    registro = normalizacion.Registro()
    cero, malo = normalizacion.normalizar_indicadores(
        [base | {"anio": "2020", "valor": "0"}, base | {"anio": "2021", "valor": "n/d"}], CONFIG, registro
    )
    assert cero["valor"] == 0.0
    assert malo["valor"] is None
    assert registro.cambios[0]["motivo"] == normalizacion.MOTIVO_NUMERO_NO_NORMALIZABLE


# ------------------------------------------------------------------ procedencia (D-32) y medio


@pytest.mark.parametrize(
    ("texto", "agencia", "tipo"),
    [
        (None, None, "sin firma"),
        ("", None, "sin firma"),
        ("EFE", "EFE", "agencia"),
        ("Por Juan Pérez / Reuters", "Reuters", "agencia"),
        ("europa press", "Europa Press", "agencia"),
        ("Redacción", None, "medio"),
        ("Juan Pérez", None, "persona"),
        ("Apertura", None, "persona"),  # "AP" no debe detectarse dentro de otra palabra
    ],
)
def test_derivar_firma(texto: str | None, agencia: str | None, tipo: str) -> None:
    assert normalizacion.derivar_firma(texto, "TVN Panamá", CONFIG) == (agencia, tipo)


def test_el_nombre_de_la_persona_no_se_guarda_en_ninguna_tabla(tmp_path: Path) -> None:
    fila = _noticia(firma="Juan Pérez Secreto")
    (resultado,), _ = _normalizar([fila])
    assert resultado["tipo_firma"] == "persona" and resultado["agencia"] is None
    assert "Secreto" not in json.dumps(resultado, ensure_ascii=False)
    ruta = tmp_path / "p.duckdb"
    db.guardar_todo(ruta, {"noticias": [resultado]})
    assert "Secreto".encode() not in ruta.read_bytes()


def test_nombre_legible_del_medio_desde_fuentes() -> None:
    fuentes = [{"dominio": "prensa.com", "nombre_legible": "La Prensa", "pais": "Panamá", "origen": "GDELT", "condiciones": "x"}]
    (fila,), _ = _normalizar([_noticia(url="https://www.prensa.com/politica/a/", medio="prensa.com")], fuentes)
    assert fila["medio"] == "La Prensa"
    assert fila["dominio"] == "prensa.com"
    assert fila["pais_medio"] == "Panamá"


# ------------------------------------------------------------------ inmutabilidad y tablas


def _sha256(carpeta: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(carpeta.iterdir()) if p.is_file()}


def test_no_modifica_processed_ni_validos_y_crea_las_tablas(validos: Path, tmp_path: Path) -> None:
    antes_processed, antes_validos = _sha256(PROCESADOS), _sha256(validos)
    destino = tmp_path / "senales.duckdb"
    conteos = normalizacion.ejecutar(validos, destino, CONFIG)
    assert _sha256(PROCESADOS) == antes_processed
    assert _sha256(validos) == antes_validos
    con = db.conectar(destino, solo_lectura=True)
    tablas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {"noticias", "indicadores", "sismos"} <= tablas
    for tabla in ("noticias", "indicadores", "sismos"):
        assert db.contar_filas(con, tabla) == conteos[tabla] > 0
    con.close()


def test_main_sin_validos_falla_con_mensaje(tmp_path: Path) -> None:
    assert normalizacion.main(["--entrada", str(tmp_path / "no_existe"), "--salida", str(tmp_path / "x.duckdb")]) == 1


def test_guardar_todo_es_atomico_y_no_deja_temporales(tmp_path: Path) -> None:
    ruta = tmp_path / "a.duckdb"
    db.guardar_todo(ruta, {"fuentes": [{"dominio": "a.com", "nombre_legible": "A"}]})
    with pytest.raises(Exception):
        db.guardar_todo(ruta, {"fuentes": [{"dominio": "b.com", "nombre_legible": None}]})  # NOT NULL
    assert not (tmp_path / "a.duckdb.tmp").exists()
    con = db.conectar(ruta, solo_lectura=True)
    assert [f["dominio"] for f in db.leer_tabla(con, "fuentes")] == ["a.com"]  # la base anterior sigue intacta
    con.close()



# ------------------------------------------------------------------ diccionario


def _campos_del_diccionario() -> dict[str, dict[str, tuple[str, str, str]]]:
    """Tabla -> campo -> (tipo, nullable, clase), leído de la sección de ``senales.duckdb`` de data/diccionario.md."""
    texto = (RAIZ / "data" / "diccionario.md").read_text(encoding="utf-8")
    seccion = texto[texto.index("## `senales.duckdb`") :]
    resultado: dict[str, dict[str, tuple[str, str, str]]] = {}
    tabla = ""
    for linea in seccion.splitlines():
        if linea.startswith("### `"):
            tabla = linea.split("`")[1]
            resultado[tabla] = {}
        elif tabla and linea.startswith("| `"):
            celdas = [c.strip() for c in linea.strip("|").split("|")]
            resultado[tabla][celdas[0].strip("`")] = (celdas[1], celdas[2], celdas[4])
    return resultado


def test_el_diccionario_documenta_cada_campo_de_cada_tabla() -> None:
    diccionario = _campos_del_diccionario()
    assert set(diccionario) == set(db.ESQUEMA)
    for tabla, cols in db.ESQUEMA.items():
        assert set(diccionario[tabla]) == {c for c, _ in cols}, tabla
        for columna, definicion in cols:
            tipo, nullable, clase = diccionario[tabla][columna]
            assert definicion.split()[0] == tipo, (tabla, columna)
            assert nullable == ("no" if ("NOT NULL" in definicion or "PRIMARY KEY" in definicion) else "sí"), (tabla, columna)
            assert clase in {"mínimo", "opcional", "derivado"}, (tabla, columna)


def test_los_campos_minimos_del_diccionario_son_los_del_contrato() -> None:
    contrato = cargar_contrato()
    diccionario = _campos_del_diccionario()
    for tabla, campos in (("noticias", contrato.noticias), ("indicadores", contrato.indicadores), ("sismos", contrato.eventos)):
        minimos = {c for c, (_, _, clase) in diccionario[tabla].items() if clase == "mínimo"}
        assert minimos == set(campos), tabla


# ------------------------------------------------------------------ revisión del PR #7


@pytest.mark.parametrize(
    ("texto", "agencia", "tipo"),
    [
        ("Redacción TVN", None, "medio"),
        ("REDACCIÓN La Prensa", None, "medio"),
        ("redaccion web", None, "medio"),
        ("TVN Noticias", None, "medio"),
        ("La Prensa Panamá", None, "medio"),
        ("Agencias", None, "agencia"),
        ("Associated Press", "AP", "agencia"),
        ("agence france-presse", "AFP", "agencia"),
        ("Agence France Presse", "AFP", "agencia"),
        ("Agencia EFE", "EFE", "agencia"),
        ("Thomson Reuters", "Reuters", "agencia"),
        ("Xinhua", "Xinhua", "agencia"),
        ("Redacción EFE", "EFE", "agencia"),
        ("Webster Pérez", None, "persona"),  # "web" no cuenta dentro de otra palabra
        ("María Redactora", None, "persona"),
    ],
)
def test_derivar_firma_busca_dentro_del_texto(texto: str, agencia: str | None, tipo: str) -> None:
    assert normalizacion.derivar_firma(texto, "La Prensa", CONFIG) == (agencia, tipo)


def test_la_firma_con_nombre_de_persona_y_agencia_no_guarda_el_nombre() -> None:
    (fila,), _ = _normalizar([_noticia(firma="Ana Nombresecreto, Associated Press")])
    assert (fila["agencia"], fila["tipo_firma"]) == ("AP", "agencia")
    assert "Nombresecreto" not in json.dumps(fila, ensure_ascii=False)


def test_duplicados_toman_la_deteccion_mas_temprana_sin_importar_el_orden() -> None:
    tarde = _noticia(url="https://ejemplo.com/x", fecha_deteccion="2026-10-02T09:00:00Z")
    temprano = _noticia(url="https://www.ejemplo.com/x/", fecha_deteccion="2026-10-01T23:00:00Z")
    sin = _noticia(url="http://ejemplo.com/x?utm_source=a", fecha_deteccion="")
    for orden in ([tarde, temprano, sin], [sin, temprano, tarde], [temprano, sin, tarde]):
        (fila,), _ = _normalizar(orden)
        assert fila["fecha_deteccion"] == "2026-10-01T23:00:00Z"


def test_deteccion_mas_temprana_compara_instantes_no_texto() -> None:
    a = _noticia(url="https://ejemplo.com/x", fecha_deteccion="2026-10-01T23:00:00-05:00")  # 2026-10-02T04:00Z
    b = _noticia(url="https://ejemplo.com/x/", fecha_deteccion="2026-10-02T01:00:00Z")
    (fila,), _ = _normalizar([a, b])
    assert fila["fecha_deteccion"] == "2026-10-02T01:00:00Z"


def test_indicador_duplicado_conserva_la_primera_aparicion_sin_rellenar_con_otras() -> None:
    base = {"pais_iso3": "PAN", "indicador_id": "X.Y", "anio": "2020", "fuente_url": "https://x.example/",
            "fecha_extraccion": "2026-10-06T10:00:00Z", "licencia": "CC"}  # fmt: skip
    completa = base | {"valor": "1.5", "unidad": "%"}
    incompleta = base | {"valor": "", "unidad": "otra"}
    for orden in ([completa, incompleta], [incompleta, completa]):
        registro = normalizacion.Registro()
        (fila,) = normalizacion.normalizar_indicadores(orden, CONFIG, registro)
        assert (fila["valor"], fila["unidad"]) == (1.5, "%")
        assert len(registro.duplicados) == 1
    nula_a = base | {"valor": "", "unidad": "%"}
    nula_b = base | {"valor": "", "unidad": "otra"}
    (fila,) = normalizacion.normalizar_indicadores([nula_a, nula_b], CONFIG, normalizacion.Registro())
    assert fila["valor"] is None  # nunca se rellena con el valor de otra fila ni con 0


def test_los_tests_no_escriben_en_el_repo(validos: Path) -> None:
    assert not str(validos).startswith(str(RAIZ))
