"""
test_word_html.py — Soporte para el index.html exportado desde Word.

El HTML de prueba reproduce la estructura real de un articulo de la revista
exportado desde Word (1328-RTE-37-2): titulos de seccion con el estilo
propio "Nivel1" (sin <h1>), autores con superindice y link ORCID,
afiliacion en cursiva, emails en un parrafo aparte, fechas con tabuladores
de Word, y el recuadro "Sumario / Como citar" como cuadro de texto VML
anclado dentro del primer parrafo del resumen. Los datos son ficticios.
"""

import asyncio
import re
import zipfile

import pytest

from amelica.parsing import (
    extract_article_data_from_html, extract_full_article_data_from_html, fix_zip_for_amelica,
)
from amelica.parsing.word_html import (
    decodificar_html, es_html_de_word, extraer_datos_basicos_word, extraer_portada_word,
    normalizar_titulos_word, sacar_recuadros_del_resumen,
)


HTML_WORD = """<html xmlns:v="urn:schemas-microsoft-com:vml"
xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta http-equiv=Content-Type content="text/html; charset={charset}">
<meta name=ProgId content=Word.Document>
<meta name=Generator content="Microsoft Word 15">
<style>
<!--
p.MsoNormal, li.MsoNormal, div.MsoNormal
	{{margin:0cm;
	font-size:12.0pt;}}
h1
	{{mso-outline-level:1;
	font-size:16.0pt;}}
p.MsoTitle, li.MsoTitle, div.MsoTitle
	{{mso-outline-level:1;
	font-size:16.0pt;}}
p.Nivel1, li.Nivel1, div.Nivel1
	{{mso-style-name:"Nivel 1";
	mso-outline-level:1;
	font-weight:bold;}}
p.Nivel2, li.Nivel2, div.Nivel2
	{{mso-style-name:"Nivel 2";
	mso-outline-level:2;}}
-->
</style>
</head>
<body lang=ES-EC>
<div class=WordSection1>
<p class=MsoNormal align=right><span lang=ES-EC><a
href="https://doi.org/10.99999/rev.v1n1.0001"><span>https://doi.org/10.99999/rev.v1n1.0001</span></a></span></p>
<p class=MsoNormal align=right><span>Artículos originales<o:p></o:p></span></p>
<p class=MsoNormal align=center style='margin-bottom:12.0pt'><a name="_Hlk1"><b><span
style='font-size:16.0pt'>Título de prueba en español
sobre un tema cualquiera</span></b></a><span style='font-size:10.0pt'><o:p></o:p></span></p>
<p class=MsoNormal align=center style='margin-bottom:12.0pt'><b><span lang=EN-US
style='font-size:16.0pt'>Test title in English about any topic</span></b><span
lang=EN-US style='font-size:10.0pt'><o:p></o:p></span></p>
<p class=MsoNormal align=center><span lang=ES-EC>Ana
Pérez</span><sup><span lang=PT-BR>1</span></sup><span> </span><a
href="https://orcid.org/0000-0000-0000-0011"><sup><span>https://orcid.org/0000-0000-0000-0011</span></sup></a><span>,<o:p></o:p></span></p>
<p class=MsoNormal align=center><span lang=ES-EC>Luis
Gómez</span><sup><span lang=PT-BR>2</span></sup><sup><span><span
style='mso-spacerun:yes'>  </span></span></sup><a
href="https://orcid.org/0000-0000-0000-0011"><sup><span>https://orcid.org/0000-0000-0000-0011</span></sup></a></p>
<p class=MsoNormal align=center><span><o:p>&nbsp;</o:p></span></p>
<p class=MsoNormal align=center><sup><span>1</span></sup><i><span>Universidad
de Prueba</span></i><span>, Quito, Ecuador</span></p>
<p class=MsoNormal align=center><a href="mailto:ana.perez@ejemplo.edu.ec"><span>ana.perez@ejemplo.edu.ec</span></a></p>
<p class=MsoNormal align=center><sup><span>2</span></sup><i><span>Instituto
Ficticio</span></i><span>, Córdoba, Argentina</span></p>
<p class=MsoNormal align=center><span>luis.gomez@ejemplo.edu.ar <o:p></o:p></span></p>
<p class=paragraph align=right><span>Enviado:<span style='mso-spacerun:yes'>    </span>2025/06/01</span></p>
<p class=paragraph align=right><span>Aceptado:<span style='mso-tab-count:1'>       </span>2025/09/04</span></p>
<p class=paragraph align=right><span>Publicado:
<span style='mso-tab-count:1'>     </span>2025/12/15</span></p>
<p class=Nivel1><span class=normaltextrun><span>Resumen</span></span><span
style='font-size:18.0pt'><o:p></o:p></span></p>
<p class=MsoNormal><o:wrapblock><v:shape id="Cuadro_2" type="#_x0000_t202">
  <v:textbox>
   <![if !mso]>
   <table cellpadding=0 cellspacing=0 width="100%">
    <tr>
     <td><![endif]>
     <div>
     <p class=MsoNormal><b><span>Sumario:</span></b><span> Introducción, Conclusiones.</span></p>
     <p class=MsoNormal><b><span>Como citar:</span></b><span> Pérez, A. &amp; Gómez, L.
     (2025). Título de prueba. </span><i><span>Revista de Prueba, 1(2), 285-299.</span></i></p>
     </div>
     <![if !mso]></td>
    </tr>
   </table>
   <![endif]></v:textbox>
 </v:shape></o:wrapblock><br style='mso-ignore:vglayout' clear=ALL>
<span>Este es el resumen
en español del artículo.</span></p>
<p class=MsoNormal><span>Segundo párrafo del resumen.</span></p>
<p class=MsoNormal><a name="_Hlk2"><b><i><span>Palabras
clave: </span></i></b></a><span>uno, dos,
tres.<o:p></o:p></span></p>
<p class=Nivel1><span lang=EN-US>Abstract</span></p>
<p class=MsoNormal><span lang=EN-US>This is the English abstract.</span></p>
<p class=MsoNormal><b><i><span lang=EN-US>Keywords: </span></i></b><span
lang=EN-US>one, two, three.</span></p>
<p class=Nivel1><span>Introducción</span></p>
<p class=MsoNormal><span>Texto de la introducción.</span></p>
<p class=Nivel2><span>Una subsección</span></p>
<p class=MsoNormal><span>Texto de la subsección.</span></p>
<p class=Nivel1><a name="_Hlk3"><span>Resultados
y Discusión<o:p></o:p></span></a></p>
<p class=MsoNormal><span>Texto de resultados.</span></p>
<p class=Nivel1><span>Conclusiones<o:p></o:p></span></p>
<p class=MsoNormal><span>Texto final de las conclusiones del artículo.</span></p>
<p class=Nivel1><span>Referencias<o:p></o:p></span></p>
<p class=paragraph><span>Autor, A. (2020). Una referencia. Revista, 1(1), 1-2.</span></p>
</div>
</body>
</html>
"""


