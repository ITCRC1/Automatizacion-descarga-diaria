"""
modulos/drive_upload.py

Maneja la subida de archivos a Google Drive via API usando
una Service Account. Las credenciales vienen de la variable
de entorno GOOGLE_CREDENTIALS_JSON.
"""

import json
import logging
import os
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]

# Carpeta raiz compartida con la service account
CARPETA_RAIZ = "Auditoria Corcovado"


def _get_service():
    """Crea el cliente de Google Drive con las credenciales de la service account."""
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not credentials_json:
        raise RuntimeError("Falta GOOGLE_CREDENTIALS_JSON en las variables de entorno")

    info = json.loads(credentials_json)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials)


def _get_or_create_folder(service, nombre: str, parent_id: str = None) -> str:
    """Busca una carpeta por nombre. Si no existe, la crea."""
    query = (
        f"name='{nombre}' and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    resultados = service.files().list(q=query, fields="files(id, name)").execute()
    archivos = resultados.get("files", [])

    if archivos:
        return archivos[0]["id"]

    # No existe, la creamos
    metadata = {
        "name": nombre,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    carpeta = service.files().create(body=metadata, fields="id").execute()
    logger.info(f"Carpeta creada en Drive: {nombre}")
    return carpeta["id"]


def _find_root_folder(service) -> str:
    """Encuentra la carpeta raiz compartida con la service account."""
    query = (
        f"name='{CARPETA_RAIZ}' and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    resultados = service.files().list(q=query, fields="files(id, name)").execute()
    archivos = resultados.get("files", [])

    if not archivos:
        raise RuntimeError(
            f"No se encontró la carpeta '{CARPETA_RAIZ}' en Drive.\n"
            "Verificá que esté compartida con la service account."
        )
    return archivos[0]["id"]


def subir_archivos(archivos: list[Path], subcarpeta: str, fecha_str: str):
    """
    Sube una lista de archivos a Drive en la estructura:
    Auditoria Corcovado / Inputs / YYYY-MM-DD / subcarpeta /

    Parametros:
        archivos    : lista de rutas locales a subir
        subcarpeta  : "opera", "integrity" o "pos"
        fecha_str   : fecha en formato YYYY-MM-DD
    """
    if not archivos:
        return

    service = _get_service()

    # Navegar / crear la estructura de carpetas
    raiz_id      = _find_root_folder(service)
    inputs_id    = _get_or_create_folder(service, "Inputs",    raiz_id)
    fecha_id     = _get_or_create_folder(service, fecha_str,   inputs_id)
    destino_id   = _get_or_create_folder(service, subcarpeta,  fecha_id)

    for archivo in archivos:
        archivo = Path(archivo)
        if not archivo.exists():
            logger.warning(f"Archivo no encontrado, se omite: {archivo}")
            continue

        media = MediaFileUpload(str(archivo), resumable=True)
        metadata = {
            "name": archivo.name,
            "parents": [destino_id],
        }
        service.files().create(
            body=metadata, media_body=media, fields="id"
        ).execute()
        logger.info(f"Subido a Drive: {archivo.name}")
