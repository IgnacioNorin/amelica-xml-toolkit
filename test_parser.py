"""
test_parser.py — Diagnóstico del parser de referencias
Uso: python test_parser.py ruta/al/articulo.zip
"""
import sys, os, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amelica_uploader import parse_references_from_html

if len(sys.argv) < 2:
    print("Uso: python test_parser.py ruta/al/articulo.zip")
    sys.exit(1)

with zipfile.ZipFile(sys.argv[1]) as z:
    html = z.read('index.html').decode('utf-8')

refs = parse_references_from_html(html)
print(f"Total referencias: {len(refs)}\n")

# Resumen por tipo
from collections import Counter
tipos = Counter(r['pub_type'] for r in refs)
print("=== TIPOS ===")
for t, n in sorted(tipos.items()):
    print(f"  {t}: {n}")

# Mostrar 2 de cada tipo
print("\n=== MUESTRA POR TIPO ===")
shown = {}
for r in refs:
    t = r['pub_type']
    if shown.get(t, 0) >= 2:
        continue
    shown[t] = shown.get(t, 0) + 1
    surname = r['authors'][0]['surname'] if r['authors'] else '(inst.)'
    print(f"\n[{t}] {surname} ({r['year']})")
    print(f"  title:  {r['article_title'][:65]}")
    print(f"  source: {r['source'][:60]}")
    print(f"  vol: {r['volume']}  issue: {r['issue']}  "
          f"fpage: {r['fpage']}  lpage: {r['lpage']}  eloc: {r['elocation']}")
    print(f"  url: {r['url'][:60]}")
    print(f"  authors: {len(r['authors'])} → {r['authors'][:2]}")

print(f"\n=== RESUMEN ===")
print(f"Total:       {len(refs)}")
print(f"Con año:     {sum(1 for r in refs if r.get('year'))}")
print(f"Con título:  {sum(1 for r in refs if r.get('article_title'))}")
print(f"Con source:  {sum(1 for r in refs if r.get('source'))}")
print(f"Con volumen: {sum(1 for r in refs if r.get('volume'))}")
print(f"Con páginas: {sum(1 for r in refs if r.get('fpage'))}")
print(f"Con eloc:    {sum(1 for r in refs if r.get('elocation'))}")
print(f"Con URL:     {sum(1 for r in refs if r.get('url'))}")
