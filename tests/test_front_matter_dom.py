"""
Tests de la guarda que impide destruir autores ya cargados.

El 2026-08-18 el front matter corrió sobre un artículo ya publicado y su
"Paso 0: borrar autores sobrantes" eliminó 3 autores reales. Estos tests
fijan el comportamiento nuevo contra un DOM falso que imita el editor.
"""

import pytest

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright  # noqa: E402

from amelica.portal.uploader import AmelicaUploader  # noqa: E402

CAMPOS = ["Nombre(s)", "Apellido(s)", "Correo electrónico",
          "Afiliación completa", "Institución"]


def autor_html(valores=None):
    """Un bloque de autor. valores=None o {} → bloque vacío."""
    valores = valores or {}
    campos = "".join(
        f'<span title="{c}" class="contenido-">{valores.get(c, "")}</span>'
        for c in CAMPOS
    )
    return f'''<div title="Autor" class="autor">
        {campos}
        <a title="Cerrar" onclick="this.closest('.autor').remove()">x</a>
    </div>'''


def pagina(autores):
    return f"<html><body>{''.join(autor_html(a) for a in autores)}</body></html>"


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


async def _contar_autores(page):
    return await page.evaluate(
        "document.querySelectorAll('[title=\"Autor\"]').length")


# ── Detección de artículo ya cargado ─────────────────────────────

@pytest.mark.asyncio
async def test_articulo_nuevo_tiene_todos_los_bloques_vacios():
    """Un artículo recién creado: los bloques existen pero están vacíos."""
    async def caso(up, page):
        return await up._autores_con_datos()

    autores = await _con_pagina(pagina([None, None, None]), caso)
    assert len(autores) == 3
    assert not any(a["tiene_datos"] for a in autores)


@pytest.mark.asyncio
async def test_articulo_ya_cargado_se_detecta():
    """EL CASO DEL ACCIDENTE: el artículo ya tenía autores reales."""
    async def caso(up, page):
        return await up._autores_con_datos()

    autores = await _con_pagina(pagina([
        {"Nombre(s)": "Dunia Maritza", "Apellido(s)": "Yaguache Maza"},
        {"Nombre(s)": "Freddy", "Apellido(s)": "Ordóñez"},
        None,
    ]), caso)
    con_datos = [a for a in autores if a["tiene_datos"]]
    assert len(con_datos) == 2
    assert con_datos[0]["valores"]["Apellido(s)"] == "Yaguache Maza"


# ── Borrado selectivo ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_borra_los_vacios_sobrantes():
    """Comportamiento normal: limpia restos de inferencias previas."""
    async def caso(up, page):
        r = await up._borrar_autores_sobrantes(solo_vacios=True)
        return r, await _contar_autores(page)

    resultado, quedan = await _con_pagina(pagina([None, None, None, None]), caso)
    assert resultado == {"borrados": 3, "conservados": 0}
    assert quedan == 1


@pytest.mark.asyncio
async def test_no_borra_autores_con_datos():
    """LA GUARDA: los bloques con contenido real no se tocan."""
    async def caso(up, page):
        r = await up._borrar_autores_sobrantes(solo_vacios=True)
        return r, await _contar_autores(page)

    resultado, quedan = await _con_pagina(pagina([
        {"Nombre(s)": "Dunia Maritza"},
        {"Nombre(s)": "Freddy"},
        {"Nombre(s)": "Silvia"},
        {"Nombre(s)": "Jorge"},
    ]), caso)
    assert resultado == {"borrados": 0, "conservados": 3}
    assert quedan == 4, "no se debe perder ningún autor real"


@pytest.mark.asyncio
async def test_borra_vacios_y_conserva_llenos():
    """Mezcla: limpia lo que es basura y respeta lo que es dato."""
    async def caso(up, page):
        r = await up._borrar_autores_sobrantes(solo_vacios=True)
        return r, await _contar_autores(page)

    resultado, quedan = await _con_pagina(pagina([
        None,                          # primero: nunca se toca
        {"Apellido(s)": "Yaguache"},   # dato real
        None,                          # basura
        None,                          # basura
    ]), caso)
    assert resultado == {"borrados": 2, "conservados": 1}
    assert quedan == 2


@pytest.mark.asyncio
async def test_sobrescribir_borra_todo_igual():
    """Con --sobrescribir el usuario pidió explícitamente pisar los datos."""
    async def caso(up, page):
        r = await up._borrar_autores_sobrantes(solo_vacios=False)
        return r, await _contar_autores(page)

    resultado, quedan = await _con_pagina(pagina([
        {"Nombre(s)": "A"}, {"Nombre(s)": "B"}, {"Nombre(s)": "C"},
    ]), caso)
    assert resultado == {"borrados": 2, "conservados": 0}
    assert quedan == 1


@pytest.mark.asyncio
async def test_un_solo_autor_no_borra_nada():
    async def caso(up, page):
        r = await up._borrar_autores_sobrantes(solo_vacios=True)
        return r, await _contar_autores(page)

    resultado, quedan = await _con_pagina(pagina([None]), caso)
    assert resultado == {"borrados": 0, "conservados": 0}
    assert quedan == 1
