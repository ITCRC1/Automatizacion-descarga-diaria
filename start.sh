#!/bin/sh
# Script de arranque para Railway.
# Arranca Xvfb (pantalla virtual) manualmente en el display :99 en segundo
# plano, espera a que este listo, y luego corre el proceso. Se usa este
# metodo en vez de "xvfb-run" porque este ultimo, al arrancar en frio sin
# terminal interactivo (como hace el cron de Railway), se cuelga en
# "Starting Container" sin ejecutar nada.

# Iniciar Xvfb en segundo plano
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!

# Exportar el display para que Chromium lo use
export DISPLAY=:99

# Esperar 2 segundos a que Xvfb termine de levantar
sleep 2

# Correr el proceso principal
python main.py
CODIGO=$?

# Al terminar, cerrar Xvfb
kill $XVFB_PID 2>/dev/null

exit $CODIGO
