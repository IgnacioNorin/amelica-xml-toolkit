"""
smoke_test.py — Verifica el flujo hasta el login SIN escribir en el portal.

Hace: abrir navegador -> login -> listar los numeros "En proceso" -> cerrar.
NO crea articulos, no sube ZIPs, no toca referencias. Es seguro correrlo
las veces que haga falta.

Sirve para comprobar que el paquete quedo bien armado despues del refactor:
ejercita config.py, portal/__init__.py, la resolucion de los mixins,
start(), login() y _get_inprocess_issues().

Uso:
    python tools/smoke_test.py           # con navegador visible
    python tools/smoke_test.py --headless
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amelica.config import load_credentials
from amelica.portal import AmelicaUploader


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
