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
CARGAR_REVENUE_URL = "https://www.programarcr.com/Conta506/forms/frmParametros_OperaCargarRevenue.aspx"


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
        logger.info(f"Cargando archivo: {archivo_revenue_xml.name}...")
        page.get_by_role("button", name="Cargar revenue").set_input_files(str(archivo_revenue_xml))
        page.wait_for_timeout(1000)

        # Confirmar la carga: Cargar -> Confirmar -> Close
        # El boton "Cargar" tiene ID exacto btnCargarAsientoJS (evita confundirlo
        # con el input de archivo que tambien matchea por accesibilidad).
        page.locator("#btnCargarAsientoJS").click()

        # "Confirmar" aparece en un dialogo SOLO cuando la carga es nueva. Si el
        # revenue de esta fecha YA se cargo antes (re-corrida del mismo dia),
        # Integrity no muestra ese dialogo y esperar "Confirmar" falla con
        # Timeout. Eso NO es un error real: el asiento ya existe de la carga
        # anterior, asi que se continua directo a buscarlo y descargarlo.
        confirmar = page.get_by_role("button", name="Confirmar")
        try:
            confirmar.wait_for(state="visible", timeout=20000)
            confirmar.click()
            close_btn = page.get_by_role("button", name="Close")
            close_btn.wait_for(state="visible", timeout=20000)
            close_btn.click()
            page.wait_for_load_state("networkidle", timeout=60000)
            logger.info("Revenue cargado y confirmado correctamente.")
        except Exception:
            logger.warning(
                "No aparecio 'Confirmar' — el revenue de esta fecha ya estaba "
                "cargado (re-corrida del mismo dia). Se continua a buscar el "
                "asiento existente."
            )
            for cerrar in ("Close", "Cerrar"):
                try:
                    page.get_by_role("button", name=cerrar).click(timeout=2000)
                except Exception:
                    pass
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(1000)

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
                page.get_by_text("Generar excel").click()
            popup_info.value.close()
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
