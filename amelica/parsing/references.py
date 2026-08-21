"""
references.py — Parser de referencias bibliograficas en formato APA.

Extrae y clasifica las referencias del index.html en 6 tipos: journal, book,
thesis, webpage, confproc, report. Validado contra los ZIPs de fixtures/
(ver tests/test_references.py) — es la parte del proyecto con cobertura real.

No depende de Playwright ni del portal: es parseo puro, testeable offline.
"""

import re


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
    - journal  : 2+ <em> (fuente + volumen en cursiva), o patron
                 "volumen(numero), paginas" aunque no haya cursivas
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

    # JOURNAL sin cursivas: el HTML de origen a veces no envuelve la revista
    # en <em> (confirmado en un articulo real, "peor caso" de formato de
    # origen), pero el patron "volumen(numero), paginas" -- ej. "22(2),
    # 143-162" -- solo aparece en articulos de revista. Sin esto, esas
    # referencias caian en la regla de respaldo de webpage (sin cursiva +
    # URL) solo por traer un DOI.
    if re.search(r'\d+\(\d+\),\s*\d+\s*[-–—]\s*\d+', full_text):
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

        # Respaldo sin cursivas: mismo patron "volumen(numero), paginas" que
        # detecta pub_type='journal' cuando el HTML de origen no envuelve la
        # revista en <em> (ver _classify_reference_type). Sin esto, volume/
        # issue quedaban vacios y la post-clasificacion de mas abajo
        # terminaba bajando el tipo de nuevo a 'book' por "sin volumen".
        if not volume:
            vol_issue_m = re.search(r'(\d+)\((\d+)\),\s*\d+\s*[-–—]\s*\d+', full_text)
            if vol_issue_m and vol_issue_m.group(1) != year:
                volume = vol_issue_m.group(1)
                issue  = vol_issue_m.group(2)

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

        # Respaldo para cualquier tipo (originalmente solo book/report/webpage,
        # pero un journal sin <em> en el HTML de origen -- ver el respaldo de
        # volumen/issue mas arriba -- tampoco encuentra titulo por el metodo
        # de arriba, que exige '<em>' in raw): título después del año, o el
        # <em> si es el título.
        if not article_title and year:
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
