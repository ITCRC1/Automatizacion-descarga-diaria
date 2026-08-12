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
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

logger = logging.getLogger(__name__)

INTEGRITY_URL = "https://www.programarcr.com/conta506/index.aspx"
CARGAR_REVENUE_URL = "https://www.programarcr.com/Conta506/forms/7_configuracion/1_opera/frmParametros_OperaCargarRevenue.aspx"


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
    fecha_busqueda = fecha_reporte.strftime("%d/%m/%Y")          # DD/MM/YYYY para el filtro
    descripcion_busqueda = f"OPL - Ingresos Opera/Simphony {fecha_busqueda}"

    archivos = []

    with sync_playwright() as playwright:
        # En modo headless (Railway) es OBLIGATORIO fijar un viewport grande:
        # con no_viewport la ventana headless queda en tamaño minimo (~800px) y
        # el sitio de Integrity, al ser responsive, colapsa el menu superior en
        # un menu movil — el boton "Configuracion" ni siquiera se renderiza en
        # el DOM y todo el flujo falla. Con 1920x1080 se muestra el layout de
        # escritorio, igual que en la PC local. (Mismo enfoque que opera.py.)
        if headless:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1920, "height": 1080},
            )
        else:
            browser = playwright.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(
                accept_downloads=True,
                no_viewport=True,
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
        logger.info("Login en Integrity...")
        page.goto(INTEGRITY_URL)
        page.wait_for_load_state("networkidle", timeout=60000)
        page.get_by_role("textbox", name="Usuario").click()
        page.get_by_role("textbox", name="Usuario").fill(usuario)
        page.get_by_role("textbox", name="Contrasena").or_(
            page.get_by_role("textbox", name="Contraseña")
        ).fill(password)
        page.get_by_role("button", name="Ingresar").click()

        # Tras "Ingresar", Integrity redirige a Menu.aspx. Esa redireccion a
        # veces tarda, y si se intenta clickear "Configuracion" antes de que
        # el menu termine de cargar, falla con Timeout (el boton aun no existe).
        # Por eso se espera explicitamente: primero que la navegacion a Menu
        # termine, y luego que el boton este realmente visible, con reintentos.
        page.wait_for_load_state("networkidle", timeout=60000)
        try:
            page.wait_for_url("**/Menu.aspx", timeout=30000)
        except Exception:
            pass  # si ya estaba en Menu.aspx o la URL difiere, seguimos

        # -- Ir directo a Cargar revenue ----------------------------------------
        # No se navega por el menu: la pagina de carga tiene URL propia y
        # navegar directo funciona siempre. (Los logs historicos muestran que
        # incluso en local el flujo terminaba yendo por URL: "Link directo no
        # disponible, usando navegacion por URL..." — el menu nunca fue
        # necesario y en headless su boton ni siquiera es localizable.)
        logger.info("Abriendo Cargar revenue (navegacion directa)...")
        page.goto(CARGAR_REVENUE_URL)
        page.wait_for_load_state("networkidle", timeout=60000)

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

        page.wait_for_load_state("networkidle", timeout=60000)
        logger.info("Revenue cargado correctamente.")

        # -- Buscar el asiento OPL del dia --------------------------------------
        logger.info(f"Buscando asiento: {descripcion_busqueda}...")
        page.locator(".card-pro").first.click()
        page.wait_for_load_state("networkidle", timeout=60000)
        page.wait_for_timeout(1000)

        buscador = page.locator("#txtVOUDESHeader")
        buscador.click()
        buscador.fill(descripcion_busqueda)
        buscador.press("Enter")
        page.wait_for_timeout(2000)

        # -- Descargar el Excel del asiento -------------------------------------
        logger.info("Descargando Excel del asiento...")
        # Puede haber mas de un asiento cuyo nombre contenga esta descripcion
        # (p.ej. un duplicado de un intento anterior). Se toma el mas reciente.
        fila = page.get_by_role("row", name="OPL - Ingresos Opera/").last
        fila.locator("#dropdownMenuButton").click()
        page.wait_for_timeout(800)
        with page.expect_download() as dl_info:
            with page.expect_popup() as popup_info:
                # Se busca DENTRO de la fila, no en toda la pagina: cada asiento
                # tiene su propio "Generar excel", asi que buscarlo global falla
                # por modo estricto en cuanto hay mas de un asiento con la misma
                # descripcion (y podria bajar el Excel del asiento equivocado).
                fila.get_by_text("Generar excel").click()
            popup = popup_info.value

        # El popup es el que ejecuta la descarga: se cierra DESPUES de que el
        # archivo termino de bajar. Cerrarlo antes (como estaba) puede abortarla.
        descarga = dl_info.value
        try:
            popup.close()
        except Exception:
            pass  # el popup pudo cerrarse solo al terminar la descarga
        archivos.append(_guardar(descarga, carpeta_destino, "INTEGRITY_OPL", fecha_str))


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
