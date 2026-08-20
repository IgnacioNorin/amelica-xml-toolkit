"""
Regresion: en el IDML el titulo traducido a veces sale en tipografia mas
chica que el titulo principal y no llega al umbral de 15pt que usa
looks_like_title -- queda como parrafo comun sin la clase article-title y
extract_full_article_data_from_html lo pierde. Confirmado con un articulo
real (1386-RTE-38-1, idioma principal ingles).
"""

from amelica.idml.converter import _promote_secondary_title


def test_promueve_titulo_secundario_sin_clase():
    body_parts = [
        '<p class="MsoNormal article-title" style="text-align:center;">'
        '<b><span>Analysis of Readability</span></b></p>',
        '<p class="MsoNormal" style="text-align:center;">'
        '<strong>Análisis de la legibilidad</strong></p>',
        '<p class="MsoNormal" style="text-align:center;">'
        'Andrea Ullaguari<span>1</span> <a href="https://orcid.org/x">orcid</a></p>',
    ]
    out = _promote_secondary_title(list(body_parts))

    assert 'article-title' in out[1]
    assert 'Análisis de la legibilidad' in out[1]
    assert out[2] == body_parts[2]   # la linea de autores no se toca


def test_no_promueve_la_linea_de_autores_si_no_hay_titulo_secundario():
    body_parts = [
        '<p class="MsoNormal article-title" style="text-align:center;">'
        '<b><span>Solo titulo</span></b></p>',
        '<p class="MsoNormal" style="text-align:center;">'
        'Juan Perez<span>1</span> <a href="https://orcid.org/x">orcid</a></p>',
    ]
    out = _promote_secondary_title(list(body_parts))

    assert out == body_parts
