#!/bin/sh
# Script de arranque para Railway.
# Arranca Xvfb (pantalla virtual) manualmente en el display :99 en segundo
# plano, espera a que este listo, y luego corre el proceso.

# Si quedo un lock de una corrida anterior que no cerro limpio, Xvfb no
# puede arrancar ("Server is already active for display 99") y todo el
# proceso falla en cadena. Se limpia el lock (y cualquier Xvfb colgado)
# antes de arrancar, por las dudas.
rm -f /tmp/.X99-lock
pkill Xvfb 2>/dev/null

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

# Al terminar, cerrar Xvfb y limpiar el lock para la proxima corrida
kill $XVFB_PID 2>/dev/null
rm -f /tmp/.X99-lock

exit $CODIGO
