"""X15: observaciones de la revisión independiente del PR #13 (E1-07). Cada prueba fija un hallazgo."""

import csv
import re
from pathlib import Path

import numpy as np
import pytest

from eval import clasificacion as evalclas, metricas
from src import baseline, clasificacion, db, embeddings
from src.baseline import SIN_TEMA
from src.configuracion import cargar_clasificacion, cargar_ruido, cargar_temas
from src.limpieza import Reglas, plano
from tests.motor_falso import MotorFalso, config_de_prueba, temas_de_prueba
from tests.test_clasificacion import FILAS, _base, _fila, _leer

RAIZ = Path(__file__).resolve().parent.parent
TEMAS = cargar_temas()
CLASES = [*TEMAS.temas, SIN_TEMA]
REGLAS = Reglas.desde_config()
CRITERIO = cargar_clasificacion().criterio_ab.model_copy(update={"remuestreos": 200})


# ------------------------------------------------------------------ H1: clases de la predicción


def test_h1_una_prediccion_de_una_clase_ausente_de_las_etiquetas_no_rompe_las_metricas() -> None:
    real = ["economia", "economia", "turismo"]
    pred = ["economia", SIN_TEMA, "turismo"]               # sin_tema se predice pero no está en las etiquetas
    f1_economia, f1_turismo = 2 / 3, 1.0
    assert metricas.macro_f1(real, pred, CLASES) == pytest.approx((f1_economia + f1_turismo) / 2)   # solo clases con soporte
    assert metricas.matriz_confusion(real, pred, CLASES)[CLASES.index("economia")][CLASES.index(SIN_TEMA)] == 1
    r = metricas.macro_f1_con_ic(real, pred, CLASES, CRITERIO)
    assert r["macro_f1"] == pytest.approx((f1_economia + f1_turismo) / 2, abs=1e-4) and r["ic95"] is not None
    d = metricas.diferencia_con_ic(real, real, pred, CLASES, CRITERIO)
    assert d["diferencia_macro_f1"] is not None
    c = metricas.aplicar_criterio(real * 10, real * 10, pred * 10, CLASES, CRITERIO)
    assert c["decision"] in {"A", "B"}


def test_h1_una_clase_desconocida_se_rechaza_con_un_error_claro() -> None:
    with pytest.raises(ValueError, match="fuera de clases"):
        metricas.macro_f1(["a"], ["zzz"], ["a", "b"])


def test_h1_la_clase_predicha_sin_soporte_no_entra_en_el_promedio_pero_resta_recall() -> None:
    real, pred = ["a"] * 4, ["a", "a", "a", "x"]
    assert metricas.macro_f1(real, pred, ["a", "x"]) == pytest.approx(2 * 3 / (2 * 3 + 0 + 1))   # solo "a": 6/7
    m = metricas.por_clase(real, pred, ["a", "x"], 1.96)
    assert m["x"]["soporte"] == 0 and m["x"]["predichos"] == 1 and m["x"]["precision"]["n"] == 0


def test_h1_evaluar_configuracion_acepta_predicciones_fuera_de_las_clases_con_soporte() -> None:
    reales = ["economia", "turismo", "economia"]
    preds = [evalclas.Prediccion(p, None, 0.9, None) for p in ("economia", SIN_TEMA, "economia")]
    r = evalclas.evaluar_configuracion(["1", "2", "3"], ["a", "b", "c"], reales, [None] * 3, preds, CLASES, cargar_clasificacion(), 1.96)
    assert r["exactitud_principal"]["n"] == 2 and r["macro_f1"]["macro_f1"] is not None
    assert r["clases_en_macro_f1"] == ["economia", "turismo"]


# ------------------------------------------------------------------ H2: formato real de E1-06


COLUMNAS_E106 = ("id_noticia", "titulo", "tema_principal", "tema_secundario", "ruido", "grupo", "alcance_regional", "nota",
                 "etiquetado_por", "fecha_etiquetado", "estrato", "peso_muestreo", "n_etiquetadores")


def _consolidado(ruta: Path, filas: list[dict]) -> Path:
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_E106)
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in COLUMNAS_E106})
    return ruta


def _fila_e106(id_, tema="", ruido="ninguno", estrato="no_ruido", peso="2.0"):
    return {"id_noticia": id_, "tema_principal": tema, "ruido": ruido, "estrato": estrato, "peso_muestreo": peso, "n_etiquetadores": "1"}


