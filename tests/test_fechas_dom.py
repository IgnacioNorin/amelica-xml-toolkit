"""
Tests del apuntado de fechas contra un DOM falso.

Bug del 2026-08-18 (detectado por el usuario en el artículo 5): el año de
"aceptado" quedó en 2026 cuando era 2025. Causa: el select de tipo y el
input del datepicker se buscaban con .at(-1) — el último del documento —
sin importar qué fecha se estuviera llenando, así que las dos fechas
escribían en el mismo control y "published" pisaba a "accepted".

Estructura tomada del DOM real (editor_dump.html):
  select.date-type-526564616c7963   → tipo de fecha
  input.date-526564616c7963         → campo de fecha, con id dp<timestamp>
Hay otros inputs cuyo nombre de clase contiene "date-" y NO son la fecha
del artículo: iso-8601-date-, open-data-date-, conf-date-.
"""

import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

from amelica.portal.uploader import AmelicaUploader  # noqa: E402

SUF = "526564616c7963"


def caja_fecha(dp_id, extra=""):
    return f'''<div class="fecha">
      <select class="date-type-{SUF} attrib-{SUF}">
        <option value="">Elige una opción</option>
        <option value="received">Recibido</option>
        <option value="accepted">Aceptado</option>
        <option value="pub">Publicado</option>
      </select>
      <input class="date-{SUF} datepicker-{SUF} hasDatepicker" type="text"
             id="{dp_id}" readonly onclick="window.__abiertos.push('{dp_id}')">
      {extra}
    </div>'''


def pagina(n=2, con_señuelos=False):
    señuelos = ""
    if con_señuelos:
        # Inputs que contienen "date-" en la clase pero NO son la fecha
        señuelos = (f'<input class="iso-8601-date-{SUF}" id="senuelo-iso">'
                    f'<input class="open-data-date-{SUF}" id="senuelo-open">'
                    f'<input class="conf-date-{SUF}" id="senuelo-conf">')
    cajas = "".join(caja_fecha(f"dp10000{i}") for i in range(n))
    return (f'<html><body><script>window.__abiertos=[];</script>'
            f'{señuelos}{cajas}</body></html>')


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
async def test_cada_fecha_abre_su_propio_datepicker():
    """EL BUG: las dos fechas terminaban en el mismo input."""
    async def caso(up, page):
        a = await up._open_date_picker(0)
        b = await up._open_date_picker(1)
        return a, b, await page.evaluate("window.__abiertos")

    a, b, abiertos = await _con_pagina(pagina(2), caso)
    assert a == "ok-dp100000"
    assert b == "ok-dp100001"
    assert a != b, "cada fecha debe usar su propio control"
    assert abiertos == ["dp100000", "dp100001"]


@pytest.mark.asyncio
async def test_el_tipo_va_al_select_correcto():
    async def caso(up, page):
        r0 = await up._set_date_type(0, "accepted")
        r1 = await up._set_date_type(1, "pub")
        valores = await page.evaluate(
            f"[...document.querySelectorAll('select.date-type-{SUF}')].map(s => s.value)")
        return r0, r1, valores

    r0, r1, valores = await _con_pagina(pagina(2), caso)
    assert (r0, r1) == ("ok-accepted", "ok-pub")
    assert valores == ["accepted", "pub"], "cada tipo en su propia fecha"


@pytest.mark.asyncio
async def test_ignora_inputs_de_otras_fechas():
    """iso-8601-date-, open-data-date- y conf-date- contienen 'date-' en la
    clase pero no son el campo de fecha del artículo."""
    async def caso(up, page):
        return await up._open_date_picker(0)

    assert await _con_pagina(pagina(2, con_señuelos=True), caso) == "ok-dp100000"


@pytest.mark.asyncio
async def test_indice_inexistente_se_reporta_con_detalle():
    """Si el DOM no tiene tantas fechas hay que decirlo, no escribir en otra."""
    async def caso(up, page):
        return await up._open_date_picker(5), await up._set_date_type(5, "pub")

    inp, sel = await _con_pagina(pagina(2), caso)
    assert inp == "no-input-5-de-2"
    assert sel == "no-select-5-de-2"


@pytest.mark.asyncio
async def test_no_cuenta_controles_ocultos():
    async def caso(up, page):
        await page.evaluate(
            f"document.querySelectorAll('input.date-{SUF}')[0].style.display='none'")
        return await up._open_date_picker(0)

    # Con el primero oculto, el índice 0 debe ser el segundo visible
    assert await _con_pagina(pagina(2), caso) == "ok-dp100001"


@pytest.mark.asyncio
async def test_contar_campos_de_fecha():
    async def caso(up, page):
        return await up._contar_campos_fecha()

    assert await _con_pagina(pagina(2), caso) == 2
    assert await _con_pagina(pagina(1), caso) == 1
    # Los señuelos no son campos de fecha del artículo
    assert await _con_pagina(pagina(2, con_señuelos=True), caso) == 2


@pytest.mark.asyncio
async def test_contar_ignora_ocultos():
    async def caso(up, page):
        await page.evaluate(
            f"document.querySelectorAll('input.date-{SUF}')[0].style.display='none'")
        return await up._contar_campos_fecha()

    assert await _con_pagina(pagina(2), caso) == 1
