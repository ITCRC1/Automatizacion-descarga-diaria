"""
modulos/drive_upload.py

Maneja la subida de archivos a Google Drive via API usando
una Service Account. Los archivos se guardan en una UNIDAD COMPARTIDA
(Shared Drive), necesaria porque las service accounts no tienen
almacenamiento propio.

Las credenciales vienen de la variable de entorno GOOGLE_CREDENTIALS_JSON.
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

# ID de la Unidad Compartida "Auditoria Corcovado"
# (tomado de la URL: drive.google.com/drive/folders/ESTE_ID)
SHARED_DRIVE_ID = "0AKEzInrdMcvUUk9PVA"


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


def _get_or_create_folder(service, nombre: str, parent_id: str) -> str:
    """
    Busca una carpeta por nombre dentro de parent_id. Si no existe, la crea.
    Compatible con Unidades Compartidas.
    """
    query = (
        f"name='{nombre}' and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"'{parent_id}' in parents and "
        f"trashed=false"
    )
    resultados = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora="drive",
        driveId=SHARED_DRIVE_ID,
    ).execute()
    archivos = resultados.get("files", [])

    if archivos:
        return archivos[0]["id"]

    # No existe, la creamos
    metadata = {
        "name": nombre,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    carpeta = service.files().create(
        body=metadata,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    logger.info(f"Carpeta creada en Drive: {nombre}")
    return carpeta["id"]


def subir_archivos(archivos: list[Path], subcarpeta: str, fecha_str: str):
    """
    Sube una lista de archivos a la Unidad Compartida en la estructura:
    Auditoria Corcovado / Inputs / YYYY-MM-DD / subcarpeta /

    Parametros:
        archivos    : lista de rutas locales a subir
        subcarpeta  : "opera", "integrity" o "pos"
        fecha_str   : fecha en formato YYYY-MM-DD
    """
    if not archivos:
        return

    service = _get_service()

    # La raiz de la estructura es la Unidad Compartida en si misma
    inputs_id  = _get_or_create_folder(service, "Inputs",     SHARED_DRIVE_ID)
    fecha_id   = _get_or_create_folder(service, fecha_str,    inputs_id)
    destino_id = _get_or_create_folder(service, subcarpeta,   fecha_id)

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
            body=metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        logger.info(f"Subido a Drive: {archivo.name}")
