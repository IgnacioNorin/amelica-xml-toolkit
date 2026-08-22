#!/usr/bin/env python3
"""
app.py — Pequeña web local para convertir archivos .idml a index.zip
(listos para AmeliCA) y subirlos directamente al portal.

Uso:
    python -m amelica.idml.webapp
    (despues abrir http://localhost:5000 en el navegador)

Requiere: flask, Pillow (pip install flask Pillow)
tkinter viene incluido con Python en Windows/Mac; en Linux puede
necesitar instalarse aparte (ej: sudo apt install python3-tk).

Credenciales: se cargan desde la web y quedan SOLO en la memoria de este
proceso (nunca se escriben en credentials.json ni en ningún otro archivo).
Se pasan al subproceso de subida por variable de entorno, que es lo que
amelica.config.load_credentials() ya prioriza por sobre el archivo. Si
cierras este servidor (Ctrl+C) o recargas sin volver a cargarlas, se
pierden solas — no hay nada que "limpiar" en disco.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

# En Windows, cuando stdout no es una consola UTF-8 (cp1252 por default),
# los print() con emoji de converter.py y del subproceso de subida revientan
# con UnicodeEncodeError. Forzarlo aquí evita que dependa de que quien lo
# ejecute sepa poner PYTHONIOENCODING=utf-8 a mano.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, request, jsonify, render_template_string

from .converter import build_index_zip
from ..config import PROJECT_ROOT

app = Flask(__name__)

# ── Credenciales: solo en memoria de este proceso ──────────────────────
CREDENCIALES = {"email": "", "password": "", "volume": ""}

# ── Trabajos de subida en curso/terminados: id -> estado ───────────────
TRABAJOS = {}
TRABAJOS_LOCK = threading.Lock()


# ── Historial de subidas: persiste en disco (a diferencia de TRABAJOS,
# que se pierde al reiniciar el servidor). Un JSON por línea, uno por
# trabajo terminado -- se abre en modo "append", nunca se reescribe
# entero, así que una corrida larga no se cae por un archivo gigante a
# reescribir. Vive junto a credentials.json, mismo criterio de
# .gitignore (no son secretos, pero son datos locales de esta máquina).
HISTORIAL_FILE = PROJECT_ROOT / "historial_subidas.jsonl"

_ETAPA_RE = re.compile(r"^##ETAPA## ([a-z_]+)\|(ok|fail)\|(.*)$")


def _parsear_etapas(log: str) -> dict:
    """Extrae las líneas '##ETAPA## nombre|ok/fail|detalle' que emite
    AmelicaUploader._step() (amelica/portal/uploader.py) del log crudo de
    un trabajo. Si una etapa aparece más de una vez (ej. 'zip', que puede
    reportarse primero de forma optimista y corregirse después via
    _confirmar_zip_por_marcaje), gana la última ocurrencia -- es la más
    reciente y la más precisa."""
    resultados = {}
    for linea in (log or "").splitlines():
        m = _ETAPA_RE.match(linea.strip())
        if m:
            resultados[m.group(1)] = {"ok": m.group(2) == "ok", "detalle": m.group(3)}
    return resultados


def _registrar_historial(zip_path: str, ok: bool, log: str) -> None:
    """Agrega una línea al historial persistente. No debe poder tirar
    abajo la subida si falla (ej. disco lleno, permisos) -- se avisa por
    consola y se sigue, nunca se propaga la excepción."""
    entrada = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "zip_path": zip_path,
        "ok": ok,
        "etapas": _parsear_etapas(log),
    }
    try:
        with open(HISTORIAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"No se pudo escribir el historial de subidas: {e}")

INDEX_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>IDML a AmeliCA</title>
<style>
  :root {
    --bg: #f4f6fb;
    --card-bg: #ffffff;
    --text: #1e293b;
    --text-muted: #64748b;
    --border: #e2e8f0;
    --primary: #2563eb;
    --primary-dark: #1d4ed8;
    --success: #16a34a;
    --success-dark: #15803d;
    --purple: #7c3aed;
    --purple-dark: #6d28d9;
    --radius: 12px;
    --shadow: 0 1px 3px rgba(15, 23, 42, .06), 0 1px 2px rgba(15, 23, 42, .04);
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 0; color: var(--text); background: var(--bg); line-height: 1.5;
  }

  .pagina { max-width: 1400px; margin: 0 auto; padding: 48px 20px 60px; }
  .encabezado { margin-bottom: 24px; }
  h1 { font-size: 1.5rem; font-weight: 700; margin: 0 0 4px; }
  .subtitulo { color: var(--text-muted); font-size: .92rem; }

  .layout {
    display: flex; align-items: flex-start; gap: 24px;
    counter-reset: paso;
  }
  .sidebar { flex: 0 0 400px; min-width: 320px; max-width: 460px; }

  .tarjeta {
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: var(--radius); box-shadow: var(--shadow);
    padding: 24px; margin-top: 20px;
  }
  .tarjeta h2 {
    font-size: 1rem; font-weight: 700; margin: 0 0 18px;
    display: flex; align-items: center; gap: 10px;
    cursor: pointer; user-select: none;
  }
  .tarjeta h2::before {
    counter-increment: paso; content: counter(paso);
    display: inline-flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
    background: var(--primary); color: white; font-size: .8rem; font-weight: 700;
  }
  .tarjeta h2 .chev {
    margin-left: auto; font-size: .75rem; color: var(--text-muted);
    transition: transform .15s;
  }
  .tarjeta.colapsada h2 { margin-bottom: 0; }
  .tarjeta.colapsada h2 .chev { transform: rotate(-90deg); }
  .tarjeta.colapsada .tarjeta-cuerpo { display: none; }
  .cola-nota { font-weight: normal; font-size: .78rem; color: var(--text-muted); }

  .panel-estado {
    flex: 1; min-width: 0; position: sticky; top: 48px;
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: var(--radius); box-shadow: var(--shadow);
    padding: 24px; display: flex; flex-direction: column;
    max-height: calc(100vh - 96px);
  }
  .panel-estado h2 { font-size: 1rem; font-weight: 700; margin: 0 0 4px; }
  .panel-titulo {
    font-size: .82rem; color: var(--text-muted); margin-bottom: 18px;
    word-break: break-all; padding-bottom: 14px; border-bottom: 1px solid var(--border);
  }

  /* Progreso por etapa: línea de tiempo vertical, sin iconos -- un punto
     de estado por etapa unido por una guía, como un checklist de CI. */
  .etapas { display: flex; flex-direction: column; overflow-y: auto; }
  .etapa { display: flex; align-items: flex-start; gap: 12px; padding: 9px 0; position: relative; }
  .etapa:not(:last-child)::after {
    content: ''; position: absolute; left: 5px; top: 25px; bottom: -3px;
    width: 2px; background: var(--border);
  }
  .etapa .punto {
    width: 12px; height: 12px; border-radius: 50%; margin-top: 4px; flex-shrink: 0;
    background: var(--bg); border: 2px solid var(--border); position: relative; z-index: 1;
  }
  .etapa.hecho .punto { background: var(--success); border-color: var(--success); }
  .etapa.fallo .punto { background: #dc2626; border-color: #dc2626; }
  .etapa.curso .punto { background: var(--primary); border-color: var(--primary); animation: pulso 1.4s ease-in-out infinite; }
  @keyframes pulso {
    0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, .35); }
    50%      { box-shadow: 0 0 0 5px rgba(37, 99, 235, 0); }
  }
  .etapa .info { flex: 1; min-width: 0; }
  .etapa .etiqueta { font-size: .88rem; font-weight: 600; }
  .etapa.pendiente .etiqueta { color: var(--text-muted); font-weight: 500; }
  .etapa .detalle { font-size: .78rem; color: var(--text-muted); margin-top: 2px; }
  .etapa.fallo .detalle { color: #b91c1c; }
  .etapa .estado-txt { font-size: .74rem; color: var(--text-muted); flex-shrink: 0; margin-top: 3px; }
  .etapa.hecho .estado-txt { color: var(--success-dark); }
  .etapa.fallo .estado-txt { color: #b91c1c; }
  .etapa.curso .estado-txt { color: var(--primary); font-weight: 600; }

  .panel-log-toggle { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); flex-shrink: 0; }
  .panel-log-toggle button {
    background: none; border: none; color: var(--text-muted); font-size: .78rem;
    padding: 0; font-weight: 600; cursor: pointer;
  }
  .panel-log-toggle button:hover { color: var(--primary); }
  .log-crudo {
    display: none; margin-top: 10px; background: #f8fafc; border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 14px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .74rem;
    color: var(--text-muted); white-space: pre-wrap; max-height: 220px; overflow-y: auto;
  }
  .log-crudo.visible { display: block; }

  .campo { margin-bottom: 18px; }
  .campo:last-child { margin-bottom: 0; }
  label { display: block; margin-bottom: 6px; font-weight: 600; font-size: .88rem; }
  input[type=file], input[type=text], input[type=password] {
    display: block; width: 100%; padding: 9px 11px;
    border: 1px solid var(--border); border-radius: 8px; font-size: .92rem;
    background: #fbfcfe; transition: border-color .15s;
  }
  input[type=file]:focus, input[type=text]:focus, input[type=password]:focus {
    outline: none; border-color: var(--primary); background: white;
  }

  button {
    padding: 9px 16px; border-radius: 8px; border: 1px solid var(--border);
    background: #f8fafc; cursor: pointer; font-size: .9rem; font-weight: 600;
    transition: background .15s, transform .05s;
  }
  button:hover { background: #eef2f7; }
  button:active { transform: scale(.98); }
  button:disabled { opacity: .55; cursor: not-allowed; transform: none; }

  #convertir, #guardar-credenciales { background: var(--primary); color: white; border: none; }
  #convertir:hover, #guardar-credenciales:hover { background: var(--primary-dark); }
  #convertir:disabled { background: #93c5fd; }

  .subir-btn { background: var(--success); color: white; border: none; }
  .subir-btn:hover { background: var(--success-dark); }
  .subir-btn:disabled { background: #86efac; }

  #lote-btn { background: var(--purple); color: white; border: none; }
  #lote-btn:hover { background: var(--purple-dark); }
  #lote-btn:disabled { background: #c4b5fd; }

  #carpeta-elegida { margin-top: 8px; font-size: .85rem; color: var(--text-muted); word-break: break-all; }

  .estado { margin-top: 16px; padding: 12px 14px; border-radius: 8px; display: none; font-size: .88rem; }
  .estado.ok { background: #dcfce7; color: #166534; display: block; }
  .estado.error { background: #fee2e2; color: #991b1b; display: block; }
  .estado.trabajando { background: #fef9c3; color: #713f12; display: block; }
  .creds-estado { font-size: .82rem; margin-top: 10px; color: var(--text-muted); }

  .item {
    border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-top: 10px;
    display: flex; align-items: flex-start; gap: 10px; background: #fbfcfe;
    transition: border-color .15s;
  }
  .item:hover { border-color: #cbd5e1; }
  .item.arrastrando { opacity: .4; }
  .item.en-cola-encima { border-top: 3px solid var(--primary); }
  .item.activo-panel { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary); }
  .item .pos-input {
    width: 40px; text-align: center; padding: 4px 2px; font-size: .85rem;
    font-weight: 700; color: var(--primary); border: 1px solid var(--border);
    border-radius: 6px; flex-shrink: 0; margin-top: 1px;
  }
  .item .asa { cursor: grab; color: #94a3b8; font-size: 1.1rem; padding-top: 3px; user-select: none; flex-shrink: 0; }
  .item .cuerpo { flex: 1; min-width: 0; }
  .item .nombre { word-break: break-all; font-size: .88rem; cursor: pointer; }
  .item .nombre:hover { color: var(--primary); }
  .item .fila-botones { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .badge { font-size: .72rem; padding: 3px 9px; border-radius: 20px; background: #f1f5f9; color: #475569; font-weight: 600; }
  .badge.ok { background: #dcfce7; color: #166534; }
  .badge.error { background: #fee2e2; color: #991b1b; }
  .badge.trabajando { background: #fef9c3; color: #713f12; }
  .quitar-btn { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 1rem; padding: 2px 6px; }
  .quitar-btn:hover { color: #dc2626; }

  .toggle-nav { display: flex; align-items: center; gap: 8px; font-size: .88rem;
                margin-top: 14px; font-weight: normal; }
  .lote-barra { display: flex; align-items: center; gap: 10px; margin-top: 18px; }

  .hist-item {
    display: flex; align-items: center; gap: 10px; padding: 10px 0;
    border-bottom: 1px solid var(--border); cursor: pointer;
  }
  .hist-item:last-child { border-bottom: none; }
  .hist-item:hover .hist-nombre { color: var(--primary); }
  .hist-item .hist-info { flex: 1; min-width: 0; }
  .hist-item .hist-nombre { font-size: .85rem; word-break: break-all; }
  .hist-item .hist-fecha { font-size: .74rem; color: var(--text-muted); margin-top: 2px; }
</style>
</head>
<body>
  <div class="pagina">
    <header class="encabezado">
      <h1>Convertir .idml a AmeliCA</h1>
      <div class="subtitulo">Convierte artículos de InDesign y súbelos al portal, todo desde aquí.</div>
    </header>

    <div class="layout">
    <div class="sidebar">
      <div class="tarjeta" id="tarjeta-credenciales">
        <h2>Credenciales (solo para esta sesión) <span class="chev">▾</span></h2>
        <div class="tarjeta-cuerpo">
          <div class="campo">
            <label for="cred-email">Email AmeliCA XML</label>
            <input type="text" id="cred-email" autocomplete="off">
          </div>
          <div class="campo">
            <label for="cred-password">Contraseña</label>
            <input type="password" id="cred-password" autocomplete="off">
          </div>
          <div class="campo">
            <label for="cred-volume">Volumen (ej: "38 (1)")</label>
            <input type="text" id="cred-volume" autocomplete="off">
          </div>
          <button id="guardar-credenciales">Guardar para esta sesión</button>
          <div class="creds-estado" id="creds-estado">
            No se guardan en ningún archivo — quedan en memoria mientras este
            servidor esté corriendo y se pierden si lo cierras.
          </div>
        </div>
      </div>

      <div class="tarjeta" id="tarjeta-convertir">
        <h2>Convertir artículos <span class="chev">▾</span></h2>
        <div class="tarjeta-cuerpo">
          <div class="campo">
            <label for="archivo">Archivos .idml (puedes elegir varios)</label>
            <input type="file" id="archivo" accept=".idml" multiple>
          </div>

          <div class="campo">
            <label>Carpeta padre de destino</label>
            <button type="button" id="elegir-carpeta">Elegir carpeta...</button>
            <div id="carpeta-elegida">(ninguna elegida — se usará la carpeta actual del servidor)</div>
          </div>

          <div class="campo" style="margin-top:16px;">
            <button id="convertir">Convertir</button>
          </div>
          <div id="estado-convertir" class="estado"></div>
        </div>
      </div>

      <div class="tarjeta" id="tarjeta-cola">
        <h2>Cola de subida <span class="chev">▾</span></h2>
        <div class="tarjeta-cuerpo">
          <div class="cola-nota" style="margin-bottom:14px;">
            Arrastra las tarjetas para reordenar, o escribe la posición.
          </div>
          <div class="campo">
            <button type="button" id="agregar-zip">Agregar ZIP ya hecho...</button>
            <button type="button" id="agregar-carpeta-zips">Agregar carpeta con varios artículos...</button>
            <div class="cola-nota" style="margin-top:6px;">
              El primer botón sirve para elegir uno o varios index.zip dentro de
              una misma carpeta. El segundo busca automáticamente todos los
              index.zip dentro de las subcarpetas de la carpeta que elijas (ej.
              una carpeta con una subcarpeta por artículo).
            </div>
          </div>

          <label class="toggle-nav">
            <input type="checkbox" id="ver-navegador" checked>
            Mostrar el navegador mientras sube (destilda para que corra oculto)
          </label>

          <label class="toggle-nav" title="Borra las referencias que el artículo ya tenga cargadas en el portal antes de escribir las nuevas.">
            <input type="checkbox" id="cargar-referencias">
            Cargar también las referencias (EXPERIMENTAL — borra las referencias preexistentes del artículo)
          </label>

          <div class="lote-barra">
            <button id="lote-btn">▶ Subir todo en orden</button>
            <span id="lote-estado" class="cola-nota"></span>
          </div>

          <div id="items"></div>
        </div>
      </div>

      <div class="tarjeta colapsada" id="tarjeta-historial">
        <h2>Historial de subidas <span class="chev">▾</span></h2>
        <div class="tarjeta-cuerpo">
          <div class="cola-nota" id="historial-vacio">Todavía no hay subidas registradas.</div>
          <div id="historial-lista"></div>
        </div>
      </div>
    </div>

    <div class="panel-estado">
      <h2>Progreso del artículo</h2>
      <div class="panel-titulo" id="panel-titulo">
        Ningún trabajo en curso — sube un artículo, o haz clic en el
        nombre de uno de la cola para ver su progreso.
      </div>
      <div class="etapas" id="etapas"></div>
      <div class="panel-log-toggle">
        <button type="button" id="toggle-log-crudo">Ver registro completo ▾</button>
        <pre class="log-crudo" id="log-crudo"></pre>
      </div>
    </div>
    </div>
  </div>

  <script>
    let carpetaDestino = "";

    // ── Tarjetas plegables: clic en el título expande/colapsa ────────
    document.querySelectorAll('.tarjeta > h2').forEach((h2) => {
      h2.addEventListener('click', () => {
        h2.closest('.tarjeta').classList.toggle('colapsada');
      });
    });

    // ── Panel de progreso compartido: uno solo, a la derecha ──────────
    // Todas las subidas lo comparten (nunca corren en paralelo -- ver
    // nota en el listener de #lote-btn), así que alcanza con guardar el
    // log crudo de cada item en memoria y mostrar el del que está activo.
    //
    // El log crudo se parsea buscando líneas "##ETAPA## nombre|ok/fail|detalle"
    // que emite AmelicaUploader._step() (amelica/portal/uploader.py) por
    // cada etapa completada, y con eso se arma una línea de tiempo de
    // progreso en vez de mostrar el texto crudo del subproceso. El mismo
    // orden y las mismas etiquetas que usa AmelicaUploader.print_summary().
    const ETAPAS = [
      ['login', 'Login'],
      ['issue', 'Selección del número'],
      ['article', 'Alta del artículo'],
      ['zip', 'Subida del ZIP'],
      ['marcar', 'Apertura del editor'],
      ['marker', 'Marcaje de secciones'],
      ['front_matter', 'Datos del artículo'],
      ['references', 'Referencias'],
    ];
    const RE_ETAPA = /^##ETAPA## ([a-z_]+)\\|(ok|fail)\\|(.*)$/;

    const logsPorItem = {};
    const idsEnCurso = new Set();
    let itemActivoId = null;

    function escaparHtml(texto) {
      const d = document.createElement('div');
      d.textContent = texto;
      return d.innerHTML;
    }

    function parsearEtapas(log) {
      const resultados = {};
      (log || '').split('\\n').forEach((linea) => {
        const m = RE_ETAPA.exec(linea.trim());
        if (m) resultados[m[1]] = { ok: m[2] === 'ok', detalle: m[3] };
      });
      return resultados;
    }

    function renderEtapas(log, terminado) {
      renderEtapasDesdeResultados(parsearEtapas(log), terminado);
    }

    // Separado de renderEtapas para poder reusarlo con resultados ya
    // parseados de antemano -- caso del historial, que los trae listos
    // desde el servidor (ver cargarHistorial) sin loguear texto crudo.
    function renderEtapasDesdeResultados(resultados, terminado) {
      let yaHayEnCurso = false;
      document.getElementById('etapas').innerHTML = ETAPAS.map(([clave, etiqueta]) => {
        let estado, textoEstado, detalle = '';
        if (resultados[clave]) {
          estado = resultados[clave].ok ? 'hecho' : 'fallo';
          textoEstado = resultados[clave].ok ? 'Completado' : 'Con problemas';
          detalle = resultados[clave].detalle;
        } else if (!terminado && !yaHayEnCurso) {
          yaHayEnCurso = true;
          estado = 'curso';
          textoEstado = 'En curso…';
        } else {
          estado = 'pendiente';
          textoEstado = 'Pendiente';
        }
        return `
          <div class="etapa ${estado}">
            <span class="punto"></span>
            <div class="info">
              <div class="etiqueta">${etiqueta}</div>
              ${detalle ? `<div class="detalle">${escaparHtml(detalle)}</div>` : ''}
            </div>
            <span class="estado-txt">${textoEstado}</span>
          </div>`;
      }).join('');
    }

    function mostrarEstado(id, zipPath) {
      itemActivoId = id;
      document.getElementById('panel-titulo').textContent = zipPath;
      const log = logsPorItem[id] || '';
      document.getElementById('log-crudo').textContent = log || '(sin salida todavía)';
      renderEtapas(log, !idsEnCurso.has(id));
      document.querySelectorAll('.item').forEach((el) => {
        el.classList.toggle('activo-panel', el.dataset.itemId === id);
      });
    }

    function actualizarEstadoSi(id, texto) {
      logsPorItem[id] = texto;
      if (id !== itemActivoId) return;
      document.getElementById('log-crudo').textContent = texto;
      renderEtapas(texto, !idsEnCurso.has(id));
    }

    document.getElementById('toggle-log-crudo').addEventListener('click', () => {
      const pre = document.getElementById('log-crudo');
      const btn = document.getElementById('toggle-log-crudo');
      pre.classList.toggle('visible');
      btn.textContent = pre.classList.contains('visible')
        ? 'Ocultar registro completo ▴'
        : 'Ver registro completo ▾';
    });

    // ── Historial de subidas: persiste entre reinicios del servidor ──
    // (a diferencia de la cola y logsPorItem, que son solo de esta
    // pestaña). Se carga al abrir la página y se refresca cada vez que
    // termina una subida.
    let historialEntradas = [];

    async function cargarHistorial() {
      const resp = await fetch('/historial');
      const data = await resp.json();
      historialEntradas = data.entradas || [];

      const vacio = document.getElementById('historial-vacio');
      const cont = document.getElementById('historial-lista');
      if (!historialEntradas.length) {
        vacio.style.display = 'block';
        cont.innerHTML = '';
        return;
      }
      vacio.style.display = 'none';
      cont.innerHTML = historialEntradas.map((e, i) => `
        <div class="hist-item" data-idx="${i}">
          <div class="hist-info">
            <div class="hist-nombre">${escaparHtml(e.zip_path)}</div>
            <div class="hist-fecha">${escaparHtml((e.timestamp || '').replace('T', ' '))}</div>
          </div>
          <span class="badge ${e.ok ? 'ok' : 'error'}">${e.ok ? 'completado' : 'con problemas'}</span>
        </div>
      `).join('');
      cont.querySelectorAll('.hist-item').forEach((el) => {
        el.addEventListener('click', () => {
          const entrada = historialEntradas[Number(el.dataset.idx)];
          itemActivoId = null;
          document.getElementById('panel-titulo').textContent =
            `${entrada.zip_path} — ${(entrada.timestamp || '').replace('T', ' ')}`;
          document.getElementById('log-crudo').textContent =
            '(subida de una sesión anterior — se guardó el resultado por etapa, no el registro crudo)';
          renderEtapasDesdeResultados(entrada.etapas || {}, true);
          document.querySelectorAll('.item').forEach((it) => it.classList.remove('activo-panel'));
        });
      });
    }
    cargarHistorial();

    // ── Credenciales ──────────────────────────────────────────────
    document.getElementById('guardar-credenciales').addEventListener('click', async () => {
      const email    = document.getElementById('cred-email').value.trim();
      const password = document.getElementById('cred-password').value;
      const volume   = document.getElementById('cred-volume').value.trim();
      const resp = await fetch('/credenciales', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, volume }),
      });
      const data = await resp.json();
      const el = document.getElementById('creds-estado');
      el.textContent = data.success
        ? 'Credenciales cargadas en memoria para esta sesión.'
        : '' + data.error;
      // Guardado con éxito -> se pliega sola para liberar espacio; si
      // hace falta cambiar algo, un clic en el título la vuelve a abrir.
      if (data.success) {
        document.getElementById('tarjeta-credenciales').classList.add('colapsada');
      }
    });

    // ── Elegir carpeta ────────────────────────────────────────────
    document.getElementById('elegir-carpeta').addEventListener('click', async () => {
      const resp = await fetch('/pick-folder', { method: 'POST' });
      const data = await resp.json();
      if (data.path) {
        carpetaDestino = data.path;
        document.getElementById('carpeta-elegida').textContent = carpetaDestino;
      }
    });

    // ── Convertir (uno o varios .idml de una) ────────────────────────
    async function convertirUno(archivo) {
      const formData = new FormData();
      formData.append('archivo', archivo);
      formData.append('carpeta_destino', carpetaDestino);
      const resp = await fetch('/convert', { method: 'POST', body: formData });
      return await resp.json();
    }

    document.getElementById('convertir').addEventListener('click', async () => {
      const fileInput = document.getElementById('archivo');
      const estado = document.getElementById('estado-convertir');
      const boton = document.getElementById('convertir');
      const archivos = [...fileInput.files];

      if (!archivos.length) {
        estado.className = 'estado error';
        estado.textContent = 'Elige primero uno o más archivos .idml';
        return;
      }

      boton.disabled = true;
      let ok = 0;
      const errores = [];

      for (let i = 0; i < archivos.length; i++) {
        estado.className = 'estado trabajando';
        estado.textContent = archivos.length > 1
          ? `Convirtiendo ${i + 1}/${archivos.length}: ${archivos[i].name}...`
          : `Convirtiendo ${archivos[i].name}... puede tardar unos segundos si tiene imágenes grandes.`;
        try {
          const data = await convertirUno(archivos[i]);
          if (data.success) {
            ok++;
            agregarItem(data.output_path);
          } else {
            errores.push(`${archivos[i].name}: ${data.error}`);
          }
        } catch (e) {
          errores.push(`${archivos[i].name}: error de conexión (${e})`);
        }
      }

      if (!errores.length) {
        estado.className = 'estado ok';
        estado.textContent = archivos.length > 1
          ? `${ok}/${archivos.length} convertidos y agregados a la cola.`
          : `Listo — agregado a la cola.`;
      } else {
        estado.className = 'estado error';
        estado.textContent = `${ok}/${archivos.length} OK. Con problemas: ${errores.join(' | ')}`;
      }
      fileInput.value = '';
      boton.disabled = false;
    });

    // ── Agregar uno o varios ZIP ya hechos (sin reconvertir) ──────────
    document.getElementById('agregar-zip').addEventListener('click', async () => {
      const resp = await fetch('/pick-zip', { method: 'POST' });
      const data = await resp.json();
      if (data.error) {
        alert(data.error);
        return;
      }
      (data.paths || []).forEach(agregarItem);
    });

    // ── Agregar todos los index.zip dentro de las subcarpetas de una
    //    carpeta (ej. una carpeta con una subcarpeta por artículo) ────
    document.getElementById('agregar-carpeta-zips').addEventListener('click', async () => {
      const resp = await fetch('/pick-zip-folder', { method: 'POST' });
      const data = await resp.json();
      if (data.error) {
        alert(data.error);
        return;
      }
      if (!data.paths || !data.paths.length) {
        alert('No se encontró ningún index.zip dentro de esa carpeta ni de sus subcarpetas.');
        return;
      }
      data.paths.forEach(agregarItem);
    });

    // ── Cola de subida: tarjetas reordenables por drag & drop o por número ──
    let arrastrado = null;

    // Recalcula el número de posición (1-based) de cada tarjeta según su
    // orden real en el DOM. Se llama después de agregar, quitar, arrastrar
    // o reordenar por número, para que el input de posición de cada
    // tarjeta siempre refleje dónde está parada de verdad.
    function renumerarItems() {
      const items = document.getElementById('items');
      [...items.children].forEach((div, i) => {
        const posInput = div.querySelector('.pos-input');
        if (posInput) posInput.value = i + 1;
      });
    }

    // Mueve una tarjeta a la posición 1-based que el usuario escribió,
    // corriendo al resto. La posición se acota a [1, total] para que un
    // valor fuera de rango no la mande fuera de la lista.
    function moverItemAPosicion(div, posDeseada) {
      const items = document.getElementById('items');
      const hijos = [...items.children];
      const total = hijos.length;
      const destino = Math.max(1, Math.min(total, posDeseada)) - 1;
      hijos.splice(hijos.indexOf(div), 1);
      hijos.splice(destino, 0, div);
      hijos.forEach(h => items.appendChild(h));
      renumerarItems();
    }

    function agregarItem(zipPath) {
      const items = document.getElementById('items');
      const div = document.createElement('div');
      div.className = 'item';
      div.draggable = true;
      const id = 'item-' + Math.random().toString(36).slice(2);
      div.dataset.itemId = id;
      div.innerHTML = `
        <input type="number" class="pos-input" id="${id}-pos" min="1" title="Posición en la cola">
        <span class="asa" title="Arrastrar para reordenar">⠿</span>
        <div class="cuerpo">
          <div class="nombre" title="Ver su progreso">${zipPath}</div>
          <div class="fila-botones">
            <button class="subir-btn" id="${id}-btn">Subir a AmeliCA</button>
            <span class="badge" id="${id}-badge">en cola</span>
            <button class="quitar-btn" id="${id}-quitar" title="Quitar de la cola">✕</button>
          </div>
        </div>
      `;
      // appendChild (no prepend): el primer artículo agregado queda
      // arriba y ahí se queda -- antes cada artículo nuevo empujaba a
      // los anteriores hacia abajo.
      items.appendChild(div);
      renumerarItems();

      div.addEventListener('dragstart', () => {
        arrastrado = div;
        div.classList.add('arrastrando');
      });
      div.addEventListener('dragend', () => {
        div.classList.remove('arrastrando');
        [...items.children].forEach(c => c.classList.remove('en-cola-encima'));
      });
      div.addEventListener('dragover', (e) => {
        e.preventDefault();
        if (div !== arrastrado) div.classList.add('en-cola-encima');
      });
      div.addEventListener('dragleave', () => div.classList.remove('en-cola-encima'));
      div.addEventListener('drop', (e) => {
        e.preventDefault();
        div.classList.remove('en-cola-encima');
        if (!arrastrado || arrastrado === div) return;
        const despues = [...items.children].indexOf(div) > [...items.children].indexOf(arrastrado);
        items.insertBefore(arrastrado, despues ? div.nextSibling : div);
        renumerarItems();
      });

      document.getElementById(`${id}-pos`).addEventListener('change', (e) => {
        const val = parseInt(e.target.value, 10);
        if (Number.isNaN(val)) { renumerarItems(); return; }
        moverItemAPosicion(div, val);
      });
      document.getElementById(`${id}-quitar`).addEventListener('click', () => {
        div.remove();
        renumerarItems();
        delete logsPorItem[id];
        idsEnCurso.delete(id);
        if (itemActivoId === id) {
          itemActivoId = null;
          document.getElementById('panel-titulo').textContent =
            'Ningún trabajo en curso — sube un artículo, o haz clic en el '
            + 'nombre de uno de la cola para ver su progreso.';
          document.getElementById('etapas').innerHTML = '';
          document.getElementById('log-crudo').textContent = '';
        }
      });
      document.getElementById(`${id}-btn`).addEventListener('click', () => subirItem(id, zipPath));
      div.querySelector('.nombre').addEventListener('click', () => mostrarEstado(id, zipPath));
      return id;
    }

    function verNavegador() {
      return document.getElementById('ver-navegador').checked;
    }

    function cargarReferencias() {
      return document.getElementById('cargar-referencias').checked;
    }

    // Sondea un trabajo YA lanzado (trabajo_id ya existe del lado del
    // servidor) hasta que termine. La separó de subirItem() para poder
    // reusarla también al reconciliar trabajos que quedaron corriendo
    // de antes de una recarga de página (ver reconciliarTrabajosActivos).
    async function pollearTrabajo(id, trabajoId, btn, badge) {
      return await new Promise((resolve) => {
        const poll = setInterval(async () => {
          const r = await fetch(`/subir-estado/${trabajoId}`);
          const estado = await r.json();
          if (estado.terminado) idsEnCurso.delete(id);
          actualizarEstadoSi(id, estado.log);
          if (estado.terminado) {
            clearInterval(poll);
            btn.disabled = false;
            btn.textContent = estado.ok ? 'Subido' : 'Terminó con problemas — reintentar';
            badge.className = 'badge ' + (estado.ok ? 'ok' : 'error');
            badge.textContent = estado.ok ? 'listo' : 'con problemas';
            cargarHistorial();
            resolve(estado.ok);
          }
        }, 1500);
      });
    }

    async function subirItem(id, zipPath) {
      const btn = document.getElementById(`${id}-btn`);
      const badge = document.getElementById(`${id}-badge`);
      btn.disabled = true;
      badge.className = 'badge trabajando';
      badge.textContent = 'subiendo...';
      idsEnCurso.add(id);
      mostrarEstado(id, zipPath);
      actualizarEstadoSi(id, 'Iniciando...');

      const resp = await fetch('/subir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zip_path: zipPath, headless: !verNavegador(), referencias: cargarReferencias() }),
      });
      const data = await resp.json();
      if (!data.success) {
        idsEnCurso.delete(id);
        actualizarEstadoSi(id, '' + data.error);
        badge.className = 'badge error';
        badge.textContent = 'error';
        btn.disabled = false;
        return false;
      }

      return await pollearTrabajo(id, data.trabajo_id, btn, badge);
    }

    // ── Reconciliar trabajos que quedaron corriendo de antes de una
    //    recarga de página. El subproceso sigue vivo del lado del
    //    servidor aunque el navegador se haya perdido el hilo -- esto
    //    reconstruye la tarjeta de cola y retoma el polling usando el
    //    trabajo_id real (nunca zip_path: un mismo archivo puede tener
    //    varios intentos con trabajo_id distintos).
    async function reconciliarTrabajosActivos() {
      const resp = await fetch('/trabajos-activos');
      const data = await resp.json();
      for (const t of (data.trabajos || [])) {
        const id = agregarItem(t.zip_path);
        const btn = document.getElementById(`${id}-btn`);
        const badge = document.getElementById(`${id}-badge`);
        btn.disabled = true;
        badge.className = 'badge trabajando';
        badge.textContent = 'reanudando...';
        idsEnCurso.add(id);
        mostrarEstado(id, t.zip_path);
        pollearTrabajo(id, t.trabajo_id, btn, badge);
      }
    }
    reconciliarTrabajosActivos();

    // ── Lote: una detrás de otra, en el orden de las tarjetas ────────
    // Correrlas en paralelo rompe el portal (dos sesiones con la misma
    // cuenta chocan entre sí) — por eso se espera a que cada una termine
    // antes de arrancar la siguiente.
    document.getElementById('lote-btn').addEventListener('click', async () => {
      const loteBtn = document.getElementById('lote-btn');
      const loteEstado = document.getElementById('lote-estado');
      const tarjetas = [...document.getElementById('items').children];
      if (!tarjetas.length) {
        loteEstado.textContent = 'No hay nada en la cola.';
        return;
      }

      loteBtn.disabled = true;
      let ok = 0, fallo = 0;
      for (let i = 0; i < tarjetas.length; i++) {
        const div = tarjetas[i];
        if (!div.isConnected) continue;   // se pudo haber quitado en el medio
        const id = div.dataset.itemId;
        const zipPath = div.querySelector('.nombre').textContent;
        loteEstado.textContent = `Subiendo ${i + 1}/${tarjetas.length}...`;
        div.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const resultado = await subirItem(id, zipPath);
        if (resultado) ok++; else fallo++;
      }
      loteEstado.textContent = `Lote terminado: ${ok} OK, ${fallo} con problemas.`;
      loteBtn.disabled = false;
    });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/credenciales", methods=["POST"])
def set_credenciales():
    """Guarda email/password/volume SOLO en memoria de este proceso — no
    se escribe ningún archivo. Se pasan al subproceso de subida por
    variable de entorno cuando corresponda (ver /subir)."""
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""
    volume   = (data.get("volume") or "").strip()

    if not email or not password:
        return jsonify({"success": False, "error": "Falta email o contraseña"}), 400

    CREDENCIALES["email"] = email
    CREDENCIALES["password"] = password
    CREDENCIALES["volume"] = volume
    return jsonify({"success": True})


@app.route("/pick-folder", methods=["POST"])
def pick_folder():
    """Abre el explorador de archivos nativo del sistema operativo para
    elegir una carpeta de destino. Usa tkinter, que corre en el servidor
    (o sea, en tu propia PC, ya que este servidor solo corre localmente)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return jsonify({
            "path": None,
            "error": "tkinter no está instalado. En Linux prueba: sudo apt install python3-tk"
        }), 500

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Elige la carpeta padre de destino")
    root.destroy()

    return jsonify({"path": folder or None})


