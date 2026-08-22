// grabar_estado_referencia_limpia.js — vuelca el HTML real de la caja
// "Referencia" limpia (vacía, recién creada) que deja
// limpiarReferencias() (en tools/probar_referencia.js), para tener
// documentado el "punto de partida": cómo es el DOM ANTES de llenar
// nada. Sirve para comparar después de ejecutar probar_referencia.js y
// ver qué cambió campo por campo, o para escribir selectores nuevos sin
// adivinar.
//
// Uso:
//   1. Ejecutar limpiarReferencias() primero (debe quedar exactamente 1
//      caja "Referencia" visible y vacía).
//   2. Pegar este script en la consola (F12) y Enter.
//   3. Ejecutar en la consola:
//        copy(window.__estadoLimpio.html)
//      Eso copia el HTML al portapapeles. Pégalo en un archivo (ej.
//      tools/fixtures/referencia_vacia.html) para dejarlo en el repo.
//      También puedes ejecutar:
//        copy(JSON.stringify(window.__estadoLimpio, null, 2))
//      para copiar todo, con el mapa de campos [title] incluido.

(() => {
  function refBoxes() {
    return [...document.querySelectorAll('[title="Referencia"]')]
      .filter((el) => el.offsetParent !== null);
  }

  const boxes = refBoxes();
  if (boxes.length !== 1) {
    console.warn(
      `Se esperaba exactamente 1 caja "Referencia" visible (encontradas: ${boxes.length}). `
      + 'Ejecuta limpiarReferencias() primero si hace falta.',
    );
  }
  const caja = boxes[boxes.length - 1];
  if (!caja) {
    console.error('No se encontró ninguna caja "Referencia" -- ¿estás en la pestaña Referencias?');
    return;
  }

  // Todos los [title] dentro de la caja: mapa rápido de qué campos existen
  // y con qué title= identificarlos (lo mismo que usan _click_caja /
  // _fill_ref_contenido para apuntar a cada uno).
  const camposConTitle = [...caja.querySelectorAll('[title]')].map((el) => ({
    title: el.getAttribute('title'),
    tag: el.tagName,
    class: (el.className || '').toString().slice(0, 80),
    contenteditable: el.querySelector('[contenteditable="true"]') !== null,
  }));

  window.__estadoLimpio = {
    timestamp: new Date().toISOString(),
    html: caja.outerHTML,
    campos: camposConTitle,
  };

  console.log(
    `Estado capturado (${caja.outerHTML.length} chars de HTML, ${camposConTitle.length} campos con [title]).`,
  );
  console.table(camposConTitle);
  console.log(
    '%cEjecuta: copy(window.__estadoLimpio.html)  para copiar el HTML al portapapeles.',
    'color: green; font-weight: bold',
  );
  console.log(
    '%c    o: copy(JSON.stringify(window.__estadoLimpio, null, 2))  para copiar todo (con el mapa de campos).',
    'color: green; font-weight: bold',
  );
})();
