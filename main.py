"""
main.py — versión Railway

Orquestador del proceso diario de descargas para correr en la nube.

Flujo:
  1. Descarga cada fuente a una carpeta temporal (/tmp)
  2. Sube los archivos a Google Drive (Unidad Compartida) via API
  3. Limpia la carpeta temporal

Estructura resultante en la Unidad Compartida:
  Auditoria Corcovado / Inputs / YYYY-MM-DD /
      ├── opera/       ← 9 archivos de Opera Cloud
      ├── integrity/   ← 1 Excel de Integrity
      └── pos/         ← 1 Excel consolidado

Variables de entorno requeridas en Railway:
  GOOGLE_CREDENTIALS_JSON   (contenido del JSON de la service account)
  OPERA_USERNAME / OPERA_PASSWORD
  INTEGRITY_USERNAME / INTEGRITY_PASSWORD
  ORS_USERNAME / ORS_ENTERPRISE / ORS_PASSWORD
"""

import logging
import os
import sys
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def preparar_carpetas_temp() -> tuple[Path, dict[str, Path]]:
    """Crea las carpetas temporales de trabajo. Devuelve (raiz_temp, dict)."""
    fecha_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    raiz = Path(tempfile.mkdtemp()) / fecha_str

    carpetas = {
        "opera":     raiz / "opera",
        "integrity": raiz / "integrity",
        "pos":       raiz / "pos",
    }
    for carpeta in carpetas.values():
        carpeta.mkdir(parents=True, exist_ok=True)

    logger.info(f"Carpeta temporal: {raiz}")
    return raiz, carpetas


def main():
    logger.info("=" * 60)
    logger.info("INICIO DEL PROCESO DIARIO")
    logger.info("=" * 60)

    fecha_reporte = datetime.now() - timedelta(days=1)
    fecha_str = fecha_reporte.strftime("%Y-%m-%d")

    raiz_temp, carpetas = preparar_carpetas_temp()
    errores: list[str] = []

    from modulos.drive_upload import subir_archivos

    # ── 1. Opera Cloud ──────────────────────────────────────────────────────
    logger.info("─" * 40)
    logger.info("PASO 1/3 — Opera Cloud")
    logger.info("─" * 40)
    archivos_opera = []
    try:
        from modulos.opera import descargar_opera
        archivos_opera = descargar_opera(carpetas["opera"], headless=False)
        logger.info(f"Opera: {len(archivos_opera)} archivos descargados ✓")
        subir_archivos(archivos_opera, "opera", fecha_str)
        logger.info("Opera: archivos subidos a Drive ✓")
    except Exception as e:
        logger.error(f"Opera falló: {e}", exc_info=True)
        errores.append(f"Opera: {e}")

    # ── 2. Integrity ────────────────────────────────────────────────────────
    logger.info("─" * 40)
    logger.info("PASO 2/3 — Integrity")
    logger.info("─" * 40)
    try:
        from modulos.integrity import subir_revenue_y_descargar

        revenue_xml = carpetas["opera"] / f"OPERA_GEN_XMLBO_REVENUE_{fecha_str}.xml"
        if not revenue_xml.exists():
            raise FileNotFoundError(
                f"No se encontró el XML de revenue: {revenue_xml}\n"
                "Verificá que el paso de Opera haya terminado correctamente."
            )

        archivos_integrity = subir_revenue_y_descargar(
            revenue_xml, carpetas["integrity"], fecha_reporte=fecha_reporte, headless=False
        )
        logger.info(f"Integrity: {len(archivos_integrity)} archivo(s) descargado(s) ✓")
        subir_archivos(archivos_integrity, "integrity", fecha_str)
        logger.info("Integrity: archivos subidos a Drive ✓")
    except Exception as e:
        logger.error(f"Integrity falló: {e}", exc_info=True)
        errores.append(f"Integrity: {e}")

    # ── 3. ORS (POS) ────────────────────────────────────────────────────────
    logger.info("─" * 40)
    logger.info("PASO 3/3 — Reporting, Analytics and People (ORS/POS)")
    logger.info("─" * 40)
    ors_ok = False
    try:
        from modulos.ors import descargar_reportes_ors
        archivos_ors = descargar_reportes_ors(carpetas["pos"], headless=False)
        logger.info(f"ORS: {len(archivos_ors)} archivos descargados ✓")
        ors_ok = True
    except Exception as e:
        logger.error(f"ORS falló: {e}", exc_info=True)
        errores.append(f"ORS: {e}")

    # ── 3b. Consolidar POS y subir ──────────────────────────────────────────
    if ors_ok:
        logger.info("─" * 40)
        logger.info("PASO 3b — Consolidando reporte POS")
        logger.info("─" * 40)
        try:
            from modulos.consolidar import consolidar_pos
            final = consolidar_pos(
                carpetas["pos"], fecha_reporte=fecha_reporte, borrar_originales=True
            )
            logger.info(f"Reporte POS consolidado: {final.name} ✓")
            subir_archivos([final], "pos", fecha_str)
            logger.info("POS: archivo subido a Drive ✓")
        except Exception as e:
            logger.error(f"Consolidación POS falló: {e}", exc_info=True)
            errores.append(f"Consolidación POS: {e}")

    # ── Limpiar temporales ──────────────────────────────────────────────────
    try:
        shutil.rmtree(raiz_temp.parent)
        logger.info("Carpeta temporal limpiada ✓")
    except Exception:
        pass

    # ── Resumen ─────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    if errores:
        logger.warning("PROCESO TERMINADO CON ERRORES:")
        for err in errores:
            logger.warning(f"  • {err}")
        logger.info("=" * 60)
        sys.exit(1)
    else:
        logger.info("PROCESO COMPLETADO SIN ERRORES ✓")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
