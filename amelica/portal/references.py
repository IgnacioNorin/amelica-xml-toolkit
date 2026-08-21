"""
references.py — Llenado de la pestania "Referencias" en el portal.

ESTADO: NO conectado al flujo automatico. Se ejecuta solo con --referencias.

Motivo: `_delete_refs_but_one` borra referencias preexistentes antes de
escribir -- la operacion mas destructiva del proyecto -- y la escritura
en el portal solo se verifico parcialmente. El 2026-08-20 se grabo una
referencia JOURNAL completa a mano en el portal real (click-a-click, con
un script en la consola del navegador) para confirmar los selectores: la
mayoria coincidia con lo que este archivo ya asumia (Referencia completa,
Referencia detallada - JOURNAL, Nombre(s)/Apellido(s), Fuente, Volumen,
Numero, Pagina inicial/final, Paginacion electronica, Titulo del articulo,
el select publication-type-). Se encontro y arreglo un mismatch real:
Año NO es un span editable como asumia _fill_ref_year -- es un
select[class*="iso-8601-date-"], igual mecanismo que publication-type-.

El boton Guardar (`#save-526564616c7963:buttonS`, onclick="salvarContenido();")
tambien esta confirmado: es el mismo boton compartido del editor de
marker.oa que ya usan con exito el guardado del marcaje y el de "Datos
del articulo" (verificado inspeccionando el HTML real de ese form).

Autores institucionales tambien confirmados (2026-08-21, grabacion en
vivo): la caja "Autor" (personal) pre-creada por defecto NO se puede
borrar, asi que si el (unico) autor es institucional esa caja se deja
vacia sin tocar y el institucional se agrega aparte con el boton "Autor
institucional" + campo title="Institución". _add_ref_authors ya lo hace
asi, enrutando segun el mismo criterio que usa el parser para marcar un
autor institucional (given='').

Sigue sin probarse en vivo: el llenado completo de una referencia real y
el guardado de punta a punta con --referencias sobre un articulo de
prueba (los selectores individuales ya estan verificados, pero no se
corrio el flujo completo end-to-end). El parser que alimenta esto
(parsing/references.py) si esta validado. Para seguir verificando: correr
con --referencias sobre un numero de prueba, o repetir la grabacion con
tools/grabador_referencias.js (pegar en la consola del navegador mientras
se completa una referencia a mano en el portal).
"""

import asyncio


