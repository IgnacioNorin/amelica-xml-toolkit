#!/usr/bin/env python3
"""
idml_a_html.py — Convierte un artículo exportado de InDesign (.idml) a un
index.zip listo para subir a AmeliCA (HTML con títulos/tablas/figuras/
referencias bien identificados, imágenes optimizadas para web incluidas).

Uso:
    python idml_a_html.py articulo.idml
    python idml_a_html.py articulo.idml -o salida.zip

Requiere: Pillow (pip install Pillow)
"""

import re
import html as htmlmod
import os
import sys
import glob
import shutil
import zipfile
import argparse
import tempfile
import base64
import io
import html as htmlmod
from PIL import Image

STYLE_MAP = {
    "Nivel 1": "h1",
    "Nivel 2": "h2",
    "Nivel 3": "h3",
    "Normal": "p",
    "Referencias": "p",
    "paragraph": "p",
}
TABLE_MARK_STYLES = {"Tabla Titulo"}      # "Tabla 1", "Figura 1", etc. -> heading marcador
TABLE_SUBTITLE_STYLES = {"Tabla Subtitulo"}  # leyenda descriptiva de la tabla/figura

# Las stories de encabezado/pie de pagina repetido (nombre de revista,
# autores, ESPOL, marcador <?ACE 18?>) se excluyen a proposito: son
# artefactos de paginacion de InDesign/Word que no tienen sentido como texto
# suelto en un HTML sin paginas, y el propio flujo de validacion manual de
# la editorial las descarta.
#
# Los roles de cada story (cuerpo, caja Sumario/Como-citar, licencia CC,
# encabezado/pie) se identifican por su CONTENIDO, no por el ID que le puso
# InDesign (Story_u188c.xml, etc.) -- esos IDs no son estables entre
# archivos .idml distintos. Confirmado con 1393-RTE-38-1: todas sus stories
# tienen IDs completamente distintos a los del resto de articulos del mismo
# numero de revista, asi que con IDs fijos el cuerpo del articulo (y por lo
# tanto todo su procesamiento especial) se saltaba en silencio.

IMAGES_REL_PREFIX = "index_archivos"

