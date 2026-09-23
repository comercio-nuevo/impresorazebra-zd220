# CazaToy

App de barra de menú para macOS. Imprime etiquetas de 4×6 pulgadas en una Zebra ZD220 por USB y las anuncia en la red local como AirPrint.

Los archivos nuevos en Descargas (PDF, ZPL, TXT, JPG, PNG, CSV o ZIP) se imprimen y se borran. No guarda copias de las etiquetas.

## Uso

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m caza_toy
```

La impresora tiene que existir en el Mac con el nombre `Zebra_ZD220`. Se puede cambiar en `~/Library/Application Support/CazaToy/config.json`, que se crea en cada computadora y no forma parte de este repositorio.

Para que arranque al iniciar sesión:

```bash
.venv/bin/python install_agent.py
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cazatoy.labels.plist
```

`com.cazatoy.labels.plist` en el repo usa las marcas `PROJECT_DIR` y `HOME`. `install_agent.py` escribe el archivo real solo en tu Mac.

## Menú

- **Matriz:** apagada, un `.txt` con `^XA` sale como ZPL II. Encendida, la etiqueta se dibuja como una cuadrícula de números y el código de barras no se escanea.
- **Abrir bandeja:** abre Descargas.
