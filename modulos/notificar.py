"""
=============================================================
Módulo de notificaciones por email
=============================================================
Envía alertas cuando el bot falla o detecta condiciones anormales.

Usa smtplib (estándar de Python, no requiere paquetes extra).
Probado con Gmail; para otros proveedores puede requerir ajustes
en los parámetros del .env.

IMPORTANTE para Gmail:
  - No usar tu contraseña normal de Gmail
  - Generar un "App Password" en https://myaccount.google.com/apppasswords
  - Tener 2FA habilitada en la cuenta de Gmail (requisito para App Passwords)
=============================================================
"""

import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from loguru import logger

from config import config


def enviar_email(
    asunto: str,
    cuerpo: str,
    adjuntos: list[Path] | None = None,
) -> bool:
    """
    Envía un email a los destinatarios configurados en .env.

    Args:
        asunto: Línea de asunto del email
        cuerpo: Texto plano del cuerpo del mensaje
        adjuntos: Lista opcional de archivos a adjuntar (típicamente capturas .png)

    Returns:
        True si se envió correctamente, False si hubo error.
    """
    try:
        # Construir el mensaje
        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = config.email_remitente
        mensaje["To"] = ", ".join(config.destinatarios_lista)
        mensaje.set_content(cuerpo)

        # Adjuntar archivos si los hay
        if adjuntos:
            for ruta in adjuntos:
                if not ruta.exists():
                    logger.warning(f"Adjunto no encontrado, se omite: {ruta}")
                    continue

                with open(ruta, "rb") as f:
                    datos = f.read()

                # Detectar tipo MIME por extensión (suficiente para nuestro caso)
                if ruta.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    maintype, subtype = "image", ruta.suffix.lower().strip(".")
                else:
                    maintype, subtype = "application", "octet-stream"

                mensaje.add_attachment(
                    datos,
                    maintype=maintype,
                    subtype=subtype,
                    filename=ruta.name,
                )

        # Conectar al servidor y enviar
        logger.debug(
            f"Conectando a {config.email_smtp_servidor}:{config.email_smtp_puerto}"
        )
        with smtplib.SMTP(
            config.email_smtp_servidor,
            config.email_smtp_puerto,
            timeout=30,
        ) as servidor:
            servidor.starttls()
            servidor.login(config.email_remitente, config.email_password)
            servidor.send_message(mensaje)

        logger.success(f"📧 Email enviado: '{asunto}'")
        return True

    except Exception as e:
        # Si falla el envío, lo logueamos pero NO levantamos excepción
        # (no queremos que un fallo de email rompa el bot)
        logger.error(f"❌ Error enviando email: {e}")
        return False


def alertar_fallo_bot(
    motivo: str,
    detalle: str = "",
    capturas: list[Path] | None = None,
) -> None:
    """
    Envía un email de alerta cuando el bot falla.

    Args:
        motivo: Resumen corto del problema (va al asunto)
        detalle: Explicación más larga (va al cuerpo)
        capturas: Capturas de pantalla relevantes para adjuntar
    """
    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cuerpo = f"""Bot de descarga Opera Cloud — FALLO

Hora: {hora}
Motivo: {motivo}

Detalle:
{detalle if detalle else '(sin detalle adicional)'}

{'Se adjuntan las últimas capturas de pantalla.' if capturas else ''}

---
Este es un mensaje automático del bot de automatización del reporte diario.
Si esto se repite, revisar los logs en: {config.carpeta_logs}
"""

    enviar_email(
        asunto=f"[BOT REVENUE] {motivo}",
        cuerpo=cuerpo.strip(),
        adjuntos=capturas,
    )


def notificar_exito(archivo_descargado: Path) -> None:
    """
    Envía un email confirmando que la descarga fue exitosa.
    Útil para tener evidencia diaria del proceso.
    """
    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cuerpo = f"""Bot de descarga Opera Cloud — ÉXITO

Hora: {hora}
Archivo descargado: {archivo_descargado.name}
Ruta completa: {archivo_descargado}
Tamaño: {archivo_descargado.stat().st_size:,} bytes

---
Este es un mensaje automático del bot.
"""

    enviar_email(
        asunto=f"[BOT REVENUE] Descarga OK - {archivo_descargado.name}",
        cuerpo=cuerpo.strip(),
    )