def html_word(charset="utf-8"):
    return HTML_WORD.format(charset=charset)


def h1s(html):
    return [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S)]


# ── Detección y decodificación ───────────────────────────────────────

def test_detecta_html_de_word():
    assert es_html_de_word(html_word())
    assert not es_html_de_word("<html><head></head><body><h1>Resumen</h1></body></html>")


def test_decodifica_segun_charset_del_meta():
    datos = html_word("windows-1252").encode("windows-1252")
    texto, codificacion = decodificar_html(datos)
    assert codificacion == "windows-1252"
    assert "Título de prueba en español" in texto


# ── Títulos de sección ───────────────────────────────────────────────

def test_convierte_nivel1_en_h1():
    html, convertidos = normalizar_titulos_word(html_word())
    assert convertidos == 6
    assert h1s(html) == [
        "Resumen", "Abstract", "Introducción", "Resultados y Discusión",
        "Conclusiones", "Referencias",
    ]
    assert '<h1 class=Nivel1>' in html
    # Nivel 2 no es nivel 1: queda como párrafo.
    assert '<p class=Nivel2>' in html


def test_reconoce_titulos_en_exportacion_filtrada():
    """'Página web filtrada' borra mso-outline-level de la hoja de estilos:
    la clase de título se reconoce por los nombres de sección conocidos."""
    filtrada = re.sub(r"mso-outline-level:\d;", "", html_word()).replace(
        'content="Microsoft Word 15"', 'content="Microsoft Word 15 (filtered)"')
    html, convertidos = normalizar_titulos_word(filtrada)
    assert convertidos == 6
    assert "Introducción" in h1s(html)
    assert '<p class=Nivel2>' in html
    assert extraer_portada_word(filtrada)["abstracts"] == extraer_portada_word(html_word())["abstracts"]


def test_no_convierte_estilos_genericos_aunque_digan_resumen():
    html = html_word().replace("<p class=Nivel1><span class=normaltextrun>",
                               "<p class=MsoNormal><span class=normaltextrun>")
    sin_css = re.sub(r"mso-outline-level:\d;", "", html)
    convertido, _ = normalizar_titulos_word(sin_css)
    assert '<p class=MsoNormal><span class=normaltextrun><span>Resumen' in convertido


def test_colapsa_saltos_de_linea_dentro_del_titulo():
    html, _ = normalizar_titulos_word(html_word())
    assert "Resultados y Discusión" in h1s(html)


