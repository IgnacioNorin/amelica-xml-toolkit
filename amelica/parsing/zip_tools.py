"""
zip_tools.py — Conversion DOCX -> index.zip y correcciones del ZIP de Word.

`fix_zip_for_amelica` toma un ZIP exportado desde Word (en cualquier idioma)
y lo normaliza al formato que espera AmeliCA. `build_zip_from_docx` hace la
conversion completa desde el .docx cuando no hay export de Word disponible.
"""

import os
import re
import shutil
import tempfile
import zipfile
import html as htmlmod
from pathlib import Path


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