# CSS embebido (extraido originalmente de un index.html real exportado de
# Word, y corregido para coincidir con lo que el IDML realmente define:
# alineacion de h2/h3 a la izquierda, negrita/cursiva correctas segun cada
# estilo de InDesign, etc). No se incluyen los archivos de soporte de Word
# (header.html, colorschememapping.xml, themedata.thmx) porque son
# artefactos de impresion que los navegadores ignoran -- si en algun
# momento se detecta que AmeliCA SI los necesita, se pueden volver a agregar.
CSS_BLOCK = r"""

<style>
<!--
 /* Font Definitions */
 @font-face
	{font-family:"Cambria Math";
	panose-1:2 4 5 3 5 4 6 3 2 4;
	mso-font-charset:0;
	mso-generic-font-family:roman;
	mso-font-pitch:variable;
	mso-font-signature:3 0 0 0 1 0;}
@font-face
	{font-family:Calibri;
	panose-1:2 15 5 2 2 2 4 3 2 4;
	mso-font-charset:0;
	mso-generic-font-family:swiss;
	mso-font-pitch:variable;
	mso-font-signature:-469750017 -1040178053 9 0 511 0;}
@font-face
	{font-family:Roboto;
	panose-1:0 0 0 0 0 0 0 0 0 0;
	mso-font-charset:0;
	mso-generic-font-family:auto;
	mso-font-pitch:variable;
	mso-font-signature:-536870161 1207967835 346030112 0 415 0;}
 /* Style Definitions */
 p.MsoNormal, li.MsoNormal, div.MsoNormal
	{mso-style-unhide:no;
	mso-style-qformat:yes;
	mso-style-parent:"";
	margin-top:0cm;
	margin-right:.3pt;
	margin-bottom:14.15pt;
	margin-left:0cm;
	text-align:justify;
	text-justify:inter-ideograph;
	text-indent:35.5pt;
	line-height:104%;
	mso-pagination:widow-orphan;
	font-size:12.0pt;
	mso-bidi-font-size:11.0pt;
	font-family:"Times New Roman",serif;
	mso-fareast-font-family:"Times New Roman";
	color:black;}
h1
	{mso-style-priority:9;
	mso-style-unhide:no;
	mso-style-qformat:yes;
	mso-style-parent:"";
	mso-style-link:"Título 1 Car";
	mso-style-next:Normal;
	margin-top:0cm;
	margin-right:.3pt;
	margin-bottom:0cm;
	margin-left:.5pt;
	text-align:center;
	text-indent:-.5pt;
	line-height:107%;
	mso-pagination:widow-orphan lines-together;
	page-break-after:avoid;
	mso-outline-level:1;
	font-size:12.0pt;
	mso-bidi-font-size:11.0pt;
	font-family:"Times New Roman",serif;
	mso-fareast-font-family:"Times New Roman";
	color:black;
	mso-font-kerning:0pt;
	mso-bidi-font-weight:normal;}
h2
	{mso-style-priority:9;
	mso-style-qformat:yes;
	mso-style-parent:"";
	mso-style-link:"Título 2 Car";
	mso-style-next:Normal;
	margin-top:0cm;
	margin-right:0cm;
	margin-bottom:.15pt;
	margin-left:.5pt;
	text-align:left;
	text-indent:-.5pt;
	line-height:105%;
	mso-pagination:widow-orphan lines-together;
	page-break-after:avoid;
	mso-outline-level:2;
	font-size:12.0pt;
	mso-bidi-font-size:11.0pt;
	font-family:"Times New Roman",serif;
	mso-fareast-font-family:"Times New Roman";
	color:black;
	font-weight:bold;
	font-style:normal;
	mso-bidi-font-style:normal;}
h3
	{margin-top:0cm;
	margin-right:0cm;
	margin-bottom:.15pt;
	margin-left:.5pt;
	text-align:left;
	line-height:105%;
	page-break-after:avoid;
	font-size:12.0pt;
	font-family:"Times New Roman",serif;
	color:black;
	font-weight:bold;
	font-style:italic;}
span.Ttulo1Car
	{mso-style-name:"Título 1 Car";
	mso-style-unhide:no;
	mso-style-locked:yes;
	mso-style-parent:"";
	mso-style-link:"Título 1";
	mso-ansi-font-size:12.0pt;
	font-family:"Times New Roman",serif;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	font-weight:bold;
	mso-bidi-font-weight:normal;}
span.Ttulo2Car
	{mso-style-name:"Título 2 Car";
	mso-style-unhide:no;
	mso-style-locked:yes;
	mso-style-parent:"";
	mso-style-link:"Título 2";
	mso-ansi-font-size:12.0pt;
	font-family:"Times New Roman",serif;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	font-style:italic;
	mso-bidi-font-style:normal;}
span.SpellE
	{mso-style-name:"";
	mso-spl-e:yes;}
.MsoChpDefault
	{mso-style-type:export-only;
	mso-default-props:yes;
	font-family:"Calibri",sans-serif;
	mso-ascii-font-family:Calibri;
	mso-ascii-theme-font:minor-latin;
	mso-fareast-font-family:"Times New Roman";
	mso-fareast-theme-font:minor-fareast;
	mso-hansi-font-family:Calibri;
	mso-hansi-theme-font:minor-latin;
	mso-bidi-font-family:"Times New Roman";
	mso-bidi-theme-font:minor-bidi;}
.MsoPapDefault
	{mso-style-type:export-only;
	margin-bottom:8.0pt;
	line-height:107%;}
 /* Page Definitions */
 @page
	{mso-footnote-separator:url("index_archivos/header.html") fs;
	mso-footnote-continuation-separator:url("index_archivos/header.html") fcs;
	mso-endnote-separator:url("index_archivos/header.html") es;
	mso-endnote-continuation-separator:url("index_archivos/header.html") ecs;
	mso-facing-pages:yes;}
@page WordSection1
	{size:595.3pt 841.9pt;
	margin:22.05pt 71.65pt 58.6pt 72.0pt;
	mso-header-margin:36.0pt;
	mso-footer-margin:23.2pt;
	mso-page-numbers:25;
	mso-title-page:yes;
	mso-even-header:url("index_archivos/header.html") eh1;
	mso-header:url("index_archivos/header.html") h1;
	mso-even-footer:url("index_archivos/header.html") ef1;
	mso-footer:url("index_archivos/header.html") f1;
	mso-first-header:url("index_archivos/header.html") fh1;
	mso-first-footer:url("index_archivos/header.html") ff1;
	mso-paper-source:0;}
div.WordSection1
	{page:WordSection1;}
@page WordSection2
	{size:595.3pt 841.9pt;
	margin:72.0pt 71.75pt 72.0pt 72.0pt;
	mso-header-margin:36.0pt;
	mso-footer-margin:23.2pt;
	mso-even-header:url("index_archivos/header.html") eh2;
	mso-header:url("index_archivos/header.html") h2;
	mso-even-footer:url("index_archivos/header.html") ef2;
	mso-footer:url("index_archivos/header.html") f2;
	mso-first-header:url("index_archivos/header.html") fh2;
	mso-first-footer:url("index_archivos/header.html") ff2;
	mso-paper-source:0;}
div.WordSection2
	{page:WordSection2;}
 /* List Definitions */
 @list l0
	{mso-list-id:178281053;
	mso-list-type:hybrid;
	mso-list-template-ids:-697521564 1328808904 2107774748 -776167638 -1376988532 86122780 -1955696188 -142033876 1535403920 -1640708878;}
@list l0:level1
	{mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:53.65pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level2
	{mso-level-number-format:alpha-lower;
	mso-level-text:%2;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:83.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level3
	{mso-level-number-format:roman-lower;
	mso-level-text:%3;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:119.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level4
	{mso-level-text:%4;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:155.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level5
	{mso-level-number-format:alpha-lower;
	mso-level-text:%5;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:191.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level6
	{mso-level-number-format:roman-lower;
	mso-level-text:%6;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:227.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level7
	{mso-level-text:%7;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:263.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level8
	{mso-level-number-format:alpha-lower;
	mso-level-text:%8;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:299.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
@list l0:level9
	{mso-level-number-format:roman-lower;
	mso-level-text:%9;
	mso-level-tab-stop:none;
	mso-level-number-position:left;
	margin-left:335.9pt;
	text-indent:0cm;
	mso-ansi-font-size:12.0pt;
	mso-bidi-font-size:12.0pt;
	mso-ascii-font-family:"Times New Roman";
	mso-fareast-font-family:"Times New Roman";
	mso-hansi-font-family:"Times New Roman";
	mso-bidi-font-family:"Times New Roman";
	color:black;
	border:none;
	mso-ansi-font-weight:normal;
	mso-ansi-font-style:normal;
	text-underline:black;
	text-decoration:none;
	text-underline:none;
	text-decoration:none;
	text-line-through:none;
	vertical-align:baseline;}
ol
	{margin-bottom:0cm;}
ul
	{margin-bottom:0cm;}
-->
</style>
"""

def unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&apos;", "'").replace("&quot;", '"'))


