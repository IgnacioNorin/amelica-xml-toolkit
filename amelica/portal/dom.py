"""
dom.py — Helpers de bajo nivel para manipular el editor de AmeliCA.

El editor no expone controles normales: son "cajas" contenteditable que se
activan disparando eventos de mouse desde JS. Todo lo que sabe interactuar
con esos widgets vive aca, separado de la logica de que dato va en cada campo.

Los nombres de clase llevan el sufijo fijo "526564616c7963" (== "Redalyc" en
hex, NO es un token de sesion). Cuando se puede se matchea por texto visible,
que resiste mejor los cambios de la plataforma.
"""

import asyncio


class DomHelpersMixin:
    """Helpers de interaccion con el DOM del editor. Se mezcla en AmelicaUploader."""

    async def _click_caja(self, title_attr: str, timeout_ms: int = 5000,
                           nth: str = 'last') -> bool:
        """Activa el contexto de edicion de una 'caja' (titulo, autor, fecha,
        etc.) disparando los eventos de mouse directamente desde JS.

        POR QUÉ JS Y NO Playwright .click():
        Confirmado en diagnóstico: el div tiene contenteditable="false" y su
        handler de AmeliCA agrega la clase focus-526564616c7963 solo cuando
        recibe mousedown/mouseup a través del handler nativo. El .click() de
        Playwright no dispara ese handler de la misma forma que el click real
        del usuario. Usando dispatchEvent desde JS se replica exactamente lo
        que hace el usuario, igual que en AmelicaMarker.

        nth='last' (default): la caja recién creada aparece al final.
        nth='first': usar para la primera caja de un tipo (ej. primera Fecha).

        Devuelve True si la caja fue encontrada y los eventos disparados, y
        además espera hasta 2s a que la clase focus- aparezca como señal de
        que el handler procesó el click correctamente."""
        try:
            locator = self.page.locator(f'[title="{title_attr}"]:visible')
            target = locator.last if nth == 'last' else locator.first
            # Hover real via CDP (no sintetico): algunos menus de AmeliCA
            # (ej. "direct-menu-..." con "Titulo en otro idioma") se revelan
            # con :hover de CSS puro, que un MouseEvent despachado desde JS
            # no dispara. dispatchEvent de mouseover/mouseenter mas abajo
            # queda como refuerzo por si en cambio es un listener de JS.
            await target.hover(timeout=timeout_ms)
        except Exception:
            pass

        result = await self.page.evaluate("""([title, nth]) => {
            const all = [...document.querySelectorAll(`[title="${title}"]`)]
                .filter(el => el.offsetParent !== null);
            if (!all.length) return 'not-found';
            const el = nth === 'first' ? all[0] : all[all.length - 1];
            // Algunos menus (ej. "direct-menu-..." con el boton "Titulo en
            // otro idioma") solo se revelan con mouseover/mouseenter -- un
            // click real de usuario siempre dispara esos eventos antes del
            // mousedown, asi que agregarlos replica mejor la interaccion
            // real y no deberia romper cajas que no los necesitan.
            el.dispatchEvent(new MouseEvent('mouseover',  {bubbles: true, cancelable: true, view: window}));
            el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true, cancelable: true, view: window}));
            el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
            el.dispatchEvent(new MouseEvent('mouseup',   {bubbles: true, cancelable: true, view: window}));
            el.dispatchEvent(new MouseEvent('click',     {bubbles: true, cancelable: true, view: window}));
            el.focus();
            return el.className;
        }""", [title_attr, nth])

        if result == 'not-found':
            print(f"   ⚠️  No se pudo activar la caja '{title_attr}' (no encontrada)")
            return False

        # Esperar a que la clase focus- aparezca (señal de que el handler procesó)
        for _ in range(8):
            await asyncio.sleep(0.25)
            has_focus = await self.page.evaluate("""(title) => {
                const el = [...document.querySelectorAll(`[title="${title}"]`)]
                    .find(e => e.offsetParent !== null);
                return el ? el.className.includes('focus-') : false;
            }""", title_attr)
            if has_focus:
                return True

        # Si después de 2s no tiene focus-, igual continuamos (puede que el
        # título= de esta caja no use ese patrón de clase)
        print(f"   ℹ️  Caja '{title_attr}': clase focus- no apareció — continuando igual")
        return True

    async def _click_menu_button(self, text: str, timeout_ms: int = 5000) -> bool:
        """Clickea un boton (input type=button) cuyo texto visible (value=)
        coincide, esperando a que este visible primero (los menus de AmeliCA
        aparecen/desaparecen via display:none segun el contexto activo)."""
        try:
            locator = self.page.locator(f'input[type="button"][value="{text}"]:visible').first
            await locator.wait_for(state='visible', timeout=timeout_ms)
            await locator.click()
            return True
        except Exception:
            print(f"   ⚠️  No se pudo clickear el boton '{text}' (¿no visible o no existe?)")
            return False

    async def _select_option_containing_class(self, class_substring: str, option_text: str, timeout_ms: int = 5000) -> bool:
        """Selecciona una opcion por texto visible, en el <select> visible
        cuya clase contiene class_substring (puede haber varios <select>
        con esa clase en el DOM si hay varios bloques repetidos -- se toma
        el primero visible, asumiendo que es el recien insertado)."""
        try:
            locator = self.page.locator(f'select[class*="{class_substring}"]:visible').first
            await locator.wait_for(state='visible', timeout=timeout_ms)
            await locator.select_option(label=option_text)
            return True
        except Exception:
            print(f"   ⚠️  No se pudo seleccionar '{option_text}' en select[class*={class_substring}]")
            return False

    async def _type_in_last_contenteditable(self, text: str) -> bool:
        """Tipea texto en el último contenteditable visible.

        USO EXCLUSIVO: ORCID. Es el ÚNICO campo que no viene pre-relleno por
        la inferencia de AmeliCA y requiere tipeo real. Para todos los demás
        campos usar _click_contenteditable_with_text() en su lugar."""
        try:
            elements = self.page.locator('[contenteditable="true"]:visible')
            count = await elements.count()
            if count == 0:
                print("   ⚠️  Sin contenteditable visible para tipear ORCID")
                return False
            target = elements.nth(count - 1)
            await target.click()
            await target.fill('')  # limpiar placeholder si lo hubiera
            await self.page.keyboard.type(text)
            return True
        except Exception as e:
            print(f"   ⚠️  No se pudo tipear ORCID '{text[:30]}': {e}")
            return False

    async def _click_tab(self, tab_text: str) -> bool:
        """Cambia de pestaña dentro del editor de marcaje (datos del
        articulo / referencias-apendices / texto completo / Datos abiertos).

        Las pestañas comparten la clase "tab-526564616c7963", pero el tag y
        la clase difieren segun esten activas o no (confirmado en vivo,
        2026-08-21):
        - Inactiva: <a class="tab-526564616c7963 ...">, ej. la de
          Referencias, <a id="back-526564616c7963" ...> con texto
          "<referencias/apéndices/>".
        - YA ACTIVA (la pestaña en la que ya estás parado): NO es un <a>,
          es un <div class="tab-526564616c7963 ... tabSeleccionado-...">,
          ej. "Datos del artículo" es la pestaña activa por defecto al
          abrir el editor -- <div id="front-526564616c7963"
          class="... tabSeleccionado-...">. Un primer intento que solo
          buscaba <a class*="tab-"> nunca la encontraba (no hace falta
          clickear algo en lo que ya estás) y abortaba el flujo entero.

        Se busca en cualquier elemento con esa clase (no solo <a>): si ya
        esta activa (tabSeleccionado) se devuelve True sin clickear nada;
        si no, se clickea. El match generico anterior a estos dos fixes
        (buscar tab_text en CUALQUIER elemento de la pagina, sin
        restringir a la clase de pestaña) agarraba elementos ajenos como
        el boton "Post-inferencia de referencias" del panel de guardado."""
        result = await self.page.evaluate("""(texto) => {
            const tabs = [...document.querySelectorAll('[class*="tab-"]')]
                .filter(el => el.offsetParent !== null);
            const needle = texto.toLowerCase();
            const tab = tabs.find(el => (el.innerText || '').toLowerCase().includes(needle));
            if (!tab) return 'not-found';
            if (/tabSeleccionado/i.test(tab.className)) return 'already-active';
            tab.click();
            return 'clicked';
        }""", tab_text)
        if result == 'not-found':
            print(f"   ⚠️  No se pudo cambiar a la pestaña '{tab_text}'")
            return False
        if result == 'clicked':
            await asyncio.sleep(1)
        return True

    async def _click_contenteditable_with_text(self, text: str,
                                                timeout_ms: int = 6000) -> bool:
        """Busca el primer [contenteditable="true"] visible cuyo texto ya sea
        `text` y lo clickea para disparar el blur que AmeliCA necesita.

        MECANISMO CONFIRMADO (grabado.txt, 382 eventos): AmeliCA pre-rellena
        los campos con su inferencia del artículo. El 'llenado' es un simple
        click sobre ese texto ya presente — confirmado para nombre, apellido,
        email, afiliación, abstract, palabras clave y DOI. NO se tipea nada.

        Matching: exacto, o por prefijo de ≥12 chars para textos largos como
        abstracts o nombres de instituciones (tolerancia a truncamiento).

        Retry: 3 intentos con pausa entre ellos, por si el campo tarda en
        renderizarse después del click en el botón que lo creó.
        """
        text_s = text.strip()
        if not text_s:
            return False
        prefix_len = min(len(text_s), 25)
        prefix = text_s[:prefix_len].lower()

        for attempt in range(3):
            result = await self.page.evaluate("""([ts, pfx, pfx_len]) => {
                for (const el of document.querySelectorAll('[contenteditable="true"]')) {
                    // offsetParent === null significa que el elemento está oculto
                    if (el.offsetParent === null) continue;
                    const elText = (el.innerText || el.textContent || '').trim();
                    const elLow  = elText.toLowerCase();
                    if (elText === ts ||
                        (pfx_len >= 12 && elLow.startsWith(pfx))) {
                        el.click();
                        el.focus();
                        return elText.substring(0, 60);
                    }
                }
                return null;
            }""", [text_s, prefix, prefix_len])

            if result is not None:
                await asyncio.sleep(0.4)
                print(f"      ✅ Click en campo pre-relleno: '{result}'")
                return True

            if attempt < 2:
                await asyncio.sleep(timeout_ms / 3000.0)

        print(f"      ⚠️  Sin contenteditable con texto: '{text_s[:50]}'")
        return False

    async def _fill_datepicker(self, date_str: str) -> bool:
        """Selecciona una fecha en el datepicker jQuery UI de AmeliCA.

        date_str: "DD-MM-YYYY" o "DD/MM/YYYY" (resultado de
        extract_full_article_data_from_html, que reemplaza '/' con '-').

        Requiere que el datepicker ya esté visible. Si no lo está, intenta
        abrirlo clickeando el trigger más reciente visible (ícono de
        calendario o input de fecha). Si tampoco funciona, avisa para
        completar manualmente — mejor que silenciar el error.

        Implementación basada en estructura estándar jQuery UI datepicker:
          .ui-datepicker-month  → <select> de mes (0-indexed)
          .ui-datepicker-year   → <select> de año
          td[data-handler="selectDay"] a → celdas de días
        No confirmado contra el datepicker real de AmeliCA — es el primer
        lugar a ajustar si los selectores no coinciden.
        """
        parts = date_str.replace('/', '-').split('-')
        if len(parts) != 3:
            print(f"   ⚠️  Formato de fecha irreconocible: '{date_str}'")
            return False
        try:
            if len(parts[0]) == 4:          # YYYY-MM-DD
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            else:                            # DD-MM-YYYY
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            print(f"   ⚠️  Fecha no numérica: '{date_str}'")
            return False

        month_idx = month - 1   # jQuery UI: meses 0-based

        # Abrir el datepicker si no está visible
        dp_visible = await self.page.evaluate("""() => {
            const dp = document.getElementById('ui-datepicker-div');
            return !!(dp && dp.offsetParent !== null);
        }""")

        if not dp_visible:
            opened = await self.page.evaluate("""() => {
                const candidates = [
                    ...document.querySelectorAll('.ui-datepicker-trigger'),
                    ...document.querySelectorAll('input[id*="date"]:not([type="hidden"])'),
                    ...document.querySelectorAll('button[class*="calendar"], button[class*="date"]'),
                ].filter(el => el.offsetParent !== null);
                if (!candidates.length) return false;
                candidates[candidates.length - 1].click();
                return true;
            }""")
            if opened:
                await asyncio.sleep(0.5)
            else:
                print(f"      ⚠️  Datepicker no visible y no se pudo abrir — "
                      f"completá la fecha {date_str} manualmente")
                return False

        # Seleccionar mes y año en los selects del datepicker.
        #
        # OJO: van en DOS evaluate() separados, no uno. jQuery UI reconstruye
        # los <select> de mes/año del datepicker cuando cambia el mes (parte
        # de _updateDatepicker() al redibujar el calendario), así que si se
        # consultan ambos selects ANTES de disparar el 'change' del mes, la
        # referencia al select de año queda apuntando a un nodo ya
        # desconectado del DOM cuando se dispara SU 'change' — el evento no
        # llega a ningún listener y el año nunca se aplica. Confirmado en
        # vivo (2026-08-18): día y mes quedaban bien, año se quedaba en el
        # actual (2026) en vez del pedido. Re-consultar el select de año
        # DESPUÉS del cambio de mes evita la referencia stale.
        month_result = await self.page.evaluate("""(mi) => {
            const dp = document.getElementById('ui-datepicker-div');
            if (!dp || dp.offsetParent === null) return 'dp-hidden';
            const mSel = dp.querySelector('.ui-datepicker-month');
            if (!mSel) return 'no-month';
            mSel.value = String(mi);
            mSel.dispatchEvent(new Event('change', {bubbles: true}));
            return 'ok';
        }""", month_idx)

        if month_result == 'dp-hidden':
            print(f"      ⚠️  Datepicker se ocultó antes de setear el mes para {date_str}")
            return False

        await asyncio.sleep(0.3)    # dejar que jQuery UI re-renderice tras el cambio de mes

        year_result = await self.page.evaluate("""(yr) => {
            const dp = document.getElementById('ui-datepicker-div');
            if (!dp || dp.offsetParent === null) return 'dp-hidden';
            const ySel = dp.querySelector('.ui-datepicker-year');   // re-consultado, no reusado
            if (!ySel) return 'no-year';
            ySel.value = String(yr);
            ySel.dispatchEvent(new Event('change', {bubbles: true}));
            return 'ok';
        }""", year)

        if year_result == 'dp-hidden':
            print(f"      ⚠️  Datepicker se ocultó antes de setear el año para {date_str}")
            return False

        await asyncio.sleep(0.4)    # esperar re-render del calendario

        # Click en el día correspondiente
        day_clicked = await self.page.evaluate("""(day) => {
            const dp = document.getElementById('ui-datepicker-div');
            if (!dp) return false;
            // jQuery UI estándar: <td data-handler="selectDay"><a class="ui-state-default">
            for (const a of dp.querySelectorAll(
                    'td[data-handler="selectDay"] a.ui-state-default')) {
                if (parseInt(a.textContent.trim()) === day) {
                    a.click();
                    return true;
                }
            }
            // Fallback: cualquier <a> en celda de día no gris del mes actual
            for (const td of dp.querySelectorAll(
                    'td:not(.ui-datepicker-other-month):not(.ui-state-disabled)')) {
                const a = td.querySelector('a');
                if (a && parseInt(a.textContent.trim()) === day) {
                    a.click();
                    return true;
                }
            }
            return false;
        }""", day)

        if day_clicked:
            print(f"      ✅ Fecha seleccionada: {day:02d}/{month:02d}/{year}")
            await asyncio.sleep(0.3)
            return True
        else:
            print(f"      ⚠️  Día {day} no encontrado en el datepicker — "
                  f"completá {date_str} manualmente")
            return False

    async def _type_in_caja_contenido(self, title_attr: str, text: str) -> bool:
        """Tipea texto en el span.contenido- dentro de la caja identificada por
        title_attr. Usado para campos vacíos que AmeliCA NO pre-rellena porque
        el texto no aparece en el artículo cargado.

        Casos confirmados:
        - Título en otro idioma: 'Título Alternativo - EN'
          (el artículo es en ES, AmeliCA no puede inferir el título en EN)

        Casos probables con la misma estructura (a confirmar):
        - Si el resumen en otro idioma también quedara vacío (aunque en
          grabado.txt sí venía pre-relleno, así que ahí se usa
          _click_contenteditable_with_text en su lugar).

        Estructura DOM confirmada:
          <div title="Título Alternativo - EN">
            <span class="contenido-526564616c7963" contenteditable="true"></span>
          </div>
        """
        result = await self.page.evaluate("""([title]) => {
            const all = [...document.querySelectorAll(`[title="${title}"]`)]
                .filter(el => el.offsetParent !== null);
            if (!all.length) return 'not-found';
            const caja = all[all.length - 1];   // la más reciente si hay varias
            const span = caja.querySelector('[contenteditable="true"]');
            if (!span) return 'no-span';
            span.click();
            span.focus();
            return 'ok';
        }""", [title_attr])

        if result != 'ok':
            print(f"      ⚠️  _type_in_caja_contenido ({result}): '{title_attr}'")
            return False

        await asyncio.sleep(0.2)
        await self.page.keyboard.type(text, delay=8)
        print(f"      ✅ Tipeado en '{title_attr}': '{text[:55]}'")
        return True
