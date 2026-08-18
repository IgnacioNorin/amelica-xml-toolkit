"""
docx.py — Extraccion de metadatos directamente desde un .docx.

Se usa solo cuando no hay un export HTML de Word; el camino preferido es
`parsing.html`, que lee datos ya bien etiquetados.
"""

import re
import zipfile


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
