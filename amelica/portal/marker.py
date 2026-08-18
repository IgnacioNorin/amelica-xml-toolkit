"""
amelica_marker.py  —  Automatización del marcaje de secciones en AmeliCA XML
=============================================================================
El editor de AmeliCA usa un modal (#maskInfP) con DOS PANELES que alternan:
  - Panel secciones: #arbol con los textareas
  - Panel artículo: #articuloIn con el HTML del artículo

Flujo por cada sección:
  1. Click en textarea → artículo se carga en #articuloIn (~1s)
  2. Click en heading del artículo → texto va al textarea, vuelve panel secciones
"""

import asyncio
import re
from typing import Optional

# Marcador de version: si al correr esto NO ves esta linea en la consola con
# este numero, estas corriendo una version vieja en cache -- borra la carpeta
# __pycache__/ de este proyecto y volve a intentar.
MARKER_VERSION = "2026-08-07-solo-h1"


class AmelicaMarker:
    """Automatiza el marcaje de secciones en el editor de AmeliCA XML."""

    def __init__(self, page, headless: bool = False, auto_guardar: bool = True):
        self.page     = page
        self.headless = headless
        # "Guardar" es lo que persiste el marcaje. Por defecto se hace
        # siempre: no depende de si el navegador esta visible o no.
        self.auto_guardar = auto_guardar
        self._sections_cache = []  # Cache de secciones extraídas

    # ── Punto de entrada ─────────────────────────────────────────

    async def run(self) -> bool:
        """
        Ejecuta el flujo completo de marcaje.
        Debe llamarse cuando la página ya está en marker.oa.
        """
        print("\n🏷️  Iniciando marcaje automático de secciones...")
        print(f"   🔖 Version del script: {MARKER_VERSION}")

        # ── Esperar a que la navegación a marker.oa termine ──────────
        print("   ⏳ Esperando navegación a marker.oa...")
        try:
            await self.page.wait_for_url('**/marker.oa**', timeout=20_000)
        except Exception:
            pass  # Si la URL ya coincide, continuar

        try:
            await self.page.wait_for_load_state('networkidle', timeout=20_000)
        except Exception:
            print("   ⚠️  networkidle no alcanzado — continuando de todas formas")

        await asyncio.sleep(2)  # Buffer extra por si el JS sigue inicializando

        # ── Paso 0: Aceptar el modal del asistente si aparece ────────
        await self._accept_inference_assistant()

        # Esperar a que el modal del editor esté presente
        try:
            await self.page.wait_for_selector('#maskInfP', timeout=15_000)
            await self.page.wait_for_selector('#intArbol', timeout=15_000)
        except Exception:
            print("   ⚠️  Editor de marcaje no detectado — verificá la página")
            return False

        await asyncio.sleep(1)

        # Paso 1: Click en el primer textarea para cargar el artículo
        print("   🖱️  Activando primer textarea para cargar el artículo...")
        first_textarea = await self.page.query_selector(
            '#intArbol .txtarea:not(.txtareafinArticulo)'
        )
        if not first_textarea:
            print("   ⚠️  No se encontró el primer textarea")
            return False

        await first_textarea.click()
        print("   ⏳ Esperando que cargue el artículo en #articuloIn...")
        await asyncio.sleep(2.5)

        # Verificar que #articuloIn tenga contenido
        has_content = await self.page.evaluate("""() => {
            const el = document.getElementById('articuloIn');
            return el && el.innerText && el.innerText.trim().length > 50;
        }""")

        if not has_content:
            # Esperar un poco más
            await asyncio.sleep(3)
            has_content = await self.page.evaluate("""() => {
                const el = document.getElementById('articuloIn');
                return el && el.innerText && el.innerText.trim().length > 50;
            }""")

        if not has_content:
            print("   ⚠️  #articuloIn sigue vacío — el artículo no cargó")
            return False

        print("   ✅ Artículo cargado en #articuloIn")

        # Paso 2: Extraer secciones del artículo (ahora que está cargado)
        sections = await self._extract_article_sections()
        if not sections:
            print("   ⚠️  No se detectaron secciones en el artículo")
            return False

        print(f"   📋 Secciones detectadas: {len(sections)}")
        for s in sections:
            lvl = "  " * (s['level'] - 1)
            print(f"      {lvl}{'└─' if s['level'] > 1 else '•'} {s['text'][:60]}")

        self._sections_cache = sections

        # Paso 3: Primera sección — ya hay textarea activo y artículo cargado
        # Solo hacer click en el heading correspondiente
        print(f"\n   📝 Marcando sección 1/{len(sections)}: {sections[0]['text'][:50]}")
        success = await self._click_heading_in_article(sections[0], is_first=True)
        if not success:
            print(f"      ⚠️  No se pudo marcar la primera sección")

        await asyncio.sleep(1)

        # Paso 4: Secciones restantes
        for i, section in enumerate(sections[1:], start=1):
            print(f"\n   📝 Marcando sección {i+1}/{len(sections)}: {section['text'][:50]}")

            prev_level = sections[i-1]['level']
            curr_level = section['level']

            if curr_level > prev_level:
                # Subsección
                success = await self._add_and_fill_subsection(section)
            else:
                # Nueva sección del mismo nivel o superior
                success = await self._add_and_fill_section(section)

            if not success:
                print(f"      ⚠️  No se pudo marcar: {section['text'][:40]}")

            await asyncio.sleep(0.5)

        # Paso 5: Textarea de fin de artículo
        await self._fill_end_of_article()

        # Paso 6: Verificar y manejar amarillos
        await self._handle_verification()

        # Paso 7: Click en "Guardar" — es lo que persiste el marcaje.
        #
        # Antes se buscaba "Inferir", que no existe en esta pantalla, y
        # ademas estaba detras de `if self.headless`: corriendo con --show
        # (el modo recomendado) el marcaje no se guardaba nunca y al volver
        # a entrar estaba todo perdido. El modo de visualizacion no puede
        # cambiar si el trabajo se guarda o no.
        if not self.auto_guardar:
            print("\n   ✅ Marcaje completado — SIN guardar (--no-guardar).")
            print("      Hacé click en 'Guardar' en el navegador o se pierde.")
            return True

        if not await self._click_guardar():
            print("\n   ❌ Marcaje NO guardado.")
            print("      Las secciones se marcaron pero se pierden al salir.")
            print("      Guardalo a mano en el navegador.")
            return False

        # Comprobar que quedó realmente guardado, no solo que el click salió.
        persistio = await self._verificar_persistencia()
        if persistio is True:
            print("\n   ✅ Marcaje guardado y verificado tras recargar")
            return True
        if persistio is False:
            print("\n   ❌ Se guardó pero al recargar las secciones NO están.")
            print("      Revisá el artículo en el navegador.")
            return False

        print("\n   ⚠️  Marcaje guardado, pero no se pudo verificar la recarga.")
        print("      Confirmá a mano que las secciones quedaron.")
        return False

    # ── Aceptar modal del asistente ───────────────────────────────

    async def _accept_inference_assistant(self):
        """
        Detecta y acepta el modal del asistente de inferencias (#wlcmInferParrafos).
        """
        print("   🔍 Verificando modal del asistente de inferencias...")

        modal_found = False
        for _ in range(8):
            await asyncio.sleep(1)
            visible = await self.page.evaluate("""() => {
                const modal = document.getElementById('wlcmInferParrafos');
                if (!modal) return false;
                const style = window.getComputedStyle(modal);
                return style.display !== 'none' && style.visibility !== 'hidden';
            }""")
            if visible:
                modal_found = True
                break

        if not modal_found:
            print("   ℹ️  Modal del asistente no detectado — continuando")
            return

        print("   ✅ Modal detectado — haciendo click en 'Aceptar'...")

        accepted = await self.page.evaluate("""() => {
            const modal = document.getElementById('wlcmInferParrafos');
            if (!modal) return false;
            const btns = modal.querySelectorAll('button');
            for (const btn of btns) {
                const txt = (btn.innerText || btn.textContent || '').trim();
                if (txt === 'Aceptar') {
                    btn.click();
                    return true;
                }
            }
            if (typeof infiereParrafos === 'function') {
                infiereParrafos();
                return 'direct-call';
            }
            return false;
        }""")

        if accepted:
            print(f"   ✅ Asistente aceptado ({accepted}) — esperando editor...")
            await asyncio.sleep(3)

            # Esperar que el modal del asistente desaparezca
            for _ in range(10):
                await asyncio.sleep(1)
                still_visible = await self.page.evaluate("""() => {
                    const modal = document.getElementById('wlcmInferParrafos');
                    if (!modal) return false;
                    const style = window.getComputedStyle(modal);
                    return style.display !== 'none' && style.visibility !== 'hidden';
                }""")
                if not still_visible:
                    print("   ✅ Modal del asistente cerrado")
                    return
            print("   ⚠️  El modal del asistente tardó demasiado en cerrarse")
        else:
            print("   ⚠️  No se pudo hacer click en Aceptar del asistente")

    # ── Extracción de secciones ───────────────────────────────────

    async def _extract_article_sections(self) -> list[dict]:
        """
        Extrae los headings del HTML del artículo (#articuloIn).
        Debe llamarse DESPUÉS de que #articuloIn haya cargado el contenido.
        """
        sections = await self.page.evaluate(r"""() => {
            const container = document.getElementById('articuloIn');
            if (!container) return [];

            const results = [];
            const seen = new Set();

            // Solo h1 se trata como seccion real a marcar (Resumen, Introduccion,
            // Materiales y Metodos, etc). Los h2/h3 de subseccion se dejan como
            // texto normal dentro de su seccion -- AmeliCA no promueve h2/h3 de
            // forma confiable a "Subseccion" propia (verificado con casos reales
            // donde el mismo patron de HTML dio resultados distintos), asi que
            // automatizar solo con h1 es lo unico predecible.
            const headingElements = [];
            container.querySelectorAll('h1').forEach(el => headingElements.push(el));
            // Also include <p> elements styled as headings
            container.querySelectorAll('p').forEach(p => {
                const cls = (p.className || '').toLowerCase();
                const style = p.getAttribute('style') || '';
                if (cls.includes('heading') || cls.includes('msotitle') || style.includes('mso-outline-level')) {
                    headingElements.push(p);
                }
            });
            // Sort by document order
            headingElements.sort((a, b) =>
                a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1
            );

            function getAllText(node) {
                let t = '';
                const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
                let tn;
                while ((tn = w.nextNode())) t += tn.textContent;
                return t.trim();
            }

            // Known section keywords — headings containing these are never article titles
            const knownSections = [
                'introduccion', 'introducción', 'abstract', 'resumen',
                'metodolog', 'método', 'metodo', 'material', 'resultado',
                'discusion', 'discusión', 'conclusion', 'conclusión',
                'palabras clave', 'keywords', 'reconocimiento', 'referencia',
                'bibliograf', 'agradecimiento', 'declaraci', 'financiami',
                'conflicto', 'apéndice', 'apendice', 'anexo'
            ];

            // Track whether we've seen the first known section to stop skipping titles
            let firstKnownSectionSeen = false;

            let index = 0;
            for (const node of headingElements) {
                const text = getAllText(node);
                if (!text || text.length < 2) continue;
                if (seen.has(text)) continue;

                const lower = text.toLowerCase();

                // Determine if this heading is a known section
                const isKnownSection = knownSections.some(s => lower.startsWith(s));
                if (isKnownSection) firstKnownSectionSeen = true;

                // Skip headings that are article titles (not sections):
                // A title heading is an <h1> or a <p> with a title class that appears
                // BEFORE the first known section and is not itself a known section.
                if (!firstKnownSectionSeen && !isKnownSection) {
                    const tag = node.tagName.toLowerCase();
                    const cls = (node.className || '').toLowerCase();
                    const isTitleElement = tag === 'h1' ||
                        cls.includes('msotitle') || cls.includes('article-title') ||
                        (tag === 'p' && (cls.includes('titulo') || cls.includes('title')));
                    if (isTitleElement) continue;  // Saltear título del artículo
                }

                if (lower.startsWith('abstract') ||
                    lower.startsWith('resumen') ||
                    lower.startsWith('palabras clave') ||
                    lower.startsWith('keywords') ||
                    lower.startsWith('reconocimiento') ||
                    lower.startsWith('referencia') ||
                    lower.startsWith('bibliograf') ||
                    lower.startsWith('agradecimiento') ||
                    lower.startsWith('declaraci') ||
                    lower.startsWith('financiami') ||
                    lower.startsWith('conflicto') ||
                    lower.startsWith('apéndice') ||
                    lower.startsWith('apendice') ||
                    lower.startsWith('anexo') ||
                    /^figura\s+\d/.test(lower) ||
                    /^tabla\s+\d/.test(lower)) {
                    continue;
                }

                seen.add(text);

                // Ahora headingElements solo contiene <h1>, asi que el nivel
                // siempre es 1 -- ya no hace falta inspeccionar el tag ni
                // el estilo para decidir si es h2/h3.
                let level = 1;

                node.setAttribute('data-amelica-idx', String(index));

                results.push({ text, level, idx: index });
                index++;
            }

            return results;
        }""")

        return sections

    # ── Click en heading del artículo ────────────────────────────

    async def _click_heading_in_article(self, section: dict, is_first: bool = False) -> bool:
        """
        Simula la selección de texto del heading con Selection API.
        AmeliCA escucha mouseup/selectionchange y captura window.getSelection()
        para copiarlo al textarea activo.

        is_first: True si es la primera sección (verificar primer textarea),
                  False para secciones adicionales (verificar último textarea).
        """
        idx = section.get('idx', -1)

        selected = await self.page.evaluate("""(idx) => {
            const el = document.querySelector(`[data-amelica-idx="${idx}"]`);
            if (!el) return false;

            // Scroll al elemento
            el.scrollIntoView({behavior: 'smooth', block: 'center'});

            // Usar innerText completo del elemento para asegurar texto completo
            const fullText = (el.innerText || el.textContent || '').trim();

            // Seleccionar todo el contenido del elemento con Selection API
            const range = document.createRange();
            range.selectNodeContents(el);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);

            // Disparar mousedown en el elemento
            el.dispatchEvent(new MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true,
                view: window
            }));

            // Disparar mouseup para que AmeliCA capture la selección
            el.dispatchEvent(new MouseEvent('mouseup', {
                bubbles: true,
                cancelable: true,
                view: window
            }));

            // También disparar selectionchange por si AmeliCA lo escucha en document
            document.dispatchEvent(new Event('selectionchange'));

            return fullText.substring(0, 60);
        }""", idx)

        if selected:
            await asyncio.sleep(1.5)
            print(f"      ✅ Texto seleccionado: '{selected[:50]}'")
        else:
            # Fallback: buscar SOLO en h1-h6 por texto y seleccionar
            print(f"      ℹ️  Buscando por texto: '{section['text'][:40]}'")
            selected = await self.page.evaluate("""(text) => {
                const container = document.getElementById('articuloIn');
                if (!container) return false;

                // Buscar solo en h1-h6 para evitar coincidir con spans hijos parciales
                const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                for (const heading of headings) {
                    const w = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
                    let fullText = '';
                    let tn;
                    while ((tn = w.nextNode())) fullText += tn.textContent;
                    fullText = fullText.trim();

                    if (fullText && fullText.toLowerCase().startsWith(text.toLowerCase().substring(0, 10))) {
                        const range = document.createRange();
                        range.selectNodeContents(heading);
                        const sel = window.getSelection();
                        sel.removeAllRanges();
                        sel.addRange(range);
                        heading.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
                        heading.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
                        document.dispatchEvent(new Event('selectionchange'));
                        return fullText.substring(0, 60);
                    }
                }
                return false;
            }""", section['text'])
            await asyncio.sleep(1.5)

        # Verificar que el textarea correcto se llenó con texto de longitud suficiente
        # (>2 chars para evitar que valores como "C" pasen la verificación)
        # Para la primera sección verificar el PRIMER textarea;
        # para secciones adicionales verificar el ÚLTIMO textarea.
        if is_first:
            filled = await self.page.evaluate("""() => {
                const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
                if (!textareas.length) return null;
                const val = textareas[0].value && textareas[0].value.trim();
                return val && val.length > 2 ? val : null;
            }""")
        else:
            filled = await self.page.evaluate("""() => {
                const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
                if (!textareas.length) return null;
                const last = textareas[textareas.length - 1];
                const val = last.value && last.value.trim();
                return val && val.length > 2 ? val : null;
            }""")

        if filled:
            print(f"      ✅ Textarea relleno: '{filled[:40]}'")
            return True
        else:
            print(f"      ⚠️  Textarea no se llenó — inyectando manualmente")
            return await self._inject_text_to_last_active_textarea(section['text'], is_first=is_first)

    async def _inject_text_to_last_active_textarea(self, text: str, is_first: bool = False) -> bool:
        """Inyecta texto directamente en el textarea correcto como fallback.

        is_first: True para inyectar en el PRIMER textarea (primera sección),
                  False para inyectar en el ÚLTIMO textarea (secciones adicionales).

        Busca el texto del heading directamente en h1-h6 del DOM para obtener el
        texto completo concatenado (evita inyectar texto parcial como "C").
        """
        if is_first:
            injected = await self.page.evaluate("""(text) => {
                const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
                if (!textareas.length) return false;
                const target = textareas[0];
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(target, text);
                target.dispatchEvent(new Event('input', {bubbles: true}));
                target.dispatchEvent(new Event('change', {bubbles: true}));
                return target.value;
            }""", text)
        else:
            # Buscar el heading completo en h1-h6 para obtener fullText del DOM
            injected = await self.page.evaluate("""(text) => {
                const container = document.getElementById('articuloIn');
                const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
                if (!textareas.length) return false;
                const target = textareas[textareas.length - 1];
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;

                // Intentar encontrar el fullText del heading en el DOM (h1-h6 únicamente)
                let injectText = text;
                if (container) {
                    const headings = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                    for (const heading of headings) {
                        const w = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
                        let fullText = '';
                        let tn;
                        while ((tn = w.nextNode())) fullText += tn.textContent;
                        fullText = fullText.trim();
                        if (fullText && fullText.toLowerCase().startsWith(text.toLowerCase().substring(0, 8))) {
                            injectText = fullText;
                            break;
                        }
                    }
                }

                setter.call(target, injectText);
                target.dispatchEvent(new Event('input', {bubbles: true}));
                target.dispatchEvent(new Event('change', {bubbles: true}));
                return target.value;
            }""", text)
        return bool(injected)

    # ── Agregar sección nueva ────────────────────────────────────

    async def _add_and_fill_section(self, section: dict) -> bool:
        """Click en 'Agregar Sección' via JS directo (evita intercepción de imágenes)."""
        await self._ensure_sections_panel_visible()

        clicked = await self.page.evaluate("""() => {
            // Buscar botón Agregar Sección - directo en #arbol o dentro de #intArbol
            const candidates = document.querySelectorAll('#arbol > button, #intArbol > button');
            for (const btn of candidates) {
                const txt = (btn.innerText || btn.textContent || '').trim();
                if (txt.includes('Agregar') && (txt.includes('Secci') || txt.includes('seccion'))) {
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                    return 'clicked: ' + txt;
                }
            }
            // Fallback más amplio
            for (const btn of document.querySelectorAll('#intArbol button')) {
                const txt = (btn.innerText || btn.textContent || '').trim();
                if (txt === 'Agregar Sección' || txt === 'Agregar Seccion') {
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                    return 'clicked-fallback: ' + txt;
                }
            }
            return null;
        }""")

        if not clicked:
            print("      ⚠️  No se encontró 'Agregar Sección'")
            return False

        print(f"      ✅ {clicked}")
        await asyncio.sleep(0.5)

        return await self._activate_textarea_and_click_heading(section)

    async def _add_and_fill_subsection(self, section: dict) -> bool:
        """Click en 'Agregar Subsección' via JS directo."""
        await self._ensure_sections_panel_visible()

        clicked = await self.page.evaluate("""() => {
            const buttons = document.querySelectorAll('#intArbol button');
            let subsecBtn = null;
            for (const btn of buttons) {
                const txt = (btn.innerText || btn.textContent || '').trim();
                if (txt.includes('Agregar') && txt.includes('Sub')) {
                    subsecBtn = btn;  // tomar el último
                }
            }
            if (subsecBtn) {
                subsecBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                return 'clicked: ' + (subsecBtn.innerText || '').trim();
            }
            return null;
        }""")

        if not clicked:
            print("      ℹ️  Sin botón subsección — agregando como sección")
            return await self._add_and_fill_section(section)

        print(f"      ✅ {clicked}")
        await asyncio.sleep(0.5)

        return await self._activate_textarea_and_click_heading(section)

    async def _activate_textarea_and_click_heading(self, section: dict) -> bool:
        """
        Activa el último textarea vacío via JS click, espera que cargue el artículo,
        y luego selecciona el texto del heading.
        """
        # Usar JS para hacer click en el último textarea vacío (evita intercepción)
        activated = await self.page.evaluate("""() => {
            const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
            if (!textareas.length) return false;
            const last = textareas[textareas.length - 1];
            last.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            last.focus();
            return true;
        }""")

        if not activated:
            return False

        print(f"      🖱️  Textarea activado — esperando artículo...")
        await asyncio.sleep(2.5)

        # Verificar que #articuloIn cargó
        has_content = await self.page.evaluate("""() => {
            const el = document.getElementById('articuloIn');
            return el && el.innerText && el.innerText.trim().length > 50;
        }""")
        if not has_content:
            await asyncio.sleep(2)

        return await self._click_heading_in_article(section)

    # ── Helpers ──────────────────────────────────────────────────

    async def _ensure_sections_panel_visible(self):
        """Verifica que estamos viendo el panel de secciones (no el del artículo)."""
        await asyncio.sleep(0.3)

    async def _find_button_by_text(self, selector: str, text: str):
        """Busca un botón por texto dentro de un selector."""
        buttons = await self.page.query_selector_all(selector)
        for b in buttons:
            txt = (await b.inner_text()).strip()
            if text in txt:
                return b
        # Fallback más amplio
        all_buttons = await self.page.query_selector_all('#intArbol button')
        for b in all_buttons:
            txt = (await b.inner_text()).strip()
            if text in txt or text.replace('ó', 'o') in txt:
                return b
        return None

    # ── Fin de artículo ───────────────────────────────────────────

    async def _fill_end_of_article(self):
        print("\n   📍 Rellenando fin de artículo...")
        await self._ensure_sections_panel_visible()

        # Click en fin textarea via JS (evita intercepción)
        activated = await self.page.evaluate("""() => {
            const el = document.querySelector('.txtareafinArticulo');
            if (!el) return false;
            el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
            el.focus();
            return true;
        }""")

        if not activated:
            print("   ⚠️  No se encontró el textarea de fin de artículo")
            return

        print("   ⏳ Esperando que cargue el artículo para fin...")
        await asyncio.sleep(2.5)

        # Calcular las últimas 5 palabras del último párrafo de Conclusiones
        # SIN usar Selection API (que haría que AmeliCA capture el párrafo completo)
        last_words = await self.page.evaluate(r"""() => {
            const container = document.getElementById('articuloIn');
            if (!container) return '';

            const closingSections = [
                'reconocimiento', 'referencia', 'bibliograf', 'agradecimiento',
                'declaraci', 'financiami', 'conflicto', 'apéndice', 'apendice', 'anexo'
            ];

            function getHeadingText(el) {
                const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                let t = '', tn;
                while ((tn = w.nextNode())) t += tn.textContent;
                return t.trim().toLowerCase();
            }

            let conclusionesEl = null;
            let closingEl = null;

            const headings = container.querySelectorAll('h1,h2,h3,h4,h5,h6');
            for (const h of headings) {
                const txt = getHeadingText(h);
                if (txt.startsWith('conclusi')) {
                    conclusionesEl = h;
                } else if (conclusionesEl && closingSections.some(s => txt.startsWith(s))) {
                    closingEl = h;
                    break;
                }
            }

            // Si no encontramos Conclusiones, usar el último párrafo significativo del doc
            if (!conclusionesEl) {
                const allP = Array.from(container.querySelectorAll('p'));
                for (let i = allP.length - 1; i >= 0; i--) {
                    const text = (allP[i].innerText || allP[i].textContent || '').replace(/\s+/g, ' ').trim();
                    if (text.length > 20) {
                        return text.split(' ').filter(w => w.length > 0).slice(-5).join(' ');
                    }
                }
                return '';
            }

            // Filtrar todos los <p> que estén después del heading de Conclusiones
            // y antes del heading de cierre (usando compareDocumentPosition)
            const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING;
            const PRECEDING = Node.DOCUMENT_POSITION_PRECEDING;
            const allParagraphs = Array.from(container.querySelectorAll('p'));
            const candidates = allParagraphs.filter(p => {
                const afterConclusion = !!(conclusionesEl.compareDocumentPosition(p) & FOLLOWING);
                const beforeClosing = closingEl ? !!(closingEl.compareDocumentPosition(p) & PRECEDING) : true;
                return afterConclusion && beforeClosing;
            });

            // Encontrar el último párrafo significativo entre esos candidatos
            for (let i = candidates.length - 1; i >= 0; i--) {
                const text = (candidates[i].innerText || candidates[i].textContent || '').replace(/\s+/g, ' ').trim();
                if (text.length > 20) {
                    return text.split(' ').filter(w => w.length > 0).slice(-5).join(' ');
                }
            }

            return '';
        }""")

        if last_words:
            # Inyectar DIRECTAMENTE con native value setter — NO usar Selection API
            # porque AmeliCA escucha mouseup/selectionchange y capturaría el párrafo completo
            await self.page.evaluate("""(text) => {
                const el = document.querySelector('.txtareafinArticulo');
                if (el) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(el, text);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }""", last_words)
            print(f"   ✅ Fin de artículo: '{last_words}'")
        else:
            print("   ⚠️  No se encontró párrafo final en sección de Conclusiones")

    # ── Verificación ─────────────────────────────────────────────

    async def _handle_verification(self) -> bool:
        """Hace click en 'Verificar', detecta textareas amarillos y los re-marca.
        Luego hace click en 'Continuar'."""
        print("\n   🔍 Verificando marcaje...")

        # Click en "Verificar"
        clicked = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                const txt = (btn.innerText || btn.textContent || '').trim();
                if (txt === 'Verificar') {
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                    return true;
                }
            }
            return false;
        }""")

        if not clicked:
            print("   ℹ️  No se encontró botón 'Verificar' — continuando")
            return True

        await asyncio.sleep(1.5)

        # Detectar textareas amarillos (con warning)
        yellow_textareas = await self.page.evaluate("""() => {
            const results = [];
            const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
            for (let i = 0; i < textareas.length; i++) {
                const ta = textareas[i];
                const style = window.getComputedStyle(ta);
                const bg = style.backgroundColor;
                // Amarillo: rgb(255, 255, 0) o similar
                if (bg.includes('255, 255, 0') || bg.includes('255,255,0') ||
                    ta.style.backgroundColor === 'yellow' ||
                    ta.classList.contains('warning') || ta.classList.contains('amarillo')) {
                    results.push({ index: i, value: ta.value });
                }
            }
            return results;
        }""")

        if not yellow_textareas:
            print("   ✅ Verificación OK — sin textareas amarillos")
        else:
            print(f"   ⚠️  {len(yellow_textareas)} textarea(s) amarillo(s) — re-marcando...")
            for item in yellow_textareas:
                idx = item['index']
                val = item['value']
                print(f"      🔄 Re-marcando textarea {idx}: '{val[:40]}'")

                # Click en el textarea amarillo via JS
                await self.page.evaluate(f"""() => {{
                    const textareas = document.querySelectorAll('#intArbol .txtarea:not(.txtareafinArticulo)');
                    const ta = textareas[{idx}];
                    if (ta) {{
                        ta.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true, view: window}}));
                        ta.focus();
                    }}
                }}""")
                await asyncio.sleep(2.5)

                # Buscar el heading en #articuloIn por texto y re-seleccionarlo
                re_selected = await self.page.evaluate("""(text) => {
                    const container = document.getElementById('articuloIn');
                    if (!container) return false;

                    function getAllText(node) {
                        let t = '';
                        const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
                        let tn;
                        while ((tn = w.nextNode())) t += tn.textContent;
                        return t.trim();
                    }

                    const walker = document.createTreeWalker(container, NodeFilter.SHOW_ELEMENT);
                    let node;
                    while ((node = walker.nextNode())) {
                        const tag = node.tagName.toLowerCase();
                        const isHeading = ['h1','h2','h3','h4','h5','h6'].includes(tag) ||
                            (tag === 'p' && (node.className || '').toLowerCase().includes('heading'));
                        if (!isHeading) continue;

                        const nodeText = getAllText(node);
                        if (nodeText.toLowerCase().startsWith(text.toLowerCase().substring(0, 10))) {
                            const range = document.createRange();
                            range.selectNodeContents(node);
                            const sel = window.getSelection();
                            sel.removeAllRanges();
                            sel.addRange(range);
                            node.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
                            node.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
                            document.dispatchEvent(new Event('selectionchange'));
                            return nodeText;
                        }
                    }
                    return false;
                }""", val)

                await asyncio.sleep(1.5)
                if re_selected:
                    print(f"      ✅ Re-marcado: '{re_selected[:40]}'")
                else:
                    print(f"      ⚠️  No se pudo re-marcar: '{val[:40]}'")

        # Click en "Continuar"
        await asyncio.sleep(0.5)
        continued = await self.page.evaluate("""() => {
            for (const btn of document.querySelectorAll('button')) {
                const txt = (btn.innerText || btn.textContent || '').trim();
                if (txt === 'Continuar') {
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                    return true;
                }
            }
            return false;
        }""")

        if continued:
            print("   ✅ Click en 'Continuar'")
            await asyncio.sleep(2)
        else:
            print("   ℹ️  No se encontró 'Continuar' — puede que no sea necesario")

        return True

    # ── Inferir ──────────────────────────────────────────────────

    #: Botón "Guardar" del editor. Confirmado inspeccionando el DOM real:
    #: es un <a> cuyo onclick llama a salvarContenido(). Los vecinos son
    #: buttonRepo (Respaldos) y buttonC (Finalizar) — no confundir.
    SAVE_BUTTON_ID = 'save-526564616c7963:buttonS'
    #: Spinner que JSF muestra mientras procesa el guardado.
    WAIT_SPINNER_ID = 'wait-526564616c7963'

    async def _click_guardar(self) -> bool:
        """Click en 'Guardar' — es lo que persiste el marcaje.

        Antes se buscaba 'Inferir', que no existe en esta pantalla: por eso
        el marcaje se perdía. Devuelve True solo si encontró y clickeó el
        botón; quien llama necesita saberlo.
        """
        print("\n   💾 Guardando el marcaje...")

        clicked = await self.page.evaluate(r"""(saveId) => {
            const el = document.getElementById(saveId);
            if (el) { el.click(); return 'by-id'; }
            for (const a of document.querySelectorAll('a, button')) {
                const t = (a.innerText || a.textContent || '').trim();
                if (t === 'Guardar' && a.offsetParent !== null) {
                    a.click(); return 'by-text';
                }
            }
            return null;
        }""", self.SAVE_BUTTON_ID)

        if not clicked:
            print("   ⚠️  No se encontró el botón 'Guardar'")
            return False
        print(f"   ✅ Click en 'Guardar' ({clicked})")

        # Esperar a que el spinner de JSF aparezca y vuelva a ocultarse: si
        # cerramos antes, el guardado queda a medias y se pierde el trabajo.
        await asyncio.sleep(1.5)
        try:
            await self.page.wait_for_function(
                """(id) => {
                    const w = document.getElementById(id);
                    return !w || w.offsetParent === null;
                }""", arg=self.WAIT_SPINNER_ID, timeout=90_000)
        except Exception:
            print("   ⚠️  El indicador de guardado no terminó en 90s")
            return False

        try:
            await self.page.wait_for_load_state('networkidle', timeout=30_000)
        except Exception:
            pass
        await asyncio.sleep(2)
        return True

    async def _verificar_persistencia(self) -> bool | None:
        """Recarga el editor y comprueba que las secciones sigan ahí.

        Devuelve True/False si pudo comprobarlo, o None si no pudo (por
        ejemplo si la recarga no vuelve al editor). None NO es éxito: se
        informa como "no verificado" en vez de dar el guardado por bueno.
        """
        try:
            await self.page.reload(wait_until='networkidle', timeout=60_000)
            await asyncio.sleep(3)

            # Aceptar el asistente si reaparece tras la recarga
            await self.page.evaluate(r"""() => {
                for (const a of document.querySelectorAll('a, button')) {
                    const t = (a.innerText || a.textContent || '').trim().toLowerCase();
                    if (t === 'aceptar' && a.offsetParent !== null) { a.click(); return; }
                }
            }""")
            await asyncio.sleep(3)

            if 'marker' not in (self.page.url or '').lower():
                return None

            secciones = await self.page.evaluate(r"""() => {
                const t = [...document.querySelectorAll('#intArbol .txtarea')];
                if (!t.length) return null;
                return t.map(x => (x.value || '').trim()).filter(Boolean);
            }""")
            if secciones is None:
                return None
            return len(secciones) > 0
        except Exception as e:
            print(f"   ℹ️  No se pudo verificar la persistencia: {e}")
            return None

    async def _click_inferir(self) -> bool:
        """Click en el botón 'Inferir' (pantalla de inferencia, no la de
        marcaje). Se conserva por si hace falta, pero NO es lo que guarda:
        para eso está _click_guardar().
        """
        print("\n   🚀 Haciendo click en 'Inferir'...")

        await self._ensure_sections_panel_visible()

        clicked = await self.page.evaluate("""() => {
            // Buscar el botón Inferir por id
            const btn = document.getElementById('inferirWarning');
            if (btn) { btn.click(); return 'by-id'; }

            // Fallback: buscar por texto
            for (const b of document.querySelectorAll('button')) {
                if ((b.innerText || b.textContent || '').trim() === 'Inferir') {
                    b.click();
                    return 'by-text';
                }
            }
            return null;
        }""")

        if clicked:
            print(f"   ✅ Click en 'Inferir' ({clicked})")
            await asyncio.sleep(3)
            return True

        print("   ⚠️  No se encontró el botón 'Inferir'")
        return False
