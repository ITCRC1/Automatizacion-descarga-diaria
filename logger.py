"""
=============================================================
Configuración del sistema de logs
=============================================================
Usa Loguru en vez del módulo logging estándar porque:
  - Sintaxis mucho más simple (logger.info() y listo)
  - Salida colorizada en consola por defecto
  - Rotación de archivos sin configurar nada raro
  - Excepciones con traceback completo de un solo comando

Uso desde cualquier módulo:
    from loguru import logger
    logger.info("Mensaje normal")
    logger.warning("Advertencia")
    logger.error("Error")
=============================================================
"""

import sys
from datetime import datetime

from loguru import logger

from config import config


def configurar_logger() -> None:
    """
    Configura los handlers de log:
      - Consola con colores
      - Archivo diario en carpeta de logs
    """
    # Eliminamos el handler por defecto para reemplazarlo con los nuestros
    logger.remove()

    # === Handler 1: Consola (con colores) ===
    logger.add(
        sys.stderr,
        level=config.nivel_log,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}:{function}:{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # === Handler 2: Archivo (sin colores, más limpio) ===
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    archivo_log = config.carpeta_logs / f"bot_{fecha_hoy}.log"

    logger.add(
        archivo_log,
        level=config.nivel_log,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
        rotation="00:00",       # archivo nuevo cada medianoche
        retention="30 days",    # mantener 30 días de historial
        encoding="utf-8",
        enqueue=True,           # thread-safe
    )

    logger.info(f"Logger configurado. Archivo: {archivo_log}")
