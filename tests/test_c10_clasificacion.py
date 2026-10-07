"""C-10 (T3): D4, la sección de la URL de TVN sube la sospecha de `fuera_de_temas`, nunca la marca por sí sola.

Decisión del dueño, C-10, 2026-10-07. La sección solo marca si el clasificador tampoco halla un tema con confianza
(`sin_tema`). Sin umbral nuevo: se usa el `umbral_sin_tema` que ya existe. La lista de secciones vive en `config/ruido.yaml`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import clasificacion, db, embeddings, limpieza
from src.configuracion import ErrorDeConfiguracion, cargar_config, cargar_ruido, ConfigRuido
from src.limpieza import Reglas
from tests.motor_falso import MotorFalso, config_de_prueba, temas_de_prueba

REGLAS = Reglas.desde_config()
RAIZ = Path(__file__).resolve().parent.parent
SIN_TEMA_TEXTO = "Zzz qqq xxx"      # vocabulario disjunto de los 6 temas de prueba: queda bajo el umbral de la prueba
CON_TEMA_TEXTO = "Fuerte sismo temblor lluvias inundaciones"


def _fila(id_: str, titulo: str, url: str, es_ruido: bool = False, motivo: str | None = None) -> dict:
    return {
        "id_noticia": id_, "titulo": titulo, "url": url, "url_canonica": url, "medio": "TVN", "tipo_firma": "sin firma",
        "tema": "economia", "descripcion": None, "titulo_original": titulo, "titulo_limpio": titulo,
        "es_ruido": es_ruido, "motivo_ruido": motivo, "alcance_regional": False,
    }


def _tvn(seccion: str, id_: str = "x") -> str:
    return f"https://www.tvn-2.com/{seccion}/{id_}/nota"


def _cfg():
    """Configuración de prueba con un umbral_sin_tema alto (0.3): lo que no comparte vocabulario queda sin tema."""
    cfg = config_de_prueba()
    modelo = cfg.modelos[cfg.modelo_activo]
    umbrales = {m: u.model_copy(update={"umbral_sin_tema": 0.3}) for m, u in modelo.umbrales.items()}
    modelos = {**cfg.modelos, cfg.modelo_activo: modelo.model_copy(update={"umbrales": umbrales})}
    return cfg.model_copy(update={"modelos": modelos})


def _correr(tmp_path: Path, filas: list[dict]) -> Path:
    ruta = tmp_path / "senales.duckdb"
    db.guardar_todo(ruta, {"noticias": filas})
    cfg = _cfg()
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, cargar_ruido(), temas_de_prueba(), emb, "A", REGLAS)
    return ruta


def _leer(ruta: Path) -> dict[str, tuple]:
    con = db.conectar(ruta, solo_lectura=True)
    try:
        sql = "SELECT id_noticia, es_ruido, motivo_ruido, tema_clasificado FROM noticias"
        return {r[0]: r[1:] for r in con.execute(sql).fetchall()}
    finally:
        con.close()


# ------------------------------------------------------------------ configuración


def test_d4_las_secciones_sospechosas_viven_en_ruido_yaml() -> None:
    secciones = cargar_ruido().fuera_de_temas.secciones_sospechosas
    assert {"deportes", "entretenimiento", "cultura"} <= set(secciones)


@pytest.mark.parametrize("entrada", ["/deportes/", "Deportes", "", "deportes/futbol", "deportes deportes"])
def test_d4_una_seccion_mal_escrita_o_repetida_se_rechaza(tmp_path: Path, entrada: str) -> None:
    ruido = cargar_ruido()
    secciones = [*ruido.fuera_de_temas.secciones_sospechosas, entrada]
    datos = ruido.model_dump()
    datos["fuera_de_temas"]["secciones_sospechosas"] = secciones
    with pytest.raises(ValueError):
        ConfigRuido.model_validate(datos)


def test_d4_la_clave_es_obligatoria_en_el_yaml(tmp_path: Path) -> None:
    carpeta = tmp_path / "config"
    carpeta.mkdir()
    texto = (RAIZ / "config" / "ruido.yaml").read_text(encoding="utf-8")
    lineas = [l for l in texto.splitlines() if not l.strip().startswith("secciones_sospechosas")]
    (carpeta / "ruido.yaml").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    with pytest.raises(ErrorDeConfiguracion):
        cargar_config("ruido", ConfigRuido, carpeta)


# ------------------------------------------------------------------ la sección sola solo sospecha


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        (_tvn("deportes"), True),
        (_tvn("entretenimiento"), True),
        (_tvn("cultura"), True),
        (_tvn("economia"), False),
        (_tvn("contenido-exclusivo"), False),
        ("https://otro-medio.com/deportes/nota", False),       # solo el dominio de TVN tiene secciones que valgan
        ("https://www.tvn-2.com/", False),
    ],
)
def test_d4_la_seccion_sospechosa_solo_aplica_a_tvn(url: str, esperado: bool) -> None:
    assert limpieza.seccion_sospechosa_fuera_de_temas(_fila("NOT-1", "x", url), REGLAS) is esperado


def test_d4_la_limpieza_no_marca_por_la_seccion_sola() -> None:
    fila = _fila("NOT-1", "Plan para el ordenamiento del puerto", _tvn("deportes"))
    assert limpieza.motivo_ruido(fila, fila["titulo_limpio"], REGLAS) is None


# ------------------------------------------------------------------ sección sospechosa Y sin tema


def test_d4_seccion_sospechosa_y_sin_tema_se_marca_fuera_de_temas(tmp_path: Path) -> None:
    ruta = _correr(tmp_path, [_fila("NOT-1", SIN_TEMA_TEXTO, _tvn("deportes"))])
    assert _leer(ruta)["NOT-1"] == (True, "fuera_de_temas", None)


def test_d4_seccion_sospechosa_pero_con_tema_confiable_se_conserva_y_se_clasifica(tmp_path: Path) -> None:
    ruta = _correr(tmp_path, [_fila("NOT-1", CON_TEMA_TEXTO, _tvn("entretenimiento"))])
    assert _leer(ruta)["NOT-1"] == (False, None, "eventos_naturales")


def test_d4_sin_tema_en_una_seccion_normal_no_se_marca(tmp_path: Path) -> None:
    ruta = _correr(tmp_path, [_fila("NOT-1", SIN_TEMA_TEXTO, _tvn("economia"))])
    assert _leer(ruta)["NOT-1"] == (False, None, "sin_tema")


def test_d4_el_dominio_ajeno_no_se_marca_aunque_la_ruta_diga_deportes(tmp_path: Path) -> None:
    ruta = _correr(tmp_path, [_fila("NOT-1", SIN_TEMA_TEXTO, "https://otro-medio.com/deportes/nota")])
    assert _leer(ruta)["NOT-1"] == (False, None, "sin_tema")


def test_d4_la_marca_se_deshace_si_la_seccion_deja_de_ser_sospechosa(tmp_path: Path) -> None:
    ruta = _correr(tmp_path, [_fila("NOT-1", SIN_TEMA_TEXTO, _tvn("deportes"))])
    assert _leer(ruta)["NOT-1"][1] == "fuera_de_temas"
    ruido = cargar_ruido()
    sin_secciones = ruido.model_copy(
        update={"fuera_de_temas": ruido.fuera_de_temas.model_copy(update={"secciones_sospechosas": ["cultura"]})}
    )
    cfg = _cfg()
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    reglas = Reglas(sin_secciones, *_resto_de_reglas())
    clasificacion.aplicar_a_base(ruta, cfg, sin_secciones, temas_de_prueba(), emb, "A", reglas)
    assert _leer(ruta)["NOT-1"] == (False, None, "sin_tema")


def test_d4_no_pisa_el_motivo_que_ya_puso_la_limpieza(tmp_path: Path) -> None:
    fila = _fila("NOT-1", SIN_TEMA_TEXTO, _tvn("deportes"), es_ruido=True, motivo="no_es_noticia")
    assert _leer(_correr(tmp_path, [fila]))["NOT-1"] == (True, "no_es_noticia", None)


def test_d4_la_marca_por_la_seccion_es_estable_en_una_segunda_corrida(tmp_path: Path) -> None:
    ruta = _correr(tmp_path, [_fila("NOT-1", SIN_TEMA_TEXTO, _tvn("deportes"))])
    cfg = _cfg()
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, cargar_ruido(), temas_de_prueba(), emb, "A", REGLAS)
    assert _leer(ruta)["NOT-1"] == (True, "fuera_de_temas", None)


COLUMNAS_TEMA = (
    "tema_clasificado", "tema_similitud", "subtema_clasificado", "tema_secundario", "tema_secundario_similitud",
    "tema_baseline",
)


def test_d4_al_marcar_por_la_seccion_en_una_segunda_corrida_no_queda_ningun_campo_de_tema_anterior(tmp_path: Path) -> None:
    """R3-d4-stale-tema-fields: la nota tenía tema en la corrida 1 y cae a sin_tema en la 2; no conserva el tema viejo."""
    ruta = _correr(tmp_path, [_fila("NOT-1", CON_TEMA_TEXTO, _tvn("deportes"))])
    assert _leer(ruta)["NOT-1"] == (False, None, "eventos_naturales")
    cfg = _cfg()
    modelo = cfg.modelos[cfg.modelo_activo]
    umbrales = {m: u.model_copy(update={"umbral_sin_tema": 0.99}) for m, u in modelo.umbrales.items()}
    cfg = cfg.model_copy(update={"modelos": {**cfg.modelos, cfg.modelo_activo: modelo.model_copy(update={"umbrales": umbrales})}})
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, cargar_ruido(), temas_de_prueba(), emb, "A", REGLAS)
    con = db.conectar(ruta, solo_lectura=True)
    try:
        fila = con.execute(
            f"SELECT es_ruido, motivo_ruido, {', '.join(COLUMNAS_TEMA)} FROM noticias WHERE id_noticia = 'NOT-1'"
        ).fetchone()
    finally:
        con.close()
    assert fila == (True, "fuera_de_temas", *([None] * len(COLUMNAS_TEMA)))


def test_d4_el_ruido_por_palabras_clave_en_seccion_sospechosa_no_se_deshace_al_volver_a_correr(tmp_path: Path) -> None:
    """R3-d4-keyword-guard-untested: la limpieza ya la marcó por palabras clave; la marca previa NO es de la sección."""
    fila = _fila("NOT-1", "Fútbol: selección nacional gana el torneo", _tvn("deportes"))
    assert limpieza.motivo_ruido(fila, fila["titulo_limpio"], REGLAS) == "fuera_de_temas"
    fila.update(es_ruido=True, motivo_ruido="fuera_de_temas")
    assert clasificacion.marca_previa_por_seccion(fila, REGLAS) is False
    ruta = _correr(tmp_path, [fila])
    assert _leer(ruta)["NOT-1"] == (True, "fuera_de_temas", None)
    cfg = _cfg()
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, cargar_ruido(), temas_de_prueba(), emb, "A", REGLAS)
    assert _leer(ruta)["NOT-1"] == (True, "fuera_de_temas", None)


def _resto_de_reglas() -> tuple:
    from src.configuracion import cargar_fuentes, cargar_normalizacion, cargar_restricciones

    return cargar_restricciones(), cargar_fuentes(), cargar_normalizacion()