class ReferencesMixin:
    """Llenado de la pestania Referencias. Se mezcla en AmelicaUploader."""

    # ── Referencias ──────────────────────────────────────────────

    async def _close_ref_modals(self):
        """Cierra los 3 modales que aparecen al entrar a la pestaña Referencias."""
        await asyncio.sleep(2)
        # Modal 1: alerta general (#alerta a.aceptar)
        closed1 = await self.page.evaluate("""() => {
            const btn = document.querySelector('#alerta a.aceptar, #alerta button.aceptar');
            if (btn && btn.offsetParent) { btn.click(); return true; }
            return false;
        }""")
        if closed1:
            print("   ✅ Modal alerta cerrado")
            await asyncio.sleep(1)

        # Modal 2: asistente de inferencia → Cancelar
        closed2 = await self.page.evaluate("""() => {
            const modals = document.querySelectorAll('.ui-dialog, [id*="infer"], [id*="welcome"]');
            for (const m of modals) {
                if (!m.offsetParent) continue;
                for (const btn of m.querySelectorAll('button, a')) {
                    const t = (btn.innerText || btn.textContent || '').trim();
                    if (t === 'Cancelar' || t === 'Cancel') { btn.click(); return true; }
                }
            }
            return false;
        }""")
        if closed2:
            print("   ✅ Modal asistente cerrado")
            await asyncio.sleep(1)

        # Modal 3: jQuery UI dialog warning
        closed3 = await self.page.evaluate("""() => {
            const sets = document.querySelectorAll('.ui-dialog-buttonset');
            for (const set of sets) {
                const parent = set.closest('.ui-dialog');
                if (!parent || !parent.offsetParent) continue;
                const btn = set.querySelector('button');
                if (btn) { btn.click(); return true; }
            }
            return false;
        }""")
        if closed3:
            print("   ✅ Modal warning cerrado")
            await asyncio.sleep(1)

    async def _delete_refs_but_one(self) -> int:
        """Borra todas las referencias menos la primera. Retorna cantidad borrada."""
        deleted = await self.page.evaluate("""async () => {
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            const refs = [...document.querySelectorAll('[title="Referencia"]')]
                .filter(el => el.offsetParent !== null);
            let count = 0;
            for (let i = refs.length - 1; i >= 1; i--) {
                refs[i].dispatchEvent(new MouseEvent('mouseover',  {bubbles:true}));
                refs[i].dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
                await sleep(150);
                const btn = refs[i].querySelector('[title="Cerrar"]');
                if (btn) { btn.click(); count++; await sleep(250); }
            }
            return count;
        }""")
        if deleted:
            print(f"   🗑️  Borradas {deleted} referencias pre-existentes")
            await asyncio.sleep(0.5)
        return deleted

    async def _set_ref_pub_type(self, pub_type: str) -> bool:
        """Selecciona el tipo de publicación en la Referencia detallada activa."""
        result = await self.page.evaluate("""(pub_type) => {
            const sel = [...document.querySelectorAll('select[class*="publication-type-"]')]
                .filter(el => el.offsetParent !== null).at(-1);
            if (!sel) return false;
            sel.value = pub_type;
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            // Llamar a editInput si existe (guarda el valor en AmeliCA)
            if (typeof editInput526564616c7963 === 'function')
                editInput526564616c7963('publication-type-526564616c7963');
            return true;
        }""", pub_type)
        if result:
            await asyncio.sleep(0.8)  # esperar que cambien los botones disponibles
        return result

    async def _fill_ref_contenido(self, title_attr: str, text: str,
                                   nth: str = 'last') -> bool:
        """Escribe texto en el span.contenido- de la caja con el title dado.
        nth='last' usa la más reciente (útil cuando hay varias del mismo tipo).
        nth='first' usa la primera."""
        result = await self.page.evaluate("""([title, nth]) => {
            const all = [...document.querySelectorAll(`[title="${title}"]`)]
                .filter(el => el.offsetParent !== null);
            if (!all.length) return 'not-found';
            const caja = nth === 'first' ? all[0] : all[all.length - 1];

            // Activar la caja
            caja.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
            caja.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
            caja.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
            caja.focus();

            const span = caja.querySelector('[contenteditable="true"]');
            if (!span) return 'no-span';

            span.click();
            span.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete',    false, null);
            document.execCommand('insertText', false, text);
            return 'ok';
        }""", [title_attr, nth])

        if result != 'ok':
            print(f"      ⚠️  _fill_ref_contenido ({result}): '{title_attr}'")
            return False
        return True

    async def _fill_ref_year(self, year: str) -> bool:
        """Llena el campo Año de la referencia activa.

        Confirmado grabando una referencia a mano en el portal
        (2026-08-20): a diferencia de los demas campos de texto libre
        (Fuente, Volumen, etc.), Año NO es un span[contenteditable] --
        es un <select class="iso-8601-date-..."> con una opcion por año
        (igual mecanismo que el select de tipo de publicacion). La version
        anterior de este metodo asumia un span editable (con un fallback
        de inyectar uno a mano) y nunca tocaba ese select, asi que nunca
        funciono contra el portal real."""
        # Primero activar la caja "Año" para que el select se muestre/monte
        # (igual que los demas campos, algunos selects de PrimeFaces no
        # existen en el DOM hasta que se hace click en su contenedor).
        await self.page.evaluate("""() => {
            const cajas = [...document.querySelectorAll('[title="Año"]')]
                .filter(el => el.offsetParent !== null);
            const caja = cajas[cajas.length - 1];
            if (caja) {
                caja.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                caja.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                caja.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
            }
        }""")
        await asyncio.sleep(0.3)

        result = await self.page.evaluate("""(year) => {
            const sel = [...document.querySelectorAll('select[class*="iso-8601-date-"]')]
                .filter(el => el.offsetParent !== null).at(-1);
            if (!sel) return 'not-found';
            for (const opt of sel.options) {
                if (opt.text.trim() === String(year)) {
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'ok';
                }
            }
            return 'no-match';
        }""", year)

        if result == 'not-found':
            print(f"      ⚠️  Select de Año no encontrado")
            return False
        if result == 'no-match':
            print(f"      ⚠️  Año '{year}' no está entre las opciones del select")
            return False
        print(f"      ✅ Año: {year} ({result})")
        return True

    async def _add_ref_authors(self, authors: list) -> bool:
        """Llena los autores de la referencia activa.

        El parser (parsing/references.py) marca un autor institucional con
        given='' -- mismo criterio que _is_institutional_author.

        El primer autor "personal" (Nombre(s)/Apellido(s)) viene pre-creado
        vacío, pero esa caja NO SE PUEDE BORRAR (confirmado por el usuario
        grabando el flujo real en el portal, 2026-08-21). Si el (unico)
        autor es institucional, esa caja pre-creada se deja vacia sin
        tocar, y el autor institucional se agrega aparte con el boton
        "Autor institucional" + el campo title="Institución". Por eso el
        indice para decidir "hay que crear una caja nueva o ya existe una
        vacia" se lleva aparte (personal_added), no por posicion en la
        lista de autores."""
        if not authors:
            return True

        personal_added = False
        for author in authors:
            given   = author.get('given', '')
            surname = author.get('surname', '')
            institutional = not given and surname

            if institutional:
                await self._click_caja('Autores')
                clicked = await self._click_menu_button('Autor institucional')
                if not clicked:
                    print(f"      ⚠️  No se pudo crear autor institucional")
                    continue
                await asyncio.sleep(0.4)
                await self._fill_ref_contenido('Institución', surname, nth='last')
                continue

            if personal_added:
                # Ya se uso la caja "Autor" pre-creada -> crear una nueva
                await self._click_caja('Autores')
                clicked = await self._click_menu_button('Autor')
                if not clicked:
                    print(f"      ⚠️  No se pudo crear autor")
                    continue
                await asyncio.sleep(0.4)
            personal_added = True

            await self._fill_ref_contenido('Nombre(s)', given,   nth='last')
            await self._fill_ref_contenido('Apellido(s)', surname, nth='last')

        return True

    async def _fill_single_reference(self, ref: dict) -> bool:
        """Llena todos los campos de una referencia individual."""
        pub_type = ref.get('pub_type', 'journal')
        year     = ref.get('year', '')
        authors  = ref.get('authors', [])

        # 1. Seleccionar tipo de publicación
        ok = await self._set_ref_pub_type(pub_type)
        if not ok:
            print(f"      ⚠️  No se pudo setear pub_type={pub_type}")

        # 2. Referencia completa (texto plano)
        full_text = ref.get('full_text', '')
        if full_text:
            await self._fill_ref_contenido('Referencia completa', full_text)
            await asyncio.sleep(0.2)

        # 3. Activar Referencia detallada para revelar botones
        det_title = f'Referencia detallada - {pub_type.upper()}'
        await self._click_caja(det_title)
        await asyncio.sleep(0.3)

        # 4. Autores
        await self._add_ref_authors(authors)
        await asyncio.sleep(0.2)

        # 5. Año
        if year:
            await self._fill_ref_year(year)

        # 6. Fuente (journal, confproc)
        source = ref.get('source', '')
        if source and pub_type in ('journal', 'confproc', 'book'):
            await self._fill_ref_contenido('Fuente', source)

        # 7. Campos adicionales según tipo
        if pub_type in ('journal', 'confproc'):
            # Título del artículo
            article_title = ref.get('article_title', '')
            if article_title:
                await self._click_caja(det_title)
                if await self._click_menu_button('Título del artículo'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Título del artículo', article_title)

            # Volumen
            volume = ref.get('volume', '')
            if volume:
                await self._click_caja(det_title)
                if await self._click_menu_button('Volumen'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Volumen', volume)

            # Número
            issue = ref.get('issue', '')
            if issue:
                await self._click_caja(det_title)
                if await self._click_menu_button('Número'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Número', issue)

            # Página inicial / final
            fpage = ref.get('fpage', '')
            lpage = ref.get('lpage', '')
            if fpage:
                await self._click_caja(det_title)
                if await self._click_menu_button('Página inicial'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Página inicial', fpage)
            if lpage:
                await self._click_caja(det_title)
                if await self._click_menu_button('Página final'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Página final', lpage)

            # Paginación electrónica (elocation)
            elocation = ref.get('elocation', '')
            if elocation:
                await self._click_caja(det_title)
                if await self._click_menu_button('Paginación electrónica'):
                    await asyncio.sleep(0.3)
                    await self._fill_ref_contenido('Paginación electrónica', elocation)

        # URL (todos los tipos)
        url = ref.get('url', '')
        if url:
            await self._click_caja(det_title)
            if await self._click_menu_button('URL'):
                await asyncio.sleep(0.3)
                await self._fill_ref_contenido('URL', url)

        return True

    async def fill_references(self, refs: list) -> bool:
        """Completa la pestaña 'Referencias' con los datos parseados del HTML.

        refs: lista devuelta por parse_references_from_html().
        """
        if not refs:
            print("   ℹ️  Sin referencias para completar")
            return True

        print("\n" + "─"*55)
        print(f"📚 Completando Referencias ({len(refs)} refs)...")
        print("⚠️  EXPERIMENTAL — este paso borra las referencias que el")
        print("   artículo ya tenga cargadas en el portal antes de escribir.")
        print("─"*55)

        # 1. Ir a pestaña Referencias
        await self._click_tab('referencias')
        await asyncio.sleep(2)

        # 2. Cerrar modales
        await self._close_ref_modals()

        # 3. Borrar todas las referencias pre-existentes menos 1
        await self._delete_refs_but_one()
        await asyncio.sleep(0.5)

        # 4. Llenar cada referencia
        for i, ref in enumerate(refs):
            surname = ref['authors'][0]['surname'] if ref['authors'] else '(inst.)'
            print(f"\n   📖 [{i+1}/{len(refs)}] {surname} ({ref['year']}) [{ref['pub_type']}]")

            if i > 0:
                # Crear nueva referencia con botón
                await self._click_caja('Referencias')
                if not await self._click_menu_button('Referencia'):
                    print(f"      ⚠️  No se pudo crear la referencia {i+1}")
                    continue
                await asyncio.sleep(0.5)

            await self._fill_single_reference(ref)
            await asyncio.sleep(0.3)

        # 5. Guardar
        print("\n   💾 Guardando referencias...")
        saved = await self.page.evaluate("""() => {
            // Buscar botón Guardar visible
            // Nota: nada de selectores tipo :contains() -- eso es jQuery y
            // querySelector tira SyntaxError. La busqueda por texto va abajo.
            for (const sel of [
                '#save-526564616c7963\\\\:buttonS',
                'input[value="Guardar"]',
            ]) {
                try {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent) { el.click(); return true; }
                } catch(e) {}
            }
            // Fallback: buscar por texto
            for (const btn of document.querySelectorAll('input[type="button"], button')) {
                if ((btn.value || btn.innerText || '').trim() === 'Guardar' && btn.offsetParent) {
                    btn.click(); return true;
                }
            }
            return false;
        }""")

        if saved:
            print("   ✅ Referencias guardadas")
        else:
            print("   ⚠️  No se encontró botón Guardar — guardá manualmente")

        return True
