"""
amelica — Automatizacion de carga de articulos en AmeliCA XML.

Subpaquetes:
  parsing/  Parseo de DOCX, HTML y referencias; armado del index.zip.
            No depende de Playwright: es logica pura y testeable offline.
  portal/   Automatizacion del portal con Playwright (login, alta de
            articulo, subida del ZIP, marcaje, front matter, referencias).
  idml/     Conversor .idml -> index.zip, con una web local opcional.

Punto de entrada: amelica.cli (o `python -m amelica`).
"""

__version__ = "2.0.0"
