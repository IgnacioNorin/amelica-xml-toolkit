"""
test_cli.py — Validación de extensiones de entrada en amelica/cli.py.

Antes, cualquier archivo que no fuera .zip caía en la rama .docx y
reventaba con un error poco claro de python-docx (por ejemplo, un .doc
de Word 97-2003). Estos tests cubren que ahora se rechace antes, con un
mensaje que dice qué hacer, sin llegar a pedir credenciales ni abrir el
navegador.
"""

import asyncio
from argparse import Namespace
from pathlib import Path

import pytest

from amelica import cli


def test_validar_entrada_acepta_permitidas():
    assert cli._validar_entrada(Path("a.ZIP"), (".zip", ".docx"))
    assert cli._validar_entrada(Path("a.docx"), (".zip", ".docx"))


def test_validar_entrada_doc_viejo(capsys):
    assert not cli._validar_entrada(Path("articulo.doc"), (".zip", ".docx"))
    assert "guárdalo como .docx" in capsys.readouterr().out


def test_validar_entrada_extension_desconocida(capsys):
    assert not cli._validar_entrada(Path("articulo.pdf"), (".zip", ".docx"))
    salida = capsys.readouterr().out
    assert "'.pdf'" in salida and ".zip, .docx" in salida


def test_upload_doc_sale_antes_de_pedir_credenciales(tmp_path, monkeypatch):
    doc = tmp_path / "articulo.doc"
    doc.write_bytes(b"contenido")

    def no_deberia_llamarse():
        raise AssertionError("No debe cargar credenciales con un .doc")

    monkeypatch.setattr(cli, "load_credentials", no_deberia_llamarse)
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.cmd_upload(Namespace(input=str(doc))))
    assert exc.value.code == 1


def test_zip_rechaza_doc(tmp_path, capsys):
    doc = tmp_path / "articulo.doc"
    doc.write_bytes(b"contenido")
    assert cli.cmd_zip(Namespace(input=str(doc), output=str(tmp_path))) == 1
    assert "guárdalo como .docx" in capsys.readouterr().out


def test_batch_avisa_doc_omitidos(tmp_path, capsys):
    (tmp_path / "viejo.doc").write_bytes(b"contenido")
    assert asyncio.run(cli.cmd_batch(Namespace(folder=str(tmp_path)))) is None
    salida = capsys.readouterr().out
    assert "Se omiten 1 archivo(s) .doc" in salida
    assert "viejo.doc" in salida
    assert "No hay archivos .zip ni .docx" in salida
