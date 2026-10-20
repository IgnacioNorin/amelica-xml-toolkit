"""
word_html.py — Soporte para el index.html que genera Microsoft Word.

El resto de amelica/parsing/html.py esta pensado para el HTML del conversor
de InDesign (amelica/idml/converter.py), que marca a proposito cada dato con
una clase propia (article-title, <h1> por seccion, etc). El HTML de Word no
trae nada de eso:

  - Los titulos de seccion de la plantilla de la revista son parrafos con un
    estilo propio (<p class=Nivel1>Resumen</p>), y el nivel de titulo vive
    solo en la hoja de estilos (p.Nivel1 {... mso-outline-level:1 ...}).
    Sin <h1>, el marcaje no encuentra ninguna seccion.
  - Titulos, autores, afiliaciones y fechas son parrafos MsoNormal con
    formato directo (negrita, tamaño, superindices).

Este modulo resuelve ambas cosas: `normalizar_titulos_word` convierte esos
parrafos en <h1> antes de subir el ZIP, y `extraer_portada_word` /
`extraer_datos_basicos_word` leen la portada con heuristicas de formato y
devuelven exactamente la misma estructura que las funciones de html.py.

Validado contra un articulo real exportado desde Word (1328-RTE-37-2).
"""

import html as htmlmod
import re

_RE_GENERADOR_WORD = re.compile(
    r'<meta\s+name=["\']?Generator["\']?\s+content=["\']?Microsoft Word', re.IGNORECASE
)
_RE_CHARSET = re.compile(rb'<meta[^>]+charset=["\']?([\w-]+)', re.IGNORECASE)

# Clases de Word que tienen mso-outline-level:1 pero no son titulos de
# seccion del cuerpo (titulo del documento y encabezados de tabla de
# contenido).
_CLASES_EXCLUIDAS = ('msotitle', 'msotoc')

# Estilos de parrafo de uso general: aunque un parrafo de estos diga
# "Resumen", no se puede inferir que toda la clase sea un titulo.
_CLASES_GENERICAS = ('msonormal', 'msobodytext', 'msolistparagraph', 'msonospacing',
                     'msoplaintext', 'paragraph', 'default')

# Titulos de seccion que aparecen en practicamente todo articulo; sirven
# para reconocer la clase de titulo cuando la hoja de estilos no lo dice.
_SECCIONES_ANCLA = {
    'resumen', 'abstract', 'introducción', 'introduccion', 'introduction',
    'conclusiones', 'conclusión', 'conclusion', 'conclusions',
    'referencias', 'references', 'bibliografía', 'bibliografia',
    'materiales y métodos', 'materiales y metodos', 'materials and methods',
    'metodología', 'metodologia', 'methodology', 'resultados', 'results',
}

_TITULOS_RESUMEN = {'resumen': 'es', 'abstract': 'en'}
_ETIQUETAS_KEYWORDS = r'(?:Palabras\s+clave|Keywords|Key\s+words)'


def es_html_de_word(html: str) -> bool:
    """True si el HTML fue generado por Microsoft Word."""
    return bool(_RE_GENERADOR_WORD.search(html[:5000]))


def decodificar_html(datos: bytes) -> tuple[str, str]:
    """Decodifica el HTML respetando el charset de su <meta>.

    Word puede guardar en utf-8 o en windows-1252 segun la configuracion de
    "Opciones web"; decodificar siempre como utf-8 rompe los acentos en el
    segundo caso. Devuelve (texto, codificacion) para poder reescribir el
    archivo con la misma codificacion.
    """
    m = _RE_CHARSET.search(datos[:5000])
    candidatas = []
    if m:
        candidatas.append(m.group(1).decode('ascii', errors='ignore'))
    candidatas += ['utf-8', 'windows-1252']
    for cod in candidatas:
        try:
            return datos.decode(cod), cod
        except (LookupError, UnicodeDecodeError):
            continue
    return datos.decode('utf-8', errors='replace'), 'utf-8'


# ── Titulos de seccion ───────────────────────────────────────────────

