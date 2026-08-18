"""
Tests de la lógica de decisión del uploader — sin portal ni navegador.

Cubren los dos defectos encontrados en la corrida en vivo del 2026-08-18:

  1. "Marcar" se buscaba por texto del título y clickeaba el primer match
     del DOM. Si el número ya tenía un artículo homónimo, abría el viejo y
     el front matter lo sobrescribía (llegó a borrar 3 autores reales).
  2. run() imprimía "completado" y devolvía True aunque el marcaje y el
     front matter hubieran fallado.
"""

import pytest

from amelica.portal.uploader import AmelicaUploader

TITULO = "Las cajas de ahorro comunitarias, opción al desarrollo socioeconómico"


def bloque(clave, titulo=TITULO, estable=True):
    """Un bloque del listado.

    estable=False imita un bloque sin id de elemento, donde lo único
    disponible es el onclick del link 'Marcar' — que puede ser posicional.
    """
    return {"clave": clave, "titulo": titulo,
            "id_estable": clave if estable else ""}


# ── 1. Elección del artículo a marcar ────────────────────────────

def test_bloque_nuevo_identificable_se_elige_por_clave():
    antes = [bloque("art-1", "Otro artículo")]
    despues = antes + [bloque("art-2")]
    assert AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO) \
        == ("clave", "art-2")


def test_sin_claves_pero_titulo_nuevo_es_seguro_por_titulo():
    """El portal no siempre expone ids; si el título no existía, no hay riesgo."""
    antes = [bloque("", "Otro artículo")]
    despues = antes + [bloque("")]
    estrategia, _ = AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)
    assert estrategia == "titulo"


def test_homonimo_preexistente_sin_claves_aborta():
    """EL CASO QUE ROMPIÓ EL ARTÍCULO PUBLICADO.

    El artículo ya estaba en el número y no hay claves para distinguirlo:
    la única respuesta correcta es no tocar nada.
    """
    antes = [bloque("", TITULO)]          # el artículo ya publicado
    despues = antes + [bloque("")]        # + el que acabamos de crear
    estrategia, motivo = AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)
    assert estrategia == "abortar"
    assert motivo


def test_homonimo_con_claves_posicionales_aborta():
    """Un onclick posicional NO alcanza para distinguir.

    Si el portal inserta el artículo nuevo arriba, las claves se corren:
    el viejo pasa a 'marcar(1)' y parece el bloque nuevo. Confiar en eso
    reproduce exactamente el accidente, así que se aborta.
    """
    antes   = [bloque("marcar(0)", TITULO, estable=False)]
    despues = [bloque("marcar(0)", TITULO, estable=False),
               bloque("marcar(1)", TITULO, estable=False)]
    estrategia, _ = AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)
    assert estrategia == "abortar"


def test_homonimo_preexistente_con_claves_no_aborta():
    """Con claves estables sí se puede distinguir, aunque haya homónimo."""
    antes = [bloque("art-1", TITULO)]
    despues = antes + [bloque("art-2", TITULO)]
    assert AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO) \
        == ("clave", "art-2")


def test_ningun_bloque_nuevo_con_homonimo_aborta():
    antes = [bloque("art-1", TITULO)]
    assert AmelicaUploader.decidir_articulo_a_marcar(antes, antes, TITULO)[0] == "abortar"


def test_varios_bloques_nuevos_con_homonimo_aborta():
    antes = [bloque("art-1", TITULO)]
    despues = antes + [bloque("art-2"), bloque("art-3")]
    assert AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)[0] == "abortar"


def test_ids_posicionales_que_se_corren_abortan():
    """AmeliCA usa ids con el número de fila adentro
    ('j_idt66:0:j_idt77:3:form-opciones'). Si el artículo se inserta en el
    medio, todas las filas de abajo cambian de id: aparecen varios bloques
    'nuevos' y hay que abortar en vez de adivinar.
    """
    fila = lambda n, t: bloque(f"j_idt66:0:j_idt77:{n}:form-opciones", t)
    antes = [fila(0, "Artículo A"), fila(1, TITULO), fila(2, "Artículo C")]
    # Se inserta en la posición 1 → las filas 1 y 2 se corren a 2 y 3
    despues = [fila(0, "Artículo A"), fila(1, TITULO),
               fila(2, TITULO), fila(3, "Artículo C")]
    estrategia, _ = AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)
    assert estrategia == "abortar"


def test_id_nuevo_con_titulo_ajeno_no_se_elige():
    """Guarda extra: un id nuevo cuyo bloque tiene OTRO título no puede ser
    el artículo que acabamos de crear, aunque sea el único id nuevo."""
    antes = [bloque("art-1", TITULO)]
    despues = antes + [bloque("art-9", "Un artículo totalmente distinto")]
    estrategia, _ = AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)
    assert estrategia == "abortar"


def test_agregado_al_final_se_identifica_bien():
    """El caso normal en AmeliCA: el artículo nuevo va al final y las filas
    existentes conservan su id."""
    fila = lambda n, t: bloque(f"j_idt66:0:j_idt77:{n}:form-opciones", t)
    antes = [fila(0, "Artículo A"), fila(1, "Artículo B")]
    despues = antes + [fila(2, TITULO)]
    estrategia, clave = AmelicaUploader.decidir_articulo_a_marcar(antes, despues, TITULO)
    assert estrategia == "clave"
    assert clave.endswith(":2:form-opciones")