def test_normalizar_es_idempotente_y_no_toca_html_ajeno():
    html, _ = normalizar_titulos_word(html_word())
    assert normalizar_titulos_word(html) == (html, 0)
    ajeno = "<html><body><p class=Nivel1>Resumen</p></body></html>"
    assert normalizar_titulos_word(ajeno) == (ajeno, 0)


# ── Portada ──────────────────────────────────────────────────────────

def test_titulos_con_su_idioma():
    data = extraer_portada_word(html_word())
    assert data["titles"] == [
        {"lang": "es", "text": "Título de prueba en español sobre un tema cualquiera"},
        {"lang": "en", "text": "Test title in English about any topic"},
    ]


def test_autores_con_afiliacion_y_orcid():
    data = extraer_portada_word(html_word())
    assert data["authors"] == [
        {"name": "Ana Pérez", "affil_num": "1", "orcid": "https://orcid.org/0000-0000-0000-0011"},
        {"name": "Luis Gómez", "affil_num": "2", "orcid": "https://orcid.org/0000-0000-0000-0011"},
    ]


def test_afiliaciones_con_pais_y_emails():
    data = extraer_portada_word(html_word())
    assert data["affiliations"] == {
        "1": {"text": "Universidad de Prueba", "country": "Quito, Ecuador",
              "emails": ["ana.perez@ejemplo.edu.ec"]},
        "2": {"text": "Instituto Ficticio", "country": "Córdoba, Argentina",
              "emails": ["luis.gomez@ejemplo.edu.ar"]},
    }


def test_avisa_orcid_repetido_entre_autores():
    data = extraer_portada_word(html_word())
    assert len(data["warnings"]) == 1
    assert "Ana Pérez, Luis Gómez" in data["warnings"][0]


def test_fechas_y_doi():
    data = extraer_portada_word(html_word())
    assert data["dates"] == {"accepted": "2025-09-04", "published": "2025-12-15"}
    assert data["doi"] == "https://doi.org/10.99999/rev.v1n1.0001"


def test_resumenes_sin_el_recuadro_como_citar():
    data = extraer_portada_word(html_word())
    assert data["abstracts"] == [
        {"lang": "es",
         "text": "Este es el resumen en español del artículo. Segundo párrafo del resumen.",
         "keywords": ["uno", "dos", "tres"]},
        {"lang": "en", "text": "This is the English abstract.",
         "keywords": ["one", "two", "three"]},
    ]


def test_portada_igual_antes_y_despues_de_normalizar():
    html = html_word()
    assert extraer_portada_word(normalizar_titulos_word(html)[0]) == extraer_portada_word(html)


def test_datos_basicos():
    assert extraer_datos_basicos_word(html_word()) == {
        "title": "Título de prueba en español sobre un tema cualquiera",
        "article_type": "Artículo científico",
        "section": "Artículos",
        "language": "Español",
        "citation": "APA",
        "page_start": "285",
        "page_end": "299",
    }


def test_idioma_ingles_si_abstract_va_primero():
    html = html_word()
    resumen = re.search(r"<p class=Nivel1><span class=normaltextrun>.*?(?=<p class=Nivel1><span lang=EN-US>)",
                        html, re.S).group(0)
    abstract = re.search(r"<p class=Nivel1><span lang=EN-US>.*?(?=<p class=Nivel1><span>Introducción)",
                         html, re.S).group(0)
    invertido = html.replace(resumen + abstract, abstract + resumen)
    assert extraer_datos_basicos_word(invertido)["language"] == "Inglés"
    assert [a["lang"] for a in extraer_portada_word(invertido)["abstracts"]] == ["en", "es"]


# ── Recuadro "Sumario / Como citar" ──────────────────────────────────

def _primer_parrafo_del_resumen(html):
    return re.search(r"<h1[^>]*>(?:(?!</h1>).)*Resumen.*?</h1>\s*(<p.*?</p>)", html, re.S).group(1)


def _preparado(html):
    return sacar_recuadros_del_resumen(normalizar_titulos_word(html)[0])


def test_saca_el_cuadro_de_texto_del_resumen():
    html, movidos = _preparado(html_word())
    assert movidos == 1
    parrafo = _primer_parrafo_del_resumen(html)
    assert not re.search(r"<table|<v:|<img", parrafo)
    assert "Este es el resumen" in parrafo
    # El recuadro queda antes del título "Resumen", como en InDesign.
    recuadro = html.index("background:#F1F1F1")
    assert recuadro < html.index("Como citar:") < html.index("<h1 class=Nivel1><span class=normaltextrun>")
    assert sacar_recuadros_del_resumen(html) == (html, 0)


