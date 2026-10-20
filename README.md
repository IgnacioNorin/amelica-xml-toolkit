# Amelica XML Toolkit

[![Tests](https://github.com/IgnacioNorin/amelica-xml-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/IgnacioNorin/amelica-xml-toolkit/actions/workflows/tests.yml)

Automatiza la carga de artículos científicos en el portal [AmeliCA XML](https://portal.amelica.org):
toma un artículo exportado a HTML, lo sube, crea el registro, marca las
secciones y completa los datos del artículo — sin hacerlo a mano.

> **Nota**: esto automatiza un portal específico (AmeliCA XML). Para
> probar el flujo completo hace falta una cuenta real ahí, con acceso de
> editor a alguna revista. Sin cuenta, igual se puede: correr `pytest`
> (169 tests, no necesitan portal ni credenciales), o leer el código del
> parser (`amelica/parsing/`), que es puro y se prueba solo.

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

Copia la plantilla y edita el archivo con tus datos reales:

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

El camino recomendado empieza en Word: abre el DOCX → *Guardar como* →
**Página web filtrada (.htm, .html)**. Eso genera `index.html` +
`index_archivos/`. Comprime ambos en un `index.zip` y súbelo:

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

# Los .doc (Word 97-2003) no se aceptan: hay que guardarlos como .docx
# antes. `batch` los omite y avisa cuáles se saltó.

# Sobreescribir metadatos detectados automáticamente
amelica upload index.zip --titulo "Mi título" --idioma Inglés \
                         --pagina-inicio 1 --pagina-fin 15
```

También funciona sin instalar: `python -m amelica upload index.zip`.

### Convertir .idml/.docx y subir desde una web local

Para artículos que llegan como InDesign o Word, o para manejar varios artículos
a la vez sin usar la terminal:

```bash
python -m amelica.idml.webapp    # abre el navegador solo en http://localhost:5000
```

Requiere el extra `idml` (`pip install -e ".[idml]"`). Todo corre en tu
propia máquina — nada se sube a ningún servidor externo salvo el portal
AmeliCA en sí. Qué hace:

- **Convertir** uno o varios `.idml` o `.docx` a `index.zip` de una. Los
  `.docx` usan la misma conversión que `amelica zip` (Word si está
  instalado, si no LibreOffice o el conversor propio). Para mejor calidad
  con Word, sigue conviniendo exportar el `index.zip` a mano y agregarlo
  con "Agregar ZIP ya hecho".
- **Cola de subida** reordenable (arrastrando o escribiendo la posición),
  con botón para subir todo en orden — correrlas en paralelo rompe el
  portal (dos sesiones con la misma cuenta chocan entre sí), así que
  siempre van una detrás de otra.
- **"Agregar carpeta con varios artículos"**: busca automáticamente todos
  los `index.zip` dentro de las subcarpetas de una carpeta (el patrón que
  arma la propia conversión: `carpeta/nombre_articulo/index.zip`), sin
  necesidad de mover ni renombrar nada.
- **Panel de progreso por etapa**: en vez de un log crudo, muestra una
  línea de tiempo con las mismas 8 etapas de `AmelicaUploader.print_summary()`
  (login, número, artículo, ZIP, editor, marcaje, datos del artículo,
  referencias), coloreada por estado. El log crudo sigue disponible atrás
  de un botón, por si hace falta para depurar un error puntual.
- **Historial persistente** (`historial_subidas.jsonl`, en `.gitignore`):
  a diferencia de la cola (que es solo de esa pestaña del navegador), el
  historial sobrevive a cerrar el servidor — queda qué se subió, cuándo, y
  cómo salió cada etapa.
- **Recupera trabajos en curso al recargar la página**: si se cierra o
  recarga la pestaña de la webapp a mitad de una subida, el subproceso
  sigue corriendo del lado del servidor y la webapp lo vuelve a encontrar
  al abrir de nuevo. **Límite real**: esto NO puede revivir la ventana de
  Chromium que abre `--show` si se la cierra manualmente — Playwright
  pierde el control del navegador en el acto y esa subida termina fallada
  (esperado, no es un bug: no hay forma de "seguir" sin el navegador).
- Credenciales cargadas ahí quedan solo en memoria del proceso, nunca se
  escriben a `credentials.json` ni a ningún archivo.

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
    word_html.py      Lo mismo para el HTML exportado desde Word
    references.py     Parser de referencias APA
    zip_tools.py      DOCX -> index.zip y correcciones del ZIP de Word
  portal/           Automatización con Playwright
    uploader.py       Orquestador del flujo completo
    dom.py            Helpers de bajo nivel del editor
    front_matter.py   "Datos del artículo"
    marker.py         Marcaje de secciones
    references.py     Llenado de referencias (experimental, ver abajo)
  idml/             Conversor .idml -> index.zip + web local
    converter.py      Conversor .idml -> index.zip
    webapp.py         Web local: convertir, cola de subida, historial
tests/              169 tests: parser, CLI, DOM del portal, y la web local
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
| Marcaje de secciones | **Verificado en vivo**: guardado confirmado (click + spinner de JSF) en varias corridas reales |
| Datos del artículo (front matter) | **Verificado en vivo**: completado de punta a punta en corridas reales, incluidos autores, ORCID, fechas, resúmenes y DOI |
| Artículos desde Word (`parsing/word_html.py`) | **Probado sin portal** contra un artículo real exportado desde Word: títulos de sección, portada completa y secciones a marcar. Falta una corrida real en el portal |
| Llenado de referencias en el portal | **Experimental, apagado por defecto** |
| Web local (`idml/webapp.py`) | **Verificado en vivo**: cola, panel de progreso, historial y recuperación al recargar, con 35 tests propios (endpoints Flask + lógica JS) |

### Flujo completo verificado en vivo (2026-08-20)

Con el 403 del reload de verificación resuelto (ver `AmelicaMarker.run()`) y
la confirmación del ZIP reescrita para leer la respuesta ajax en vez de
hacer polling del DOM (`uploader.upload_zip()`), se corrieron los 12
artículos de prueba de punta a punta: login, alta del artículo (incluida
*Sección*, que ya no falla), subida del ZIP, marcaje de secciones, y
"Datos del artículo" completo (títulos ES/EN, autores con ORCID,
afiliaciones, fechas, resúmenes/keywords, DOI). Las 8 etapas quedan en OK.

De paso se encontraron y arreglaron dos bugs de extracción de ORCID
(`amelica/parsing/html.py`) con artefactos reales de InDesign: un espacio
colado en el href (perdía el ORCID de todos los autores en silencio) y una
barra sobrante que desalineaba el ORCID de un autor con el de otro.

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
> flujo completo: usa un artículo que no exista en el número destino.

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

Pruébalo primero sobre un número de prueba, y empieza revisando
`_delete_refs_but_one()`.

## Tests

```bash
pip install -e ".[dev,idml]"
pytest
```

169 tests en total, sin abrir ningún navegador ni tocar el portal real:

- **Parser y DOM del portal** (`amelica/parsing/`, `amelica/portal/`): tests
  de regresión sobre `fixtures/` que fijan el rendimiento medido del parser
  para que un cambio futuro no lo degrade en silencio. `articulo_12.zip` es
  el peor caso conocido (HTML de origen con otro formato, sin cursivas para
  la fuente) y está incluido a propósito.
- **Web local** (`tests/test_webapp.py`): endpoints Flask (`/subir`,
  `/convert`, `/historial`, `/trabajos-activos`, etc.) con
  `app.test_client()` — no lanza ningún subproceso real de `amelica upload`
  ni abre diálogos de tkinter, solo valida lo que la webapp hace antes de
  llegar a eso.
- **Web local, lado JS** (`tests/test_webapp_js.py`): la lógica del
  `<script>` embebido (parseo de etapas, panel de progreso, reordenar la
  cola) corrida de verdad con Node y un DOM mínimo simulado a mano — sin
  agregar ningún framework de JS al proyecto.

`test_webapp.py` se saltea limpio si falta `flask` (extra `idml`);
`test_webapp_js.py` se saltea limpio si no hay `node` instalado. Ninguno de
los dos rompe la colección de tests para quien instaló sin esos extras.

## Limitaciones conocidas

- Los selectores del portal llevan el sufijo `526564616c7963` (`Redalyc` en
  hex). Es fijo, no un token de sesión, pero si AmeliCA cambia el front-end
  hay que remapearlos.
- El parser de referencias rinde peor con HTML que no marca la fuente en
  cursiva (ver `articulo_12.zip`).
- La conversión DOCX vía Word solo funciona en Windows con Word instalado;
  si no está, cae al conversor propio, de menor calidad.
- La portada de un artículo de Word se lee por su formato, no por marcas
  propias: títulos en negrita con la fuente más grande, autores con número
  de afiliación en superíndice, afiliación con la institución en cursiva.
  Una plantilla muy distinta a la de la revista puede necesitar ajustes.
  Si el parser detecta algo raro (por ejemplo, dos autores con el mismo
  ORCID), lo avisa en vez de seguir en silencio.
- La web local recupera trabajos en curso si se recarga su propia pestaña,
  pero no puede revivir la ventana de Chromium que abre `--show` si se
  cierra manualmente -- Playwright pierde el control del navegador ahí
  mismo y esa subida termina fallada (comportamiento esperado, no un bug).

## Licencia

Todos los derechos reservados. El código queda público para consulta,
evaluación y uso personal, pero no está bajo ninguna licencia de código
abierto -- no está permitido reutilizarlo, redistribuirlo ni incorporarlo
a otro proyecto sin permiso explícito. Si te interesa usar algo de aquí,
escribime.
