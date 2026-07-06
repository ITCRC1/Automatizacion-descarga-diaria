"""
=============================================================
Configuración del proyecto
=============================================================
Carga las variables de entorno desde .env y las valida con Pydantic.

Por qué Pydantic:
  - Falla rápido si falta una variable o tiene tipo incorrecto
  - Convierte tipos automáticamente (str a int, str a bool, str a Path)
  - Mensajes de error claros, no crípticos

Uso:
    from config import config
    print(config.opera_url)
=============================================================
"""

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    """
    Configuración completa del proyecto en un único objeto.
    Las variables se leen del archivo .env automáticamente.
    """

    # Le decimos a Pydantic dónde está el archivo .env
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # OPERA_URL == opera_url
        extra="ignore",  # ignorar variables que no estén definidas acá
    )

    # --- Opera Cloud ---
    opera_url: str
    opera_usuario: str
    opera_password: str
    opera_propiedad: str = "COWLCR"

    # --- Integrity (se usa en Fase 2, ya validamos su presencia) ---
    integrity_url: str
    integrity_usuario: str
    integrity_password: str

    # --- Rutas locales ---
    carpeta_descargas: Path
    carpeta_logs: Path
    carpeta_capturas: Path

    # --- Navegador ---
    modo_headless: bool = False
    timeout_segundos: int = 180

    # --- Logging ---
    nivel_log: str = "INFO"

    # --- Email ---
    email_smtp_servidor: str = "smtp.gmail.com"
    email_smtp_puerto: int = 587
    email_remitente: str
    email_password: str
    email_destinatarios: str  # lista separada por coma en el .env

    @field_validator("carpeta_descargas", "carpeta_logs", "carpeta_capturas")
    @classmethod
    def crear_carpeta_si_no_existe(cls, v: Path) -> Path:
        """
        Si la carpeta no existe, la crea.
        Esto evita errores cuando ejecutamos el bot por primera vez.
        """
        v.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def destinatarios_lista(self) -> list[str]:
        """
        Convierte la string 'a@x.com,b@y.com' en lista ['a@x.com', 'b@y.com'].
        Quita espacios extras por si acaso.
        """
        return [d.strip() for d in self.email_destinatarios.split(",") if d.strip()]


# === Instancia global ===
# Se carga una sola vez al importar este módulo desde cualquier otro archivo.
# Si falta algo en .env, esto explota acá con un mensaje claro.
try:
    config = Configuracion()
except Exception as e:
    print("=" * 60)
    print("❌ ERROR cargando la configuración")
    print("=" * 60)
    print(f"\nDetalle: {e}\n")
    print("Verificá que:")
    print("  1. El archivo .env existe en la carpeta del proyecto")
    print("  2. Todas las variables están definidas (mirá .env.example)")
    print("  3. No quedaron valores entre <> sin reemplazar")
    print()
    raise
