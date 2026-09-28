"""Icono de CazaToy en la barra de menú, junto al reloj."""

from __future__ import annotations

import logging
import subprocess
import threading

import rumps
from PIL import Image, ImageDraw

from .config import DOWNLOADS, ICON_PATH, IMPRIMIR, LOG_PATH, ensure_dirs
from .pipeline import TEST_ZPL
from .service import Service

log = logging.getLogger(__name__)


def setup_logging() -> None:
    ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
        force=True,
    )
    logging.getLogger("zeroconf").setLevel(logging.ERROR)


def build_icon(path=ICON_PATH) -> None:
    ensure_dirs()
    image = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 4, 30, 32), radius=3, outline=(0, 0, 0, 255), width=3)
    draw.line((10, 12, 26, 12), fill=(0, 0, 0, 255), width=2)
    draw.line((10, 18, 22, 18), fill=(0, 0, 0, 255), width=2)
    draw.rectangle((10, 22, 18, 28), fill=(0, 0, 0, 255))
    image.save(path)


class CazaApp(rumps.App):
    def __init__(self, service: Service) -> None:
        super().__init__("CazaToy", title=None, icon=str(ICON_PATH), template=True, quit_button=None)
        self.service = service
        self.status_item = rumps.MenuItem(service.status)
        self.net_item = rumps.MenuItem(service.network_label())
        self.pause_item = rumps.MenuItem("Pausar", callback=self.on_pause)
        self.matrix_item = rumps.MenuItem("Matriz", callback=self.on_matrix)
        self.menu = [
            self.status_item,
            self.net_item,
            None,
            self.matrix_item,
            rumps.MenuItem("Posición del logo", callback=self.on_editor),
            self.pause_item,
            rumps.MenuItem("Reimprimir última", callback=self.on_reprint),
            rumps.MenuItem("Abrir Descargas", callback=self.on_open),
            rumps.MenuItem("Carpeta de imágenes", callback=self.on_images),
            rumps.MenuItem("Imprimir prueba", callback=self.on_test),
        ]
        rumps.Timer(self.refresh, 1).start()

    def refresh(self, _timer) -> None:
        self.status_item.title = f"{self.service.status_line()} · {self.service.store_name()}"
        self.pause_item.title = "Reanudar" if self.service.paused else "Pausar"
        self.matrix_item.state = 1 if self.service.matrix_enabled() else 0
        self.net_item.title = self.service.network_label()

    def on_pause(self, _sender) -> None:
        self.service.toggle_pause()
        self.refresh(None)

    def on_matrix(self, _sender) -> None:
        self.service.toggle_matrix()
        self.refresh(None)

    def on_reprint(self, _sender) -> None:
        threading.Thread(target=self.service.reprint, name="caza-reprint", daemon=True).start()

    def on_editor(self, _sender) -> None:
        port = self.service.server.ipp_port if self.service.server else 8631
        subprocess.run(["/usr/bin/open", f"http://127.0.0.1:{port}/editor"], check=False)

    def on_open(self, _sender) -> None:
        subprocess.run(["/usr/bin/open", str(DOWNLOADS)], check=False)

    def on_images(self, _sender) -> None:
        subprocess.run(["/usr/bin/open", str(IMPRIMIR)], check=False)

    def on_test(self, _sender) -> None:
        self.service.submit_bytes(TEST_ZPL.encode("ascii"), "prueba.zpl")


def main() -> None:
    setup_logging()
    build_icon()
    service = Service()
    service.start()
    try:
        CazaApp(service).run()
    except Exception:
        log.exception("la barra de menú no pudo abrirse; sigo recibiendo etiquetas")
        threading.Event().wait()
