"""
cli.py  ─  Interfaz de línea de comandos de AmeliCA XML
========================================================

Flujo recomendado:
  1. Abre el DOCX en Word → Guardar como → "Página web filtrada (*.htm, *.html)"
     Esto genera: index.html + carpeta index_archivos/
  2. Selecciona ambos (index.html + index_archivos/) y comprímelos en index.zip
  3. Ejecuta:  amelica upload index.zip --show

También acepta .docx directamente, pero la calidad del HTML será mejor
si lo exportas desde Word.

Modos de uso
─────────────
# Subir un ZIP (recomendado — HTML exportado desde Word):
    amelica upload index.zip --show

# Subir desde DOCX (genera HTML automáticamente):
    amelica upload articulo.docx --show

# Con credenciales directas:
    amelica upload index.zip --email tu@correo.com --password TuClave

# O guardá tus credenciales una vez en credentials.json (mismo formato que
# credentials.example.json) para no tener que pegarlas cada vez:
    cp credentials.example.json credentials.json
    # y editá ese archivo con tu email/contraseña reales.
    amelica upload index.zip --show   # ya no pide email/password

# Con metadatos del artículo personalizados:
    amelica upload index.zip --titulo "Mi título" --idioma "Inglés" --pagina-inicio 1 --pagina-fin 15

# Procesar varios ZIPs de una carpeta:
    amelica batch ./ArticulosZip/ --email tu@correo.com

Sin instalar el paquete, todo lo anterior funciona como `python -m amelica ...`.

Las referencias NO se cargan en el portal por defecto: ese paso es
experimental y borra las referencias preexistentes. Ver --referencias
y amelica/portal/references.py.
"""

import asyncio
import argparse
import getpass
import sys
from pathlib import Path

from .parsing import (
    extract_article_data, extract_article_data_from_html, fix_zip_for_amelica,
)
from .config import load_credentials
from .portal import AmelicaUploader


# ─────────────────────────────────────────────
# Subcomandos
# ─────────────────────────────────────────────

async def cmd_upload(args):
    """Sube un artículo (ZIP o DOCX) al portal AmeliCA."""
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Archivo no encontrado: {input_path}")
        sys.exit(1)

    saved_email, saved_password, saved_volume = load_credentials()
    email    = args.email    or saved_email    or input("📧 Email AmeliCA XML: ")
    password = args.password or saved_password or getpass.getpass("🔑 Contraseña: ")
    volume   = args.volumen  or saved_volume

    # Metadatos del artículo
    if input_path.suffix.lower() == '.zip':
        # Se extraen los datos reales (titulo, idioma, paginas) del index.html
        # dentro del zip; los flags de CLI (--titulo, etc.) sobreescriben si
        # se pasaron explicitamente, igual que en la rama .docx de abajo.
        data = extract_article_data_from_html(str(input_path))
        if args.titulo:        data['title']        = args.titulo
        if args.idioma:        data['language']     = args.idioma
        if args.tipo:          data['article_type'] = args.tipo
        if args.seccion:       data['section']      = args.seccion
        if args.pagina_inicio: data['page_start']   = args.pagina_inicio
        if args.pagina_fin:    data['page_end']     = args.pagina_fin
    else:
        # DOCX — extraer automáticamente y permitir sobreescribir
        data = extract_article_data(str(input_path))
        if args.titulo:        data['title']      = args.titulo
        if args.idioma:        data['language']   = args.idioma
        if args.tipo:          data['article_type'] = args.tipo
        if args.seccion:       data['section']    = args.seccion
        if args.pagina_inicio: data['page_start'] = args.pagina_inicio
        if args.pagina_fin:    data['page_end']   = args.pagina_fin

    print(f"\n{'─'*55}")
    print(f"📄 Archivo  : {input_path.name}")
    print(f"   Título   : {data['title'][:55]}")
    print(f"   Idioma   : {data['language']}")
    print(f"   Citación : {data['citation']}")
    if data['page_start']:
        print(f"   Páginas  : {data['page_start']} – {data['page_end']}")
    print(f"{'─'*55}\n")

    uploader = AmelicaUploader(
        email=email, password=password, headless=not args.show,
        fill_refs=args.referencias, overwrite=args.sobrescribir,
    )
    ok = await uploader.run(input_path=str(input_path), article_data=data,
                            keep_zip=args.keep_zip, target_volume=volume)
    # Salir con codigo != 0 si alguna etapa fallo: antes siempre salia 0,
    # aunque el marcaje y el front matter se hubieran caido.
    return 0 if ok else 1