@app.route("/pick-zip", methods=["POST"])
def pick_zip():
    """Abre el explorador nativo para elegir uno o varios index.zip ya
    generados en corridas anteriores, sin pasar por /convert -- para
    reintentar subidas sin reconvertir el .idml de origen."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return jsonify({
            "paths": [],
            "error": "tkinter no está instalado. En Linux prueba: sudo apt install python3-tk"
        }), 500

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    zip_paths = filedialog.askopenfilenames(
        title="Elige uno o más index.zip ya generados",
        filetypes=[("ZIP", "*.zip")],
    )
    root.destroy()

    return jsonify({"paths": list(zip_paths)})


@app.route("/pick-zip-folder", methods=["POST"])
def pick_zip_folder():
    """Abre el explorador nativo para elegir UNA carpeta y busca dentro de
    ella, en cualquier subcarpeta, todos los index.zip que encuentre --
    para agregar de una vez a la cola los artículos que viven cada uno en
    su propia subcarpeta (mismo patrón que ArticulosZip/Articulo N/index.zip
    o el que arma /convert: carpeta_destino/nombre_articulo/index.zip)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return jsonify({
            "paths": [],
            "error": "tkinter no está instalado. En Linux prueba: sudo apt install python3-tk"
        }), 500

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(
        title="Elige la carpeta que contiene los artículos (con su index.zip adentro)"
    )
    root.destroy()

    if not folder:
        return jsonify({"paths": []})

    zip_paths = sorted(str(p) for p in Path(folder).rglob("index.zip"))
    return jsonify({"paths": zip_paths})


