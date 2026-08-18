"""
smoke_test.py — Verifica el flujo hasta el login SIN escribir en el portal.

Hace: abrir navegador -> login -> listar los numeros "En proceso" -> cerrar.
NO crea articulos, no sube ZIPs, no toca referencias. Es seguro correrlo
las veces que haga falta.

Sirve para comprobar que el paquete quedo bien armado despues del refactor:
ejercita config.py, portal/__init__.py, la resolucion de los mixins,
start(), login() y _get_inprocess_issues().

Con --inspeccionar entra además al número configurado y describe cómo
identifica el portal a cada artículo del listado. Eso decide si el arreglo
anti-sobrescritura va a poder distinguir el artículo nuevo por id, o si va a
tener que abortar por ambigüedad. Sigue sin escribir nada.

Uso:
    python tools/smoke_test.py                 # con navegador visible
    python tools/smoke_test.py --headless
    python tools/smoke_test.py --inspeccionar  # + diagnóstico del listado
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amelica.config import load_credentials
from amelica.portal import AmelicaUploader


async def inspeccionar_listado(up) -> None:
    """Describe cómo identifica el portal a cada artículo del listado.

    Lo único que importa saber: ¿los bloques traen un id de elemento? De eso
    depende que el uploader pueda distinguir el artículo recién creado de uno
    homónimo ya publicado, o tenga que abortar por ambigüedad.
    """
    print("\n" + "─" * 55)
    print("🔬 Inspección del listado de artículos (solo lectura)")
    print("─" * 55)

    bloques = await up._snapshot_article_blocks()
    if not bloques:
        print("   ⚠️  No se detectó ningún div.articulo.")
        print("      O el número está vacío, o cambió la estructura del portal")
        print("      (en ese caso el selector 'div.articulo' quedó obsoleto).")
        return

    con_id  = [b for b in bloques if b["id_estable"]]
    con_alt = [b for b in bloques if not b["id_estable"] and b["clave"]]
    sin_nada = [b for b in bloques if not b["clave"]]

    print(f"   Artículos en el número : {len(bloques)}")
    print(f"   Con id de elemento     : {len(con_id)}")
    print(f"   Solo onclick/href      : {len(con_alt)}")
    print(f"   Sin identificador      : {len(sin_nada)}")

    print("\n   Muestra:")
    for b in bloques[:5]:
        tipo = "id" if b["id_estable"] else ("alt" if b["clave"] else "—")
        print(f"     [{tipo:3s}] {b['clave'][:34]:34s} │ {b['titulo'][:38]}")
    if len(bloques) > 5:
        print(f"     … y {len(bloques) - 5} más")

    # Títulos repetidos: son el escenario que dispara el aborto.
    vistos, repetidos = set(), set()
    for b in bloques:
        clave_tit = b["titulo"][:50].lower().strip()
        if clave_tit in vistos:
            repetidos.add(clave_tit)
        vistos.add(clave_tit)

    # ¿Los ids son posicionales? En AmeliCA lo son: el patrón JSF
    # "j_idt66:0:j_idt77:3:form-opciones" lleva el número de fila adentro,
    # así que un id NO es prueba de identidad estable.
    indices = [re.findall(r":(\d+):", b["id_estable"])[-1]
               for b in con_id if re.findall(r":(\d+):", b["id_estable"])]
    # Un índice distinto por bloque = el id codifica la fila, no la identidad.
    son_posicionales = len(con_id) > 1 and len(set(indices)) == len(con_id)

    print("\n   📌 Veredicto:")
    if not con_id:
        print("      NINGÚN bloque tiene id de elemento → con un título que ya")
        print("      exista en el número, el uploader aborta antes de abrir el")
        print("      editor (correcto, pero hay que marcar a mano).")
    elif son_posicionales:
        print("      Los ids llevan el número de fila adentro → son POSICIONALES,")
        print("      no identidad. El uploader lo contempla: si el artículo nuevo")
        print("      se agrega al final, lo identifica bien; si se inserta en el")
        print("      medio, las filas de abajo cambian de id, aparecen varias")
        print("      'nuevas' y aborta en vez de adivinar. Además exige que el")
        print("      bloque elegido tenga el título esperado.")
    elif len(con_id) == len(bloques):
        print("      Todos los bloques tienen id y no parecen posicionales →")
        print("      identificación confiable incluso con homónimos.")
    else:
        print("      Solo algunos bloques tienen id → funciona salvo que el")
        print("      artículo nuevo caiga entre los que no lo tienen.")

    if repetidos:
        print(f"\n      ⚠️  Ya hay {len(repetidos)} título(s) duplicado(s) en el número.")
    else:
        print("\n      Sin títulos duplicados hoy en el número.")


async def main() -> int:
    headless = "--headless" in sys.argv
    creds = load_credentials()

    if not creds.email or not creds.password:
        print("❌ Faltan credenciales. Configurá credentials.json o "
              "AMELICA_EMAIL / AMELICA_PASSWORD.")
        return 1

    print("─" * 55)
    print("🔍 SMOKE TEST — solo lectura, no escribe nada en el portal")
    print(f"   Cuenta : {creds.email}")
    print(f"   Volumen configurado: {creds.volume!r}")
    print("─" * 55)

    up = AmelicaUploader(email=creds.email, password=creds.password,
                         headless=headless)

    # Chequeo de armado del paquete antes de tocar la red: si el split de
    # mixins quedo mal, preferimos enterarnos aca y no a mitad del flujo.
    faltantes = [m for m in ("login", "add_article", "upload_zip",
                             "fill_front_matter", "fill_references",
                             "_click_caja", "_get_inprocess_issues", "run")
                 if not hasattr(up, m)]
    if faltantes:
        print(f"❌ Métodos faltantes tras el refactor: {faltantes}")
        return 1
    print(f"✅ Mixins resueltos — fill_refs={up.fill_refs} (debe ser False)\n")

    try:
        await up.start()
        print("✅ Navegador abierto\n")

        if not await up.login():
            print("\n❌ Login falló — revisá credenciales o si cambió el portal")
            return 1
        print("\n✅ Login OK\n")

        issues = await up._get_inprocess_issues()
        if not issues:
            print("\n⚠️  No se detectó ningún número 'En proceso'.")
            print("   Puede ser normal (no hay números abiertos) o puede")
            print("   significar que cambió el HTML del portal.")
        else:
            print(f"\n📋 Números 'En proceso' detectados ({len(issues)}):")
            for i in issues:
                marca = "  ← coincide con credentials.json" \
                        if creds.volume and creds.volume in i["label"] else ""
                print(f"   • {i['label']}{marca}")

            if creds.volume and not any(creds.volume in i["label"] for i in issues):
                print(f"\n⚠️  El volumen configurado {creds.volume!r} NO está entre")
                print("   los números en proceso — un upload preguntaría cuál usar.")

        if "--inspeccionar" in sys.argv:
            if not await up.pick_issue_interactive(creds.volume):
                print("\n⚠️  No se pudo abrir el número — se omite la inspección")
            else:
                await inspeccionar_listado(up)

        print("\n" + "═" * 55)
        print("🎉 Smoke test OK — nada fue creado ni modificado")
        print("═" * 55)
        return 0

    except Exception as e:
        print(f"\n💥 Error: {type(e).__name__}: {e}")
        if up.page:
            await up._ss("smoke_error")
        return 1
    finally:
        await up.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
