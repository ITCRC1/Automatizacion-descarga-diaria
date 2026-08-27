"""
modulos/integrity.py

PROCESO COMPLETO de Integrity:
  1. Login (Chromium)
  2. Configuracion -> Cargar revenue
  3. Selecciona el XML de revenue descargado de Opera
  4. Confirma la carga (Cargar -> Confirmar -> Close)
  5. Busca el asiento "OPL - Ingresos Opera/Simphony <fecha ayer>"
  6. Descarga el Excel del asiento -> carpeta integrity del dia

El archivo de revenue se toma de la carpeta opera del dia:
  G:\\...\\Inputs\\<fecha ayer>\\opera\\OPERA_GEN_XMLBO_REVENUE_<fecha>.xml

Credenciales esperadas en .env:
    INTEGRITY_USERNAME=jretana
    INTEGRITY_PASSWORD=tu_password
"""

import os
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

logger = logging.getLogger(__name__)

# Subir este numero al cambiar el modulo: el log lo imprime al arrancar, asi
# se ve enseguida si el contenedor tiene el codigo nuevo o una imagen vieja.
VERSION_MODULO = "2026-08-27-c (interfaz nueva + paso de seleccion de compañia)"

BASE_URL = "https://www.programarcr.com"
INTEGRITY_URL = f"{BASE_URL}/Conta506/login"
MENU_URL = f"{BASE_URL}/Conta506/Menu.aspx"

# La ruta de "Cargar revenue" ya cambio dos veces en agosto de 2026 (el sitio
# esta en rediseño), asi que NO se usa una constante fija: se lee el href del
# enlace en el propio menu. Esta queda solo como ultimo recurso.
CARGAR_REVENUE_URL = f"{BASE_URL}/Conta506/forms/frmParametros_OperaCargarRevenue.aspx"


def _fecha_negocio_del_xml(ruta: Path):
    """Lee la fecha de negocio del XML de revenue, que viene en el atributo
    date de la raiz: <revenue hotel_code="COWLCR" date="YYYY-MM-DD">.

    Hace falta porque el nombre del archivo NO garantiza el dia de los datos:
    si el proceso corre de madrugada, antes del night audit de Opera, el
    export todavia trae el dia anterior. Y el asiento en Integrity se nombra
    segun la fecha de los datos, no segun la del archivo.

    Devuelve datetime o None si no se pudo leer.
    """
    try:
        for _, elem in ET.iterparse(str(ruta), events=("start",)):
            valor = elem.get("date")
            return datetime.strptime(valor, "%Y-%m-%d") if valor else None
    except Exception as e:
        logger.warning(f"No se pudo leer la fecha del XML {ruta.name}: {e}")
    return None


def _listar_menu(page) -> None:
    """Vuelca al log todos los enlaces y botones del menu con su texto y href.

    Sirve cuando el sitio reubica una opcion: en vez de adivinar la ruta nueva
    o buscarla a mano, el log muestra donde quedo cada cosa y con que nombre.
    """
    try:
        elementos = page.evaluate(
            "() => Array.from(document.querySelectorAll('a, button')).map(el => ({"
            "tag: el.tagName, "
            "texto: (el.innerText || el.title || '').trim().slice(0, 60), "
            "href: el.getAttribute('href') || '', "
            "onclick: (el.getAttribute('onclick') || '').slice(0, 80)"
            "})).filter(x => x.texto || x.href || x.onclick)"
        )
        logger.error(f"[MENU] Enlaces y botones disponibles ({len(elementos)}):")
        for elem in elementos:
            logger.error(f"[MENU]   {elem}")
    except Exception as e:
        logger.error(f"[MENU] No se pudo listar el menu: {e}")


def _guardar(descarga, carpeta: Path, prefijo: str, fecha_str: str) -> Path:
    extension = Path(descarga.suggested_filename).suffix or ".xlsx"
    destino = carpeta / f"{prefijo}_{fecha_str}{extension}"
    descarga.save_as(destino)
    logger.info(f"Guardado: {destino.name}")
    return destino


