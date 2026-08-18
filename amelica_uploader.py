"""
amelica_uploader.py  —  Automatización AmeliCA XML
====================================================
Flujo:
  1. Login
  2. Detectar números En proceso → usuario elige
  3. Agregar artículo: rellenar modal (tipo, título, sección, idioma,
     páginas, norma APA) → Click "Crear"
  4. Click en ícono de subir HTML del artículo
  5. Subir ZIP con index.html
  6. Cerrar modal de subida HTML
  7. Cerrar modal de nuevo artículo
  8. Click automático en "Marcar" → abre el editor de marcaje
  9. Aceptar asistente de inferencia si aparece
 10. Ejecutar marcaje automático de secciones (AmelicaMarker)
"""

import asyncio
import os
import re
import sys
import time
import zipfile
import tempfile
import shutil
import getpass
import html as htmlmod
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from amelica_marker import AmelicaMarker

PORTAL_URL = "https://portal.amelica.org/ameli/issue.oa"


# ═══════════════════════════════════════════════════════════════
# Helpers de conversión DOCX → ZIP
# ═══════════════════════════════════════════════════════════════

def _esc(t: str) -> str:
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fix_zip_for_amelica(src_zip: str) -> str:
    """
    Recibe un ZIP externo (ej. exportado desde Word en español) y devuelve
    la ruta de un nuevo ZIP corregido llamado index.zip, donde:
      - El ZIP se llama index.zip
      - La carpeta de recursos se llama index_files/ (no index_archivos/ ni cualquier otro nombre)
      - Todas las referencias internas en index.html y header.html son actualizadas
    """
    tmpdir = tempfile.mkdtemp(prefix='amelica_')
    extract_dir = os.path.join(tmpdir, 'extracted')
    os.makedirs(extract_dir)

    with zipfile.ZipFile(src_zip, 'r') as zf:
        zf.extractall(extract_dir)

    entries = os.listdir(extract_dir)
    resources_dir_old = None
    for entry in entries:
        full = os.path.join(extract_dir, entry)
        if os.path.isdir(full):
            resources_dir_old = entry
            break

    resources_dir_new = 'index_files'

    if resources_dir_old and resources_dir_old != resources_dir_new:
        os.rename(
            os.path.join(extract_dir, resources_dir_old),
            os.path.join(extract_dir, resources_dir_new),
        )
        print(f"   🔧 Carpeta renombrada: {resources_dir_old}/ → {resources_dir_new}/")

        html_p = os.path.join(extract_dir, 'index.html')
        if os.path.exists(html_p):
            with open(html_p, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            content = content.replace(resources_dir_old + '/', resources_dir_new + '/')
            with open(html_p, 'w', encoding='utf-8') as f:
                f.write(content)

        header_p = os.path.join(extract_dir, resources_dir_new, 'header.html')
        if os.path.exists(header_p):
            with open(header_p, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            content = content.replace(resources_dir_old + '/', resources_dir_new + '/')
            with open(header_p, 'w', encoding='utf-8') as f:
                f.write(content)

    zip_p = os.path.join(tmpdir, 'index.zip')
    with zipfile.ZipFile(zip_p, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                arc_name = os.path.relpath(abs_path, extract_dir)
                zf.write(abs_path, arc_name)

    kb = os.path.getsize(zip_p) // 1024
    print(f"   📦 ZIP corregido ({kb} KB): {zip_p}")
    shutil.rmtree(extract_dir, ignore_errors=True)
    return zip_p


def build_zip_from_docx(docx_path: str, output_dir: str = None) -> str:
    """
    Convierte DOCX → index.html usando:
      1. Microsoft Word via pywin32 (Windows) — mejor calidad, igual a manual
      2. LibreOffice como fallback
      3. Conversión básica python-docx si los anteriores no están disponibles
    Empaqueta como index.zip con estructura index.html + index_archivos/
    """
    docx_path = os.path.abspath(docx_path)
    tmpdir    = output_dir if output_dir else tempfile.mkdtemp(prefix='amelica_')
    os.makedirs(tmpdir, exist_ok=True)
    html_out  = os.path.join(tmpdir, 'index.html')
    zip_p     = os.path.join(tmpdir, 'index.zip')
    converted = False

    # ── 1. Microsoft Word via pywin32 (Windows) ──────────────────────
    try:
        import win32com.client, pythoncom
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch('Word.Application')
        word.Visible = False
        word.DisplayAlerts = False
        try:
            doc = word.Documents.Open(docx_path)
            doc.SaveAs2(html_out, FileFormat=8)
            doc.Close(False)
            converted = True
            print("   ✅ Convertido con Microsoft Word")
        finally:
            word.Quit()
            pythoncom.CoUninitialize()
    except ImportError:
        print("   ℹ️  pywin32 no instalado — para mejor calidad: pip install pywin32")
    except Exception as e:
        print(f"   ⚠️  Word falló: {e}")

    # ── 2. LibreOffice ────────────────────────────────────────────────
    if not converted:
        import subprocess, shutil
        lo_candidates = [
            r'C:\Program Files\LibreOffice\program\soffice.exe',
            r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
            '/usr/bin/soffice', '/usr/bin/libreoffice', 'soffice',
        ]
        lo_exe = next((p for p in lo_candidates
                       if shutil.which(p) or os.path.exists(p)), None)
        if lo_exe:
            try:
                subprocess.run([lo_exe, '--headless', '--convert-to',
                                'html:HTML (StarWriter)', '--outdir', tmpdir, docx_path],
                               capture_output=True, timeout=60, check=True)
                base   = os.path.splitext(os.path.basename(docx_path))[0]
                lo_h   = os.path.join(tmpdir, base + '.html')
                lo_dir = os.path.join(tmpdir, base + '_html_files')
                if os.path.exists(lo_h):
                    os.rename(lo_h, html_out)
                    if os.path.exists(lo_dir):
                        os.rename(lo_dir, os.path.join(tmpdir, 'index_archivos'))
                    converted = True
                    print("   ✅ Convertido con LibreOffice")
            except Exception as e:
                print(f"   ⚠️  LibreOffice falló: {e}")

    # ── 3. Fallback python-docx ───────────────────────────────────────
    if not converted:
        print("   ⚠️  Usando conversión básica (instala pywin32 para calidad óptima)")
        _build_html_basic(docx_path, html_out, tmpdir)
        converted = True

    if not os.path.exists(html_out):
        raise RuntimeError(f"No se pudo generar index.html desde {docx_path}")

    # ── Empaquetar como index.zip ─────────────────────────────────────
    arc_dir = os.path.join(tmpdir, 'index_archivos')
    with zipfile.ZipFile(zip_p, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(html_out, 'index.html')
        if os.path.exists(arc_dir):
            for root, _, files in os.walk(arc_dir):
                for fname in files:
                    abs_p = os.path.join(root, fname)
                    arc_n = 'index_archivos/' + os.path.relpath(abs_p, arc_dir)
                    zf.write(abs_p, arc_n)

    kb    = os.path.getsize(zip_p) // 1024
    n_img = len(os.listdir(arc_dir)) if os.path.exists(arc_dir) else 0
    print(f"   📦 index.zip ({kb} KB) — {n_img} recursos en index_archivos/")
    return zip_p


def _build_html_basic(docx_path: str, html_out: str, tmpdir: str):
    """Fallback: conversión con python-docx preservando estilos básicos."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph as DocxPara
    from docx.table import Table as DocxTable

    def _esc(t): return t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    def _css(d): return '; '.join(f'{k}:{v}' for k,v in d.items())

    def pcss(para):
        css, pPr = {}, para._p.find(qn('w:pPr'))
        if pPr is None: return css
        jc = pPr.find(qn('w:jc'))
        if jc is not None:
            v = jc.get(qn('w:val'),'')
            if   v=='center':              css['text-align']='center'
            elif v=='right':               css['text-align']='right'
            elif v in('both','distribute'):css['text-align']='justify'
        sp = pPr.find(qn('w:spacing'))
        if sp is not None:
            b=sp.get(qn('w:before')); a=sp.get(qn('w:after'))
            if b and int(b)>0: css['margin-top']=f"{int(b)/20:.0f}pt"
            if a and int(a)>0: css['margin-bottom']=f"{int(a)/20:.0f}pt"
        return css

    def rhtml(run):
        rPr=run._r.find(qn('w:rPr')); css,pre,post={},'' ,''
        if rPr is not None:
            sz=rPr.find(qn('w:sz'))
            if sz is not None:
                pt=int(sz.get(qn('w:val'),24))//2
                if pt!=11: css['font-size']=f'{pt}pt'
            col=rPr.find(qn('w:color'))
            if col is not None:
                v=col.get(qn('w:val'))
                if v and v!='auto': css['color']=f'#{v}'
            if rPr.find(qn('w:b')) is not None:  pre+='<strong>'; post='</strong>'+post
            if rPr.find(qn('w:i')) is not None:  pre+='<em>';     post='</em>'+post
            va=rPr.find(qn('w:vertAlign'))
            if va is not None:
                v=va.get(qn('w:val'),'')
                if v=='superscript': pre+='<sup>'; post='</sup>'+post
                elif v=='subscript': pre+='<sub>'; post='</sub>'+post
        t=_esc(run.text)
        if css: t=f'<span style="{_css(css)}">{t}</span>'
        return pre+t+post

    def phtml(para, img_map):
        sname=(para.style.name.lower() if para.style else 'normal')
        pc=pcss(para); sa=f' style="{_css(pc)}"' if pc else ''
        hm={'heading 1':'h1','heading 2':'h2','heading 3':'h3','heading 4':'h4','title':'h1'}
        tag=hm.get(sname,'p')
        inner=''.join(rhtml(r) for r in para.runs if r.text)
        ns='http://schemas.openxmlformats.org/drawingml/2006/main'
        for drw in para._p.iter(qn('w:drawing')):
            for blip in drw.iter(f'{{{ns}}}blip'):
                rId=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if rId in img_map:
                    inner+=f'<img src="index_archivos/{img_map[rId]}" style="max-width:100%">'
        return f'<{tag}{sa}>{inner or "&nbsp;"}</{tag}>'

    def thtml(tbl, img_map):
        rows=[]
        for row in tbl.rows:
            cells=''.join(
                '<td style="border:1px solid #999;padding:4pt">'
                +''.join(phtml(p,img_map) for p in cell.paragraphs)
                +'</td>' for cell in row.cells)
            rows.append(f'<tr>{cells}</tr>')
        return f'<table style="border-collapse:collapse;width:100%">{"".join(rows)}</table>'

    doc=Document(docx_path)
    fdir=os.path.join(tmpdir,'index_archivos')
    os.makedirs(fdir,exist_ok=True)
    img_map={}
    for rId,rel in doc.part.rels.items():
        if 'image' in rel.reltype:
            ext=rel.target_part.content_type.split('/')[-1].replace('jpeg','jpg')
            name=f"image{len(img_map)+1:03d}.{ext}"
            with open(os.path.join(fdir,name),'wb') as f:
                f.write(rel.target_part.blob)
            img_map[rId]=name

    body=[]
    for block in doc.element.body:
        btag=block.tag.split('}')[-1] if '}' in block.tag else block.tag
        if   btag=='p':   body.append(phtml(DocxPara(block,doc),img_map))
        elif btag=='tbl': body.append(thtml(DocxTable(block,doc),img_map))

    html=(
        '<!DOCTYPE html>\n<html>\n<head>\n'
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n'
        '<meta name=ProgId content=Word.Document>\n'
        '<meta name=Generator content="Microsoft Word 15">\n'
        '<style>\n'
        '  body{font-family:Arial,sans-serif;font-size:11pt;margin:2cm;line-height:1.5}\n'
        '  h1{font-size:14pt;font-weight:bold;margin:12pt 0 6pt}\n'
        '  h2{font-size:12pt;font-weight:bold;margin:10pt 0 4pt}\n'
        '  h3{font-size:11pt;font-weight:bold;margin:8pt 0 4pt}\n'
        '  p{margin:3pt 0} img{max-width:100%;height:auto}\n'
        '  table{border-collapse:collapse;width:100%;margin:8pt 0}\n'
        '</style>\n</head>\n'
        "<body lang=ES style='tab-interval:36.0pt;word-wrap:break-word'>\n"
        '<div class=WordSection1>\n'
        +'\n'.join(body)
        +'\n</div>\n</body>\n</html>'
    )
    with open(html_out,'w',encoding='utf-8') as f:
        f.write(html)


def extract_article_data(docx_path: str) -> dict:
    """
    Extrae del DOCX: título, idioma, páginas (desde la cita del artículo).
    Norma de citación: siempre APA.
    """
    PAGE_PATTERNS = [
        r'\bpp?(?:ágs?)?\.?\s*(\d+)\s*[-–—]\s*(\d+)',
        r'\bpáginas?\s+(\d+)\s*(?:a|-|–)\s*(\d+)',
        r'\(\s*(?:pp?\.?\s*)?(\d+)\s*[-–—]\s*(\d+)\s*\)',
    ]
    try:
        from docx import Document
        doc = Document(docx_path)

        title = ''
        for para in doc.paragraphs:
            sname = para.style.name.lower() if para.style else ''
            text  = para.text.strip()
            if text and sname in ('heading 1', 'title'):
                title = text; break
        if not title:
            for para in doc.paragraphs:
                if para.text.strip():
                    title = para.text.strip(); break

        full = ' '.join(p.text for p in doc.paragraphs[:15]).lower()
        lang = 'Inglés' if any(
            w in full for w in ('abstract', 'introduction', 'conclusion', 'keywords')
        ) else 'Español'

        page_start = page_end = ''
        for para in doc.paragraphs:
            for pat in PAGE_PATTERNS:
                m = re.search(pat, para.text, re.IGNORECASE)
                if m:
                    page_start, page_end = m.group(1), m.group(2)
                    break
            if page_start:
                break

        return {
            'title':        title or 'Título del artículo',
            'article_type': 'Artículo científico',
            'section':      'Artículos',
            'language':     lang,
            'citation':     'APA',
            'page_start':   page_start,
            'page_end':     page_end,
        }
    except Exception:
        return {
            'title': 'Título del artículo', 'article_type': 'Artículo científico',
            'section': 'Artículos', 'language': 'Español',
            'citation': 'APA', 'page_start': '', 'page_end': '',
        }


# ═══════════════════════════════════════════════════════════════
# Uploader principal
# ═══════════════════════════════════════════════════════════════

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


# ── Parser de referencias bibliográficas ──────────────────────────────────────

def _parse_apa_authors(authors_str: str) -> list:
    """
    Parsea la cadena de autores APA a lista de dicts {given, surname}.
    Formato: "Abud, T. P., Cataldo, E., ... & Borba, B. S. M. C."
    """
    from html import unescape
    authors_str = unescape(authors_str)
    authors_str = re.sub(r'\s*[&…]\s*', ', ', authors_str)
    authors_str = re.sub(r'\s+y\s+', ', ', authors_str)
    authors_str = authors_str.strip().rstrip(',')
    # Solo quitar el punto final si NO es el punto de una inicial (ej. "L.")
    if authors_str.endswith('.') and not re.search(r'[A-ZÁÉÍÓÚ]\.$', authors_str):
        authors_str = authors_str[:-1]

    authors = []
    pattern = re.compile(
        r'((?:[a-záéíóúà][a-záéíóúà\s]+\s+)?'
        r'[A-ZÁÉÍÓÚÀÂÃÑÜ][A-Za-záéíóúàâãñü\-]+'
        r'(?:\s+[A-ZÁÉÍÓÚÀÂÃÑÜ][a-záéíóúàâãñü\-]+)*)'
        r',\s+'
        r'((?:[A-ZÁÉÍÓÚÀÂÃÑÜ]\.\s*)+)',
        re.UNICODE
    )
    for m in pattern.finditer(authors_str):
        surname = m.group(1).strip()
        given   = m.group(2).strip()
        if surname and given:
            authors.append({'given': given, 'surname': surname})

    if not authors and authors_str.strip():
        for part in re.split(r',\s+(?=[A-ZÁÉÍÓÚ])', authors_str):
            part = part.strip().rstrip(',').strip()
            if part:
                sub = part.split(',', 1)
                if len(sub) == 2:
                    authors.append({'given': sub[1].strip(), 'surname': sub[0].strip()})
                else:
                    authors.append({'given': '', 'surname': part})

    return authors


def _is_institutional_author(authors_str: str) -> bool:
    """
    Detecta si el autor es institucional (organismo, ministerio, documento legal)
    en vez de personal. Un autor personal siempre tiene "Apellido, I." donde
    el apellido es un nombre propio real, no una palabra de título.
    """
    # Palabras que indican documento legal/institucional, no apellido personal
    doc_words = r'\b(Libro|Tomo|Vol|Art|Ley|Decreto|Código|Norma|Resolución|Manual|Guía|Reglamento|Capítulo)\b'
    if re.search(doc_words, authors_str, re.IGNORECASE):
        return True
    # Si hay patrón "Apellido real, I." → personal
    # Apellido real = no es una palabra de doc_words y tiene morfología de nombre propio
    if re.search(r'[A-ZÁÉÍÓÚÀÂÃÑÜ][a-záéíóúàâãñü\-]+,\s+[A-ZÁÉÍÓÚÀÂÃÑÜ]\.', authors_str):
        return False
    # Todo en mayúsculas (siglas): UNESCO, CAST, ONU
    if re.match(r'[A-ZÁÉÍÓÚ]{2,}[\s\.]*$', authors_str.strip()):
        return True
    # Sin coma → nombre institucional directo
    if ',' not in authors_str:
        return True
    return False


def _classify_reference_type(raw_html: str, full_text: str) -> str:
    """
    Clasifica una referencia en uno de los 6 tipos usados:
    journal, book, thesis, webpage, confproc, report.

    Reglas en orden de prioridad (confirmadas con ejemplos reales):
    - thesis   : tiene [Tesis o [Thesis
    - confproc : palabras clave de conferencia
    - journal  : 2+ <em> (fuente + volumen en cursiva)
    - report   : autor institucional + ("Informe","Report","Guidelines","Norma","Balance")
                 o autor institucional sin revista
    - webpage  : "Retrieved from", fecha extendida, corchetes sin Tesis, URL sin editorial
    - book     : 1 <em> (título) o sin cursiva con editorial al final
    """
    text_lower = full_text.lower()
    em_count   = len(re.findall(r'<em>', raw_html))

    # Extraer cadena de autores (antes del primer año)
    year_m = re.search(r'\((\d{4})', full_text)
    authors_str = full_text[:year_m.start()].strip().rstrip('.') if year_m else ''
    institutional = _is_institutional_author(authors_str)

    # THESIS
    if re.search(r'\[tesis', text_lower) or re.search(r'\[thesis', text_lower):
        return 'thesis'

    # CONFPROC
    conf_kw = ['proceedings', 'conference', 'congreso', 'simposio',
               'symposium', 'anales', 'actas']
    if any(kw in text_lower for kw in conf_kw):
        return 'confproc'

    # JOURNAL: 2+ cursivas
    if em_count >= 2:
        return 'journal'

    # REPORT: autor institucional con palabras clave de reporte
    report_kw = ['informe', 'report', 'guidelines', 'norma', 'balance social',
                 'segmentación', 'resolución', 'decreto', 'ley ', 'código ',
                 'reglamento', 'manual', 'guía ']
    if institutional and any(kw in text_lower for kw in report_kw):
        return 'report'
    # También report si institucional y sin cursiva (sin revista)
    if institutional and em_count == 0:
        return 'report'

    # WEBPAGE
    if re.search(r'retrieved from', text_lower):
        return 'webpage'
    if re.search(r'recuperado de', text_lower):
        return 'webpage'
    # Fecha extendida: (2020, Febrero) o (2021, Diciembre 9)
    if re.search(r'\(\d{4},\s+[A-Za-záéíóú]', full_text):
        return 'webpage'
    # Corchetes sin "Tesis"
    if re.search(r'\[', full_text):
        return 'webpage'
    # Sin cursiva + URL
    if em_count == 0 and re.search(r'https?://', full_text):
        return 'webpage'

    # BOOK: 1 cursiva (título del libro) o sin cursiva sin URL
    if em_count <= 1:
        return 'book'

    return 'webpage'  # fallback


def parse_references_from_html(html: str) -> list:
    """
    Extrae referencias bibliográficas del HTML generado por idml_a_html.py.
    Clasifica automáticamente: journal, book, thesis, webpage, confproc, report.

    Retorna lista de dicts:
        full_text, pub_type, authors, year, article_title, source,
        volume, issue, fpage, lpage, elocation, url
    """
    from html import unescape
    refs = []

    for p_match in re.finditer(
        r'<p[^>]*class="[^"]*reference[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL
    ):
        raw = p_match.group(1).strip()
        full_text = unescape(re.sub(r'<[^>]+>', ' ', raw))
        full_text = re.sub(r'\s+', ' ', full_text).strip()

        # Filtrar párrafos que no son referencias reales
        if not re.search(r'\(\d{4}', raw) and '<em>' not in raw:
            continue

        em_count = len(re.findall(r'<em>', raw))
        pub_type = _classify_reference_type(raw, full_text)

        year_m = re.search(r'\((\d{4})', raw)
        year   = year_m.group(1) if year_m else ''

        authors = []
        if year and f'({year}' in full_text:
            authors_raw = full_text[:full_text.find(f'({year}')].strip().rstrip(',')
            if _is_institutional_author(authors_raw):
                # Autor institucional: guardar como nombre completo sin punto final
                authors = [{'given': '', 'surname': authors_raw.strip().rstrip('.')}]
            else:
                authors = _parse_apa_authors(authors_raw)

        # DOI/URL
        url = ''
        href_m = re.search(r'href="([^"]+)"', raw)
        if href_m:
            url = href_m.group(1)
        else:
            url_m = re.search(r'https?://\S+', full_text)
            if url_m:
                url = url_m.group(0).rstrip('.')

        # Fuente y volumen: primer y segundo <em>
        em_contents = re.findall(r'<em>(.*?)</em>', raw)
        first_em = unescape(re.sub(r'<[^>]+>', '', em_contents[0])).strip() if em_contents else ''
        vol_raw  = unescape(re.sub(r'<[^>]+>', '', em_contents[1])).strip() if len(em_contents) > 1 else ''

        # Dos formatos posibles:
        # A) <em>Fuente</em>, <em>Vol</em>   → source y vol_raw separados
        # B) <em>Fuente, Vol</em>(issue)      → todo en un solo <em> separado por coma+número
        source = first_em
        if not vol_raw:
            vol_split = re.search(r'^(.*),\s*(\d+)\s*$', first_em)
            if vol_split:
                source  = vol_split.group(1).strip()
                vol_raw = vol_split.group(2).strip()

        # Volumen e issue — computar ANTES de los chequeos de source
        issue_in_vol = re.search(r'\(([^)]+)\)', vol_raw)
        raw_issue = issue_in_vol.group(1).strip() if issue_in_vol else ''
        vol_clean = re.sub(r'\([^)]+\)', '', vol_raw).strip()
        vol_num = re.search(r'(\d+)', vol_clean)
        # No usar como volumen si el número coincide con el año o el vol_raw es puro texto
        if vol_num and vol_num.group(1) != year:
            volume = vol_num.group(1)
        else:
            volume = ''

        # Si el issue no estaba dentro del <em>, buscarlo en texto inmediatamente
        # después del volumen: "32(4)" aparece como "<em>32</em>(4)"
        if not raw_issue and volume:
            vol_pos = full_text.find(volume)
            if vol_pos >= 0:
                after_vol = full_text[vol_pos + len(volume):]
                issue_m = re.match(r'\s*\(([^)]+)\)', after_vol)
                if issue_m:
                    raw_issue = issue_m.group(1).strip()
        issue = raw_issue if raw_issue.isdigit() else ''

        # Para webpage/report sin volumen: el <em> no es una revista real → limpiar source
        if pub_type in ('webpage', 'report') and not volume and not issue:
            source = ''

        # Limpiar corchetes del source (ej. "[Cooperativa de Ahorro y Crédito Coopmego]")
        if source:
            source = re.sub(r'^\[|\]$', '', source).strip()

        # Para thesis: la institución puede estar en <em>[Tesis de grado, Inst]</em>
        if pub_type == 'thesis':
            inst_m = re.search(r'\[(?:Tesis[^,]*,\s*)([^\]]+)\]', first_em, re.IGNORECASE)
            if inst_m:
                source = inst_m.group(1).strip()
            else:
                inst_m2 = re.search(r'\[(?:Tesis[^,]*,\s*)([^\]]+)\]', full_text, re.IGNORECASE)
                if inst_m2:
                    source = inst_m2.group(1).strip()

        # Título del artículo: entre año y primer <em>
        article_title = ''
        if year_m and '<em>' in raw:
            after_year_html = raw[year_m.end():]
            # Saltar fecha extendida: ", Noviembre)" o ", Junio 03)"
            after_year_html = re.sub(r'^[^)]*\)', '', after_year_html, count=1) if after_year_html.startswith(',') else after_year_html
            first_em_pos = after_year_html.find('<em>')
            if first_em_pos >= 0:
                title_html = after_year_html[:first_em_pos]
                article_title = unescape(re.sub(r'<[^>]+>', '', title_html)).strip()
                article_title = re.sub(r'^[\s).]+', '', article_title).strip().strip('.')

        # Para book/report/webpage: título después del año, o el <em> si es el título
        if pub_type in ('book', 'report', 'webpage') and not article_title and year:
            # Si hay em pero no source (el em ES el título, ej. VersionOne)
            if first_em and not source:
                article_title = first_em
            else:
                year_group_m = re.search(r'\(\d{4}[^)]*\)', full_text)
                if year_group_m:
                    after_year = full_text[year_group_m.end():].strip().lstrip('.').strip()
                    title_m = re.match(r'([^.]+(?:\.[^A-ZÁÉÍÓÚ\s][^.]*)*)', after_year)
                    if title_m:
                        t = title_m.group(1).strip().strip('.')
                        t = re.sub(r'\s*\([^)]*$', '', t).strip()
                        article_title = t

        # Páginas y elocation
        fpage = lpage = elocation = ''
        after = full_text
        if source:
            src_pos = full_text.find(source)
            if src_pos >= 0:
                after = full_text[src_pos + len(source):]

        range_m = re.search(r'(\d+)\s*[–\-]\s*(\d+)', after)
        if range_m:
            fpage = range_m.group(1)
            lpage = range_m.group(2)
        else:
            eloc_m = re.search(r',\s*(\d{5,})\s*[.\s]', after)
            if eloc_m and eloc_m.group(1) != year:
                elocation = eloc_m.group(1)

        # ── Post-clasificación basada en campos extraídos ──────────────────
        # Solo aplica a tipos ambiguos (journal/book).
        # thesis, webpage, confproc, report nunca se tocan aquí.
        if pub_type not in ('thesis', 'webpage', 'confproc', 'report'):
            if volume or issue:
                # Tiene volumen o número → siempre revista
                pub_type = 'journal'
                # Limpiar source si coincide con el título (era título del libro, no revista)
                if source and article_title and source.strip() == article_title.strip():
                    source = ''
            elif source and em_count >= 1 and source.strip() != article_title.strip():
                # Source en cursiva DIFERENTE al título → es una revista real
                pub_type = 'journal'
            else:
                # Sin volumen, sin revista distinguible → libro
                pub_type = 'book'
                # Si source == article_title era el título del libro en <em>, limpiarlo
                if source and article_title and source.strip() == article_title.strip():
                    source = ''

        refs.append({
            'full_text':     full_text,
            'pub_type':      pub_type,
            'authors':       authors,
            'year':          year,
            'article_title': article_title,
            'source':        source,
            'volume':        volume,
            'issue':         issue,
            'fpage':         fpage,
            'lpage':         lpage,
            'elocation':     elocation,
            'url':           url,
        })

    return refs


class AmelicaUploader:

    def __init__(self, email: str, password: str, headless: bool = False):
        self.email    = email
        self.password = password
        self.headless = headless
        self.page                = None
        self.browser             = None
        self._last_article_title = ''

    # ── Ciclo de vida ────────────────────────────────────────────

    async def start(self):
        self._pw     = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=self.headless, slow_mo=350,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        self.page = await self.browser.new_page(
            viewport={'width': 1280, 'height': 900}, locale='es-419'
        )
        self.page.set_default_timeout(30_000)

    async def stop(self):
        if self.browser: await self.browser.close()
        if hasattr(self, '_pw'): await self._pw.stop()

    # ── Login ────────────────────────────────────────────────────

    async def login(self) -> bool:
        print("🔐 Iniciando sesión...")
        await self.page.goto(PORTAL_URL, wait_until='networkidle')

        try:
            await self.page.wait_for_selector('input[type="password"]', timeout=10_000)
        except PlaywrightTimeout:
            print("❌ Formulario de login no encontrado")
            await self._ss("debug_login"); return False

        user = await self.page.query_selector(
            'input[type="email"], input[type="text"][id*="user"], '
            'input[type="text"][name*="user"]'
        )
        if not user:
            inputs = await self.page.query_selector_all('input[type="text"]')
            user = inputs[0] if inputs else None

        pwd = await self.page.query_selector('input[type="password"]')

        if not user or not pwd:
            print("❌ Campos de login no encontrados")
            await self._ss("debug_no_fields"); return False

        await user.fill(self.email)
        await pwd.fill(self.password)

        btn = await self.page.query_selector(
            'button[type="submit"], input[type="submit"], button:has-text("Entrar")'
        )
        if btn: await btn.click()
        else:   await pwd.press('Enter')

        await asyncio.sleep(3)

        pages = self.browser.contexts[0].pages if self.browser.contexts else []
        if len(pages) > 1:
            self.page = pages[-1]
            print(f"   Nueva pestaña detectada, cambiando...")

        try:
            await self.page.wait_for_load_state('networkidle', timeout=15_000)
        except Exception:
            pass

        current_url = self.page.url
        print(f"   URL actual: {current_url}")

        if 'issue.oa' in current_url or 'home.oa' in current_url or 'journal' in current_url:
            print("✅ Login exitoso"); return True

        try:
            content = await self.page.content()
            if any(w in content for w in ['Bienvenido', 'Revista', 'Editor', 'Números']):
                print("✅ Login exitoso"); return True
        except Exception:
            pass

        if current_url == PORTAL_URL or 'issue.oa' not in current_url:
            print(f"❌ Login fallido. URL: {current_url}")
            try:
                await self._ss("debug_login_fail")
            except Exception:
                pass
            return False

        print("✅ Login exitoso (redirigido)"); return True

    # ── Selección interactiva de número ─────────────────────────

    async def pick_issue_interactive(self, target_volume: str | None = None) -> bool:
        print("\n🔍 Detectando números En proceso...")
        await asyncio.sleep(1.5)

        issues = await self._get_inprocess_issues()

        if not issues:
            print("⚠️  No se detectaron números En proceso.")
            await self._ss("debug_no_issues"); return False

        # Si se paso un volumen objetivo (desde credentials.json), buscar el
        # match exacto por texto y saltear la pregunta interactiva.
        if target_volume:
            norm_target = re.sub(r"\s+", " ", target_volume.strip())
            for iss in issues:
                norm_label = re.sub(r"\s+", " ", iss["label"].strip())
                if norm_label == norm_target:
                    print(f"\n🔧 Volumen preconfigurado encontrado: '{iss['label']}' (desde credentials.json)")
                    await self._click_gear(iss)
                    heading = await self.page.query_selector('h1, h2, h3')
                    if heading:
                        print(f"   Página: {(await heading.inner_text()).strip()}")
                    print("✅ Número seleccionado"); return True
            print(f"⚠️  No se encontró un volumen 'En proceso' que coincida con "
                  f"'{target_volume}' — se pide elegir manualmente.")

        print()
        print("┌────┬──────────┬────────────────────────────────────┐")
        print("│  # │ Tipo     │ Número                             │")
        print("├────┼──────────┼────────────────────────────────────┤")
        regulares  = [(i, iss) for i, iss in enumerate(issues) if not iss['especial']]
        especiales = [(i, iss) for i, iss in enumerate(issues) if iss['especial']]
        if regulares:
            print("│    │ ── REGULARES ──────────────────────────────│")
            for i, iss in regulares:
                print(f"│ {i+1:2d} │ Regular  │ {iss['label'][:36].ljust(36)} │")
        if especiales:
            print("│    │ ── ESPECIALES ─────────────────────────────│")
            for i, iss in especiales:
                print(f"│ {i+1:2d} │ Especial │ {iss['label'][:36].ljust(36)} │")
        print("└────┴──────────┴────────────────────────────────────┘")

        while True:
            try:
                choice = input(f"\n▶  Elige el número (1–{len(issues)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(issues): break
                print(f"   Ingresa un valor entre 1 y {len(issues)}")
            except (ValueError, KeyboardInterrupt):
                print("\nCancelado."); return False

        selected = issues[idx]
        print(f"\n🔧 Abriendo: {selected['label'].strip()}")
        await self._click_gear(selected)

        heading = await self.page.query_selector('h1, h2, h3')
        if heading:
            print(f"   Página: {(await heading.inner_text()).strip()}")

        agregar = await self.page.query_selector(
            'button:has-text("Agregar"), a:has-text("Agregar")'
        )
        if not agregar:
            print("⚠️  No se detectó botón 'Agregar artículo'")
            await self._ss("debug_after_gear_click")

        print("✅ Número seleccionado"); return True

    async def _get_inprocess_issues(self) -> list[dict]:
        link_ids = await self.page.evaluate("""
            () => {
                const IC_PROCESO = 'ic-proceso.png';
                const results = [];
                document.querySelectorAll('img').forEach(img => {
                    if (!(img.getAttribute('src') || '').includes(IC_PROCESO)) return;
                    const spanConIcono = img.parentElement;
                    if (!spanConIcono) return;
                    const spanPadre = spanConIcono.parentElement;
                    if (!spanPadre) return;
                    const spanLabel = spanPadre.querySelector('span:first-child');
                    if (!spanLabel) return;
                    const link = spanLabel.querySelector('a');
                    if (!link) return;
                    const onclick = link.getAttribute('onclick') || '';
                    if (!onclick.includes('enlace')) return;
                    const label = link.innerText.replace(/\\s+/g, ' ').trim();
                    results.push({
                        label,
                        especial: /^esp\\.?\\s/i.test(label),
                        linkId: link.id,
                    });
                });
                return results;
            }
        """)

        print(f"   JS encontró {len(link_ids)} números En proceso")
        issues = []
        for item in link_ids:
            link_id = item.get("linkId", "")
            if not link_id:
                continue
            issues.append({
                "label":    item["label"].strip(),
                "especial": item["especial"],
                "link_id":  link_id,
            })

        print(f"   ✅ {len(issues)} números En proceso detectados")
        return issues

    async def _click_gear(self, issue: dict) -> bool:
        link_id = issue.get("link_id", "")
        print(f"   Navegando al número (id={link_id})...")

        clicked = await self.page.evaluate(
            "id => { const el = document.getElementById(id); if (el) { el.click(); return true; } return false; }",
            link_id
        )
        if not clicked:
            print(f"❌ No se encontró elemento id={link_id}")
            await self._ss("debug_gear_lost"); return False

        print("   ✅ Click ejecutado")
        await asyncio.sleep(2)
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        return True

    # ── Agregar artículo ─────────────────────────────────────────

    async def add_article(self, data: dict) -> bool:
        print("\n📝 Abriendo formulario 'Nuevo artículo'...")

        try:
            await self.page.wait_for_selector(
                'button:has-text("Agregar"), a:has-text("Agregar")', timeout=8_000
            )
        except PlaywrightTimeout:
            pass

        btn = await self.page.query_selector(
            'button:has-text("Agregar artículo"), a:has-text("Agregar artículo")'
        )
        if not btn:
            for b in await self.page.query_selector_all('button, a'):
                txt = (await b.inner_text()).strip().lower()
                if 'agregar' in txt and 'art' in txt:
                    btn = b; break
        if not btn:
            print("❌ No se encontró 'Agregar artículo'")
            await self._ss("debug_no_agregar"); return False

        await btn.click()
        await asyncio.sleep(1.5)

        try:
            await self.page.wait_for_selector('#form-articulo', timeout=8_000)
        except PlaywrightTimeout:
            await asyncio.sleep(1.5)

        self._last_article_title = data.get('title', '')
        print(f"   📌 Título: {data['title'][:60]}")

        fill_result = await self.page.evaluate("""(d) => {
            function getFirst(ids) {
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (el) return el;
                }
                return null;
            }
            function setSelect(ids, label) {
                const sel = getFirst(ids);
                if (!sel) return false;
                for (const opt of sel.options) {
                    if (opt.text.trim() === label || opt.text.includes(label)) {
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
                return false;
            }
            function setInput(ids, val) {
                const el = getFirst(ids);
                if (!el) return false;
                el.value = val;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                return true;
            }

            return {
                tipo:     setSelect(['form-articulo-editar:form-tipo-editar_input', 'form-articulo:form-tipo_input'], d.article_type),
                titulo:   setInput (['form-articulo-editar:form-titulo-editar',     'form-articulo:form-titulo'],     d.title),
                seccion:  setSelect(['form-articulo-editar:form-seccion-editar_input', 'form-articulo:form-seccion_input'], d.section),
                idioma:   setSelect(['form-articulo-editar:form-idioma-editar_input',  'form-articulo:form-idioma_input'],  d.language),
                pag_ini:  d.page_start ? setInput(['form-articulo-editar:form-inicial-editar', 'form-articulo:form-inicial'], d.page_start) : null,
                pag_fin:  d.page_end   ? setInput(['form-articulo-editar:form-final-editar',   'form-articulo:form-final'],   d.page_end)   : null,
                citacion: setSelect(['form-articulo-editar:form-citacion_input', 'form-articulo:form-citacion_input'], d.citation),
            };
        }""", data)

        failed = [k for k, v in fill_result.items() if v is False]
        if failed:
            print(f"   ⚠️  No se pudieron completar estos campos (ID no encontrado en la pagina): {', '.join(failed)}")
        else:
            print(f"   ✅ Campos rellenados — páginas: {data.get('page_start','?')}–{data.get('page_end','?')}, citación: {data.get('citation','APA')}")
        await asyncio.sleep(0.5)

        clicked = await self.page.evaluate("""() => {
            const btn = document.querySelector('#form-articulo button[type="submit"], #form-articulo-editar button[type="submit"]');
            if (btn) { btn.click(); return true; }
            return false;
        }""")
        if not clicked:
            # "Crear" es el boton del panel "Agregar articulo"; "Actualizar"
            # es el boton real del panel "Editar articulo" (confirmado con
            # el HTML real del formulario) -- se prueban ambos.
            crear = await self.page.query_selector('button:has-text("Crear")')
            if not crear:
                crear = await self.page.query_selector('button:has-text("Actualizar")')
            if not crear:
                print("❌ Botón 'Crear'/'Actualizar' no encontrado")
                await self._ss("debug_no_crear"); return False
            await crear.click()

        print("   ✅ Click en 'Crear'/'Actualizar'")
        await asyncio.sleep(2.5)
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(1)

        print("   🔍 Abriendo panel de subida HTML...")
        await asyncio.sleep(1)

        opened = await self.page.evaluate("""() => {
            try {
                if (typeof PF === 'function') {
                    PF('panel-html').show();
                    try { PF('panel-articulo').hide(); } catch(e) {}
                    return 'PF-direct';
                }
            } catch(e) {}
            const panel = document.getElementById('panel-html');
            if (panel) {
                panel.style.display = 'block';
                const pa = document.getElementById('panel-articulo');
                if (pa) pa.style.display = 'none';
                return 'div-display';
            }
            return null;
        }""")

        if opened:
            print(f"   ✅ Panel HTML abierto ({opened})")
            await self.page.evaluate("""() => {
                try {
                    const a = document.getElementById('form-articulo:j_idt552');
                    if (a) PrimeFaces.ab({s: a, e: 'action', p: 'form-articulo:j_idt552', u: 'enlace'});
                } catch(e) {}
            }""")
            await asyncio.sleep(2)
        else:
            print("   ⚠️  No se pudo abrir panel HTML — súbelo manualmente")

        return True

    # ── Subir ZIP ────────────────────────────────────────────────

    async def upload_zip(self, zip_path: str) -> bool:
        print(f"\n📤 Subiendo ZIP ({Path(zip_path).stat().st_size // 1024} KB)...")

        upload_frame = None
        for attempt in range(15):
            await asyncio.sleep(1)
            for frame in self.page.frames:
                if 'upload' in (frame.url or '').lower():
                    upload_frame = frame
                    break
            if upload_frame:
                break
            print(f"   ⏳ Esperando iframe de subida... ({attempt+1}/15)")

        if not upload_frame:
            print("⚠️  No se encontró el iframe — usando página principal")
            upload_frame = self.page

        try:
            await upload_frame.wait_for_selector('input[type="file"]', timeout=10_000)
        except PlaywrightTimeout:
            print("❌ No apareció el input de archivo")
            await self._ss("debug_no_zip_input")
            return False

        file_input = await upload_frame.query_selector('input[type="file"]')
        if not file_input:
            print("❌ No se encontró input[type=file]")
            await self._ss("debug_no_file_input")
            return False

        await file_input.set_input_files(str(zip_path))
        print("   ✅ ZIP seleccionado")

        for sel in ['button:has-text("Subir")', 'button:has-text("Aceptar")',
                    'button:has-text("Cargar")', 'input[type="submit"]']:
            confirm = await upload_frame.query_selector(sel)
            if confirm:
                await confirm.click()
                print("   ✅ Confirmación enviada")
                break

        # Esperar a que aparezcan los span.mostrar1 — señal de que el servidor
        # procesó y aceptó el ZIP. Timeout de 60s, luego 2s extra.
        print("   ⏳ Esperando procesamiento del ZIP...")
        for attempt in range(60):
            await asyncio.sleep(1)
            mostrar = await self.page.evaluate("""() => {
                const spans = [...document.querySelectorAll('span.mostrar1')]
                    .filter(el => el.offsetParent !== null && (el.innerText||'').trim());
                return spans.length > 0 ? spans.map(s => s.innerText.trim()).join(' | ') : null;
            }""")
            if mostrar:
                print(f"   ✅ ZIP aceptado tras {attempt+1}s: {mostrar[:80]}")
                await asyncio.sleep(2)
                break
            if attempt % 5 == 4:
                print(f"   ⏳ Esperando... ({attempt+1}s)")
        else:
            print("   ⚠️  Timeout esperando confirmación del ZIP — continuando igual")

        # Cerrar modal ZIP
        print("   🔒 Cerrando modal ZIP (click en X)...")
        await self.page.evaluate("""() => {
            const header = document.querySelector('#p-html_header, #panel-html .ui-panel-titlebar');
            if (header) {
                const btn = header.querySelector('a.ui-panel-titlebar-icon, a[aria-label]');
                if (btn) { btn.click(); return; }
            }
            const panelHtml = document.getElementById('panel-html');
            if (panelHtml) {
                const btn = panelHtml.querySelector('a[aria-label]');
                if (btn) btn.click();
            }
        }""")
        print("   ✅ Modal ZIP cerrado — esperando 4s...")
        await asyncio.sleep(4)

        # Cerrar modal artículo
        print("   🔒 Cerrando modal artículo (click en X)...")
        await self.page.evaluate("""() => {
            const header = document.querySelector('#p-articulo_header, #panel-articulo .ui-panel-titlebar');
            if (header) {
                const btn = header.querySelector('a.ui-panel-titlebar-icon, a[aria-label]');
                if (btn) { btn.click(); return; }
            }
            const panelArt = document.getElementById('panel-articulo');
            if (panelArt) {
                const btn = panelArt.querySelector('a[aria-label]');
                if (btn) btn.click();
            }
        }""")
        print("   ✅ Modal artículo cerrado — esperando 6s...")
        await asyncio.sleep(6)

        # Click en "Marcar"
        titulo = self._last_article_title or ''
        print(f"   🎯 Buscando 'Marcar' para: {titulo[:60]}...")

        marcar_clicked = await self.page.evaluate("""(titulo) => {
            const needle = titulo.substring(0, 50).toLowerCase().trim();

            for (const bloque of document.querySelectorAll('div.articulo')) {
                const titDiv = bloque.querySelector('.titulo-articulo');
                if (!titDiv) continue;
                const txt = (titDiv.innerText || titDiv.textContent || '').toLowerCase();
                if (needle && txt.includes(needle)) {
                    for (const a of bloque.querySelectorAll('a')) {
                        if ((a.innerText || a.textContent || '').trim() === 'Marcar') {
                            a.click();
                            return 'por-titulo';
                        }
                    }
                }
            }
            return null;
        }""", titulo)

        if not marcar_clicked:
            print("   ⚠️  No se encontró 'Marcar' por título — revisá el artículo manualmente")
            return True

        print(f"   ✅ Click en 'Marcar' ({marcar_clicked})")
        await asyncio.sleep(2)
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(1)

        # ── NUEVO: Marcaje automático de secciones ──────────────────
        print("\n" + "─"*55)
        print("🏷️  Iniciando marcaje automático de secciones...")
        print("─"*55)
        marker = AmelicaMarker(self.page, headless=self.headless)
        marked = await marker.run()
        if marked:
            print("\n🎉 ¡Artículo marcado exitosamente!")
        else:
            print("\n⚠️  Marcaje no completado — revisá manualmente el editor")

        # ── NUEVO: Completar "Datos del artículo" (titulos/autores/etc) ──
        try:
            full_data = extract_full_article_data_from_html(zip_path)
            await self.fill_front_matter(full_data)
        except Exception as e:
            print(f"\n⚠️  No se pudo completar 'Datos del artículo' automáticamente: {e}")
            print("   Completalo manualmente en el navegador.")

        # ── NUEVO: Completar Referencias ──────────────────────────────────
        try:
            with __import__('zipfile').ZipFile(zip_path) as z:
                html_name = next((n for n in z.namelist() if n.endswith('index.html')), None)
                if html_name:
                    html = z.read(html_name).decode('utf-8', errors='replace')
                    refs = parse_references_from_html(html)
                    if refs:
                        await self.fill_references(refs)
                    else:
                        print("\n   ℹ️  No se encontraron referencias en el HTML")
        except Exception as e:
            print(f"\n⚠️  No se pudieron completar las referencias automáticamente: {e}")
            print("   Completá las referencias manualmente en el navegador.")

        return True

    # ── Datos del artículo (front matter): titulo/autores/resumen/etc ────
    #
    # Basado en el registro real de clicks que el usuario grabo con un
    # script de consola mientras hacia el marcaje a mano (ver conversacion).
    # Los nombres de clase reales tienen un sufijo fijo "526564616c7963"
    # (== "Redalyc" en hex, NO es un token aleatorio de sesion) que aparece
    # en toda la plataforma, pero se prefiere matchear por texto visible del
    # boton (value=...) cuando es posible, que es mas resistente a cambios.
    #
    # AVISO: esto no fue probado contra el sitio real. Esta basado en lo
    # observado en la grabacion + el HTML de menus que el usuario compartio,
    # pero la pantalla real tiene menus dinamicos en cascada dificiles de
    # verificar sin acceso en vivo. Es punto de partida para corregir, no
    # una automatizacion garantizada.

    # ── Helpers estáticos de datos ───────────────────────────────

    @staticmethod
    def _split_author_name(full_name: str) -> tuple:
        """Divide el nombre completo en (Nombre(s), Apellido(s)).

        Regla confirmada para estos artículos:
          2 palabras → 1 nombre  + 1 apellido
          3 palabras → 1 nombre  + 2 apellidos
          4 palabras → 2 nombres + 2 apellidos
          5+         → 2 nombres + resto como apellidos
        """
        parts = full_name.strip().split()
        if len(parts) <= 1:
            return full_name, ''
        elif len(parts) == 2:
            return parts[0], parts[1]
        elif len(parts) == 3:
            return parts[0], ' '.join(parts[1:])
        else:   # 4+
            return ' '.join(parts[:2]), ' '.join(parts[2:])

    @staticmethod
    def _country_code_from_affil(affil_text: str, affil_country: str,
                                  emails: list) -> str:
        """Devuelve el código ISO-2 en minúsculas (ej. 'ec') para el select
        de País, inferido del TLD del email o del texto de país de la afiliación.

        El select de AmeliCA usa value='ec', 'co', etc. (minúsculas).
        """
        # 1. TLD del email: @ucuenca.edu.ec → 'ec'
        for email in (emails or []):
            domain = email.split('@')[-1] if '@' in email else ''
            tld = domain.split('.')[-1].lower()
            if len(tld) == 2 and tld.isalpha():
                return tld

        # 2. Última palabra del campo country de la afiliación → mapeo
        country_map = {
            'ecuador': 'ec', 'colombia': 'co', 'perú': 'pe', 'peru': 'pe',
            'chile': 'cl', 'argentina': 'ar', 'mexico': 'mx', 'méxico': 'mx',
            'venezuela': 've', 'bolivia': 'bo', 'paraguay': 'py', 'uruguay': 'uy',
            'brasil': 'br', 'brazil': 'br', 'cuba': 'cu', 'españa': 'es',
            'spain': 'es', 'estados unidos': 'us', 'united states': 'us',
            'costa rica': 'cr', 'panama': 'pa', 'panamá': 'pa',
            'guatemala': 'gt', 'honduras': 'hn', 'nicaragua': 'ni',
            'el salvador': 'sv', 'república dominicana': 'do',
        }
        last = (affil_country or '').split(',')[-1].strip().lower()
        if last in country_map:
            return country_map[last]

        # 3. Intentar buscar cualquier país en el texto completo de afiliación
        full = ((affil_text or '') + ' ' + (affil_country or '')).lower()
        for name, code in country_map.items():
            if name in full:
                return code

        return ''

    async def _click_caja(self, title_attr: str, timeout_ms: int = 5000,
                           nth: str = 'last') -> bool:
        """Activa el contexto de edicion de una 'caja' (titulo, autor, fecha,
        etc.) disparando los eventos de mouse directamente desde JS.

        POR QUÉ JS Y NO Playwright .click():
        Confirmado en diagnóstico: el div tiene contenteditable="false" y su
        handler de AmeliCA agrega la clase focus-526564616c7963 solo cuando
        recibe mousedown/mouseup a través del handler nativo. El .click() de
        Playwright no dispara ese handler de la misma forma que el click real
        del usuario. Usando dispatchEvent desde JS se replica exactamente lo
        que hace el usuario, igual que en AmelicaMarker.

        nth='last' (default): la caja recién creada aparece al final.
        nth='first': usar para la primera caja de un tipo (ej. primera Fecha).

        Devuelve True si la caja fue encontrada y los eventos disparados, y
        además espera hasta 2s a que la clase focus- aparezca como señal de
        que el handler procesó el click correctamente."""
        result = await self.page.evaluate("""([title, nth]) => {
            const all = [...document.querySelectorAll(`[title="${title}"]`)]
                .filter(el => el.offsetParent !== null);
            if (!all.length) return 'not-found';
            const el = nth === 'first' ? all[0] : all[all.length - 1];
            el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
            el.dispatchEvent(new MouseEvent('mouseup',   {bubbles: true, cancelable: true, view: window}));
            el.dispatchEvent(new MouseEvent('click',     {bubbles: true, cancelable: true, view: window}));
            el.focus();
            return el.className;
        }""", [title_attr, nth])

        if result == 'not-found':
            print(f"   ⚠️  No se pudo activar la caja '{title_attr}' (no encontrada)")
            return False

        # Esperar a que la clase focus- aparezca (señal de que el handler procesó)
        for _ in range(8):
            await asyncio.sleep(0.25)
            has_focus = await self.page.evaluate("""(title) => {
                const el = [...document.querySelectorAll(`[title="${title}"]`)]
                    .find(e => e.offsetParent !== null);
                return el ? el.className.includes('focus-') : false;
            }""", title_attr)
            if has_focus:
                return True

        # Si después de 2s no tiene focus-, igual continuamos (puede que el
        # título= de esta caja no use ese patrón de clase)
        print(f"   ℹ️  Caja '{title_attr}': clase focus- no apareció — continuando igual")
        return True

    async def _click_menu_button(self, text: str, timeout_ms: int = 5000) -> bool:
        """Clickea un boton (input type=button) cuyo texto visible (value=)
        coincide, esperando a que este visible primero (los menus de AmeliCA
        aparecen/desaparecen via display:none segun el contexto activo)."""
        try:
            locator = self.page.locator(f'input[type="button"][value="{text}"]:visible').first
            await locator.wait_for(state='visible', timeout=timeout_ms)
            await locator.click()
            return True
        except Exception:
            print(f"   ⚠️  No se pudo clickear el boton '{text}' (¿no visible o no existe?)")
            return False

    async def _select_option_containing_class(self, class_substring: str, option_text: str, timeout_ms: int = 5000) -> bool:
        """Selecciona una opcion por texto visible, en el <select> visible
        cuya clase contiene class_substring (puede haber varios <select>
        con esa clase en el DOM si hay varios bloques repetidos -- se toma
        el primero visible, asumiendo que es el recien insertado)."""
        try:
            locator = self.page.locator(f'select[class*="{class_substring}"]:visible').first
            await locator.wait_for(state='visible', timeout=timeout_ms)
            await locator.select_option(label=option_text)
            return True
        except Exception:
            print(f"   ⚠️  No se pudo seleccionar '{option_text}' en select[class*={class_substring}]")
            return False

    async def _type_in_last_contenteditable(self, text: str) -> bool:
        """Tipea texto en el último contenteditable visible.

        USO EXCLUSIVO: ORCID. Es el ÚNICO campo que no viene pre-relleno por
        la inferencia de AmeliCA y requiere tipeo real. Para todos los demás
        campos usar _click_contenteditable_with_text() en su lugar."""
        try:
            elements = self.page.locator('[contenteditable="true"]:visible')
            count = await elements.count()
            if count == 0:
                print("   ⚠️  Sin contenteditable visible para tipear ORCID")
                return False
            target = elements.nth(count - 1)
            await target.click()
            await target.fill('')  # limpiar placeholder si lo hubiera
            await self.page.keyboard.type(text)
            return True
        except Exception as e:
            print(f"   ⚠️  No se pudo tipear ORCID '{text[:30]}': {e}")
            return False

    async def _click_tab(self, tab_text: str) -> bool:
        """Cambia de pestaña dentro del editor de marcaje (datos del
        articulo / referencias-apendices / texto completo / Datos abiertos).
        Selector por texto visible, sin clase conocida verificada."""
        try:
            locator = self.page.get_by_text(tab_text, exact=False).first
            await locator.click()
            await asyncio.sleep(1)
            return True
        except Exception:
            print(f"   ⚠️  No se pudo cambiar a la pestaña '{tab_text}'")
            return False

    async def _click_contenteditable_with_text(self, text: str,
                                                timeout_ms: int = 6000) -> bool:
        """Busca el primer [contenteditable="true"] visible cuyo texto ya sea
        `text` y lo clickea para disparar el blur que AmeliCA necesita.

        MECANISMO CONFIRMADO (grabado.txt, 382 eventos): AmeliCA pre-rellena
        los campos con su inferencia del artículo. El 'llenado' es un simple
        click sobre ese texto ya presente — confirmado para nombre, apellido,
        email, afiliación, abstract, palabras clave y DOI. NO se tipea nada.

        Matching: exacto, o por prefijo de ≥12 chars para textos largos como
        abstracts o nombres de instituciones (tolerancia a truncamiento).

        Retry: 3 intentos con pausa entre ellos, por si el campo tarda en
        renderizarse después del click en el botón que lo creó.
        """
        text_s = text.strip()
        if not text_s:
            return False
        prefix_len = min(len(text_s), 25)
        prefix = text_s[:prefix_len].lower()

        for attempt in range(3):
            result = await self.page.evaluate("""([ts, pfx, pfx_len]) => {
                for (const el of document.querySelectorAll('[contenteditable="true"]')) {
                    // offsetParent === null significa que el elemento está oculto
                    if (el.offsetParent === null) continue;
                    const elText = (el.innerText || el.textContent || '').trim();
                    const elLow  = elText.toLowerCase();
                    if (elText === ts ||
                        (pfx_len >= 12 && elLow.startsWith(pfx))) {
                        el.click();
                        el.focus();
                        return elText.substring(0, 60);
                    }
                }
                return null;
            }""", [text_s, prefix, prefix_len])

            if result is not None:
                await asyncio.sleep(0.4)
                print(f"      ✅ Click en campo pre-relleno: '{result}'")
                return True

            if attempt < 2:
                await asyncio.sleep(timeout_ms / 3000.0)

        print(f"      ⚠️  Sin contenteditable con texto: '{text_s[:50]}'")
        return False

    async def _fill_datepicker(self, date_str: str) -> bool:
        """Selecciona una fecha en el datepicker jQuery UI de AmeliCA.

        date_str: "DD-MM-YYYY" o "DD/MM/YYYY" (resultado de
        extract_full_article_data_from_html, que reemplaza '/' con '-').

        Requiere que el datepicker ya esté visible. Si no lo está, intenta
        abrirlo clickeando el trigger más reciente visible (ícono de
        calendario o input de fecha). Si tampoco funciona, avisa para
        completar manualmente — mejor que silenciar el error.

        Implementación basada en estructura estándar jQuery UI datepicker:
          .ui-datepicker-month  → <select> de mes (0-indexed)
          .ui-datepicker-year   → <select> de año
          td[data-handler="selectDay"] a → celdas de días
        No confirmado contra el datepicker real de AmeliCA — es el primer
        lugar a ajustar si los selectores no coinciden.
        """
        parts = date_str.replace('/', '-').split('-')
        if len(parts) != 3:
            print(f"   ⚠️  Formato de fecha irreconocible: '{date_str}'")
            return False
        try:
            if len(parts[0]) == 4:          # YYYY-MM-DD
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            else:                            # DD-MM-YYYY
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            print(f"   ⚠️  Fecha no numérica: '{date_str}'")
            return False

        month_idx = month - 1   # jQuery UI: meses 0-based

        # Abrir el datepicker si no está visible
        dp_visible = await self.page.evaluate("""() => {
            const dp = document.getElementById('ui-datepicker-div');
            return !!(dp && dp.offsetParent !== null);
        }""")

        if not dp_visible:
            opened = await self.page.evaluate("""() => {
                const candidates = [
                    ...document.querySelectorAll('.ui-datepicker-trigger'),
                    ...document.querySelectorAll('input[id*="date"]:not([type="hidden"])'),
                    ...document.querySelectorAll('button[class*="calendar"], button[class*="date"]'),
                ].filter(el => el.offsetParent !== null);
                if (!candidates.length) return false;
                candidates[candidates.length - 1].click();
                return true;
            }""")
            if opened:
                await asyncio.sleep(0.5)
            else:
                print(f"      ⚠️  Datepicker no visible y no se pudo abrir — "
                      f"completá la fecha {date_str} manualmente")
                return False

        # Seleccionar mes y año en los selects del datepicker
        set_result = await self.page.evaluate("""([mi, yr]) => {
            const dp = document.getElementById('ui-datepicker-div');
            if (!dp || dp.offsetParent === null) return 'dp-hidden';
            const mSel = dp.querySelector('.ui-datepicker-month');
            const ySel = dp.querySelector('.ui-datepicker-year');
            if (mSel) {
                mSel.value = String(mi);
                mSel.dispatchEvent(new Event('change', {bubbles: true}));
            }
            if (ySel) {
                ySel.value = String(yr);
                ySel.dispatchEvent(new Event('change', {bubbles: true}));
            }
            return (mSel ? 'month' : 'no-month') + '/' + (ySel ? 'year' : 'no-year');
        }""", [month_idx, year])

        if set_result == 'dp-hidden':
            print(f"      ⚠️  Datepicker se ocultó antes de setear mes/año para {date_str}")
            return False

        await asyncio.sleep(0.4)    # esperar re-render del calendario

        # Click en el día correspondiente
        day_clicked = await self.page.evaluate("""(day) => {
            const dp = document.getElementById('ui-datepicker-div');
            if (!dp) return false;
            // jQuery UI estándar: <td data-handler="selectDay"><a class="ui-state-default">
            for (const a of dp.querySelectorAll(
                    'td[data-handler="selectDay"] a.ui-state-default')) {
                if (parseInt(a.textContent.trim()) === day) {
                    a.click();
                    return true;
                }
            }
            // Fallback: cualquier <a> en celda de día no gris del mes actual
            for (const td of dp.querySelectorAll(
                    'td:not(.ui-datepicker-other-month):not(.ui-state-disabled)')) {
                const a = td.querySelector('a');
                if (a && parseInt(a.textContent.trim()) === day) {
                    a.click();
                    return true;
                }
            }
            return false;
        }""", day)

        if day_clicked:
            print(f"      ✅ Fecha seleccionada: {day:02d}/{month:02d}/{year}")
            await asyncio.sleep(0.3)
            return True
        else:
            print(f"      ⚠️  Día {day} no encontrado en el datepicker — "
                  f"completá {date_str} manualmente")
            return False

    async def _type_in_caja_contenido(self, title_attr: str, text: str) -> bool:
        """Tipea texto en el span.contenido- dentro de la caja identificada por
        title_attr. Usado para campos vacíos que AmeliCA NO pre-rellena porque
        el texto no aparece en el artículo cargado.

        Casos confirmados:
        - Título en otro idioma: 'Título Alternativo - EN'
          (el artículo es en ES, AmeliCA no puede inferir el título en EN)

        Casos probables con la misma estructura (a confirmar):
        - Si el resumen en otro idioma también quedara vacío (aunque en
          grabado.txt sí venía pre-relleno, así que ahí se usa
          _click_contenteditable_with_text en su lugar).

        Estructura DOM confirmada:
          <div title="Título Alternativo - EN">
            <span class="contenido-526564616c7963" contenteditable="true"></span>
          </div>
        """
        result = await self.page.evaluate("""([title]) => {
            const all = [...document.querySelectorAll(`[title="${title}"]`)]
                .filter(el => el.offsetParent !== null);
            if (!all.length) return 'not-found';
            const caja = all[all.length - 1];   // la más reciente si hay varias
            const span = caja.querySelector('[contenteditable="true"]');
            if (!span) return 'no-span';
            span.click();
            span.focus();
            return 'ok';
        }""", [title_attr])

        if result != 'ok':
            print(f"      ⚠️  _type_in_caja_contenido ({result}): '{title_attr}'")
            return False

        await asyncio.sleep(0.2)
        await self.page.keyboard.type(text, delay=8)
        print(f"      ✅ Tipeado en '{title_attr}': '{text[:55]}'")
        return True

    async def fill_front_matter(self, data: dict) -> bool:
        """Completa la pestaña 'Datos del artículo' en AmeliCA.

        LÓGICA CORRECTA — confirmada con grabado.txt (382 eventos reales):

        AmeliCA pre-rellena los campos con su inferencia automática del
        artículo. Para confirmar cada campo, el usuario (o nosotros) hace
        CLICK sobre el texto ya presente en el campo — nunca tipea. El
        único campo que requiere tipeo es el ORCID (no aparece pre-inferido
        en ningún parte del artículo).

        Regla de creación (qué necesita click en botón vs qué ya existe):
        - PRE-CREADOS (sin click en "Agregar"): el primer autor, las 2 fechas.
        - NECESITAN botón: autores 2-N, título/resumen en otro idioma,
          cada grupo de palabras clave, cada palabra clave individual, DOI.

        data: el dict de extract_full_article_data_from_html().
        """
        print("\n" + "─"*55)
        print("📋 Completando 'Datos del artículo'...")
        print("─"*55)

        if data.get('warnings'):
            for w in data['warnings']:
                print(f"   ⚠️  {w}")
            print("   ⚠️  Hay inconsistencias en autores/afiliaciones — "
                  "revisá manualmente antes de guardar.")

        await self._click_tab('datos del artículo')
        await asyncio.sleep(1.5)

        # ── 1. Título en otro idioma ──────────────────────────────────
        # CAMPO VACÍO — requiere tipeo. AmeliCA no puede inferir el título EN
        # desde un artículo en ES: el span.contenido- queda vacío, confirmado
        # en diagnóstico. Se usa _type_in_caja_contenido, no _click_...
        # La caja creada tiene title="Título Alternativo - EN" (confirmado).
        title_en = next((t for t in data.get('titles', []) if t['lang'] == 'en'), None)
        if title_en:
            print(f"\n   📌 Título EN: {title_en['text'][:60]}")
            if await self._click_caja('Títulos'):
                if await self._click_menu_button('Título en otro idioma'):
                    await self._select_option_containing_class('xml:lang', 'Inglés')
                    await asyncio.sleep(0.4)   # esperar que se cree la caja
                    await self._type_in_caja_contenido(
                        'Título Alternativo - EN', title_en['text']
                    )

        # ── 2. Autores ────────────────────────────────────────────────
        # CONFIRMADO (grabado.txt):
        # - Primer autor: PRE-CREADO por AmeliCA. Solo activar su caja y
        #   clickear los campos ya pre-rellenos (nombre, afiliación, email).
        # - Autores 2-N: crear con botón "Autor", luego clickear sus campos.
        # - ORCID: único campo que se tipea (no viene pre-inferido).
        #
        # Incertidumbre pendiente: ¿el nombre de autor viene en un campo
        # único "nombre completo" o en campos separados nombre/apellido?
        # El evento 65 muestra click en "Freddy" (solo primer nombre), lo que
        # sugiere campos separados. Por eso se intenta el nombre completo
        # primero y luego cada parte por separado si falla el match completo.

        # ── 2. Autores ────────────────────────────────────────────────
        # ESTRATEGIA (confirmada con diagnóstico en vivo):
        # - Todos los campos del autor están VACÍOS (AmeliCA no los pre-rellena).
        # - Hay que tipear todo: nombre, apellido, afiliación, email, país, ORCID.
        # - Puede haber divs de autor sobrantes de inferencias previas →
        #   borrar todos excepto el primero, luego sobrescribir autor 1 y
        #   crear autores 2-N con el botón.
        #
        # Campos y title= confirmados en DOM real:
        #   Nombre(s)          → title="Nombre(s)"         span.contenido-
        #   Apellido(s)        → title="Apellido(s)"        span.contenido-
        #   Correo electrónico → title="Correo electrónico" span.contenido-
        #   Afiliación completa→ title="Afiliación completa" span.contenido-
        #   Institución        → title="Institución"        span.contenido-
        #   País               → title="País"               select value=código_iso
        #   Identificador autor→ title="Identificador del autor" (pre-creado)
        #                        select contrib-id-type → "ORCID"
        #                        span.contenido- → "https://orcid.org/" + sufijo

        emails_ptr = {num: 0 for num in data.get('affiliations', {})}

        # Paso 0: borrar autores sobrantes (todos menos el primero)
        deleted = await self.page.evaluate("""() => {
            const authors = [...document.querySelectorAll('[title="Autor"]')]
                .filter(el => el.offsetParent !== null);
            let count = 0;
            for (let i = authors.length - 1; i >= 1; i--) {
                const a = authors[i];
                a.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                a.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                const btn = a.querySelector('[title="Cerrar"]');
                if (btn) { btn.click(); count++; }
            }
            return count;
        }""")
        if deleted:
            print(f"\n   🗑️  Eliminados {deleted} autor(es) sobrante(s)")
            await asyncio.sleep(0.8 * deleted)   # esperar re-render por cada uno

        for i, author in enumerate(data.get('authors', [])):
            affil      = data.get('affiliations', {}).get(author.get('affil_num', ''), {})
            affil_text = affil.get('text', '')        # "Universidad de Cuenca, Fac..."
            affil_ctry = affil.get('country', '')     # "Cuenca, Ecuador"
            emails     = affil.get('emails', [])

            # Email de este autor (siguiente disponible de su afiliación)
            ptr   = emails_ptr.get(author.get('affil_num', ''), 0)
            email = emails[ptr] if ptr < len(emails) else ''
            if email:
                emails_ptr[author['affil_num']] = ptr + 1

            given, surname = self._split_author_name(author['name'])
            country_code   = self._country_code_from_affil(affil_text, affil_ctry, emails)
            # Afiliación completa = texto + país (todo junto como aparece en el artículo)
            affil_full = ', '.join(filter(None, [affil_text, affil_ctry]))
            # Institución = solo hasta la primera coma
            institution = affil_text.split(',')[0].strip() if affil_text else ''

            print(f"\n   👤 Autor {i+1}: {given} | {surname} | {country_code or '?'}")

            if i == 0:
                # Primer autor: ya existe, activar su caja directamente
                await self._click_caja('Autor', nth='first')
            else:
                # Autores 2+: crear con botón desde la sección Autores
                await self._click_caja('Autores')
                if not await self._click_menu_button('Autor'):
                    print(f"      ⚠️  No se pudo crear autor {i+1} — saltando")
                    continue
                await asyncio.sleep(0.5)
                await self._click_caja('Autor')   # activar el recién creado (.last)

            # ── Nombre(s) y Apellido(s) ──────────────────────────────
            if given:
                await self._type_in_caja_contenido('Nombre(s)', given)
            if surname:
                await self._click_caja('Apellido(s)')
                await self._type_in_caja_contenido('Apellido(s)', surname)

            # ── Afiliación completa e Institución ────────────────────
            if affil_full:
                await self._click_caja('Afiliación completa')
                await self._type_in_caja_contenido('Afiliación completa', affil_full)
            if institution:
                await self._click_caja('Institución')
                await self._type_in_caja_contenido('Institución', institution)

            # ── País (select por value=código_iso, ej. 'ec') ─────────
            # El select tiene class="country-526564616c7963 attrib-526564616c7963"
            # y options con value='ec', 'co', etc. (minúsculas, sin texto).
            # _select_option_containing_class usa label= que no matchea —
            # hay que usar value= directamente.
            if country_code:
                await self._click_caja('País')
                country_set = await self.page.evaluate("""(code) => {
                    const sel = [...document.querySelectorAll('select')]
                        .filter(el => el.offsetParent !== null &&
                                      el.className.includes('country-'))
                        .at(-1);
                    if (!sel) return 'no-select';
                    const opt = [...sel.options].find(
                        o => o.value.toLowerCase() === code.toLowerCase()
                    );
                    if (!opt) return 'no-option-' + code;
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'ok-' + opt.value;
                }""", country_code)
                print(f"      {'✅' if country_set.startswith('ok') else '⚠️ '} País: {country_set}")

            # ── Correo electrónico ───────────────────────────────────
            if email:
                await self._click_caja('Correo electrónico')
                await self._type_in_caja_contenido('Correo electrónico', email)

            # ── ORCID ────────────────────────────────────────────────
            # "Identificador del autor" es un botón que CREA el div,
            # no una caja preexistente. Hay que: activar el autor (.last),
            # clickear el botón, seleccionar ORCID en el select, tipear sufijo.
            if author.get('orcid'):
                await self._click_caja('Autor')   # re-activar para que aparezcan botones
                if await self._click_menu_button('Identificador del autor'):
                    await asyncio.sleep(0.3)
                    orcid_suffix = author['orcid'].replace('https://orcid.org/', '')
                    # Seleccionar ORCID en el select visible
                    sel_ok = await self.page.evaluate("""() => {
                        const sel = [...document.querySelectorAll('select')]
                            .filter(el => el.offsetParent !== null &&
                                          el.className.includes('contrib-id-type'))
                            .at(-1);
                        if (!sel) return 'no-select';
                        sel.value = 'ORCID';
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return 'ok';
                    }""")
                    if sel_ok == 'ok':
                        await asyncio.sleep(0.5)  # esperar pre-relleno "https://orcid.org/"
                        inserted = await self.page.evaluate("""(full_orcid) => {
                            const divs = [...document.querySelectorAll('[title="Identificador del autor"]')]
                                .filter(el => el.offsetParent !== null);
                            if (!divs.length) return 'not-found';
                            const span = divs.at(-1).querySelector('[contenteditable="true"]');
                            if (!span) return 'no-span';
                            span.focus();
                            document.execCommand('selectAll', false, null);
                            const ok = document.execCommand('insertText', false, full_orcid);
                            return ok ? 'ok:' + span.innerText.slice(-10) : 'insertText-failed';
                        }""", author['orcid'])
                        if inserted.startswith('ok'):
                            print(f"      ✅ ORCID: {inserted}")
                        else:
                            print(f"      ⚠️  ORCID no insertado ({inserted})")
                    else:
                        print(f"      ⚠️  ORCID select no encontrado ({sel_ok})")

        # ── 3. Fechas: Aceptado y Publicado ───────────────────────────
        # CONFIRMADO con DOM real:
        # - Vienen 3 cajas pre-creadas: "Fecha - RECEIVED", "Fecha - ACCEPTED",
        #   "Fecha - PUB". RECEIVED no se usa — se borra.
        # - El tipo se elige en select.date-type- con values en inglés:
        #   'accepted', 'pub' (NO 'published'). El título del div cambia
        #   dinámicamente a "Fecha - ACCEPTED" / "Fecha - PUB".
        # - La fecha se ingresa abriendo el datepicker del input.date-
        #   (id="dp..."), que es jQuery UI estándar: selects de mes (0-based)
        #   y año, click en el día. AmeliCA rellena Día/Mes/Año automáticamente.
        # - Misma estrategia que autores: borrar todo excepto la primera caja,
        #   sobrescribir la primera con Aceptado, crear segunda para Publicado.

        # Mapeo data_key → value del select (confirmado con DOM)
        DATE_TYPE_VALUES = {'accepted': 'accepted', 'published': 'pub'}

        # Paso 0: crear las fechas nuevas PRIMERO (quedan al final del DOM)
        dates_ordered = [
            (k, DATE_TYPE_VALUES[k])
            for k in ('accepted', 'published')
            if data.get('dates', {}).get(k)
        ]

        n_created = 0
        for date_key, type_value in dates_ordered:
            await self._click_caja('Fechas')
            if await self._click_menu_button('Fecha'):
                n_created += 1
                await asyncio.sleep(0.4)

        # Borrar las fechas pre-existentes (las primeras del DOM).
        # El botón Cerrar solo aparece al hacer hover — se dispara mouseover
        # para revelarlo antes de clickearlo, igual que con los autores.
        if n_created > 0:
            deleted_dates = await self.page.evaluate("""(n_new) => {
                const fechas = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Fecha') &&
                                  el.className.includes('date-526564616c7963'));
                const to_delete = fechas.slice(0, fechas.length - n_new);
                let count = 0;
                for (let i = to_delete.length - 1; i >= 0; i--) {
                    const f = to_delete[i];
                    // Disparar hover para revelar el botón Cerrar
                    f.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    f.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = f.querySelector('[title="Cerrar"]');
                    if (btn) { btn.click(); count++; }
                }
                return count;
            }""", n_created)
            if deleted_dates:
                print(f"\n   🗑️  Eliminadas {deleted_dates} fecha(s) pre-existente(s)")
                await asyncio.sleep(0.4 * deleted_dates)

        # Ahora llenar cada fecha nueva (son las únicas que quedan, en orden)
        for date_idx, (date_key, type_value) in enumerate(dates_ordered):
            date_str = data['dates'][date_key]
            print(f"\n   📅 {date_key}: {date_str}")

            # Activar la fecha en orden (primera = nth first, segunda = last)
            nth = 'first' if date_idx == 0 else 'last'
            await self._click_caja('Fecha', nth=nth)

            # Elegir tipo en el select (value en inglés: 'accepted', 'pub')
            type_set = await self.page.evaluate("""(val) => {
                const sel = [...document.querySelectorAll('select')]
                    .filter(el => el.offsetParent !== null &&
                                  el.className.includes('date-type-'))
                    .at(-1);
                if (!sel) return 'no-select';
                sel.value = val;
                sel.dispatchEvent(new Event('change', {bubbles: true}));
                return 'ok-' + val;
            }""", type_value)
            print(f"      {'✅' if type_set.startswith('ok') else '⚠️ '} Tipo: {type_set}")
            await asyncio.sleep(0.3)

            # Abrir el datepicker: clickear el input.date- visible más reciente
            dp_opened = await self.page.evaluate("""() => {
                const inp = [...document.querySelectorAll('input.date-526564616c7963')]
                    .filter(el => el.offsetParent !== null && el.type !== 'hidden')
                    .at(-1);
                if (!inp) return 'no-input';
                inp.click();
                return 'ok-' + inp.id;
            }""")
            print(f"      {'✅' if dp_opened.startswith('ok') else '⚠️ '} Datepicker: {dp_opened}")
            await asyncio.sleep(0.4)

            await self._fill_datepicker(date_str)

        # ── 4. Resúmenes ──────────────────────────────────────────────
        # CONFIRMADO con DOM real:
        # - Sección padre: title="Resúmenes"
        # - Resumen ES viene pre-creado: title="Resumen  - ES" (2 espacios)
        # - Párrafo dentro del resumen: title="Párrafo", span.contenido- adentro
        # - Botón para crear EN: "Resumen en otro idioma"
        # - Estrategia: borrar todo, crear ES y EN desde cero con botones,
        #   tipear en el Párrafo de cada uno con _type_in_caja_contenido.
        # INCERTIDUMBRE: el botón para crear el resumen ES puede llamarse
        # "Resumen" u otro nombre — confirmar si falla.

        abstracts_to_fill = data.get('abstracts', [])
        if abstracts_to_fill:
            # REGLA CONFIRMADA:
            # - Siempre hay 1 resumen pre-creado: title="Resumen Original - ES/EN"
            # - Si hay 2 abstracts: primero → pre-creado, segundo → crear con botón
            # - Si hay 1: solo el pre-creado
            # - Nunca hay 3
            #
            # Para el pre-creado:
            # - Verificar idioma (xml:lang oculto ya viene correcto normalmente)
            # - Si tiene más de 1 párrafo, borrar los extras (con mouseover+Cerrar)
            #   dejando solo 1. Si solo hay 1, no se puede borrar — AmeliCA lo impide.
            # - Tipear el texto en el único párrafo que queda
            #
            # Para el segundo (si aplica): crear con botón, asignar idioma, tipear.

            abstract_primary   = abstracts_to_fill[0]
            abstract_secondary = abstracts_to_fill[1] if len(abstracts_to_fill) > 1 else None

            # ── Resumen pre-creado (primero / principal) ──────────────
            print(f"\n   📝 Resumen principal {abstract_primary['lang'].upper()} "
                  f"({len(abstract_primary['text'])} chars)")

            # Activar el pre-creado con click
            activated = await self.page.evaluate("""() => {
                const r = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Resumen Original') &&
                                  el.className.includes('abstract-'))
                    .at(0);
                if (!r) return 'not-found';
                r.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                r.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                r.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                r.focus();
                return 'ok-' + r.getAttribute('title');
            }""")
            print(f"      {'✅' if activated.startswith('ok') else '⚠️ '} {activated}")
            await asyncio.sleep(0.3)

            # Borrar párrafos extras (si hay más de 1) — dejar solo el primero
            deleted_p = await self.page.evaluate("""() => {
                const r = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Resumen Original') &&
                                  el.className.includes('abstract-'))
                    .at(0);
                if (!r) return 0;
                const parrafos = [...r.querySelectorAll('[title="Párrafo"]')]
                    .filter(el => el.offsetParent !== null);
                // Borrar de atrás hacia adelante, dejando el primero
                let count = 0;
                for (let i = parrafos.length - 1; i >= 1; i--) {
                    const p = parrafos[i];
                    p.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    p.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = p.querySelector('[title="Cerrar"]');
                    if (btn) { btn.click(); count++; }
                }
                return count;
            }""")
            if deleted_p:
                print(f"      🗑️  Eliminados {deleted_p} párrafo(s) extra(s)")
                await asyncio.sleep(0.3 * deleted_p)

            # Tipear en el único párrafo del pre-creado (limpiar primero si tiene texto)
            await self._click_caja('Párrafo')
            await self.page.evaluate("""() => {
                const spans = [...document.querySelectorAll('[title="Párrafo"] [contenteditable="true"]')]
                    .filter(el => el.offsetParent !== null);
                if (!spans.length) return;
                const span = spans.at(0);
                span.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
            }""")
            await asyncio.sleep(0.2)
            await self._type_in_caja_contenido('Párrafo', abstract_primary['text'])

            # ── Resumen secundario (si aplica) ────────────────────────
            if abstract_secondary:
                lang = abstract_secondary['lang']
                print(f"\n   📝 Resumen secundario {lang.upper()} "
                      f"({len(abstract_secondary['text'])} chars)")

                await self._click_caja('Resúmenes')
                if await self._click_menu_button('Resumen en otro idioma'):
                    await asyncio.sleep(0.4)
                    await self._click_caja('Resumen')
                    lang_set = await self.page.evaluate("""(lang) => {
                        const sel = [...document.querySelectorAll('select')]
                            .filter(el => el.offsetParent !== null &&
                                          el.className.includes('xml:lang-'))
                            .at(-1);
                        if (!sel) return 'no-select';
                        sel.value = lang;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return 'ok-' + lang;
                    }""", lang)
                    print(f"      {'✅' if lang_set.startswith('ok') else '⚠️ '} Idioma: {lang_set}")
                    await asyncio.sleep(0.3)
                    await self._click_caja('Párrafo')
                    await self._type_in_caja_contenido('Párrafo', abstract_secondary['text'])



        # ── 5. Palabras clave (ES e EN) ────────────────────────────────
        # ESTRATEGIA CONFIRMADA (igual que resúmenes):
        # 1. Borrar grupos extras dejando solo 1 con mouseover+Cerrar
        # 2. Borrar keywords extras dentro del grupo dejando solo 1
        # 3. Asignar idioma al grupo que quedó → tipear primera keyword
        #    (limpiar con selectAll+delete primero)
        # 4. Crear keywords adicionales con botón → tipear
        # 5. Si hay segundo idioma: crear grupo → asignar idioma → mismo flujo

        kwd_abstracts = [a for a in data.get('abstracts', []) if a.get('keywords')]

        if kwd_abstracts:
            # Paso 1: activar sección padre
            await self._click_caja('Grupo de palabras clave')
            await asyncio.sleep(0.5)

            # Paso 2: si no hay ningún grupo, crear uno con el botón
            n_grupos_ini = await self.page.evaluate("""() =>
                [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                  el.className.includes('kwd-group-')).length
            """)
            if n_grupos_ini == 0:
                print("   ℹ️  Sin grupos pre-creados — creando uno...")
                await self._click_menu_button('Grupo de palabras clave')
                await asyncio.sleep(0.4)
                await self._click_caja('Grupo de palabras clave')
                await asyncio.sleep(0.3)

            # Paso 3: borrar grupos extras dejando solo el primero
            await self.page.evaluate("""() => {
                const grupos = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                  el.className.includes('kwd-group-'));
                for (let i = grupos.length - 1; i >= 1; i--) {
                    const g = grupos[i];
                    g.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    g.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = g.querySelector('[title="Cerrar"]');
                    if (btn) btn.click();
                }
            }""")
            await asyncio.sleep(0.4)

            # Paso 4: borrar keywords extras en el grupo que quedó, dejando solo 1
            await self.page.evaluate("""() => {
                const grupo = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                  el.className.includes('kwd-group-')).at(0);
                if (!grupo) return;
                const kwds = [...grupo.querySelectorAll('[title="Palabra clave"]')]
                    .filter(el => el.offsetParent !== null);
                for (let i = kwds.length - 1; i >= 1; i--) {
                    const k = kwds[i];
                    k.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    k.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = k.querySelector('[title="Cerrar"]');
                    if (btn) btn.click();
                }
            }""")
            await asyncio.sleep(0.4)

            for kwd_idx, abstract in enumerate(kwd_abstracts):
                lang = abstract['lang']
                keywords = abstract['keywords']
                # is_first: True = primer grupo (pre-existente), False = grupo nuevo
                is_first = (kwd_idx == 0)
                print(f"\n   🏷️  Keywords {lang.upper()}: {keywords}")

                if is_first:
                    # Re-activar sección padre y luego el primer grupo
                    await self._click_caja('Grupo de palabras clave')
                    await asyncio.sleep(0.3)
                    await self.page.evaluate("""() => {
                        const g = [...document.querySelectorAll('[title]')]
                            .filter(el => el.offsetParent !== null &&
                                          el.getAttribute('title').startsWith('Palabras clave') &&
                                          el.className.includes('kwd-group-')).at(0);
                        if (!g) return;
                        g.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                        g.focus();
                    }""")
                else:
                    # Crear grupo nuevo con botón
                    await self._click_caja('Grupo de palabras clave')
                    if not await self._click_menu_button('Grupo de palabras clave'):
                        print(f"      ⚠️  No se pudo crear grupo {lang.upper()} — saltando")
                        continue
                    await asyncio.sleep(0.4)
                    # Activar el grupo recién creado (el último)
                    await self.page.evaluate("""() => {
                        const g = [...document.querySelectorAll('[title]')]
                            .filter(el => el.offsetParent !== null &&
                                          el.getAttribute('title').startsWith('Palabras clave') &&
                                          el.className.includes('kwd-group-')).at(-1);
                        if (!g) return;
                        g.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                        g.focus();
                    }""")
                await asyncio.sleep(0.3)

                # Asignar idioma
                lang_set = await self.page.evaluate("""(lang) => {
                    const sel = [...document.querySelectorAll('select')]
                        .filter(el => el.offsetParent !== null &&
                                      el.className.includes('xml:lang-'))
                        .at(-1);
                    if (!sel) return 'no-select';
                    sel.value = lang;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'ok-' + lang;
                }""", lang)
                print(f"      {'✅' if lang_set.startswith('ok') else '⚠️ '} Idioma: {lang_set}")
                await asyncio.sleep(0.3)

                # Tipear keywords — mismo flujo que el script de consola que funcionó:
                # kw_idx=0: activar kwd existente, limpiar, tipear
                # kw_idx>0: re-activar grupo, botón, tipear en la última kwd
                for kw_idx, kw in enumerate(keywords):
                    if kw_idx == 0:
                        typed = await self.page.evaluate("""([nth_group, text]) => {
                            const grupos = [...document.querySelectorAll('[title]')]
                                .filter(el => el.offsetParent !== null &&
                                              el.getAttribute('title').startsWith('Palabras clave') &&
                                              el.className.includes('kwd-group-'));
                            const grupo = nth_group === 0 ? grupos.at(0) : grupos.at(-1);
                            if (!grupo) return 'no-grupo';
                            const kwd = [...grupo.querySelectorAll('[title="Palabra clave"]')]
                                .filter(el => el.offsetParent !== null).at(0);
                            if (!kwd) return 'no-kwd';
                            kwd.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                            kwd.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                            kwd.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                            const span = kwd.querySelector('[contenteditable="true"]');
                            if (!span) return 'no-span';
                            span.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, text);
                            return 'ok';
                        }""", [kwd_idx, kw])
                        print(f"      {'✅' if typed == 'ok' else '⚠️ '} KWD[0]: '{kw[:40]}' ({typed})")
                    else:
                        # Re-activar grupo y crear keyword nueva
                        await self.page.evaluate("""(nth_group) => {
                            const grupos = [...document.querySelectorAll('[title]')]
                                .filter(el => el.offsetParent !== null &&
                                              el.getAttribute('title').startsWith('Palabras clave') &&
                                              el.className.includes('kwd-group-'));
                            const g = nth_group === 0 ? grupos.at(0) : grupos.at(-1);
                            if (!g) return;
                            g.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                            g.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                            g.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                            g.focus();
                        }""", kwd_idx)
                        await asyncio.sleep(0.2)
                        if await self._click_menu_button('Palabra clave'):
                            await asyncio.sleep(0.2)
                            typed = await self.page.evaluate("""([nth_group, text]) => {
                                const grupos = [...document.querySelectorAll('[title]')]
                                    .filter(el => el.offsetParent !== null &&
                                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                                  el.className.includes('kwd-group-'));
                                const grupo = nth_group === 0 ? grupos.at(0) : grupos.at(-1);
                                if (!grupo) return 'no-grupo';
                                const span = [...grupo.querySelectorAll(
                                    '[title="Palabra clave"] [contenteditable="true"]')]
                                    .filter(el => el.offsetParent !== null).at(-1);
                                if (!span) return 'no-span';
                                span.focus();
                                document.execCommand('insertText', false, text);
                                return 'ok';
                            }""", [kwd_idx, kw])
                            print(f"      {'✅' if typed == 'ok' else '⚠️ '} KWD[{kw_idx}]: '{kw[:40]}' ({typed})")
                    await asyncio.sleep(0.2)


        # ── 6. DOI ────────────────────────────────────────────────────
        # CONFIRMADO con DOM real:
        # - Botón "DOI" siempre visible (no requiere activar caja padre)
        # - Puede venir pre-creado o no — se verifica primero
        # - Si existe: usar el pre-creado; si no: crear con botón
        # - Estructura: [title="DOI"] con span.contenido- adentro → tipear
        # - Limpiar con selectAll+delete antes de tipear (puede tener placeholder)
        if data.get('doi'):
            print(f"\n   🔗 DOI: {data['doi']}")

            # Clickear el div "Datos del artículo" para revelar los botones globales
            await self.page.evaluate("""() => {
                const div = [...document.querySelectorAll('[title="Datos del artículo"]')]
                    .find(el => el.offsetParent !== null);
                if (div) {
                    div.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                    div.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                    div.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                    div.focus();
                }
            }""")
            await asyncio.sleep(0.5)

            # Verificar si ya existe el div DOI (clase confirmada: article-id-doi-)
            # Si no existe, crearlo con el botón que aparece en el panel global
            doi_exists = await self.page.evaluate("""() =>
                [...document.querySelectorAll('[title="DOI"]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.className.includes('article-id-doi-')).length > 0
            """)

            if not doi_exists:
                btn_clicked = await self.page.evaluate("""() => {
                    const btn = [...document.querySelectorAll('input[type="button"]')]
                        .filter(el => el.offsetParent !== null && el.value === 'DOI')[0];
                    if (!btn) return false;
                    btn.click();
                    return true;
                }""")
                if not btn_clicked:
                    print("      ⚠️  Botón DOI no encontrado — saltando")
                    return saved if 'saved' in dir() else False
                print("      ✅ Botón DOI clickeado — esperando creación del div...")
                await asyncio.sleep(0.8)  # esperar a que AmeliCA cree el div

            # Activar el div DOI y tipear
            typed = await self.page.evaluate("""(doi) => {
                const div = [...document.querySelectorAll('[title="DOI"]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.className.includes('article-id-doi-')).at(-1);
                if (!div) return 'no-div';
                div.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                div.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                div.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                div.focus();
                const span = div.querySelector('[contenteditable="true"]');
                if (!span) return 'no-span';
                span.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                document.execCommand('insertText', false, doi);
                return 'ok:' + span.innerText.slice(-15);
            }""", data['doi'])
            print(f"      {'✅' if typed.startswith('ok') else '⚠️ '} DOI: {typed}")
            await asyncio.sleep(0.3)

        # ── 7. Guardar ──────────────────────────────────────────────────
        print("\n   💾 Guardando...")
        saved = False
        try:
            await self.page.locator('#save-526564616c7963\\:buttonS').click()
            saved = True
            print("   ✅ Click en 'Guardar'")
        except Exception:
            # Fallback por texto visible
            try:
                btn = await self.page.query_selector(
                    'input[value="Guardar"]:visible, button:has-text("Guardar"):visible'
                )
                if btn:
                    await btn.click()
                    saved = True
                    print("   ✅ Click en 'Guardar' (fallback por texto)")
            except Exception:
                pass

        if not saved:
            print("   ⚠️  No se encontró el botón 'Guardar' — guardá manualmente")

        return saved

    # ── Referencias ──────────────────────────────────────────────

    async def _close_ref_modals(self):
        """Cierra los 3 modales que aparecen al entrar a la pestaña Referencias."""
        await asyncio.sleep(2)
        # Modal 1: alerta general (#alerta a.aceptar)
        closed1 = await self.page.evaluate("""() => {
            const btn = document.querySelector('#alerta a.aceptar, #alerta button.aceptar');
            if (btn && btn.offsetParent) { btn.click(); return true; }
            return false;
        }""")
        if closed1:
            print("   ✅ Modal alerta cerrado")
            await asyncio.sleep(1)

        # Modal 2: asistente de inferencia → Cancelar
        closed2 = await self.page.evaluate("""() => {
            const modals = document.querySelectorAll('.ui-dialog, [id*="infer"], [id*="welcome"]');
            for (const m of modals) {
                if (!m.offsetParent) continue;
                for (const btn of m.querySelectorAll('button, a')) {
                    const t = (btn.innerText || btn.textContent || '').trim();
                    if (t === 'Cancelar' || t === 'Cancel') { btn.click(); return true; }
                }
            }
            return false;
        }""")
        if closed2:
            print("   ✅ Modal asistente cerrado")
            await asyncio.sleep(1)

        # Modal 3: jQuery UI dialog warning
        closed3 = await self.page.evaluate("""() => {
            const sets = document.querySelectorAll('.ui-dialog-buttonset');
            for (const set of sets) {
                const parent = set.closest('.ui-dialog');
                if (!parent || !parent.offsetParent) continue;
                const btn = set.querySelector('button');
                if (btn) { btn.click(); return true; }
            }
            return false;
        }""")
        if closed3:
            print("   ✅ Modal warning cerrado")
            await asyncio.sleep(1)

    async def _delete_refs_but_one(self) -> int:
        """Borra todas las referencias menos la primera. Retorna cantidad borrada."""
        deleted = await self.page.evaluate("""async () => {
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            const refs = [...document.querySelectorAll('[title="Referencia"]')]
                .filter(el => el.offsetParent !== null);
            let count = 0;
            for (let i = refs.length - 1; i >= 1; i--) {
                refs[i].dispatchEvent(new MouseEvent('mouseover',  {bubbles:true}));
                refs[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
                await sleep(150);
                const btn = refs[i].querySelector('[title="Cerrar"]');
                if (btn) { btn.click(); count++; await sleep(250); }
            }
            return count;
        }""")
        if deleted:
            print(f"   🗑️  Borradas {deleted} referencias pre-existentes")
            await asyncio.sleep(0.5)
        return deleted

    async def _set_ref_pub_type(self, pub_type: str) -> bool:
        """Selecciona el tipo de publicación en la Referencia detallada activa."""
        result = await self.page.evaluate("""(pub_type) => {
            const sel = [...document.querySelectorAll('select[class*="publication-type-"]')]
                .filter(el => el.offsetParent !== null).at(-1);
            if (!sel) return false;
            sel.value = pub_type;
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            // Llamar a editInput si existe (guarda el valor en AmeliCA)
            if (typeof editInput526564616c7963 === 'function')
                editInput526564616c7963('publication-type-526564616c7963');
            return true;
        }""", pub_type)
        if result:
            await asyncio.sleep(0.8)  # esperar que cambien los botones disponibles
        return result

    async def _fill_ref_contenido(self, title_attr: str, text: str,
                                   nth: str = 'last') -> bool:
        """Escribe texto en el span.contenido- de la caja con el title dado.
        nth='last' usa la más reciente (útil cuando hay varias del mismo tipo).
        nth='first' usa la primera."""
        result = await self.page.evaluate("""([title, nth]) => {
            const all = [...document.querySelectorAll(`[title="${title}"]`)]
                .filter(el => el.offsetParent !== null);
            if (!all.length) return 'not-found';
            const caja = nth === 'first' ? all[0] : all[all.length - 1];

            // Activar la caja
            caja.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
            caja.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
            caja.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
            caja.focus();

            const span = caja.querySelector('[contenteditable="true"]');
            if (!span) return 'no-span';

            span.click();
            span.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete',    false, null);
            document.execCommand('insertText', false, text);
            return 'ok';
        }""", [title_attr, nth])

        if result != 'ok':
            print(f"      ⚠️  _fill_ref_contenido ({result}): '{title_attr}'")
            return False
        return True

    async def _fill_ref_year(self, year: str) -> bool:
        """Llena el campo Año de la referencia activa.
        El campo Año en referencias puede no tener span.contenido- inicial —
        se intenta activar y tipear; si no hay span, se inyecta directamente."""
        result = await self.page.evaluate("""(year) => {
            const cajas = [...document.querySelectorAll('[title="Año"]')]
                .filter(el => el.offsetParent !== null);
            if (!cajas.length) return 'not-found';
            const caja = cajas[cajas.length - 1];

            caja.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
            caja.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
            caja.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
            caja.focus();

            // Buscar span contenteditable (puede aparecer al activar)
            let span = caja.querySelector('[contenteditable="true"]');
            if (span) {
                span.click(); span.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete',    false, null);
                document.execCommand('insertText', false, year);
                // Actualizar hidden input iso-8601-date
                const hidden = caja.querySelector('[title*="iso-8601"]');
                if (hidden) { hidden.value = year; hidden.dispatchEvent(new Event('change', {bubbles:true})); }
                return 'span-ok';
            }

            // Sin span: crear uno e inyectar el año
            const newSpan = document.createElement('span');
            newSpan.className = [...caja.classList]
                .find(c => c.startsWith('contenido')) || 'contenido-526564616c7963';
            newSpan.setAttribute('contenteditable', 'true');
            newSpan.textContent = year;
            caja.insertBefore(newSpan, caja.firstChild);

            // Actualizar hidden input
            const hidden = caja.querySelector('[title*="iso-8601"]');
            if (hidden) {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(hidden, year);
                hidden.dispatchEvent(new Event('input',  {bubbles:true}));
                hidden.dispatchEvent(new Event('change', {bubbles:true}));
            }
            // Disparar editInput de AmeliCA si existe
            if (typeof editInput526564616c7963 === 'function')
                editInput526564616c7963('iso-8601-date-526564616c7963');
            return 'injected';
        }""", year)

        if result == 'not-found':
            print(f"      ⚠️  Campo Año no encontrado")
            return False
        print(f"      ✅ Año: {year} ({result})")
        return True

    async def _add_ref_authors(self, authors: list) -> bool:
        """Llena los autores de la referencia activa.
        El primer autor viene pre-creado vacío; los demás se agregan con botón."""
        if not authors:
            return True

        for i, author in enumerate(authors):
            given   = author.get('given', '')
            surname = author.get('surname', '')

            if i > 0:
                # Crear autor adicional con botón "Autores"
                await self._click_caja('Autores')
                clicked = await self._click_menu_button('Autor')
                if not clicked:
                    print(f"      ⚠️  No se pudo crear autor {i+1}")
                    continue
                await asyncio.sleep(0.4)

            # Llenar Nombre(s) y Apellido(s) del último autor creado
            await self._fill_ref_contenido('Nombre(s)', given,   nth='last')
            await self._fill_ref_contenido('Apellido(s)', surname, nth='last')

        return True

    async def _fill_single_reference(self, ref: dict, is_first: bool = True) -> bool:
        """Llena todos los campos de una referencia individual."""
        pub_type = ref.get('pub_type', 'journal')
        year     = ref.get('year', '')
        authors  = ref.get('authors', [])

        # 1. Seleccionar tipo de publicación
        ok = await self._set_ref_pub_type(pub_type)
        if not ok:
            print(f"      ⚠️  No se pudo setear pub_type={pub_type}")

        # 2. Referencia completa (texto plano)
        full_text = ref.get('full_text', '')
        if full_text:
            await self._fill_ref_contenido('Referencia completa', full_text)
            await asyncio.sleep(0.2)

        # 3. Activar Referencia detallada para revelar botones
        det_title = f'Referencia detallada - {pub_type.upper()}'
        await self._click_caja(det_title)
        await asyncio.sleep(0.3)

        # 4. Autores
        await self._add_ref_authors(authors)
        await asyncio.sleep(0.2)

        # 5. Año
        if year:
            await self._fill_ref_year(year)

        # 6. Fuente (journal, confproc)
        source = ref.get('source', '')
        if source and pub_type in ('journal', 'confproc', 'book'):
            await self._fill_ref_contenido('Fuente', source)

        # 7. Campos adicionales según tipo
        if pub_type in ('journal', 'confproc'):
            # Título del artículo
            article_title = ref.get('article_title', '')
            if article_title:
                await self._click_caja(det_title)
                if await self._click_menu_button('Título del artículo'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Título del artículo', article_title)

            # Volumen
            volume = ref.get('volume', '')
            if volume:
                await self._click_caja(det_title)
                if await self._click_menu_button('Volumen'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Volumen', volume)

            # Número
            issue = ref.get('issue', '')
            if issue:
                await self._click_caja(det_title)
                if await self._click_menu_button('Número'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Número', issue)

            # Página inicial / final
            fpage = ref.get('fpage', '')
            lpage = ref.get('lpage', '')
            if fpage:
                await self._click_caja(det_title)
                if await self._click_menu_button('Página inicial'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Página inicial', fpage)
            if lpage:
                await self._click_caja(det_title)
                if await self._click_menu_button('Página final'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Página final', lpage)

            # Paginación electrónica (elocation)
            elocation = ref.get('elocation', '')
            if elocation:
                await self._click_caja(det_title)
                if await self._click_menu_button('Paginación electrónica'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Paginación electrónica', elocation)

        # URL (todos los tipos)
        url = ref.get('url', '')
        if url:
            await self._click_caja(det_title)
            if await self._click_menu_button('URL'):
                await asyncio.sleep(0.3)
                await self._fill_ref_contenido('URL', url)

        return True

    async def fill_references(self, refs: list) -> bool:
        """Completa la pestaña 'Referencias' con los datos parseados del HTML.

        refs: lista devuelta por parse_references_from_html().
        """
        if not refs:
            print("   ℹ️  Sin referencias para completar")
            return True

        print("\n" + "─"*55)
        print(f"📚 Completando Referencias ({len(refs)} refs)...")
        print("─"*55)

        # 1. Ir a pestaña Referencias
        await self._click_tab('referencias')
        await asyncio.sleep(2)

        # 2. Cerrar modales
        await self._close_ref_modals()

        # 3. Borrar todas las referencias pre-existentes menos 1
        await self._delete_refs_but_one()
        await asyncio.sleep(0.5)

        # 4. Llenar cada referencia
        for i, ref in enumerate(refs):
            surname = ref['authors'][0]['surname'] if ref['authors'] else '(inst.)'
            print(f"\n   📖 [{i+1}/{len(refs)}] {surname} ({ref['year']}) [{ref['pub_type']}]")

            if i > 0:
                # Crear nueva referencia con botón
                await self._click_caja('Referencias')
                if not await self._click_menu_button('Referencia'):
                    print(f"      ⚠️  No se pudo crear la referencia {i+1}")
                    continue
                await asyncio.sleep(0.5)

            await self._fill_single_reference(ref, is_first=(i == 0))
            await asyncio.sleep(0.3)

        # 5. Guardar
        print("\n   💾 Guardando referencias...")
        saved = await self.page.evaluate("""() => {
            // Buscar botón Guardar visible
            for (const sel of [
                '#save-526564616c7963\\\\:buttonS',
                'input[value="Guardar"]',
                'button:contains("Guardar")',
            ]) {
                try {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent) { el.click(); return true; }
                } catch(e) {}
            }
            // Fallback: buscar por texto
            for (const btn of document.querySelectorAll('input[type="button"], button')) {
                if ((btn.value || btn.innerText || '').trim() === 'Guardar' && btn.offsetParent) {
                    btn.click(); return true;
                }
            }
            return false;
        }""")

        if saved:
            print("   ✅ Referencias guardadas")
        else:
            print("   ⚠️  No se encontró botón Guardar — guardá manualmente")

        return True

    # ── Screenshot helper ────────────────────────────────────────

    async def _ss(self, name: str):
        try:
            path = f"{name}_{int(time.time())}.png"
            await self.page.screenshot(path=path, full_page=True)
            print(f"   📸 {path}")
        except Exception:
            pass  # No romper el flujo si la página está cerrada

    # ── Flujo principal ──────────────────────────────────────────

    async def run(self, input_path: str, article_data: dict | None = None, keep_zip: str | None = None, target_volume: str | None = None) -> bool:
        input_path = Path(input_path)
        if not input_path.exists():
            print(f"❌ Archivo no encontrado: {input_path}"); return False

        # Aceptar tanto .docx como .zip directamente
        if input_path.suffix.lower() == '.zip':
            print(f"   📂 ZIP recibido — aplicando correcciones AmeliCA...")
            zip_path = fix_zip_for_amelica(str(input_path))
            if article_data is None:
                # Antes: placeholders fijos. Ahora: se extraen los datos reales
                # (titulo, idioma, paginas) directamente del index.html generado,
                # que ya trae esa info bien etiquetada -- no hace falta adivinar.
                article_data = extract_article_data_from_html(str(input_path))
        else:
            if article_data is None:
                article_data = extract_article_data(str(input_path))
            zip_path = build_zip_from_docx(str(input_path), output_dir=keep_zip)

        cleanup_dir = os.path.dirname(zip_path)

        try:
            await self.start()
            if not await self.login():                    return False
            if not await self.pick_issue_interactive(target_volume):   return False
            if not await self.add_article(article_data):  return False
            if not await self.upload_zip(zip_path):       return False

            if not self.headless:
                print("\n" + "═"*55)
                print("🎉 ¡Marcaje completado!")
                print("   El navegador sigue abierto para que revises el")
                print("   resultado. Cuando termines, presioná Enter aquí")
                print("   para cerrar.")
                print("═"*55)
                input()
            else:
                print("\n" + "═"*55)
                print("🎉 ¡Proceso completado!")
                print("═"*55)
            return True

        except Exception as e:
            print(f"\n💥 Error: {e}")
            if self.page: await self._ss("error_fatal")
            raise
        finally:
            if not keep_zip:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            else:
                print(f"   📁 ZIP guardado en: {cleanup_dir}")
            await self.stop()


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

async def _cli():
    if len(sys.argv) < 3:
        print("Uso: python amelica_uploader.py <email> <archivo.docx|index.zip> [--show]")
        sys.exit(1)
    email    = sys.argv[1]
    input_f  = sys.argv[2]
    show     = '--show' in sys.argv
    password = getpass.getpass("🔑 Contraseña AmeliCA: ")
    uploader = AmelicaUploader(email=email, password=password, headless=not show)
    await uploader.run(input_path=input_f)


if __name__ == '__main__':
    asyncio.run(_cli())