# Formatting defined by each IDML character style (Resources/Styles.xml),
# e.g. {"CharacterStyle/RTE_Bold": {"FontStyle": "Bold"}}. Filled by
# load_character_styles at the start of each conversion.
_CHAR_STYLE_FORMAT = {}
_CHAR_STYLE_KEYS = ("FontStyle", "Position", "PointSize")


def load_character_styles(styles_xml_path):
    """Read the IDML character styles and store the formatting each one
    defines (bold/italic, superscript/subscript, size), resolving BasedOn
    inheritance.

    Some IDML files do not mark formatting with local attributes on each
    CharacterStyleRange (FontStyle="Bold", Position="Superscript") but with
    named styles (CharacterStyle/RTE_Bold, RTE_Sup, RTE_Italic) whose
    formatting only lives in Styles.xml. Confirmed with 1602-RTE-38-E1:
    without this the title was not detected (no bold), affiliation numbers
    came out as plain text and every italic was lost."""
    _CHAR_STYLE_FORMAT.clear()
    try:
        with open(styles_xml_path, encoding="utf-8") as f:
            xml = f.read()
    except OSError:
        return

    own, parent = {}, {}
    style_pattern = re.compile(
        r'<CharacterStyle Self="([^"]*)"([^>]*?)(?:/>|>(.*?)</CharacterStyle>)', re.DOTALL
    )
    for self_id, attrs, inner in style_pattern.findall(xml):
        own[self_id] = {
            k: m.group(1) for k in _CHAR_STYLE_KEYS
            if (m := re.search(rf'\b{k}="([^"]*)"', attrs))
        }
        based_on = re.search(r'<BasedOn type="object">([^<]*)</BasedOn>', inner or "")
        if based_on:
            parent[self_id] = based_on.group(1)

    def resolve(style_id, seen):
        if style_id in seen or style_id not in own:
            return {}
        fmt = dict(resolve(parent[style_id], seen | {style_id})) if style_id in parent else {}
        fmt.update(own[style_id])
        return fmt

    for style_id in own:
        fmt = resolve(style_id, frozenset())
        if fmt:
            _CHAR_STYLE_FORMAT[style_id] = fmt


def _effective_char_attrs(style_id, attrs):
    """Add the formatting of the run's character style to its local
    attributes. Local attributes win, since they are overrides."""
    for key, value in _CHAR_STYLE_FORMAT.get(style_id, {}).items():
        if f'{key}="' not in attrs:
            attrs += f' {key}="{value}"'
    return attrs


def extract_runs(body):
    """Extrae los runs de un parrafo. Un CharacterStyleRange puede contener VARIOS
    <Content> separados por <Br/> en su interior (no solo uno) -- hay que partir ahi
    para no pegar texto de lados distintos del salto de linea."""
    runs = []
    char_pattern = re.compile(
        r'<CharacterStyleRange AppliedCharacterStyle="([^"]*)"([^>]*)>(.*?)</CharacterStyleRange>',
        re.DOTALL
    )
    for style_id, attrs, inner in char_pattern.findall(body):
        attrs = _effective_char_attrs(style_id, attrs)
        is_bold = 'FontStyle="Bold' in attrs
        is_italic = 'Italic' in attrs
        size_match = re.search(r'PointSize="([\d.]+)"', attrs)
        size = float(size_match.group(1)) if size_match else None

        # El texto de los enlaces (emails, ORCID) vive DENTRO de <HyperlinkTextSource>.
        # No hay que borrar el bloque (se perderia el email), solo quitar las etiquetas
        # y conservar el <Content> de adentro.
        # Guardamos ademas si este run es un hyperlink, para envolverlo en <a href>.
        is_hyperlink = 'AppliedCharacterStyle="CharacterStyle/Hyperlink"' in attrs or '<HyperlinkTextSource' in inner
        inner_clean = re.sub(r'<HyperlinkTextSource[^>]*>', '', inner)
        inner_clean = inner_clean.replace('</HyperlinkTextSource>', '')

        # Superindice / subindice (p.ej. el "1" de la afiliacion de cada autor).
        # Word no usa <sup> para esto: usa font-size chico (7pt), asi que replicamos eso.
        is_superscript = 'Position="Superscript"' in attrs
        is_subscript = 'Position="Subscript"' in attrs

        # Partir el contenido interno en segmentos separados por <Br/>, preservando
        # el mismo formato (bold/italic/size) para cada segmento.
        segments = re.split(r'<Br\s*/?>', inner_clean)
        for i, seg in enumerate(segments):
            texts = re.findall(r'<Content>(.*?)</Content>', seg, re.DOTALL)
            text = "".join(texts)
            is_last_segment = (i == len(segments) - 1)
            if text or not is_last_segment:
                runs.append({
                    "text": unescape(text),
                    "bold": is_bold,
                    "italic": is_italic,
                    "size": size,
                    "sup": is_superscript,
                    "sub": is_subscript,
                    "link": is_hyperlink,
                    # break_after=True si este segmento fue seguido de un <Br/>
                    # (es decir, no es el ultimo segmento del split)
                    "break_after": not is_last_segment,
                })
    return runs


