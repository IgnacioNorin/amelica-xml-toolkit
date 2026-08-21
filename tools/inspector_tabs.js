// Pegar en la consola con el editor de un artículo abierto (en cualquier
// pestaña). Lista TODOS los elementos con clase "tab-..." visibles (no
// solo <a> -- la pestaña ACTIVA es un <div>, no un link, confirmado
// 2026-08-21 con "Datos del artículo") con su tag/id/class/texto, para
// confirmar el texto real de cada pestaña (Datos del artículo,
// Referencias/apéndices, Texto completo, Datos abiertos, etc.) y que
// _click_tab() no dependa de adivinar.

(() => {
  const tabs = [...document.querySelectorAll('[class*="tab-"]')]
    .filter(el => el.offsetParent !== null);
  if (!tabs.length) {
    console.log('No se encontró ningún elemento con clase "tab-" visible.');
  }
  tabs.forEach(el => {
    console.log({
      tag: el.tagName,
      id: el.id || null,
      class: el.className || null,
      activa: /tabSeleccionado/i.test(el.className),
      text: (el.innerText || '').trim(),
    });
  });
})();
