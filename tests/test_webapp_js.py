"""
test_webapp_js.py — Tests de la lógica JS embebida en amelica/idml/webapp.py.

tests/test_webapp.py cubre el lado Flask (endpoints); esto cubre el lado
del navegador, que hasta ahora no tenía NADA de verificación automática
(solo `node --check` a mano durante el desarrollo). No se agrega ningún
framework de testing de JS -- se corre el <script> real, extraído de
INDEX_HTML, con Node y un DOM mínimo simulado a mano, y se le pide que
imprima un JSON con el resultado que interesa verificar. Es más manual
que usar jsdom/jest, pero no agrega dependencias nuevas al proyecto (que
hoy no tiene ningún toolchain de JS -- ni package.json).

Se saltea limpio si falta flask (INDEX_HTML se renderiza con
render_template_string, igual que test_webapp.py) o si no está instalado
Node.

IMPORTANTE: el <script> se extrae del HTML ya RENDERIZADO (vía
app.test_client()), no de la plantilla cruda -- INDEX_HTML tiene una
expresión Jinja (`{{ 'true' if auto_apagar else 'false' }}` para
AUTO_APAGAR, ver el apagado automático al cerrar la pestaña) que Node no
puede parsear como JS si no se resuelve primero.

El script real corre COMPLETO al cargarlo (incluye el cableado de
eventos y las llamadas de arranque `cargarHistorial()` /
`reconciliarTrabajosActivos()`), así que el DOM simulado tiene que ser lo
bastante permisivo para que esas llamadas no revienten -- ver
_PREAMBULO_DOM. No se verifica ese cableado en sí (requeriría un DOM de
verdad, tipo jsdom); lo que se verifica acá son las funciones puras o
casi puras que sí importa proteger de una regresión silenciosa:
parsearEtapas, renderEtapasDesdeResultados, moverItemAPosicion/
renumerarItems.
"""

import json
import re
import shutil
import subprocess

import pytest

flask = pytest.importorskip("flask")

from amelica.idml.webapp import app  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js no está instalado"
)

_html_renderizado = app.test_client().get("/").get_data(as_text=True)
_m = re.search(r"<script>(.*)</script>", _html_renderizado, re.S)
assert _m, "No se encontró el bloque <script> en INDEX_HTML -- ¿cambió la estructura del HTML?"
SCRIPT_JS = _m.group(1)

# DOM mínimo simulado: getElementById devuelve, para CUALQUIER id, un
# elemento genérico permisivo (no revienta con .addEventListener,
# .classList, etc.) -- salvo que un test lo pise a propósito ANTES de
# ejecutar su parte, vía __elementos['algun-id'] = ... (ver los tests
# de moverItemAPosicion más abajo). fetch() se stubea para devolver
# siempre {} -- alcanza para que cargarHistorial()/
# reconciliarTrabajosActivos() (llamadas al final del script real) no
# rompan nada, ya que ambas manejan datos ausentes con `|| []`/`|| {}`.
_PREAMBULO_DOM = r"""
'use strict';
const __elementos = {};
function __crearElemento() {
  let _texto = '';
  const el = {
    className: '', dataset: {}, value: '', style: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, force) {
        const on = force === undefined ? !this._set.has(c) : force;
        if (on) this._set.add(c); else this._set.delete(c);
        return on;
      },
      contains(c) { return this._set.has(c); },
    },
    addEventListener() {},
    closest() { return __crearElemento(); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    appendChild(x) { return x; },
    insertBefore(x) { return x; },
    remove() {},
    click() {},
    focus() {},
    dispatchEvent() {},
    scrollIntoView() {},
    innerHTML: '',
    get textContent() { return _texto; },
    set textContent(v) {
      _texto = v;
      this.innerHTML = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  };
  return el;
}
global.document = {
  getElementById(id) {
    if (!__elementos[id]) __elementos[id] = __crearElemento();
    return __elementos[id];
  },
  querySelectorAll() { return []; },
  createElement() { return __crearElemento(); },
};
global.window = global;
global.performance = { now: () => Date.now() };
global.fetch = async () => ({ json: async () => ({}) });
"""


