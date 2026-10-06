"""E1-07: embeddings, clasificación (A y B), baseline y filtro de ruido por similitud. Sin red: codificador de prueba."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from src import baseline, clasificacion, db, embeddings
from src.configuracion import (
    CARGADORES,
    ConfigClasificacion,
    ErrorDeConfiguracion,
    UmbralesMetodo,
    cargar_clasificacion,
    cargar_config,
    cargar_ruido,
    cargar_temas,
    validar_todo,
)
from src.limpieza import Reglas
from tests.motor_falso import MotorFalso, config_de_prueba, temas_de_prueba

REGLAS = Reglas.desde_config()
RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def emb(tmp_path):
    cfg = config_de_prueba()
    motor = MotorFalso()
    return embeddings.crear(cfg, motor=motor, raiz=tmp_path)


def _fila(id_, titulo, es_ruido=False, tema_origen="economia", descripcion=None, regional=False, motivo=None):
    return {
        "id_noticia": id_, "titulo": titulo, "url": f"https://x.test/{id_}", "url_canonica": f"https://x.test/{id_}",
        "medio": "Medio", "tipo_firma": "sin firma", "tema": tema_origen, "descripcion": descripcion,
        "titulo_original": titulo, "titulo_limpio": titulo, "es_ruido": es_ruido, "motivo_ruido": motivo,
        "alcance_regional": regional,
    }


def _base(tmp_path, filas) -> Path:
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": filas})
    return ruta


def _leer(ruta, sql):
    con = db.conectar(ruta, solo_lectura=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


FILAS = [
    _fila("NOT-1", "Inflacion sube y precios de la canasta suben", tema_origen="regulacion"),
    _fila("NOT-2", "El canal reduce transitos de buques", tema_origen="economia"),
    _fila("NOT-3", "Hoteles llenos de turistas y cruceros", tema_origen="economia"),
    _fila("NOT-4", "Fuerte sismo y temblor sacude la capital", tema_origen="turismo"),
    _fila("NOT-5", "Aprueban ley y decreto que sanciona con multa", tema_origen="logistica"),
    _fila("NOT-6", "Barrios sin agua potable por tuberia rota", tema_origen="eventos_naturales"),
    _fila("NOT-7", "Gol gol gol del delantero", es_ruido=True, motivo="fuera_de_temas", tema_origen="economia"),
]


# ------------------------------------------------------------------ configuración


def test_la_configuracion_de_clasificacion_esta_registrada_y_valida() -> None:
    assert "clasificacion" in CARGADORES
    assert "clasificacion" in validar_todo()
    cfg = cargar_clasificacion()
    assert set(cfg.baseline.palabras_clave) == set(cargar_temas().temas)


def test_los_modelos_estan_fijados_por_id_y_revision_exacta() -> None:
    cfg = cargar_clasificacion()
    assert cfg.modelos["e5"].id == "intfloat/multilingual-e5-small"
    assert cfg.modelos["minilm"].id == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    for modelo in cfg.modelos.values():
        assert len(modelo.revision) == 40 and set(modelo.revision) <= set("0123456789abcdef")
    # e5 exige los prefijos query:/passage:; MiniLM no los usa
    assert (cfg.modelos["e5"].prefijo_titular, cfg.modelos["e5"].prefijo_tema) == ("query: ", "passage: ")
    assert (cfg.modelos["minilm"].prefijo_titular, cfg.modelos["minilm"].prefijo_tema) == ("", "")


def test_el_criterio_ab_esta_fijado_en_la_configuracion() -> None:
    criterio = cargar_clasificacion().criterio_ab
    assert (criterio.remuestreos, criterio.confianza) == (1000, 0.95)


def _copiar_config(tmp_path, reemplazos: dict[str, str]) -> Path:
    carpeta = tmp_path / "config"
    carpeta.mkdir()
    texto = (RAIZ / "config" / "clasificacion.yaml").read_text(encoding="utf-8")
    for viejo, nuevo in reemplazos.items():
        assert viejo in texto
        texto = texto.replace(viejo, nuevo)
    (carpeta / "clasificacion.yaml").write_text(texto, encoding="utf-8")
    return carpeta


@pytest.mark.parametrize(
    ("reemplazos", "mensaje"),
    [
        ({"614241f622f53c4eeff9890bdc4f31cfecc418b3": "main"}, "revision"),           # una rama no es una revisión fija
        ({"modelo_activo: e5": "modelo_activo: inexistente"}, "modelo_activo"),
        ({"metodo_activo: A": "metodo_activo: C"}, "metodo_activo"),
        ({"version: 1\nsemilla: 42": "version: 1\nextra: 1\nsemilla: 42"}, "extra"),                      # claves desconocidas prohibidas
        ({"[crecimiento, pib,": "[Crecimiento, pib,"}, "minúsculas"),                              # término en mayúsculas
        ({"umbral_sin_tema: 0.825": "umbral_sin_tema: 7.0"}, "umbral_sin_tema"),
    ],
)
def test_la_configuracion_invalida_se_rechaza(tmp_path, reemplazos, mensaje) -> None:
    carpeta = _copiar_config(tmp_path, reemplazos)
    with pytest.raises(ErrorDeConfiguracion, match=mensaje):
        cargar_config("clasificacion", ConfigClasificacion, carpeta)


def test_la_coherencia_exige_que_el_baseline_cubra_los_mismos_temas(tmp_path) -> None:
    import shutil

    carpeta = tmp_path / "config"
    shutil.copytree(RAIZ / "config", carpeta)
    ruta = carpeta / "clasificacion.yaml"
    texto = ruta.read_text(encoding="utf-8")
    assert "    regulacion:\n      guia: " in texto
    ruta.write_text(texto.replace("    regulacion:\n      guia: ", "    regulacionx:\n      guia: "), encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion, match="baseline.palabras_clave"):
        validar_todo(carpeta)


def test_ruido_similitud_prototipo_se_valida() -> None:
    cfg = cargar_ruido().similitud_prototipo
    assert cfg.activo is False  # sin etiquetas humanas no se activa
    assert cfg.prototipos and 0 <= cfg.umbral <= 1


# ------------------------------------------------------------------ embeddings


def test_los_vectores_salen_normalizados_y_con_el_prefijo_de_cada_rol(tmp_path) -> None:
    cfg = cargar_clasificacion()
    motor = MotorFalso()
    e = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=motor, raiz=tmp_path)
    v = e.codificar(["Hola mundo", "Otro texto"], "titular")
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-6)
    e.codificar(["Un pasaje"], "tema")
    assert motor.recibidos == ["query: Hola mundo", "query: Otro texto", "passage: Un pasaje"]
    # MiniLM no usa prefijos
    motor2 = MotorFalso()
    embeddings.Embeddings(cfg.modelos["minilm"], cfg, motor=motor2, raiz=tmp_path).codificar(["Hola"], "titular")
    assert motor2.recibidos == ["Hola"]


def test_la_cache_en_disco_evita_recodificar_y_sobrevive_a_otra_instancia(tmp_path) -> None:
    cfg = cargar_clasificacion()
    motor = MotorFalso()
    e1 = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=motor, raiz=tmp_path)
    primero = e1.codificar(["uno", "dos", "uno"], "titular")
    assert e1.codificados == 2                       # "uno" repetido se codifica una vez
    assert e1.ruta_cache.exists()
    otro = MotorFalso()
    e2 = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=otro, raiz=tmp_path)
    segundo = e2.codificar(["uno", "dos", "uno"], "titular")
    assert otro.recibidos == [] and e2.codificados == 0 and e2.aciertos_cache == 3
    assert np.array_equal(primero, segundo)


def test_la_cache_separa_roles_y_modelos(tmp_path) -> None:
    cfg = cargar_clasificacion()
    e = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=MotorFalso(), raiz=tmp_path)
    e.codificar(["igual"], "titular")
    e.codificar(["igual"], "tema")
    assert e.codificados == 2                        # mismo texto, distinto prefijo: dos vectores
    m = embeddings.Embeddings(cfg.modelos["minilm"], cfg, motor=MotorFalso(), raiz=tmp_path)
    assert m.ruta_cache != e.ruta_cache


def test_la_cache_no_guarda_el_texto(tmp_path) -> None:
    """El texto puede traer la descripción del RSS (D-31): solo se guarda su hash."""
    cfg = cargar_clasificacion()
    e = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=MotorFalso(), raiz=tmp_path)
    texto_interno = "DESCRIPCION-INTERNA-NO-REDISTRIBUIBLE"
    e.codificar([texto_interno], "titular")
    with np.load(e.ruta_cache, allow_pickle=False) as datos:
        assert all(len(c) == embeddings.LARGO_CLAVE for c in datos["claves"].tolist())
        assert texto_interno not in " ".join(datos["claves"].tolist())
    assert texto_interno.encode() not in e.ruta_cache.read_bytes()


def test_un_motor_inyectado_sin_raiz_no_toca_la_cache_real() -> None:
    cfg = cargar_clasificacion()
    e = embeddings.crear(cfg, motor=MotorFalso())
    assert e.usar_cache is False
    e.codificar(["no debe quedar en disco"], "titular")
    assert not e.ruta_cache.exists() or b"no debe" not in e.ruta_cache.read_bytes()


def test_una_cache_danada_se_descarta(tmp_path) -> None:
    cfg = cargar_clasificacion()
    e = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=MotorFalso(), raiz=tmp_path)
    e.codificar(["algo"], "titular")
    e.ruta_cache.write_bytes(b"basura")
    otro = embeddings.Embeddings(cfg.modelos["e5"], cfg, motor=MotorFalso(), raiz=tmp_path)
    assert otro.codificar(["algo"], "titular").shape[0] == 1 and otro.codificados == 1


def test_sin_textos_no_hay_matriz_ni_llamada(tmp_path) -> None:
    motor = MotorFalso()
    e = embeddings.Embeddings(cargar_clasificacion().modelos["e5"], cargar_clasificacion(), motor=motor, raiz=tmp_path)
    assert e.codificar([], "titular").shape == (0, 0) and motor.recibidos == []


def test_los_embeddings_son_locales_sin_api() -> None:
    """D-03: nada de clientes HTTP ni de proveedores de pago en los módulos de embeddings."""
    for archivo in ("embeddings.py", "clasificacion.py", "baseline.py"):
        fuente = (RAIZ / "src" / archivo).read_text(encoding="utf-8")
        assert "requests" not in fuente and "openai" not in fuente.lower() and "deepseek" not in fuente.lower()


# ------------------------------------------------------------------ puntaje y decisión


@pytest.fixture
def ref(emb):
    return clasificacion.construir_referencias(emb, temas_de_prueba(), REGLAS)


def test_metodo_a_centroide_de_descripcion_y_ejemplos(emb, ref) -> None:
    d = clasificacion.clasificar_textos(["inflacion sube precios"], emb, ref, "A", UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=0.0))
    assert d[0].principal == "economia" and d[0].subtema is None
    assert set(d[0].similitudes) == set(cargar_temas().temas)


def test_metodo_b_sube_el_subtema_a_su_tema(emb, ref) -> None:
    d = clasificacion.clasificar_textos(["desempleo y trabajo"], emb, ref, "B", UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=0.0))
    assert (d[0].principal, d[0].subtema) == ("economia", "empleo")
    d = clasificacion.clasificar_textos(["hospital pacientes"], emb, ref, "B", UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=0.0))
    assert (d[0].principal, d[0].subtema) == ("servicios_publicos", "salud")


def test_la_salida_son_solo_los_6_temas_o_sin_tema(emb, ref) -> None:
    textos = ["inflacion", "canal", "turistas", "hospital", "sismo", "ley", "palabras que no estan en ningun tema zzz"]
    permitidos = set(cargar_temas().temas) | {baseline.SIN_TEMA}
    for metodo in ("A", "B"):
        for d in clasificacion.clasificar_textos(textos, emb, ref, metodo, UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=0.5)):
            assert d.principal in permitidos
            assert d.secundario is None or d.secundario in cargar_temas().temas


def test_bajo_el_umbral_no_hay_tema_y_el_umbral_sale_del_yaml(emb, ref) -> None:
    texto = "zzz qqq xxx"                              # sin palabras en común con ningún tema
    estricto = UmbralesMetodo(umbral_sin_tema=0.5, margen_secundario=0.5)
    d = clasificacion.clasificar_textos([texto], emb, ref, "A", estricto)[0]
    assert d.principal == baseline.SIN_TEMA and d.secundario is None and d.subtema is None
    assert d.similitud < 0.5                           # la similitud máxima se conserva para explicar la abstención
    laxo = UmbralesMetodo(umbral_sin_tema=0.0, margen_secundario=0.0)
    assert clasificacion.clasificar_textos([texto], emb, ref, "A", laxo)[0].principal != baseline.SIN_TEMA
    assert "umbral_sin_tema" in (RAIZ / "src" / "clasificacion.py").read_text(encoding="utf-8")


def test_sin_numeros_magicos_en_los_modulos_de_clasificacion() -> None:
    """Ningún umbral, peso ni ventana en ``src/``: los decimales del código son 0 o 1 (neutros); el resto va en YAML."""
    import ast

    for archivo in ("embeddings.py", "clasificacion.py", "baseline.py"):
        arbol = ast.parse((RAIZ / "src" / archivo).read_text(encoding="utf-8"))
        flotantes = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant) and isinstance(n.value, float)}
        assert flotantes <= {0.0, 1.0}, (archivo, flotantes)


def test_tema_secundario_solo_si_esta_dentro_del_margen(emb, ref) -> None:
    texto = "canal transitos y turistas hoteles"        # mezcla logística y turismo
    sin_margen = UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=0.0)
    ancho = UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=1.0)
    assert clasificacion.clasificar_textos([texto], emb, ref, "A", sin_margen)[0].secundario is None
    d = clasificacion.clasificar_textos([texto], emb, ref, "A", ancho)[0]
    assert d.secundario in {"logistica", "turismo"} and d.secundario != d.principal
    assert d.similitud_secundaria <= d.similitud


def test_un_empate_lo_gana_el_primer_tema_de_temas_yaml() -> None:
    temas = list(cargar_temas().temas)
    sim = np.zeros(len(temas))
    d = clasificacion.decidir(sim, [None] * len(temas), temas, UmbralesMetodo(umbral_sin_tema=0.0, margen_secundario=0.0))
    assert d.principal == temas[0]


def test_el_resultado_es_determinista(tmp_path) -> None:
    corridas = []
    for i in range(2):
        e = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path / str(i))
        r = clasificacion.construir_referencias(e, temas_de_prueba(), REGLAS)
        corridas.append(clasificacion.clasificar_textos(["inflacion sube", "canal buques", "zzz"], e, r, "B", UmbralesMetodo(umbral_sin_tema=0.05, margen_secundario=0.5)))
    assert corridas[0] == corridas[1]


def test_los_ejemplos_se_limpian_igual_que_los_titulares(emb) -> None:
    temas = cargar_temas()
    textos = clasificacion.textos_de_referencia(temas, REGLAS)
    assert "¿Cómo se fija el precio del combustible en Panamá? El MEF explica la fórmula quincenal tras aprobarse nuevo subsidio" in textos["economia"]
    assert textos["economia"][0] == temas.temas["economia"].descripcion


def test_texto_de_entrada_usa_la_descripcion_solo_si_existe_y_esta_permitido() -> None:
    assert clasificacion.texto_de_entrada("Titular", None, True) == "Titular"
    assert clasificacion.texto_de_entrada("Titular", "  ", True) == "Titular"
    assert clasificacion.texto_de_entrada("Titular", "Detalle", True) == "Titular. Detalle"
    assert clasificacion.texto_de_entrada("Titular", "Detalle", False) == "Titular"


# ------------------------------------------------------------------ baseline


def test_baseline_clasifica_por_palabras_clave_sin_tildes_ni_mayusculas() -> None:
    b = baseline.Baseline()
    assert b.clasificar("INFLACIÓN cerró el año en 3 %").principal == "economia"
    assert b.clasificar("Fuerte sismo sacude Chiriquí").principal == "eventos_naturales"
    assert b.clasificar("Selección de fútbol clasifica").principal == baseline.SIN_TEMA


def test_baseline_usa_las_mismas_categorias_que_el_clasificador() -> None:
    b = baseline.Baseline()
    assert b.temas == list(cargar_temas().temas)
    textos = ["inflacion", "canal de panama", "turistas", "hospital", "sismo", "ley", "nada de nada"]
    for t in textos:
        r = b.clasificar(t)
        assert r.principal in {*b.temas, baseline.SIN_TEMA}
        assert r.secundario is None or r.secundario in b.temas


def test_baseline_puntaje_empate_y_secundario() -> None:
    b = baseline.Baseline()
    r = b.clasificar("Sequía obliga al Canal a reducir tránsitos")       # logística 2 patrones; eventos naturales 1
    assert (r.principal, r.secundario) == ("logistica", "eventos_naturales")
    assert r.puntajes["logistica"] == 2 and r.puntajes["eventos_naturales"] == 1
    # empate: el primero de temas.yaml (economía) gana
    assert b.clasificar("inflacion y sismo").principal == "economia"
    assert b.clasificar("inflacion").secundario is None


def test_baseline_solo_recibe_el_texto_nunca_el_tema_de_origen() -> None:
    import inspect

    assert list(inspect.signature(baseline.Baseline.clasificar).parameters) == ["self", "texto"]
    assert list(inspect.signature(baseline.Baseline.puntuar).parameters) == ["self", "texto"]


# ------------------------------------------------------------------ pipeline en DuckDB


def _correr(tmp_path, filas=FILAS, activo=False, umbral=0.0, usar_descripcion=True, metodo="A"):
    cfg = config_de_prueba(usar_descripcion=usar_descripcion)
    ruido = cargar_ruido()
    ruido = ruido.model_copy(update={"similitud_prototipo": ruido.similitud_prototipo.model_copy(update={"activo": activo, "umbral": umbral})})
    ruta = _base(tmp_path, filas)
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    resultado = clasificacion.aplicar_a_base(ruta, cfg, ruido, temas_de_prueba(), emb, metodo, REGLAS)
    return ruta, resultado, cfg, ruido


def test_clasifica_las_no_ruido_y_deja_el_ruido_sin_tema(tmp_path) -> None:
    ruta, _, _, _ = _correr(tmp_path)
    filas = {r[0]: r for r in _leer(ruta, "SELECT id_noticia, tema_clasificado, tema_similitud, tema_baseline, es_ruido FROM noticias")}
    esperado = {"NOT-1": "economia", "NOT-2": "logistica", "NOT-3": "turismo", "NOT-4": "eventos_naturales", "NOT-5": "regulacion", "NOT-6": "servicios_publicos"}
    for id_, tema in esperado.items():
        assert filas[id_][1] == tema, id_
        assert filas[id_][2] is not None and 0 <= filas[id_][2] <= 1.0001
        assert filas[id_][3] is not None
    assert filas["NOT-7"][1:4] == (None, None, None)         # ruido: no se clasifica, pero se conserva
    assert len(filas) == len(FILAS)


def test_la_clasificacion_no_usa_el_tema_de_origen(tmp_path) -> None:
    """D-62: cambiar el ``tema`` de origen no cambia ninguna salida (sería una fuga de información)."""
    ruta1, _, _, _ = _correr(tmp_path / "a")
    envenenadas = [dict(f, tema="turismo") for f in FILAS]
    ruta2, _, _, _ = _correr(tmp_path / "b", envenenadas)
    sql = "SELECT id_noticia, tema_clasificado, tema_similitud, tema_secundario, tema_baseline, similitud_panama FROM noticias ORDER BY 1"
    assert _leer(ruta1, sql) == _leer(ruta2, sql)
    assert _leer(ruta1, "SELECT id_noticia, tema FROM noticias ORDER BY 1") != _leer(ruta2, "SELECT id_noticia, tema FROM noticias ORDER BY 1")
    # y el origen tampoco se sobrescribe
    assert [r[1] for r in _leer(ruta1, "SELECT id_noticia, tema FROM noticias ORDER BY 1")] == [f["tema"] for f in FILAS]


def test_guarda_la_similitud_con_cada_tema_y_el_subtema_solo_en_b(tmp_path) -> None:
    ruta, _, _, _ = _correr(tmp_path)
    filas = _leer(ruta, "SELECT id_noticia, metodo, tema, similitud, subtema FROM similitud_tema")
    assert len(filas) == 6 * 6 * 2                           # 6 noticias útiles × 6 temas × métodos A y B
    assert {f[1] for f in filas} == {"A", "B"}
    assert all(f[4] is None for f in filas if f[1] == "A") and all(f[4] is not None for f in filas if f[1] == "B")
    assert not any(f[0] == "NOT-7" for f in filas)           # el ruido no entra
    # el tema principal es el de mayor similitud del método activo
    mejor = {}
    for id_, metodo, tema, sim, _ in filas:
        if metodo == "A" and sim > mejor.get(id_, (None, -1))[1]:
            mejor[id_] = (tema, sim)
    for id_, tema in _leer(ruta, "SELECT id_noticia, tema_clasificado FROM noticias WHERE NOT es_ruido"):
        assert mejor[id_][0] == tema


def test_el_metodo_b_guarda_el_subtema(tmp_path) -> None:
    ruta, _, _, _ = _correr(tmp_path, metodo="B")
    sub = dict(_leer(ruta, "SELECT id_noticia, subtema_clasificado FROM noticias"))
    assert sub["NOT-6"] == "agua" and sub["NOT-7"] is None


def test_es_idempotente_y_no_cambia_el_numero_de_noticias(tmp_path) -> None:
    ruta, _, cfg, ruido = _correr(tmp_path)
    sql = "SELECT * FROM noticias ORDER BY id_noticia"
    antes = _leer(ruta, sql)
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, ruido, temas_de_prueba(), emb, "A", REGLAS)
    assert _leer(ruta, sql) == antes
    assert _leer(ruta, "SELECT count(*) FROM similitud_tema")[0][0] == 6 * 6 * 2


def test_una_base_anterior_sin_las_columnas_nuevas_se_completa(tmp_path) -> None:
    import duckdb

    ruta = tmp_path / "vieja.duckdb"
    con = duckdb.connect(str(ruta))
    cols = [(c, t) for c, t in db.ESQUEMA["noticias"] if c not in clasificacion.COLUMNAS_CLASIFICACION]
    con.execute("CREATE TABLE noticias (" + ", ".join(f'"{c}" {t}' for c, t in cols) + ")")
    con.close()
    con = db.conectar(ruta)
    agregado = db.asegurar_esquema(con)
    con.close()
    assert set(clasificacion.COLUMNAS_CLASIFICACION) <= {a.split(".")[1] for a in agregado if a.startswith("noticias.")}
    assert "similitud_tema" in agregado


def test_exige_haber_corrido_la_limpieza(tmp_path) -> None:
    sin_limpiar = [dict(f, titulo_limpio=None, es_ruido=None) for f in FILAS]
    with pytest.raises(RuntimeError, match="limpieza"):
        _correr(tmp_path, sin_limpiar)


def test_la_descripcion_se_usa_como_texto_interno_y_no_se_escribe_en_ninguna_salida(tmp_path) -> None:
    texto_interno = "DESCRIPCION-INTERNA-NO-REDISTRIBUIBLE zzzunica"
    filas = [_fila("NOT-1", "Titular neutro", descripcion=texto_interno)]
    ruta, _, cfg, ruido = _correr(tmp_path, filas, usar_descripcion=True)
    motor = MotorFalso()
    emb = embeddings.crear(cfg, motor=motor, raiz=tmp_path / "otra")
    clasificacion.aplicar_a_base(ruta, cfg, ruido, temas_de_prueba(), emb, "A", REGLAS)
    assert any(texto_interno in t for t in motor.recibidos)        # se codificó "titular. descripción"
    reporte = clasificacion.construir_reporte(
        clasificacion.aplicar_a_base(ruta, cfg, ruido, temas_de_prueba(), emb, "A", REGLAS), cfg, ruido,
        cfg.modelos[cfg.modelo_activo].umbrales["A"], "A", 1.96,
    )
    assert texto_interno not in str(reporte)
    # con usar_descripcion=false no se codifica
    motor3 = MotorFalso()
    cfg_sin = config_de_prueba(usar_descripcion=False)
    emb3 = embeddings.crear(cfg_sin, motor=motor3, raiz=tmp_path / "tercera")
    clasificacion.aplicar_a_base(ruta, cfg_sin, ruido, temas_de_prueba(), emb3, "A", REGLAS)
    assert not any("zzzunica" in t for t in motor3.recibidos)


def test_el_reporte_lleva_n_e_ic_y_no_afirma_exactitud(tmp_path) -> None:
    ruta, filas, cfg, ruido = _correr(tmp_path)
    r = clasificacion.construir_reporte(filas, cfg, ruido, cfg.modelos[cfg.modelo_activo].umbrales["A"], "A", 1.96)
    assert r["clasificadas_no_ruido"] == 6 and r["noticias_en_base"] == 7
    total = sum(p["n"] for p in r["distribucion"].values())
    assert total == 6
    for p in r["distribucion"].values():
        assert p["de"] == 6 and len(p["ic95"]) == 2 and p["ic95"][0] <= p["proporcion"] <= p["ic95"][1]
    assert "NO es exactitud" in r["nota"] and r["modelo"]["revision"] == cargar_clasificacion().modelos["e5"].revision
    assert "exactitud" not in " ".join(k for k in r if k != "nota")


def test_escribir_seccion_conserva_las_demas_secciones(tmp_path) -> None:
    ruta = tmp_path / "reporte.json"
    ruta.write_text('{"ruido": {"x": 1}}', encoding="utf-8")
    clasificacion.escribir_seccion(ruta, "clasificacion", {"y": 2})
    import json

    assert json.loads(ruta.read_text(encoding="utf-8")) == {"ruido": {"x": 1}, "clasificacion": {"y": 2}}


# ------------------------------------------------------------------ filtro de ruido por similitud con un prototipo (D-84)


NOTICIAS_PANAMA = [
    _fila("NOT-1", "El gobierno panameño anuncia una medida en Panamá"),
    _fila("NOT-2", "Zzz qqq xxx sin relacion alguna"),                               # sin similitud con los prototipos
    _fila("NOT-3", "Zzz qqq xxx sin relacion alguna pero regional", regional=True),   # alcance regional: nunca se marca
    _fila("NOT-4", "Zzz qqq xxx ya marcada", es_ruido=True, motivo="fuera_de_temas"),
]


def test_con_el_filtro_inactivo_solo_se_guarda_la_senal(tmp_path) -> None:
    ruta, _, _, _ = _correr(tmp_path, NOTICIAS_PANAMA, activo=False, umbral=0.99)
    filas = {r[0]: r for r in _leer(ruta, "SELECT id_noticia, es_ruido, motivo_ruido, similitud_panama, ruido_similitud FROM noticias")}
    assert all(f[3] is not None for f in filas.values())                  # la señal se guarda siempre
    assert [filas[i][1] for i in ("NOT-1", "NOT-2", "NOT-3", "NOT-4")] == [False, False, False, True]
    assert all(f[4] is None for f in filas.values())


def test_el_filtro_activo_marca_lo_poco_parecido_y_respeta_el_alcance_regional(tmp_path) -> None:
    ruta, _, _, _ = _correr(tmp_path, NOTICIAS_PANAMA, activo=True, umbral=0.3)
    f = {r[0]: r for r in _leer(ruta, "SELECT id_noticia, es_ruido, motivo_ruido, ruido_similitud, tema_clasificado FROM noticias")}
    assert f["NOT-1"][1] is False and f["NOT-1"][4] is not None             # se parece al prototipo: se clasifica
    assert (f["NOT-2"][1], f["NOT-2"][2], f["NOT-2"][3]) == (True, "no_es_panama", True)
    assert f["NOT-2"][4] is None                                             # lo marcado no se clasifica
    assert f["NOT-3"][1] is False and f["NOT-3"][3] is None                  # regional: no es ruido (D-84)
    assert (f["NOT-4"][1], f["NOT-4"][2], f["NOT-4"][3]) == (True, "fuera_de_temas", None)  # no pisa el motivo de la limpieza
    assert len(f) == 4                                                       # marcar, no borrar


def test_apagar_el_filtro_deshace_las_marcas_de_la_corrida_anterior(tmp_path) -> None:
    ruta, _, cfg, ruido = _correr(tmp_path, NOTICIAS_PANAMA, activo=True, umbral=0.3)
    assert _leer(ruta, "SELECT es_ruido FROM noticias WHERE id_noticia = 'NOT-2'") == [(True,)]
    apagado = ruido.model_copy(update={"similitud_prototipo": ruido.similitud_prototipo.model_copy(update={"activo": False})})
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, apagado, temas_de_prueba(), emb, "A", REGLAS)
    assert _leer(ruta, "SELECT es_ruido, motivo_ruido FROM noticias WHERE id_noticia = 'NOT-2'") == [(False, None)]
    assert _leer(ruta, "SELECT es_ruido, motivo_ruido FROM noticias WHERE id_noticia = 'NOT-4'") == [(True, "fuera_de_temas")]


# ------------------------------------------------------------------ CLI y sin internet


def test_el_cli_falla_con_claridad_si_no_hay_base(tmp_path) -> None:
    assert clasificacion.main(["--base", str(tmp_path / "no_existe.duckdb")]) == 1


def _modelo_en_cache() -> bool:
    cfg = cargar_clasificacion()
    carpeta = RAIZ / cfg.carpetas.modelos
    return carpeta.exists() and any(carpeta.glob("models--intfloat--multilingual-e5-small"))


@pytest.mark.skipif(not _modelo_en_cache(), reason="el modelo no está descargado todavía (primera descarga con internet)")
def test_el_modelo_funciona_sin_internet_despues_de_la_primera_descarga(tmp_path) -> None:
    """Un proceso nuevo con HF_HUB_OFFLINE=1 carga el modelo de la caché local y devuelve vectores normalizados."""
    codigo = (
        "from src import embeddings; import numpy as np;"
        "e = embeddings.crear(usar_cache=False);"
        "v = e.codificar(['Sismo sacude Chiriquí', 'El Canal reduce tránsitos'], 'titular');"
        "assert v.shape == (2, 384) and abs(float(np.linalg.norm(v[0])) - 1) < 1e-4; print('OK')"
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONPATH": str(RAIZ)}
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=env, cwd=RAIZ, timeout=300)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-800:]