def _clases_de_titulo(html: str) -> set[str]:
    """Clases de parrafo que son titulos de seccion de nivel 1 (ej. 'Nivel1'
    en la plantilla de la revista). Dos criterios que se suman:

      1. La hoja de estilos las define con mso-outline-level:1. Solo sirve
         con "Pagina web" comun: la exportacion "filtrada" borra todas las
         propiedades mso-* (verificado con Word 15).
      2. Algun parrafo de esa clase dice exactamente el nombre de una
         seccion conocida ("Resumen", "Introducción", "Referencias"...).
         Funciona con ambas exportaciones. Se ignoran los estilos genericos
         de parrafo para no convertir texto comun en titulo.
    """
    clases = set()
    for estilo in re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE):
        for selectores, cuerpo in re.findall(r'([^{}]+)\{([^{}]*)\}', estilo):
            if not re.search(r'mso-outline-level:\s*1\s*(?:;|$)', cuerpo):
                continue
            for clase in re.findall(r'\bp\.([\w-]+)', selectores):
                if not clase.lower().startswith(_CLASES_EXCLUIDAS):
                    clases.add(clase)

    for attrs, contenido in re.findall(r'<p(\s[^>]*)>(.*?)</p>', html, re.DOTALL | re.IGNORECASE):
        clase = re.search(r'\bclass=["\']?([\w-]+)', attrs)
        if not clase or clase.group(1).lower().startswith(_CLASES_GENERICAS):
            continue
        if _texto(contenido).lower().rstrip('.: ') in _SECCIONES_ANCLA:
            clases.add(clase.group(1))
    return clases


def normalizar_titulos_word(html: str) -> tuple[str, int]:
    """Convierte en <h1> los parrafos cuyo estilo de Word es un titulo de
    nivel 1. Conserva la clase y el resto de atributos para no perder el
    formato. Devuelve (html, cantidad de parrafos convertidos).

    No toca HTML que no sea de Word ni parrafos ya convertidos, asi que se
    puede aplicar mas de una vez sin efectos secundarios.
    """
    if not es_html_de_word(html):
        return html, 0
    clases = _clases_de_titulo(html)
    if not clases:
        return html, 0

    convertidos = 0

    def _reemplazar(m):
        nonlocal convertidos
        clase = re.search(r'\bclass=["\']?([\w-]+)', m.group(1))
        if not (clase and clase.group(1) in clases):
            return m.group(0)
        convertidos += 1
        # Word corta las lineas largas del codigo fuente dentro del texto
        # ("Resultados\r\ny Discusión"); se colapsan para que el texto del
        # <h1> coincida con lo que se ve, que es contra lo que compara el
        # marcaje cuando busca un titulo por texto.
        contenido = re.sub(r'\s+', ' ', m.group(2))
        return f'<h1{m.group(1)}>{contenido}</h1>'

    # Un <p> no puede contener otro <p>, asi que el primer </p> siguiente
    # siempre es su cierre.
    html = re.sub(r'<p(\s[^>]*)?>(.*?)</p>', _reemplazar, html, flags=re.DOTALL | re.IGNORECASE)
    return html, convertidos


# ── Recuadro "Sumario / Como citar" ──────────────────────────────────

# Estructuras que Word usa para un cuadro de texto anclado en un parrafo
# (verificado con Word 15):
#   - Cuadro con ajuste "arriba y abajo" (caso real 1328): <o:wrapblock> con
#     el VML visible y una <table> adentro para navegadores.
#   - Cuadro con otros ajustes: VML dentro de un comentario condicional mas
#     una imagen de respaldo con el texto del cuadro en el alt.
#   - Exportacion filtrada: solo la imagen, con el texto en el alt.
_RE_CUADRO_VML = re.compile(
    r'<o:wrapblock>.*?</o:wrapblock>(?:\s*<br[^>]*mso-ignore:vglayout[^>]*>)?'
    r'|<!--\[if gte vml 1\]>.*?<!\[endif\]-->(?:\s*<!\[if !vml\]>.*?<!\[endif\]>)?'
    r'|<v:shape\b[^>]*>.*?</v:shape>',
    re.DOTALL | re.IGNORECASE,
)
_RE_IMG_CON_ALT = re.compile(r'<img\b[^>]*\balt=["\']([^"\']*)["\'][^>]*>', re.IGNORECASE)
_RE_TEXTO_DE_RECUADRO = re.compile(r'\b(?:Sumario|Como citar|Cómo citar|How to cite)\s*:', re.IGNORECASE)

