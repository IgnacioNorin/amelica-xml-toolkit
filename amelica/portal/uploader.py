"""
uploader.py — Orquestador del flujo contra el portal AmeliCA.

Flujo:
  1. Login
  2. Detectar numeros "En proceso" -> elegir (o usar el de credentials.json)
  3. Agregar articulo: rellenar modal -> "Crear"
  4. Subir el ZIP con index.html
  5. Click en "Marcar" -> abre el editor
  6. Marcaje automatico de secciones (AmelicaMarker)
  7. Completar "Datos del articulo" (front matter)
  8. Referencias — solo si se pide con --referencias (ver portal/references.py)
"""

import asyncio
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from ..parsing import (
    extract_article_data,
    extract_article_data_from_html,
    extract_full_article_data_from_html,
    build_zip_from_docx,
    fix_zip_for_amelica,
    parse_references_from_html,
)
from .dom import DomHelpersMixin
from .front_matter import FrontMatterMixin
from .marker import AmelicaMarker
from .references import ReferencesMixin

PORTAL_URL = "https://portal.amelica.org/ameli/issue.oa"


class AmelicaUploader(DomHelpersMixin, FrontMatterMixin, ReferencesMixin):

    def __init__(self, email: str, password: str, headless: bool = False,
                 fill_refs: bool = False, overwrite: bool = False):
        self.email    = email
        self.password = password
        self.headless = headless
        # Llenado de referencias en el portal: experimental, ver
        # portal/references.py. Apagado salvo que se pase --referencias.
        self.fill_refs = fill_refs
        # Permitir pisar un articulo que ya tiene datos cargados. Apagado:
        # por defecto el front matter aborta antes de sobrescribir trabajo
        # hecho (ver portal/front_matter.py).
        self.overwrite = overwrite
        self.page                = None
        self.browser             = None
        self._last_article_title = ''
        # Resultado real de cada etapa. Antes el flujo imprimia "completado"
        # y devolvia True aunque el marcaje y el front matter hubieran
        # fallado; ahora cada etapa deja registro y run() reporta la verdad.
        self.steps: dict[str, tuple[bool, str]] = {}

    # ── Registro de estado por etapa ─────────────────────────────

    #: Etapas cuyo fallo hace fallar la corrida entera. El resto (marcaje,
    #: front matter, referencias) degrada a "incompleto": el articulo quedo
    #: creado y se puede terminar a mano, pero NO es un exito.
    CRITICAL_STEPS = ('login', 'issue', 'article', 'zip')

    def _step(self, name: str, ok: bool, detail: str = '') -> bool:
        """Registra el resultado de una etapa y lo devuelve, para poder
        escribir `if not self._step('zip', await self.upload_zip(...)):`."""
        self.steps[name] = (ok, detail)
        return ok

    def _confirmar_zip_por_marcaje(self, marcaje_ok: bool) -> None:
        """Resuelve el estado del ZIP cuando el servidor no lo confirmó.

        El marcaje solo puede leer las secciones del artículo si el servidor
        proceso el HTML, asi que un marcaje exitoso es prueba de que el ZIP
        entro. Si el marcaje tampoco funciono, quedamos sin evidencia y el
        ZIP pasa a fallo: es el escenario donde de verdad conviene mirar.
        """
        if not getattr(self, '_zip_sin_confirmar', False):
            return
        if marcaje_ok:
            self._step('zip', True, 'confirmado indirectamente: el editor cargó el artículo')
        else:
            self._step('zip', False,
                       'sin confirmación del servidor y el editor no cargó el artículo')
        self._zip_sin_confirmar = False

    @property
    def succeeded(self) -> bool:
        """True solo si todas las etapas registradas salieron bien."""
        return bool(self.steps) and all(ok for ok, _ in self.steps.values())

    def print_summary(self) -> None:
        etiquetas = {
            'login':        'Login',
            'issue':        'Selección del número',
            'article':      'Alta del artículo',
            'zip':          'Subida del ZIP',
            'marcar':       'Apertura del editor',
            'marker':       'Marcaje de secciones',
            'front_matter': 'Datos del artículo',
            'references':   'Referencias',
        }
        print("\n" + "═"*55)
        print("📊 RESULTADO POR ETAPA")
        print("═"*55)
        for clave, etiqueta in etiquetas.items():
            if clave not in self.steps:
                continue
            ok, detail = self.steps[clave]
            print(f"   {'✅' if ok else '❌'} {etiqueta:24s}{' — ' + detail if detail else ''}")

        fallidas = [k for k, (ok, _) in self.steps.items() if not ok]
        if not fallidas:
            print("\n🎉 Proceso completado — todas las etapas OK")
        elif any(k in self.CRITICAL_STEPS for k in fallidas):
            print("\n💥 El proceso FALLÓ en una etapa crítica.")
        else:
            print("\n⚠️  Artículo creado pero INCOMPLETO — terminá a mano las")
            print("   etapas marcadas con ❌ en el navegador.")
        print("═"*55)

    # ── Ciclo de vida ────────────────────────────────────────────

    async def start(self):
        self._pw     = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=self.headless, slow_mo=350,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        self.page = await self.browser.new_page(
            viewport={'width': 1280, 'height': 900}, locale='es-419'
        )
        self.page.set_default_timeout(30_000)

    async def stop(self):
        if self.browser: await self.browser.close()
        if hasattr(self, '_pw'): await self._pw.stop()

    # ── Login ────────────────────────────────────────────────────

    async def login(self) -> bool:
        print("🔐 Iniciando sesión...")
        await self.page.goto(PORTAL_URL, wait_until='networkidle')

        try:
            await self.page.wait_for_selector('input[type="password"]', timeout=10_000)
        except PlaywrightTimeout:
            print("❌ Formulario de login no encontrado")
            await self._ss("debug_login"); return False

        user = await self.page.query_selector(
            'input[type="email"], input[type="text"][id*="user"], '
            'input[type="text"][name*="user"]'
        )
        if not user:
            inputs = await self.page.query_selector_all('input[type="text"]')
            user = inputs[0] if inputs else None

        pwd = await self.page.query_selector('input[type="password"]')

        if not user or not pwd:
            print("❌ Campos de login no encontrados")
            await self._ss("debug_no_fields"); return False

        await user.fill(self.email)
        await pwd.fill(self.password)

        btn = await self.page.query_selector(
            'button[type="submit"], input[type="submit"], button:has-text("Entrar")'
        )
        if btn: await btn.click()
        else:   await pwd.press('Enter')

        await asyncio.sleep(3)

        pages = self.browser.contexts[0].pages if self.browser.contexts else []
        if len(pages) > 1:
            self.page = pages[-1]
            print(f"   Nueva pestaña detectada, cambiando...")

        try:
            await self.page.wait_for_load_state('networkidle', timeout=15_000)
        except Exception:
            pass

        current_url = self.page.url
        print(f"   URL actual: {current_url}")

        if 'issue.oa' in current_url or 'home.oa' in current_url or 'journal' in current_url:
            print("✅ Login exitoso"); return True

        try:
            content = await self.page.content()
            if any(w in content for w in ['Bienvenido', 'Revista', 'Editor', 'Números']):
                print("✅ Login exitoso"); return True
        except Exception:
            pass

        if current_url == PORTAL_URL or 'issue.oa' not in current_url:
            print(f"❌ Login fallido. URL: {current_url}")
            try:
                await self._ss("debug_login_fail")
            except Exception:
                pass
            return False

        print("✅ Login exitoso (redirigido)"); return True

    # ── Selección interactiva de número ─────────────────────────

    async def pick_issue_interactive(self, target_volume: str | None = None) -> bool:
        print("\n🔍 Detectando números En proceso...")
        await asyncio.sleep(1.5)

        issues = await self._get_inprocess_issues()

        if not issues:
            print("⚠️  No se detectaron números En proceso.")
            await self._ss("debug_no_issues"); return False

        # Si se paso un volumen objetivo (desde credentials.json), buscar el
        # match exacto por texto y saltear la pregunta interactiva.
        if target_volume:
            norm_target = re.sub(r"\s+", " ", target_volume.strip())
            for iss in issues:
                norm_label = re.sub(r"\s+", " ", iss["label"].strip())
                if norm_label == norm_target:
                    print(f"\n🔧 Volumen preconfigurado encontrado: '{iss['label']}' (desde credentials.json)")
                    await self._click_gear(iss)
                    heading = await self.page.query_selector('h1, h2, h3')
                    if heading:
                        print(f"   Página: {(await heading.inner_text()).strip()}")
                    print("✅ Número seleccionado"); return True
            print(f"⚠️  No se encontró un volumen 'En proceso' que coincida con "
                  f"'{target_volume}' — se pide elegir manualmente.")

        print()
        print("┌────┬──────────┬────────────────────────────────────┐")
        print("│  # │ Tipo     │ Número                             │")
        print("├────┼──────────┼────────────────────────────────────┤")
        regulares  = [(i, iss) for i, iss in enumerate(issues) if not iss['especial']]
        especiales = [(i, iss) for i, iss in enumerate(issues) if iss['especial']]
        if regulares:
            print("│    │ ── REGULARES ──────────────────────────────│")
            for i, iss in regulares:
                print(f"│ {i+1:2d} │ Regular  │ {iss['label'][:36].ljust(36)} │")
        if especiales:
            print("│    │ ── ESPECIALES ─────────────────────────────│")
            for i, iss in especiales:
                print(f"│ {i+1:2d} │ Especial │ {iss['label'][:36].ljust(36)} │")
        print("└────┴──────────┴────────────────────────────────────┘")

        while True:
            try:
                choice = input(f"\n▶  Elige el número (1–{len(issues)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(issues): break
                print(f"   Ingresa un valor entre 1 y {len(issues)}")
            except (ValueError, KeyboardInterrupt):
                print("\nCancelado."); return False

        selected = issues[idx]
        print(f"\n🔧 Abriendo: {selected['label'].strip()}")
        await self._click_gear(selected)

        heading = await self.page.query_selector('h1, h2, h3')
        if heading:
            print(f"   Página: {(await heading.inner_text()).strip()}")

        agregar = await self.page.query_selector(
            'button:has-text("Agregar"), a:has-text("Agregar")'
        )
        if not agregar:
            print("⚠️  No se detectó botón 'Agregar artículo'")
            await self._ss("debug_after_gear_click")

        print("✅ Número seleccionado"); return True

    async def _get_inprocess_issues(self) -> list[dict]:
        link_ids = await self.page.evaluate("""
            () => {
                const IC_PROCESO = 'ic-proceso.png';
                const results = [];
                document.querySelectorAll('img').forEach(img => {
                    if (!(img.getAttribute('src') || '').includes(IC_PROCESO)) return;
                    const spanConIcono = img.parentElement;
                    if (!spanConIcono) return;
                    const spanPadre = spanConIcono.parentElement;
                    if (!spanPadre) return;
                    const spanLabel = spanPadre.querySelector('span:first-child');
                    if (!spanLabel) return;
                    const link = spanLabel.querySelector('a');
                    if (!link) return;
                    const onclick = link.getAttribute('onclick') || '';
                    if (!onclick.includes('enlace')) return;
                    const label = link.innerText.replace(/\\s+/g, ' ').trim();
                    results.push({
                        label,
                        especial: /^esp\\.?\\s/i.test(label),
                        linkId: link.id,
                    });
                });
                return results;
            }
        """)

        print(f"   JS encontró {len(link_ids)} números En proceso")
        issues = []
        for item in link_ids:
            link_id = item.get("linkId", "")
            if not link_id:
                continue
            issues.append({
                "label":    item["label"].strip(),
                "especial": item["especial"],
                "link_id":  link_id,
            })

        print(f"   ✅ {len(issues)} números En proceso detectados")
        return issues

    async def _click_gear(self, issue: dict) -> bool:
        link_id = issue.get("link_id", "")
        print(f"   Navegando al número (id={link_id})...")

        clicked = await self.page.evaluate(
            "id => { const el = document.getElementById(id); if (el) { el.click(); return true; } return false; }",
            link_id
        )
        if not clicked:
            print(f"❌ No se encontró elemento id={link_id}")
            await self._ss("debug_gear_lost"); return False

        print("   ✅ Click ejecutado")
        await asyncio.sleep(2)
        await self.page.wait_for_load_state("networkidle")
        await asyncio.sleep(1)
        return True

    # ── Agregar artículo ─────────────────────────────────────────

    async def _snapshot_article_blocks(self) -> list[dict]:
        """Foto de los artículos ya listados en el número: una clave estable
        por bloque, para poder distinguir después cuál es el recién creado.

        Sin esto, 'Marcar' se buscaba por texto del título y clickeaba el
        primer match del DOM. Si el artículo ya existía en el número, abría
        el viejo — y el front matter lo sobrescribía.

        Devuelve por bloque:
          titulo      texto del título
          clave       mejor identificador disponible (id, onclick o href)
          id_estable  SOLO id de elemento — nunca onclick/href, que pueden
                      ser posicionales y correrse al insertarse un artículo
        """
        return await self.page.evaluate(r"""() => {
            const linkMarcar = (b) => {
                for (const a of b.querySelectorAll('a')) {
                    if ((a.innerText || a.textContent || '').trim() === 'Marcar') return a;
                }
                return null;
            };
            const out = [];
            document.querySelectorAll('div.articulo').forEach((b) => {
                const t = b.querySelector('.titulo-articulo');
                const m = linkMarcar(b);
                const idEstable = b.id || (m && m.id) || '';
                out.push({
                    titulo: (t ? (t.innerText || t.textContent || '') : '')
                                .replace(/\s+/g, ' ').trim(),
                    id_estable: idEstable,
                    clave: idEstable
                        || (m && (m.getAttribute('onclick') || m.getAttribute('href')))
                        || '',
                });
            });
            return out;
        }""")

    @classmethod
    def decidir_articulo_a_marcar(cls, antes: list[dict], despues: list[dict],
                                  titulo: str) -> tuple[str, str]:
        """Decide sobre qué artículo abrir el editor. Función pura, sin DOM.

        Devuelve (estrategia, dato):
          ('clave', k)   → se identificó un único bloque nuevo: abrir ese.
          ('titulo', '') → no hay claves utilizables, pero ningún artículo
                           previo tenía este título, así que el match por
                           texto es necesariamente el nuestro.
          ('abortar', motivo) → ambiguo. NO tocar nada: abrir el equivocado
                           sobrescribe un artículo ya publicado.

        Con homónimos presentes solo se aceptan ids de elemento: un onclick
        o href puede ser posicional ("marcar(0)", "marcar(1)") y correrse
        cuando el portal inserta el artículo nuevo, con lo cual "el bloque
        nuevo" terminaría siendo el viejo — justo el caso que hay que evitar.

        Ojo: en AmeliCA los ids TAMBIÉN son posicionales
        ("j_idt66:0:j_idt77:3:form-opciones" — ese 3 es la fila). Si el
        artículo se agrega al final aparece una sola clave nueva y se
        identifica bien; si se inserta en el medio, todas las filas de abajo
        cambian de id, aparecen varias "nuevas" y esto aborta. Además, por
        las dudas, se exige que el bloque elegido tenga efectivamente el
        título que buscamos: sin esa guarda, un id nuevo podría corresponder
        a un artículo ajeno que solo se corrió de lugar.
        """
        homonimos = cls._titulos_coincidentes(antes, titulo)
        needle = (titulo or '')[:50].lower().strip()

        def nuevos_por(campo):
            previas = {b[campo] for b in antes if b.get(campo)}
            return [b for b in despues if b.get(campo) and b[campo] not in previas]

        def con_titulo_esperado(bloques):
            if not needle:
                return bloques
            return [b for b in bloques if needle in b.get('titulo', '').lower()]

        if homonimos:
            candidatos = con_titulo_esperado(nuevos_por('id_estable'))
            if len(candidatos) == 1:
                return ('clave', candidatos[0]['id_estable'])
            return ('abortar',
                    f'{homonimos} artículo(s) con el mismo título ya presentes '
                    f'y {len(candidatos)} bloque(s) nuevo(s) que coincidan')

        candidatos = con_titulo_esperado(nuevos_por('clave'))
        if len(candidatos) == 1:
            return ('clave', candidatos[0]['clave'])
        return ('titulo', '')

    @staticmethod
    def _titulos_coincidentes(bloques: list[dict], titulo: str) -> int:
        """Cuántos bloques ya tienen ese título (mismo criterio que usaba la
        búsqueda vieja: los primeros 50 caracteres, sin distinguir mayúsculas)."""
        needle = (titulo or '')[:50].lower().strip()
        if not needle:
            return 0
        return sum(1 for b in bloques if needle in b['titulo'].lower())

    async def add_article(self, data: dict) -> bool:
        print("\n📝 Abriendo formulario 'Nuevo artículo'...")

        # Foto ANTES de crear nada: es lo que después permite saber cuál de
        # los artículos del listado es el nuestro.
        self._blocks_before = await self._snapshot_article_blocks()
        ya_existian = self._titulos_coincidentes(
            self._blocks_before, data.get('title', ''))
        if ya_existian:
            print(f"   ⚠️  Ojo: ya hay {ya_existian} artículo(s) con ese título en el número.")
            print("      Se va a crear igual, pero el editor solo se abrirá si")
            print("      se puede identificar sin ambigüedad cuál es el nuevo.")

        try:
            await self.page.wait_for_selector(
                'button:has-text("Agregar"), a:has-text("Agregar")', timeout=8_000
            )
        except PlaywrightTimeout:
            pass

        btn = await self.page.query_selector(
            'button:has-text("Agregar artículo"), a:has-text("Agregar artículo")'
        )
        if not btn:
            for b in await self.page.query_selector_all('button, a'):
                txt = (await b.inner_text()).strip().lower()
                if 'agregar' in txt and 'art' in txt:
                    btn = b; break
        if not btn:
            print("❌ No se encontró 'Agregar artículo'")
            await self._ss("debug_no_agregar"); return False

        await btn.click()
        await asyncio.sleep(1.5)

        try:
            await self.page.wait_for_selector('#form-articulo', timeout=8_000)
        except PlaywrightTimeout:
            await asyncio.sleep(1.5)

        self._last_article_title = data.get('title', '')
        print(f"   📌 Título: {data['title'][:60]}")

        fill_result = await self.page.evaluate("""(d) => {
            function getFirst(ids) {
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (el) return el;
                }
                return null;
            }
            function setSelect(ids, label) {
                const sel = getFirst(ids);
                if (!sel) return false;
                for (const opt of sel.options) {
                    if (opt.text.trim() === label || opt.text.includes(label)) {
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
                return false;
            }
            function setInput(ids, val) {
                const el = getFirst(ids);
                if (!el) return false;
                el.value = val;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                return true;
            }

            return {
                tipo:     setSelect(['form-articulo-editar:form-tipo-editar_input', 'form-articulo:form-tipo_input'], d.article_type),
                titulo:   setInput (['form-articulo-editar:form-titulo-editar',     'form-articulo:form-titulo'],     d.title),
                seccion:  setSelect(['form-articulo-editar:form-seccion-editar_input', 'form-articulo:form-seccion_input'], d.section),
                idioma:   setSelect(['form-articulo-editar:form-idioma-editar_input',  'form-articulo:form-idioma_input'],  d.language),
                pag_ini:  d.page_start ? setInput(['form-articulo-editar:form-inicial-editar', 'form-articulo:form-inicial'], d.page_start) : null,
                pag_fin:  d.page_end   ? setInput(['form-articulo-editar:form-final-editar',   'form-articulo:form-final'],   d.page_end)   : null,
                citacion: setSelect(['form-articulo-editar:form-citacion_input', 'form-articulo:form-citacion_input'], d.citation),
            };
        }""", data)

        failed = [k for k, v in fill_result.items() if v is False]
        if failed:
            print(f"   ⚠️  No se pudieron completar estos campos (ID no encontrado en la pagina): {', '.join(failed)}")
        else:
            print(f"   ✅ Campos rellenados — páginas: {data.get('page_start','?')}–{data.get('page_end','?')}, citación: {data.get('citation','APA')}")
        await asyncio.sleep(0.5)

        clicked = await self.page.evaluate("""() => {
            const btn = document.querySelector('#form-articulo button[type="submit"], #form-articulo-editar button[type="submit"]');
            if (btn) { btn.click(); return true; }
            return false;
        }""")
        if not clicked:
            # "Crear" es el boton del panel "Agregar articulo"; "Actualizar"
            # es el boton real del panel "Editar articulo" (confirmado con
            # el HTML real del formulario) -- se prueban ambos.
            crear = await self.page.query_selector('button:has-text("Crear")')
            if not crear:
                crear = await self.page.query_selector('button:has-text("Actualizar")')
            if not crear:
                print("❌ Botón 'Crear'/'Actualizar' no encontrado")
                await self._ss("debug_no_crear"); return False
            await crear.click()

        print("   ✅ Click en 'Crear'/'Actualizar'")
        await asyncio.sleep(2.5)
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(1)

        print("   🔍 Abriendo panel de subida HTML...")
        await asyncio.sleep(1)

        opened = await self.page.evaluate("""() => {
            try {
                if (typeof PF === 'function') {
                    PF('panel-html').show();
                    try { PF('panel-articulo').hide(); } catch(e) {}
                    return 'PF-direct';
                }
            } catch(e) {}
            const panel = document.getElementById('panel-html');
            if (panel) {
                panel.style.display = 'block';
                const pa = document.getElementById('panel-articulo');
                if (pa) pa.style.display = 'none';
                return 'div-display';
            }
            return null;
        }""")

        if opened:
            print(f"   ✅ Panel HTML abierto ({opened})")
            await self.page.evaluate("""() => {
                try {
                    const a = document.getElementById('form-articulo:j_idt552');
                    if (a) PrimeFaces.ab({s: a, e: 'action', p: 'form-articulo:j_idt552', u: 'enlace'});
                } catch(e) {}
            }""")
            await asyncio.sleep(2)
        else:
            print("   ⚠️  No se pudo abrir panel HTML — súbelo manualmente")

        return True

    # ── Apertura del editor ("Marcar") ───────────────────────────

    async def _click_marcar_por_clave(self, clave: str) -> bool:
        """Clickea 'Marcar' en el bloque cuya clave coincida exactamente."""
        return await self.page.evaluate(r"""(clave) => {
            for (const b of document.querySelectorAll('div.articulo')) {
                let marcar = null;
                for (const a of b.querySelectorAll('a')) {
                    if ((a.innerText || a.textContent || '').trim() === 'Marcar') {
                        marcar = a; break;
                    }
                }
                if (!marcar) continue;
                // Acepta cualquiera de los identificadores con los que se
                // pudo haber tomado la foto (id de bloque, id del link, o
                // su onclick/href como ultimo recurso).
                const candidatos = [
                    b.id,
                    marcar.id,
                    marcar.getAttribute('onclick'),
                    marcar.getAttribute('href'),
                ].filter(Boolean);
                if (candidatos.includes(clave)) { marcar.click(); return true; }
            }
            return false;
        }""", clave)

    async def _click_marcar_por_titulo(self, titulo: str) -> bool:
        """Clickea 'Marcar' buscando por texto del título.

        Solo es seguro cuando se verificó antes que ningún artículo previo
        tenía ese título — si no, puede abrir el equivocado.
        """
        return await self.page.evaluate(r"""(titulo) => {
            const needle = titulo.substring(0, 50).toLowerCase().trim();
            if (!needle) return false;
            for (const b of document.querySelectorAll('div.articulo')) {
                const t = b.querySelector('.titulo-articulo');
                if (!t) continue;
                const txt = (t.innerText || t.textContent || '').toLowerCase();
                if (!txt.includes(needle)) continue;
                for (const a of b.querySelectorAll('a')) {
                    if ((a.innerText || a.textContent || '').trim() === 'Marcar') {
                        a.click(); return true;
                    }
                }
            }
            return false;
        }""", titulo)

    # ── Subir ZIP ────────────────────────────────────────────────

    async def upload_zip(self, zip_path: str) -> bool:
        print(f"\n📤 Subiendo ZIP ({Path(zip_path).stat().st_size // 1024} KB)...")

        upload_frame = None
        for attempt in range(15):
            await asyncio.sleep(1)
            for frame in self.page.frames:
                if 'upload' in (frame.url or '').lower():
                    upload_frame = frame
                    break
            if upload_frame:
                break
            print(f"   ⏳ Esperando iframe de subida... ({attempt+1}/15)")

        if not upload_frame:
            print("⚠️  No se encontró el iframe — usando página principal")
            upload_frame = self.page

        try:
            await upload_frame.wait_for_selector('input[type="file"]', timeout=10_000)
        except PlaywrightTimeout:
            print("❌ No apareció el input de archivo")
            await self._ss("debug_no_zip_input")
            return False

        file_input = await upload_frame.query_selector('input[type="file"]')
        if not file_input:
            print("❌ No se encontró input[type=file]")
            await self._ss("debug_no_file_input")
            return False

        await file_input.set_input_files(str(zip_path))
        print("   ✅ ZIP seleccionado")

        for sel in ['button:has-text("Subir")', 'button:has-text("Aceptar")',
                    'button:has-text("Cargar")', 'input[type="submit"]']:
            confirm = await upload_frame.query_selector(sel)
            if confirm:
                await confirm.click()
                print("   ✅ Confirmación enviada")
                break

        # Esperar a que aparezcan los span.mostrar1 — señal de que el servidor
        # procesó y aceptó el ZIP. Timeout de 60s, luego 2s extra.
        print("   ⏳ Esperando procesamiento del ZIP...")
        for attempt in range(60):
            await asyncio.sleep(1)
            mostrar = await self.page.evaluate("""() => {
                const spans = [...document.querySelectorAll('span.mostrar1')]
                    .filter(el => el.offsetParent !== null && (el.innerText||'').trim());
                return spans.length > 0 ? spans.map(s => s.innerText.trim()).join(' | ') : null;
            }""")
            if mostrar:
                print(f"   ✅ ZIP aceptado tras {attempt+1}s: {mostrar[:80]}")
                self._step('zip', True)
                await asyncio.sleep(2)
                break
            if attempt % 5 == 4:
                print(f"   ⏳ Esperando... ({attempt+1}s)")
        else:
            # span.mostrar1 no siempre aparece aunque el ZIP haya entrado
            # bien (comprobado el 2026-08-18: timeout acá y sin embargo el
            # editor cargó el artículo con sus 5 secciones). Se marca como
            # incierto, no como fallo: si despues el marcaje logra abrir el
            # articulo, eso prueba que el servidor lo proceso y se confirma
            # retroactivamente en _confirmar_zip_por_marcaje().
            print("   ⚠️  Sin confirmación explícita del ZIP — se verifica más adelante")
            self._step('zip', True, 'sin confirmación explícita (se verificó por el editor)')
            self._zip_sin_confirmar = True

        # Cerrar modal ZIP
        print("   🔒 Cerrando modal ZIP (click en X)...")
        await self.page.evaluate("""() => {
            const header = document.querySelector('#p-html_header, #panel-html .ui-panel-titlebar');
            if (header) {
                const btn = header.querySelector('a.ui-panel-titlebar-icon, a[aria-label]');
                if (btn) { btn.click(); return; }
            }
            const panelHtml = document.getElementById('panel-html');
            if (panelHtml) {
                const btn = panelHtml.querySelector('a[aria-label]');
                if (btn) btn.click();
            }
        }""")
        print("   ✅ Modal ZIP cerrado — esperando 4s...")
        await asyncio.sleep(4)

        # Cerrar modal artículo
        print("   🔒 Cerrando modal artículo (click en X)...")
        await self.page.evaluate("""() => {
            const header = document.querySelector('#p-articulo_header, #panel-articulo .ui-panel-titlebar');
            if (header) {
                const btn = header.querySelector('a.ui-panel-titlebar-icon, a[aria-label]');
                if (btn) { btn.click(); return; }
            }
            const panelArt = document.getElementById('panel-articulo');
            if (panelArt) {
                const btn = panelArt.querySelector('a[aria-label]');
                if (btn) btn.click();
            }
        }""")
        print("   ✅ Modal artículo cerrado — esperando 6s...")
        await asyncio.sleep(6)

        # Click en "Marcar" — sobre el artículo que ACABAMOS de crear.
        #
        # Se identifica por diferencia contra la foto tomada en add_article,
        # no por texto del título: si el número ya tenía un artículo con el
        # mismo nombre, la búsqueda por texto abría el viejo y el front
        # matter lo sobrescribía (llegó a borrar autores reales).
        titulo = self._last_article_title or ''
        print(f"\n   🎯 Identificando el artículo recién creado...")

        antes    = getattr(self, '_blocks_before', [])
        despues  = await self._snapshot_article_blocks()
        estrategia, dato = self.decidir_articulo_a_marcar(antes, despues, titulo)

        if estrategia == 'clave':
            print(f"   ✅ Identificado sin ambigüedad por clave del bloque")
            marcar_clicked = await self._click_marcar_por_clave(dato)

        elif estrategia == 'titulo':
            print("   ℹ️  Sin claves estables, pero el título no existía antes")
            marcar_clicked = await self._click_marcar_por_titulo(titulo)

        else:
            print("\n   🛑 ABORTADO: no se puede identificar el artículo nuevo.")
            print(f"      Motivo: {dato}")
            print("      Abrir el editor acá podría sobrescribir un artículo ya")
            print("      publicado, así que no se toca nada. El artículo quedó")
            print("      creado: abrí 'Marcar' a mano sobre el correcto.")
            self._step('marcar', False, f'ambiguo ({dato}) — no se abrió el editor')
            self._confirmar_zip_por_marcaje(False)
            return True

        if not marcar_clicked:
            print("   ⚠️  No se encontró el botón 'Marcar' — revisá el artículo manualmente")
            self._step('marcar', False, "no se encontró el botón 'Marcar'")
            self._confirmar_zip_por_marcaje(False)
            return True

        self._step('marcar', True)
        print(f"   ✅ Click en 'Marcar'")
        await asyncio.sleep(2)
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(1)

        # ── NUEVO: Marcaje automático de secciones ──────────────────
        print("\n" + "─"*55)
        print("🏷️  Iniciando marcaje automático de secciones...")
        print("─"*55)
        marker = AmelicaMarker(self.page, headless=self.headless)
        marked = await marker.run()
        self._step('marker', bool(marked),
                   '' if marked else 'el editor de marcaje no respondió')
        self._confirmar_zip_por_marcaje(bool(marked))
        if marked:
            print("\n🎉 ¡Artículo marcado exitosamente!")
        else:
            print("\n⚠️  Marcaje no completado — revisá manualmente el editor")

        # ── NUEVO: Completar "Datos del artículo" (titulos/autores/etc) ──
        try:
            full_data = extract_full_article_data_from_html(zip_path)
            ok_fm = await self.fill_front_matter(full_data)
            self._step('front_matter', bool(ok_fm),
                       '' if ok_fm else 'quedó incompleto')
        except Exception as e:
            print(f"\n⚠️  No se pudo completar 'Datos del artículo' automáticamente: {e}")
            print("   Completalo manualmente en el navegador.")
            self._step('front_matter', False, f'{type(e).__name__}: {e}')

        # ── Referencias: solo si se pidio explicitamente ──────────────────
        #
        # Apagado por defecto: el llenado en el portal nunca se verifico en
        # vivo y _delete_refs_but_one borra referencias preexistentes. El
        # parser si esta validado, asi que igual se informa cuantas se
        # detectaron para que sepas que hay para cargar a mano.
        # Ver amelica/portal/references.py.
        try:
            refs = self._parse_refs_from_zip(zip_path)
            if not refs:
                print("\n   ℹ️  No se encontraron referencias en el HTML")
            elif self.fill_refs:
                ok_refs = await self.fill_references(refs)
                self._step('references', bool(ok_refs))
            else:
                print(f"\n   📚 {len(refs)} referencias detectadas en el HTML.")
                print("      Cargalas a mano, o probá --referencias (experimental).")
                # No es un fallo: es el comportamiento pedido. Se registra
                # como pendiente para que aparezca en el resumen.
                self._step('references', True,
                           f'{len(refs)} detectadas, a cargar a mano (sin --referencias)')
        except Exception as e:
            print(f"\n⚠️  No se pudieron procesar las referencias: {e}")
            print("   Completá las referencias manualmente en el navegador.")
            self._step('references', False, f'{type(e).__name__}: {e}')

        return True

    @staticmethod
    def _parse_refs_from_zip(zip_path: str) -> list:
        """Lee el index.html del ZIP y devuelve sus referencias parseadas."""
        with zipfile.ZipFile(zip_path) as z:
            html_name = next((n for n in z.namelist() if n.endswith('index.html')), None)
            if not html_name:
                return []
            html = z.read(html_name).decode('utf-8', errors='replace')
        return parse_references_from_html(html)

    # ── Screenshot helper ────────────────────────────────────────

    async def _ss(self, name: str):
        try:
            path = f"{name}_{int(time.time())}.png"
            await self.page.screenshot(path=path, full_page=True)
            print(f"   📸 {path}")
        except Exception:
            pass  # No romper el flujo si la página está cerrada

    # ── Flujo principal ──────────────────────────────────────────

    async def run(self, input_path: str, article_data: dict | None = None, keep_zip: str | None = None, target_volume: str | None = None) -> bool:
        input_path = Path(input_path)
        if not input_path.exists():
            print(f"❌ Archivo no encontrado: {input_path}"); return False

        # Aceptar tanto .docx como .zip directamente
        if input_path.suffix.lower() == '.zip':
            print(f"   📂 ZIP recibido — aplicando correcciones AmeliCA...")
            zip_path = fix_zip_for_amelica(str(input_path))
            if article_data is None:
                # Antes: placeholders fijos. Ahora: se extraen los datos reales
                # (titulo, idioma, paginas) directamente del index.html generado,
                # que ya trae esa info bien etiquetada -- no hace falta adivinar.
                article_data = extract_article_data_from_html(str(input_path))
        else:
            if article_data is None:
                article_data = extract_article_data(str(input_path))
            zip_path = build_zip_from_docx(str(input_path), output_dir=keep_zip)

        cleanup_dir = os.path.dirname(zip_path)

        try:
            await self.start()

            # Las 4 etapas criticas cortan el flujo si fallan. Las de despues
            # (marcaje, front matter, referencias) no cortan -- el articulo ya
            # esta creado y conviene avanzar lo que se pueda -- pero cada una
            # deja su resultado en self.steps y sale en el resumen final.
            if not self._step('login', await self.login()):
                return False
            if not self._step('issue', await self.pick_issue_interactive(target_volume)):
                return False
            if not self._step('article', await self.add_article(article_data)):
                return False
            self.steps.setdefault('zip', (True, ''))   # upload_zip lo pisa si falla
            if not await self.upload_zip(zip_path):
                self._step('zip', False, 'no se pudo subir el ZIP')
                return False

            self.print_summary()

            if not self.headless:
                print("\n   El navegador sigue abierto para que revises el")
                print("   resultado. Cuando termines, presioná Enter acá")
                print("   para cerrar.")
                try:
                    input()
                except EOFError:
                    # Corriendo sin terminal interactiva (CI, pipe): no es un
                    # fallo del proceso, solo no hay quien apriete Enter.
                    print("   (sin terminal interactiva — cerrando)")

            return self.succeeded

        except Exception as e:
            print(f"\n💥 Error: {e}")
            if self.page: await self._ss("error_fatal")
            if self.steps:
                self.print_summary()
            raise
        finally:
            if not keep_zip:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            else:
                print(f"   📁 ZIP guardado en: {cleanup_dir}")
            await self.stop()
