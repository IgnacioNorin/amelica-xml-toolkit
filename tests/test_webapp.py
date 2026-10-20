"""
test_webapp.py — Tests de amelica/idml/webapp.py (la web local de subida).

No lanza subprocesos reales de `amelica upload` ni abre diálogos de
tkinter (askdirectory/askopenfilenames): eso ya está cubierto en la
práctica por los tests de amelica/portal/ (lo que /subir termina
ejecutando) y por corridas reales verificadas a mano. Lo que se cubre acá
es la parte propia de la webapp que no tenía ningún test:

  - Las validaciones de cada endpoint Flask (¿rechaza bien lo que tiene
    que rechazar, antes de llegar a lanzar nada?).
  - _parsear_etapas() y _registrar_historial(): las funciones puras que
    alimentan el panel de progreso y el historial persistente.

flask es una dependencia opcional (extra "idml", ver pyproject.toml) --
si no está instalada, este archivo se saltea entero en vez de romper la
colección de tests para quien instaló el proyecto sin ese extra.
"""

import json
from io import BytesIO
from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from amelica.idml import webapp as webapp_mod  # noqa: E402
from amelica.idml.webapp import app, _parsear_etapas, _registrar_historial  # noqa: E402


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(autouse=True)
def estado_limpio():
    """CREDENCIALES y TRABAJOS son dicts a nivel de módulo, compartidos
    por todas las requests reales -- sin resetearlos, un test contamina
    al siguiente (ej. credenciales cargadas en un test seguirían
    "cargadas" para el que corre después)."""
    webapp_mod.CREDENCIALES.update({"email": "", "password": "", "volume": ""})
    webapp_mod.TRABAJOS.clear()
    yield
    webapp_mod.CREDENCIALES.update({"email": "", "password": "", "volume": ""})
    webapp_mod.TRABAJOS.clear()


# ── GET / ────────────────────────────────────────────────────────────

def test_index_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Convertir artículos a AmeliCA" in html
    # Guarda contra HTML roto por un tag sin cerrar en un edit futuro.
    assert html.count("<div") == html.count("</div>")


# ── /credenciales ────────────────────────────────────────────────────

def test_credenciales_falta_email_o_password(client):
    resp = client.post("/credenciales", json={"email": "", "password": ""})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_credenciales_ok_queda_en_memoria(client):
    resp = client.post("/credenciales", json={
        "email": "test@x.com", "password": "abc123", "volume": "38 (1)",
    })
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert webapp_mod.CREDENCIALES["email"] == "test@x.com"
    assert webapp_mod.CREDENCIALES["password"] == "abc123"
    assert webapp_mod.CREDENCIALES["volume"] == "38 (1)"


# ── /subir: validaciones antes de lanzar el subproceso ───────────────

def test_subir_sin_zip_existente(client):
    resp = client.post("/subir", json={"zip_path": "no/existe.zip"})
    assert resp.status_code == 400
    assert "No existe el ZIP" in resp.get_json()["error"]


def test_subir_sin_credenciales(client, tmp_path):
    zip_falso = tmp_path / "index.zip"
    zip_falso.write_bytes(b"PK\x03\x04")  # el endpoint solo chequea que exista
    resp = client.post("/subir", json={"zip_path": str(zip_falso)})
    assert resp.status_code == 400
    assert "credenciales" in resp.get_json()["error"].lower()


# ── /subir-estado ────────────────────────────────────────────────────

def test_subir_estado_trabajo_inexistente(client):
    resp = client.get("/subir-estado/no-existe")
    assert resp.status_code == 404


def test_subir_estado_trabajo_real(client):
    webapp_mod.TRABAJOS["abc123"] = {"log": "hola", "terminado": True, "ok": True}
    resp = client.get("/subir-estado/abc123")
    assert resp.status_code == 200
    assert resp.get_json() == {"log": "hola", "terminado": True, "ok": True}


# ── /trabajos-activos ────────────────────────────────────────────────

def test_trabajos_activos_solo_devuelve_los_no_terminados(client):
    webapp_mod.TRABAJOS["en-curso"] = {
        "log": "...", "terminado": False, "ok": False, "zip_path": "C:/a/index.zip",
    }
    webapp_mod.TRABAJOS["ya-termino"] = {
        "log": "...", "terminado": True, "ok": True, "zip_path": "C:/b/index.zip",
    }
    resp = client.get("/trabajos-activos")
    assert resp.status_code == 200
    activos = resp.get_json()["trabajos"]
    assert activos == [{"trabajo_id": "en-curso", "zip_path": "C:/a/index.zip"}]