def subir_revenue_y_descargar(
    archivo_revenue_xml: Path,
    carpeta_destino: Path,
    fecha_reporte: datetime = None,
    headless: bool = False,
) -> list:
    """
    Sube el XML de revenue a Integrity, confirma la carga y descarga el
    Excel del asiento OPL en carpeta_destino.

    Parametros:
        archivo_revenue_xml : ruta al XML descargado por opera.py
        carpeta_destino     : carpeta integrity del dia
        fecha_reporte       : fecha del reporte (por defecto: ayer)
        headless            : False para ver el navegador

    Devuelve la lista de archivos descargados.
    """
    archivo_revenue_xml = Path(archivo_revenue_xml)
    if not archivo_revenue_xml.exists():
        raise FileNotFoundError(f"No se encontro el archivo de revenue: {archivo_revenue_xml}")

    carpeta_destino = Path(carpeta_destino)
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    usuario  = os.getenv("INTEGRITY_USERNAME")
    password = os.getenv("INTEGRITY_PASSWORD")
    if not all([usuario, password]):
        raise RuntimeError("Faltan INTEGRITY_USERNAME / INTEGRITY_PASSWORD en el .env")

    if fecha_reporte is None:
        fecha_reporte = datetime.now() - timedelta(days=1)
    fecha_str = fecha_reporte.strftime("%Y-%m-%d")

    # El asiento se busca por la fecha de los DATOS (la que trae el XML), no por
    # la del nombre del archivo ni por "ayer": si el proceso corre antes del
    # night audit, Opera exporta el dia anterior y buscar por "ayer" no
    # encuentra nada. El nombre del archivo descargado sigue usando fecha_str
    # para no romper la estructura de carpetas que arma main.py.
    fecha_datos = _fecha_negocio_del_xml(archivo_revenue_xml) or fecha_reporte
    if fecha_datos.date() != fecha_reporte.date():
        logger.warning(
            f"El XML contiene datos del {fecha_datos:%d/%m/%Y}, no del "
            f"{fecha_reporte:%d/%m/%Y}. Se busca el asiento por la fecha de los datos."
        )
    fecha_busqueda = fecha_datos.strftime("%d/%m/%Y")             # DD/MM/YYYY para el filtro
    descripcion_busqueda = f"OPL - Ingresos Opera/Simphony {fecha_busqueda}"

    archivos = []

    with sync_playwright() as playwright:
        # SIEMPRE se fija un viewport de escritorio, con o sin headless.
        #
        # Integrity es responsive: si la ventana es angosta colapsa el menu
        # superior en un menu movil y el boton "Configuracion" ni siquiera se
        # renderiza en el DOM, asi que no hay forma de navegar a Cargar revenue.
        #
        # Antes, con headless=False (que es como lo llama main.py) se usaba
        # "--start-maximized" + no_viewport. Eso funciona en una PC con
        # escritorio, pero NO bajo Xvfb en el contenedor: ahi no corre ningun
        # gestor de ventanas, y "--start-maximized" es solo una sugerencia que
        # implementa el gestor. Sin el, la ventana se queda en su tamaño por
        # defecto (~800px) aunque la pantalla virtual sea de 1920x1080.
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--window-size=1920,1080"],
        )
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # Playwright descarta solo los dialogos nativos (confirm/alert) cuando
        # corre como script — no asi al grabar con codegen, donde los responde
        # la persona. Si Integrity lanza un confirm() nativo al cargar, sin
        # este handler se cancelaria en silencio y el flujo quedaria trabado
        # esperando un modal que nunca llega.
        page.on("dialog", lambda dialogo: (
            logger.info(f"Dialogo nativo aceptado: {dialogo.message[:200]}"),
            dialogo.accept(),
        ))

        # Instrumentacion: cuando un click "no hace nada" la causa suele estar
        # en un error de JS o en una peticion que fallo, cosas invisibles desde
        # el DOM. Se loguean para no tener que deducirlas a ciegas.
        page.on("pageerror", lambda err: logger.error(f"[JS-ERROR] {str(err)[:300]}"))
        page.on("console", lambda msg: (
            logger.error(f"[JS-CONSOLE-{msg.type}] {msg.text[:300]}")
            if msg.type in ("error", "warning") else None
        ))
        page.on("requestfailed", lambda req: logger.error(
            f"[RED-FALLIDA] {req.method} {req.url[:200]} — {req.failure}"
        ))
        page.on("response", lambda resp: (
            logger.error(f"[HTTP-{resp.status}] {resp.request.method} {resp.url[:200]}")
            if resp.status >= 400 else None
        ))
        page.on("load", lambda p: logger.info(f"[NAV] Pagina (re)cargada: {p.url[:200]}"))

        try:
            _ejecutar_flujo_integrity(
                page, usuario, password, archivo_revenue_xml,
                descripcion_busqueda, carpeta_destino, fecha_str, archivos,
            )
        except Exception:
            _guardar_diagnostico(page, carpeta_destino)
            raise
        finally:
            context.close()
            browser.close()

    logger.info(f"Integrity: {len(archivos)} archivo(s) descargado(s) en {carpeta_destino}")
    return archivos


