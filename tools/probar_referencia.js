// probar_referencia.js — recrea "crear una referencia" para iterar en la
// consola del navegador, sin repetir login/navegación/marcaje cada vez.
//
// Es un puerto 1:1 a JS puro de la lógica que ya vive en
// amelica/portal/references.py (_fill_single_reference, _add_ref_authors,
// _fill_ref_year, _set_ref_pub_type, _set_ref_pub_id_type,
// _fill_ref_contenido, _click_ref_close, _delete_refs_but_one) y de los
// helpers de amelica/portal/dom.py (_click_caja, _click_menu_button) que
// usa. Si aquí se encuentra y se arregla un bug de escritura, hay que
// portar el mismo fix a esos archivos .py -- este script es solo para
// probar rápido, el que corre en las subidas reales es el Python.
//
// Uso:
//   1. Entrar a mano al portal, abrir un artículo DE PRUEBA (no uno real)
//      e ir a la pestaña "Referencias/apéndices". Cerrar los modales que
//      aparezcan como siempre.
//   2. Pegar este script entero en la consola (F12) y Enter.
//   3. Ejecutar:  probarReferencia(REFS_PRUEBA)
//   4. Ver el resultado en la pantalla. Si algo falló, editar REFS_PRUEBA
//      o el cuerpo de fillSingleReference() más abajo, volver a pegar
//      TODO el script (redefine las funciones) y ejecutar
//      probarReferencia() de nuevo. No hace falta recargar la página ni
//      volver a iniciar sesión.
//
// Por defecto, ANTES de llenar nada, se espera (await) a que termine
// limpiarReferencias(): borra todas las referencias existentes menos 1,
// agrega una nueva vacía, y borra la vieja -- así cada corrida arranca
// desde un estado limpio conocido sin arrastrar basura de la corrida
// anterior. Para saltear ese paso: probarReferencia(REFS_PRUEBA, {limpiar: false}).
//
// Opciones:
//   probarReferencia(REFS_PRUEBA)                        // limpia primero (default), no guarda
//   probarReferencia(REFS_PRUEBA, {limpiar: false})       // no limpia, escribe sobre lo que haya
//   probarReferencia(REFS_PRUEBA, {guardar: true})        // clickea Guardar al final
//
// También queda disponible sola: limpiarReferencias() -- por si solo se
// quiere dejar el artículo limpio sin llenar nada todavía.
//
// El primer elemento de REFS_PRUEBA usa la caja "Referencia" (la que deja
// limpiarReferencias); desde el segundo en adelante se crea una caja
// nueva con el botón "Referencia" -- ese paso fue el que más bugs dio en
// corridas reales (ver memoria: sesion-2026-08-19-bugs-ingles-y-403.md),
// así que conviene dejar al menos 2 elementos para seguir ejercitándolo.