def test_trabajos_activos_vacio_sin_trabajos(client):
    resp = client.get("/trabajos-activos")
    assert resp.status_code == 200
    assert resp.get_json()["trabajos"] == []


def test_trabajos_activos_dos_intentos_mismo_zip_no_se_confunden(client):
    """El mismo zip_path puede tener dos trabajo_id activos a la vez
    (ej. un reintento manual mientras el primero seguía corriendo) --
    la respuesta debe traer los dos por separado, identificados por
    trabajo_id, no colapsados por ruta."""
    webapp_mod.TRABAJOS["intento-1"] = {
        "log": "", "terminado": False, "ok": False, "zip_path": "C:/mismo/index.zip",
    }
    webapp_mod.TRABAJOS["intento-2"] = {
        "log": "", "terminado": False, "ok": False, "zip_path": "C:/mismo/index.zip",
    }
    resp = client.get("/trabajos-activos")
    activos = resp.get_json()["trabajos"]
    assert len(activos) == 2
    assert {a["trabajo_id"] for a in activos} == {"intento-1", "intento-2"}


def test_subir_guarda_zip_path_en_trabajos(client, tmp_path, monkeypatch):
    """El campo que /trabajos-activos necesita para reconstruir la cola
    -- confirma que /subir lo deja guardado desde que crea el trabajo,
    no solo al terminar."""
    zip_falso = tmp_path / "index.zip"
    zip_falso.write_bytes(b"PK\x03\x04")
    webapp_mod.CREDENCIALES.update({"email": "a@b.com", "password": "x", "volume": ""})

    # No se quiere lanzar el subproceso real de `amelica upload` en un
    # test. threading.Thread tambien se reemplaza por una version que
    # corre el target YA (sincronica, en el mismo hilo del test) en vez
    # de en segundo plano: sin esto, /subir devuelve antes de que el
    # hilo real termine, y ese hilo -- corriendo ya fuera del alcance
    # del monkeypatch de HISTORIAL_FILE -- puede terminar escribiendo
    # sobre el historial_subidas.jsonl REAL del proyecto (paso una vez
    # armando este test: pisó un registro real del usuario).
    class ProcesoFalso:
        stdout = iter([])
        def wait(self):
            return 0

    class HiloSincronoFalso:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(webapp_mod.subprocess, "Popen", lambda *a, **k: ProcesoFalso())
    monkeypatch.setattr(webapp_mod.threading, "Thread",
                         lambda target=None, daemon=None: HiloSincronoFalso(target))
    monkeypatch.setattr(webapp_mod, "HISTORIAL_FILE", tmp_path / "historial_test.jsonl")

    resp = client.post("/subir", json={"zip_path": str(zip_falso)})
    assert resp.status_code == 200
    trabajo_id = resp.get_json()["trabajo_id"]

    # Con el hilo sincrónico, para cuando /subir ya respondió el trabajo
    # está completamente terminado -- no hace falta esperar nada más.
    with webapp_mod.TRABAJOS_LOCK:
        assert webapp_mod.TRABAJOS[trabajo_id]["zip_path"] == str(zip_falso)
        assert webapp_mod.TRABAJOS[trabajo_id]["terminado"] is True


# ── /convert: validaciones ───────────────────────────────────────────