def test_datos_iguales_despues_de_mover_el_recuadro():
    html = html_word()
    preparado, _ = _preparado(html)
    assert extraer_portada_word(preparado) == extraer_portada_word(html)
    assert extraer_datos_basicos_word(preparado) == extraer_datos_basicos_word(html)


def test_saca_cuadro_vml_en_comentario_condicional():
    """Cuadro de texto con ajuste distinto de "arriba y abajo": VML dentro de
    un comentario condicional y una imagen de respaldo (Word 15)."""
    vml = ('<!--[if gte vml 1]><v:shape id="Cuadro_1"><v:textbox><![if !mso]><table><tr><td>'
           '<![endif]><div><p class=MsoNormal>Sumario: A.</p><p class=MsoNormal>Como citar: B.</p>'
           '</div><![if !mso]></td></tr></table><![endif]></v:textbox></v:shape><![endif]-->'
           '<![if !vml]><img src="index_archivos/image001.png" alt="Cuadro de texto: Sumario: A.">'
           '<![endif]>')
    html = re.sub(r"<o:wrapblock>.*?</o:wrapblock>", vml, html_word(), flags=re.S)
    preparado, movidos = _preparado(html)
    assert movidos == 1
    assert not re.search(r"<table|<v:|<img", _primer_parrafo_del_resumen(preparado))
    assert "<p class=MsoNormal>Como citar: B.</p>" in preparado


def test_saca_cuadro_exportado_como_imagen_en_web_filtrada():
    img = '<img width=534 height=81 src="index_archivos/image001.png" alt="Sumario: A.&#13;&#10;Como citar: B.&#13;&#10;">'
    html = re.sub(r"<o:wrapblock>.*?</o:wrapblock>", img, html_word(), flags=re.S)
    preparado, movidos = _preparado(html)
    assert movidos == 1
    assert "<img" not in _primer_parrafo_del_resumen(preparado)
    assert "<p class=MsoNormal>Sumario: A.</p>" in preparado
    assert "<p class=MsoNormal>Como citar: B.</p>" in preparado


def test_no_toca_imagenes_comunes_del_resumen():
    img = '<img src="index_archivos/image001.png" alt="Gráfico de barras">'
    html = re.sub(r"<o:wrapblock>.*?</o:wrapblock>", img, html_word(), flags=re.S)
    preparado, movidos = _preparado(html)
    assert movidos == 0
    assert img in preparado


# ── Integración con el ZIP ───────────────────────────────────────────

def _zip_de_word(tmp_path, charset="windows-1252"):
    zip_p = tmp_path / "index.zip"
    html = html_word(charset).replace("Artículos originales", "Artículos originales "
                                      "<img src=\"index_archivos/image001.png\">")
    with zipfile.ZipFile(zip_p, "w") as zf:
        zf.writestr("index.html", html.encode(charset))
        zf.writestr("index_archivos/image001.png", b"png")
    return zip_p


def test_parsers_de_html_py_delegan_en_word(tmp_path):
    zip_p = _zip_de_word(tmp_path)
    assert extract_article_data_from_html(str(zip_p))["title"].startswith("Título de prueba")
    full = extract_full_article_data_from_html(str(zip_p))
    assert [a["name"] for a in full["authors"]] == ["Ana Pérez", "Luis Gómez"]


def test_fix_zip_convierte_titulos_y_conserva_codificacion(tmp_path):
    corregido = fix_zip_for_amelica(str(_zip_de_word(tmp_path)))
    with zipfile.ZipFile(corregido) as zf:
        assert "index_files/image001.png" in zf.namelist()
        datos = zf.read("index.html")
    html, codificacion = decodificar_html(datos)
    assert codificacion == "windows-1252"
    assert "Título de prueba en español" in html
    assert "index_archivos/" not in html
    assert "Introducción" in h1s(html)
    assert not re.search(r"<table|<v:", _primer_parrafo_del_resumen(html))


# ── Marcaje sobre el HTML normalizado ────────────────────────────────

def test_marcaje_encuentra_las_secciones_de_word():
    playwright_api = pytest.importorskip("playwright.async_api")
    from amelica.portal.marker import AmelicaMarker
    from amelica.portal.uploader import AmelicaUploader

    html, _ = normalizar_titulos_word(html_word())
    cuerpo = re.search(r"<body[^>]*>(.*)</body>", html, re.S).group(1)

    async def extraer():
        async with playwright_api.async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(f'<html><body><div id="articuloIn">{cuerpo}</div></body></html>')
                up = AmelicaUploader.__new__(AmelicaUploader)
                up.page = page
                return await AmelicaMarker._extract_article_sections(up)
            finally:
                await browser.close()

    secciones = asyncio.run(extraer())
    assert [s["text"] for s in secciones] == [
        "Introducción", "Resultados y Discusión", "Conclusiones",
    ]
