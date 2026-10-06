"""T03 · Noticia antigua recirculada (E1-03): publicación y detección son distintas y se conservan."""

from pathlib import Path

import pytest

from src import db, normalizacion
from src.configuracion import cargar_fuentes, cargar_normalizacion

FIXTURE = Path(__file__).parent / "fixtures" / "t03_recirculada.csv"
CONFIG = cargar_normalizacion()
FUENTES = cargar_fuentes()


def _normalizar(filas: list[dict]) -> list[dict]:
    return normalizacion.normalizar_noticias(filas, [], CONFIG, FUENTES, normalizacion.Registro())


def test_el_fixture_conserva_la_fecha_de_publicacion_original() -> None:
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    assert fila["fecha_publicacion"] == "2024-03-14T15:00:00Z"
    assert fila["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    assert fila["fecha_publicacion"] != fila["fecha_deteccion"]
    assert fila["id_noticia"] == "SYN-T03-001"  # los sintéticos conservan su ID (D-63)


def test_la_noticia_antigua_no_se_trata_como_evento_nuevo() -> None:
    """Regla: detectada más de ``dias_para_recirculada`` días después de publicada = recirculada."""
    (fila,) = _normalizar(normalizacion.leer_csv(FIXTURE))
    assert fila["es_recirculada"] is True


def test_una_noticia_reciente_no_es_recirculada() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": "2025-09-28T08:00:00Z"}
    (resultado,) = _normalizar([fila])
    assert resultado["es_recirculada"] is False


def test_sin_publicacion_queda_nula_y_no_se_sustituye_por_la_deteccion() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": ""}
    (resultado,) = _normalizar([fila])
    assert resultado["fecha_publicacion"] is None
    assert resultado["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    assert resultado["es_recirculada"] is None


def test_sin_deteccion_queda_nula_y_no_se_sustituye_por_la_publicacion() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_deteccion": ""}
    (resultado,) = _normalizar([fila])
    assert resultado["fecha_deteccion"] is None
    assert resultado["fecha_publicacion"] == "2024-03-14T15:00:00Z"


def test_una_fecha_con_zona_se_convierte_a_utc() -> None:
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": "2024-03-14T10:00:00-05:00"}
    (resultado,) = _normalizar([fila])
    assert resultado["fecha_publicacion"] == "2024-03-14T15:00:00Z"


@pytest.mark.parametrize("texto", ["2024-03-14", "no es fecha", "2024-03-14T10:00:00"])
def test_una_fecha_ilegible_o_sin_zona_no_se_adivina_y_se_registra(texto: str) -> None:
    registro = normalizacion.Registro()
    fila = normalizacion.leer_csv(FIXTURE)[0] | {"fecha_publicacion": texto}
    (resultado,) = normalizacion.normalizar_noticias([fila], [], CONFIG, FUENTES, registro)
    assert resultado["fecha_publicacion"] is None
    assert [c["campo"] for c in registro.cambios] == ["fecha_publicacion"]


def test_las_dos_fechas_sobreviven_al_ida_y_vuelta_por_duckdb(tmp_path: Path) -> None:
    ruta = tmp_path / "t.duckdb"
    db.guardar_todo(ruta, {"noticias": _normalizar(normalizacion.leer_csv(FIXTURE))})
    con = db.conectar(ruta, solo_lectura=True)
    fila = db.leer_tabla(con, "noticias")[0]
    con.close()
    assert fila["fecha_publicacion"] == "2024-03-14T15:00:00Z"
    assert fila["fecha_deteccion"] == "2025-09-28T09:30:00Z"
    assert fila["es_recirculada"] is True
