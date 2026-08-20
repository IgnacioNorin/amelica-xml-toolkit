"""
Regresion: EXCLUDED_STORIES saca las stories de encabezado/pie dedicadas,
pero InDesign a veces deja el marcador de paginacion (ej. "<?ACE 18?>", el
codigo de encabezado repetido) colado inline en el flujo del cuerpo del
articulo, en vez de en su propia story. Confirmado con un articulo real
(1393-RTE-38-1): aparecia dos veces al principio del cuerpo, antes de
autores y antes del titulo.
"""

from amelica.idml.converter import _strip_pagination_markers


def test_saca_el_marcador_de_paginacion_del_cuerpo():
    body_parts = [
        '<p class="MsoNormal"><strong>&lt;?ACE 18?&gt;</strong></p>',
        '<p class="MsoNormal"><em>Jorge Gudiño-Lau, Kevin Andrade-Gudiño</em></p>',
        '<p class="MsoNormal"><strong>&lt;?ACE 18?&gt;</strong></p>',
        '<p class="MsoNormal"><em>La robótica y ChatGPT: aplicación educativa</em></p>',
    ]
    out = _strip_pagination_markers(body_parts)

    assert len(out) == 2
    assert 'ACE' not in ''.join(out)
    assert 'Jorge Gudiño-Lau' in out[0]
    assert 'La robótica y ChatGPT' in out[1]


def test_no_saca_texto_real_que_no_es_un_marcador():
    body_parts = [
        '<p class="MsoNormal">Este parrafo menciona ACE como sigla dentro del texto.</p>',
        '<h1>Introducción</h1>',
    ]
    out = _strip_pagination_markers(body_parts)

    assert out == body_parts