ETIQUETAS_E106 = [
    _fila_e106("NOT-1", "economia"),
    _fila_e106("NOT-2", "logistica"),
    _fila_e106("NOT-3", "turismo"),
    _fila_e106("NOT-4", "eventos_naturales"),
    _fila_e106("NOT-5", "regulacion"),
    _fila_e106("NOT-6", "", ruido="no_es_noticia"),                                  # una persona lo marcó ruido: abstención correcta
    _fila_e106("NOT-7", "", ruido="fuera_de_temas", estrato="ruido", peso="10.0"),    # y el sistema también
]


def _evaluar_e106(tmp_path, etiquetas=ETIQUETAS_E106):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ruta = _consolidado(tmp_path / "etiquetas.csv", etiquetas)
    return evalclas.evaluar_etiquetas(ruta, _base(tmp_path, FILAS), "tema_principal", config_de_prueba(), TEMAS, ["e5"], {"e5": MotorFalso()})


def test_h2_no_es_noticia_cuenta_como_fuera_de_los_temas() -> None:
    assert "no_es_noticia" in evalclas.FUERA_DE_LOS_TEMAS
    assert evalclas.tema_a_id("no_es_noticia", TEMAS) == SIN_TEMA


def test_h2_un_titular_marcado_como_ruido_es_abstencion_dorada_no_sin_etiquetar(tmp_path) -> None:
    etiquetas = evalclas.leer_etiquetas(_consolidado(tmp_path / "e.csv", ETIQUETAS_E106), "tema_principal", TEMAS)
    assert etiquetas["NOT-6"].tema == SIN_TEMA and etiquetas["NOT-7"].tema == SIN_TEMA
    assert etiquetas["NOT-1"].tema == "economia"
    assert (etiquetas["NOT-7"].peso, etiquetas["NOT-7"].estrato) == (10.0, "ruido")
    assert len(etiquetas) == 7


def test_h2_una_fila_sin_tema_ni_ruido_si_es_sin_etiquetar(tmp_path) -> None:
    etiquetas = evalclas.leer_etiquetas(_consolidado(tmp_path / "e.csv", [_fila_e106("NOT-1", ""), _fila_e106("NOT-2", "economia")]), "tema_principal", TEMAS)
    assert set(etiquetas) == {"NOT-2"}


def test_h2_el_clasificador_se_mide_contra_la_abstencion_humana(tmp_path) -> None:
    r = _evaluar_e106(tmp_path)
    assert r["conteo"]["evaluados"] == 6                                  # NOT-7 ya lo descartó el sistema (ruido)
    base = r["configuraciones"]["baseline"]
    assert base["exactitud_principal"]["n"] == 5 and base["exactitud_principal"]["de"] == 6      # NOT-6: predice un tema, la persona dice ruido
    assert base["por_tema"][SIN_TEMA]["soporte"] == 1


def test_h2_se_reporta_ponderado_con_peso_muestreo_y_sin_ponderar(tmp_path) -> None:
    r = _evaluar_e106(tmp_path)
    pipe = r["pipeline"]                                                  # sistema completo: el ruido del filtro cuenta como sin_tema
    assert pipe["conteo"]["evaluados"] == 7
    base = pipe["configuraciones"]["baseline"]
    assert base["sin_ponderar"]["exactitud_principal"]["n"] == 6 and base["sin_ponderar"]["exactitud_principal"]["de"] == 7
    # aciertos 5 × 2.0 + 1 × 10.0 = 20 de un peso total 6 × 2.0 + 10.0 = 22
    pond = base["ponderado"]["exactitud_principal"]
    assert pond["suma_pesos_aciertos"] == pytest.approx(20.0) and pond["suma_pesos"] == pytest.approx(22.0)
    assert pond["proporcion"] == pytest.approx(20 / 22, abs=1e-4)
    assert base["ponderado"]["macro_f1"]["macro_f1"] is not None
    assert "ponderado" in r["configuraciones"]["baseline"]                # también para el clasificador solo


def test_h2_los_pesos_invalidos_se_rechazan(tmp_path) -> None:
    malas = [_fila_e106("NOT-1", "economia", peso="0"), _fila_e106("NOT-2", "economia", peso="abc")]
    for fila in malas:
        with pytest.raises(ValueError, match="peso_muestreo"):
            evalclas.leer_etiquetas(_consolidado(tmp_path / "m.csv", [fila]), "tema_principal", TEMAS)


