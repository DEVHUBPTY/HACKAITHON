"""D-120: la excepción regional (D-84) exige evidencia de impacto en Panamá para los medios no panameños."""

from src import limpieza
from src.configuracion import cargar_fuentes, cargar_normalizacion, cargar_restricciones, cargar_ruido

REGLAS = limpieza.Reglas.desde_config()
TRUMP = "Trump streicht Europa-Hilfe, lenkt Millionen nach Lateinamerika"
EL_NINO = "Intensifying El Nino deepens economic risks across LatAm"


def _fila(titulo: str, **campos: str | None) -> dict:
    base = {
        "titulo": titulo, "url": "https://ejemplo.example/n/1", "url_canonica": "https://ejemplo.example/n/1",
        "medio": "Ejemplo", "dominio": "ejemplo.example", "origen": "GDELT", "pais_medio": "Alemania",
        "fecha_deteccion": "2026-10-01T10:00:00Z", "fecha_publicacion": None, "fecha_extraccion": "2026-10-06T10:00:00Z",
        "descripcion": None, "categoria_fuente": None,
    }  # fmt: skip
    return base | campos


def test_medio_internacional_regional_sin_panama_ni_fenomeno_es_no_es_panama() -> None:
    r = limpieza.evaluar(_fila(TRUMP), REGLAS)
    assert r.es_ruido is True and r.motivo_ruido == "no_es_panama"


def test_medio_internacional_con_el_nino_regional_se_conserva_con_alcance_regional() -> None:
    r = limpieza.evaluar(_fila(EL_NINO, pais_medio="Estados Unidos"), REGLAS)
    assert r.es_ruido is False and r.motivo_ruido is None and r.alcance_regional is True


def test_medio_panameno_regional_sin_nombrar_panama_no_es_ruido() -> None:
    for campos in ({"pais_medio": "Panamá"}, {"origen": "TVN RSS", "pais_medio": None}):
        r = limpieza.evaluar(_fila("Crece el comercio en Latinoamérica", **campos), REGLAS)
        assert r.es_ruido is False and r.alcance_regional is True, campos


def test_medio_internacional_que_nombra_panama_no_lo_afecta_esta_regla() -> None:
    r = limpieza.evaluar(_fila("Trump redirige ayuda a Latinoamérica y a Panamá"), REGLAS)
    assert r.es_ruido is False and r.alcance_regional is True


def test_migracion_y_rutas_maritimas_son_fenomenos_con_impacto() -> None:
    for t in ("Migrantes cruzan hacia Centroamérica", "Shipping routes shift across Latin America"):
        assert limpieza.evaluar(_fila(t), REGLAS).es_ruido is False, t


def test_la_lista_de_fenomenos_sale_de_la_configuracion() -> None:
    """Cambiar `fenomenos_regionales_con_impacto` cambia el resultado: no hay lista fija en el código."""
    ruido = cargar_ruido()
    vacia = ruido.model_copy(update={"panama": ruido.panama.model_copy(update={"fenomenos_regionales_con_impacto": ["a^"]})})
    reglas = limpieza.Reglas(vacia, cargar_restricciones(), cargar_fuentes(), cargar_normalizacion())
    assert limpieza.evaluar(_fila(EL_NINO), REGLAS).es_ruido is False
    assert limpieza.evaluar(_fila(EL_NINO), reglas).motivo_ruido == "no_es_panama"
