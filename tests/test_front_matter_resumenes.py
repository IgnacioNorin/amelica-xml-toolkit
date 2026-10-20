"""
Regresion: resumenes en "Datos del articulo" con un articulo de Word (1328).

El DOM de prueba reproduce lo que dejo el portal: el parrafo del resumen ES
pre-creado con una "Tabla o cuadro" adentro (el recuadro "Sumario / Como
citar" que Word ancla dentro del resumen) y el resumen EN ya pre-creado.
Antes el texto del resumen se escribia en el "Identificador" de la tabla y
el resumen EN quedaba duplicado.
"""

import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

from amelica.portal.uploader import AmelicaUploader  # noqa: E402

S = "-526564616c7963"

PARRAFO_CON_TABLA = f'''
<div class="p{S}" title="Párrafo">
  <div class="moveButton{S}" title="Mover" contenteditable="false"></div>
  <div class="table-wrap{S}" title="Tabla o cuadro">
    <div class="label{S}" title="Identificador">
      <span class="contenido{S}" contenteditable="true">Sumario: ...</span>
    </div>
    <input title="id{S}" value="gt1" type="hidden">
  </div>
</div>'''

PARRAFO_LIMPIO = f'''
<div class="p{S}" title="Párrafo">
  <span class="contenido{S}" contenteditable="true">texto previo</span>
</div>'''


def pagina(parrafo_es):
    return f'''<html><body>
    <div class="abstract-box{S}" title="Resúmenes">
      <div class="abstract{S}" title="Resumen  - ES">
        {parrafo_es}
        <input title="xml:lang{S}" value="es" type="hidden">
      </div>
      <div class="trans-abstract{S}" title="Resumen  - EN">
        {PARRAFO_LIMPIO}
        <input title="xml:lang{S}" value="en" type="hidden">
      </div>
    </div></body></html>'''


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
async def test_no_escribe_en_un_parrafo_con_tabla_adentro():
    async def caso(up, page):
        r = await page.evaluate_handle("document.querySelector('[title=\"Resumen  - ES\"]')")
        estado = await up._preparar_parrafo_de_resumen(r)
        intacto = await page.evaluate(
            "document.querySelector('[title=\"Identificador\"] span').textContent")
        return estado, intacto
    estado, intacto = await _con_pagina(pagina(PARRAFO_CON_TABLA), caso)
    assert estado == "anidado"
    assert intacto == "Sumario: ..."


@pytest.mark.asyncio
async def test_parrafo_limpio_queda_vacio_y_con_foco():
    async def caso(up, page):
        r = await page.evaluate_handle("document.querySelector('[title=\"Resumen  - ES\"]')")
        estado = await up._preparar_parrafo_de_resumen(r)
        await page.keyboard.type("Resumen nuevo")
        return estado, await page.evaluate(
            "document.querySelector('[title=\"Resumen  - ES\"] [contenteditable]').textContent")
    estado, texto = await _con_pagina(pagina(PARRAFO_LIMPIO), caso)
    assert estado == "ok"
    assert texto == "Resumen nuevo"


@pytest.mark.asyncio
async def test_parrafo_con_boton_mover_sigue_siendo_apto():
    parrafo = PARRAFO_LIMPIO.replace(
        f'title="Párrafo">', f'title="Párrafo"><div class="moveButton{S}" title="Mover"></div>', 1)

    async def caso(up, page):
        r = await page.evaluate_handle("document.querySelector('[title=\"Resumen  - ES\"]')")
        return await up._preparar_parrafo_de_resumen(r)
    assert await _con_pagina(pagina(parrafo), caso) == "ok"


@pytest.mark.asyncio
async def test_encuentra_el_resumen_en_otro_idioma_ya_creado():
    async def caso(up, page):
        titulos = []
        for lang in ("en", "es", "pt"):
            h = await up._buscar_resumen_por_idioma(lang)
            titulos.append(await page.evaluate("r => r ? r.getAttribute('title') : null", h))
        return titulos
    assert await _con_pagina(pagina(PARRAFO_LIMPIO), caso) == [
        "Resumen  - EN", "Resumen  - ES", None]
