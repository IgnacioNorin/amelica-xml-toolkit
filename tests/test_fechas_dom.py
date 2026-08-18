"""
Tests del apuntado de fechas contra un DOM falso.

Dos bugs distintos del año/tipo de fecha, ambos vistos en vivo:

1. (Detectado 2026-08-18 en Articulo 5, artículo previo) el año de
   "aceptado" quedaba en el año actual. El select de tipo y el input del
   datepicker se buscaban con .at(-1) sin mirar qué fecha se estaba
   llenando.
2. (Detectado 2026-08-18 en Articulo 4 y 5, con DOM real pegado por el
   usuario, confirmado en corridas secuenciales) tras arreglar (1) indexando
   por posición absoluta, "published" (índice 1) nunca encontraba su
   select/input. Causa real: en el DOM de AmeliCA solo la caja de fecha
   recién activada por _click_caja() tiene su <select>/<input> VISIBLE — la
   de la fecha anterior se oculta al activar la siguiente. Nunca hay más de
   un select/input visible a la vez, así que indexar por posición (sels[1])
   jamás iba a encontrar nada. La función ahora toma el único visible,
   confiando en que _click_caja() ya activó la caja correcta antes de
   llamarla.

Estructura tomada del DOM real (editor_dump.html):
  div[title^="Fecha"].date-526564616c7963  → contenedor de cada fecha
  select.date-type-526564616c7963          → tipo de fecha (visible SOLO si
                                              su caja está activa)
  input.date-526564616c7963                → campo de fecha, con id
                                              dp<timestamp> (idem)
Hay otros inputs cuyo nombre de clase contiene "date-" y NO son la fecha
del artículo: iso-8601-date-, open-data-date-, conf-date-.
"""

import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

from amelica.portal.uploader import AmelicaUploader  # noqa: E402

SUF = "526564616c7963"


