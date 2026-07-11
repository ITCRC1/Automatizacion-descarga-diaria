FROM python:3.11-slim

# Dependencias del sistema para Playwright + pantalla virtual (xvfb)
# Las fuentes son necesarias porque python:3.11-slim no trae ninguna: sin
# fuentes, Chromium headless puede colapsar a 0x0 elementos cuyo tamaño
# depende de un glyph de icon-font (como los iconos del menú de Oracle ADF).
RUN apt-get update && apt-get install -y \
    xvfb \
    fontconfig \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Playwright y Chromium
RUN playwright install chromium
RUN playwright install-deps chromium

# Copiar el proyecto
COPY . .

# Dar permiso de ejecucion al script de arranque
RUN chmod +x start.sh

# Arrancar via el script (levanta Xvfb manualmente y corre python).
# No se usa "xvfb-run" porque se cuelga al arrancar en frio en el cron.
CMD ["sh", "start.sh"]
