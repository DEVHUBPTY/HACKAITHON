"""D-133 · Ayuda de pruebas para ir a la URL de una pantalla con ``AppTest`` (las páginas de la app son funciones, no archivos)."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src import interfaz as ui
from src.configuracion import cargar_interfaz


def ir_a_pantalla(at: AppTest, clave: str) -> AppTest:
    """Abre la pantalla ``clave`` por su ``url_path`` y vuelve a ejecutar. Hace una primera ejecución si la app todavía no registró sus páginas.

    ``AppTest.switch_page`` solo entiende páginas de archivo; para las de ``st.Page(función)`` se fija el hash que la sesión real usaría
    para esa URL (``_registered_pages`` es lo que ``st.navigation`` registró).
    """
    if not at._registered_pages:
        at.run()
    url = ui.url_de_pantalla(cargar_interfaz(), clave)
    at._page_hash = next(h for h, info in at._registered_pages.items() if info.get("url_pathname") == url)
    return at.run()


def url_actual(at: AppTest) -> str:
    """La ruta (``url_path``) de la página que sirvió la última ejecución (``""`` es la raíz).

    ``AppTest`` no actualiza su página al cambiar con ``st.switch_page`` dentro de la app; la app deja la página real en
    ``session_state["pantalla"]``, que sale de la navegación nativa (``st.navigation``), y de ahí sale la ruta.
    """
    return ui.url_de_pantalla(cargar_interfaz(), at.session_state["pantalla"])


def seguir(at: AppTest) -> AppTest:
    """Después de un cambio de página hecho por la app, hace que las próximas ejecuciones de ``AppTest`` se queden en esa página."""
    url = url_actual(at)
    at._page_hash = next(h for h, info in at._registered_pages.items() if info.get("url_pathname") == url)
    return at