def test_h2_el_formato_de_etiquetar_py_es_el_que_se_lee() -> None:
    from eval import etiquetar

    assert {"tema_principal", "ruido", "estrato", "peso_muestreo"} <= set(etiquetar.COLUMNAS_CONSOLIDADO)
    assert evalclas.COLUMNA_RUIDO == "ruido" and evalclas.COLUMNA_PESO == "peso_muestreo"


# ------------------------------------------------------------------ H3: honestidad del baseline


EXTENSION_DE_LA_REVISION = {"asep", "asamblea", "homicidio", "aerolinea"}


def test_h3_el_baseline_de_la_guia_solo_usa_terminos_de_la_guia() -> None:
    guia = plano((RAIZ / "docs" / "guia_temas.md").read_text(encoding="utf-8").split("## Casos difíciles")[0])
    for tema, grupos in cargar_clasificacion().baseline.palabras_clave.items():
        assert grupos.guia, tema
        for termino in grupos.guia:
            assert re.search(r"\b" + re.escape(plano(termino)), guia), f"{tema}: {termino!r} no está en la guía (fuera de los casos difíciles)"


def test_h3_los_terminos_de_la_revision_no_estan_en_la_variante_de_la_guia() -> None:
    bl = cargar_clasificacion().baseline
    guia = {plano(t) for g in bl.palabras_clave.values() for t in g.guia}
    ext = {plano(t) for g in bl.palabras_clave.values() for t in g.extension}
    assert not (EXTENSION_DE_LA_REVISION & guia) and EXTENSION_DE_LA_REVISION <= ext


def test_h3_las_dos_variantes_dan_resultados_distintos_donde_importa() -> None:
    solo_guia, ampliado = baseline.Baseline(variante="guia"), baseline.Baseline(variante="ampliado")
    assert solo_guia.clasificar("ASEP aprueba aumento de la tarifa eléctrica").principal != "regulacion"
    assert ampliado.clasificar("ASEP aprueba aumento de la tarifa eléctrica").principal == "regulacion"
    assert ampliado.clasificar("Policía reporta aumento de homicidios").principal == "servicios_publicos"
    with pytest.raises(ValueError, match="variante"):
        baseline.Baseline(variante="otra")


def test_h3_el_reporte_de_casos_dificiles_trae_el_baseline_con_y_sin_la_extension() -> None:
    r = evalclas.evaluar_casos_dificiles(cargar_clasificacion(), TEMAS, ["e5"], {"e5": MotorFalso(), "minilm": MotorFalso()}, verificar_fuga=False)
    assert {"baseline", "baseline_ampliado", "e5/A", "e5/B"} <= set(r["configuraciones"])