@app.route("/convert", methods=["POST"])
def convert():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify({"success": False, "error": "No se recibió ningún archivo .idml"}), 400
    if not archivo.filename.lower().endswith(".idml"):
        return jsonify({"success": False, "error": "El archivo debe tener extensión .idml"}), 400

    carpeta_destino = request.form.get("carpeta_destino", "").strip()
    if not carpeta_destino:
        carpeta_destino = os.getcwd()
    if not os.path.isdir(carpeta_destino):
        return jsonify({"success": False, "error": f"La carpeta de destino no existe: {carpeta_destino}"}), 400

    # Carpeta padre -> una subcarpeta por artículo -> index.zip. Mismo
    # patrón que ArticulosZip/Articulo N/index.zip en el resto del
    # proyecto: amelica batch espera justo esa forma.
    base_name = os.path.splitext(os.path.basename(archivo.filename))[0]
    articulo_dir = os.path.join(carpeta_destino, base_name)
    output_path = os.path.join(articulo_dir, "index.zip")

    with tempfile.TemporaryDirectory(prefix="idml_upload_") as tmpdir:
        idml_temp_path = os.path.join(tmpdir, archivo.filename)
        archivo.save(idml_temp_path)

        try:
            build_index_zip(idml_temp_path, output_path)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": f"{type(e).__name__}: {e}"}), 500

    return jsonify({"success": True, "output_path": output_path})