def _guardar_diagnostico(page, carpeta_destino: Path) -> None:
    """Al fallar, guarda screenshot + HTML y ADEMAS loguea que pagina se estaba
    viendo (URL, titulo y texto visible). En Railway la carpeta temporal se
    borra, pero el log queda — y con el texto de la pagina se ve exactamente
    que le mostro el sitio al bot (login fallido, error, otra pagina, etc.)."""
    debug_dir = carpeta_destino / "debug"
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        page.screenshot(path=str(debug_dir / f"error_{timestamp}.png"), full_page=True)
        (debug_dir / f"error_{timestamp}.html").write_text(page.content(), encoding="utf-8")
        logger.error(f"Diagnostico del error guardado en: {debug_dir}")
    except Exception as e:
        logger.error(f"No se pudo guardar el diagnostico del error: {e}")

    # Volcar al log que pagina se estaba viendo (siempre, aunque falle lo anterior)
    try:
        logger.error(f"[DIAG] URL actual: {page.url}")
        logger.error(f"[DIAG] Titulo: {page.title()}")
        texto = page.locator("body").inner_text(timeout=5000)
        # Solo los primeros 1500 caracteres, sin lineas vacias
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        resumen = " | ".join(lineas)[:1500]
        logger.error(f"[DIAG] Texto visible de la pagina: {resumen}")
    except Exception as e:
        logger.error(f"[DIAG] No se pudo extraer el texto de la pagina: {e}")

    # Listar los botones/inputs reales del DOM con su id y texto. Cuando el
    # sitio cambia, esto muestra de una que selector hay que usar en vez de
    # tener que adivinar por que un click "no hizo nada".
    try:
        controles = page.evaluate(
            "() => Array.from(document.querySelectorAll('button, input[type=button], "
            "input[type=submit], input[type=file], a.btn')).map(el => ({"
            "tag: el.tagName, id: el.id, tipo: el.type || '', "
            "texto: (el.innerText || el.value || '').trim().slice(0, 60), "
            "visible: !!(el.offsetWidth || el.offsetHeight)}))"
        )
        logger.error(f"[DIAG] Controles en la pagina ({len(controles)}):")
        for ctrl in controles:
            logger.error(f"[DIAG]   {ctrl}")
    except Exception as e:
        logger.error(f"[DIAG] No se pudieron listar los controles: {e}")


