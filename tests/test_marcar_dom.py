"""
Tests del JS que identifica y abre el artículo correcto — contra un DOM
falso que imita el listado del portal, sin red ni credenciales.

Reproduce el escenario que rompió un artículo publicado el 2026-08-18:
el número ya contenía un artículo con el mismo título, y el click en
'Marcar' abría el viejo.
"""

import pytest

playwright_api = pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

from amelica.portal.uploader import AmelicaUploader  # noqa: E402

TITULO = "Las cajas de ahorro comunitarias, opción al desarrollo socioeconómico"


def pagina_html(articulos):
    """articulos: lista de (id_bloque, titulo). id_bloque '' = sin id."""
    bloques = []
    for i, (bid, titulo) in enumerate(articulos):
        attr_id = f' id="{bid}"' if bid else ''
        bloques.append(f'''
          <div class="articulo"{attr_id}>
            <div class="titulo-articulo">{titulo}</div>
            <a href="#" onclick="marcado({i})">Marcar</a>
            <a href="#">Otra acción</a>
          </div>''')
    return f'''<html><body>
      <script>window.__marcados = [];
               function marcado(i) {{ window.__marcados.push(i); }}</script>
      {''.join(bloques)}
    </body></html>'''


class PaginaFalsa:
    """Envuelve una page de Playwright para poder llamar los métodos del
    uploader que solo necesitan self.page."""

    def __init__(self, page):
        self.page = page


async def _con_pagina(html, fn):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html)
            up = AmelicaUploader.__new__(AmelicaUploader)
            up.page = page
            return await fn(up, page)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_snapshot_extrae_una_clave_por_bloque():
    async def caso(up, page):
        return await up._snapshot_article_blocks()

    bloques = await _con_pagina(
        pagina_html([("art-1", "Primer artículo"), ("art-2", TITULO)]), caso)
    assert len(bloques) == 2
    assert bloques[0]["clave"] == "art-1"
    assert bloques[1]["titulo"] == TITULO
    assert all(b["clave"] for b in bloques)


@pytest.mark.asyncio
async def test_snapshot_cae_al_onclick_si_no_hay_id():
    async def caso(up, page):
        return await up._snapshot_article_blocks()

    bloques = await _con_pagina(pagina_html([("", TITULO)]), caso)
    assert bloques[0]["clave"] == "marcado(0)"


@pytest.mark.asyncio
async def test_click_por_clave_abre_el_bloque_correcto():
    """Con dos artículos homónimos, debe abrir el segundo — el nuevo — y
    NO el primero, que es el que la búsqueda por título agarraba."""
    async def caso(up, page):
        ok = await up._click_marcar_por_clave("art-nuevo")
        return ok, await page.evaluate("window.__marcados")

    ok, marcados = await _con_pagina(
        pagina_html([("art-viejo", TITULO), ("art-nuevo", TITULO)]), caso)
    assert ok
    assert marcados == [1], "debía clickear el bloque nuevo (índice 1)"


@pytest.mark.asyncio
async def test_click_por_clave_inexistente_no_clickea_nada():
    async def caso(up, page):
        ok = await up._click_marcar_por_clave("no-existe")
        return ok, await page.evaluate("window.__marcados")

    ok, marcados = await _con_pagina(pagina_html([("art-1", TITULO)]), caso)
    assert not ok
    assert marcados == []


@pytest.mark.asyncio
async def test_click_por_titulo_agarra_el_primero():
    """Documenta por qué la búsqueda por título sola es peligrosa: con
    homónimos elige el primero, que es el artículo ya publicado."""
    async def caso(up, page):
        ok = await up._click_marcar_por_titulo(TITULO)
        return ok, await page.evaluate("window.__marcados")

    ok, marcados = await _con_pagina(
        pagina_html([("art-viejo", TITULO), ("art-nuevo", TITULO)]), caso)
    assert ok
    assert marcados == [0], "confirma el comportamiento riesgoso que ahora se evita"


@pytest.mark.asyncio
async def test_flujo_completo_con_homonimo_no_toca_nada():
    """Extremo a extremo del caso destructivo: snapshot antes, snapshot
    después, decisión → abortar, y ningún click."""
    antes_html = pagina_html([("", TITULO)])           # ya publicado, sin id
    despues_html = pagina_html([("", TITULO), ("", TITULO)])

    async def caso(up, page):
        antes = await up._snapshot_article_blocks()
        await page.set_content(despues_html)
        despues = await up._snapshot_article_blocks()
        estrategia, motivo = up.decidir_articulo_a_marcar(antes, despues, TITULO)
        return estrategia, motivo, await page.evaluate("window.__marcados")

    estrategia, motivo, marcados = await _con_pagina(antes_html, caso)
    assert estrategia == "abortar", motivo
    assert marcados == [], "no debe clickear nada en el caso ambiguo"
