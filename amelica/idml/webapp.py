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
cerrás este servidor (Ctrl+C) o recargás sin volver a cargarlas, se
pierden solas — no hay nada que "limpiar" en disco.
"""

import os
import subprocess
import sys
import tempfile
import threading
import traceback
import uuid

# En Windows, cuando stdout no es una consola UTF-8 (cp1252 por default),
# los print() con emoji de converter.py y del subproceso de subida revientan
# con UnicodeEncodeError. Forzarlo acá evita que dependa de que quien lo
# corra sepa poner PYTHONIOENCODING=utf-8 a mano.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, request, jsonify, render_template_string

from .converter import build_index_zip

app = Flask(__name__)

# ── Credenciales: solo en memoria de este proceso ──────────────────────
CREDENCIALES = {"email": "", "password": "", "volume": ""}

# ── Trabajos de subida en curso/terminados: id -> estado ───────────────
TRABAJOS = {}
TRABAJOS_LOCK = threading.Lock()

INDEX_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>IDML a AmeliCA</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 60px auto; color: #222; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.05rem; margin-top: 40px; border-top: 1px solid #e5e5e5; padding-top: 24px; }
  .campo { margin-bottom: 20px; }
  label { display: block; margin-bottom: 6px; font-weight: 600; }
  input[type=file], input[type=text], input[type=password] {
    display: block; width: 100%; box-sizing: border-box; padding: 6px 8px;
    border: 1px solid #ccc; border-radius: 4px; font-size: 0.95rem;
  }
  button { padding: 8px 16px; border-radius: 6px; border: 1px solid #ccc;
           background: #f5f5f5; cursor: pointer; font-size: 0.95rem; }
  button:hover { background: #eaeaea; }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  #convertir, #guardar-credenciales { background: #2563eb; color: white; border: none; }
  #convertir:hover, #guardar-credenciales:hover { background: #1d4ed8; }
  #convertir:disabled { background: #93c5fd; }
  .subir-btn { background: #16a34a; color: white; border: none; margin-top: 10px; }
  .subir-btn:hover { background: #15803d; }
  .subir-btn:disabled { background: #86efac; }
  #carpeta-elegida { margin-top: 8px; font-size: 0.9rem; color: #555; word-break: break-all; }
  .estado { margin-top: 20px; padding: 12px; border-radius: 6px; display: none; }
  .estado.ok { background: #dcfce7; color: #166534; display: block; }
  .estado.error { background: #fee2e2; color: #991b1b; display: block; }
  .estado.trabajando { background: #fef9c3; color: #713f12; display: block; }
  .creds-estado { font-size: 0.85rem; margin-top: 8px; color: #555; }
  .log { margin-top: 10px; background: #0f172a; color: #e2e8f0; padding: 12px;
         border-radius: 6px; font-family: ui-monospace, monospace; font-size: 0.8rem;
         white-space: pre-wrap; max-height: 320px; overflow-y: auto; display: none; }
  .log.visible { display: block; }
  .item { border: 1px solid #e5e5e5; border-radius: 8px; padding: 14px; margin-top: 10px;
          display: flex; align-items: flex-start; gap: 10px; background: white; }
  .item.arrastrando { opacity: 0.4; }
  .item.en-cola-encima { border-top: 3px solid #2563eb; }
  .item .asa { cursor: grab; color: #999; font-size: 1.1rem; padding-top: 2px; user-select: none; }
  .item .cuerpo { flex: 1; min-width: 0; }
  .item .nombre { word-break: break-all; font-size: 0.9rem; }
  .item .fila-botones { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
  .badge { font-size: 0.75rem; padding: 2px 8px; border-radius: 10px; background: #f1f5f9; color: #475569; }
  .badge.ok { background: #dcfce7; color: #166534; }
  .badge.error { background: #fee2e2; color: #991b1b; }
  .badge.trabajando { background: #fef9c3; color: #713f12; }
  .quitar-btn { background: none; border: none; color: #999; cursor: pointer; font-size: 1rem; }
  .quitar-btn:hover { color: #dc2626; }
  .toggle-nav { display: flex; align-items: center; gap: 6px; font-size: 0.9rem;
                margin-top: 10px; font-weight: normal; }
  .lote-barra { display: flex; align-items: center; gap: 10px; margin-top: 16px; }
  #lote-btn { background: #7c3aed; color: white; border: none; }
  #lote-btn:hover { background: #6d28d9; }
  #lote-btn:disabled { background: #c4b5fd; }
</style>
</head>
<body>
  <h1>Convertir .idml a AmeliCA</h1>

  <h2>1. Credenciales (solo para esta sesión)</h2>
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
    servidor esté corriendo y se pierden si lo cerrás.
  </div>

  <h2>2. Convertir artículos</h2>
  <div class="campo">
    <label for="archivo">Archivos .idml (podés elegir varios)</label>
    <input type="file" id="archivo" accept=".idml" multiple>
  </div>

  <div class="campo">
    <label>Carpeta padre de destino</label>
    <button type="button" id="elegir-carpeta">📁 Elegir carpeta...</button>
    <div id="carpeta-elegida">(ninguna elegida — se usará la carpeta actual del servidor)</div>
  </div>

  <label class="toggle-nav">
    <input type="checkbox" id="ver-navegador" checked>
    Mostrar el navegador mientras sube (destildá para que corra oculto)
  </label>

  <button id="convertir">Convertir</button>

  <div id="estado-convertir" class="estado"></div>

  <h2>3. Cola de subida <span style="font-weight:normal; font-size:0.8rem; color:#777;">(arrastrá las tarjetas para cambiar el orden)</span></h2>
  <div class="campo">
    <button type="button" id="agregar-zip">📦 Agregar ZIP ya hecho...</button>
    <span style="font-size:0.85rem; color:#777; margin-left:8px;">
      Para reintentar una subida sin volver a convertir el .idml
    </span>
  </div>
  <div class="lote-barra">
    <button id="lote-btn">▶ Subir todo en orden</button>
    <span id="lote-estado" style="font-size:0.85rem; color:#555;"></span>
  </div>

  <div id="items"></div>

  <script>
    let carpetaDestino = "";

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
        ? '✅ Credenciales cargadas en memoria para esta sesión.'
        : '❌ ' + data.error;
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
        estado.textContent = 'Elegí primero uno o más archivos .idml';
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
          ? `✅ ${ok}/${archivos.length} convertidos y agregados a la cola.`
          : `✅ Listo — agregado a la cola.`;
      } else {
        estado.className = 'estado error';
        estado.textContent = `${ok}/${archivos.length} OK. Con problemas: ${errores.join(' | ')}`;
      }
      fileInput.value = '';
      boton.disabled = false;
    });

    // ── Agregar un ZIP ya hecho (sin reconvertir) ─────────────────────
    document.getElementById('agregar-zip').addEventListener('click', async () => {
      const resp = await fetch('/pick-zip', { method: 'POST' });
      const data = await resp.json();
      if (data.error) {
        alert(data.error);
        return;
      }
      (data.paths || []).forEach(agregarItem);
    });

    // ── Cola de subida: tarjetas reordenables por drag & drop ────────
    let arrastrado = null;

    function agregarItem(zipPath) {
      const items = document.getElementById('items');
      const div = document.createElement('div');
      div.className = 'item';
      div.draggable = true;
      const id = 'item-' + Math.random().toString(36).slice(2);
      div.dataset.itemId = id;
      div.innerHTML = `
        <span class="asa" title="Arrastrar para reordenar">⠿</span>
        <div class="cuerpo">
          <div class="nombre">${zipPath}</div>
          <div class="fila-botones">
            <button class="subir-btn" id="${id}-btn">🚀 Subir a AmeliCA</button>
            <span class="badge" id="${id}-badge">en cola</span>
            <button class="quitar-btn" id="${id}-quitar" title="Quitar de la cola">✕</button>
          </div>
          <div class="log" id="${id}-log"></div>
        </div>
      `;
      items.prepend(div);

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
      });

      document.getElementById(`${id}-quitar`).addEventListener('click', () => div.remove());
      document.getElementById(`${id}-btn`).addEventListener('click', () => subirItem(id, zipPath));
    }

    function verNavegador() {
      return document.getElementById('ver-navegador').checked;
    }

    async function subirItem(id, zipPath) {
      const btn = document.getElementById(`${id}-btn`);
      const badge = document.getElementById(`${id}-badge`);
      const log = document.getElementById(`${id}-log`);
      btn.disabled = true;
      badge.className = 'badge trabajando';
      badge.textContent = 'subiendo...';
      log.className = 'log visible';
      log.textContent = 'Iniciando...';

      const resp = await fetch('/subir', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zip_path: zipPath, headless: !verNavegador() }),
      });
      const data = await resp.json();
      if (!data.success) {
        log.textContent = '❌ ' + data.error;
        badge.className = 'badge error';
        badge.textContent = 'error';
        btn.disabled = false;
        return false;
      }

      const trabajoId = data.trabajo_id;
      return await new Promise((resolve) => {
        const poll = setInterval(async () => {
          const r = await fetch(`/subir-estado/${trabajoId}`);
          const estado = await r.json();
          log.textContent = estado.log;
          log.scrollTop = log.scrollHeight;
          if (estado.terminado) {
            clearInterval(poll);
            btn.disabled = false;
            btn.textContent = estado.ok ? '✅ Subido' : '⚠️ Terminó con problemas — reintentar';
            badge.className = 'badge ' + (estado.ok ? 'ok' : 'error');
            badge.textContent = estado.ok ? 'listo' : 'con problemas';
            resolve(estado.ok);
          }
        }, 1500);
      });
    }

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
            "error": "tkinter no está instalado. En Linux probá: sudo apt install python3-tk"
        }), 500

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Elegí la carpeta padre de destino")
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
            "error": "tkinter no está instalado. En Linux probá: sudo apt install python3-tk"
        }), 500

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    zip_paths = filedialog.askopenfilenames(
        title="Elegí uno o más index.zip ya generados",
        filetypes=[("ZIP", "*.zip")],
    )
    root.destroy()

    return jsonify({"paths": list(zip_paths)})


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
    if not zip_path or not os.path.isfile(zip_path):
        return jsonify({"success": False, "error": f"No existe el ZIP: {zip_path}"}), 400

    if not CREDENCIALES["email"] or not CREDENCIALES["password"]:
        return jsonify({"success": False,
                        "error": "Cargá las credenciales primero (paso 1)"}), 400

    trabajo_id = uuid.uuid4().hex
    with TRABAJOS_LOCK:
        TRABAJOS[trabajo_id] = {"log": "", "terminado": False, "ok": False}

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
        except Exception as e:
            with TRABAJOS_LOCK:
                TRABAJOS[trabajo_id]["log"] += f"\n💥 {type(e).__name__}: {e}\n"
                TRABAJOS[trabajo_id]["terminado"] = True
                TRABAJOS[trabajo_id]["ok"] = False

    threading.Thread(target=correr, daemon=True).start()
    return jsonify({"success": True, "trabajo_id": trabajo_id})


@app.route("/subir-estado/<trabajo_id>")
def subir_estado(trabajo_id):
    with TRABAJOS_LOCK:
        trabajo = TRABAJOS.get(trabajo_id)
    if not trabajo:
        return jsonify({"log": "Trabajo no encontrado", "terminado": True, "ok": False}), 404
    return jsonify(trabajo)


if __name__ == "__main__":
    print("Abrí http://localhost:5000 en tu navegador")
    print("Las credenciales que cargues ahí quedan solo en memoria de este")
    print("proceso — no se escriben en ningún archivo.")
    app.run(host="127.0.0.1", port=5000, debug=False)
