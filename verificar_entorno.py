"""
=============================================================
Verificador de Entorno - Automatización Reporte Diario
=============================================================
Este script revisa que toda la instalación esté correcta
ANTES de empezar a desarrollar los bots reales.

Verifica:
  1. Versión de Python (debe ser 3.10 o superior)
  2. Paquetes Python instalados (playwright, dotenv, etc.)
  3. Navegadores de Playwright instalados
  4. Archivo .env existe y tiene todas las variables
  5. Carpetas de trabajo existen o se pueden crear

Uso:
    python verificar_entorno.py
=============================================================
"""

import sys
import os
from pathlib import Path

# Códigos de color para que la salida sea más legible en terminal
VERDE = "\033[92m"
ROJO = "\033[91m"
AMARILLO = "\033[93m"
RESET = "\033[0m"
NEGRITA = "\033[1m"


def imprimir_titulo(texto: str) -> None:
    """Imprime un título destacado en la terminal."""
    print(f"\n{NEGRITA}{'=' * 60}{RESET}")
    print(f"{NEGRITA}{texto}{RESET}")
    print(f"{NEGRITA}{'=' * 60}{RESET}")


def imprimir_ok(mensaje: str) -> None:
    """Imprime un mensaje de éxito en verde."""
    print(f"  {VERDE}✓{RESET} {mensaje}")


def imprimir_error(mensaje: str) -> None:
    """Imprime un mensaje de error en rojo."""
    print(f"  {ROJO}✗{RESET} {mensaje}")


def imprimir_advertencia(mensaje: str) -> None:
    """Imprime una advertencia en amarillo."""
    print(f"  {AMARILLO}!{RESET} {mensaje}")


def verificar_python() -> bool:
    """
    Verifica que la versión de Python sea adecuada.

    Returns:
        True si Python es 3.10+, False si no
    """
    imprimir_titulo("1. Verificando versión de Python")

    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major == 3 and version.minor >= 10:
        imprimir_ok(f"Python {version_str} (OK - se requiere 3.10+)")
        return True
    else:
        imprimir_error(f"Python {version_str} - se requiere 3.10 o superior")
        print(f"    Descargá Python desde: https://www.python.org/downloads/")
        return False


def verificar_paquetes() -> bool:
    """
    Verifica que los paquetes Python requeridos estén instalados.

    Returns:
        True si todos los paquetes están, False si falta alguno
    """
    imprimir_titulo("2. Verificando paquetes Python")

    # Mapeo: nombre para importar -> nombre que muestra pip
    paquetes_requeridos = {
        "playwright": "playwright",
        "dotenv": "python-dotenv",
        "loguru": "loguru",
        "pydantic": "pydantic",
        "pydantic_settings": "pydantic-settings",
    }

    todos_ok = True
    for modulo, nombre_pip in paquetes_requeridos.items():
        try:
            __import__(modulo)
            imprimir_ok(f"{nombre_pip}")
        except ImportError:
            imprimir_error(f"{nombre_pip} NO instalado")
            print(f"    Instalalo con: pip install {nombre_pip}")
            todos_ok = False

    return todos_ok


def verificar_navegadores_playwright() -> bool:
    """
    Verifica que los navegadores de Playwright estén descargados.

    Playwright instala los navegadores en una carpeta separada
    de los paquetes Python. Necesitamos confirmarlo.

    Returns:
        True si Chromium está disponible, False si no
    """
    imprimir_titulo("3. Verificando navegadores de Playwright")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Intentamos lanzar Chromium en modo headless rápido
            # Si los binarios no están descargados, esto falla
            try:
                navegador = p.chromium.launch(headless=True)
                navegador.close()
                imprimir_ok("Chromium instalado y funcional")

                # También verificamos Firefox (lo usamos para Integrity)
                try:
                    navegador = p.firefox.launch(headless=True)
                    navegador.close()
                    imprimir_ok("Firefox instalado y funcional")
                except Exception:
                    imprimir_advertencia(
                        "Firefox no instalado (lo usaremos para Integrity)"
                    )
                    print("    Instalalo con: playwright install firefox")

                return True
            except Exception as e:
                imprimir_error(f"Chromium no instalado correctamente: {e}")
                print("    Instalá con: playwright install chromium")
                return False
    except ImportError:
        imprimir_error("Playwright no está instalado todavía")
        return False


