"""
modulos/opera.py

Descarga los 9 archivos de Opera Cloud para COWLCR:

  Reports → Manage Reports:
    1. History and Forecast (parámetros por defecto)         → XML
    2. History and Forecast (Total Revenue)                  → XML
    3. Trial Balance                                         → XML
    4. Statistics - Room Type (01-ene año actual → hoy)      → XML

  Miscellaneous → Exports → General:
    5. Export General #1 (Actions fila 1)
    6. Export General #2 (Actions fila 2)
    7. Export General #3 (Actions fila 3)
    8. Export General #4 (Actions fila 6)
    9. Export General #5 (Actions fila 8)

Credenciales esperadas en .env:
    OPERA_USERNAME=tu_usuario
    OPERA_PASSWORD=tu_password
"""

import os
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

logger = logging.getLogger(__name__)

OPERA_URL = (
    "https://mtcu11.oraclehospitality.us-ashburn-1.ocs.oraclecloud.com"
    "/ECRWLG/operacloud/faces/opera-cloud-index/OperaCloud"
)
LOGIN_URL = (
    "https://idcs-2a66451eca3945c8812bb54a4010565a.identity.oraclecloud.com"
    "/ui/v1/signin"
)

# Selector del botón de búsqueda en Manage Reports (el mismo en todas las búsquedas)
BTN_BUSCAR = (
    "[id=\"pt1:oc_pg_pt:mainRegion:1:pt1:oc_pnl_lst_cmp:oc_scrn_pnl_lst_tmpl"
    ":oc_scrn_tmpl_by43sy:oc_pnl_lst_tmpl:oc_pnl_lstng_tmpl:oc_pnl_tmpl_by43sy"
    ":oc_pnl_lstng_vw_srch_swtchr:odec_srch_swtchr_advncd_sf"
    ":odec_srch_swtchr_advncd_srch_btn\"]"
)

# Selectores robustos sin el sufijo dinámico (oc_scrn_tmpl_XXXXX cambia por sesión)
BTN_CONFIRMAR_EXPORT = "[id*='odec_axn_br_axn_pstv']"

# Botón de 3 puntos (⋮) de la primera fila en Generated Exports
LINK_DESCARGA_EXPORT = "a[id*=':t1:0:ra1:odec_rw_axns_mrlnk']"  # solo el <a>, no el <span>


def _guardar(descarga, carpeta: Path, prefijo: str, fecha_str: str) -> Path:
    extension = Path(descarga.suggested_filename).suffix or ".xml"
    destino = carpeta / f"{prefijo}_{fecha_str}{extension}"
    descarga.save_as(destino)
    logger.info(f"Guardado: {destino.name}")
    return destino


def _buscar_reporte(page, nombre: str):
    """Limpia el campo, escribe el nombre y hace click en Buscar."""
    campo = page.get_by_role("textbox", name="Report Name")
    campo.click()
    campo.fill(nombre)
    page.locator(BTN_BUSCAR).click()


def _descargar_reporte_xml(page, carpeta: Path, prefijo: str, fecha_str: str) -> Path:
    """Hace click en Download As → XML → Download, cierra el popup y guarda el archivo."""
    page.get_by_role("button", name="Download As...").click()
    page.get_by_text("XML").click()
    with page.expect_download() as dl_info:
        with page.expect_popup() as popup_info:
            page.get_by_role("button", name="Download", exact=True).click()
    popup_info.value.close()
    return _guardar(dl_info.value, carpeta, prefijo, fecha_str)


def _view_exports_y_descargar(page, carpeta: Path, prefijo: str, fecha_str: str, confirmar: bool = False) -> Path:
    """Dentro de la lista de exports: clic en el primer row, Download, y opcional confirm."""
    # 1. Entrar a Generated Exports
    page.get_by_role("link", name="View Exports").click()
    page.wait_for_load_state("networkidle")

    # 2. Abrir el menú ⋮ de la primera fila.
    #    El menú a veces tarda en abrir, así que reintentamos hasta que
    #    "Download" sea visible antes de continuar.
    download_link = page.get_by_role("link", name="Download")
    for intento in range(3):
        page.locator(LINK_DESCARGA_EXPORT).click()
        page.wait_for_timeout(1000)
        try:
            download_link.wait_for(state="visible", timeout=5000)
            break  # el menú abrió y Download está visible
        except Exception:
            if intento == 2:
                raise  # se agotaron los reintentos
            page.wait_for_timeout(1000)  # reintentar

    # 3. Descargar
    with page.expect_download() as dl_info:
        download_link.click()
    archivo = _guardar(dl_info.value, carpeta, prefijo, fecha_str)

    # 4. Confirmar (si aplica) y volver al estado estable
    if confirmar:
        page.locator(BTN_CONFIRMAR_EXPORT).click()
        page.wait_for_load_state("networkidle")
    return archivo