def _ejecutar_flujo_integrity(
    page, usuario, password, archivo_revenue_xml,
    descripcion_busqueda, carpeta_destino, fecha_str, archivos,
) -> None:
        # -- Login --------------------------------------------------------------
        # Regla general en este modulo: NO esperar estados globales de pagina
        # ("load" / "networkidle"), sino el elemento concreto que se va a usar.
        # El sitio tiene control de sesion que hace peticiones periodicas, asi
        # que la red puede no quedar nunca quieta, y un solo recurso lento
        # (imagen, fuente, script externo) basta para que "load" no dispare
        # aunque la pagina ya este perfectamente usable.
        # Marca de version: sirve para saber de un vistazo si el contenedor esta
        # corriendo el codigo actual o una imagen vieja sin reconstruir.
        logger.info(f"[VERSION] integrity.py {VERSION_MODULO}")
        logger.info("Login en Integrity...")
        page.goto(INTEGRITY_URL, wait_until="domcontentloaded", timeout=60000)

        campo_usuario = page.get_by_role("textbox", name="Usuario")
        campo_usuario.wait_for(state="visible", timeout=60000)
        campo_usuario.fill(usuario)
        page.get_by_role("textbox", name="Contrasena").or_(
            page.get_by_role("textbox", name="Contraseña")
        ).fill(password)

        # Se clickea #btnIngresar por ID: en la pagina hay DOS controles con el
        # nombre "Ingresar" (btnIngresar visible y btnIngresarComp oculto), asi
        # que buscarlos por rol es ambiguo.
        page.locator("#btnIngresar").click()

        # -- Segundo paso: seleccion de compañia --------------------------------
        # El formulario trae un combo #cbCompanias y un segundo boton
        # #btnIngresarComp, ambos ocultos al cargar. Si el usuario tiene mas de
        # una compañia, tras "Ingresar" aparecen y hay que elegir una para
        # entrar. En un navegador con sesion previa este paso puede no verse
        # (por eso no salio al grabar), pero el contenedor arranca siempre
        # limpio y ahi si aparece: sin esto el proceso se queda en el login.
        combo_compania = page.locator("#cbCompanias")
        try:
            combo_compania.wait_for(state="visible", timeout=10000)
            opciones = combo_compania.evaluate(
                "el => Array.from(el.options).map(o => ({valor: o.value, texto: o.text.trim()}))"
            )
            logger.info(f"Paso de compañia detectado. Opciones: {opciones}")

            # Se puede fijar cual con INTEGRITY_COMPANIA en el .env; si no, se
            # toma la primera opcion que tenga un valor real.
            deseada = os.getenv("INTEGRITY_COMPANIA")
            if deseada:
                combo_compania.select_option(label=deseada)
                logger.info(f"Compañia seleccionada por configuracion: {deseada}")
            else:
                validas = [o for o in opciones if o["valor"]]
                if not validas:
                    raise RuntimeError(f"El combo de compañias no trae opciones: {opciones}")
                combo_compania.select_option(value=validas[0]["valor"])
                logger.info(f"Compañia seleccionada (primera): {validas[0]['texto']}")

            page.locator("#btnIngresarComp").click()
        except Exception as e:
            logger.info(f"Sin paso de compañia (o no fue necesario): {e}")

        # Verificar que el login REALMENTE funciono. Antes esto se ignoraba con
        # un "except: pass", y el proceso seguia sin sesion: el sintoma aparecia
        # mucho despues como un 404 o un timeout buscando #fuPlantilla, que no
        # tienen nada que ver con la causa.
        try:
            page.wait_for_url("**/Menu.aspx", timeout=60000)
            logger.info("Login correcto.")
        except Exception:
            if "/login" in page.url or "index.aspx" in page.url:
                # Seguimos en la pantalla de login: capturar el mensaje que
                # muestre el sitio (credenciales, paso extra, bloqueo, etc.).
                try:
                    texto = page.locator("body").inner_text(timeout=5000)
                    resumen = " | ".join(l.strip() for l in texto.splitlines() if l.strip())[:600]
                except Exception:
                    resumen = "(no se pudo leer el texto de la pagina)"
                _listar_menu(page)
                raise RuntimeError(
                    f"El login no paso: seguimos en {page.url}\n"
                    f"Texto de la pagina: {resumen}\n"
                    "Puede ser un cambio en la pantalla de login (por ejemplo un "
                    "paso extra de compañia: existe un boton oculto btnIngresarComp) "
                    "o credenciales rechazadas."
                )
            logger.warning(f"No se llego a Menu.aspx; URL actual: {page.url}. Se continua.")

        # -- Ir a Cargar revenue ------------------------------------------------
        # La ruta se LEE del menu en vez de estar fija: el sitio ya la movio dos
        # veces en agosto de 2026. Se toma el href del enlace (no se clickea),
        # porque el enlace vive dentro de un desplegable y Playwright no puede
        # clickear lo que no esta visible — pero el atributo si se puede leer
        # aunque el desplegable este cerrado.
        logger.info("Abriendo Cargar revenue...")
        destino_revenue = None
        try:
            enlace = page.locator("a").filter(has_text=re.compile("revenue", re.I)).first
            enlace.wait_for(state="attached", timeout=20000)
            href = enlace.get_attribute("href")
            if href:
                destino_revenue = href if href.startswith("http") else f"{BASE_URL}{href}"
                logger.info(f"Ruta de Cargar revenue tomada del menu: {destino_revenue}")
        except Exception as e:
            logger.warning(f"No se pudo leer la ruta desde el menu: {e}")

        if not destino_revenue:
            destino_revenue = CARGAR_REVENUE_URL
            logger.info(f"Usando la ruta de respaldo: {destino_revenue}")

        page.goto(destino_revenue, wait_until="domcontentloaded", timeout=60000)

        # Si no se llego a la pagina, cortar con un error claro: sin esto el
        # sintoma seria un timeout de 30s buscando #fuPlantilla, que no explica
        # nada. Se lista el menu para ver donde quedo la opcion.
        if "cannot be found" in (page.title() or ""):
            try:
                page.goto(MENU_URL, wait_until="domcontentloaded", timeout=30000)
                _listar_menu(page)
            except Exception as e:
                logger.error(f"No se pudo listar el menu: {e}")
            raise RuntimeError(
                f"La pagina de carga de revenue no existe (HTTP 404) en: {destino_revenue}\n"
                "Revisa el listado [MENU] en el log para ver donde quedo la opcion."
            )

        # -- Seleccionar y CARGAR el archivo ------------------------------------
        # Se apunta al <input type=file> real (#fuPlantilla), NO al boton
        # "Cargar revenue" por rol: ese boton no es el input ni su <label>, asi
        # que adjuntar ahi funcionaba de casualidad — algunos dias el archivo
        # quedaba adjunto y otros no, y ese era el origen de la intermitencia.
        logger.info(f"Cargando archivo: {archivo_revenue_xml.name}...")
        input_archivo = page.locator("#fuPlantilla")
        input_archivo.wait_for(state="attached", timeout=30000)
        input_archivo.set_input_files(str(archivo_revenue_xml))

        # Verificar que el archivo QUEDO adjunto antes de seguir. Sin esto, si
        # el adjunto falla el sitio no hace nada al clickear "Cargar" y el error
        # aparece 30s despues como "no aparecio Confirmar", que no dice nada
        # sobre la causa real.
        valor_input = input_archivo.evaluate("el => el.value")
        if not valor_input:
            raise RuntimeError(
                f"El archivo no quedo adjunto en #fuPlantilla: {archivo_revenue_xml}"
            )
        logger.info(f"Archivo adjunto correctamente: {valor_input}")

        # Pausa antes de clickear "Cargar": el sitio parece subir el archivo por
        # AJAX al detectar el change del input, y clickear de inmediato (96 ms)
        # es clickear antes de que termine. La corrida que funciono tenia ~3,5 s
        # entre adjuntar y clickear; sin esta pausa el boton no hace efecto.
        page.wait_for_timeout(3000)

        # Confirmar la carga: Cargar -> Confirmar -> Close
        # El boton "Cargar" se ubica por ID exacto btnCargarAsientoJS. NO usar
        # get_by_role(name="Cargar"): su nombre accesible arranca con el glifo
        # del icono, asi que exact=True no matchea y sin exact matchea tambien
        # el boton de archivo "Cargar revenue" (violacion de modo estricto).
        # Se captura la peticion POST que dispara el click junto con la respuesta
        # del servidor. Es el unico dato que faltaba: el JS corre sin errores y
        # limpia el input (o sea, proceso el archivo), pero el modal no aparece,
        # asi que la explicacion tiene que estar en lo que contesta el servidor.
        respuesta_upload = None
        try:
            with page.expect_response(
                lambda r: r.request.method == "POST", timeout=20000
            ) as resp_info:
                page.locator("#btnCargarAsientoJS").click()
            respuesta_upload = resp_info.value
        except Exception as e:
            logger.error(f"[UPLOAD] No se detecto ninguna peticion POST tras el click: {e}")

        if respuesta_upload is not None:
            logger.info(
                f"[UPLOAD] POST {respuesta_upload.url[:200]} -> HTTP {respuesta_upload.status}"
            )
            try:
                logger.info(f"[UPLOAD] Respuesta del servidor: {respuesta_upload.text()[:1000]}")
            except Exception as e:
                logger.info(f"[UPLOAD] No se pudo leer el cuerpo de la respuesta: {e}")

        # Chequeo temprano: si tras el click el input quedo vacio, hubo un
        # postback/recarga que descarto el archivo, y esperar "Confirmar" 30s
        # solo tapa el problema real. Se reporta al toque y con la causa.
        page.wait_for_timeout(2000)
        try:
            valor_post_click = input_archivo.evaluate("el => el.value")
        except Exception:
            valor_post_click = "<input ya no existe en el DOM>"
        logger.info(f"Estado de #fuPlantilla tras clickear Cargar: '{valor_post_click}'")

        # Confirmar / Close son OPCIONALES: la carga se completa sola con el
        # click en "Cargar" (lo prueban los asientos que quedaban creados en
        # corridas que "fallaban" justo aca). El modal no siempre aparece, asi
        # que exigirlo bloqueaba todo el flujo — incluida la descarga, que es
        # lo unico que faltaba — esperando algo que no llega.
        confirmar = page.get_by_role("button", name="Confirmar").or_(
            page.get_by_role("link", name="Confirmar")
        ).or_(
            page.locator("input[value='Confirmar' i]")
        ).first
        try:
            confirmar.wait_for(state="visible", timeout=10000)
            confirmar.click()
            logger.info("Modal de confirmacion aceptado.")
        except Exception:
            logger.info("No aparecio el modal de confirmacion; la carga se completo sola.")

        close_btn = page.get_by_role("button", name="Close")
        try:
            close_btn.wait_for(state="visible", timeout=5000)
            close_btn.click()
        except Exception:
            pass  # sin modal no hay nada que cerrar

        logger.info("Revenue cargado correctamente.")

        # -- Buscar el asiento OPL del dia --------------------------------------
        # Se espera el buscador (el elemento que realmente se necesita) en vez
        # del estado de red, que en este sitio puede no quedar nunca quieto.
        logger.info(f"Buscando asiento: {descripcion_busqueda}...")
        # Interfaz nueva (27/08/2026): se entra por el link "Nuevo asiento
        # Registrar"; antes era una tarjeta con clase .card-pro, que ya no
        # existe. Se deja la vieja como respaldo.
        try:
            page.get_by_role("link", name="Nuevo asiento Registrar").click(timeout=20000)
        except Exception:
            logger.info("No se hallo 'Nuevo asiento Registrar'; probando .card-pro.")
            page.locator(".card-pro").first.click(timeout=20000)

        # El ID del buscador tambien cambio con el rediseño.
        buscador = page.locator("#txtAsientos_EncVOUDESHeader").or_(
            page.locator("#txtVOUDESHeader")
        ).first
        buscador.wait_for(state="visible", timeout=60000)
        buscador.click()
        buscador.fill(descripcion_busqueda)
        buscador.press("Enter")
        page.wait_for_timeout(2000)

        # Si la busqueda no devolvio filas, cortar con un error que diga QUE se
        # busco. Sin esto el sintoma era un timeout de 30s sobre el menu de una
        # fila inexistente, que no dice nada sobre la causa.
        filas = page.get_by_role("row", name="OPL - Ingresos Opera/")
        if filas.count() == 0:
            raise RuntimeError(
                f"No se encontro ningun asiento '{descripcion_busqueda}' en Integrity. "
                "Revisa que la carga del revenue haya generado el asiento de esa fecha."
            )

        # -- Descargar el Excel del asiento -------------------------------------
        logger.info(f"Descargando Excel del asiento ({filas.count()} fila(s) encontrada(s))...")
        # Interfaz nueva (27/08/2026): la descarga es un icono de Excel en la
        # fila, que baja el archivo directo. Antes habia que abrir el menu ⋮,
        # elegir "Generar excel" y esperar un popup; nada de eso existe ya.
        icono_excel = page.locator(".bi.bi-file-earmark-excel-fill").first
        icono_excel.wait_for(state="visible", timeout=30000)
        with page.expect_download() as dl_info:
            icono_excel.click()
        archivos.append(_guardar(dl_info.value, carpeta_destino, "INTEGRITY_OPL", fecha_str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ayer = datetime.now() - timedelta(days=1)
    fecha_str = ayer.strftime("%Y-%m-%d")
    base_drive = os.getenv(
        "DRIVE_BASE_PATH",
        r"G:\Mi unidad\Projecto Auditoria Diaria\Auditoria Corcovado\Inputs",
    )
    xml_revenue = (
        Path(base_drive) / fecha_str / "opera" / f"OPERA_GEN_XMLBO_REVENUE_{fecha_str}.xml"
    )
    carpeta_integrity = Path(base_drive) / fecha_str / "integrity"
    print(f"Buscando archivo: {xml_revenue}")
    subir_revenue_y_descargar(xml_revenue, carpeta_integrity, fecha_reporte=ayer, headless=False)
