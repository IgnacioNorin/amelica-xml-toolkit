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
    for (const b of document.querySelectorAll(
            'button, input[type=button], input[type=submit], a, [onclick]')) {
        if (b.offsetParent === null) continue;
        const txt = (b.innerText || b.textContent || b.value || '').trim();
        if (!txt || txt.length > 40) continue;
        out.push({texto: txt, tag: b.tagName, id: b.id || '',
                  clase: (b.className || '').slice(0, 60),
                  onclick: (b.getAttribute('onclick') || '').slice(0, 70)});
    }
    return out;
}"""

# El usuario confirmó que el botón que persiste el marcaje es "Guardar".
# Esto lo busca sin importar el tipo de elemento ni si está oculto, para
# saber si existe pero no es visible en ese momento.
JS_GUARDAR = r"""() => {
    const out = [];
    for (const el of document.querySelectorAll('*')) {
        const txt = (el.value || el.innerText || el.textContent || '').trim();
        if (txt.toLowerCase() !== 'guardar') continue;
        if (el.children.length > 1) continue;   // evitar contenedores
        out.push({
            tag: el.tagName,
            id: el.id || '',
            clase: (el.className || '').toString().slice(0, 70),
            visible: el.offsetParent !== null,
            onclick: (el.getAttribute('onclick') || '').slice(0, 90),
            padre_id: el.parentElement ? (el.parentElement.id || '') : '',
        });
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
        # Esperar la NAVEGACION a marker.oa. Contar botones no sirve: la
        # pagina del numero ya tiene varios, asi que la espera terminaba
        # enseguida sin haber salido de issue.oa.
        print("   ⏳ Esperando navegación al editor (marker.oa)...")
        for intento in range(25):
            await asyncio.sleep(2)
            if 'marker' in up.page.url.lower():
                print(f"   ✅ En el editor tras {(intento+1)*2}s")
                break
        else:
            print(f"   ⚠️  Nunca navegó al editor (sigue en {up.page.url})")

        # Aceptar el asistente de inferencias si aparece: mientras el modal
        # esté encima, el editor real no es accesible.
        await asyncio.sleep(3)
        acepto = await up.page.evaluate(r"""() => {
            for (const a of document.querySelectorAll('a, button')) {
                const t = (a.innerText || a.textContent || '').trim().toLowerCase();
                if ((t === 'aceptar' || t === 'continuar') && a.offsetParent !== null) {
                    a.click(); return t;
                }
            }
            return null;
        }""")
        if acepto:
            print(f"   ✅ Modal '{acepto}' aceptado")
            await asyncio.sleep(4)

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
            print(f"  [{b['tag']:6s}] {b['texto'][:30]:30s} id={b['id'][:26]:26s} "
                  f"{b['onclick'][:30]}")

        print("\n" + "═"*60)
        print("ELEMENTOS 'GUARDAR' (visibles y ocultos)")
        print("═"*60)
        guardar = await up.page.evaluate(JS_GUARDAR)
        if not guardar:
            print("  (ninguno)")
        for g in guardar:
            print(f"  [{g['tag']:6s}] visible={str(g['visible']):5s} id={g['id'][:34]}")
            print(f"           clase={g['clase'][:60]}")
            if g['onclick']:
                print(f"           onclick={g['onclick']}")

        # Ir a "Datos del artículo" — mismo texto que usa fill_front_matter
        await up._click_tab('datos del artículo')
        await asyncio.sleep(4)

        # Desplegar la sección de Fechas: las cajas pueden no existir en el
        # DOM hasta que se activa el contenedor.
        await up._click_caja('Fechas')
        await asyncio.sleep(2)

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

        # Lo que realmente hace falta saber: dado un control de fecha, ¿cuál
        # es el ancestro que lo agrupa con SU caja [title^="Fecha"]? Eso es
        # lo que permite apuntar a la fecha correcta en vez de al último
        # control del documento.
        print("\n" + "═"*60)
        print("RUTA DESDE CADA CONTROL HASTA SU CAJA DE FECHA")
        print("═"*60)
        rutas = await up.page.evaluate(r"""() => {
            const inps = [...document.querySelectorAll('input[class*="date-"]')]
                .filter(el => el.offsetParent !== null && el.type !== 'hidden');
            return inps.map(inp => {
                const cadena = [];
                let nodo = inp, nivel = 0, cajaTitulo = null, nivelCaja = -1;
                while (nodo && nivel < 12) {
                    const t = nodo.getAttribute && nodo.getAttribute('title');
                    cadena.push(nodo.tagName +
                        (nodo.id ? '#' + nodo.id.slice(-24) : '') +
                        (t ? '[title=' + t + ']' : ''));
                    if (t && t.startsWith('Fecha') && cajaTitulo === null) {
                        cajaTitulo = t; nivelCaja = nivel;
                    }
                    nodo = nodo.parentElement; nivel++;
                }
                return {input: inp.id.slice(-30), caja: cajaTitulo,
                        niveles_hasta_caja: nivelCaja, cadena: cadena};
            });
        }""")
        for r in rutas:
            print(f"\n  input …{r['input']}")
            print(f"    caja de fecha: {r['caja']!r} a {r['niveles_hasta_caja']} niveles arriba")
            for paso in r['cadena'][:8]:
                print(f"      ↑ {paso[:78]}")

        print("\n✅ Inspección terminada — no se modificó nada")
        return 0

    except Exception as e:
        print(f"\n💥 {type(e).__name__}: {e}")
        return 1
    finally:
        await up.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
