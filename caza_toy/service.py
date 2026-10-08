"""Cola única: bandeja, AirPrint y puerto 9100 imprimen por aquí."""

from __future__ import annotations

import io
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue

from .config import DOWNLOADS, IMPRIMIR, active_placement, apply_stores, load_config, logo_file, save_config, wipe_cache
from .jobs import JOB_ABORTED, JOB_CANCELED, JOB_COMPLETED, JOB_PENDING, JOB_PROCESSING, Job
from PIL import Image

from .logo import clean_logo
from .pipeline import image_to_zpl, pdf_page_count, pdf_page_png, prepare, render_pdf_crop, send_to_printer
from .server import PrintServer
from .watch import accepts_download, file_ident, files_in_zip, run_inbox

log = logging.getLogger(__name__)


def sanitize(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "etiqueta"
    return base[:80]


def short_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:120] or "error de impresión"


def ipv4_addrs() -> list[str]:
    try:
        text = subprocess.check_output(["/sbin/ifconfig"], text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("inet ") or "127.0.0.1" in line:
            continue
        ip = line.split()[1]
        if ip not in found and _usable_ipv4(ip):
            found.append(ip)
    return found


def _usable_ipv4(ip: str) -> bool:
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    # 100.64.0.0/10 es la red de Tailscale, no la Wi‑Fi de la tienda.
    if first == 100 and 64 <= second <= 127:
        return False
    return True


class Service:
    def __init__(self) -> None:
        config = load_config()
        self.uuid = str(config["uuid"])
        self.ipp_port = int(config["ipp_port"])
        self.raw_port = int(config["raw_port"])
        self.ips = ipv4_addrs()
        self.display_ip = self.ips[0] if self.ips else "sin red"
        self.paused = False
        self.busy = False
        self.jobs: dict[int, Job] = {}
        self.queue: Queue[Job] = Queue()
        self.print_lock = threading.Lock()
        self._lock = threading.Lock()
        self._seq = 0
        self._status = "Lista"
        self._stop = threading.Event()
        self._last_zpl: str | None = None
        self._inflight: set[str] = set()
        self._ignore: set[tuple] = set()
        self.server: PrintServer | None = None
        self._pdf = b""

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def set_status(self, text: str) -> None:
        with self._lock:
            self._status = text

    def network_label(self) -> str:
        ip = self.display_ip
        port = self.server.ipp_port if self.server else self.ipp_port
        raw = self.server.raw_port if self.server else self.raw_port
        if ip == "sin red":
            return "Red: sin conexión"
        return f"Red: {ip}  AirPrint {port}  ZPL {raw}"

    def _idle_status(self) -> str:
        if self.paused:
            return "Pausada"
        if self.server and self.server.raw_warning:
            return self.server.raw_warning
        return "Lista"

    def status_line(self) -> str:
        current = self.status
        if current.startswith(("Imprimiendo", "Error:", "Reimprimiendo")):
            return current
        return self._idle_status()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        log.info("pausa=%s", self.paused)
        if self.paused:
            self.set_status("Pausada")
        elif not self.busy:
            self.set_status("Lista")

    def logo_text(self) -> str:
        return clean_logo(str(load_config().get("logo_text", "caza toy")))

    def matrix_enabled(self) -> bool:
        return bool(load_config().get("matrix"))

    def store_name(self) -> str:
        place = active_placement()
        return str(place["name"]) if place else "Sin tienda"

    def stores_payload(self) -> dict:
        data = load_config()
        return {"active": data.get("active_store"), "stores": data.get("stores") or []}

    def save_logo(self, store_name: str, data: bytes, slot: int = 1) -> None:
        if not store_name.strip():
            raise ValueError("falta la tienda")
        if len(data) > 8_000_000:
            raise ValueError("imagen demasiado grande")
        image = Image.open(io.BytesIO(data))
        image = image.convert("RGBA")
        image.thumbnail((1200, 1200))
        path = logo_file(store_name, slot)
        image.save(path, "PNG")
        log.info("logo de %s", store_name.strip())

    def delete_logo(self, store_name: str, slot: int = 1) -> None:
        if not store_name.strip():
            raise ValueError("falta la tienda")
        logo_file(store_name, slot).unlink(missing_ok=True)
        log.info("logo borrado %s %s", store_name.strip(), slot)

    def save_stores(self, stores: list, active: str) -> dict:
        data = apply_stores(load_config(), stores, active)
        save_config(data)
        log.info("tienda=%s", data["active_store"])
        return {"active": data["active_store"], "stores": data["stores"]}

    def toggle_matrix(self) -> bool:
        data = load_config()
        enabled = not bool(data.get("matrix"))
        data["matrix"] = enabled
        save_config(data)
        log.info("matriz=%s", enabled)
        return enabled

    def printer_name(self) -> str:
        return str(load_config().get("printer") or "Zebra_ZD220")

    def snapshot_jobs(self) -> list[Job]:
        with self._lock:
            return list(self.jobs.values())

    def reserve_job(self, name: str) -> Job:
        with self._lock:
            self._seq += 1
            job_id = self._seq
            job = Job(id=job_id, name=sanitize(name))
            self.jobs[job_id] = job
            self._trim_jobs()
        return job

    def _trim_jobs(self) -> None:
        if len(self.jobs) <= 80:
            return
        finished = [job for job in self.jobs.values() if job.state in (JOB_CANCELED, JOB_ABORTED, JOB_COMPLETED)]
        finished.sort(key=lambda job: job.created)
        for job in finished[: len(self.jobs) - 80]:
            self.jobs.pop(job.id, None)

    def start_job(
        self,
        job: Job,
        data: bytes,
        copies: int = 1,
        source: Path | None = None,
        ident: tuple | None = None,
        keep: bool = False,
        plain: bool = False,
    ) -> None:
        job.copies = max(1, min(20, int(copies or 1)))
        job.data = data
        job.source = source
        job.ident = ident
        job.keep = keep
        job.plain = plain
        if job.state == JOB_CANCELED:
            return
        job.state = JOB_PENDING
        job.queued = True
        self.queue.put(job)

    def submit_bytes(
        self,
        data: bytes,
        name: str,
        copies: int = 1,
        source: Path | None = None,
        ident: tuple | None = None,
        keep: bool = False,
        plain: bool = False,
    ) -> Job:
        job = self.reserve_job(name)
        self.start_job(job, data, copies, source, ident, keep, plain)
        return job

    def cancel_job(self, job: Job) -> None:
        if job.state in (JOB_COMPLETED, JOB_ABORTED, JOB_CANCELED):
            return
        job.state = JOB_CANCELED
        job.reasons = "job-canceled"

    def consider(self, path: Path, keep: bool = False) -> None:
        ident = file_ident(path)
        key = str(path)
        if ident is None or ident in self._ignore or key in self._inflight:
            return
        self._inflight.add(key)
        try:
            data = path.read_bytes()
            if len(data) > 30_000_000:
                raise ValueError("el archivo supera 30 MB")
            if not keep and not accepts_download(path.name, data):
                self._inflight.discard(key)
                self._ignore.add(ident)
                log.info("se dejó, no es etiqueta %s", path.name)
                return
            self.submit_bytes(data, path.name, source=path, ident=ident, keep=keep)
            log.info("%s %s", "imprimir" if keep else "descargas", path.name)
        except Exception as exc:
            log.exception("no se pudo encolar %s", path.name)
            self._inflight.discard(key)
            self._ignore.add(ident)
            self.set_status(f"Error: {short_error(exc)}")

    def print_ready(self, name: str) -> None:
        from .ready import ready_zpl

        self.submit_bytes(ready_zpl(name).encode("ascii"), f"{name}.zpl", plain=True)

    def store_pdf(self, data: bytes) -> int:
        if len(data) > 30_000_000:
            raise ValueError("el PDF supera 30 MB")
        if not data.lstrip(b"\xef\xbb\xbf").startswith(b"%PDF"):
            raise ValueError("no es un PDF")
        count = pdf_page_count(data)
        self._pdf = data
        return count

    def pdf_preview(self, index: int) -> bytes:
        if not self._pdf:
            raise ValueError("carga un PDF primero")
        return pdf_page_png(self._pdf, index)

    def print_pdf_crop(self, index: int, x: float, y: float, w: float, h: float, turned: bool = False) -> None:
        if not self._pdf:
            raise ValueError("carga un PDF primero")
        image = render_pdf_crop(self._pdf, index, x, y, w, h, turned)
        self.submit_bytes(image_to_zpl(image).encode("ascii"), "recorte.pdf", plain=True)

    def reprint(self) -> None:
        if not self._last_zpl:
            self.set_status("Error: no hay etiqueta anterior")
            return
        self.set_status("Reimprimiendo")
        try:
            with self.print_lock:
                request_id = send_to_printer(self._last_zpl, self.printer_name())
            log.info("reimpresa %s", request_id)
            self.set_status(self._idle_status())
        except Exception as exc:
            log.exception("reimprimir")
            self.set_status(f"Error: {short_error(exc)}")

    def start(self) -> None:
        self.server = PrintServer(
            self,
            host="0.0.0.0",
            ipp_port=self.ipp_port,
            raw_port=self.raw_port,
            advertise=True,
            ips=self.ips,
        )
        self.server.start()
        if self.server.bind_error:
            log.error(self.server.bind_error)
            self.set_status(f"Error: {short_error(RuntimeError(self.server.bind_error))}")
        else:
            self.set_status(self._idle_status())
        wipe_cache()
        threading.Thread(target=self._worker, name="caza-print", daemon=True).start()
        threading.Thread(
            target=run_inbox,
            args=(DOWNLOADS, lambda path: self.consider(path, keep=False), self._stop),
            name="caza-watch",
            daemon=True,
        ).start()
        threading.Thread(
            target=run_inbox,
            kwargs={"inbox": IMPRIMIR, "ingest": lambda path: self.consider(path, keep=True), "stop": self._stop, "images": True},
            name="caza-images",
            daemon=True,
        ).start()
        log.info(
            "CazaToy listo ip=%s airprint=%s zpl=%s",
            self.display_ip,
            self.server.ipp_port,
            self.server.raw_port,
        )

    def _worker(self) -> None:
        while not self._stop.is_set():
            if self.paused:
                time.sleep(0.25)
                continue
            try:
                job = self.queue.get(timeout=0.4)
            except Empty:
                continue
            if job.state == JOB_CANCELED:
                self._finish_download(job, ok=False)
                continue
            self.busy = True
            job.state = JOB_PROCESSING
            self.set_status(f"Imprimiendo {job.name}")
            try:
                payload, stamped, pages = self._render(job)
                if job.copies > 1:
                    payload = "\n".join([payload] * job.copies)
                with self.print_lock:
                    request_id = send_to_printer(payload, self.printer_name())
                self._last_zpl = payload
                job.state = JOB_COMPLETED
                mode = "matriz" if self.matrix_enabled() else "normal"
                note = "con caza toy" if stamped else "sin espacio para el logo"
                note = f"{note} {mode}"
                self._finish_download(job, ok=True)
                log.info("impresa %s %s páginas=%s cups=%s", job.name, note, pages, request_id)
                self.set_status(self._idle_status())
            except Exception as exc:
                job.state = JOB_ABORTED
                job.reasons = str(exc)
                log.exception("falló %s", job.name)
                self._finish_download(job, ok=False)
                self.set_status(f"Error: {short_error(exc)}")
            finally:
                self.busy = False

    def _render(self, job: Job) -> tuple[str, bool, int]:
        if job.plain:
            return job.data.decode("latin-1"), False, job.data.count(b"^XA") or 1
        if job.name.lower().endswith(".zip"):
            files = files_in_zip(job.data)
            if not files:
                raise ValueError("el ZIP no trae etiquetas")
            chunks: list[str] = []
            stamped = False
            pages = 0
            for name, blob in files:
                prepared = prepare(
                    blob,
                    self.logo_text(),
                    name,
                    matrix=self.matrix_enabled(),
                    placement=active_placement(),
                )
                chunks.append(prepared.zpl)
                stamped = stamped or prepared.stamped
                pages += prepared.pages
            return "\n".join(chunks), stamped, pages
        prepared = prepare(
            job.data,
            self.logo_text(),
            job.name,
            matrix=self.matrix_enabled(),
            placement=active_placement(),
        )
        return prepared.zpl, prepared.stamped, prepared.pages

    def _finish_download(self, job: Job, ok: bool) -> None:
        source = job.source
        try:
            if source is None:
                return
            if not ok or job.keep:
                if not ok and job.ident is not None:
                    self._ignore.add(job.ident)
                if job.keep and ok:
                    log.info("se conservó %s", source.name)
                elif not ok:
                    log.info("se dejó %s", source.name)
                return
            try:
                source.resolve().relative_to(DOWNLOADS.resolve())
            except ValueError:
                return
            try:
                source.unlink(missing_ok=True)
                log.info("borrado %s", source.name)
            except OSError:
                log.exception("no se pudo borrar %s", source)
        finally:
            self._inflight.discard(str(source) if source is not None else job.name)

