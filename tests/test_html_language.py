"""
Regresion: articulos cuyo idioma principal es ingles traen el titulo EN
primero en el documento (y el ES, si existe, segundo) -- extract_full_
article_data_from_html no debe asumir que el primer <p class="article-title">
siempre es español.
"""

import zipfile

from amelica.parsing.html import (
    extract_article_data_from_html,
    extract_full_article_data_from_html,
)


def _build_zip(tmp_path, html, name="index.zip"):
    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("index.html", html)
    return str(zip_path)


def test_articulo_principal_ingles_titulo_en_primero(tmp_path):
    html = """
    <html><body>
    <p class="MsoNormal article-title">Water quality in urban rivers</p>
    <p class="MsoNormal article-title">Calidad del agua en rios urbanos</p>
    <h1>Abstract</h1>
    <p class="MsoNormal">Some english abstract text. Keywords: water, quality.</p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    assert data["titles"][0]["lang"] == "en"
    assert data["titles"][0]["text"] == "Water quality in urban rivers"
    assert data["titles"][1]["lang"] == "es"
    assert data["titles"][1]["text"] == "Calidad del agua en rios urbanos"


def test_paginas_con_how_to_cite_en_ingles(tmp_path):
    """Caso real: 1386-RTE-38-1 usa 'How to cite:' en vez de 'Como citar',
    y las paginas quedaban vacias porque el regex solo buscaba español."""
    html = """
    <html><body>
    <p class="MsoNormal article-title">Analysis of Readability</p>
    <p class="MsoNormal"><strong>How to cite:</strong> Ullaguari, A. (2026).
    Analysis of Readability. <em>Revista, 38(1), 123-140.</em></p>
    <h1>Abstract</h1>
    <p class="MsoNormal">English abstract text. Keywords: reading.</p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_article_data_from_html(zip_path)

    assert data["page_start"] == "123"
    assert data["page_end"] == "140"


def test_fechas_en_ingles_se_detectan(tmp_path):
    html = """
    <html><body>
    <p class="MsoNormal article-title">Water quality in urban rivers</p>
    <h1>Abstract</h1>
    <p class="MsoNormal">Some english abstract text. Keywords: water, quality.</p>
    <p class="MsoNormal">Submitted: 01/02/2026</p>
    <p class="MsoNormal">Accepted: 03/04/2026</p>
    <p class="MsoNormal">Published: 05/06/2026</p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    assert data["dates"]["accepted"] == "03-04-2026"
    assert data["dates"]["published"] == "05-06-2026"


def test_articulo_principal_ingles_con_ambos_resumenes(tmp_path):
    """Caso real: 1386-RTE-38-1. El articulo tiene Resumen Y Abstract (el
    Resumen es una traduccion agregada mas abajo), pero el idioma principal
    es ingles -- 'Abstract' aparece ANTES que 'Resumen' en el documento.
    No alcanza con mirar si 'Resumen' existe para decidir el idioma
    principal ni el orden de los abstracts."""
    html = """
    <html><body>
    <p class="MsoNormal article-title">Analysis of Readability</p>
    <h1>Abstract</h1>
    <p class="MsoNormal">English abstract text. Keywords: reading, complexity.</p>
    <h1>Resumen</h1>
    <p class="MsoNormal">Texto en español. Palabras clave: lectura, complejidad.</p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)

    basic = extract_article_data_from_html(zip_path)
    assert basic["language"] == "Inglés"

    full = extract_full_article_data_from_html(zip_path)
    assert full["titles"][0]["lang"] == "en"
    assert full["abstracts"][0]["lang"] == "en"
    assert full["abstracts"][1]["lang"] == "es"


