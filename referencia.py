import zipfile, re
with zipfile.ZipFile('index.zip') as z:
    html = z.read('index.html').decode('utf-8')

for m in re.finditer(r'<p[^>]*class="[^"]*reference[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL):
    if 'VersionOne' in m.group(1) or 'Neumann' in m.group(1):
        print(repr(m.group(1)[:400]))
        print()