async def cmd_batch(args):
    """Sube todos los ZIPs/DOCXs de una carpeta."""
    folder = Path(args.folder)
    files  = sorted(list(folder.glob('*.zip')) + list(folder.glob('*.docx')))

    if not files:
        print(f"⚠️  No hay archivos .zip ni .docx en: {folder}")
        return

    saved_email, saved_password, saved_volume = load_credentials()
    email    = args.email    or saved_email    or input("📧 Email AmeliCA XML: ")
    password = args.password or saved_password or getpass.getpass("🔑 Contraseña: ")

    print(f"\n📂 {len(files)} archivos en {folder}\n")
    ok, err = [], []

    for i, fpath in enumerate(files, 1):
        print(f"\n{'═'*55}")
        print(f"[{i}/{len(files)}] {fpath.name}")
        try:
            if fpath.suffix.lower() == '.zip':
                data = extract_article_data_from_html(str(fpath))
            else:
                data = extract_article_data(str(fpath))

            uploader = AmelicaUploader(email=email, password=password, headless=not args.show,
                                       fill_refs=args.referencias,
                                       overwrite=args.sobrescribir)
            success  = await uploader.run(input_path=str(fpath), article_data=data, target_volume=saved_volume)
            (ok if success else err).append(fpath.name)
        except Exception as e:
            print(f"   💥 Error: {e}")
            err.append(fpath.name)

    print(f"\n{'═'*55}")
    print(f"📊 RESUMEN: {len(ok)} OK  |  {len(err)} con etapas fallidas")
    for n in ok:  print(f"   ✅ {n}")
    for n in err: print(f"   ❌ {n}")
    print("   (❌ no significa que no se creó el artículo: puede estar creado")
    print("    pero incompleto. Revisá el detalle por etapa de cada uno.)")
    return 0 if not err else 1


# ─────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog='amelica',
        description='🔬 Automatización de carga de artículos en AmeliCA XML',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest='command', required=True)

    # zip-only
    pz = sub.add_parser('zip', help='Solo genera el index.zip sin subir (para inspeccionar)')
    pz.add_argument('input', help='Archivo .docx')
    pz.add_argument('-o', '--output', default='.', help='Carpeta de salida (default: carpeta actual)')

    # upload
    pu = sub.add_parser('upload', help='Sube un artículo (ZIP o DOCX)')
    pu.add_argument('input', help='Archivo .zip (recomendado) o .docx')
    _portal_args(pu)
    _article_args(pu)

    # batch
    pb = sub.add_parser('batch', help='Sube todos los ZIPs/DOCXs de una carpeta')
    pb.add_argument('folder', help='Carpeta con archivos')
    _portal_args(pb)

    return p


def _portal_args(p):
    p.add_argument('--email',    help='Email de AmeliCA XML')
    p.add_argument('--password', help='Contraseña')
    p.add_argument('--volumen',  help='Numero+edicion del volumen (ej: "38 (1)") -- si no se pasa, se usa el de credentials.json, o se pregunta interactivamente')
    p.add_argument('--show', action='store_true', help='Mostrar el navegador')
    p.add_argument('--keep-zip', dest='keep_zip', metavar='CARPETA',
                   help='Guardar el ZIP generado en esta carpeta (para inspeccionarlo)')
    p.add_argument('--sobrescribir', action='store_true',
                   help='Permitir pisar un articulo que YA tiene datos cargados. '
                        'Por defecto el paso de "Datos del articulo" aborta si '
                        'detecta autores con contenido, para no destruir trabajo '
                        'ya hecho.')
    p.add_argument('--referencias', action='store_true',
                   help='EXPERIMENTAL: cargar tambien las referencias en el portal. '
                        'Apagado por defecto porque borra las referencias preexistentes '
                        'del articulo y nunca se verifico en vivo. Sin este flag solo se '
                        'informa cuantas referencias se detectaron.')


def _article_args(p):
    p.add_argument('--titulo',        help='Título del artículo')
    p.add_argument('--tipo',          help='Tipo (ej: "Artículo científico")')
    p.add_argument('--seccion',       help='Sección (ej: "Artículos")')
    p.add_argument('--idioma',        help='Idioma (ej: "Español", "Inglés")')
    p.add_argument('--pagina-inicio', dest='pagina_inicio', help='Página inicial')
    p.add_argument('--pagina-fin',    dest='pagina_fin',    help='Página final')


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def cmd_zip(args):
    """Solo genera el ZIP sin subir — útil para inspeccionar el resultado."""
    from .parsing import build_zip_from_docx
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Archivo no encontrado: {input_path}"); return 1
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📄 Convirtiendo: {input_path.name}")
    zip_path = build_zip_from_docx(str(input_path), output_dir=str(output_dir))
    print(f"\n✅ ZIP guardado en: {zip_path}")
    print(f"   Puedes abrirlo con WinRAR/7-Zip para inspeccionar el contenido.")
    return 0


def main():
    parser = build_parser()
    args   = parser.parse_args()
    if   args.command == 'upload': code = asyncio.run(cmd_upload(args))
    elif args.command == 'batch':  code = asyncio.run(cmd_batch(args))
    elif args.command == 'zip':    code = cmd_zip(args)
    else:                          code = 1
    sys.exit(code or 0)


if __name__ == '__main__':
    main()