def test_email_en_texto_plano_sin_link_mailto(tmp_path):
    """Caso real: 1386-RTE-38-1. El primer email de la afiliacion viene en
    texto plano (sin <a href="mailto:...">), el segundo si tiene link -- el
    de texto plano se perdia porque el regex solo buscaba 'mailto:'."""
    html = """
    <html><body>
    <p class="MsoNormal article-title">Analysis of Readability</p>
    <p class="MsoNormal">Andrea Ullaguari<span>1</span>
    <a href="https://orcid.org/0009-0007-4118-5266">https://orcid.org/0009-0007-4118-5266</a>,
    Rodrigo Tovar<span>1</span></p>
    <p class="MsoNormal"><span>1</span><em>Universidad Tecnica</em>, Latacunga, Ecuador<br>
    andrea@utc.edu.ec, <a href="mailto:rodrigo@utc.edu.ec">rodrigo@utc.edu.ec</a><br></p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    emails = data["affiliations"]["1"]["emails"]
    assert "andrea@utc.edu.ec" in emails
    assert "rodrigo@utc.edu.ec" in emails


def test_orcid_con_espacio_colado_no_se_pierde(tmp_path):
    """Caso real: 1393-RTE-38-1. InDesign dejo un espacio justo despues de
    "orcid.org/" en el href (href="https://orcid.org/ 0000-..."). Sin
    tolerar ese espacio, la regex no matcheaba NINGUN ORCID del articulo y
    los 5 autores quedaban con orcid=None sin ningun aviso."""
    html = """
    <html><body>
    <p class="MsoNormal article-title">La robotica y ChatGPT</p>
    <p class="MsoNormal">Jorge Gudino<span>1</span>
    <a href="https://orcid.org/ 0000-0002-0585-908X">https://orcid.org/ 0000-0002-0585-908X</a>,
    Kevin Andrade<span>1</span>
    <a href="https://orcid.org/ 0000-0003-4257-5788">https://orcid.org/ 0000-0003-4257-5788</a></p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    assert data["authors"][0]["orcid"] == "https://orcid.org/0000-0002-0585-908X"
    assert data["authors"][1]["orcid"] == "https://orcid.org/0000-0003-4257-5788"


def test_orcid_con_barra_sobrante_no_desalinea_a_otros_autores(tmp_path):
    """Caso real: 1336-RTE-38-1. El href del primer autor trae una barra
    sobrante antes de la comilla de cierre
    (href="https://orcid.org/0000-.../"). Con la extraccion anterior (lista
    de ORCIDs aparte, emparejada por indice con la lista de autores), ese
    href roto se descartaba Y ademas corria el resto de los ORCIDs un lugar
    a la izquierda -- cada autor terminaba con el ORCID de otro."""
    html = """
    <html><body>
    <p class="MsoNormal article-title">Cajas de ahorro comunitarias</p>
    <p class="MsoNormal">Dunia Yaguache<span>1</span>
    <a href="https://orcid.org/0000-0002-3058-3775/">https://orcid.org/0000-0002-3058-3775/</a>,
    Carlos Cobos<span>1</span>
    <a href="https://orcid.org/0000-0002-7597-9351">https://orcid.org/0000-0002-7597-9351</a>,
    Veronica Cabrera<span>1</span>
    <a href="https://orcid.org/0000-0002-5489-3321">https://orcid.org/0000-0002-5489-3321</a></p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    assert data["authors"][0]["name"] == "Dunia Yaguache"
    assert data["authors"][0]["orcid"] == "https://orcid.org/0000-0002-3058-3775"
    assert data["authors"][1]["name"] == "Carlos Cobos"
    assert data["authors"][1]["orcid"] == "https://orcid.org/0000-0002-7597-9351"
    assert data["authors"][2]["name"] == "Veronica Cabrera"
    assert data["authors"][2]["orcid"] == "https://orcid.org/0000-0002-5489-3321"


def test_doi_con_espacio_colado_se_limpia(tmp_path):
    html = """
    <html><body>
    <p class="MsoNormal article-title">Articulo con DOI raro</p>
    <p class="MsoNormal"><a href="https://doi.org/10.37815/rte.v38n1. 1393">
    https://doi.org/10.37815/rte.v38n1. 1393</a></p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    assert data["doi"] == "https://doi.org/10.37815/rte.v38n1.1393"


def test_articulo_principal_espanol_titulo_es_primero(tmp_path):
    html = """
    <html><body>
    <p class="MsoNormal article-title">Calidad del agua en rios urbanos</p>
    <p class="MsoNormal article-title">Water quality in urban rivers</p>
    <h1>Resumen</h1>
    <p class="MsoNormal">Texto de resumen. Palabras clave: agua, calidad.</p>
    <h1>Abstract</h1>
    <p class="MsoNormal">Some english abstract text. Keywords: water, quality.</p>
    </body></html>
    """
    zip_path = _build_zip(tmp_path, html)
    data = extract_full_article_data_from_html(zip_path)

    assert data["titles"][0]["lang"] == "es"
    assert data["titles"][1]["lang"] == "en"
