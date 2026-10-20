"""
Regresion: algunos IDML (1602, 1603, 1605, 1606 y 1645 de RTE-38-E1) marcan
la negrita, cursiva y superindice con estilos de caracter con nombre
(CharacterStyle/RTE_Bold, RTE_Sup, RTE_Italic) en vez de atributos sueltos
en cada CharacterStyleRange. Sin leer Resources/Styles.xml el titulo no se
reconocia y el articulo se daba de alta como "Título del artículo", sin
autores.
"""

import os

import pytest

from amelica.idml import converter
from amelica.idml.converter import extract_runs, load_character_styles


STYLES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<idPkg:Styles xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging">
<RootCharacterStyleGroup Self="u7a">
<CharacterStyle Self="CharacterStyle/$ID/[No character style]" Name="$ID/[No character style]" />
<CharacterStyle Self="CharacterStyle/Hyperlink" Name="Hyperlink" PointSize="9">
<Properties><BasedOn type="string">$ID/[No character style]</BasedOn></Properties>
</CharacterStyle>
<CharacterStyle Self="CharacterStyle/RTE_Bold" Name="RTE_Bold" FontStyle="Bold">
<Properties><BasedOn type="string">$ID/[No character style]</BasedOn></Properties>
</CharacterStyle>
<CharacterStyle Self="CharacterStyle/RTE_Sup" Name="RTE_Sup" Position="Superscript">
<Properties><BasedOn type="string">$ID/[No character style]</BasedOn></Properties>
</CharacterStyle>
<CharacterStyle Self="CharacterStyle/RTE_ORCID" Name="RTE_ORCID" Position="Superscript">
<Properties><BasedOn type="object">CharacterStyle/Hyperlink</BasedOn></Properties>
</CharacterStyle>
</RootCharacterStyleGroup>
</idPkg:Styles>
"""

TITLE_PARA = """<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/Normal" Justification="CenterAlign">
<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_Bold" PointSize="16">
<Content>Titulo en espanol</Content>
</CharacterStyleRange>
<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
<Br />
</CharacterStyleRange>
<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_Bold" PointSize="16">
<Content>Title in English</Content>
</CharacterStyleRange>
</ParagraphStyleRange>"""


@pytest.fixture
def estilos(tmp_path):
    path = tmp_path / "Styles.xml"
    path.write_text(STYLES_XML, encoding="utf-8")
    load_character_styles(str(path))
    yield
    converter._CHAR_STYLE_FORMAT.clear()


def test_estilo_con_nombre_aplica_negrita_y_superindice(estilos):
    body = (
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_Bold" PointSize="16">'
        '<Content>Titulo</Content></CharacterStyleRange>'
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_Sup">'
        '<Content>1</Content></CharacterStyleRange>'
    )
    titulo, sup = extract_runs(body)

    assert titulo["bold"] and titulo["size"] == 16.0
    assert sup["sup"] and not sup["bold"]


def test_herencia_based_on_y_override_local(estilos):
    body = (
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_ORCID">'
        '<Content>a</Content></CharacterStyleRange>'
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_ORCID" PointSize="7">'
        '<Content>b</Content></CharacterStyleRange>'
    )
    heredado, override = extract_runs(body)

    assert heredado["size"] == 9.0 and heredado["sup"]
    assert override["size"] == 7.0


def test_titulos_separados_por_br_en_run_sin_negrita(estilos, tmp_path):
    story = tmp_path / "Story_u1.xml"
    story.write_text(f"<Story>{TITLE_PARA}</Story>", encoding="utf-8")
    html_parts = []
    converter.convert_story(str(story), html_parts, str(tmp_path))

    titulos = [p for p in html_parts if "article-title" in p]
    assert len(titulos) == 2
    assert "Titulo en espanol" in titulos[0] and "Title in English" in titulos[1]


def test_sin_styles_xml_no_falla(tmp_path):
    load_character_styles(os.path.join(str(tmp_path), "no_existe.xml"))
    runs = extract_runs(
        '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/RTE_Bold">'
        '<Content>x</Content></CharacterStyleRange>'
    )
    assert not runs[0]["bold"]