def runs_to_html(runs):
    """Convierte una lista de runs a HTML inline, preservando bold/italic, escapando el texto."""
    parts = []
    for idx, r in enumerate(runs):
        if not r["text"]:
            # Un run vacio con break_after es un salto de linea suelto
            if r.get("break_after") and idx < len(runs) - 1:
                parts.append("<br>")
            continue
        t = htmlmod.escape(r["text"])
        if r["bold"]:
            t = f"<strong>{t}</strong>"
        if r["italic"]:
            t = f"<em>{t}</em>"
        # Word marca el numero de afiliacion y los ORCID como texto chico (7pt),
        # no con <sup>. Replicamos ese patron para que se vea igual.
        if r.get("sup") or r.get("sub"):
            t = f"<span style=\"font-size:7.0pt;line-height:107%\">{t}</span>"
        # Los hyperlinks (ORCID, emails) van como <a href> reales.
        if r.get("link"):
            url = r["text"].strip()
            if url.startswith("http"):
                href = url
            elif "@" in url:
                href = f"mailto:{url}"
            else:
                href = None
            if href:
                t = f'<a href="{htmlmod.escape(href, quote=True)}">{t}</a>'
        parts.append(t)
        # Un <Br/> del IDML dentro de un parrafo normal es un salto de linea real
        # (p.ej. separa la afiliacion del email). En listas/referencias el break se
        # usa para partir items, y ahi se maneja aparte antes de llamar a esta funcion.
        if r.get("break_after") and idx < len(runs) - 1:
            parts.append("<br>")
    return "".join(parts)


def parse_table(table_xml):
    """Parsea un bloque <Table ...>...</Table> completo y devuelve (n_rows, n_cols,
    dict{(r,c): {"text":..., "rowspan":..., "colspan":...}})."""
    rows_m = re.search(r'BodyRowCount="(\d+)"', table_xml)
    cols_m = re.search(r'ColumnCount="(\d+)"', table_xml)
    n_rows = int(rows_m.group(1)) if rows_m else 0
    n_cols = int(cols_m.group(1)) if cols_m else 0

    cells = {}
    max_row, max_col = 0, 0
    cell_pattern = re.compile(
        r'<Cell Self="[^"]*" Name="(\d+):(\d+)" RowSpan="(\d+)" ColumnSpan="(\d+)"[^>]*>(.*?)</Cell>',
        re.DOTALL
    )
    for col_s, row_s, rowspan, colspan, body in cell_pattern.findall(table_xml):
        # OJO: en el atributo Name="X:Y" de InDesign, X es la COLUMNA e Y es la FILA
        # (al reves de lo que parece a simple vista). Confirmado comparando el
        # BodyRowCount/ColumnCount reales contra el rango de indices de las celdas.
        r, c = int(row_s), int(col_s)
        para_pattern = re.compile(
            r'<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/[^"]*"[^>]*>(.*?)</ParagraphStyleRange>',
            re.DOTALL
        )
        paras = para_pattern.findall(body)
        texts = []
        for p in paras:
            runs = extract_runs(p)
            t = "".join(r["text"] for r in runs).strip()
            if t:
                texts.append(t)
        text = " ".join(texts)
        cells[(r, c)] = {"text": text, "rowspan": int(rowspan), "colspan": int(colspan)}
        max_row, max_col = max(max_row, r), max(max_col, c)

    n_rows = max(n_rows, max_row + 1)
    n_cols = max(n_cols, max_col + 1)
    return n_rows, n_cols, cells


def table_to_html(n_rows, n_cols, cells):
    """Genera un <table> HTML real a partir de la estructura parseada."""
    if n_rows == 0 or n_cols == 0:
        return ""
    covered = set()  # celdas ocupadas por un rowspan/colspan anterior
    rows_html = []
    for r in range(n_rows):
        cells_html = []
        for c in range(n_cols):
            if (r, c) in covered:
                continue
            info = cells.get((r, c))
            if info is None:
                cells_html.append('<td style="border:1px solid black;padding:3pt;">&nbsp;</td>')
                continue
            span_attrs = ""
            if info["rowspan"] > 1:
                span_attrs += f' rowspan="{info["rowspan"]}"'
            if info["colspan"] > 1:
                span_attrs += f' colspan="{info["colspan"]}"'
            for rr in range(r, r + info["rowspan"]):
                for cc in range(c, c + info["colspan"]):
                    if (rr, cc) != (r, c):
                        covered.add((rr, cc))
            text = htmlmod.escape(info["text"])
            cell_style = "border:1px solid black;padding:3pt;text-align:center;"
            if r == 0:
                cells_html.append(f'<td{span_attrs} style="{cell_style}"><b>{text}</b></td>')
            else:
                cells_html.append(f'<td{span_attrs} style="{cell_style}">{text}</td>')
        rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
    return (
        '<table class="MsoNormalTable" border="1" cellspacing="0" cellpadding="3" '
        'style="border-collapse:collapse;margin-left:auto;margin-right:auto;">'
        + "".join(rows_html) + "</table>"
    )


def extract_image_as_file(image_xml, image_id, out_dir, rel_prefix, max_width=1600, jpeg_quality=85):
    """Extrae los bytes de un elemento <Image>...</Image> del IDML, los redimensiona
    y comprime, y los guarda como archivo real dentro de out_dir. Devuelve la ruta
    relativa (rel_prefix/nombre.ext) para usar en <img src="...">, o None si fallo.
    InDesign puede partir los datos binarios grandes en varios bloques CDATA
    consecutivos (<![CDATA[...]]><![CDATA[...]]>), asi que hay que unirlos
    todos antes de decodificar, no solo tomar el primero.
    Las imagenes originales suelen venir a resolucion de impresion (miles de px
    de ancho); para uso web se reducen a max_width y se recomprimen, lo que baja
    el peso ~80% sin perdida visible en pantalla. Se usa JPEG para imagenes sin
    transparencia real (mucho mas liviano) y PNG solo cuando hace falta alpha.
    Se guardan como archivo (no data URI) porque AmeliCA solo detecta imagenes
    para su galeria cuando el <img src> apunta a un archivo real del paquete."""
    contents_match = re.search(r'<Contents>(.*?)</Contents>', image_xml, re.DOTALL)
    if not contents_match:
        return None
    inner = contents_match.group(1)
    inner = inner.replace('<![CDATA[', '').replace(']]>', '')
    b64_data = re.sub(r'\s+', '', inner)
    if len(b64_data) % 4 != 0 or not b64_data:
        return None

    raw_bytes = base64.b64decode(b64_data)
    os.makedirs(out_dir, exist_ok=True)
    try:
        im = Image.open(io.BytesIO(raw_bytes))
        im.load()
    except Exception:
        # Si no se puede procesar con PIL, se guarda el original sin optimizar
        # antes que perder la imagen por completo.
        ext = "jpg" if 'JPEG' in image_xml[:600] else "png"
        fname = f"{image_id}.{ext}"
        with open(os.path.join(out_dir, fname), "wb") as f:
            f.write(raw_bytes)
        return f"{rel_prefix}/{fname}"

    if im.width > max_width:
        ratio = max_width / im.width
        im = im.resize((max_width, int(im.height * ratio)), Image.LANCZOS)

    alpha_used = im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255

    if alpha_used:
        fname = f"{image_id}.png"
        im.save(os.path.join(out_dir, fname), "PNG", optimize=True)
    else:
        fname = f"{image_id}.jpg"
        im.convert("RGB").save(os.path.join(out_dir, fname), "JPEG", quality=jpeg_quality, optimize=True)

    return f"{rel_prefix}/{fname}"