def _correr_js(arnes: str, tmp_path) -> dict:
    """Concatena el DOM simulado + el <script> real + el arnes de prueba,
    lo corre con node, y parsea la ÚLTIMA línea de stdout como JSON (el
    arnes tiene que terminar con exactamente un console.log(JSON.stringify(...)))."""
    contenido = _PREAMBULO_DOM + "\n\n" + SCRIPT_JS + "\n\n" + arnes
    archivo = tmp_path / "arnes.js"
    archivo.write_text(contenido, encoding="utf-8")
    resultado = subprocess.run(
        ["node", str(archivo)], capture_output=True, timeout=15,
        stdin=subprocess.DEVNULL,
        # Se pide bytes crudos (sin text=True/encoding=) y se decodifica
        # a mano como UTF-8 abajo: Node escribe stdout/stderr en UTF-8
        # siempre, pero text=True en Windows decodifica con el encoding
        # por defecto de la plataforma (cp1252) y corrompe cualquier
        # tilde/ñ del JSON de salida. stdin=DEVNULL evita heredar un
        # handle de stdin raro bajo Git Bash/MSYS que en este entorno
        # tira OSError (WinError 6, "Controlador no válido") al armar
        # el subproceso.
    )
    stdout = resultado.stdout.decode("utf-8", errors="replace")
    stderr = resultado.stderr.decode("utf-8", errors="replace")
    assert resultado.returncode == 0, (
        f"node terminó con error (código {resultado.returncode}).\n"
        f"stdout:\n{stdout}\nstderr:\n{stderr}"
    )
    lineas = [l for l in stdout.splitlines() if l.strip()]
    assert lineas, f"node no imprimió nada. stderr:\n{stderr}"
    return json.loads(lineas[-1])


def test_el_script_carga_sin_reventar(tmp_path):
    """Guarda mínima: si el <script> tiene un error de sintaxis o el
    cableado de arranque revienta contra un DOM vacío, esto ya lo
    detecta antes de llegar a ningún test más específico."""
    resultado = _correr_js("console.log(JSON.stringify({ok: true}));", tmp_path)
    assert resultado == {"ok": True}


# ── parsearEtapas ────────────────────────────────────────────────────
# Réplica en JS de _parsear_etapas() (amelica/idml/webapp.py, lado
# Python) -- las dos leen el mismo formato "##ETAPA## nombre|ok/fail|
# detalle" que emite AmelicaUploader._step(). Están para verificar que
# no se desincronizan entre sí con el tiempo.

def test_parsear_etapas_lineas_normales(tmp_path):
    driver = r"""
    const log = [
      '##ETAPA## login|ok|',
      '##ETAPA## issue|ok|',
      '##ETAPA## marker|fail|no se pudo guardar',
    ].join('\n');
    console.log(JSON.stringify(parsearEtapas(log)));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {
        "login": {"ok": True, "detalle": ""},
        "issue": {"ok": True, "detalle": ""},
        "marker": {"ok": False, "detalle": "no se pudo guardar"},
    }


def test_parsear_etapas_la_ultima_ocurrencia_gana(tmp_path):
    driver = r"""
    const log = [
      '##ETAPA## zip|ok|sin confirmación del servidor',
      '##ETAPA## zip|fail|sin confirmación y el editor no cargó',
    ].join('\n');
    console.log(JSON.stringify(parsearEtapas(log)));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado["zip"] == {
        "ok": False, "detalle": "sin confirmación y el editor no cargó",
    }


def test_parsear_etapas_ignora_ruido(tmp_path):
    driver = r"""
    const log = 'esto no es una etapa\n##ETAPA## incompleta\n';
    console.log(JSON.stringify(parsearEtapas(log)));
    """
    assert _correr_js(driver, tmp_path) == {}


# ── renderEtapasDesdeResultados ──────────────────────────────────────