def test_convert_sin_archivo(client):
    resp = client.post("/convert", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_convert_extension_invalida(client):
    data = {"archivo": (BytesIO(b"contenido"), "articulo.pdf")}
    resp = client.post("/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    error = resp.get_json()["error"]
    assert ".idml" in error and ".docx" in error


def test_convert_doc_viejo_da_mensaje_claro(client):
    data = {"archivo": (BytesIO(b"contenido"), "articulo.doc")}
    resp = client.post("/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "guárdalo como .docx" in resp.get_json()["error"]


def test_convert_docx_deja_solo_index_zip(client, tmp_path, monkeypatch):
    """Un .docx se convierte con build_zip_from_docx() y en la carpeta del
    artículo queda solo index.zip, igual que con un .idml (sin el
    index.html ni index_archivos/ intermedios)."""
    def falso_build_zip_from_docx(docx_path, output_dir):
        assert docx_path.endswith("Mi articulo.docx")
        (Path(output_dir) / "index.html").write_text("<html></html>")
        zip_p = Path(output_dir) / "index.zip"
        zip_p.write_bytes(b"PK zip falso")
        return str(zip_p)

    monkeypatch.setattr(webapp_mod, "build_zip_from_docx", falso_build_zip_from_docx)
    data = {
        "archivo": (BytesIO(b"contenido"), "Mi articulo.docx"),
        "carpeta_destino": str(tmp_path),
    }
    resp = client.post("/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True

    articulo_dir = tmp_path / "Mi articulo"
    assert Path(body["output_path"]) == articulo_dir / "index.zip"
    assert [p.name for p in articulo_dir.iterdir()] == ["index.zip"]
    assert (articulo_dir / "index.zip").read_bytes() == b"PK zip falso"


def test_convert_carpeta_destino_inexistente(client):
    data = {
        "archivo": (BytesIO(b"contenido"), "articulo.idml"),
        "carpeta_destino": "Z:/carpeta/que/no/existe/de/verdad/seguro",
    }
    resp = client.post("/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "no existe" in resp.get_json()["error"].lower()


# ── _parsear_etapas ──────────────────────────────────────────────────

def test_parsear_etapas_lineas_normales():
    log = "\n".join([
        "Iniciando sesión...",
        "##ETAPA## login|ok|",
        "##ETAPA## issue|ok|",
        "##ETAPA## marker|fail|no se pudo guardar",
    ])
    assert _parsear_etapas(log) == {
        "login": {"ok": True, "detalle": ""},
        "issue": {"ok": True, "detalle": ""},
        "marker": {"ok": False, "detalle": "no se pudo guardar"},
    }


def test_parsear_etapas_ignora_lineas_sin_formato():
    log = "esto no es una etapa\n##ETAPA## incompleta\n"
    assert _parsear_etapas(log) == {}


def test_parsear_etapas_vacio_o_none():
    assert _parsear_etapas("") == {}
    assert _parsear_etapas(None) == {}


def test_parsear_etapas_la_ultima_ocurrencia_gana():
    """'zip' puede reportarse dos veces: una vez de forma optimista al
    subir el ZIP, y corregido después vía _confirmar_zip_por_marcaje si
    el servidor no confirmó -- ver amelica/portal/uploader.py. Tiene que
    quedar el valor final, no el primero."""
    log = "\n".join([
        "##ETAPA## zip|ok|sin confirmación del servidor",
        "##ETAPA## zip|fail|sin confirmación y el editor no cargó",
    ])
    resultados = _parsear_etapas(log)
    assert resultados["zip"] == {
        "ok": False, "detalle": "sin confirmación y el editor no cargó",
    }


# ── _registrar_historial + /historial ────────────────────────────────

def test_registrar_historial_y_leer(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp_mod, "HISTORIAL_FILE", tmp_path / "historial_subidas.jsonl")

    _registrar_historial("C:/x/index.zip", True, "##ETAPA## login|ok|")
    _registrar_historial("C:/y/index.zip", False, "##ETAPA## login|fail|credenciales inválidas")

    resp = client.get("/historial")
    assert resp.status_code == 200
    entradas = resp.get_json()["entradas"]
    assert len(entradas) == 2
    # Más reciente primero.
    assert entradas[0]["zip_path"] == "C:/y/index.zip"
    assert entradas[0]["ok"] is False
    assert entradas[0]["etapas"]["login"]["detalle"] == "credenciales inválidas"
    assert entradas[1]["zip_path"] == "C:/x/index.zip"
    assert entradas[1]["ok"] is True


def test_historial_vacio_si_no_hay_archivo(client, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp_mod, "HISTORIAL_FILE", tmp_path / "no_existe.jsonl")
    resp = client.get("/historial")
    assert resp.status_code == 200
    assert resp.get_json()["entradas"] == []


def test_historial_ignora_lineas_corruptas(client, tmp_path, monkeypatch):
    """Una línea rota (ej. el proceso se cortó a mitad de un write) no
    debe tirar abajo la lectura de las demás."""
    archivo = tmp_path / "historial_subidas.jsonl"
    archivo.write_text(
        json.dumps({"timestamp": "2026-08-21T10:00:00", "zip_path": "a.zip",
                    "ok": True, "etapas": {}}) + "\n"
        + "{esto no es json valido\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(webapp_mod, "HISTORIAL_FILE", archivo)

    resp = client.get("/historial")
    assert resp.status_code == 200
    entradas = resp.get_json()["entradas"]
    assert len(entradas) == 1
    assert entradas[0]["zip_path"] == "a.zip"


def test_registrar_historial_no_tira_si_no_puede_escribir(tmp_path, monkeypatch):
    """Un fallo al escribir el historial (ej. carpeta inexistente) no
    debe propagar la excepción -- no puede tumbar el hilo de subida por
    un problema de logging secundario."""
    monkeypatch.setattr(webapp_mod, "HISTORIAL_FILE", tmp_path / "no" / "existe" / "hist.jsonl")
    _registrar_historial("a.zip", True, "")  # no debe lanzar
