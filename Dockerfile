FROM python:3.11-slim

# Dependencias del sistema para Playwright + pantalla virtual (xvfb)
RUN apt-get update && apt-get install -y \
    xvfb \
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

# Correr con pantalla virtual para que Chromium funcione correctamente
CMD ["xvfb-run", "--auto-servernum", "python", "main.py"]
