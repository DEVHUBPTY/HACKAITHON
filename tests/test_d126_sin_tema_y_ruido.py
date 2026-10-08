"""D-126: ``sin_tema`` pasa a ser ruido ``fuera_de_temas`` y las reglas de ruido cubren las filtraciones de la etapa 2."""

import duckdb
import pytest

from src import clasificacion, db, embeddings
from src.configuracion import cargar_ruido
from src.limpieza import Reglas, evaluar
from tests.motor_falso import MotorFalso, config_de_prueba, temas_de_prueba
from tests.test_clasificacion import _base, _fila as _fila_db
from tests.test_ruido import _fila

REGLAS = Reglas.desde_config()


def _tvn(titulo: str, seccion: str) -> dict:
    url = f"https://www.tvn-2.com/{seccion}/nota_1_1.html"
    return _fila(titulo, url=url, url_canonica=url, medio="TVN", dominio="tvn-2.com", origen="TVN RSS", pais_medio="Panamá")


# ------------------------------------------------------------------ las tres filtraciones ahora son ruido


@pytest.mark.parametrize(
    ("titulo", "seccion"),
    [
        ("¡Noche de diva! Ale Merod gana el octavo show de Tu Cara Me Suena como Jennifer Lopez", "tu-cara-me-suena"),
        ("Panamá condena atentados del 7 de octubre y pide paz entre israelíes y palestinos", "mundo"),
        ("Gianmatteo Rousseau | Piloto panameño que triunfa en el extranjero", "tvmax"),
    ],
)
def test_las_tres_filtraciones_son_fuera_de_temas(titulo: str, seccion: str) -> None:
    assert evaluar(_tvn(titulo, seccion), REGLAS).motivo_ruido == "fuera_de_temas"


def test_politica_internacional_no_depende_de_la_seccion() -> None:
    titulo = "Panamá condena atentados del 7 de octubre y pide paz entre israelíes y palestinos"
    assert evaluar(_tvn(titulo, "nacionales"), REGLAS).motivo_ruido == "fuera_de_temas"


# ------------------------------------------------------------------ lo que NO debe ser ruido


@pytest.mark.parametrize(
    ("titulo", "seccion"),
    [
        ("Pilotos solicitan al Aeropuerto de Tocumen fortalecer controles por riesgo de aves durante temporada migratoria", "nacionales"),
        ("Pilotos solicitan al Aeropuerto de Tocumen fortalecer controles por riesgo de aves", "tvmax"),   # incluso en sección dudosa
        ("Panamá apunta a salir de la lista fiscal de la Unión Europea, pero aún enfrenta una revisión clave en 2027", "economia"),
        ("Panamá condena ataque con sanciones que afectan al Canal de Panamá", "mundo"),
        ("Aumenta la migración irregular por el Darién tras la guerra", "mundo"),
        ("Showroom de autos eléctricos abre en Albrook Mall", "nacionales"),                              # «show» solo como palabra completa
    ],
)
def test_lo_que_toca_a_panama_o_a_un_piloto_de_avion_no_es_ruido(titulo: str, seccion: str) -> None:
    assert evaluar(_tvn(titulo, seccion), REGLAS).motivo_ruido is None


def test_piloto_de_carreras_es_deporte_aunque_no_este_en_una_seccion_dudosa() -> None:
    assert evaluar(_tvn("Piloto panameño correrá en la IndyCar", "nacionales"), REGLAS).motivo_ruido == "fuera_de_temas"


# ------------------------------------------------------------------ sin_tema -> ruido fuera_de_temas


FILAS = [
    _fila_db("NOT-1", "Inflacion sube y precios de la canasta suben"),
    _fila_db("NOT-2", "Zzz qqq xxx sin ninguna palabra conocida"),
]


def _correr(tmp_path, activo: bool = True, umbral: float = 0.2):  # umbral entre la similitud de NOT-2 (0.07) y la de NOT-1 (0.43) con el codificador de prueba
    cfg = config_de_prueba()
    modelo = cfg.modelos[cfg.modelo_activo]
    umbrales = {m: u.model_copy(update={"umbral_sin_tema": umbral}) for m, u in modelo.umbrales.items()}
    cfg = cfg.model_copy(update={"modelos": {**cfg.modelos, cfg.modelo_activo: modelo.model_copy(update={"umbrales": umbrales})}})
    ruido = cargar_ruido()
    ruido = ruido.model_copy(update={"sin_tema_como_ruido": ruido.sin_tema_como_ruido.model_copy(update={"activo": activo})})
    ruta = _base(tmp_path, FILAS)
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, ruido, temas_de_prueba(), emb, "A", REGLAS)
    return ruta, cfg, ruido


def _leer(ruta, sql):
    con = db.conectar(ruta, solo_lectura=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


SQL = "SELECT id_noticia, es_ruido, motivo_ruido, ruido_sin_tema, tema_clasificado FROM noticias ORDER BY 1"


def test_sin_tema_se_marca_ruido_y_se_conserva(tmp_path) -> None:
    ruta, _, _ = _correr(tmp_path)
    filas = {r[0]: r for r in _leer(ruta, SQL)}
    assert filas["NOT-1"][1:4] == (False, None, None) and filas["NOT-1"][4] == "economia"
    assert filas["NOT-2"][1:5] == (True, "fuera_de_temas", True, "sin_tema")   # ruido, no borrado, con su tema sin_tema
    assert len(filas) == len(FILAS)


def test_el_interruptor_apagado_deja_el_sin_tema_como_antes(tmp_path) -> None:
    ruta, _, _ = _correr(tmp_path, activo=False)
    filas = {r[0]: r for r in _leer(ruta, SQL)}
    assert filas["NOT-2"][1:5] == (False, None, None, "sin_tema")


def test_reclasificar_deshace_la_marca_de_la_corrida_anterior(tmp_path) -> None:
    ruta, cfg, ruido = _correr(tmp_path)
    apagado = ruido.model_copy(update={"sin_tema_como_ruido": ruido.sin_tema_como_ruido.model_copy(update={"activo": False})})
    emb = embeddings.crear(cfg, motor=MotorFalso(), raiz=tmp_path)
    clasificacion.aplicar_a_base(ruta, cfg, apagado, temas_de_prueba(), emb, "A", REGLAS)
    assert {r[0]: r for r in _leer(ruta, SQL)}["NOT-2"][1:4] == (False, None, None)


def test_un_grupo_sin_ruido_nunca_tiene_tema_sin_tema(tmp_path) -> None:
    """Las que no son ruido no llevan ``sin_tema``: la agrupación solo ve las no ruido."""
    ruta, _, _ = _correr(tmp_path)
    assert _leer(ruta, "SELECT count(*) FROM noticias WHERE NOT es_ruido AND tema_clasificado = 'sin_tema'") == [(0,)]


def test_en_la_base_real_ningun_grupo_tiene_sin_tema() -> None:
    from src.configuracion import RAIZ

    ruta = RAIZ / "data" / "senales.duckdb"
    if not ruta.exists():
        pytest.skip("no hay data/senales.duckdb (se genera con el pipeline)")
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        grupos = {r[0] for r in con.execute("SELECT tema_clasificado FROM grupos").fetchall()}
        residuo = con.execute("SELECT count(*) FROM noticias WHERE NOT es_ruido AND tema_clasificado = 'sin_tema'").fetchone()[0]
    finally:
        con.close()
    assert "sin_tema" not in grupos and None not in grupos
    assert residuo == 0