def convert_story(path, html_parts, images_dir):
    """Convierte una story del IDML a HTML, agregando el resultado a html_parts."""
    content = open(path, encoding="utf-8").read()

    # Sacar las tablas del flujo (no las reconstruimos, solo evitamos que sus 100s de
    # parrafos de celdas contaminen el texto corrido). Dejamos un marcador para saber
    # que hubo una tabla ahi, aunque el titulo real ya viene aparte por "Tabla Titulo".
    table_blocks = []

    def stash_table(m):
        table_blocks.append(m.group(0))
        return f"@@TABLE@@{len(table_blocks)-1}@@"

    content_no_tables = re.sub(r'<Table .*?</Table>', stash_table, content, flags=re.DOTALL)

    # Sacar las imagenes embebidas del flujo tambien, para insertarlas como <img>
    # real en el lugar correcto (justo donde InDesign las tenia ancladas).
    image_blocks = []

    def stash_image(m):
        image_blocks.append(m.group(0))
        return f"@@IMAGE@@{len(image_blocks)-1}@@"

    content_no_tables = re.sub(r'<Image .*?</Image>', stash_image, content_no_tables, flags=re.DOTALL)

    para_pattern = re.compile(
        r'<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/([^"]*)"([^>]*)>(.*?)</ParagraphStyleRange>',
        re.DOTALL
    )
    matches = para_pattern.findall(content_no_tables)
    print(f"  {os.path.basename(path)}: {len(matches)} parrafos, {len(table_blocks)} tablas, {len(image_blocks)} imagenes")

    for style_name, para_attrs, body in matches:
        # Si el parrafo tiene el marcador de una imagen embebida, insertamos el <img>
        # real en su lugar.
        if "@@IMAGE@@" in body:
            m = re.search(r'@@IMAGE@@(\d+)@@', body)
            if m:
                idx = int(m.group(1))
                image_xml = image_blocks[idx]
                id_match = re.search(r'<Image Self="([^"]*)"', image_xml)
                image_id = id_match.group(1) if id_match else f"img{idx}"
                rel_path = extract_image_as_file(image_xml, image_id, images_dir, IMAGES_REL_PREFIX)
                if rel_path:
                    html_parts.append(
                        f'<p style="text-align:center;"><img src="{rel_path}" '
                        f'style="max-width:100%;height:auto;"></p>'
                    )
            continue

        # Si el parrafo es (casi) solo el marcador de una tabla, insertamos la
        # tabla real en su lugar (su titulo/caption real ya viene aparte por
        # "Tabla Titulo"/"Tabla Subtitulo", no hay que duplicarlo aca).
        if "@@TABLE@@" in body:
            m = re.search(r'@@TABLE@@(\d+)@@', body)
            if m:
                idx = int(m.group(1))
                n_rows, n_cols, cells = parse_table(table_blocks[idx])
                table_html = table_to_html(n_rows, n_cols, cells)
                if table_html:
                    html_parts.append(table_html)
            continue

        runs = extract_runs(body)
        full_text = "".join(r["text"] for r in runs).strip()
        if not full_text:
            continue

        # Titulo de tabla/figura ("Tabla 1", "Figura 3", etc.) -> heading marcador de posicion.
        # En el IDML, "Tabla Titulo" y "Tabla Subtitulo" van siempre centrados
        # (Justification="CenterAlign" en Resources/Styles.xml), asi que se fuerza
        # el centrado explicito aca en vez de depender de lo que herede la clase.
        if style_name in TABLE_MARK_STYLES:
            html_parts.append(f'<h1 class="table-figure-marker" style="text-align:center;">{htmlmod.escape(full_text)}</h1>')
            continue
        if style_name in TABLE_SUBTITLE_STYLES:
            # No usar solo la sangria de primera linea de MsoNormal (35.5pt): eso hace
            # que la primera linea del caption arranque mas a la derecha que el resto,
            # rompiendo el centrado parejo. Se anula la sangria explicitamente aca.
            html_parts.append(
                f'<p class="table-figure-caption MsoNormal" '
                f'style="text-align:center;text-indent:0;">'
                f'<em>{htmlmod.escape(full_text)}</em></p>'
            )
            continue

        # Referencias: en el IDML todas las referencias de un bloque estan en el MISMO
        # parrafo, separadas por <Br/> (no un ParagraphStyleRange por referencia).
        # Hay que partir por el break, o AmeliCA las detecta como una sola referencia gigante.
        if style_name == "Referencias":
            groups, current = [], []
            for r in runs:
                current.append(r)
                if r["break_after"]:
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)
            for group in groups:
                text_in_group = "".join(r["text"] for r in group).strip()
                if text_in_group:
                    html_parts.append(f'<p class="reference MsoNormal">{runs_to_html(group)}</p>')
            continue


        # Titulo del articulo: Normal + bold + tamaño grande, separado por <Br/>
        looks_like_title = (
            style_name == "Normal"
            and any(r["bold"] and (r["size"] or 0) >= 15 for r in runs)
        )
        if looks_like_title:
            # The <Br/> between the two titles may sit in a run that is not
            # bold/large (confirmed in 1645-RTE-38-E1), so every run's break
            # splits groups, but only bold/large runs contribute text.
            groups, current = [], []
            for r in runs:
                if r["bold"] and (r["size"] or 0) >= 15:
                    current.append(r)
                if r["break_after"] and current:
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)
            for group in groups:
                text_in_group = "".join(r["text"] for r in group).strip()
                if text_in_group:
                    html_parts.append(
                        f'<p class="MsoNormal article-title" style="text-align:center;">'
                        f'<b style="mso-bidi-font-weight:normal"><span style="font-size:16.0pt;line-height:103%">'
                        f'{runs_to_html(group)}</span></b></p>'
                    )
            continue

        tag = STYLE_MAP.get(style_name, "p")

        # Listas: InDesign marca la lista con BulletsAndNumberingListType en el
        # ParagraphStyleRange (NO con un estilo de parrafo llamado "Lista"), y varios
        # items suelen venir en el MISMO parrafo separados por <Br/>.
        list_type = None
        if 'BulletsAndNumberingListType="NumberedList"' in para_attrs:
            list_type = "ol"
        elif 'BulletsAndNumberingListType="BulletList"' in para_attrs:
            list_type = "ul"

        if list_type:
            groups, current = [], []
            for r in runs:
                current.append(r)
                if r["break_after"]:
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)
            items = []
            for group in groups:
                text_in_group = "".join(r["text"] for r in group).strip()
                if text_in_group:
                    items.append(f"<li>{runs_to_html(group)}</li>")
            if items:
                # InDesign parte una misma lista en varios ParagraphStyleRange.
                # Si el bloque anterior ya era una lista del mismo tipo, fusionamos
                # para que la numeracion siga (1,2,3,4) en vez de reiniciarse.
                if html_parts and html_parts[-1].endswith(f"</{list_type}>"):
                    html_parts[-1] = html_parts[-1][: -len(f"</{list_type}>")] + "".join(items) + f"</{list_type}>"
                else:
                    html_parts.append(f"<{list_type}>" + "".join(items) + f"</{list_type}>")
            continue

        if tag in ("h1", "h2", "h3"):
            html_parts.append(f"<{tag}>{htmlmod.escape(full_text)}</{tag}>")
        else:
            # Alineacion: el IDML la trae en Justification del ParagraphStyleRange.
            align_map = {
                "RightAlign": "right",
                "CenterAlign": "center",
                "LeftAlign": "left",
                "LeftJustified": "justify",
                "FullyJustified": "justify",
                "CenterJustified": "justify",
            }
            align_css = ""
            m = re.search(r'Justification="([^"]*)"', para_attrs)
            if m and m.group(1) in align_map:
                align_css = f' style="text-align:{align_map[m.group(1)]};"'
            html_parts.append(f'<p class="MsoNormal"{align_css}>{runs_to_html(runs)}</p>')


