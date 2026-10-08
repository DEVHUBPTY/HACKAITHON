"""E1-06: herramienta de etiquetado. Las etiquetas de estas pruebas son SINTÉTICAS (tmp_path); nadie etiqueta aquí."""

import csv
from collections import Counter
from pathlib import Path

import pytest

from eval import etiquetar as et
from eval import ruido as eval_ruido
from src import db
from src.configuracion import cargar_etiquetado, cargar_temas, validar_todo

_CFG_REAL = cargar_etiquetado()
# Las pruebas sortean sobre bases sintéticas: sin la muestra congelada ni las ampliaciones de la config real.
CFG = _CFG_REAL.model_copy(update={"muestra": _CFG_REAL.muestra.model_copy(update={"congelada": None, "ampliaciones": []})})
TEMAS = cargar_temas()
UTC_FIJA = "2026-10-06T15:00:00Z"


@pytest.fixture(autouse=True)
def _config_sintetica(monkeypatch):
    """``main`` carga la config real; las pruebas usan ``CFG`` (sin muestra congelada, que apunta a la base real)."""
    monkeypatch.setattr(et, "cargar_etiquetado", lambda *a, **k: CFG)


def _config_sintetica_dir(tmp_path: Path, monkeypatch) -> None:
    """Para ``AppTest`` (corre el script en limpio): una carpeta de config sin muestra congelada ni ampliaciones (``HACKIA_CONFIG``)."""
    import yaml

    datos = yaml.safe_load((Path(et.RAIZ) / "config" / "etiquetado.yaml").read_text(encoding="utf-8"))
    datos["muestra"].pop("congelada", None)
    datos["muestra"].pop("ampliaciones", None)
    carpeta = tmp_path / "config_sintetica"
    carpeta.mkdir()
    (carpeta / "etiquetado.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("HACKIA_CONFIG", str(carpeta))


def _noticias(n: int = 150) -> list[dict]:
    """Un tercio son ruido según el filtro (``es_ruido``)."""
    return [
        {"id_noticia": f"NOT-{i:010x}", "titulo": f"Titular sintético {i}", "medio": "m.test", "url": f"https://m.test/{i}",
         "fecha_publicacion": None, "fecha_deteccion": UTC_FIJA, "es_ruido": i % 3 == 0}
        for i in range(n)
    ]


def _base(ruta: Path, n: int = 150) -> Path:
    con = db.conectar(ruta)
    db.crear_esquema(con)
    db.insertar(con, "noticias", [{**x, "url_canonica": x["url"], "tipo_firma": "sin_firma"} for x in _noticias(n)])
    con.close()
    return ruta


def _fila(id_: str, por: str, ruido="ninguno", principal="economia", secundario="", grupo="", regional="", titulo="t") -> dict:
    return {"id_noticia": id_, "titulo": titulo, "tema_principal": principal if ruido == "ninguno" else "",
            "tema_secundario": secundario, "ruido": ruido, "grupo": grupo, "alcance_regional": regional, "nota": "",
            "etiquetado_por": por, "fecha_etiquetado": UTC_FIJA}


# ---------------------------------------------------------------- config


def test_config_etiquetado_valida_y_coincide_con_temas():
    assert "etiquetado" in validar_todo()
    assert set(CFG.ruido.motivos) == {"no_es_panama", "fuera_de_temas", "no_es_noticia"}


# ---------------------------------------------------------------- muestra


def test_muestra_reproducible_con_la_semilla_y_del_tamano_pedido():
    a = et.construir_muestra(_noticias(), set(), CFG)
    b = et.construir_muestra(list(reversed(_noticias())), set(), CFG)  # el orden de entrada no importa
    assert [m["id_noticia"] for m in a] == [m["id_noticia"] for m in b]
    assert len(a) == CFG.muestra.tamano == 100
    assert sum(m["doble"] for m in a) == CFG.muestra.tamano_acuerdo
    assert all(m["doble"] for m in a[: CFG.muestra.tamano_acuerdo])
    assert len({m["id_noticia"] for m in a}) == len(a)


def test_muestra_estratificada_70_30_con_dobles_14_6_y_pesos():
    m = et.construir_muestra(_noticias(), set(), CFG)  # 100 no ruido y 50 ruido en la población
    nr, r = [x for x in m if x["estrato"] == "no_ruido"], [x for x in m if x["estrato"] == "ruido"]
    assert (len(nr), len(r)) == (70, 30)
    assert (sum(x["doble"] for x in nr), sum(x["doble"] for x in r)) == (14, 6)
    assert all(not x["es_ruido"] for x in nr) and all(x["es_ruido"] for x in r)
    assert nr[0]["peso"] == pytest.approx(100 / 70) and r[0]["peso"] == pytest.approx(50 / 30)
    # los pesos reponderan la muestra a la población
    assert sum(x["peso"] for x in m) == pytest.approx(150)
    assert 0 < et.n_efectivo(m) <= len(m)
    assert any("n efectivo" in linea for linea in et.composicion(m))


def test_estrato_corto_cede_su_cuota_al_otro_y_el_peso_lo_refleja():
    noticias = _noticias(150)
    for n in noticias:  # solo 40 no ruido elegibles
        n["es_ruido"] = n["id_noticia"] > "NOT-0000000027" or False
    m = et.construir_muestra(noticias, set(), CFG)
    por = Counter(x["estrato"] for x in m)
    assert sum(por.values()) == 100 and por["no_ruido"] < 70
    nr = [x for x in m if x["estrato"] == "no_ruido"]
    assert nr[0]["peso"] == pytest.approx(nr[0]["poblacion"] / len(nr))


def test_leer_noticias_exige_la_limpieza(tmp_path):
    con = db.conectar(tmp_path / "s.duckdb")
    db.crear_esquema(con)
    db.insertar(con, "noticias", [{"id_noticia": "NOT-1", "titulo": "T", "url": "u", "url_canonica": "u", "medio": "m", "tipo_firma": "sin_firma"}])
    con.close()
    with pytest.raises(et.ErrorEtiquetado, match="limpieza"):
        et.leer_noticias(tmp_path / "s.duckdb")


def test_otra_semilla_cambia_la_muestra():
    otra = CFG.model_copy(update={"muestra": CFG.muestra.model_copy(update={"semilla": CFG.muestra.semilla + 1})})
    a, b = et.construir_muestra(_noticias(), set(), CFG), et.construir_muestra(_noticias(), set(), otra)
    assert [m["id_noticia"] for m in a] != [m["id_noticia"] for m in b]


def test_la_muestra_excluye_los_ejemplos_y_no_pasa_de_lo_disponible():
    noticias = _noticias(30)
    excluidos = {n["id_noticia"] for n in noticias[:10]}
    muestra = et.construir_muestra(noticias, excluidos, CFG)
    assert len(muestra) == 20
    assert not {m["id_noticia"] for m in muestra} & excluidos


def test_la_muestra_real_no_contiene_ejemplos_excluidos():
    excluidos = et.cargar_excluidos(et.RAIZ / CFG.archivos.ejemplos_excluidos)
    assert len(excluidos) >= 10
    muestra = et.construir_muestra(_noticias() + [{**_noticias(1)[0], "id_noticia": i} for i in excluidos], excluidos, CFG)
    assert not {m["id_noticia"] for m in muestra} & excluidos


def test_asignacion_incluye_los_dobles_y_reparte_el_resto_sin_solaparse():
    muestra = et.construir_muestra(_noticias(), set(), CFG)
    a, b = et.asignadas(muestra, 1, 2), et.asignadas(muestra, 2, 2)
    dobles = {m["id_noticia"] for m in muestra if m["doble"]}
    ids_a, ids_b = {m["id_noticia"] for m in a}, {m["id_noticia"] for m in b}
    assert dobles <= ids_a and dobles <= ids_b
    assert ids_a & ids_b == dobles
    assert ids_a | ids_b == {m["id_noticia"] for m in muestra}
    with pytest.raises(et.ErrorEtiquetado):
        et.asignadas(muestra, 3, 2)


def test_leer_noticias_no_trae_descripcion_ni_ruido(tmp_path):
    ruta = tmp_path / "s.duckdb"
    con = db.conectar(ruta)
    db.crear_esquema(con)
    db.insertar(con, "noticias", [{"id_noticia": "NOT-1", "titulo": "T", "url": "u", "url_canonica": "u", "medio": "m",
                                   "descripcion": "DESCRIPCION-SECRETA", "tipo_firma": "sin_firma", "es_ruido": True,
                                   "motivo_ruido": "no_es_panama"}])
    con.close()
    filas = et.leer_noticias(ruta)
    assert "descripcion" not in filas[0] and "motivo_ruido" not in filas[0]


# ---------------------------------------------------------------- nombres


@pytest.mark.parametrize("nombre", ["Claude", "GPT-4", "Asistente IA", "bot", "IA", "Ai", "modelo local", "Claude Code", "x", "", "  ", "123", "Gemma 3"])
def test_rechaza_nombres_de_herramientas_o_invalidos(nombre):
    with pytest.raises(et.ErrorEtiquetado):
        et.validar_nombre(nombre, CFG)


@pytest.mark.parametrize("nombre", ["Ana María Pérez", "Claudia", "Javier", "O'Brien", "José-Luis", "Ai Lin", "Mia Bot Smith"])
def test_acepta_nombres_de_personas_incluido_claudia(nombre):
    assert et.validar_nombre(nombre, CFG) == nombre


def test_slug_y_grupo():
    assert et.slug_nombre("Ana María Pérez") == "ana_maria_perez"
    assert et.normalizar_grupo("Sismo Chiriquí!") == "sismo-chiriqui"
    assert et.normalizar_grupo("  ") == ""


# ---------------------------------------------------------------- filas


def test_fila_valida_y_reglas_de_ruido_y_temas():
    assert et.validar_fila(_fila("NOT-1", "Ana"), CFG, TEMAS) == []
    assert et.validar_fila(_fila("NOT-1", "Ana", secundario="regulacion", grupo="g-1"), CFG, TEMAS) == []
    assert et.validar_fila(_fila("NOT-1", "Ana", ruido="fuera_de_temas"), CFG, TEMAS) == []
    mala = _fila("NOT-1", "Ana", ruido="fuera_de_temas") | {"tema_principal": "economia"}
    assert any("no lleva tema" in e for e in et.validar_fila(mala, CFG, TEMAS))
    assert any("no lleva grupo" in e for e in et.validar_fila(_fila("N", "Ana", ruido="no_es_panama", grupo="g"), CFG, TEMAS))
    assert any("tema_principal" in e for e in et.validar_fila(_fila("N", "Ana", principal="deportes"), CFG, TEMAS))
    assert any("repetir" in e for e in et.validar_fila(_fila("N", "Ana", secundario="economia"), CFG, TEMAS))
    assert any("ruido" in e for e in et.validar_fila(_fila("N", "Ana") | {"ruido": "quizas"}, CFG, TEMAS))
    assert any("grupo" in e for e in et.validar_fila(_fila("N", "Ana", grupo="Sismo Grande"), CFG, TEMAS))
    assert any("ISO" in e for e in et.validar_fila(_fila("N", "Ana") | {"fecha_etiquetado": "ayer"}, CFG, TEMAS))
    assert et.validar_fila(_fila("N", "Claude"), CFG, TEMAS)  # nombre de IA
    assert et.validar_fila(_fila("N", "Ana", ruido="no_es_noticia"), CFG, TEMAS) == []
    assert et.validar_fila(_fila("N", "Ana", regional="si"), CFG, TEMAS) == []
    assert any("alcance_regional" in e for e in et.validar_fila(_fila("N", "Ana", regional="quizas"), CFG, TEMAS))
    assert any("solo aplica" in e for e in et.validar_fila(_fila("N", "Ana", ruido="no_es_panama", regional="si"), CFG, TEMAS))


def test_guardar_etiqueta_crea_reemplaza_y_registra_quien_y_cuando(tmp_path):
    ruta = tmp_path / "ana_perez.csv"
    n = _noticias(2)
    et.guardar_etiqueta(ruta, CFG, TEMAS, n[0], {"ruido": "ninguno", "tema_principal": "economia"}, "Ana Pérez")
    et.guardar_etiqueta(ruta, CFG, TEMAS, n[1], {"ruido": "no_es_panama"}, "Ana Pérez")
    et.guardar_etiqueta(ruta, CFG, TEMAS, n[0], {"ruido": "ninguno", "tema_principal": "turismo", "grupo": "Cruceros 2026", "alcance_regional": True, "nota": " dudo "}, "Ana Pérez")
    filas = et.leer_csv(ruta)
    assert [f["id_noticia"] for f in filas] == [n[1]["id_noticia"], n[0]["id_noticia"]]
    ultima = filas[1]
    assert (ultima["tema_principal"], ultima["grupo"], ultima["nota"], ultima["etiquetado_por"]) == ("turismo", "cruceros-2026", "dudo", "Ana Pérez")
    assert ultima["alcance_regional"] == "si"
    assert ultima["fecha_etiquetado"].endswith("Z") and not et.validar_fila(ultima, CFG, TEMAS)
    with pytest.raises(et.ErrorEtiquetado):
        et.guardar_etiqueta(ruta, CFG, TEMAS, n[0], {"ruido": "ninguno", "tema_principal": "inventado"}, "Ana Pérez")
    with pytest.raises(et.ErrorEtiquetado):
        et.guardar_etiqueta(ruta, CFG, TEMAS, n[0], {"ruido": "ninguno", "tema_principal": "economia"}, "ChatGPT")


def test_validar_hoja_detecta_columnas_ids_repetidos_y_ajenos(tmp_path):
    carpeta = tmp_path / "eval" / "etiquetas"
    ruta = carpeta / "ana.csv"
    et.escribir_csv(ruta, [_fila("NOT-1", "Ana"), _fila("NOT-1", "Ana"), _fila("NOT-9", "Ana")])
    problemas = et.validar_hoja(ruta, CFG, TEMAS, {"NOT-1"})
    assert any("repetido" in p for p in problemas) and any("no está en la muestra" in p for p in problemas)
    et.escribir_csv(ruta, [_fila("NOT-1", "Ana")])
    assert et.validar_hoja(ruta, CFG, TEMAS, {"NOT-1"}) == []
    et.escribir_csv(ruta, [_fila("NOT-1", "Beto")])
    assert any("sola persona" in p for p in et.validar_hoja(ruta, CFG, TEMAS))
    ruta.write_text("a,b\n1,2\n", encoding="utf-8")
    assert any("columnas" in p for p in et.validar_hoja(ruta, CFG, TEMAS))


# ---------------------------------------------------------------- kappa


def test_kappa_valores_conocidos():
    assert et.kappa_cohen(["a", "b"] * 5, ["a", "b"] * 5) == 1.0
    # po = 35/50 = 0.7; pe = 0.7 * 0.6 + 0.3 * 0.4 = 0.54 -> kappa = 0.16 / 0.46
    a = ["s"] * 25 + ["s"] * 10 + ["n"] * 5 + ["n"] * 10 + ["s"] * 0
    b = ["s"] * 25 + ["n"] * 10 + ["s"] * 5 + ["n"] * 10
    assert et.kappa_cohen(a, b) == pytest.approx(0.16 / 0.46, abs=1e-9)
    assert et.kappa_cohen(["a", "b", "a", "b"], ["b", "a", "b", "a"]) == pytest.approx(-1.0)
    assert et.kappa_cohen([], []) is None
    assert et.kappa_cohen(["a", "a"], ["a", "a"]) == 1.0  # pe = 1 y po = 1
    assert et.kappa_cohen(["a", "a"], ["a"]) is None


def _hojas_dobles(coinciden: int, n: int = 20) -> dict:
    ids = [f"NOT-{i:03d}" for i in range(n)]
    temas = ["economia", "turismo", "regulacion", "logistica"]
    a = [_fila(i, "Ana", principal=temas[k % 4], grupo="g-a" if k < 4 else "") for k, i in enumerate(ids)]
    b = [
        _fila(i, "Beto", principal=temas[k % 4] if k < coinciden else temas[(k + 1) % 4], grupo="g-b" if k < 4 else "")
        for k, i in enumerate(ids)
    ]
    return {"Ana": a, "Beto": b}


def test_acuerdo_perfecto_y_bajo():
    r = et.acuerdo(_hojas_dobles(20), CFG)[0]
    assert r["kappa_categoria"] == 1.0 and r["kappa_pares_grupo"] == 1.0 and not r["bajo"] and r["n_comunes"] == 20
    assert r["acuerdo_categoria"]["n"] == 20 and r["acuerdo_categoria"]["ic95"][1] == 1.0
    malo = et.acuerdo(_hojas_dobles(8), CFG)[0]
    assert malo["bajo"] and len(malo["desacuerdos"]) == 12
    assert any("ACUERDO BAJO" in linea for linea in et.texto_acuerdo([malo], CFG))
    assert et.texto_acuerdo([], CFG)[0].startswith("SIN ACUERDO")


def test_acuerdo_sin_titulos_en_comun_no_inventa_numero():
    hojas = {"Ana": [_fila("NOT-1", "Ana")], "Beto": [_fila("NOT-2", "Beto")]}
    r = et.acuerdo(hojas, CFG)[0]
    assert r["n_comunes"] == 0 and r["kappa_categoria"] is None and r["bajo"]


# ---------------------------------------------------------------- consolidar y flujo de punta a punta


def test_consolidar_acuerdo_disputa_y_tercera_persona():
    hojas = {"Ana": [_fila("A", "Ana"), _fila("B", "Ana", principal="turismo"), _fila("C", "Ana", ruido="no_es_panama")],
             "Beto": [_fila("A", "Beto", secundario="regulacion"), _fila("B", "Beto", principal="regulacion"), _fila("D", "Beto")]}
    finales, disputas = et.consolidar(hojas, CFG)
    assert disputas == ["B"]
    por_id = {f["id_noticia"]: f for f in finales}
    assert set(por_id) == {"A", "C", "D"}
    assert por_id["A"]["n_etiquetadores"] == "2" and por_id["A"]["tema_secundario"] == ""
    assert por_id["A"]["etiquetado_por"] == "Ana; Beto"
    hojas["Carla"] = [_fila("B", "Carla", principal="turismo")]
    finales, disputas = et.consolidar(hojas, CFG)
    assert disputas == [] and {f["id_noticia"]: f for f in finales}["B"]["tema_principal"] == "turismo"


def test_cli_de_punta_a_punta_con_etiquetas_sinteticas(tmp_path, capsys):
    ruta_base = tmp_path / "s.duckdb"
    con = db.conectar(ruta_base)
    db.crear_esquema(con)
    db.insertar(con, "noticias", [{**n, "url_canonica": n["url"], "tipo_firma": "sin_firma"} for n in _noticias(120)])
    con.close()
    muestra = et.muestra_desde_base(ruta_base, CFG)
    assert len(muestra) == 100
    carpeta = tmp_path / CFG.archivos.carpeta_personas
    for nombre, parte in (("Ana Pérez", 1), ("Beto Díaz", 2)):
        for m in et.asignadas(muestra, parte, 2):
            et.guardar_etiqueta(carpeta / f"{et.slug_nombre(nombre)}.csv", CFG, TEMAS, m, {"ruido": "ninguno", "tema_principal": "economia"}, nombre)
    base = ["--base", str(ruta_base), "--raiz", str(tmp_path)]
    assert et.main(["--validar", *base]) == 0
    assert et.main(["--acuerdo", *base]) == 0
    assert et.main(["--consolidar", *base]) == 0
    final = et.cargar_etiquetas_finales(tmp_path / CFG.archivos.consolidado)
    assert len(final) == 100 and {f["id_noticia"] for f in final.values()} == {m["id_noticia"] for m in muestra}
    assert et.main(["--validar", *base]) == 0
    # el consolidado lo lee eval.ruido (sin tocar su formato)
    leidas = eval_ruido.leer_etiquetas(tmp_path / CFG.archivos.consolidado, "ruido")
    assert set(leidas) == set(final) and all(v is None for v in leidas.values())
    capsys.readouterr()


def test_consolidar_se_niega_con_acuerdo_bajo_o_ausente(tmp_path, capsys):
    carpeta = tmp_path / CFG.archivos.carpeta_personas
    et.escribir_csv(carpeta / "ana.csv", [_fila("NOT-1", "Ana")])
    base = ["--base", str(tmp_path / "no_existe.duckdb"), "--raiz", str(tmp_path)]
    assert et.main(["--consolidar", *base]) == 3  # una sola persona: no hay acuerdo
    assert not (tmp_path / CFG.archivos.consolidado).exists()
    assert et.main(["--consolidar", "--forzar", *base]) == 1  # sin la base no hay estrato ni peso
    ruta_base = _base(tmp_path / "s.duckdb")
    muestra = et.muestra_desde_base(ruta_base, CFG)
    et.escribir_csv(carpeta / "ana.csv", [_fila(muestra[0]["id_noticia"], "Ana")])
    assert et.main(["--consolidar", "--forzar", "--base", str(ruta_base), "--raiz", str(tmp_path)]) == 0
    final = et.cargar_etiquetas_finales(tmp_path / CFG.archivos.consolidado)
    fila = final[muestra[0]["id_noticia"]]
    assert fila["estrato"] == muestra[0]["estrato"] and float(fila["peso_muestreo"]) == pytest.approx(muestra[0]["peso"], rel=1e-5)
    capsys.readouterr()


def test_acuerdo_sin_hojas_sale_con_2(tmp_path, capsys):
    assert et.main(["--acuerdo", "--base", str(tmp_path / "x.duckdb"), "--raiz", str(tmp_path)]) == 2
    capsys.readouterr()


def test_consolidar_informa_y_lista_los_titulos_en_disputa(tmp_path, capsys):
    ruta_base = _base(tmp_path / "s.duckdb")
    m = et.muestra_desde_base(ruta_base, CFG)
    dobles = [x for x in m if x["doble"]]
    carpeta = tmp_path / CFG.archivos.carpeta_personas
    for nombre in ("Ana", "Beto"):
        filas = [_fila(x["id_noticia"], nombre, principal="turismo" if (nombre == "Beto" and i == 0) else "economia", titulo=x["titulo"])
                 for i, x in enumerate(dobles)]
        et.escribir_csv(carpeta / f"{nombre.lower()}.csv", filas)
    base = ["--base", str(ruta_base), "--raiz", str(tmp_path)]
    assert et.main(["--desempate", *base]) == 0
    assert "1 titulares en disputa" in capsys.readouterr().out
    assert et.main(["--consolidar", "--forzar", *base]) == 0
    salida = capsys.readouterr().out
    assert "EXCLUIDOS POR DISPUTA: 1" in salida and dobles[0]["id_noticia"] in salida
    assert dobles[0]["id_noticia"] not in et.cargar_etiquetas_finales(tmp_path / CFG.archivos.consolidado)
    # una tercera persona desempata y el titular entra
    et.escribir_csv(carpeta / "carla.csv", [_fila(dobles[0]["id_noticia"], "Carla", principal="turismo", titulo=dobles[0]["titulo"])])
    assert et.main(["--consolidar", "--forzar", *base]) == 0
    assert "Excluidos por disputa: 0" in capsys.readouterr().out
    assert et.cargar_etiquetas_finales(tmp_path / CFG.archivos.consolidado)[dobles[0]["id_noticia"]]["tema_principal"] == "turismo"


def test_en_disputa_solo_titulos_sin_mayoria():
    hojas = {"Ana": [_fila("A", "Ana"), _fila("B", "Ana")], "Beto": [_fila("A", "Beto"), _fila("B", "Beto", principal="turismo")]}
    assert et.en_disputa(hojas) == {"B": ["Ana", "Beto"]}


def test_grupos_lista_titulares_y_renombrar_unifica(tmp_path, capsys):
    carpeta = tmp_path / CFG.archivos.carpeta_personas
    et.escribir_csv(carpeta / "ana.csv", [_fila("A", "Ana", grupo="sismo-chiriqui", titulo="Sismo sacude Chiriquí"), _fila("C", "Ana", grupo="solo-uno", titulo="Otro")])
    et.escribir_csv(carpeta / "beto.csv", [_fila("B", "Beto", grupo="temblor-chiriqui", titulo="Temblor en Chiriquí")])
    base = ["--base", str(tmp_path / "x.duckdb"), "--raiz", str(tmp_path)]
    assert et.main(["--grupos", *base]) == 0
    salida = capsys.readouterr().out
    assert "[sismo-chiriqui]" in salida and "Temblor en Chiriquí" in salida and "UN SOLO TITULAR" in salida
    assert et.main(["--renombrar", "temblor-chiriqui", "Sismo Chiriquí", "--persona", "Beto", *base]) == 0
    assert et.leer_csv(carpeta / "beto.csv")[0]["grupo"] == "sismo-chiriqui"
    assert len(et.grupos_usados(et.leer_hojas(tmp_path, CFG))["sismo-chiriqui"]) == 2
    assert et.main(["--renombrar", "no-existe", "x", "--persona", "Beto", *base]) == 1
    capsys.readouterr()


def test_ruido_mide_el_subconjunto_regional_aparte(tmp_path):
    ruta = tmp_path / "e.csv"
    et.escribir_csv(ruta, [_fila("A", "Ana", regional="si"), _fila("B", "Ana"), _fila("C", "Ana", regional="si")])
    humanos = eval_ruido.leer_regional(ruta)
    assert humanos == {"A": True, "B": False, "C": True}
    lineas = eval_ruido.medir_regional(humanos, {"A": True, "B": True, "C": False}, 1.96)
    assert "1/2" in lineas[1] and "1/2" in lineas[2]
    sin_columna = tmp_path / "v.csv"
    sin_columna.write_text("id_noticia,ruido\nA,ninguno\n", encoding="utf-8")
    assert eval_ruido.leer_regional(sin_columna) is None


def test_coherencia_exige_los_motivos_de_temas_mas_no_es_noticia(tmp_path):
    import shutil
    from src.configuracion import CARPETA_CONFIG, ErrorDeConfiguracion

    carpeta = tmp_path / "config"
    shutil.copytree(CARPETA_CONFIG, carpeta)
    ruta = carpeta / "etiquetado.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("[no_es_panama, fuera_de_temas, no_es_noticia]", "[no_es_panama, fuera_de_temas]"), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="no_es_noticia"):
        validar_todo(carpeta)


def test_validar_sin_etiquetas_sale_con_2(tmp_path, capsys):
    assert et.main(["--validar", "--base", str(tmp_path / "x.duckdb"), "--raiz", str(tmp_path)]) == 2
    capsys.readouterr()


def test_sugerencias_de_grupo_no_filtran_etiquetas_de_titulares_dobles():
    hojas = {"Ana": [_fila("D1", "Ana", grupo="mio"), _fila("S1", "Ana", grupo="otro-mio")],
             "Beto": [_fila("D1", "Beto", grupo="de-beto-doble"), _fila("S2", "Beto", grupo="de-beto-simple")]}
    assert et.grupos_sugeridos(hojas, "Ana", {"D1"}) == ["de-beto-simple", "mio", "otro-mio"]


def test_el_csv_tiene_las_columnas_del_contrato(tmp_path):
    ruta = tmp_path / "a.csv"
    et.escribir_csv(ruta, [_fila("NOT-1", "Ana")])
    with ruta.open(encoding="utf-8", newline="") as f:
        assert tuple(next(csv.reader(f))) == et.COLUMNAS
    assert {"id_noticia", "tema_principal", "ruido", "grupo", "etiquetado_por", "fecha_etiquetado"} <= set(et.COLUMNAS)


def test_la_interfaz_guarda_una_etiqueta_en_una_carpeta_temporal(tmp_path, monkeypatch):
    """Smoke con AppTest: abre la interfaz, escribe un nombre, etiqueta un titular y comprueba la fila guardada.

    Base y hojas van a ``tmp_path`` (``HACKIA_BASE`` y ``HACKIA_RAIZ``): no toca ``eval/etiquetas/`` real.
    """
    from streamlit.testing.v1 import AppTest

    _config_sintetica_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("HACKIA_BASE", str(_base(tmp_path / "s.duckdb")))
    monkeypatch.setenv("HACKIA_RAIZ", str(tmp_path))
    app = AppTest.from_file(str(Path(et.__file__)), default_timeout=60)
    app.run()
    assert not app.exception
    assert any("Escribe tu nombre" in i.value for i in app.info)
    app.sidebar.text_input(key="nombre").set_value("Prueba Humana").run()
    assert not app.exception
    clave = next(sel.key for sel in app.selectbox if sel.key and sel.key.startswith("tp-"))
    app.selectbox(key=clave).select("turismo").run()
    app.checkbox(key=next(c.key for c in app.checkbox if c.key and c.key.startswith("reg-"))).check().run()
    app.button[0].click().run()
    assert not app.exception and not app.error
    filas = et.leer_csv(tmp_path / CFG.archivos.carpeta_personas / "prueba_humana.csv")
    assert len(filas) == 1
    assert (filas[0]["tema_principal"], filas[0]["alcance_regional"], filas[0]["etiquetado_por"]) == ("turismo", "si", "Prueba Humana")
    assert filas[0]["id_noticia"] == clave.removeprefix("tp-")


def test_la_interfaz_en_desempate_muestra_solo_los_titulos_en_disputa(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    ruta_base = _base(tmp_path / "s.duckdb")
    d = [x for x in et.muestra_desde_base(ruta_base, CFG) if x["doble"]][0]["id_noticia"]
    carpeta = tmp_path / CFG.archivos.carpeta_personas
    et.escribir_csv(carpeta / "ana.csv", [_fila(d, "Ana")])
    et.escribir_csv(carpeta / "beto.csv", [_fila(d, "Beto", principal="turismo")])
    _config_sintetica_dir(tmp_path, monkeypatch)
    monkeypatch.setenv("HACKIA_BASE", str(ruta_base))
    monkeypatch.setenv("HACKIA_RAIZ", str(tmp_path))
    app = AppTest.from_file(str(Path(et.__file__)), default_timeout=60)
    app.run()
    app.sidebar.text_input(key="nombre").set_value("Carla Ruiz").run()
    app.sidebar.checkbox[0].check().run()
    assert not app.exception
    assert [k for k in (s.key for s in app.selectbox) if k and k.startswith("tp-")] == [f"tp-{d}"]
    assert len(app.selectbox[0].options) == 1  # la lista de titulares tiene solo el que está en disputa