def descargar_opera(carpeta_destino: Path, headless: bool = False) -> list[Path]:
    """
    Ejecuta el proceso completo de Opera Cloud y guarda los 9 archivos en
    carpeta_destino. Devuelve la lista de rutas guardadas.
    """
    carpeta_destino = Path(carpeta_destino)
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    usuario = os.getenv("OPERA_USERNAME")
    password = os.getenv("OPERA_PASSWORD")
    if not all([usuario, password]):
        raise RuntimeError("Faltan OPERA_USERNAME / OPERA_PASSWORD en el .env")

    hoy = datetime.now()
    ayer = hoy - timedelta(days=1)
    fecha_reporte_str = ayer.strftime("%Y-%m-%d")      # para nombres de archivo: YYYY-MM-DD
    fecha_hoy_str = hoy.strftime("%d-%m-%Y")           # hoy en formato Opera: DD-MM-YYYY
    fecha_ayer_opera = ayer.strftime("%d-%m-%Y")       # ayer en formato Opera: DD-MM-YYYY (To Date Statistics)
    fecha_ini_str = f"01-01-{hoy.year}"                # Statistics: siempre desde 1° enero del año

    archivos: list[Path] = []

    with sync_playwright() as playwright:
        if headless:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--window-size=1920,1080", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                accept_downloads=True,
                locale="es-419",
            )
        else:
            browser = playwright.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(
                no_viewport=True,
                accept_downloads=True,
                locale="es-419",
            )
        page = context.new_page()

        # ── Login ──────────────────────────────────────────────────────────────
        # Importante: NO se puede ir a LOGIN_URL directamente.
        # Oracle bloquea el acceso directo a /signin y cierra la página.
        # Hay que ir a Opera Cloud y dejar que Oracle redirija al SSO.
        logger.info("Login en Opera Cloud...")
        page.goto(OPERA_URL)
        page.wait_for_load_state("networkidle")

        # En este punto Oracle redirigió al SSO - llenamos credenciales
        # Selectores tolerantes a español e inglés
        page.get_by_role("textbox", name="Nombre de usuario").or_(
            page.get_by_role("textbox", name="User Name")
        ).fill(usuario)

        page.get_by_role("textbox", name="Contraseña").or_(
            page.get_by_role("textbox", name="Password")
        ).fill(password)

        # Al hacer click el SSO redirige de vuelta a Opera Cloud (sin popup)
        page.get_by_role("button", name="Conectar").or_(
            page.get_by_role("button", name="Sign In")
        ).click()

        # Esperamos a que cargue Opera Cloud tras el login
        page.wait_for_url("**/operacloud/**", timeout=60000)
        page.wait_for_load_state("networkidle")

        # Navegamos a la URL completa del dashboard para asegurarnos
        # de que el UI de Oracle ADF esté completamente inicializado
        page.goto(OPERA_URL)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)  # Oracle ADF necesita tiempo extra para renderizar los menús

        # ── Manage Reports ─────────────────────────────────────────────────────
        logger.info("Abriendo Manage Reports...")
        menu_reports = page.locator(
            "[id=\"pt1:oc_pg_pt:dm1:odec_drpmn_mb_grp:6:odec_drpmn_mb_mn\"] "
            "> .x2c8 > table > tbody > tr > td:nth-child(3) > .x2a5"
        )
        menu_reports.evaluate("el => el.click()")
        page.wait_for_timeout(1000)
        page.get_by_text("Manage Reports").click()

        # -- Reporte 1: History and Forecast (defecto) -------------------------
        logger.info("Descargando History and Forecast (defecto)...")
        _buscar_reporte(page, "History and Forecast")
        page.locator("span").filter(has_text=re.compile(r"^history_forecast$")).first.click()
        page.get_by_role("button", name="Download As...").click()
        page.get_by_text("XML").click()
        with page.expect_download() as dl_info:
            with page.expect_popup() as popup_info:
                page.get_by_role("button", name="Download", exact=True).click()
        popup_info.value.close()
        archivos.append(_guardar(dl_info.value, carpeta_destino, "OPERA_HistoryForecast_Default", fecha_reporte_str))

        # -- Reporte 2: History and Forecast (Total Revenue) -------------------
        logger.info("Descargando History and Forecast (Total Revenue)...")
        page.get_by_role("button", name="Edit Report Parameters").click()
        page.get_by_text("Total Revenue").click()
        archivos.append(_descargar_reporte_xml(page, carpeta_destino, "OPERA_HistoryForecast_TotalRevenue", fecha_reporte_str))
        page.get_by_role("link", name="Cancel").click()

        # -- Reporte 3: Trial Balance -------------------------------------------
        # La fecha se setea automáticamente a ayer — no hace falta entrar a Edit Parameters
        # (al igual que History and Forecast, se va directo a Download As...)
        logger.info("Descargando Trial Balance...")
        _buscar_reporte(page, "TRIAL")
        page.locator("span").filter(has_text=re.compile(r"^trial_balance$")).first.click()
        archivos.append(_descargar_reporte_xml(page, carpeta_destino, "OPERA_TrialBalance", fecha_reporte_str))

        # -- Reporte 4: Statistics - Room Type (01-ene → hoy) ------------------
        logger.info(f"Descargando Statistics Room Type ({fecha_ini_str} → {fecha_hoy_str})...")
        _buscar_reporte(page, "Statistics - Room Type")
        page.locator("span").filter(has_text=re.compile(r"^statroomtype$")).first.click()
        page.get_by_role("button", name="Edit Report Parameters").click()
        page.wait_for_timeout(500)
        # Ambas fechas se escriben directo en sus textbox (el calendario flatpickr
        # se re-renderiza y Playwright no puede hacer click en la fecha de forma estable)
        # Fecha inicio: 1° enero del año en curso
        page.get_by_role("textbox", name="From Date").click()
        page.get_by_role("textbox", name="From Date").fill(fecha_ini_str)
        page.get_by_role("textbox", name="From Date").press("Tab")
        page.wait_for_timeout(500)
        # Fecha fin: ayer
        page.get_by_role("textbox", name="To Date").click()
        page.get_by_role("textbox", name="To Date").fill(fecha_ayer_opera)
        page.get_by_role("textbox", name="To Date").press("Tab")
        page.wait_for_timeout(500)
        archivos.append(_descargar_reporte_xml(page, carpeta_destino, "OPERA_StatisticsRoomType", fecha_reporte_str))

        # ── Exports → General ─────────────────────────────────────────────────
        logger.info("Abriendo Exports → General...")
        menu_exports = page.locator(
            "[id=\"pt1:oc_pg_pt:dm1:odec_drpmn_mb_grp:5:odec_drpmn_mb_mn\"] "
            "> .x2c8 > table > tbody > tr > td:nth-child(3) > .x2a5"
        )
        menu_exports.evaluate("el => el.click()")
        page.wait_for_timeout(1000)
        page.get_by_text("Exports", exact=True).click()
        page.get_by_text("General").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)  # dar tiempo a que la tabla cargue completa

        # IMPORTANTE: en estas tablas de Oracle el botón ⋮ (Actions) NO está dentro
        # de la fila de datos, por eso se usan índices globales (como en la grabación).
        # El ⋮ de la primera fila de datos dentro de Generated Exports.
        # IMPORTANTE: las filas empiezan en t1:1 (no t1:0), y el índice de la
        # fila más reciente puede variar. Usamos un selector que toma cualquier
        # ⋮ de fila de datos (odec_rw_axns_mrlnk) y luego .first para el primero.
        LINK_DL = "a[id*=':ra1:odec_rw_axns_mrlnk'][title='Actions']"

        def abrir_menu_y_descargar(abrir_menu_fn, prefijo):
            """abrir_menu_fn: función que hace click en el ⋮ de la fila correcta.
            Reintenta abrir el menú hasta que 'View Exports' aparezca, luego
            hace View Exports → Download → Back."""
            ve = page.get_by_role("link", name="View Exports")
            # Abrir el menú ⋮ de la fila. Si "View Exports" ya está visible
            # (menú abierto), no clickeamos de nuevo. Reintentar hasta 4 veces.
            if not ve.is_visible():
                for intento in range(4):
                    try:
                        abrir_menu_fn()
                    except Exception:
                        pass  # puede fallar si el menú ya estaba abierto
                    page.wait_for_timeout(1200)
                    if ve.is_visible():
                        break
                    if intento == 3:
                        raise RuntimeError(f"No apareció 'View Exports' para {prefijo}")
                    page.wait_for_timeout(1500)
            ve.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            # Abrir el menú ⋮ de la primera fila para que aparezca "Download".
            # Primero verificamos si "Download" ya está visible (a veces el menú
            # quedó abierto); si no, clickeamos el ⋮ con reintentos.
            download_link = page.get_by_role("link", name="Download")
            if not download_link.is_visible():
                menu_btn = page.locator(LINK_DL).first
                for intento in range(4):
                    try:
                        menu_btn.scroll_into_view_if_needed(timeout=5000)
                        menu_btn.click(timeout=5000)
                    except Exception:
                        pass  # el menú pudo abrirse igual, verificamos abajo
                    page.wait_for_timeout(1200)
                    if download_link.is_visible():
                        break
                    if intento == 3:
                        raise RuntimeError(f"No apareció 'Download' para {prefijo}")
                    page.wait_for_timeout(1000)

            with page.expect_download() as dl_info:
                download_link.click()
            archivo = _guardar(dl_info.value, carpeta_destino, prefijo, fecha_reporte_str)
            page.get_by_role("button", name="Back").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)  # esperar que la lista General recargue
            return archivo

        # -- Export 1: BILLS (Actions de la primera fila) ----------------------
        logger.info("Descargando GEN_XMLBO_BILLS...")
        archivos.append(abrir_menu_y_descargar(
            lambda: page.get_by_role("link", name="Actions").first.click(),
            "OPERA_GEN_XMLBO_BILLS"))

        # -- Export 2: CITYLEDGER (Actions índice 3) ---------------------------
        logger.info("Descargando GEN_XMLBO_CITYLEDGER...")
        archivos.append(abrir_menu_y_descargar(
            lambda: page.get_by_role("link", name="Actions").nth(3).click(),
            "OPERA_GEN_XMLBO_CITYLEDGER"))

        # -- Export 3: CUSTOMER (Actions índice 4) -----------------------------
        logger.info("Descargando GEN_XMLBO_CUSTOMER...")
        archivos.append(abrir_menu_y_descargar(
            lambda: page.get_by_role("link", name="Actions").nth(4).click(),
            "OPERA_GEN_XMLBO_CUSTOMER"))

        # -- Export 4: REVENUE (fila índice 6, template x9d90r) ----------------
        logger.info("Descargando GEN_XMLBO_REVENUE...")
        archivos.append(abrir_menu_y_descargar(
            lambda: page.locator("a[id*=':oc_scrn_tmpl_x9d90r:'][id*=':t1:6:ra1:odec_rw_axns_mrlnk']").click(),
            "OPERA_GEN_XMLBO_REVENUE"))

        # -- Export 5: STATISTICS (fila índice 8, template x9d90r) -------------
        logger.info("Descargando GEN_XMLBO_STATISTICS...")
        archivos.append(abrir_menu_y_descargar(
            lambda: page.locator("a[id*=':oc_scrn_tmpl_x9d90r:'][id*=':t1:8:ra1:odec_rw_axns_mrlnk']").click(),
            "OPERA_GEN_XMLBO_STATISTICS"))

        context.close()
        browser.close()

    logger.info(f"Opera Cloud: {len(archivos)} archivos descargados en {carpeta_destino}")
    return archivos


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    carpeta_prueba = (
        Path(__file__).resolve().parent.parent
        / "descargas-prueba"
        / datetime.now().strftime("%Y-%m-%d")
    )
    descargar_opera(carpeta_prueba, headless=False)
