"""
modulos/ors.py

Descarga los reportes de "Reporting, Analytics and People" (ORS):
  1. Reporte general (sin filtro de local) para la fecha de negocio
  2. Reporte "My Reports" para el local Corcovado
  3. Reporte "My Reports" para el local Terra Kitchen

Credenciales esperadas en el archivo .env del proyecto (no se escriben
directo en el código):
    ORS_USERNAME=JOSUE RETANA
    ORS_ENTERPRISE=CVO
    ORS_PASSWORD=tu_password_aqui
"""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

logger = logging.getLogger(__name__)

ORS_URL = "https://ors-idm.us07.oraclerestaurants.com/oidc-ui/"
SELECTOR_FLECHA_LOCAL = (
    "#search_locations_select > .oj-text-field-container.oj-searchselect-main-field "
    "> .oj-text-field-end > .oj-searchselect-arrow"
)


def _fecha_negocio() -> datetime:
    """
    Fecha de negocio que se selecciona en el reporte.
    Por defecto: el día anterior al de hoy (así estaba grabado: el 18 de
    junio se grabó seleccionando el 17). Si en realidad debe ser el día
    de hoy, cambiá "timedelta(days=1)" por "timedelta(days=0)".
    """
    return datetime.now() - timedelta(days=1)


def _nombre_dia_calendario(fecha: datetime) -> tuple[str, str]:
    """
    Devuelve (numero_dia, descripcion) tal como los necesita el selector
    del calendario, ej: ("17", "Select Wednesday, Jun 17, 2026")
    """
    numero_dia = str(fecha.day)
    descripcion = f"Select {fecha.strftime('%A')}, {fecha.strftime('%b')} {fecha.day}, {fecha.year}"
    return numero_dia, descripcion


def _guardar_descarga(descarga, carpeta_destino: Path, prefijo: str, fecha_str: str) -> Path:
    extension = Path(descarga.suggested_filename).suffix or ".xlsx"
    destino = carpeta_destino / f"{prefijo}_{fecha_str}{extension}"
    descarga.save_as(destino)
    logger.info(f"Guardado: {destino}")
    return destino


def descargar_reportes_ors(carpeta_destino: Path, headless: bool = False) -> list[Path]:
    """
    Ejecuta el proceso completo de ORS y guarda los 3 Excel descargados
    en carpeta_destino. Devuelve la lista de rutas guardadas.
    """
    carpeta_destino = Path(carpeta_destino)
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    usuario = os.getenv("ORS_USERNAME")
    enterprise = os.getenv("ORS_ENTERPRISE")
    password = os.getenv("ORS_PASSWORD")
    if not all([usuario, enterprise, password]):
        raise RuntimeError("Faltan ORS_USERNAME / ORS_ENTERPRISE / ORS_PASSWORD en el .env")

    fecha = _fecha_negocio()
    fecha_str = fecha.strftime("%Y-%m-%d")  # fecha del reporte = ayer
    numero_dia, descripcion_dia = _nombre_dia_calendario(fecha)

    archivos_guardados: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=["--start-maximized"])
        context = browser.new_context(accept_downloads=True, no_viewport=True)
        page = context.new_page()

        logger.info("Iniciando login en ORS...")
        page.goto(ORS_URL)
        page.wait_for_load_state("networkidle", timeout=60000)  # esperar que el OIDC cargue el formulario
        page.get_by_role("textbox", name="Email or User Name").fill(usuario)
        page.get_by_role("textbox", name="Enterprise Name").fill(enterprise)
        page.get_by_role("textbox", name="Password").fill(password)
        # Sign In redirige a Oracle SSO y de vuelta a ORS — la navegación puede causar
        # "Target page closed". Usamos dispatch_event para no esperar el click completo
        # y luego esperamos que la página final cargue.
        try:
            page.get_by_test_id("login-form-signin-button").get_by_role("button", name="Sign In").click()
        except Exception:
            pass  # La navegación SSO puede "cerrar" la página durante el click
        page.wait_for_load_state("networkidle", timeout=60000)

        # ---- Reporte 1: general, sin filtro de local ----
        logger.info("Descargando reporte general...")
        page.locator("#link_100357").click()
        page.get_by_role("button", name="Edit Parameters").click()
        page.get_by_role("link", name="Advanced Business Dates").click()
        page.get_by_role("link", name=numero_dia, description=descripcion_dia, exact=True).click()
        page.get_by_role("button", name="Apply").click()
        page.get_by_role("button", name="Run").click()
        page.get_by_role("button", name="Download").click()
        with page.expect_download() as descarga_info:
            page.get_by_role("menuitem", name="Microsoft Excel (.xlsx)").click()
        archivos_guardados.append(_guardar_descarga(descarga_info.value, carpeta_destino, "ORS_General", fecha_str))

        # ---- Reporte 2: My Reports, un local a la vez ----
        page.get_by_role("tab", name="Dashboard").click()
        page.get_by_role("tab", name="My Reports").click()
        page.locator("#link_17202").click()
        page.get_by_role("link", name="Advanced Business Dates").click()
        page.get_by_role("link", name=numero_dia, description=descripcion_dia, exact=True).click()
        page.get_by_role("button", name="Apply").click()

        locales = ["Corcovado", "Terra Kitchen"]
        for i, local in enumerate(locales):
            logger.info(f"Descargando reporte de {local}...")
            if i > 0:
                page.get_by_role("button", name="Edit Parameters").click()
            page.locator(SELECTOR_FLECHA_LOCAL).click()
            if local == "Corcovado":
                page.get_by_text(local, exact=True).click()
            else:
                page.get_by_text(local).click()
            page.get_by_role("button", name="Run").click()
            page.get_by_role("button", name="Download").click()
            with page.expect_download() as descarga_info:
                page.get_by_role("menuitem", name="Microsoft Excel (.xlsx)").click()
            archivos_guardados.append(
                _guardar_descarga(descarga_info.value, carpeta_destino, f"ORS_{local.replace(' ', '')}", fecha_str)
            )

        context.close()
        browser.close()

    return archivos_guardados


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    carpeta_prueba = Path(__file__).resolve().parent.parent / "descargas-prueba" / datetime.now().strftime("%Y-%m-%d")
    descargar_reportes_ors(carpeta_prueba, headless=False)