def _merge_cc_with_dates(body_parts, cc_license_html):
    """Busca los parrafos 'Enviado:'/'Aceptado:'/'Publicado:' en el cuerpo del
    articulo y los combina con la licencia CC en una tabla de 2 columnas
    (licencia a la izquierda en texto chico, fechas a la derecha), como en el
    diseno original en InDesign/Word."""
    date_idx = [i for i, p in enumerate(body_parts) if "Enviado:" in p]
    if not date_idx or not cc_license_html:
        # Si no se encuentran las fechas o no hay licencia, no se combina nada;
        # se deja el cuerpo tal cual para no perder contenido.
        return "\n".join(body_parts)

    start = date_idx[0]
    # Las fechas son 3 parrafos consecutivos (Enviado/Aceptado/Publicado).
    end = start
    while end < len(body_parts) and any(
        k in body_parts[end] for k in ("Enviado:", "Aceptado:", "Publicado:")
    ):
        end += 1
    dates_html = "\n".join(body_parts[start:end])

    merged_table = (
        '<table style="border-collapse:collapse;width:100%;" cellpadding="0" cellspacing="0">'
        '<tr>'
        '<td style="vertical-align:top;text-align:justify;text-justify:inter-ideograph;width:50%;">'
        f'<div style="font-size:7.0pt;line-height:107%">{cc_license_html}</div>'
        '</td>'
        f'<td style="vertical-align:top;text-align:right;width:50%;">{dates_html}</td>'
        '</tr></table>'
    )
    return "\n".join(body_parts[:start]) + "\n" + merged_table + "\n" + "\n".join(body_parts[end:])


