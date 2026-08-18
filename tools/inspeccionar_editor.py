"""
inspeccionar_editor.py — Vuelca la estructura REAL del editor de AmeliCA.

No escribe nada: abre un artículo existente y describe el DOM de las partes
que el uploader manipula a ciegas. Sirve para dejar de adivinar selectores.

Vuelca:
  - Las cajas de fecha: dónde viven realmente el <select> de tipo y el
    <input> del datepicker respecto del elemento [title^="Fecha"].
  - Los botones disponibles en la pantalla de marcaje (para encontrar cuál
    persiste el trabajo: "Inferir", "Guardar", u otro).
  - Los campos de autor y sus atributos title=.

Uso:
    python tools/inspeccionar_editor.py "<título parcial del artículo>"
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amelica.config import load_credentials
from amelica.portal import AmelicaUploader

JS_BOTONES = r"""() => {
    const out = [];
    for (const b of document.querySelectorAll('button, input[type=button], input[type=submit], a')) {
        if (b.offsetParent === null) continue;
        const txt = (b.innerText || b.textContent || b.value || '').trim();
        if (!txt || txt.length > 40) continue;
        out.push({texto: txt, tag: b.tagName, id: b.id || '',
                  clase: (b.className || '').slice(0, 60)});
    }
    return out;
}"""

JS_FECHAS = r"""() => {
    const cajas = [...document.querySelectorAll('[title]')]
        .filter(el => el.offsetParent !== null &&
                      (el.getAttribute('title') || '').startsWith('Fecha'));
    return cajas.map((caja, i) => {
        // ¿El select/input están DENTRO de la caja, o hay que subir?
        const dentroSel = caja.querySelectorAll('select').length;
        const dentroInp = caja.querySelectorAll('input').length;
        // Buscar hacia arriba hasta encontrar un ancestro que los contenga
        let nivel = 0, nodo = caja, encontradoEn = -1;
        while (nodo && nivel < 6) {
            if (nodo.querySelectorAll &&
                nodo.querySelectorAll('select[class*="date-type-"]').length &&
                nodo.querySelectorAll('input[class*="date-"]').length) {
                encontradoEn = nivel; break;
            }
            nodo = nodo.parentElement; nivel++;
        }
        return {
            indice: i,
            title: caja.getAttribute('title'),
            tag: caja.tagName,
            id: caja.id || '',
            selects_dentro: dentroSel,
            inputs_dentro: dentroInp,
            ancestro_con_controles: encontradoEn,
            texto: (caja.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 70),
        };
    });
}"""

JS_CONTROLES_FECHA = r"""() => {
    const sels = [...document.querySelectorAll('select[class*="date-type-"]')]
        .filter(el => el.offsetParent !== null);
    const inps = [...document.querySelectorAll('input[class*="date-"]')]
        .filter(el => el.offsetParent !== null && el.type !== 'hidden');
    return {
        selects: sels.map(s => ({id: s.id, valor: s.value,
                                 clase: (s.className || '').slice(0, 50)})),
        inputs: inps.map(i => ({id: i.id, valor: i.value,
                                clase: (i.className || '').slice(0, 50)})),
    };
}"""


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    buscado = sys.argv[1].lower()

    creds = load_credentials()
    up = AmelicaUploader(email=creds.email, password=creds.password, headless=True)

    try:
        await up.start()
        if not await up.login():
            print("❌ Login falló"); return 1
        if not await up.pick_issue_interactive(creds.volume):
            print("❌ No se pudo abrir el número"); return 1

        bloques = await up._snapshot_article_blocks()
        objetivo = next((b for b in bloques if buscado in b['titulo'].lower()), None)
        if not objetivo:
            print(f"❌ No se encontró un artículo que contenga «{sys.argv[1]}»")
            print("   Artículos en el número:")
            for b in bloques:
                print(f"     • {b['titulo'][:65]}")
            return 1

        print(f"\n📄 Artículo: {objetivo['titulo'][:65]}")
        if not await up._click_marcar_por_clave(objetivo['clave']):
            print("❌ No se pudo abrir el editor"); return 1

        # El editor tarda: esperar a que aparezca algo con lo que trabajar
        # en vez de dormir una cantidad fija y esperar lo mejor.
        print("   ⏳ Esperando el editor...")
        for intento in range(20):
            await asyncio.sleep(2)
            listo = await up.page.evaluate(
                "() => document.querySelectorAll('button, input[type=button]').length")
            if listo:
                print(f"   ✅ Editor con {listo} controles tras {(intento+1)*2}s")
                break
        else:
            print("   ⚠️  El editor no mostró controles")

        print(f"   URL: {up.page.url}")

        # Volcar el HTML crudo para poder analizarlo sin adivinar
        destino = Path(__file__).resolve().parent.parent / "editor_dump.html"
        destino.write_text(await up.page.content(), encoding="utf-8")
        print(f"   💾 HTML volcado en: {destino.name} "
              f"({destino.stat().st_size // 1024} KB)")

        print("\n" + "═"*60)
        print("BOTONES VISIBLES EN LA PANTALLA DE MARCAJE")
        print("═"*60)
        for b in await up.page.evaluate(JS_BOTONES):
            print(f"  [{b['tag']:6s}] {b['texto'][:32]:32s} id={b['id'][:28]}")

        # Ir a "Datos del artículo" para inspeccionar las fechas
        await up._click_tab('datos')
        await asyncio.sleep(3)

        print("\n" + "═"*60)
        print("CAJAS DE FECHA — ¿dónde viven sus controles?")
        print("═"*60)
        fechas = await up.page.evaluate(JS_FECHAS)
        if not fechas:
            print("  (ninguna caja [title^='Fecha'] visible)")
        for f in fechas:
            print(f"  [{f['indice']}] title={f['title']!r} tag={f['tag']}")
            print(f"       selects adentro: {f['selects_dentro']}  "
                  f"inputs adentro: {f['inputs_dentro']}")
            print(f"       ancestro con ambos controles, subiendo: "
                  f"{f['ancestro_con_controles']} niveles "
                  f"({'la caja misma' if f['ancestro_con_controles'] == 0 else 'NO es la caja'})")
            print(f"       texto: {f['texto']}")

        print("\n" + "═"*60)
        print("CONTROLES DE FECHA EN LA PÁGINA")
        print("═"*60)
        ctl = await up.page.evaluate(JS_CONTROLES_FECHA)
        print(json.dumps(ctl, indent=2, ensure_ascii=False)[:1800])

        print("\n✅ Inspección terminada — no se modificó nada")
        return 0

    except Exception as e:
        print(f"\n💥 {type(e).__name__}: {e}")
        return 1
    finally:
        await up.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
