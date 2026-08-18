"""
html.py — Extraccion de metadatos desde el index.html dentro del ZIP.

`extract_article_data_from_html` devuelve lo minimo para crear el articulo
(titulo, idioma, paginas). `extract_full_article_data_from_html` devuelve
ademas autores, afiliaciones, resumen y palabras clave, para el front matter.
"""

import re
import zipfile
import html as htmlmod
from pathlib import Path


def extract_article_data_from_html(zip_path: str) -> dict:
    """
    Extrae del index.html (generado por convertir_html.py) los datos reales
    del articulo: titulo, idioma, paginas. A diferencia de extract_article_data
    (que adivina desde un .docx generico con heuristicas de tamaño/negrita),
    esta funcion lee directamente las clases que nuestro propio generador ya
    puso ahi a proposito (article-title, el parrafo "Como citar"), asi que
    no hace falta adivinar nada.
    """
    import zipfile as _zipfile

    defaults = {
        'title': 'Título del artículo', 'article_type': 'Artículo científico',
        'section': 'Artículos', 'language': 'Español',
        'citation': 'APA', 'page_start': '', 'page_end': '',
    }

    try:
        with _zipfile.ZipFile(zip_path, 'r') as zf:
            html_name = next((n for n in zf.namelist() if n.endswith('index.html')), None)
            if not html_name:
                return defaults
            html = zf.read(html_name).decode('utf-8', errors='replace')
    except Exception:
        return defaults

    # Titulo: el primer <p class="... article-title ..."> es el titulo en
    # español (o el unico, si el articulo esta solo en ingles). Se le saca
    # el markup interno (negrita, cursiva de nombres cientificos, etc).
    title = defaults['title']
    title_match = re.search(
        r'<p class="[^"]*article-title[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL
    )
    if title_match:
        raw = title_match.group(1)
        title = re.sub(r'<[^>]+>', '', raw).strip()
        title = re.sub(r'\s+', ' ', title)

    # Idioma: si hay un heading "Resumen" el articulo tiene resumen en
    # español (aunque tambien tenga Abstract en ingles); si solo hay
    # "Abstract" sin "Resumen", esta escrito directamente en ingles.
    has_resumen = bool(re.search(r'<h1>\s*Resumen\s*</h1>', html))
    language = 'Español' if has_resumen else 'Inglés'

    # Paginas: se sacan del parrafo "Como citar", patron "volumen(numero), inicio-fin."
    # p.ej. "387(1), 25-46."
    page_start, page_end = '', ''
    cite_match = re.search(r'Como citar.*?</p>', html, re.DOTALL)
    if cite_match:
        cite_text = re.sub(r'<[^>]+>', '', cite_match.group(0))
        pages_match = re.search(r'\(\d+\)\s*,\s*(\d+)\s*[-–—]\s*(\d+)', cite_text)
        if pages_match:
            page_start, page_end = pages_match.group(1), pages_match.group(2)

    return {
        'title': title,
        'article_type': 'Artículo científico',
        'section': 'Artículos',
        'language': language,
        'citation': 'APA',
        'page_start': page_start,
        'page_end': page_end,
    }