def _promote_secondary_title(body_parts):
    """El titulo traducido (la segunda lengua, sea ES o EN) a veces viene en
    una tipografia mas chica en el IDML original y no llega al umbral de
    15pt de 'looks_like_title', asi que sale como parrafo comun sin la clase
    article-title. extract_full_article_data_from_html (que arma el front
    matter) solo mira parrafos con esa clase, asi que el titulo secundario
    se pierde en silencio -- confirmado con un articulo real (1386-RTE-38-1)
    cuyo titulo principal es ingles y el traducido en español quedaba como
    <p class="MsoNormal"><strong>...</strong></p> normal.

    Se detecta por posicion: el parrafo que sigue INMEDIATAMENTE al titulo
    principal, si esta enteramente envuelto en un solo <strong>/<b> (sin
    links ni spans de superindice de afiliacion -- eso ya es la linea de
    autores, no el titulo), se promueve agregandole la clase article-title."""
    patron = re.compile(
        r'^<p class="([^"]*)"([^>]*)>(?:<strong>|<b\b[^>]*>)(.*)(?:</strong>|</b>)</p>$',
        re.DOTALL,
    )
    for i, p in enumerate(body_parts):
        if 'article-title' not in p:
            continue
        if i + 1 >= len(body_parts):
            break
        candidate = body_parts[i + 1].strip()
        m = patron.match(candidate)
        if not m or 'href=' in m.group(3) or '<span' in m.group(3):
            break
        clase, resto_attrs = m.group(1), m.group(2)
        body_parts[i + 1] = candidate.replace(
            f'<p class="{clase}"{resto_attrs}>',
            f'<p class="{clase} article-title"{resto_attrs}>',
            1,
        )
        break
    return body_parts


_PAGINATION_MARKER_RE = re.compile(r'^<\?.*\?>$')


def _strip_pagination_markers(body_parts):
    """Descarta parrafos que son enteramente un marcador de paginacion de
    InDesign, ej. "<?ACE 18?>" (el codigo de encabezado repetido de
    pagina). Las stories de encabezado/pie dedicadas ya se excluyen aparte
    (ver _classify_stories), pero a veces InDesign deja este marcador colado inline en
    el flujo del cuerpo en vez de en su propia story -- confirmado con un
    articulo real (1393-RTE-38-1), donde aparecia dos veces justo al
    principio del cuerpo, antes de autores y antes del titulo."""
    resultado = []
    for p in body_parts:
        texto = htmlmod.unescape(re.sub(r'<[^>]+>', '', p)).strip()
        if _PAGINATION_MARKER_RE.match(texto):
            continue
        resultado.append(p)
    return resultado


def _insert_summary_box(body_parts, summary_box_html):
    """Inserta el bloque Sumario/Como citar justo antes del heading 'Resumen'
    (o 'Abstract' si no hay Resumen) dentro del cuerpo del articulo."""
    if not summary_box_html:
        return body_parts
    target_idx = None
    for i, p in enumerate(body_parts):
        if p.strip() == "<h1>Resumen</h1>":
            target_idx = i
            break
    if target_idx is None:
        for i, p in enumerate(body_parts):
            if p.strip() == "<h1>Abstract</h1>":
                target_idx = i
                break
    if target_idx is None:
        # Ni Resumen ni Abstract encontrados: se antepone al inicio del cuerpo
        # para no perder el contenido.
        return [summary_box_html] + body_parts
    return body_parts[:target_idx] + [summary_box_html] + body_parts[target_idx:]


def _separate_stacked_headings(body_parts):
    """AmeliCA fusiona un heading con el que le sigue inmediatamente sin
    ningun parrafo de texto en el medio, tratandolos como una sola unidad de
    marcaje en vez de dos niveles independientes. Se inserta un parrafo vacio
    entre ambos para forzar que se reconozcan por separado.
    Ojo: la deteccion es por el NOMBRE del tag via regex, no por el string
    exacto "<h1>" -- los h1 de titulo/tabla/figura llevan atributos
    (class=, style=) y "startswith('<h1>')" no los detecta, dejando el
    separador sin insertar justo en esos casos."""
    result = []
    heading_re = re.compile(r'^<h[123][ >]')
    for i, p in enumerate(body_parts):
        result.append(p)
        stripped = p.strip()
        is_heading = bool(heading_re.match(stripped))
        if is_heading and i + 1 < len(body_parts):
            next_stripped = body_parts[i + 1].strip()
            next_is_heading = bool(heading_re.match(next_stripped))
            if next_is_heading:
                result.append('<p class="MsoNormal">&nbsp;</p>')
    return result


def _story_text(path):
    """Texto plano (sin tags) de una story, para clasificarla por contenido."""
    content = open(path, encoding="utf-8").read()
    texts = re.findall(r'<Content>(.*?)</Content>', content, re.DOTALL)
    return htmlmod.unescape(" ".join(texts)).strip()


def _classify_stories(available):
    """Identifica el rol de cada story por su contenido: la caja
    Sumario/Como-citar empieza con "Summary:"/"Sumario:", la licencia
    menciona "Creative Commons", y el cuerpo del articulo es, por lejos,
    la story con mas texto (cientos de parrafos vs. un puñado en el resto).
    Todo lo que no cae en ninguno de esos tres roles es encabezado/pie de
    pagina repetido y se excluye. Ver comentario arriba de por que no se usa
    el ID de story de InDesign para esto."""
    texts = {sid: _story_text(path) for sid, path in available.items()}

    summary_box_id = None
    cc_license_id = None
    for sid, text in texts.items():
        if re.match(r'^(summary|sumario)\s*:', text, re.IGNORECASE):
            summary_box_id = sid
        elif "Creative Commons" in text:
            cc_license_id = sid

    remaining = {
        sid: text for sid, text in texts.items()
        if sid not in (summary_box_id, cc_license_id)
    }
    if not remaining:
        raise RuntimeError(
            "No se pudo identificar el cuerpo del articulo entre las "
            "stories del .idml"
        )
    body_id = max(remaining, key=lambda sid: len(remaining[sid]))

    excluded_ids = {
        sid for sid in available
        if sid not in (body_id, summary_box_id, cc_license_id)
    }
    return body_id, summary_box_id, cc_license_id, excluded_ids