@app.route("/subir", methods=["POST"])
def subir():
    """Lanza `amelica upload <zip>` como subproceso, con las credenciales
    de esta sesión por variable de entorno -- nunca se tocan
    credentials.json ni ningún archivo.

    Se usa tanto para la subida individual como, llamado varias veces en
    secuencia desde el front, para el lote -- correrlas en PARALELO rompe
    el estado del portal (confirmado en vivo, 2026-08-18: dos sesiones a la
    vez con la misma cuenta chocan y una de las dos termina sin poder
    encontrar ni una caja del editor). El orden y el "una a la vez" los
    garantiza el JS del front, este endpoint solo lanza una subida.
    """
    data = request.get_json(silent=True) or {}
    zip_path = data.get("zip_path", "")
    headless = bool(data.get("headless"))
    referencias = bool(data.get("referencias"))
    if not zip_path or not os.path.isfile(zip_path):
        return jsonify({"success": False, "error": f"No existe el ZIP: {zip_path}"}), 400

    if not CREDENCIALES["email"] or not CREDENCIALES["password"]:
        return jsonify({"success": False,
                        "error": "Carga las credenciales primero (paso 1)"}), 400

    trabajo_id = uuid.uuid4().hex
    with TRABAJOS_LOCK:
        TRABAJOS[trabajo_id] = {"log": "", "terminado": False, "ok": False, "zip_path": zip_path}

    env = os.environ.copy()
    env["AMELICA_EMAIL"] = CREDENCIALES["email"]
    env["AMELICA_PASSWORD"] = CREDENCIALES["password"]
    if CREDENCIALES["volume"]:
        env["AMELICA_VOLUME"] = CREDENCIALES["volume"]
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    comando = [sys.executable, "-m", "amelica", "upload", zip_path]
    if not headless:
        comando.append("--show")
    if referencias:
        comando.append("--referencias")

    def correr():
        try:
            proceso = subprocess.Popen(
                comando,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env=env, stdin=subprocess.DEVNULL,
            )
            for linea in proceso.stdout:
                with TRABAJOS_LOCK:
                    TRABAJOS[trabajo_id]["log"] += linea
            codigo = proceso.wait()
            with TRABAJOS_LOCK:
                TRABAJOS[trabajo_id]["terminado"] = True
                TRABAJOS[trabajo_id]["ok"] = (codigo == 0)
                log_final = TRABAJOS[trabajo_id]["log"]
            _registrar_historial(zip_path, codigo == 0, log_final)
        except Exception as e:
            with TRABAJOS_LOCK:
                TRABAJOS[trabajo_id]["log"] += f"\n{type(e).__name__}: {e}\n"
                TRABAJOS[trabajo_id]["terminado"] = True
                TRABAJOS[trabajo_id]["ok"] = False
                log_final = TRABAJOS[trabajo_id]["log"]
            _registrar_historial(zip_path, False, log_final)

    threading.Thread(target=correr, daemon=True).start()
    return jsonify({"success": True, "trabajo_id": trabajo_id})