(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ── Casos de prueba — editar aquí ───────────────────────────────────
  const REFS_PRUEBA = [
    {
      // JOURNAL con autor personal — usa la caja pre-creada.
      full_text: 'Ahmed S (2021). A test article title. Journal of Testing, '
                 + '10(2), 100-110. https://doi.org/10.1234/test',
      pub_type: 'journal',
      authors: [{ given: 'S', surname: 'Ahmed' }],
      year: '2021',
      source: 'Journal of Testing',
      article_title: 'A test article title',
      volume: '10',
      issue: '2',
      fpage: '100',
      lpage: '110',
      elocation: '',
      url: 'https://doi.org/10.1234/test',
    },
    {
      // BOOK con autor institucional — fuerza crear una caja nueva.
      full_text: 'World Health Organization (2020). Test Book Title. WHO Press, Geneva.',
      pub_type: 'book',
      authors: [{ given: '', surname: 'World Health Organization' }],
      year: '2020',
      source: 'WHO Press',
      article_title: '',
      volume: '',
      issue: '',
      fpage: '',
      lpage: '',
      elocation: '',
      url: '',
    },
  ];
  // ─────────────────────────────────────────────────────────────────

  // ── Helpers (puerto de dom.py) ──────────────────────────────────────

  async function clickCaja(tituloAttr, nth = 'last') {
    const result = (() => {
      const all = [...document.querySelectorAll(`[title="${tituloAttr}"]`)]
        .filter((el) => el.offsetParent !== null);
      if (!all.length) return 'not-found';
      const el = nth === 'first' ? all[0] : all[all.length - 1];
      el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      el.focus();
      return el.className;
    })();

    if (result === 'not-found') {
      console.warn(`No se pudo activar la caja '${tituloAttr}' (no encontrada)`);
      return false;
    }
    for (let i = 0; i < 8; i++) {
      await sleep(250);
      const el = [...document.querySelectorAll(`[title="${tituloAttr}"]`)]
        .find((e) => e.offsetParent !== null);
      if (el && el.className.includes('focus-')) return true;
    }
    console.log(`Caja '${tituloAttr}': clase focus- no apareció — continuando igual`);
    return true;
  }

  async function clickMenuButton(text, timeoutMs = 5000) {
    const start = performance.now();
    while (performance.now() - start < timeoutMs) {
      const btn = [...document.querySelectorAll(`input[type="button"][value="${text}"]`)]
        .find((el) => el.offsetParent !== null);
      if (btn) { btn.click(); return true; }
      await sleep(100);
    }
    console.warn(`No se pudo clickear el botón '${text}' (¿no visible o no existe?)`);
    return false;
  }

  // ── Helpers (puerto de references.py) ───────────────────────────────

  function fillRefContenido(tituloAttr, text, nth = 'last') {
    const all = [...document.querySelectorAll(`[title="${tituloAttr}"]`)]
      .filter((el) => el.offsetParent !== null);
    if (!all.length) { console.warn(`fillRefContenido (not-found): '${tituloAttr}'`); return false; }
    const caja = nth === 'first' ? all[0] : all[all.length - 1];

    caja.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
    caja.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
    caja.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    caja.focus();

    const span = caja.querySelector('[contenteditable="true"]');
    if (!span) { console.warn(`fillRefContenido (no-span): '${tituloAttr}'`); return false; }

    span.click();
    span.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    document.execCommand('insertText', false, text);
    return true;
  }

  async function fillRefYear(year) {
    (() => {
      const cajas = [...document.querySelectorAll('[title="Año"]')]
        .filter((el) => el.offsetParent !== null);
      const caja = cajas[cajas.length - 1];
      if (caja) {
        caja.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
        caja.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
        caja.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
      }
    })();
    await sleep(300);

    const sel = [...document.querySelectorAll('select[class*="iso-8601-date-"]')]
      .filter((el) => el.offsetParent !== null).at(-1);
    if (!sel) { console.warn('Select de Año no encontrado'); return false; }
    for (const opt of sel.options) {
      if (opt.text.trim() === String(year)) {
        sel.value = opt.value;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        console.log(`Año: ${year}`);
        return true;
      }
    }
    console.warn(`Año '${year}' no está entre las opciones del select`);
    return false;
  }

  function setRefPubType(pubType) {
    const sel = [...document.querySelectorAll('select[class*="publication-type-"]')]
      .filter((el) => el.offsetParent !== null).at(-1);
    if (!sel) return false;
    sel.value = pubType;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    if (typeof editInput526564616c7963 === 'function') {
      editInput526564616c7963('publication-type-526564616c7963');
    }
    return true;
  }

  function setRefPubIdType(idType = 'doi') {
    const sel = [...document.querySelectorAll('select[class*="pub-id-type-"]')]
      .filter((el) => el.offsetParent !== null).at(-1);
    if (!sel) return false;
    sel.value = idType;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  // Contenedor [title=...] más cercano de un elemento (sin contarse a sí
  // mismo), para saber a qué caja pertenece de verdad.
  function contenedorDe(el) {
    let nodo = el.parentElement;
    while (nodo) {
      const t = nodo.getAttribute && nodo.getAttribute('title');
      if (t) return t;
      nodo = nodo.parentElement;
    }
    return null;
  }

  async function clickRefClose() {
    const all = [...document.querySelectorAll('[title="Cerrar"]')]
      .filter((el) => el.offsetParent !== null);
    if (!all.length) return false;

    // "Cerrar" es AMBIGUO: el mismo title se usa para colapsar el panel de
    // detalle de la referencia Y para borrar sub-items (Autores,
    // Institución, etc.). Confirmado en vivo (2026-08-21): tomar "el
    // último visible" a ciegas podía agarrar el Cerrar de "Autores" en vez
    // del de "Referencia" y borraba todo ese grupo de autores. Hay que
    // restringirse al que cuelga directo de la caja "Referencia".
    const candidatos = all.filter((el) => contenedorDe(el) === 'Referencia');
    if (!candidatos.length) {
      console.warn('clickRefClose: no se encontró el botón "Cerrar" de la caja "Referencia"');
      return false;
    }
    candidatos[candidatos.length - 1].click();
    await sleep(300);
    return true;
  }

  async function addRefAuthors(authors) {
    if (!authors || !authors.length) return true;
    let personalAdded = false;
    for (const author of authors) {
      const given = author.given || '';
      const surname = author.surname || '';
      const institutional = !given && surname;

      if (institutional) {
        await clickCaja('Autores');
        const clicked = await clickMenuButton('Autor institucional');
        if (!clicked) { console.warn('No se pudo crear autor institucional'); continue; }
        await sleep(400);
        fillRefContenido('Institución', surname, 'last');
        continue;
      }

      if (personalAdded) {
        await clickCaja('Autores');
        const clicked = await clickMenuButton('Autor');
        if (!clicked) { console.warn('No se pudo crear autor'); continue; }
        await sleep(400);
      }
      personalAdded = true;

      fillRefContenido('Nombre(s)', given, 'last');
      fillRefContenido('Apellido(s)', surname, 'last');
    }
    return true;
  }

  async function fillSingleReference(ref) {
    const pubType = ref.pub_type || 'journal';
    const year = ref.year || '';
    const authors = ref.authors || [];

    if (ref.full_text) {
      fillRefContenido('Referencia completa', ref.full_text, 'last');
      await sleep(200);
    }

    await clickCaja('Referencia detallada');
    await sleep(300);

    if (!setRefPubType(pubType)) console.warn(`No se pudo setear pub_type=${pubType}`);

    const detTitle = `Referencia detallada - ${pubType.toUpperCase()}`;
    await clickCaja(detTitle);
    await sleep(300);

    await addRefAuthors(authors);
    await sleep(200);

    if (year) await fillRefYear(year);

    const source = ref.source || '';
    if (source && ['journal', 'confproc', 'book'].includes(pubType)) {
      fillRefContenido('Fuente', source, 'last');
    }

    if (['journal', 'confproc'].includes(pubType)) {
      if (ref.volume) {
        await clickCaja(detTitle);
        if (await clickMenuButton('Volumen')) {
          await sleep(300); fillRefContenido('Volumen', ref.volume, 'last');
        }
      }
      if (ref.issue) {
        await clickCaja(detTitle);
        if (await clickMenuButton('Número')) {
          await sleep(300); fillRefContenido('Número', ref.issue, 'last');
        }
      }
      if (ref.fpage) {
        await clickCaja(detTitle);
        if (await clickMenuButton('Página inicial')) {
          await sleep(300); fillRefContenido('Página inicial', ref.fpage, 'last');
        }
      }
      if (ref.lpage) {
        await clickCaja(detTitle);
        if (await clickMenuButton('Página final')) {
          await sleep(300); fillRefContenido('Página final', ref.lpage, 'last');
        }
      }
      if (ref.elocation) {
        await clickCaja(detTitle);
        if (await clickMenuButton('Paginación electrónica')) {
          await sleep(300); fillRefContenido('Paginación electrónica', ref.elocation, 'last');
        }
      }
    }

    // Título del artículo: SOLO revista (journal), NO actas de conferencia
    // (confproc). Va DESPUÉS de Volumen/Número/Página inicial/Página final
    // -- confirmado por el usuario 2026-08-21 contra el orden real del
    // portal (el orden anterior lo ponía primero, al revés).
    if (pubType === 'journal' && ref.article_title) {
      await clickCaja(detTitle);
      if (await clickMenuButton('Título del artículo')) {
        await sleep(300); fillRefContenido('Título del artículo', ref.article_title, 'last');
      }
    }

    if (ref.url) {
      await clickCaja(detTitle);
      if (/^https?:\/\/(dx\.)?doi\.org\//.test(ref.url)) {
        if (await clickMenuButton('Identificador de la publicación')) {
          await sleep(300);
          setRefPubIdType('doi');
          fillRefContenido('Identificador de la publicación', ref.url, 'last');
        }
      } else if (await clickMenuButton('URL')) {
        await sleep(300); fillRefContenido('URL', ref.url, 'last');
      }
    }

    await clickRefClose();
    return true;
  }

  // ── Limpieza (antes en tools/limpiar_referencias.js, ahora unificado aquí) ──

  function refBoxes() {
    return [...document.querySelectorAll('[title="Referencia"]')]
      .filter((el) => el.offsetParent !== null);
  }

  // Mismo mecanismo que _delete_refs_but_one en references.py: hover para
  // revelar el botón "Cerrar" de esa caja puntual, después clickearlo.
  async function cerrarCaja(el) {
    el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    await sleep(150);
    const btn = el.querySelector('[title="Cerrar"]');
    if (!btn) return false;
    btn.click();
    await sleep(250);
    return true;
  }

  async function deleteRefsButOne() {
    const boxes = refBoxes();
    let count = 0;
    for (let i = boxes.length - 1; i >= 1; i--) {
      if (await cerrarCaja(boxes[i])) count++;
    }
    if (count) console.log(`Borradas ${count} referencias pre-existentes`);
    return count;
  }

  // Deja el artículo con UNA referencia nueva y vacía como punto de
  // partida limpio. La caja "Referencia" pre-creada por el portal NO se
  // deja borrar mientras sea la única presente, así que: borra todas
  // menos 1, agrega una nueva (ahora hay 2), borra la vieja (ahora sí se
  // deja). Devuelve una Promise -- awaitear antes de llenar nada encima.
  async function limpiarReferencias() {
    let boxes = refBoxes();
    console.log(`limpiarReferencias: referencias actuales: ${boxes.length}`);
    if (!boxes.length) {
      console.warn('No se encontró ninguna caja "Referencia" visible — '
        + '¿estás en la pestaña Referencias con los modales cerrados?');
      return false;
    }

    await deleteRefsButOne();
    await sleep(300);
    boxes = refBoxes();
    if (boxes.length !== 1) {
      console.warn(`Se esperaba 1 referencia tras borrar, quedaron ${boxes.length}`);
    }
    const vieja = boxes[0] || null;

    if (!(await clickCaja('Referencias'))) return false;
    if (!(await clickMenuButton('Referencia'))) return false;
    await sleep(500);

    if (vieja) {
      const ok = await cerrarCaja(vieja);
      if (!ok) console.warn('No se pudo cerrar la referencia vieja (¿ya no tiene botón Cerrar?)');
    }
    await sleep(300);

    boxes = refBoxes();
    if (boxes.length === 1) {
      console.log('limpiarReferencias: quedó 1 referencia nueva y limpia.');
    } else {
      console.warn(`limpiarReferencias: quedaron ${boxes.length} referencias — revisar a mano.`);
    }
    return boxes.length === 1;
  }

  // ── Punto de entrada ─────────────────────────────────────────────────

  async function probarReferencia(refs, opts = {}) {
    const { limpiar = true, guardar = false } = opts;

    if (limpiar) {
      const ok = await limpiarReferencias();
      if (!ok) console.warn('limpiarReferencias no terminó limpio — se continúa igual, revisa el estado a mano.');
    }

    for (let i = 0; i < refs.length; i++) {
      const ref = refs[i];
      const surname = ref.authors && ref.authors[0] ? ref.authors[0].surname : '(inst.)';
      console.log(`[${i + 1}/${refs.length}] ${surname} (${ref.year}) [${ref.pub_type}]`);

      if (i > 0) {
        await clickCaja('Referencias');
        if (!(await clickMenuButton('Referencia'))) {
          console.warn(`No se pudo crear la referencia ${i + 1}`);
          continue;
        }
        await sleep(500);
      }

      await fillSingleReference(ref);
      await sleep(300);
    }

    if (guardar) {
      const saved = (() => {
        for (const sel of ['#save-526564616c7963\\:buttonS', 'input[value="Guardar"]']) {
          try {
            const el = document.querySelector(sel);
            if (el && el.offsetParent) { el.click(); return true; }
          } catch (e) { /* selector inválido en este DOM, seguir probando */ }
        }
        for (const btn of document.querySelectorAll('input[type="button"], button')) {
          if ((btn.value || btn.innerText || '').trim() === 'Guardar' && btn.offsetParent) {
            btn.click(); return true;
          }
        }
        return false;
      })();
      console.log(saved ? 'Guardado' : 'No se encontró botón Guardar');
    } else {
      console.log('Sin guardar:true — nada se persistió. Revisa y decide a mano.');
    }
    console.log('Listo.');
  }

  window.probarReferencia = probarReferencia;
  window.limpiarReferencias = limpiarReferencias;
  window.REFS_PRUEBA = REFS_PRUEBA;

  console.log(
    '%cprobarReferencia() cargado (limpia y prueba automático). '
    + 'Ejecuta: probarReferencia(REFS_PRUEBA)',
    'color: green; font-weight: bold',
  );
})();
