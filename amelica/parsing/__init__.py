"""Parseo de documentos: DOCX, HTML, referencias y armado de ZIP."""

from .docx import extract_article_data
from .html import (
    extract_article_data_from_html,
    extract_full_article_data_from_html,
)
from .references import parse_references_from_html
from .zip_tools import build_zip_from_docx, fix_zip_for_amelica

__all__ = [
    "extract_article_data",
    "extract_article_data_from_html",
    "extract_full_article_data_from_html",
    "parse_references_from_html",
    "build_zip_from_docx",
    "fix_zip_for_amelica",
]