@app.route("/subir-estado/<trabajo_id>")
def subir_estado(trabajo_id):
    with TRABAJOS_LOCK:
        trabajo = TRABAJOS.get(trabajo_id)
    if not trabajo:
        return jsonify({"log": "Trabajo no encontrado", "terminado": True, "ok": False}), 404
    return jsonify(trabajo)


@app.route("/trabajos-activos")
def trabajos_activos():
    """Devuelve los trabajos que todavía no terminaron -- para que el
    frontend pueda reconstruir su cola si se recargó la página a mitad
    de una subida real (el subproceso sigue corriendo del lado del
    servidor aunque el navegador se haya perdido el hilo).

    La identidad de cada trabajo es su trabajo_id, nunca zip_path: un
    mismo archivo puede tener varios intentos (uno que falló, un
    reintento en curso), cada uno con su propio trabajo_id -- zip_path
    aquí es solo el dato para mostrar, no una clave de deduplicación."""
    with TRABAJOS_LOCK:
        activos = [
            {"trabajo_id": tid, "zip_path": t.get("zip_path", "")}
            for tid, t in TRABAJOS.items()
            if not t["terminado"]
        ]
    return jsonify({"trabajos": activos})


@app.route("/historial")
def historial():
    """Devuelve las subidas registradas en HISTORIAL_FILE, más recientes
    primero. A diferencia de /subir-estado (memoria, se pierde al
    reiniciar), esto persiste entre corridas del servidor -- es la
    respuesta a "¿qué subí la semana pasada y cómo salió?"."""
    entradas = []
    if HISTORIAL_FILE.exists():
        with open(HISTORIAL_FILE, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    entradas.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
    entradas.reverse()
    return jsonify({"entradas": entradas[:200]})


def _abrir_navegador():
    """Abre el navegador solo, con una pequeña demora para darle tiempo
    al servidor a levantar. Corre en un hilo aparte para no bloquear
    app.run() (que se queda corriendo en primer plano). Si el puerto ya
    estaba en uso (server ya corriendo de antes), esto simplemente abre
    una pestaña nueva apuntando a esa instancia -- comportamiento
    razonable, no un error."""
    import webbrowser
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    threading.Timer(1.2, _abrir_navegador).start()
    print("Abriendo http://localhost:5000 en tu navegador...")
    print("Las credenciales que cargues ahí quedan solo en memoria de este")
    print("proceso — no se escriben en ningún archivo.")
    app.run(host="127.0.0.1", port=5000, debug=False)
