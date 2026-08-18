"""
front_matter.py — Completa la pestania "Datos del articulo" en AmeliCA
(titulos, autores, afiliaciones, resumen, palabras clave, fechas).

AVISO: basado en un registro real de clicks + el HTML de menus del portal,
pero no verificado exhaustivamente contra el sitio en vivo. Los menus en
cascada son dinamicos. Tratar como punto de partida a corregir, no como
automatizacion garantizada.
"""

import asyncio
import re


class FrontMatterMixin:
    """Llenado de "Datos del articulo". Se mezcla en AmelicaUploader."""

    async def _autores_con_datos(self) -> list[dict]:
        """Inspecciona los bloques de autor y dice cuáles tienen contenido.

        Sirve para distinguir un artículo recién creado (bloques presentes
        pero VACÍOS — AmeliCA no pre-rellena los campos de autor) de uno ya
        cargado, donde borrar 'sobrantes' destruye datos reales.
        """
        return await self.page.evaluate(r"""() => {
            const CAMPOS = ['Nombre(s)', 'Apellido(s)', 'Correo electrónico',
                            'Afiliación completa', 'Institución'];
            const bloques = [...document.querySelectorAll('[title="Autor"]')]
                .filter(el => el.offsetParent !== null);
            return bloques.map((b, i) => {
                const valores = {};
                for (const campo of CAMPOS) {
                    const el = b.querySelector('[title="' + campo + '"]');
                    const txt = el ? (el.innerText || el.textContent || '').trim() : '';
                    if (txt) valores[campo] = txt;
                }
                return {indice: i, tiene_datos: Object.keys(valores).length > 0,
                        valores: valores};
            });
        }""")

    async def _borrar_autores_sobrantes(self, solo_vacios: bool = True) -> dict:
        """Borra los bloques de autor sobrantes (todos menos el primero).

        Con solo_vacios=True — el default — respeta los bloques que tengan
        contenido: son datos reales, no restos de una inferencia previa.
        Devuelve {'borrados': n, 'conservados': n}.
        """
        return await self.page.evaluate(r"""(soloVacios) => {
            const CAMPOS = ['Nombre(s)', 'Apellido(s)', 'Correo electrónico',
                            'Afiliación completa', 'Institución'];
            const tieneDatos = (b) => CAMPOS.some(c => {
                const el = b.querySelector('[title="' + c + '"]');
                return el && (el.innerText || el.textContent || '').trim();
            });
            const authors = [...document.querySelectorAll('[title="Autor"]')]
                .filter(el => el.offsetParent !== null);
            let borrados = 0, conservados = 0;
            for (let i = authors.length - 1; i >= 1; i--) {
                const a = authors[i];
                if (soloVacios && tieneDatos(a)) { conservados++; continue; }
                a.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                a.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                const btn = a.querySelector('[title="Cerrar"]');
                if (btn) { btn.click(); borrados++; }
            }
            return {borrados: borrados, conservados: conservados};
        }""", solo_vacios)

    @staticmethod
    def _split_author_name(full_name: str) -> tuple:
        """Divide el nombre completo en (Nombre(s), Apellido(s)).

        Regla confirmada para estos artículos:
          2 palabras → 1 nombre  + 1 apellido
          3 palabras → 1 nombre  + 2 apellidos
          4 palabras → 2 nombres + 2 apellidos
          5+         → 2 nombres + resto como apellidos
        """
        parts = full_name.strip().split()
        if len(parts) <= 1:
            return full_name, ''
        elif len(parts) == 2:
            return parts[0], parts[1]
        elif len(parts) == 3:
            return parts[0], ' '.join(parts[1:])
        else:   # 4+
            return ' '.join(parts[:2]), ' '.join(parts[2:])

    @staticmethod
    def _country_code_from_affil(affil_text: str, affil_country: str,
                                  emails: list) -> str:
        """Devuelve el código ISO-2 en minúsculas (ej. 'ec') para el select
        de País, inferido del TLD del email o del texto de país de la afiliación.

        El select de AmeliCA usa value='ec', 'co', etc. (minúsculas).
        """
        # 1. TLD del email: @ucuenca.edu.ec → 'ec'
        for email in (emails or []):
            domain = email.split('@')[-1] if '@' in email else ''
            tld = domain.split('.')[-1].lower()
            if len(tld) == 2 and tld.isalpha():
                return tld

        # 2. Última palabra del campo country de la afiliación → mapeo
        country_map = {
            'ecuador': 'ec', 'colombia': 'co', 'perú': 'pe', 'peru': 'pe',
            'chile': 'cl', 'argentina': 'ar', 'mexico': 'mx', 'méxico': 'mx',
            'venezuela': 've', 'bolivia': 'bo', 'paraguay': 'py', 'uruguay': 'uy',
            'brasil': 'br', 'brazil': 'br', 'cuba': 'cu', 'españa': 'es',
            'spain': 'es', 'estados unidos': 'us', 'united states': 'us',
            'costa rica': 'cr', 'panama': 'pa', 'panamá': 'pa',
            'guatemala': 'gt', 'honduras': 'hn', 'nicaragua': 'ni',
            'el salvador': 'sv', 'república dominicana': 'do',
        }
        last = (affil_country or '').split(',')[-1].strip().lower()
        if last in country_map:
            return country_map[last]

        # 3. Intentar buscar cualquier país en el texto completo de afiliación
        full = ((affil_text or '') + ' ' + (affil_country or '')).lower()
        for name, code in country_map.items():
            if name in full:
                return code

        return ''

    async def fill_front_matter(self, data: dict) -> bool:
        """Completa la pestaña 'Datos del artículo' en AmeliCA.

        LÓGICA CORRECTA — confirmada con grabado.txt (382 eventos reales):

        AmeliCA pre-rellena los campos con su inferencia automática del
        artículo. Para confirmar cada campo, el usuario (o nosotros) hace
        CLICK sobre el texto ya presente en el campo — nunca tipea. El
        único campo que requiere tipeo es el ORCID (no aparece pre-inferido
        en ningún parte del artículo).

        Regla de creación (qué necesita click en botón vs qué ya existe):
        - PRE-CREADOS (sin click en "Agregar"): el primer autor, las 2 fechas.
        - NECESITAN botón: autores 2-N, título/resumen en otro idioma,
          cada grupo de palabras clave, cada palabra clave individual, DOI.

        data: el dict de extract_full_article_data_from_html().
        """
        print("\n" + "─"*55)
        print("📋 Completando 'Datos del artículo'...")
        print("─"*55)

        # Problemas detectados durante el llenado. Si queda alguno, el paso
        # NO se reporta como exitoso aunque el "Guardar" final funcione:
        # guardar datos mal puestos no es haber completado el artículo.
        self._fm_problemas: list[str] = []

        # ── Guarda: ¿este artículo ya tiene datos cargados? ───────────
        #
        # En un artículo recién creado los bloques de autor existen pero
        # están VACÍOS (confirmado: AmeliCA no pre-rellena esos campos).
        # Si vienen con contenido, estamos parados sobre un artículo ya
        # trabajado — y el paso siguiente borraría autores reales, que es
        # exactamente lo que pasó el 2026-08-18 sobre el número 38 (1).
        try:
            autores_existentes = await self._autores_con_datos()
        except Exception as e:
            print(f"   ⚠️  No se pudo inspeccionar los autores existentes: {e}")
            autores_existentes = []

        con_datos = [a for a in autores_existentes if a['tiene_datos']]
        if con_datos and not getattr(self, 'overwrite', False):
            print("\n   🛑 ABORTADO: el artículo YA tiene datos cargados.")
            print(f"      Autores con contenido: {len(con_datos)} de "
                  f"{len(autores_existentes)}")
            for a in con_datos[:3]:
                resumen = ' / '.join(list(a['valores'].values())[:2])
                print(f"        • {resumen[:60]}")
            if len(con_datos) > 3:
                print(f"        • … y {len(con_datos) - 3} más")
            print("      Completar acá sobrescribiría trabajo ya hecho, así que")
            print("      no se toca nada. Si de verdad querés reescribirlo,")
            print("      volvé a correr con --sobrescribir.")
            return False

        if con_datos:
            print(f"\n   ⚠️  --sobrescribir activo: se van a pisar {len(con_datos)} "
                  f"autor(es) ya cargados")

        if data.get('warnings'):
            for w in data['warnings']:
                print(f"   ⚠️  {w}")
            print("   ⚠️  Hay inconsistencias en autores/afiliaciones — "
                  "revisá manualmente antes de guardar.")

        await self._click_tab('datos del artículo')
        await asyncio.sleep(1.5)

        # ── 1. Título en otro idioma ──────────────────────────────────
        # CAMPO VACÍO — requiere tipeo. AmeliCA no puede inferir el título EN
        # desde un artículo en ES: el span.contenido- queda vacío, confirmado
        # en diagnóstico. Se usa _type_in_caja_contenido, no _click_...
        # La caja creada tiene title="Título Alternativo - EN" (confirmado).
        title_en = next((t for t in data.get('titles', []) if t['lang'] == 'en'), None)
        if title_en:
            print(f"\n   📌 Título EN: {title_en['text'][:60]}")
            if await self._click_caja('Títulos'):
                if await self._click_menu_button('Título en otro idioma'):
                    await self._select_option_containing_class('xml:lang', 'Inglés')
                    await asyncio.sleep(0.4)   # esperar que se cree la caja
                    await self._type_in_caja_contenido(
                        'Título Alternativo - EN', title_en['text']
                    )

        # ── 2. Autores ────────────────────────────────────────────────
        # CONFIRMADO (grabado.txt):
        # - Primer autor: PRE-CREADO por AmeliCA. Solo activar su caja y
        #   clickear los campos ya pre-rellenos (nombre, afiliación, email).
        # - Autores 2-N: crear con botón "Autor", luego clickear sus campos.
        # - ORCID: único campo que se tipea (no viene pre-inferido).
        #
        # Incertidumbre pendiente: ¿el nombre de autor viene en un campo
        # único "nombre completo" o en campos separados nombre/apellido?
        # El evento 65 muestra click en "Freddy" (solo primer nombre), lo que
        # sugiere campos separados. Por eso se intenta el nombre completo
        # primero y luego cada parte por separado si falla el match completo.

        # ── 2. Autores ────────────────────────────────────────────────
        # ESTRATEGIA (confirmada con diagnóstico en vivo):
        # - Todos los campos del autor están VACÍOS (AmeliCA no los pre-rellena).
        # - Hay que tipear todo: nombre, apellido, afiliación, email, país, ORCID.
        # - Puede haber divs de autor sobrantes de inferencias previas →
        #   borrar todos excepto el primero, luego sobrescribir autor 1 y
        #   crear autores 2-N con el botón.
        #
        # Campos y title= confirmados en DOM real:
        #   Nombre(s)          → title="Nombre(s)"         span.contenido-
        #   Apellido(s)        → title="Apellido(s)"        span.contenido-
        #   Correo electrónico → title="Correo electrónico" span.contenido-
        #   Afiliación completa→ title="Afiliación completa" span.contenido-
        #   Institución        → title="Institución"        span.contenido-
        #   País               → title="País"               select value=código_iso
        #   Identificador autor→ title="Identificador del autor" (pre-creado)
        #                        select contrib-id-type → "ORCID"
        #                        span.contenido- → "https://orcid.org/" + sufijo

        emails_ptr = {num: 0 for num in data.get('affiliations', {})}

        # Paso 0: borrar autores sobrantes (todos menos el primero).
        #
        # Solo se borran bloques VACÍOS — restos de inferencias previas. Un
        # bloque con contenido es dato real y no se toca, salvo que se haya
        # pedido --sobrescribir explícitamente.
        resultado = await self._borrar_autores_sobrantes(
            solo_vacios=not getattr(self, 'overwrite', False))
        deleted = resultado['borrados']
        if resultado['conservados']:
            print(f"   🛡️  {resultado['conservados']} bloque(s) de autor con "
                  f"datos: NO se tocaron")
        if deleted:
            print(f"\n   🗑️  Eliminados {deleted} autor(es) sobrante(s)")
            await asyncio.sleep(0.8 * deleted)   # esperar re-render por cada uno

        for i, author in enumerate(data.get('authors', [])):
            affil      = data.get('affiliations', {}).get(author.get('affil_num', ''), {})
            affil_text = affil.get('text', '')        # "Universidad de Cuenca, Fac..."
            affil_ctry = affil.get('country', '')     # "Cuenca, Ecuador"
            emails     = affil.get('emails', [])

            # Email de este autor (siguiente disponible de su afiliación)
            ptr   = emails_ptr.get(author.get('affil_num', ''), 0)
            email = emails[ptr] if ptr < len(emails) else ''
            if email:
                emails_ptr[author['affil_num']] = ptr + 1

            given, surname = self._split_author_name(author['name'])
            country_code   = self._country_code_from_affil(affil_text, affil_ctry, emails)
            # Afiliación completa = texto + país (todo junto como aparece en el artículo)
            affil_full = ', '.join(filter(None, [affil_text, affil_ctry]))
            # Institución = solo hasta la primera coma
            institution = affil_text.split(',')[0].strip() if affil_text else ''

            print(f"\n   👤 Autor {i+1}: {given} | {surname} | {country_code or '?'}")

            if i == 0:
                # Primer autor: ya existe, activar su caja directamente
                await self._click_caja('Autor', nth='first')
            else:
                # Autores 2+: crear con botón desde la sección Autores
                await self._click_caja('Autores')
                if not await self._click_menu_button('Autor'):
                    print(f"      ⚠️  No se pudo crear autor {i+1} — saltando")
                    continue
                await asyncio.sleep(0.5)
                await self._click_caja('Autor')   # activar el recién creado (.last)

            # ── Nombre(s) y Apellido(s) ──────────────────────────────
            if given:
                await self._type_in_caja_contenido('Nombre(s)', given)
            if surname:
                await self._click_caja('Apellido(s)')
                await self._type_in_caja_contenido('Apellido(s)', surname)

            # ── Afiliación completa e Institución ────────────────────
            if affil_full:
                await self._click_caja('Afiliación completa')
                await self._type_in_caja_contenido('Afiliación completa', affil_full)
            if institution:
                await self._click_caja('Institución')
                await self._type_in_caja_contenido('Institución', institution)

            # ── País (select por value=código_iso, ej. 'ec') ─────────
            # El select tiene class="country-526564616c7963 attrib-526564616c7963"
            # y options con value='ec', 'co', etc. (minúsculas, sin texto).
            # _select_option_containing_class usa label= que no matchea —
            # hay que usar value= directamente.
            if country_code:
                await self._click_caja('País')
                country_set = await self.page.evaluate("""(code) => {
                    const sel = [...document.querySelectorAll('select')]
                        .filter(el => el.offsetParent !== null &&
                                      el.className.includes('country-'))
                        .at(-1);
                    if (!sel) return 'no-select';
                    const opt = [...sel.options].find(
                        o => o.value.toLowerCase() === code.toLowerCase()
                    );
                    if (!opt) return 'no-option-' + code;
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'ok-' + opt.value;
                }""", country_code)
                print(f"      {'✅' if country_set.startswith('ok') else '⚠️ '} País: {country_set}")

            # ── Correo electrónico ───────────────────────────────────
            if email:
                await self._click_caja('Correo electrónico')
                await self._type_in_caja_contenido('Correo electrónico', email)

            # ── ORCID ────────────────────────────────────────────────
            # "Identificador del autor" es un botón que CREA el div,
            # no una caja preexistente. Hay que: activar el autor (.last),
            # clickear el botón, seleccionar ORCID en el select, tipear sufijo.
            if author.get('orcid'):
                await self._click_caja('Autor')   # re-activar para que aparezcan botones
                if await self._click_menu_button('Identificador del autor'):
                    await asyncio.sleep(0.3)
                    orcid_suffix = author['orcid'].replace('https://orcid.org/', '')
                    # Seleccionar ORCID en el select visible
                    sel_ok = await self.page.evaluate("""() => {
                        const sel = [...document.querySelectorAll('select')]
                            .filter(el => el.offsetParent !== null &&
                                          el.className.includes('contrib-id-type'))
                            .at(-1);
                        if (!sel) return 'no-select';
                        sel.value = 'ORCID';
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return 'ok';
                    }""")
                    if sel_ok == 'ok':
                        await asyncio.sleep(0.5)  # esperar pre-relleno "https://orcid.org/"
                        inserted = await self.page.evaluate("""(full_orcid) => {
                            const divs = [...document.querySelectorAll('[title="Identificador del autor"]')]
                                .filter(el => el.offsetParent !== null);
                            if (!divs.length) return 'not-found';
                            const span = divs.at(-1).querySelector('[contenteditable="true"]');
                            if (!span) return 'no-span';
                            span.focus();
                            document.execCommand('selectAll', false, null);
                            const ok = document.execCommand('insertText', false, full_orcid);
                            return ok ? 'ok:' + span.innerText.slice(-10) : 'insertText-failed';
                        }""", author['orcid'])
                        if inserted.startswith('ok'):
                            print(f"      ✅ ORCID: {inserted}")
                        else:
                            print(f"      ⚠️  ORCID no insertado ({inserted})")
                    else:
                        print(f"      ⚠️  ORCID select no encontrado ({sel_ok})")

        # ── 3. Fechas: Aceptado y Publicado ───────────────────────────
        # CONFIRMADO con DOM real:
        # - Vienen 3 cajas pre-creadas: "Fecha - RECEIVED", "Fecha - ACCEPTED",
        #   "Fecha - PUB". RECEIVED no se usa — se borra.
        # - El tipo se elige en select.date-type- con values en inglés:
        #   'accepted', 'pub' (NO 'published'). El título del div cambia
        #   dinámicamente a "Fecha - ACCEPTED" / "Fecha - PUB".
        # - La fecha se ingresa abriendo el datepicker del input.date-
        #   (id="dp..."), que es jQuery UI estándar: selects de mes (0-based)
        #   y año, click en el día. AmeliCA rellena Día/Mes/Año automáticamente.
        # - Misma estrategia que autores: borrar todo excepto la primera caja,
        #   sobrescribir la primera con Aceptado, crear segunda para Publicado.

        # Mapeo data_key → value del select (confirmado con DOM)
        DATE_TYPE_VALUES = {'accepted': 'accepted', 'published': 'pub'}

        # Paso 0: crear las fechas nuevas PRIMERO (quedan al final del DOM)
        dates_ordered = [
            (k, DATE_TYPE_VALUES[k])
            for k in ('accepted', 'published')
            if data.get('dates', {}).get(k)
        ]

        n_created = 0
        for date_key, type_value in dates_ordered:
            await self._click_caja('Fechas')
            if await self._click_menu_button('Fecha'):
                n_created += 1
                await asyncio.sleep(0.4)

        # Borrar las fechas pre-existentes (las primeras del DOM).
        # El botón Cerrar solo aparece al hacer hover — se dispara mouseover
        # para revelarlo antes de clickearlo, igual que con los autores.
        if n_created > 0:
            deleted_dates = await self.page.evaluate("""(n_new) => {
                const fechas = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Fecha') &&
                                  el.className.includes('date-526564616c7963'));
                const to_delete = fechas.slice(0, fechas.length - n_new);
                let count = 0;
                for (let i = to_delete.length - 1; i >= 0; i--) {
                    const f = to_delete[i];
                    // Disparar hover para revelar el botón Cerrar
                    f.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    f.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = f.querySelector('[title="Cerrar"]');
                    if (btn) { btn.click(); count++; }
                }
                return count;
            }""", n_created)
            if deleted_dates:
                print(f"\n   🗑️  Eliminadas {deleted_dates} fecha(s) pre-existente(s)")
                await asyncio.sleep(0.4 * deleted_dates)

        # Ahora llenar cada fecha nueva (son las únicas que quedan, en orden)
        dp_usados = set()
        for date_idx, (date_key, type_value) in enumerate(dates_ordered):
            date_str = data['dates'][date_key]
            print(f"\n   📅 {date_key}: {date_str}")

            # Activar la fecha en orden (primera = nth first, segunda = last)
            nth = 'first' if date_idx == 0 else 'last'
            await self._click_caja('Fecha', nth=nth)

            # Elegir tipo en el select DE ESTA caja de fecha.
            #
            # Antes se tomaba .at(-1) — el ultimo select del documento — sin
            # importar cual caja se habia activado, asi que las dos fechas
            # escribian en el mismo widget y la segunda (published) pisaba a
            # la primera: el articulo quedaba con el año de publicacion en el
            # campo de aceptado. Ahora se busca dentro del contenedor que
            # corresponde al indice.
            type_set = await self.page.evaluate("""([idx, val]) => {
                const cajas = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  (el.getAttribute('title') || '').startsWith('Fecha'));
                const caja = cajas[idx];
                if (!caja) return 'no-caja-' + idx;
                const sel = [...caja.querySelectorAll('select')]
                    .filter(el => el.className.includes('date-type-'))[0];
                if (!sel) return 'no-select';
                sel.value = val;
                sel.dispatchEvent(new Event('change', {bubbles: true}));
                return 'ok-' + val;
            }""", [date_idx, type_value])
            print(f"      {'✅' if type_set.startswith('ok') else '⚠️ '} Tipo: {type_set}")
            await asyncio.sleep(0.3)

            # Abrir el datepicker del input DE ESTA caja (mismo motivo).
            dp_opened = await self.page.evaluate("""(idx) => {
                const cajas = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  (el.getAttribute('title') || '').startsWith('Fecha'));
                const caja = cajas[idx];
                if (!caja) return 'no-caja-' + idx;
                const inp = [...caja.querySelectorAll('input.date-526564616c7963')]
                    .filter(el => el.offsetParent !== null && el.type !== 'hidden')[0];
                if (!inp) return 'no-input';
                inp.click();
                return 'ok-' + inp.id;
            }""", date_idx)
            print(f"      {'✅' if dp_opened.startswith('ok') else '⚠️ '} Datepicker: {dp_opened}")
            await asyncio.sleep(0.4)

            # Si no se pudo apuntar a los controles de ESTA caja, la fecha
            # que se escriba puede terminar en el campo equivocado: se
            # registra como problema para que salga en el resumen final.
            if not type_set.startswith('ok'):
                self._fm_problemas.append(
                    f"fecha '{date_key}': no se encontró el select de tipo ({type_set})")
            if not dp_opened.startswith('ok'):
                self._fm_problemas.append(
                    f"fecha '{date_key}': no se encontró el input ({dp_opened})")
            elif dp_opened in dp_usados:
                # Las dos fechas apuntando al mismo input = una pisa a la otra.
                self._fm_problemas.append(
                    f"fecha '{date_key}': reusa el datepicker de otra fecha")
            else:
                dp_usados.add(dp_opened)

            await self._fill_datepicker(date_str)

        # ── 4. Resúmenes ──────────────────────────────────────────────
        # CONFIRMADO con DOM real:
        # - Sección padre: title="Resúmenes"
        # - Resumen ES viene pre-creado: title="Resumen  - ES" (2 espacios)
        # - Párrafo dentro del resumen: title="Párrafo", span.contenido- adentro
        # - Botón para crear EN: "Resumen en otro idioma"
        # - Estrategia: borrar todo, crear ES y EN desde cero con botones,
        #   tipear en el Párrafo de cada uno con _type_in_caja_contenido.
        # INCERTIDUMBRE: el botón para crear el resumen ES puede llamarse
        # "Resumen" u otro nombre — confirmar si falla.

        abstracts_to_fill = data.get('abstracts', [])
        if abstracts_to_fill:
            # REGLA CONFIRMADA:
            # - Siempre hay 1 resumen pre-creado: title="Resumen Original - ES/EN"
            # - Si hay 2 abstracts: primero → pre-creado, segundo → crear con botón
            # - Si hay 1: solo el pre-creado
            # - Nunca hay 3
            #
            # Para el pre-creado:
            # - Verificar idioma (xml:lang oculto ya viene correcto normalmente)
            # - Si tiene más de 1 párrafo, borrar los extras (con mouseover+Cerrar)
            #   dejando solo 1. Si solo hay 1, no se puede borrar — AmeliCA lo impide.
            # - Tipear el texto en el único párrafo que queda
            #
            # Para el segundo (si aplica): crear con botón, asignar idioma, tipear.

            abstract_primary   = abstracts_to_fill[0]
            abstract_secondary = abstracts_to_fill[1] if len(abstracts_to_fill) > 1 else None

            # ── Resumen pre-creado (primero / principal) ──────────────
            print(f"\n   📝 Resumen principal {abstract_primary['lang'].upper()} "
                  f"({len(abstract_primary['text'])} chars)")

            # Activar el pre-creado con click
            activated = await self.page.evaluate("""() => {
                const r = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Resumen Original') &&
                                  el.className.includes('abstract-'))
                    .at(0);
                if (!r) return 'not-found';
                r.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                r.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                r.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                r.focus();
                return 'ok-' + r.getAttribute('title');
            }""")
            print(f"      {'✅' if activated.startswith('ok') else '⚠️ '} {activated}")
            await asyncio.sleep(0.3)

            # Borrar párrafos extras (si hay más de 1) — dejar solo el primero
            deleted_p = await self.page.evaluate("""() => {
                const r = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Resumen Original') &&
                                  el.className.includes('abstract-'))
                    .at(0);
                if (!r) return 0;
                const parrafos = [...r.querySelectorAll('[title="Párrafo"]')]
                    .filter(el => el.offsetParent !== null);
                // Borrar de atrás hacia adelante, dejando el primero
                let count = 0;
                for (let i = parrafos.length - 1; i >= 1; i--) {
                    const p = parrafos[i];
                    p.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    p.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = p.querySelector('[title="Cerrar"]');
                    if (btn) { btn.click(); count++; }
                }
                return count;
            }""")
            if deleted_p:
                print(f"      🗑️  Eliminados {deleted_p} párrafo(s) extra(s)")
                await asyncio.sleep(0.3 * deleted_p)

            # Tipear en el único párrafo del pre-creado (limpiar primero si tiene texto)
            await self._click_caja('Párrafo')
            await self.page.evaluate("""() => {
                const spans = [...document.querySelectorAll('[title="Párrafo"] [contenteditable="true"]')]
                    .filter(el => el.offsetParent !== null);
                if (!spans.length) return;
                const span = spans.at(0);
                span.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
            }""")
            await asyncio.sleep(0.2)
            await self._type_in_caja_contenido('Párrafo', abstract_primary['text'])

            # ── Resumen secundario (si aplica) ────────────────────────
            if abstract_secondary:
                lang = abstract_secondary['lang']
                print(f"\n   📝 Resumen secundario {lang.upper()} "
                      f"({len(abstract_secondary['text'])} chars)")

                await self._click_caja('Resúmenes')
                if await self._click_menu_button('Resumen en otro idioma'):
                    await asyncio.sleep(0.4)
                    await self._click_caja('Resumen')
                    lang_set = await self.page.evaluate("""(lang) => {
                        const sel = [...document.querySelectorAll('select')]
                            .filter(el => el.offsetParent !== null &&
                                          el.className.includes('xml:lang-'))
                            .at(-1);
                        if (!sel) return 'no-select';
                        sel.value = lang;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        return 'ok-' + lang;
                    }""", lang)
                    print(f"      {'✅' if lang_set.startswith('ok') else '⚠️ '} Idioma: {lang_set}")
                    await asyncio.sleep(0.3)
                    await self._click_caja('Párrafo')
                    await self._type_in_caja_contenido('Párrafo', abstract_secondary['text'])



        # ── 5. Palabras clave (ES e EN) ────────────────────────────────
        # ESTRATEGIA CONFIRMADA (igual que resúmenes):
        # 1. Borrar grupos extras dejando solo 1 con mouseover+Cerrar
        # 2. Borrar keywords extras dentro del grupo dejando solo 1
        # 3. Asignar idioma al grupo que quedó → tipear primera keyword
        #    (limpiar con selectAll+delete primero)
        # 4. Crear keywords adicionales con botón → tipear
        # 5. Si hay segundo idioma: crear grupo → asignar idioma → mismo flujo

        kwd_abstracts = [a for a in data.get('abstracts', []) if a.get('keywords')]

        if kwd_abstracts:
            # Paso 1: activar sección padre
            await self._click_caja('Grupo de palabras clave')
            await asyncio.sleep(0.5)

            # Paso 2: si no hay ningún grupo, crear uno con el botón
            n_grupos_ini = await self.page.evaluate("""() =>
                [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                  el.className.includes('kwd-group-')).length
            """)
            if n_grupos_ini == 0:
                print("   ℹ️  Sin grupos pre-creados — creando uno...")
                await self._click_menu_button('Grupo de palabras clave')
                await asyncio.sleep(0.4)
                await self._click_caja('Grupo de palabras clave')
                await asyncio.sleep(0.3)

            # Paso 3: borrar grupos extras dejando solo el primero
            await self.page.evaluate("""() => {
                const grupos = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                  el.className.includes('kwd-group-'));
                for (let i = grupos.length - 1; i >= 1; i--) {
                    const g = grupos[i];
                    g.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    g.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = g.querySelector('[title="Cerrar"]');
                    if (btn) btn.click();
                }
            }""")
            await asyncio.sleep(0.4)

            # Paso 4: borrar keywords extras en el grupo que quedó, dejando solo 1
            await self.page.evaluate("""() => {
                const grupo = [...document.querySelectorAll('[title]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                  el.className.includes('kwd-group-')).at(0);
                if (!grupo) return;
                const kwds = [...grupo.querySelectorAll('[title="Palabra clave"]')]
                    .filter(el => el.offsetParent !== null);
                for (let i = kwds.length - 1; i >= 1; i--) {
                    const k = kwds[i];
                    k.dispatchEvent(new MouseEvent('mouseover',  {bubbles:true, cancelable:true, view:window}));
                    k.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true, cancelable:true, view:window}));
                    const btn = k.querySelector('[title="Cerrar"]');
                    if (btn) btn.click();
                }
            }""")
            await asyncio.sleep(0.4)

            for kwd_idx, abstract in enumerate(kwd_abstracts):
                lang = abstract['lang']
                keywords = abstract['keywords']
                # is_first: True = primer grupo (pre-existente), False = grupo nuevo
                is_first = (kwd_idx == 0)
                print(f"\n   🏷️  Keywords {lang.upper()}: {keywords}")

                if is_first:
                    # Re-activar sección padre y luego el primer grupo
                    await self._click_caja('Grupo de palabras clave')
                    await asyncio.sleep(0.3)
                    await self.page.evaluate("""() => {
                        const g = [...document.querySelectorAll('[title]')]
                            .filter(el => el.offsetParent !== null &&
                                          el.getAttribute('title').startsWith('Palabras clave') &&
                                          el.className.includes('kwd-group-')).at(0);
                        if (!g) return;
                        g.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                        g.focus();
                    }""")
                else:
                    # Crear grupo nuevo con botón
                    await self._click_caja('Grupo de palabras clave')
                    if not await self._click_menu_button('Grupo de palabras clave'):
                        print(f"      ⚠️  No se pudo crear grupo {lang.upper()} — saltando")
                        continue
                    await asyncio.sleep(0.4)
                    # Activar el grupo recién creado (el último)
                    await self.page.evaluate("""() => {
                        const g = [...document.querySelectorAll('[title]')]
                            .filter(el => el.offsetParent !== null &&
                                          el.getAttribute('title').startsWith('Palabras clave') &&
                                          el.className.includes('kwd-group-')).at(-1);
                        if (!g) return;
                        g.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                        g.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                        g.focus();
                    }""")
                await asyncio.sleep(0.3)

                # Asignar idioma
                lang_set = await self.page.evaluate("""(lang) => {
                    const sel = [...document.querySelectorAll('select')]
                        .filter(el => el.offsetParent !== null &&
                                      el.className.includes('xml:lang-'))
                        .at(-1);
                    if (!sel) return 'no-select';
                    sel.value = lang;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'ok-' + lang;
                }""", lang)
                print(f"      {'✅' if lang_set.startswith('ok') else '⚠️ '} Idioma: {lang_set}")
                await asyncio.sleep(0.3)

                # Tipear keywords — mismo flujo que el script de consola que funcionó:
                # kw_idx=0: activar kwd existente, limpiar, tipear
                # kw_idx>0: re-activar grupo, botón, tipear en la última kwd
                for kw_idx, kw in enumerate(keywords):
                    if kw_idx == 0:
                        typed = await self.page.evaluate("""([nth_group, text]) => {
                            const grupos = [...document.querySelectorAll('[title]')]
                                .filter(el => el.offsetParent !== null &&
                                              el.getAttribute('title').startsWith('Palabras clave') &&
                                              el.className.includes('kwd-group-'));
                            const grupo = nth_group === 0 ? grupos.at(0) : grupos.at(-1);
                            if (!grupo) return 'no-grupo';
                            const kwd = [...grupo.querySelectorAll('[title="Palabra clave"]')]
                                .filter(el => el.offsetParent !== null).at(0);
                            if (!kwd) return 'no-kwd';
                            kwd.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                            kwd.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                            kwd.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                            const span = kwd.querySelector('[contenteditable="true"]');
                            if (!span) return 'no-span';
                            span.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, text);
                            return 'ok';
                        }""", [kwd_idx, kw])
                        print(f"      {'✅' if typed == 'ok' else '⚠️ '} KWD[0]: '{kw[:40]}' ({typed})")
                    else:
                        # Re-activar grupo y crear keyword nueva
                        await self.page.evaluate("""(nth_group) => {
                            const grupos = [...document.querySelectorAll('[title]')]
                                .filter(el => el.offsetParent !== null &&
                                              el.getAttribute('title').startsWith('Palabras clave') &&
                                              el.className.includes('kwd-group-'));
                            const g = nth_group === 0 ? grupos.at(0) : grupos.at(-1);
                            if (!g) return;
                            g.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                            g.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                            g.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                            g.focus();
                        }""", kwd_idx)
                        await asyncio.sleep(0.2)
                        if await self._click_menu_button('Palabra clave'):
                            await asyncio.sleep(0.2)
                            typed = await self.page.evaluate("""([nth_group, text]) => {
                                const grupos = [...document.querySelectorAll('[title]')]
                                    .filter(el => el.offsetParent !== null &&
                                                  el.getAttribute('title').startsWith('Palabras clave') &&
                                                  el.className.includes('kwd-group-'));
                                const grupo = nth_group === 0 ? grupos.at(0) : grupos.at(-1);
                                if (!grupo) return 'no-grupo';
                                const span = [...grupo.querySelectorAll(
                                    '[title="Palabra clave"] [contenteditable="true"]')]
                                    .filter(el => el.offsetParent !== null).at(-1);
                                if (!span) return 'no-span';
                                span.focus();
                                document.execCommand('insertText', false, text);
                                return 'ok';
                            }""", [kwd_idx, kw])
                            print(f"      {'✅' if typed == 'ok' else '⚠️ '} KWD[{kw_idx}]: '{kw[:40]}' ({typed})")
                    await asyncio.sleep(0.2)


        # ── 6. DOI ────────────────────────────────────────────────────
        # CONFIRMADO con DOM real:
        # - Botón "DOI" siempre visible (no requiere activar caja padre)
        # - Puede venir pre-creado o no — se verifica primero
        # - Si existe: usar el pre-creado; si no: crear con botón
        # - Estructura: [title="DOI"] con span.contenido- adentro → tipear
        # - Limpiar con selectAll+delete antes de tipear (puede tener placeholder)
        if data.get('doi'):
            print(f"\n   🔗 DOI: {data['doi']}")

            # Clickear el div "Datos del artículo" para revelar los botones globales
            await self.page.evaluate("""() => {
                const div = [...document.querySelectorAll('[title="Datos del artículo"]')]
                    .find(el => el.offsetParent !== null);
                if (div) {
                    div.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                    div.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                    div.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                    div.focus();
                }
            }""")
            await asyncio.sleep(0.5)

            # Verificar si ya existe el div DOI (clase confirmada: article-id-doi-)
            # Si no existe, crearlo con el botón que aparece en el panel global
            doi_exists = await self.page.evaluate("""() =>
                [...document.querySelectorAll('[title="DOI"]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.className.includes('article-id-doi-')).length > 0
            """)

            if not doi_exists:
                btn_clicked = await self.page.evaluate("""() => {
                    const btn = [...document.querySelectorAll('input[type="button"]')]
                        .filter(el => el.offsetParent !== null && el.value === 'DOI')[0];
                    if (!btn) return false;
                    btn.click();
                    return true;
                }""")
                if not btn_clicked:
                    print("      ⚠️  Botón DOI no encontrado — saltando")
                    return saved if 'saved' in dir() else False
                print("      ✅ Botón DOI clickeado — esperando creación del div...")
                await asyncio.sleep(0.8)  # esperar a que AmeliCA cree el div

            # Activar el div DOI y tipear
            typed = await self.page.evaluate("""(doi) => {
                const div = [...document.querySelectorAll('[title="DOI"]')]
                    .filter(el => el.offsetParent !== null &&
                                  el.className.includes('article-id-doi-')).at(-1);
                if (!div) return 'no-div';
                div.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, view:window}));
                div.dispatchEvent(new MouseEvent('mouseup',   {bubbles:true, cancelable:true, view:window}));
                div.dispatchEvent(new MouseEvent('click',     {bubbles:true, cancelable:true, view:window}));
                div.focus();
                const span = div.querySelector('[contenteditable="true"]');
                if (!span) return 'no-span';
                span.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                document.execCommand('insertText', false, doi);
                return 'ok:' + span.innerText.slice(-15);
            }""", data['doi'])
            print(f"      {'✅' if typed.startswith('ok') else '⚠️ '} DOI: {typed}")
            await asyncio.sleep(0.3)

        # ── 7. Guardar ──────────────────────────────────────────────────
        print("\n   💾 Guardando...")
        saved = False
        try:
            await self.page.locator('#save-526564616c7963\\:buttonS').click()
            saved = True
            print("   ✅ Click en 'Guardar'")
        except Exception:
            # Fallback por texto visible
            try:
                btn = await self.page.query_selector(
                    'input[value="Guardar"]:visible, button:has-text("Guardar"):visible'
                )
                if btn:
                    await btn.click()
                    saved = True
                    print("   ✅ Click en 'Guardar' (fallback por texto)")
            except Exception:
                pass

        if not saved:
            print("   ⚠️  No se encontró el botón 'Guardar' — guardá manualmente")

        if self._fm_problemas:
            print("\n   ⚠️  Se completó, pero con problemas:")
            for problema in self._fm_problemas:
                print(f"      • {problema}")
            print("      Revisá esos campos en el navegador.")
            return False

        return saved
