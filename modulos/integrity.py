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
        # Chromium con ventana grande para evitar descuadres en la UI

        browser = playwright.chromium.launch(headless=headless, args=["--start-maximized"])
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
    """Al fallar, guarda screenshot + HTML de la pagina para diagnosticar despues."""
    debug_dir = carpeta_destino / "debug"
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        page.screenshot(path=str(debug_dir / f"error_{timestamp}.png"), full_page=True)
        (debug_dir / f"error_{timestamp}.html").write_text(page.content(), encoding="utf-8")
        logger.error(f"Diagnostico del error guardado en: {debug_dir}")
    except Exception as e:
        logger.error(f"No se pudo guardar el diagnostico del error: {e}")


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

        # -- Configuracion -> Cargar revenue ------------------------------------
        logger.info("Abriendo Configuracion -> Cargar revenue...")
        boton_config = page.get_by_role("button", name="Configuracion").or_(
            page.get_by_role("button", name="Configuración")
        )
        # Reintentar hasta 4 veces: esperar que el boton este visible y clickear.
        # Cubre el caso intermitente donde el menu tarda en renderizar.
        ultimo_error = None
        for intento in range(4):
            try:
                boton_config.wait_for(state="visible", timeout=15000)
                boton_config.click()
                break
            except Exception as e:
                ultimo_error = e
                logger.info(
                    f"Menu aun no listo (intento {intento + 1}/4), reintentando..."
                )
                page.wait_for_timeout(2000)
                # Recargar el menu por si quedo a medio cargar
                if intento == 2:
                    try:
                        page.goto("https://www.programarcr.com/Conta506/Menu.aspx")
                        page.wait_for_load_state("networkidle", timeout=30000)
                    except Exception:
                        pass
        else:
            raise RuntimeError(
                f"No se pudo abrir 'Configuracion' tras varios intentos: {ultimo_error}"
            )

        page.wait_for_timeout(1000)
        try:
            page.get_by_role("link", name="Cargar revenue").click(timeout=8000)
        except Exception:
            logger.info("Link directo no disponible, usando navegacion por URL...")
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

        # "Confirmar" aparece en un dialogo que puede tardar en renderizar.
        # Se espera a que este visible antes de clickear (evita Timeout).
        confirmar = page.get_by_role("button", name="Confirmar")
        confirmar.wait_for(state="visible", timeout=30000)
        confirmar.click()

        # "Close" cierra el dialogo de resultado; tambien puede tardar.
        close_btn = page.get_by_role("button", name="Close")
        close_btn.wait_for(state="visible", timeout=30000)
        close_btn.click()
        page.wait_for_load_state("networkidle", timeout=60000)
        logger.info("Revenue cargado y confirmado correctamente.")

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
