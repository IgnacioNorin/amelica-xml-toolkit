# Amelica Automatización

Automatiza la carga de artículos científicos en el portal [AmeliCA XML](https://portal.amelica.org):
toma un artículo exportado a HTML, lo sube, crea el registro, marca las
secciones y completa los datos del artículo — sin hacerlo a mano.

## Instalación

```bash
pip install -e .
playwright install chromium
```

Extras opcionales:

```bash
pip install -e ".[idml]"   # web local para convertir .idml
pip install -e ".[word]"   # conversión DOCX vía Microsoft Word (solo Windows)
pip install -e ".[dev]"    # pytest
```

## Credenciales

Copiá la plantilla y editá el archivo con tus datos reales:

```bash
cp credentials.example.json credentials.json
```

```json
{
  "email": "tu@correo.com",
  "password": "tu_contraseña",
  "volume": "38 (1)"
}
```

`volume` es el número+edición tal como aparece en la lista de AmeliCA. Si
coincide con un número "En proceso", se selecciona solo, sin preguntar.

`credentials.json` está en `.gitignore` y nunca se sube al repo. También se
pueden usar las variables de entorno `AMELICA_EMAIL`, `AMELICA_PASSWORD` y
`AMELICA_VOLUME`, que tienen prioridad sobre el archivo.

## Uso

El camino recomendado empieza en Word: abrí el DOCX → *Guardar como* →
**Página web filtrada (.htm, .html)**. Eso genera `index.html` +
`index_archivos/`. Comprimí ambos en un `index.zip` y subilo:

```bash
amelica upload index.zip --show
```

`--show` muestra el navegador para que veas lo que hace y revises el
resultado antes de cerrar.

```bash
# Varios artículos de una carpeta
amelica batch ./ArticulosZip/ --show

# Desde .docx directamente (el HTML sale peor que exportándolo de Word)
amelica upload articulo.docx

# Solo generar el ZIP, sin subir nada — para inspeccionarlo
amelica zip articulo.docx -o ./salida/

# Sobreescribir metadatos detectados automáticamente
amelica upload index.zip --titulo "Mi título" --idioma Inglés \
                         --pagina-inicio 1 --pagina-fin 15
```

También funciona sin instalar: `python -m amelica upload index.zip`.

### Convertir .idml

Para artículos que llegan como InDesign:

```bash
python -m amelica.idml.webapp    # abrir http://localhost:5000
```

## Qué hace, paso a paso

1. Login en el portal.
2. Detecta los números "En proceso" y elige el del `volume` configurado.
3. Crea el artículo (tipo, título, sección, idioma, páginas, norma APA).
4. Sube el ZIP con el `index.html`.
5. Abre el editor y **marca las secciones** automáticamente.
6. Completa **Datos del artículo**: títulos, autores, afiliaciones, resumen,
   palabras clave, fechas.
7. Informa cuántas referencias detectó (ver más abajo).

## Estructura

```
amelica/
  cli.py            Interfaz de línea de comandos
  config.py         Credenciales (env > credentials.json)
  parsing/          Parseo puro, sin navegador — testeable offline
    docx.py           Metadatos desde .docx
    html.py           Metadatos desde el index.html del ZIP
    references.py     Parser de referencias APA
    zip_tools.py      DOCX -> index.zip y correcciones del ZIP de Word
  portal/           Automatización con Playwright
    uploader.py       Orquestador del flujo completo
    dom.py            Helpers de bajo nivel del editor
    front_matter.py   "Datos del artículo"
    marker.py         Marcaje de secciones
    references.py     Llenado de referencias (experimental, ver abajo)
  idml/             Conversor .idml -> index.zip + web local
tests/              Tests del parser de referencias
fixtures/           ZIPs reales usados por los tests
```

La separación importante es `parsing/` vs `portal/`: `parsing/` no depende de
Playwright ni de la red, así que se puede testear sin abrir un navegador.

## Estado de cada parte

| Parte | Estado |
|---|---|
| Login y detección de números | Verificado en vivo (`tools/smoke_test.py`) |
| Subida del ZIP y alta del artículo | Funciona, usado en producción |
| Parser de referencias | Validado: 376 refs sobre 12 artículos, con tests |
| Marcaje de secciones | Marca bien; **el guardado se arregló pero falta verificarlo en vivo** |
| Datos del artículo (front matter) | Funciona; **el arreglo de fechas falta verificarlo en vivo** |
| Llenado de referencias en el portal | **Experimental, apagado por defecto** |

### Pendiente de verificar (2026-08-18)

Dos arreglos quedaron escritos y con tests, pero **sin confirmar contra el
portal**: las dos corridas siguientes fallaron antes de llegar, con el editor
sin cargar el artículo (`el editor de marcaje no respondió`). Antes de
confiar en ellos, hacer una corrida limpia y mirar estos dos puntos:

1. **Guardado del marcaje.** El botón es `save-526564616c7963:buttonS`
   (`salvarContenido()`), no "Inferir" — buscar ese error era la causa de que
   el marcaje se perdiera al reentrar. Ahora, tras guardar, se recarga el
   editor para comprobar que las secciones siguen ahí. Verificar que el log
   diga `Marcaje guardado y verificado tras recargar`.
2. **Fechas.** El síntoma era el año de publicación en el campo de aceptado.
   Causa: existía **un solo** campo de fecha y ambas escribían ahí. Ahora se
   cuenta antes de escribir y se intentan crear las que falten. Verificar que
   las dos fechas reporten ids `dp…` **distintos**.

También quedó sin resolver que el alta no completa el campo *Sección*
(`ID no encontrado en la pagina: seccion`).

### Protecciones contra sobrescritura

El 2026-08-18 una corrida de prueba sobre un número que ya contenía el
artículo terminó modificando el artículo publicado en vez del recién creado,
y le borró 3 autores. Quedaron dos guardas, ambas con tests:

1. **Identificación del artículo.** Antes de crear nada se saca una foto del
   listado; después el artículo se identifica por diferencia, no por texto
   del título. Los ids de AmeliCA son posicionales
   (`j_idt66:0:j_idt77:3:form-opciones` — ese `3` es la fila), así que si no
   se puede distinguir sin ambigüedad, **aborta sin abrir el editor**.
2. **Autores existentes.** El front matter aborta si detecta autores con
   contenido, y el borrado de "sobrantes" solo elimina bloques vacíos. Para
   pisar deliberadamente un artículo cargado: `--sobrescribir`.

Para ver cómo identifica el portal a los artículos de un número, sin escribir
nada:

```bash
python tools/smoke_test.py --inspeccionar
```

> Los ZIPs de `ArticulosZip/` ya están publicados. No sirven para probar el
> flujo completo: usá un artículo que no exista en el número destino.

### Sobre las referencias

Hay que distinguir dos cosas distintas:

**El parser** (`parsing/references.py`) extrae y clasifica las referencias del
HTML en 6 tipos (journal, book, thesis, webpage, confproc, report). Está
medido sobre los 12 artículos reales: 376 referencias, año en el 99%, título
en el 95%, URL en el 90%. Tiene tests de regresión en `tests/`.

**El llenado en el portal** (`portal/references.py`) es otra historia: es
automatización a ciegas, con esperas fijas y selectores hardcodeados, que
nunca se verificó contra el sitio en vivo. Además `_delete_refs_but_one()`
borra las referencias que el artículo ya tenga cargadas antes de escribir.

Por eso está **apagado por defecto**. Sin el flag, el CLI solo informa cuántas
referencias detectó para que las cargues a mano. Para retomarlo:

```bash
amelica upload index.zip --show --referencias   # experimental
```

Probalo primero sobre un número de prueba, y empezá revisando
`_delete_refs_but_one()`.

## Tests

```bash
pytest
```

Son tests de regresión sobre `fixtures/`: fijan el rendimiento medido del
parser para que un cambio futuro no lo degrade en silencio. `articulo_12.zip`
es el peor caso conocido (HTML de origen con otro formato, sin cursivas para
la fuente) y está incluido a propósito.

## Limitaciones conocidas

- Los selectores del portal llevan el sufijo `526564616c7963` (`Redalyc` en
  hex). Es fijo, no un token de sesión, pero si AmeliCA cambia el front-end
  hay que remapearlos.
- El parser de referencias rinde peor con HTML que no marca la fuente en
  cursiva (ver `articulo_12.zip`).
- La conversión DOCX vía Word solo funciona en Windows con Word instalado;
  si no está, cae al conversor propio, de menor calidad.