def test_h3_la_documentacion_no_afirma_lo_que_no_se_puede_demostrar() -> None:
    for archivo in ("docs/clasificacion.md", "docs/parametros.md", "config/clasificacion.yaml"):
        texto = (RAIZ / archivo).read_text(encoding="utf-8").lower()
        assert "sin mirar los casos" not in texto and "antes de medir y sin" not in texto, archivo
    assert "baseline_ampliado" in (RAIZ / "docs" / "clasificacion.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ H4: fuga semántica


def test_h4_la_configuracion_fija_el_umbral_de_fuga_semantica() -> None:
    f = cargar_clasificacion().fuga_semantica
    assert f.modelo in cargar_clasificacion().modelos and 0 < f.umbral_coseno < 1 and f.palabras_ignoradas


def test_h4_un_ejemplo_parafraseado_de_un_caso_se_detecta(tmp_path) -> None:
    casos = evalclas.leer_casos_dificiles()
    caso = casos[0]
    temas = temas_de_prueba()
    parafraseado = temas.model_copy(deep=True)
    parafraseado.temas["economia"].ejemplos.append(type(parafraseado.temas["economia"].ejemplos[0])(titulo=caso.titular + " hoy", real=False))
    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    cfg = cargar_clasificacion().fuga_semantica
    hallazgos = evalclas.fuga_semantica(casos, parafraseado, REGLAS, emb, cfg.umbral_coseno, cfg.palabras_ignoradas)
    assert any(h.caso == caso.id and h.referencia.startswith("economia") for h in hallazgos)
    assert evalclas.fuga_semantica(casos, temas, REGLAS, emb, 0.999, cfg.palabras_ignoradas) == []


def test_h4_la_palabra_panama_no_cuenta_como_parecido(tmp_path) -> None:
    caso = evalclas.CasoDificil("CD-X", "Panamá sale de la lista", "regulacion", None, "2")
    temas = temas_de_prueba().model_copy(deep=True)
    temas.temas["turismo"].subtemas["hoteles"] = type(temas.temas["turismo"].subtemas["hoteles"])(nombre="x", prototipo="Panamá recibe más turistas")
    emb = embeddings.crear(config_de_prueba(), motor=MotorFalso(), raiz=tmp_path)
    con = evalclas.fuga_semantica([caso], temas, REGLAS, emb, 0.15, ["panama"])
    sin = evalclas.fuga_semantica([caso], temas, REGLAS, emb, 0.15, [])
    assert not any(h.referencia.endswith("hoteles") for h in con) and any(h.referencia.endswith("hoteles") for h in sin)


def _modelo_disponible(nombre: str) -> bool:
    modelo = cargar_clasificacion().modelos[nombre]
    return any((RAIZ / cargar_clasificacion().carpetas.modelos).glob("models--" + modelo.id.replace("/", "--")))


@pytest.mark.skipif(not _modelo_disponible("minilm"), reason="MiniLM no descargado")
def test_h4_ningun_ejemplo_ni_prototipo_parafrasea_un_caso_dificil() -> None:
    cfg = cargar_clasificacion()
    f = cfg.fuga_semantica
    emb = embeddings.crear(cfg, f.modelo)
    hallazgos = evalclas.fuga_semantica(evalclas.leer_casos_dificiles(), TEMAS, REGLAS, emb, f.umbral_coseno, f.palabras_ignoradas, f.excepciones_aceptadas)
    assert hallazgos == [], "; ".join(f"{h.caso}~{h.referencia} ({h.coseno:.2f})" for h in hallazgos)


@pytest.mark.skipif(not _modelo_disponible("minilm"), reason="MiniLM no descargado")
def test_h4_las_excepciones_aceptadas_son_ejemplos_reales_y_siguen_sobre_el_umbral() -> None:
    """Una excepción solo vale para un ejemplo REAL del snapshot (no se puede reescribir) y mientras siga sobre el umbral."""
    cfg = cargar_clasificacion()
    f = cfg.fuga_semantica
    pares = evalclas.pares_mas_parecidos(evalclas.leer_casos_dificiles(), TEMAS, REGLAS, embeddings.crear(cfg, f.modelo), f.palabras_ignoradas)
    por_clave = {f"{h.caso}~{h.referencia}": h for h in pares}
    assert f.excepciones_aceptadas
    for clave in f.excepciones_aceptadas:
        assert clave in por_clave and por_clave[clave].coseno >= f.umbral_coseno, f"{clave} ya no supera el umbral: quítela"
        tema, indice = re.search(r"~(\w+)\.ejemplo\[(\d+)\]", clave).groups()
        assert TEMAS.temas[tema].ejemplos[int(indice)].real, f"{clave} no es un ejemplo real: se reescribe, no se acepta"


def test_h4_los_prototipos_de_la_revision_ya_no_parafrasean_los_casos() -> None:
    prototipos = {s: st.prototipo for t in TEMAS.temas.values() for s, st in t.subtemas.items()}
    for sub, viejo in {
        "operacion_canal": "El Canal reduce tránsitos por el nivel del lago Gatún",
        "agua_potable": "Sectores de la ciudad quedan sin agua potable",
        "resoluciones_entes": "Ente regulador emite resolución sobre las tarifas de un servicio",
        "salud_publica": "Pacientes denuncian escasez de medicamentos en un hospital público",
        "educacion_publica": "Estudiantes pierden clases en escuelas públicas por una suspensión de labores",
    }.items():
        assert prototipos[sub] != viejo, sub


# ------------------------------------------------------------------ H6: el secundario guardado


def test_h6_el_tema_secundario_se_guarda_con_su_similitud(tmp_path) -> None:
    filas = [_fila("NOT-1", "canal transitos y turistas hoteles"), _fila("NOT-2", "inflacion sube precios")]
    cfg = config_de_prueba().model_copy()
    modelo = cfg.modelos[cfg.modelo_activo]
    umbrales = {m: u.model_copy(update={"margen_secundario": 1.0}) for m, u in modelo.umbrales.items()}
    cfg = cfg.model_copy(update={"modelos": {**cfg.modelos, cfg.modelo_activo: modelo.model_copy(update={"umbrales": umbrales})}})
    ruta = _base(tmp_path, filas)
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, cargar_ruido(), temas_de_prueba(), emb, "A", REGLAS)
    fila = _leer(ruta, "SELECT tema_clasificado, tema_similitud, tema_secundario, tema_secundario_similitud FROM noticias WHERE id_noticia = 'NOT-1'")[0]
    detalle = {t: s for t, s in _leer(ruta, "SELECT tema, similitud FROM similitud_tema WHERE id_noticia = 'NOT-1' AND metodo = 'A'")}
    orden = sorted(detalle, key=lambda t: -detalle[t])
    assert fila[0] == orden[0] and fila[2] == orden[1]
    assert fila[1] == pytest.approx(detalle[orden[0]]) and fila[3] == pytest.approx(detalle[orden[1]])
    assert fila[3] <= fila[1]


