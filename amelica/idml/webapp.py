#!/usr/bin/env python3
"""
app.py — Pequeña web local para convertir archivos .idml a index.zip
(listos para AmeliCA), eligiendo la carpeta de destino con el explorador
nativo de archivos.

Uso:
    python app.py
    (despues abrir http://localhost:5000 en el navegador)

Requiere: flask, Pillow (pip install flask Pillow)
tkinter viene incluido con Python en Windows/Mac; en Linux puede
necesitar instalarse aparte (ej: sudo apt install python3-tk).
"""

import os
import tempfile
import traceback

from flask import Flask, request, jsonify, render_template_string

from .converter import build_index_zip

app = Flask(__name__)

INDEX_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>IDML a AmeliCA</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 560px; margin: 60px auto; color: #222; }
  h1 { font-size: 1.4rem; }
  .campo { margin-bottom: 20px; }
  label { display: block; margin-bottom: 6px; font-weight: 600; }
  input[type=file] { display: block; }
  button { padding: 8px 16px; border-radius: 6px; border: 1px solid #ccc;
           background: #f5f5f5; cursor: pointer; font-size: 0.95rem; }
  button:hover { background: #eaeaea; }
  #convertir { background: #2563eb; color: white; border: none; }
  #convertir:hover { background: #1d4ed8; }
  #convertir:disabled { background: #93c5fd; cursor: not-allowed; }
  #carpeta-elegida { margin-top: 8px; font-size: 0.9rem; color: #555; word-break: break-all; }
  #estado { margin-top: 20px; padding: 12px; border-radius: 6px; display: none; }
  #estado.ok { background: #dcfce7; color: #166534; display: block; }
  #estado.error { background: #fee2e2; color: #991b1b; display: block; }
  #estado.trabajando { background: #fef9c3; color: #713f12; display: block; }
</style>
</head>
<body>
  <h1>Convertir .idml a index.zip (AmeliCA)</h1>

  <div class="campo">
    <label for="archivo">Archivo .idml</label>
    <input type="file" id="archivo" accept=".idml">
  </div>

  <div class="campo">
    <label>Carpeta de destino</label>
    <button type="button" id="elegir-carpeta">📁 Elegir carpeta...</button>
    <div id="carpeta-elegida">(ninguna elegida — se usará la carpeta actual del servidor)</div>
  </div>

  <button id="convertir">Convertir</button>

  <div id="estado"></div>

  <script>
    let carpetaDestino = "";

    document.getElementById('elegir-carpeta').addEventListener('click', async () => {
      const resp = await fetch('/pick-folder', { method: 'POST' });
      const data = await resp.json();
      if (data.path) {
        carpetaDestino = data.path;
        document.getElementById('carpeta-elegida').textContent = carpetaDestino;
      }
    });

    document.getElementById('convertir').addEventListener('click', async () => {
      const fileInput = document.getElementById('archivo');
      const estado = document.getElementById('estado');
      const boton = document.getElementById('convertir');

      if (!fileInput.files.length) {
        estado.className = 'error';
        estado.textContent = 'Elegí primero un archivo .idml';
        return;
      }

      const formData = new FormData();
      formData.append('archivo', fileInput.files[0]);
      formData.append('carpeta_destino', carpetaDestino);

      boton.disabled = true;
      estado.className = 'trabajando';
      estado.textContent = 'Convirtiendo... puede tardar unos segundos si el artículo tiene imágenes grandes.';

      try {
        const resp = await fetch('/convert', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
          estado.className = 'ok';
          estado.textContent = `✅ Listo: ${data.output_path}`;
        } else {
          estado.className = 'error';
          estado.textContent = `❌ ${data.error}`;
        }
      } catch (e) {
        estado.className = 'error';
        estado.textContent = `❌ Error de conexión: ${e}`;
      } finally {
        boton.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


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
    folder = filedialog.askdirectory(title="Elegí la carpeta de destino")
    root.destroy()

    return jsonify({"path": folder or None})


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

    base_name = os.path.splitext(os.path.basename(archivo.filename))[0]
    output_path = os.path.join(carpeta_destino, f"{base_name}_index.zip")

    with tempfile.TemporaryDirectory(prefix="idml_upload_") as tmpdir:
        idml_temp_path = os.path.join(tmpdir, archivo.filename)
        archivo.save(idml_temp_path)

        try:
            build_index_zip(idml_temp_path, output_path)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": f"{type(e).__name__}: {e}"}), 500

    return jsonify({"success": True, "output_path": output_path})


if __name__ == "__main__":
    print("Abrí http://localhost:5000 en tu navegador")
    app.run(host="127.0.0.1", port=5000, debug=False)