def extract_full_article_data_from_html(zip_path: str) -> dict:
    """
    Extrae del index.html TODOS los datos de "front matter" necesarios para
    completar esa pestaña en AmeliCA: titulos ES/EN, autores con su numero
    de afiliacion y ORCID, afiliaciones con pais y emails, fechas
    (Aceptado/Publicado -- Enviado no se usa), resumen/abstract con sus
    palabras clave, y el DOI.

    Probado contra 2 artículos reales (1324, 1327), incluido un caso real
    de un error de numeracion de afiliacion en el documento fuente (dos
    afiliaciones distintas compartiendo el mismo numero de superindice),
    que se detecta y reporta en data['warnings'] en vez de perderse en
    silencio.
    """
    def _clean(raw_html_fragment):
        text = re.sub(r'<[^>]+>', '', raw_html_fragment)
        text = htmlmod.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    with zipfile.ZipFile(zip_path, 'r') as zf:
        html_name = next((n for n in zf.namelist() if n.endswith('index.html')), None)
        html = zf.read(html_name).decode('utf-8', errors='replace')

    data = {
        'titles': [], 'authors': [], 'affiliations': {}, 'dates': {},
        'abstracts': [], 'doi': None, 'warnings': [],
    }

    title_matches = re.findall(r'<p class="[^"]*article-title[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
    for i, raw in enumerate(title_matches):
        data['titles'].append({'lang': 'es' if i == 0 else 'en', 'text': _clean(raw)})

    orcid_pos = html.find('orcid.org')
    p_start = p_end = -1
    author_html = ""
    if orcid_pos != -1:
        p_start = html.rfind('<p ', 0, orcid_pos)
        p_end = html.find('</p>', orcid_pos)
        if p_start != -1 and p_end != -1:
            author_html = html[p_start:p_end]

    if author_html:
        name_num_pattern = re.compile(r'([A-ZÁÉÍÓÚÑ][^<,"=]*?)<span[^>]*>(\d+)</span>')
        names_nums = name_num_pattern.findall(author_html)
        orcids = re.findall(r'href="(https://orcid\.org/[\w-]+)"', author_html)
        for i, (name, num) in enumerate(names_nums):
            orcid = orcids[i] if i < len(orcids) else None
            data['authors'].append({'name': name.strip(), 'affil_num': num, 'orcid': orcid})

        start = p_end + len('</p>')
        table_idx = html.find('<table', start)
        affil_block = html[start:table_idx] if table_idx != -1 else html[start:start + 3000]

        affil_starts = list(re.finditer(r'<span[^>]*>(\d+)</span><em>(.*?)</em>,\s*([^<]*)', affil_block))
        for i, m in enumerate(affil_starts):
            num = m.group(1)
            name = _clean(m.group(2))
            country = _clean(m.group(3)).rstrip('.').strip()
            seg_start = m.end()
            seg_end = affil_starts[i + 1].start() if i + 1 < len(affil_starts) else len(affil_block)
            emails = re.findall(r'mailto:([^"]+)"', affil_block[seg_start:seg_end])
            if num in data['affiliations'] and data['affiliations'][num]['text'] != name:
                data['warnings'].append(
                    f"Dos afiliaciones distintas comparten el numero '{num}': "
                    f"'{data['affiliations'][num]['text']}' y '{name}'. Revisar "
                    f"manualmente a que autores corresponde cada email."
                )
                num = f"{num}b"
            data['affiliations'][num] = {'text': name, 'country': country, 'emails': emails}

    for key, pat in {'accepted': r'Aceptado:\s*([\d/]+)', 'published': r'Publicado:\s*([\d/]+)'}.items():
        m = re.search(pat, html)
        if m:
            data['dates'][key] = m.group(1).replace('/', '-')

    for heading, lang in (('Resumen', 'es'), ('Abstract', 'en')):
        h_match = re.search(rf'<h1>{heading}</h1>\s*<p class="MsoNormal">(.*?)</p>', html, re.DOTALL)
        if not h_match:
            continue
        full_text = _clean(h_match.group(1))
        kw_split = re.search(r'(Palabras clave|Keywords):\s*(.*)$', full_text)
        if kw_split:
            body_text = full_text[:kw_split.start()].strip()
            keywords = [k.strip() for k in kw_split.group(2).strip().rstrip('.').split(',') if k.strip()]
        else:
            body_text, keywords = full_text, []
        data['abstracts'].append({'lang': lang, 'text': body_text, 'keywords': keywords})

    doi_match = re.search(r'href="(https://doi\.org/[^"]+)"', html)
    if doi_match:
        data['doi'] = doi_match.group(1)

    return data