# ------------------------------------------------------------------ H8: reinicio transaccional


def _estado(ruta):
    return _leer(ruta, "SELECT id_noticia, es_ruido, motivo_ruido, tema_clasificado, tema_similitud, ruido_similitud FROM noticias ORDER BY 1"), \
        _leer(ruta, "SELECT count(*) FROM similitud_tema")


def _correr(ruta, cfg=None, emb=None, activo=False):
    cfg = cfg or config_de_prueba()
    ruido = cargar_ruido()
    ruido = ruido.model_copy(update={"similitud_prototipo": ruido.similitud_prototipo.model_copy(update={"activo": activo, "umbral": 0.3})})
    emb = emb or embeddings.crear(cfg, motor=MotorFalso(), raiz=ruta.parent)
    return clasificacion.aplicar_a_base(ruta, cfg, ruido, temas_de_prueba(), emb, "A", REGLAS)


def test_h8_si_faltan_requisitos_no_se_pierde_la_corrida_anterior(tmp_path) -> None:
    ruta = _base(tmp_path, FILAS)
    _correr(ruta)
    antes = _estado(ruta)
    assert antes[1][0][0] > 0
    con = db.conectar(ruta)
    con.execute("UPDATE noticias SET titulo_limpio = NULL WHERE id_noticia = 'NOT-3'")
    con.close()
    with pytest.raises(RuntimeError, match="limpieza"):
        _correr(ruta)
    assert _estado(ruta) == antes


def test_h8_una_falla_a_mitad_de_camino_deja_la_base_como_estaba(tmp_path) -> None:
    ruta = _base(tmp_path, FILAS)
    _correr(ruta, activo=True)
    antes = _estado(ruta)

    class MotorQueFalla(MotorFalso):
        def codificar(self, textos):
            raise OSError("se cayó el modelo")

    emb = embeddings.crear(config_de_prueba(), motor=MotorQueFalla(), raiz=tmp_path / "otra")
    with pytest.raises(OSError):
        _correr(ruta, emb=emb, activo=True)
    assert _estado(ruta) == antes


# ------------------------------------------------------------------ H9: IC sin redondear


def test_h9_la_decision_usa_los_limites_sin_redondear() -> None:
    assert metricas.criterio_elige_b([0.00004, 0.3], []) is True            # redondeado a 4 decimales sería 0.0 y daría A
    assert metricas.criterio_elige_b([-0.00004, 0.3], []) is False
    assert metricas.criterio_elige_b([0.1, 0.3], ["economia"]) is False
    d = metricas.diferencia_con_ic(["a", "b"] * 10, ["a", "b"] * 10, ["a", "b"] * 10, ["a", "b"], CRITERIO)
    assert "ic95_exacto" in d and "ic95" in d


def test_h9_el_ic_de_wilson_se_calcula_con_k_y_n_exactos() -> None:
    from src.carga import intervalo_wilson

    p = clasificacion.proporcion(3, 7, 1.96)
    bajo, alto = intervalo_wilson(3, 7, 1.96)
    assert p["ic95"] == [round(bajo, 4), round(alto, 4)] and p["proporcion"] == round(3 / 7, 4)
