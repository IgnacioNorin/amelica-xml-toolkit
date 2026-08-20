"""
Regresion: _extract_article_sections no debe marcar pies de tabla/figura
("Table 1", "Figure2") como secciones, ni saltear secciones reales en
ingles ("Introduction", "Results") por buscar solo vocabulario en español.

Confirmado con los headings reales de 1386-RTE-38-1 (idioma principal
ingles): Abstract, Resumen, Introduction, Materials and Methods,
Table 1..6, Results, Figure1, Discussion, Conclusions, Acknowledgements
and Declarations, References.
"""

import pytest

playwright_api = pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

from amelica.portal.uploader import AmelicaUploader  # noqa: E402
from amelica.portal.marker import AmelicaMarker  # noqa: E402


HEADINGS_1386 = [
    "Abstract", "Resumen", "Introduction", "Materials and Methods",
    "Table 1", "Table 2", "Table 3", "Results", "Table 4", "Table 5",
    "Table 6", "Figure1", "Discussion", "Conclusions",
    "Acknowledgements and Declarations", "References",
]


def pagina_html(headings):
    body = "".join(f"<h1>{h}</h1><p>texto de {h}</p>" for h in headings)
    return f'<html><body><div id="articuloIn">{body}</div></body></html>'


async def _extraer(headings):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(pagina_html(headings))
            up = AmelicaUploader.__new__(AmelicaUploader)
            up.page = page
            return await AmelicaMarker._extract_article_sections(up)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_no_marca_tablas_ni_figuras_en_ingles():
    secciones = await _extraer(HEADINGS_1386)
    textos = [s["text"] for s in secciones]

    for descartado in ("Table 1", "Table 2", "Table 3", "Table 4",
                        "Table 5", "Table 6", "Figure1"):
        assert descartado not in textos, f"'{descartado}' no debería marcarse como sección"


@pytest.mark.asyncio
async def test_marca_las_secciones_reales_en_ingles():
    secciones = await _extraer(HEADINGS_1386)
    textos = [s["text"] for s in secciones]

    for esperado in ("Introduction", "Materials and Methods", "Results",
                      "Discussion", "Conclusions"):
        assert esperado in textos, f"'{esperado}' debería marcarse como sección"


@pytest.mark.asyncio
async def test_no_marca_referencias_ni_agradecimientos_en_ingles():
    secciones = await _extraer(HEADINGS_1386)
    textos = [s["text"] for s in secciones]

    assert "References" not in textos
    assert "Acknowledgements and Declarations" not in textos