def test_render_etapas_solo_una_en_curso(tmp_path):
    """login/issue/article/zip ya resueltos, marker es la primera SIN
    resultado con terminado=false -> tiene que ser la única 'en curso';
    front_matter/references (más atrás, también sin resultado) tienen
    que quedar 'pendiente', no 'en curso' también."""
    driver = r"""
    const resultados = {
      login: {ok: true, detalle: ''},
      issue: {ok: true, detalle: ''},
      article: {ok: true, detalle: ''},
      zip: {ok: true, detalle: ''},
    };
    renderEtapasDesdeResultados(resultados, false);
    const html = document.getElementById('etapas').innerHTML;
    const cursos = (html.match(/etapa curso/g) || []).length;
    const pendientes = (html.match(/etapa pendiente/g) || []).length;
    const hechos = (html.match(/etapa hecho/g) || []).length;
    console.log(JSON.stringify({cursos, pendientes, hechos, orden_marker_antes_de_front: html.indexOf('Marcaje de secciones') < html.indexOf('Datos del artículo')}));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {
        "cursos": 1, "pendientes": 3, "hechos": 4,
        "orden_marker_antes_de_front": True,
    }


def test_render_etapas_terminado_no_muestra_curso(tmp_path):
    """Si el trabajo ya terminó (falló en una etapa crítica temprana),
    todo lo que no llegó a correr debe quedar 'pendiente', nunca 'en
    curso' -- no hay nada corriendo de verdad."""
    driver = r"""
    const resultados = {
      login: {ok: true, detalle: ''},
      issue: {ok: false, detalle: 'no se detectaron números'},
    };
    renderEtapasDesdeResultados(resultados, true);
    const html = document.getElementById('etapas').innerHTML;
    console.log(JSON.stringify({
      cursos: (html.match(/etapa curso/g) || []).length,
      pendientes: (html.match(/etapa pendiente/g) || []).length,
      fallos: (html.match(/etapa fallo/g) || []).length,
      tiene_detalle: html.includes('no se detectaron números'),
    }));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {"cursos": 0, "pendientes": 6, "fallos": 1, "tiene_detalle": True}


def test_render_etapas_todas_completas(tmp_path):
    driver = r"""
    const nombres = ['login','issue','article','zip','marcar','marker','front_matter','references'];
    const resultados = {};
    nombres.forEach(n => resultados[n] = {ok: true, detalle: ''});
    renderEtapasDesdeResultados(resultados, true);
    const html = document.getElementById('etapas').innerHTML;
    console.log(JSON.stringify({
      hechos: (html.match(/etapa hecho/g) || []).length,
      cursos: (html.match(/etapa curso/g) || []).length,
      pendientes: (html.match(/etapa pendiente/g) || []).length,
    }));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {"hechos": 8, "cursos": 0, "pendientes": 0}


def test_render_etapas_escapa_html_del_detalle(tmp_path):
    """El detalle viene del log real (puede incluir texto arbitrario de
    un error) -- no debe poder inyectar HTML en el panel."""
    driver = r"""
    const resultados = { login: {ok: false, detalle: '<img src=x onerror=alert(1)>'} };
    renderEtapasDesdeResultados(resultados, true);
    const html = document.getElementById('etapas').innerHTML;
    console.log(JSON.stringify({
      sin_tag_crudo: !html.includes('<img src=x'),
      con_texto_escapado: html.includes('&lt;img'),
    }));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {"sin_tag_crudo": True, "con_texto_escapado": True}


# ── moverItemAPosicion / renumerarItems ──────────────────────────────
# Necesitan un #items con hijos de verdad (appendChild que reordena, no
# duplica) -- se pisa el elemento genérico de '#items' por uno que
# lleva un array real, y cada "item" simulado expone su propio
# .pos-input vía querySelector.

_DRIVER_ITEMS = r"""
function crearItemFalso(nombre) {
  const posInput = { value: '' };
  return {
    _nombre: nombre,
    _posInput: posInput,
    querySelector(sel) { return sel === '.pos-input' ? posInput : null; },
  };
}
const a = crearItemFalso('a'), b = crearItemFalso('b'), c = crearItemFalso('c');
let _hijos = [a, b, c];
__elementos['items'] = {
  get children() { return _hijos.slice(); },
  appendChild(el) {
    const i = _hijos.indexOf(el);
    if (i !== -1) _hijos.splice(i, 1);
    _hijos.push(el);
    return el;
  },
};
"""


def test_mover_item_a_posicion_al_frente(tmp_path):
    driver = _DRIVER_ITEMS + r"""
    moverItemAPosicion(c, 1);   // mover 'c' (última) al frente
    console.log(JSON.stringify({
      orden: __elementos['items'].children.map(x => x._nombre),
      posiciones: __elementos['items'].children.map(x => x._posInput.value),
    }));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {"orden": ["c", "a", "b"], "posiciones": [1, 2, 3]}


def test_mover_item_posicion_fuera_de_rango_se_acota(tmp_path):
    """Pedir la posición 99 en una lista de 3 no debe reventar ni sacar
    el item de la lista -- se acota al último lugar válido."""
    driver = _DRIVER_ITEMS + r"""
    moverItemAPosicion(a, 99);
    console.log(JSON.stringify({
      orden: __elementos['items'].children.map(x => x._nombre),
    }));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {"orden": ["b", "c", "a"]}


def test_renumerar_items_refleja_orden_real(tmp_path):
    driver = _DRIVER_ITEMS + r"""
    _hijos = [c, a, b];   // reordenados "a mano", como haría un drag & drop
    renumerarItems();
    console.log(JSON.stringify({
      posiciones: { c: c._posInput.value, a: a._posInput.value, b: b._posInput.value },
    }));
    """
    resultado = _correr_js(driver, tmp_path)
    assert resultado == {"posiciones": {"c": 1, "a": 2, "b": 3}}