def verificar_archivo_env() -> bool:
    """
    Verifica que el archivo .env exista y tenga las variables esperadas.

    NO muestra los valores (porque son secretos), solo confirma
    que las variables están definidas.

    Returns:
        True si .env existe y está completo, False si no
    """
    imprimir_titulo("4. Verificando archivo .env")

    archivo_env = Path(__file__).parent / ".env"

    if not archivo_env.exists():
        imprimir_error(f"No existe el archivo .env en {archivo_env}")
        print("    Copiá .env.example a .env y llenalo con tus datos")
        return False

    imprimir_ok(f"Archivo .env encontrado en {archivo_env}")

    # Cargamos las variables y revisamos cuáles existen
    try:
        from dotenv import dotenv_values
        variables = dotenv_values(archivo_env)
    except ImportError:
        imprimir_error("No se puede leer .env (falta python-dotenv)")
        return False

    variables_requeridas = [
        "OPERA_URL",
        "OPERA_USUARIO",
        "OPERA_PASSWORD",
        "OPERA_PROPIEDAD",
        "INTEGRITY_URL",
        "INTEGRITY_USUARIO",
        "INTEGRITY_PASSWORD",
        "CARPETA_DESCARGAS",
        "CARPETA_LOGS",
        "CARPETA_CAPTURAS",
        "MODO_HEADLESS",
        "TIMEOUT_SEGUNDOS",
        "NIVEL_LOG",
    ]

    todas_ok = True
    for var in variables_requeridas:
        valor = variables.get(var, "")
        if not valor or valor.startswith("<"):
            imprimir_error(f"{var} no configurada o tiene valor de plantilla")
            todas_ok = False
        else:
            # Por seguridad, NO mostramos contraseñas
            if "PASSWORD" in var:
                imprimir_ok(f"{var} = ******** (oculto)")
            else:
                imprimir_ok(f"{var} = {valor}")

    return todas_ok


def verificar_carpetas() -> bool:
    """
    Verifica que las carpetas de trabajo existan o las crea.

    Returns:
        True si todas las carpetas están listas, False si hubo algún error
    """
    imprimir_titulo("5. Verificando carpetas de trabajo")

    try:
        from dotenv import dotenv_values
        archivo_env = Path(__file__).parent / ".env"
        variables = dotenv_values(archivo_env)
    except Exception:
        imprimir_error("No se pueden leer las rutas desde .env")
        return False

    carpetas = [
        ("Descargas", variables.get("CARPETA_DESCARGAS")),
        ("Logs", variables.get("CARPETA_LOGS")),
        ("Capturas", variables.get("CARPETA_CAPTURAS")),
    ]

    todas_ok = True
    for nombre, ruta in carpetas:
        if not ruta:
            imprimir_error(f"{nombre}: ruta no definida en .env")
            todas_ok = False
            continue

        ruta_obj = Path(ruta)
        try:
            # Si no existe, la creamos
            ruta_obj.mkdir(parents=True, exist_ok=True)
            imprimir_ok(f"{nombre}: {ruta_obj}")
        except Exception as e:
            imprimir_error(f"{nombre}: no se pudo crear {ruta_obj} - {e}")
            todas_ok = False

    return todas_ok


def main() -> int:
    """
    Ejecuta todas las verificaciones en orden.

    Returns:
        0 si todo está OK, 1 si hubo algún problema
    """
    print(f"\n{NEGRITA}🔍 Verificador de Entorno{RESET}")
    print(f"{NEGRITA}Automatización Reporte Diario de Ingresos{RESET}")

    # Lista de verificaciones y sus resultados
    resultados = []
    resultados.append(("Python", verificar_python()))

    # Si Python no está bien, no tiene sentido seguir
    if not resultados[-1][1]:
        print(f"\n{ROJO}{NEGRITA}❌ Detené acá: arreglá Python primero{RESET}\n")
        return 1

    resultados.append(("Paquetes", verificar_paquetes()))
    resultados.append(("Navegadores", verificar_navegadores_playwright()))
    resultados.append(("Archivo .env", verificar_archivo_env()))
    resultados.append(("Carpetas", verificar_carpetas()))

    # Resumen final
    imprimir_titulo("Resumen")
    todos_ok = all(ok for _, ok in resultados)

    for nombre, ok in resultados:
        if ok:
            imprimir_ok(nombre)
        else:
            imprimir_error(nombre)

    print()
    if todos_ok:
        print(f"{VERDE}{NEGRITA}✅ Todo listo. Podés avanzar a Fase 1.{RESET}\n")
        return 0
    else:
        print(f"{ROJO}{NEGRITA}❌ Hay cosas por arreglar antes de continuar.{RESET}\n")
        return 1


if __name__ == "__main__":
    # Salimos con el código adecuado para que se pueda usar en scripts
    sys.exit(main())
