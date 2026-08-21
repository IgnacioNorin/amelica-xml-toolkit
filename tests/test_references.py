"""
Tests del parser de referencias (amelica/parsing/references.py).

Son tests de regresion: fijan el rendimiento medido del parser sobre ZIPs
reales para que un cambio futuro no lo empeore sin que nos enteremos. Los
umbrales estan por debajo del valor medido, no encima, asi que fallan solo
si el parser realmente se degrada.

No tocan el portal ni necesitan Playwright: son parseo puro.
"""

import zipfile
from pathlib import Path

import pytest

from amelica.parsing.references import (
    _classify_reference_type,
    _is_institutional_author,
    _parse_apa_authors,
    parse_references_from_html,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# (fixture, refs esperadas, min con año, min con titulo, min con source)
# Medido el 2026-08-17 sobre los ZIPs reales de ArticulosZip/.
CASOS = [
    ("articulo_04.zip", 19, 19, 19, 19),
    ("articulo_05.zip", 20, 20, 20, 15),
    # articulo_12 es el peor caso conocido: HTML de origen con otro formato,
    # sin cursivas para la fuente. Se fija asi para detectar si mejora o empeora.
    ("articulo_12.zip", 15, 15, 13, 9),
]

TIPOS_VALIDOS = {"journal", "book", "thesis", "webpage", "confproc", "report"}


def refs_de(nombre):
    with zipfile.ZipFile(FIXTURES / nombre) as z:
        html = z.read("index.html").decode("utf-8", errors="replace")
    return parse_references_from_html(html)


@pytest.mark.parametrize("nombre,total,n_year,n_title,n_source", CASOS)
def test_cobertura_por_fixture(nombre, total, n_year, n_title, n_source):
    """El parser no debe extraer menos de lo que ya extraia."""
    refs = refs_de(nombre)
    assert len(refs) == total
    assert sum(1 for r in refs if r["year"]) >= n_year
    assert sum(1 for r in refs if r["article_title"]) >= n_title
    assert sum(1 for r in refs if r["source"]) >= n_source


@pytest.mark.parametrize("nombre", [c[0] for c in CASOS])
def test_forma_de_cada_referencia(nombre):
    """Toda referencia trae las claves esperadas y un tipo valido."""
    campos = {
        "full_text", "pub_type", "authors", "year", "article_title", "source",
        "volume", "issue", "fpage", "lpage", "elocation", "url",
    }
    for r in refs_de(nombre):
        assert campos <= set(r)
        assert r["pub_type"] in TIPOS_VALIDOS
        assert isinstance(r["authors"], list)
        for a in r["authors"]:
            assert set(a) == {"given", "surname"}


@pytest.mark.parametrize("nombre", [c[0] for c in CASOS])
def test_year_es_un_anio_plausible(nombre):
    for r in refs_de(nombre):
        if r["year"]:
            assert r["year"].isdigit() and 1800 <= int(r["year"]) <= 2100


@pytest.mark.parametrize("nombre", [c[0] for c in CASOS])
def test_volumen_nunca_es_el_anio(nombre):
    """Bug historico: el año se colaba como numero de volumen."""
    for r in refs_de(nombre):
        if r["volume"] and r["year"]:
            assert r["volume"] != r["year"], r["full_text"][:80]


# ── Unidades del parser, sin fixtures ────────────────────────────

def test_parse_apa_authors_multiples():
    autores = _parse_apa_authors("Abud, T. P., Cataldo, E., & Borba, B. S. M. C.")
    assert [a["surname"] for a in autores] == ["Abud", "Cataldo", "Borba"]
    assert autores[0]["given"] == "T. P."


def test_parse_apa_authors_uno_solo():
    autores = _parse_apa_authors("Alulema Alvarado, M. J.")
    assert len(autores) == 1
    assert autores[0]["surname"] == "Alulema Alvarado"


@pytest.mark.parametrize("texto", [
    "Banco Central del Ecuador",
    "Organización Mundial de la Salud",
])
def test_autor_institucional(texto):
    assert _is_institutional_author(texto)


@pytest.mark.parametrize("texto", ["Abud, T. P.", "García, M. & López, J."])
def test_autor_personal_no_es_institucional(texto):
    assert not _is_institutional_author(texto)


@pytest.mark.parametrize("raw,texto,esperado", [
    # journal: 2+ <em> (fuente + volumen en cursiva)
    ("<em>Revista</em>, <em>32</em>(4)", "Autor (2020). Titulo. Revista, 32(4)", "journal"),
    # thesis: [Tesis ... ] o [Thesis ...] -- gana aunque parezca otra cosa
    ("<em>[Tesis de grado, Universidad X]</em>", "Autor (2023). Titulo [Tesis de grado, Universidad X]", "thesis"),
    ("", "Smith, J. (2021). Title [Thesis, MIT University].", "thesis"),
    # confproc: palabras clave de conferencia
    ("<em>Actas del Congreso</em>", "Autor (2019). Titulo. Actas del Congreso", "confproc"),
    ("", "López, A. (2022). Ponencia. Proceedings of the IEEE Conference.", "confproc"),
    # report: autor institucional + palabra clave de reporte
    ("", "Banco Central del Ecuador. (2020). Informe anual de gestión.", "report"),
    # report: autor institucional sin cursiva (sin revista), sin palabra clave
    ("", "Organización Mundial de la Salud. (2019). Directrices generales de salud.", "report"),
    # webpage: "Retrieved from" / "Recuperado de"
    ("", "Smith, J. (2021). Website title. Retrieved from https://example.com/page", "webpage"),
    ("", "Pérez, J. (2021). Título de la página. Recuperado de https://ejemplo.com", "webpage"),
    # webpage: fecha extendida (2020, Febrero)
    ("", "García, M. (2020, Febrero). Título del artículo web.", "webpage"),
    # webpage: corchetes sin "Tesis" (ej. [Entrada de blog])
    ("", "López, A. (2021). Título del recurso [Entrada de blog].", "webpage"),
    # webpage: sin cursiva + URL, sin ninguna otra señal
    ("", "Autor, A. (2021). Título de la página sin corchetes. https://example.com/resource", "webpage"),
    # book: 1 <em> (título del libro en cursiva)
    ("<em>Título del libro</em>", "Autor, A. (2020). Título del libro. Editorial X.", "book"),
    # book: sin cursiva, sin URL, sin corchetes, autor personal (fallback)
    ("", "Abud, T. P. (2020). Título de libro sin cursiva. Editorial Y.", "book"),
])
def test_clasificacion_de_tipo(raw, texto, esperado):
    assert _classify_reference_type(raw, texto) == esperado