_ESTILO_RECUADRO = ('mso-element:para-border-div;border:none;border-bottom:solid black 1.5pt;'
                    'padding:0cm 0cm 0cm 0cm;background:#F1F1F1')


def sacar_recuadros_del_resumen(html: str) -> tuple[str, int]:
    """Saca del resumen los cuadros de texto flotantes de Word y deja su
    contenido como parrafos comunes en un recuadro justo antes del titulo
    "Resumen" (o "Abstract", el que vaya primero).

    En la plantilla de la revista, "Sumario / Como citar" es un cuadro de
    texto anclado DENTRO del primer parrafo del resumen. El portal lo
    interpreta como una "Tabla o cuadro" adentro del parrafo del resumen
    pre-creado, y el texto del resumen terminaba escrito en el campo
    "Identificador" de esa tabla. Los articulos de InDesign traen ese mismo
    recuadro como parrafos comunes antes del titulo "Resumen", que es la
    forma que ya se sabe que funciona.

    Debe aplicarse despues de normalizar_titulos_word (busca <h1>). Devuelve
    (html, cantidad de cuadros movidos).
    """
    if not es_html_de_word(html):
        return html, 0
    titulos = [(m.start(), m.end(), _texto(m.group(1)).lower())
               for m in re.finditer(r'<h1\b[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)]
    inicio = next((t for t in titulos if t[2] in _TITULOS_RESUMEN), None)
    if not inicio:
        return html, 0
    fin = next((t[0] for t in titulos if t[0] > inicio[0] and t[2] not in _TITULOS_RESUMEN),
               len(html))

    region = html[inicio[1]:fin]
    parrafos = []

    def _vml(m):
        textbox = re.search(r'<v:textbox\b.*?</v:textbox>', m.group(0), re.DOTALL | re.IGNORECASE)
        if not textbox:
            return m.group(0)   # VML de una imagen comun: no se toca
        interior = re.search(r'<div\b[^>]*>(.*)</div>', textbox.group(0), re.DOTALL | re.IGNORECASE)
        if interior:
            parrafos.extend(re.findall(r'<p\b[^>]*>.*?</p>', interior.group(1),
                                       re.DOTALL | re.IGNORECASE))
        return ''

    def _img(m):
        alt = htmlmod.unescape(m.group(1))
        if not _RE_TEXTO_DE_RECUADRO.search(alt):
            return m.group(0)   # imagen comun: no se toca
        for linea in re.split(r'[\r\n]+', alt):
            if linea.strip():
                parrafos.append(f'<p class=MsoNormal>{htmlmod.escape(linea.strip())}</p>')
        return ''

    antes = len(parrafos)
    region = _RE_CUADRO_VML.sub(_vml, region)
    movidos = 1 if len(parrafos) > antes else 0
    antes = len(parrafos)
    region = _RE_IMG_CON_ALT.sub(_img, region)
    movidos += 1 if len(parrafos) > antes else 0
    if not parrafos:
        return html, 0

    recuadro = f'<div style="{_ESTILO_RECUADRO}">\n' + '\n'.join(p.strip() for p in parrafos) + '\n</div>\n\n'
    html = html[:inicio[0]] + recuadro + html[inicio[0]:inicio[1]] + region + html[fin:]
    return html, movidos


# ── Portada ──────────────────────────────────────────────────────────

def _texto(fragmento: str) -> str:
    texto = re.sub(r'<[^>]+>', '', fragmento)
    texto = htmlmod.unescape(texto).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', texto).strip()


def _sin_cuadros_de_texto(html: str) -> str:
    """Quita los cuadros de texto flotantes (VML) y los bloques que Word
    marca solo para navegadores. En la plantilla de la revista, el recuadro
    "Sumario / Como citar" va anclado DENTRO del primer parrafo del resumen;
    sin esto su texto terminaria pegado al resumen."""
    html = re.sub(r'<v:textbox\b.*?</v:textbox>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!\[if [^\]]*\]>.*?<!\[endif\]>', '', html, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)


def _bloques(html: str) -> list[dict]:
    """Parrafos y titulos del cuerpo, en orden, con su HTML y su texto."""
    cuerpo = re.search(r'<body[^>]*>(.*)</body>', html, re.DOTALL | re.IGNORECASE)
    cuerpo = _sin_cuadros_de_texto(cuerpo.group(1) if cuerpo else html)
    bloques = []
    for m in re.finditer(r'<(p|h[1-6])(\s[^>]*)?>(.*?)</\1>', cuerpo, re.DOTALL | re.IGNORECASE):
        bloques.append({
            'tag': m.group(1).lower(),
            'attrs': m.group(2) or '',
            'html': m.group(3),
            'texto': _texto(m.group(3)),
        })
    return bloques


def _es_titulo_de_seccion(bloque: dict, clases: set[str]) -> bool:
    if bloque['tag'] == 'h1':
        return True
    clase = re.search(r'\bclass=["\']?([\w-]+)', bloque['attrs'])
    return bool(clase and clase.group(1) in clases)


def _idioma_principal(bloques: list[dict], clases: set[str]) -> str:
    """'es' o 'en' segun cual de "Resumen"/"Abstract" aparece primero
    (mismo criterio que html._primary_language)."""
    for b in bloques:
        if _es_titulo_de_seccion(b, clases):
            idioma = _TITULOS_RESUMEN.get(b['texto'].lower())
            if idioma:
                return idioma
    return 'es'


def _indice_primer_titulo(bloques: list[dict], clases: set[str]) -> int:
    for i, b in enumerate(bloques):
        if _es_titulo_de_seccion(b, clases):
            return i
    return len(bloques)


def _tamano_fuente_max(fragmento: str) -> float:
    tamanos = [float(t) for t in re.findall(r'(?<![\w-])font-size:\s*([\d.]+)pt', fragmento)]
    return max(tamanos) if tamanos else 0.0


def _titulos(portada: list[dict], idioma_principal: str) -> list[tuple[int, dict]]:
    """Titulos del articulo: los parrafos de la portada en negrita con la
    fuente mas grande (16 pt en la plantilla). El idioma sale del atributo
    lang del parrafo cuando existe; si no, del orden (primero = principal)."""
    candidatos = []
    for i, b in enumerate(portada):
        if len(b['texto']) < 15 or 'doi.org' in b['texto']:
            continue
        if not re.search(r'<b\b|font-weight:\s*bold', b['html'], re.IGNORECASE):
            continue
        tamano = _tamano_fuente_max(b['html'])
        if tamano >= 13:
            candidatos.append((i, tamano, b))
    if not candidatos:
        return []
    mayor = max(t for _, t, _ in candidatos)
    elegidos = [(i, b) for i, t, b in candidatos if t == mayor][:2]

    secundario = 'en' if idioma_principal == 'es' else 'es'
    resultado = []
    for orden, (i, b) in enumerate(elegidos):
        if re.search(r'\blang=["\']?EN', b['html'], re.IGNORECASE):
            idioma = 'en'
        elif re.search(r'\blang=["\']?ES', b['html'], re.IGNORECASE):
            idioma = 'es'
        else:
            idioma = idioma_principal if orden == 0 else secundario
        resultado.append((i, {'lang': idioma, 'text': b['texto']}))
    return resultado


def _marcar_superindices(fragmento: str) -> str:
    """Reemplaza los links ORCID por ⟪ORCID:id⟫ y los superindices numericos
    por ⟦n⟧, para poder separar autores y afiliaciones sobre el texto plano.
    El link ORCID se procesa primero porque su texto tambien va en <sup>."""
    def _orcid(m):
        ident = re.search(r'orcid\.org/\s*([\w-]+)', m.group(1))
        return f' ⟪ORCID:{ident.group(1)}⟫ ' if ident else ''
    fragmento = re.sub(r'<a\s[^>]*href=["\']?([^"\'>]*orcid\.org[^"\'>]*)["\']?[^>]*>.*?</a>',
                       _orcid, fragmento, flags=re.DOTALL | re.IGNORECASE)

    def _sup(m):
        contenido = _texto(m.group(1))
        return f'⟦{contenido}⟧' if re.fullmatch(r'\d+(?:\s*,\s*\d+)*', contenido) else ''
    return re.sub(r'<sup[^>]*>(.*?)</sup>', _sup, fragmento, flags=re.DOTALL | re.IGNORECASE)


_RE_AUTOR = re.compile(
    r'\s*(?:[,;]|\by\b|\band\b|&)?\s*'
    r'(?P<nombre>[^⟦⟪,;&]+?)\s*⟦(?P<num>[\d\s,]+)⟧\s*'
    r'(?:⟪ORCID:(?P<orcid>[^⟫]+)⟫)?'
)


def extraer_portada_word(html: str) -> dict:
    """Misma estructura que html.extract_full_article_data_from_html, pero
    leyendo la portada del HTML de Word por su formato."""
    data = {
        'titles': [], 'authors': [], 'affiliations': {}, 'dates': {},
        'abstracts': [], 'doi': None, 'warnings': [],
    }
    clases = _clases_de_titulo(html)
    bloques = _bloques(html)
    idioma_principal = _idioma_principal(bloques, clases)
    primer_titulo = _indice_primer_titulo(bloques, clases)
    portada = bloques[:primer_titulo]

    titulos = _titulos(portada, idioma_principal)
    data['titles'] = [t for _, t in titulos]
    inicio_autores = titulos[-1][0] + 1 if titulos else 0

    # Autores y afiliaciones: entre el ultimo titulo y el primer titulo de
    # seccion. Un parrafo que empieza con superindice es una afiliacion; uno
    # con "Nombre<sup>n</sup>" es un parrafo de autores (uno o varios).
    afil_actual = None
    for b in portada[inicio_autores:]:
        texto = _texto(_marcar_superindices(b['html']))
        if not texto:
            continue
        if re.match(r'(?:Enviado|Recibido|Received|Submitted|Aceptado|Accepted|Publicado|Published)\s*:',
                    texto, re.IGNORECASE):
            break

        afil = re.match(r'⟦(\d+)⟧\s*(.+)', texto)
        if afil:
            num = afil.group(1)
            fragmento = re.sub(r'<sup[^>]*>.*?</sup>', '', b['html'], count=1,
                               flags=re.DOTALL | re.IGNORECASE)
            cursiva = re.search(r'<(i|em)\b[^>]*>(.*?)</\1>', fragmento, re.DOTALL | re.IGNORECASE)
            resto = afil.group(2)
            if cursiva and _texto(cursiva.group(2)):
                institucion = _texto(cursiva.group(2))
                pais = resto.split(institucion, 1)[-1]
            else:
                institucion, _, pais = resto.partition(',')
            pais = pais.strip(' ,.')
            emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', resto)
            if emails:
                pais = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '', pais).strip(' ,.')
            if num in data['affiliations'] and data['affiliations'][num]['text'] != institucion.strip():
                data['warnings'].append(
                    f"Dos afiliaciones distintas comparten el numero '{num}': "
                    f"'{data['affiliations'][num]['text']}' y '{institucion.strip()}'. "
                    f"Revisar manualmente a que autores corresponde cada email."
                )
                num = f"{num}b"
            data['affiliations'][num] = {
                'text': institucion.strip(), 'country': pais, 'emails': list(dict.fromkeys(emails)),
            }
            afil_actual = num
            continue

        if '⟦' in texto and not data['affiliations']:
            for m in _RE_AUTOR.finditer(texto):
                nombre = m.group('nombre').strip(' ,;')
                if len(nombre) < 3:
                    continue
                orcid = m.group('orcid')
                data['authors'].append({
                    'name': nombre,
                    'affil_num': m.group('num').split(',')[0].strip(),
                    'orcid': f'https://orcid.org/{orcid}' if orcid else None,
                })
            continue

        # Parrafo suelto despues de una afiliacion: emails de esa afiliacion.
        emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', texto)
        if emails and afil_actual:
            lista = data['affiliations'][afil_actual]['emails']
            lista.extend(e for e in emails if e not in lista)

    orcids = [a['orcid'] for a in data['authors'] if a['orcid']]
    for orcid in sorted({o for o in orcids if orcids.count(o) > 1}):
        nombres = [a['name'] for a in data['authors'] if a['orcid'] == orcid]
        data['warnings'].append(
            f"Varios autores comparten el mismo ORCID ({orcid}): {', '.join(nombres)}. "
            f"Probablemente es un error del documento fuente; revisarlo a mano."
        )

    texto_portada = ' '.join(b['texto'] for b in portada)
    for clave, etiquetas in (('accepted', ('Aceptado', 'Accepted')),
                             ('published', ('Publicado', 'Published'))):
        for etiqueta in etiquetas:
            m = re.search(rf'{etiqueta}:\s*([\d/-]+)', texto_portada, re.IGNORECASE)
            if m:
                data['dates'][clave] = m.group(1).replace('/', '-')
                break

    data['abstracts'] = _resumenes(bloques, clases)

    doi = re.search(r'href=["\']?(https?://(?:dx\.)?doi\.org/[^"\'\s>]+)', html, re.IGNORECASE)
    if doi:
        data['doi'] = doi.group(1)
    return data


def _resumenes(bloques: list[dict], clases: set[str]) -> list[dict]:
    """Resumen/Abstract: los parrafos entre su titulo y la linea de palabras
    clave (o el siguiente titulo de seccion), en el orden del documento."""
    resumenes = []
    i = 0
    while i < len(bloques):
        b = bloques[i]
        idioma = _TITULOS_RESUMEN.get(b['texto'].lower()) if _es_titulo_de_seccion(b, clases) else None
        if not idioma:
            i += 1
            continue
        partes, keywords = [], []
        i += 1
        while i < len(bloques) and not _es_titulo_de_seccion(bloques[i], clases):
            texto = bloques[i]['texto']
            kw = re.match(rf'{_ETIQUETAS_KEYWORDS}\s*:\s*(.*)', texto, re.IGNORECASE)
            if kw:
                keywords = [k.strip() for k in kw.group(1).rstrip('.').split(',') if k.strip()]
                break
            if texto:
                partes.append(texto)
            i += 1
        resumenes.append({'lang': idioma, 'text': ' '.join(partes), 'keywords': keywords})
    return resumenes


def extraer_datos_basicos_word(html: str) -> dict:
    """Misma estructura que html.extract_article_data_from_html."""
    clases = _clases_de_titulo(html)
    bloques = _bloques(html)
    idioma = _idioma_principal(bloques, clases)
    portada = bloques[:_indice_primer_titulo(bloques, clases)]
    titulos = _titulos(portada, idioma)

    page_start = page_end = ''
    # El "Como citar" suele estar en un cuadro de texto que _bloques()
    # descarta, asi que se busca sobre el HTML completo.
    cita = re.search(r'(?:Como citar|Cómo citar|How to cite).*?</p>', html, re.DOTALL | re.IGNORECASE)
    if cita:
        paginas = re.search(r'\(\w+\)\s*,\s*(\d+)\s*[-–—]\s*(\d+)', _texto(cita.group(0)))
        if paginas:
            page_start, page_end = paginas.group(1), paginas.group(2)

    return {
        'title': titulos[0][1]['text'] if titulos else 'Título del artículo',
        'article_type': 'Artículo científico',
        'section': 'Artículos',
        'language': 'Español' if idioma == 'es' else 'Inglés',
        'citation': 'APA',
        'page_start': page_start,
        'page_end': page_end,
    }
