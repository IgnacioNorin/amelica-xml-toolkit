// grabador_referencias.js — grabadora de la pestaña "Referencias" del
// portal AmeliCA, para verificar contra el portal real los selectores
// que amelica/portal/references.py asume (hardcodeados, escritos sin
// verificar en vivo contra el DOM real).
//
// Uso: pegar en la consola del navegador (F12) DESPUES de entrar a la
// pestaña "Referencias" de un articulo (idealmente uno de prueba, no uno
// real -- el llenado de referencias en el portal borra las
// preexistentes). Cerrar los modales que aparezcan a mano como siempre.
//
// Completar UNA referencia entera a mano (tipo de publicacion, autores,
// año, fuente, titulo del articulo, volumen, numero, paginas, URL) y
// clickear Guardar. El script registra cada interaccion relevante --
// clicks en cajas con [title], cambios en <select>, texto tipeado en
// span[contenteditable], clicks en botones de menu -- con el
// title/id/class real del elemento tocado.
//
// Al terminar, correr en la consola:
//     copy(window.__log)
// Eso copia el registro completo (JSON) al portapapeles.
//
// Historial: usado el 2026-08-20 para confirmar que el campo Año en
// realidad es un select[class*="iso-8601-date-"] (no un span editable
// como asumia _fill_ref_year en ese momento) -- ver el comentario al
// inicio de references.py.

(() => {
  window.__log = [];
  const t0 = performance.now();
  const push = (tipo, info) => {
    const entry = { t: +((performance.now() - t0) / 1000).toFixed(1), tipo, ...info };
    window.__log.push(entry);
    console.log(`[+${entry.t}s] ${tipo}:`, info);
  };

  const describe = (el) => {
    if (!el) return null;
    const withTitle = el.closest('[title]');
    return {
      tag: el.tagName,
      id: el.id || null,
      title: withTitle ? withTitle.getAttribute('title') : null,
      class: el.className || null,
      text: (el.innerText || el.value || '').trim().slice(0, 80),
    };
  };

  // 1. Clicks en cualquier caja con [title] (el patron que usa AmeliCA
  //    para las cajas editables de Referencia detallada).
  document.addEventListener('click', (e) => {
    const caja = e.target.closest('[title]');
    if (caja) push('CLICK', describe(e.target));
  }, true);

  // 2. Cambios en <select> (tipo de publicacion, año, idioma, etc.)
  document.addEventListener('change', (e) => {
    if (e.target.tagName === 'SELECT') {
      const opt = e.target.options[e.target.selectedIndex];
      push('SELECT', { ...describe(e.target), value: e.target.value, opcion: opt ? opt.text : null });
    }
  }, true);

  // 3. Texto tipeado en span[contenteditable] -- se loguea en blur (cuando
  //    se termina de tipear ahi), no en cada tecla.
  document.addEventListener('focusout', (e) => {
    if (e.target.isContentEditable) {
      push('TEXTO', { ...describe(e.target), valor_final: e.target.innerText.trim() });
    }
  }, true);

  // 4. Cualquier boton/link clickeado con texto visible (menus "Agregar
  //    Volumen", "Agregar Número", Guardar, etc.) -- sin filtro de
  //    palabras clave, para no perderse ninguno como paso la primera vez.
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('button, input[type="button"], input[type="submit"], a');
    if (btn) {
      const label = (btn.innerText || btn.value || '').trim();
      if (label) push('BOTON', { label, id: btn.id || null });
    }
  }, true);

  console.log('%c🎥 Grabador de Referencias activo. Completá UNA referencia a mano y después corré: copy(window.__log)', 'color: green; font-weight: bold');
})();
