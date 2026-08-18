"""Tests del diagnóstico del marcaje.

`AmelicaMarker.run()` puede fallar en siete puntos distintos y antes todos
se reportaban con el mismo texto ("el editor de marcaje no respondió"): las
corridas del 2026-08-18 fallaron dos veces sin dejar rastro de en cuál. Estos
tests fijan que cada fallo diga qué pasó y que el uploader lo propague.

No abren navegador: usan un doble de la página de Playwright.
"""

import asyncio

import pytest

from amelica.portal.marker import AmelicaMarker
from amelica.portal.uploader import AmelicaUploader


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """El marcaje duerme varios segundos buscando el modal del asistente.
    Sin portal no hay nada que esperar: los tests no tienen que pagarlo."""
    async def ya(*a, **k):
        return None
    monkeypatch.setattr(asyncio, 'sleep', ya)


class PaginaFalsa:
    """Doble mínimo de la page de Playwright.

    `selectores_ausentes` son los que hacen timeout en wait_for_selector, para
    poder reproducir cada punto de fallo sin portal.
    """

    def __init__(self, selectores_ausentes=(), evaluate_result=False):
        self.selectores_ausentes = set(selectores_ausentes)
        self.evaluate_result = evaluate_result
        self.url = 'https://portal.amelica.org/marker.oa'

    async def wait_for_url(self, *a, **k):
        return None

    async def wait_for_load_state(self, *a, **k):
        return None

    async def wait_for_selector(self, selector, **k):
        if selector in self.selectores_ausentes:
            raise TimeoutError(f'timeout esperando {selector}')
        return object()

    async def wait_for_function(self, *a, **k):
        raise TimeoutError('timeout')

    async def evaluate(self, *a, **k):
        return self.evaluate_result

    async def query_selector(self, selector):
        return None


def correr(page):
    marker = AmelicaMarker(page)
    ok = asyncio.run(marker.run())
    return ok, marker.motivo_fallo


def test_editor_que_no_carga_lo_dice():
    ok, motivo = correr(PaginaFalsa(selectores_ausentes={'#maskInfP', '#intArbol'}))
    assert ok is False
    assert 'no cargó' in motivo and 'maskInfP' in motivo


def test_editor_sin_textareas_es_un_motivo_distinto():
    """El editor abrió (los selectores están) pero no hay textarea: no es lo
    mismo que 'el editor no cargó' y el resumen no debe confundirlos."""
    ok, motivo = correr(PaginaFalsa())
    assert ok is False
    assert 'sin textareas' in motivo


def test_los_motivos_no_se_repiten_entre_fallos():
    _, sin_editor = correr(PaginaFalsa(selectores_ausentes={'#maskInfP'}))
    _, sin_textarea = correr(PaginaFalsa())
    assert sin_editor != sin_textarea


def test_run_limpia_el_motivo_anterior():
    """Si no se reseteara, un fallo viejo se reportaría en la corrida siguiente."""
    marker = AmelicaMarker(PaginaFalsa(selectores_ausentes={'#intArbol'}))
    asyncio.run(marker.run())
    assert marker.motivo_fallo
    marker.page = PaginaFalsa()
    asyncio.run(marker.run())
    assert 'maskInfP' not in marker.motivo_fallo


def test_marker_arranca_sin_motivo():
    assert AmelicaMarker(PaginaFalsa()).motivo_fallo == ''


def test_el_resumen_del_uploader_usa_el_motivo_concreto():
    """Lo que se veía en el resumen era el texto genérico; ahora tiene que
    llegar el motivo real del marker."""
    up = AmelicaUploader(email='x@y.z', password='secreto')
    up._step('marker', False, 'el artículo no cargó en #articuloIn tras 30s')
    ok, detalle = up.steps['marker']
    assert ok is False
    assert '#articuloIn' in detalle