def caja_fecha(dp_id, extra=""):
    # El contenedor lleva title="Fecha" y clase date-{SUF} — es lo que
    # _contar_campos_fecha() cuenta ahora (el <input> de adentro es
    # transitorio en el DOM real, ver test_contar_campos_de_fecha).
    return f'''<div class="date-{SUF} contenedor-fecha" title="Fecha">
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


def pagina(n=2, con_señuelos=False, activa=0):
    """Página con n cajas de fecha. Solo la caja nº 'activa' tiene su
    select/input visibles — así se comporta el editor real: activar una
    caja (_click_caja) oculta el select/input de las demás. window.__activar
    (i) permite simular que el test "clickea" otra caja distinta, igual que
    haría _click_caja() antes de cada _set_date_type/_open_date_picker."""
    señuelos = ""
    if con_señuelos:
        # Inputs que contienen "date-" en la clase pero NO son la fecha
        señuelos = (f'<input class="iso-8601-date-{SUF}" id="senuelo-iso">'
                    f'<input class="open-data-date-{SUF}" id="senuelo-open">'
                    f'<input class="conf-date-{SUF}" id="senuelo-conf">')
    cajas = "".join(caja_fecha(f"dp10000{i}") for i in range(n))
    activar_js = f"""
      window.__cajas = [...document.querySelectorAll('.contenedor-fecha')];
      window.__activar = (i) => {{
        window.__cajas.forEach((c, idx) => {{
          c.querySelectorAll('select, input').forEach(el => {{
            el.style.display = (idx === i) ? '' : 'none';
          }});
        }});
      }};
      window.__activar({activa});
    """
    return (f'<html><body><script>window.__abiertos=[];</script>'
            f'{señuelos}{cajas}<script>{activar_js}</script></body></html>')


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
    """EL BUG original: las dos fechas terminaban en el mismo input.
    Simula lo que hace el flujo real: activar la caja 0 (_click_caja),
    llenar; activar la caja 1, llenar — cada _open_date_picker() opera
    sobre lo que esté activo en ese momento, no sobre un índice fijo."""
    async def caso(up, page):
        a = await up._open_date_picker(0)   # caja 0 ya activa por defecto
        await page.evaluate("window.__activar(1)")   # como haría _click_caja
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
        await page.evaluate("window.__activar(1)")
        r1 = await up._set_date_type(1, "pub")
        valores = await page.evaluate(
            f"[...document.querySelectorAll('select.date-type-{SUF}')].map(s => s.value)")
        return r0, r1, valores

    r0, r1, valores = await _con_pagina(pagina(2), caso)
    assert (r0, r1) == ("ok-accepted", "ok-pub")
    assert valores == ["accepted", "pub"], "cada tipo en su propia fecha"


@pytest.mark.asyncio
async def test_segunda_fecha_no_depende_de_que_la_primera_siga_visible():
    """EL BUG del 2026-08-18 (Articulo 4 y 5): 'published' (índice 1) nunca
    encontraba nada porque solo hay UN select/input visible a la vez — el de
    la fecha anterior se oculta al activar la siguiente. Indexar por
    posición absoluta (sels[1]) jamás iba a matchear."""
    async def caso(up, page):
        await page.evaluate("window.__activar(1)")   # solo la 2da está activa
        return await up._open_date_picker(1), await up._set_date_type(1, "pub")

    inp, sel = await _con_pagina(pagina(2), caso)
    assert inp == "ok-dp100001"
    assert sel == "ok-pub"


@pytest.mark.asyncio
async def test_ignora_inputs_de_otras_fechas():
    """iso-8601-date-, open-data-date- y conf-date- contienen 'date-' en la
    clase pero no son el campo de fecha del artículo."""
    async def caso(up, page):
        return await up._open_date_picker(0)

    assert await _con_pagina(pagina(2, con_señuelos=True), caso) == "ok-dp100000"


@pytest.mark.asyncio
async def test_sin_caja_activa_se_reporta_con_detalle():
    """Si ninguna caja está activa (nada visible) hay que decirlo, no
    escribir a ciegas en cualquier control."""
    async def caso(up, page):
        await page.evaluate("window.__activar(-1)")   # ninguna activa
        return await up._open_date_picker(5), await up._set_date_type(5, "pub")

    inp, sel = await _con_pagina(pagina(2), caso)
    assert inp == "no-input-5-de-0"
    assert sel == "no-select-5-de-0"


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
            f"document.querySelectorAll('[title=\"Fecha\"]')[0].style.display='none'")
        return await up._contar_campos_fecha()

    assert await _con_pagina(pagina(2), caso) == 1


@pytest.mark.asyncio
async def test_contar_no_depende_de_cual_caja_este_activa():
    """EL BUG del 2026-08-18 (Articulo 4): el <input> de texto de una fecha
    solo existe/es visible mientras esa caja está activa. Contar por ahí daba
    0 justo después de borrar (nada activo) y 1 justo después de crear una
    (la nueva queda activa) — sin relación con el total real. El contenedor
    no depende de cuál esté activa."""
    async def caso(up, page):
        # Ninguna caja "activa": ocultar los inputs de texto, como pasa en
        # el DOM real cuando no se está editando ninguna fecha.
        await page.evaluate(
            f"document.querySelectorAll('input.date-{SUF}')"
            f".forEach(i => i.style.display = 'none')")
        return await up._contar_campos_fecha()

    assert await _con_pagina(pagina(3), caso) == 3


def _pagina_menu_fechas(n_inicial=0, falla_primer_click=False):
    """Página con la caja 'Fechas' y su botón de menú 'Fecha', que agrega
    un campo nuevo al clickear — usada para probar _crear_campo_fecha().

    falla_primer_click simula el caso real del 2026-08-18: el primer click
    en 'Fecha' "sale bien" (Playwright no tira excepción) pero el campo no
    aparece — recién el segundo intento lo crea.
    """
    cajas = "".join(caja_fecha(f"dp10000{i}") for i in range(n_inicial))
    saltar = "if (window.__intentos === 1) return;" if falla_primer_click else ""
    return f'''<html><body>
      <div title="Fechas"></div>
      <input type="button" value="Fecha" id="btn-fecha">
      {cajas}
      <script>
        window.__intentos = 0;
        document.getElementById('btn-fecha').addEventListener('click', () => {{
          window.__intentos++;
          {saltar}
          const caja = document.createElement('div');
          caja.className = 'date-{SUF} contenedor-fecha';
          caja.title = 'Fecha';
          document.body.appendChild(caja);
        }});
      </script>
    </body></html>'''


@pytest.mark.asyncio
async def test_crear_campo_fecha_confirma_que_aparecio():
    async def caso(up, page):
        ok = await up._crear_campo_fecha()
        return ok, await up._contar_campos_fecha()

    ok, total = await _con_pagina(_pagina_menu_fechas(n_inicial=1), caso)
    assert ok is True
    assert total == 2


@pytest.mark.asyncio
async def test_crear_campo_fecha_reintenta_si_el_primer_click_no_aterriza():
    """EL BUG del 2026-08-18: se pidieron 2 campos nuevos y solo apareció 1
    porque un click 'exitoso' no garantizaba que el campo se creara."""
    async def caso(up, page):
        ok = await up._crear_campo_fecha()
        return ok, await up._contar_campos_fecha()

    ok, total = await _con_pagina(
        _pagina_menu_fechas(n_inicial=0, falla_primer_click=True), caso)
    assert ok is True
    assert total == 1


@pytest.mark.asyncio
async def test_crear_campo_fecha_no_miente_si_nunca_aparece():
    async def caso(up, page):
        # Sin _click_menu_button funcional: no hay botón 'Fecha' en esta página.
        return await up._crear_campo_fecha()

    ok = await _con_pagina('<html><body><div title="Fechas"></div></body></html>', caso)
    assert ok is False