def convert_idml_to_html_parts(stories_dir, images_dir):
    """Recorre todas las stories de un IDML ya descomprimido y devuelve el
    HTML del <body> ya armado (string)."""
    html_parts = []

    # Procesar todas las stories del IDML, en el orden de lectura definido.
    # Cualquier story que exista en el archivo pero no tenga un rol especial
    # identificado se agrega igual al final, para no perder contenido.
    available = {}
    for path in glob.glob(os.path.join(stories_dir, "Story_*.xml")):
        story_id = os.path.basename(path).replace("Story_", "").replace(".xml", "")
        available[story_id] = path

    if not available:
        raise RuntimeError(
            f"No se encontraron stories en {stories_dir} -- "
            "¿el .idml se descomprimió correctamente?"
        )

    body_id, summary_box_id, cc_license_id, excluded_ids = _classify_stories(available)

    ordered_ids = [sid for sid in (summary_box_id, cc_license_id, body_id) if sid]
    ordered_ids += [
        sid for sid in available
        if sid not in ordered_ids and sid not in excluded_ids
    ]
    if excluded_ids:
        print("Stories excluidas (encabezado/pie de pagina):", ", ".join(sorted(excluded_ids)))

    print("Procesando stories:")
    cc_license_html = ""
    summary_box_html = ""
    for story_id in ordered_ids:
        if story_id == summary_box_id:
            # Bloque "Sumario / Como citar": se guarda para insertarlo justo antes
            # del heading "Resumen" (o "Abstract" si no hay Resumen) dentro del
            # cuerpo del articulo, con el mismo recuadro gris del original.
            box_parts = []
            convert_story(available[story_id], box_parts, images_dir)
            box_html = "\n".join(box_parts)
            summary_box_html = (
                '<div style="mso-element:para-border-div;border:none;'
                'border-bottom:solid black 1.5pt;padding:0cm 0cm 0cm 0cm;'
                'background:#F1F1F1;margin-left:3.1pt;margin-right:0cm">\n'
                + box_html + "\n</div>"
            )
            print(f"  {os.path.basename(available[story_id])}: guardado para insertar antes de Resumen/Abstract")
        elif story_id == cc_license_id:
            # Licencia Creative Commons: no se inserta sola en el flujo; se guarda
            # para combinarla con las fechas (Enviado/Aceptado/Publicado) en una
            # tabla de dos columnas, como en el original.
            cc_parts = []
            convert_story(available[story_id], cc_parts, images_dir)
            cc_license_html = "\n".join(cc_parts)
            print(f"  {os.path.basename(available[story_id])}: guardado para combinar con fechas")
        elif story_id == body_id:
            body_parts = []
            convert_story(available[story_id], body_parts, images_dir)
            body_parts = _strip_pagination_markers(body_parts)
            body_parts = _separate_stacked_headings(body_parts)
            body_parts = _promote_secondary_title(body_parts)
            body_parts = _insert_summary_box(body_parts, summary_box_html)
            html_parts.append(_merge_cc_with_dates(body_parts, cc_license_html))
        else:
            convert_story(available[story_id], html_parts, images_dir)

    return "\n".join(html_parts)


def build_index_zip(idml_path, output_zip_path):
    """Flujo completo: descomprime el .idml, genera el HTML+imagenes, y
    empaqueta todo en un .zip listo para subir a AmeliCA."""
    with tempfile.TemporaryDirectory(prefix="idml_a_html_") as tmpdir:
        extract_dir = os.path.join(tmpdir, "idml_extracted")
        os.makedirs(extract_dir, exist_ok=True)
        print(f"Descomprimiendo {idml_path} ...")
        with zipfile.ZipFile(idml_path, "r") as zf:
            zf.extractall(extract_dir)

        stories_dir = os.path.join(extract_dir, "Stories")
        if not os.path.isdir(stories_dir):
            raise RuntimeError(
                f"No se encontró la carpeta Stories/ dentro de {idml_path} -- "
                "¿es un .idml valido? (Archivo > Exportar > InDesign Markup en InDesign)"
            )

        load_character_styles(os.path.join(extract_dir, "Resources", "Styles.xml"))

        out_dir = os.path.join(tmpdir, "index_zip_contents")
        images_dir = os.path.join(out_dir, IMAGES_REL_PREFIX)
        os.makedirs(images_dir, exist_ok=True)

        body_html = convert_idml_to_html_parts(stories_dir, images_dir)

        doc = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Articulo</title>
{CSS_BLOCK}
</head>
<body>
{body_html}
</body>
</html>
"""
        html_path = os.path.join(out_dir, "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(doc)

        # Empaquetar todo (index.html + index_archivos/*) en el .zip final.
        os.makedirs(os.path.dirname(os.path.abspath(output_zip_path)) or ".", exist_ok=True)
        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(out_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, out_dir)
                    zf.write(fpath, arcname)

        n_images = len(glob.glob(os.path.join(images_dir, "*")))
        size_kb = os.path.getsize(output_zip_path) / 1024
        print(f"\nListo: {output_zip_path} ({size_kb:.0f} KB, {n_images} imagen(es))")


def main():
    parser = argparse.ArgumentParser(
        description="Convierte un .idml de InDesign a un index.zip listo para AmeliCA."
    )
    parser.add_argument("idml", help="Archivo .idml de entrada")
    parser.add_argument(
        "-o", "--output",
        help="Ruta del .zip de salida (default: <nombre_del_idml>_index.zip)",
        default=None,
    )
    args = parser.parse_args()

    if not os.path.exists(args.idml):
        print(f"Archivo no encontrado: {args.idml}")
        sys.exit(1)

    output_zip = args.output
    if not output_zip:
        base = os.path.splitext(os.path.basename(args.idml))[0]
        output_zip = f"{base}_index.zip"

    build_index_zip(args.idml, output_zip)


if __name__ == "__main__":
    main()