@pytest.mark.parametrize("titulos,esperado", [
    ([TITULO], 1),
    ([TITULO, TITULO], 2),
    (["Otro tema completamente distinto"], 0),
    ([], 0),
    # El match usa los primeros 50 caracteres, sin distinguir mayúsculas
    ([TITULO.upper()], 1),
    ([TITULO[:50] + " y un subtítulo agregado"], 1),
])
def test_conteo_de_titulos_coincidentes(titulos, esperado):
    bloques = [bloque("k%d" % i, t) for i, t in enumerate(titulos)]
    assert AmelicaUploader._titulos_coincidentes(bloques, TITULO) == esperado


def test_titulo_vacio_no_cuenta_como_coincidencia():
    assert AmelicaUploader._titulos_coincidentes([bloque("k", TITULO)], "") == 0


# ── 2. Reporte honesto del resultado ─────────────────────────────

def uploader():
    return AmelicaUploader(email="x@y.z", password="secreto")


def test_todas_las_etapas_ok_es_exito():
    up = uploader()
    for etapa in ("login", "issue", "article", "zip", "marker", "front_matter"):
        up._step(etapa, True)
    assert up.succeeded


def test_marcaje_fallido_no_es_exito():
    """El bug original: el marcaje falló y run() devolvía True igual."""
    up = uploader()
    for etapa in ("login", "issue", "article", "zip"):
        up._step(etapa, True)
    up._step("marker", False, "el editor no respondió")
    up._step("front_matter", False, "browser closed")
    assert not up.succeeded


def test_sin_etapas_no_es_exito():
    assert not uploader().succeeded


def test_step_devuelve_el_valor_para_encadenar():
    up = uploader()
    assert up._step("login", True) is True
    assert up._step("zip", False, "timeout") is False
    assert up.steps["zip"] == (False, "timeout")


def test_resumen_distingue_critico_de_incompleto(capsys):
    up = uploader()
    for etapa in ("login", "issue", "article", "zip"):
        up._step(etapa, True)
    up._step("marker", False, "el editor no respondió")
    up.print_summary()
    salida = capsys.readouterr().out
    assert "INCOMPLETO" in salida        # se creó, pero falta terminarlo
    assert "FALLÓ en una etapa crítica" not in salida


def test_zip_sin_confirmar_se_valida_por_el_marcaje():
    """Falso negativo real del 2026-08-18: el servidor no confirmó el ZIP,
    pero el editor después cargó el artículo con sus 5 secciones — lo que
    solo puede pasar si el ZIP se procesó."""
    up = uploader()
    up._step("zip", True, "sin confirmación explícita")
    up._zip_sin_confirmar = True
    up._confirmar_zip_por_marcaje(True)
    ok, detalle = up.steps["zip"]
    assert ok
    assert "confirmado indirectamente" in detalle


def test_zip_sin_confirmar_y_sin_marcaje_es_fallo():
    """Sin confirmación del servidor Y sin editor no hay evidencia: falla."""
    up = uploader()
    up._step("zip", True, "sin confirmación explícita")
    up._zip_sin_confirmar = True
    up._confirmar_zip_por_marcaje(False)
    assert up.steps["zip"][0] is False
    assert not up.succeeded


def test_zip_confirmado_no_se_toca():
    """Si el servidor sí confirmó, el marcaje no debe cambiar nada."""
    up = uploader()
    up._step("zip", True)
    up._confirmar_zip_por_marcaje(False)
    assert up.steps["zip"] == (True, "")


def test_confirmacion_del_zip_es_idempotente():
    up = uploader()
    up._step("zip", True, "sin confirmación explícita")
    up._zip_sin_confirmar = True
    up._confirmar_zip_por_marcaje(True)
    up._confirmar_zip_por_marcaje(False)   # no debe revertir
    assert up.steps["zip"][0] is True


def test_resumen_marca_fallo_critico(capsys):
    up = uploader()
    up._step("login", True)
    up._step("issue", True)
    up._step("article", False, "no se encontró 'Agregar'")
    up.print_summary()
    assert "FALLÓ en una etapa crítica" in capsys.readouterr().out


# ── 3. El marcaje se guarda ──────────────────────────────────────

def test_inferir_no_depende_del_modo_de_visualizacion():
    """El bug: el guardado estaba detrás de `if self.headless`, así que
    corriendo con --show el marcaje nunca se guardaba y se perdía al salir.
    Mostrar o no el navegador no puede cambiar si el trabajo se persiste."""
    from amelica.portal.marker import AmelicaMarker
    assert AmelicaMarker(None, headless=True).auto_guardar is True
    assert AmelicaMarker(None, headless=False).auto_guardar is True


def test_se_puede_desactivar_el_guardado_explicitamente():
    from amelica.portal.marker import AmelicaMarker
    assert AmelicaMarker(None, auto_guardar=False).auto_guardar is False


def test_uploader_propaga_auto_guardar():
    assert uploader().auto_guardar is True
    up = AmelicaUploader(email="x@y.z", password="s", auto_guardar=False)
    assert up.auto_guardar is False
