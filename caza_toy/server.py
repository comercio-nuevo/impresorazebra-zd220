"""AirPrint (IPP) y puerto 9100 para recibir etiquetas de la red."""

from __future__ import annotations

import logging
import socket
import threading
import time

from zeroconf import ServiceInfo, Zeroconf

from .ipp import (
    JOB,
    PRINTER,
    STATUS_BAD_REQUEST,
    STATUS_FORMAT,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    IppMessage,
    MessageBuilder,
    first,
    parse_message,
)
from .jobs import JOB_ABORTED, JOB_CANCELED, JOB_COMPLETED, JOB_PENDING, JOB_PROCESSING

log = logging.getLogger(__name__)

ACCEPTED_FORMATS = {"application/pdf", "application/octet-stream"}
MEDIA = "na_index-4x6_4x6in"
PRINT_JOB = 0x0002
VALIDATE_JOB = 0x0004
CREATE_JOB = 0x0005
SEND_DOCUMENT = 0x0006
CANCEL_JOB = 0x0008
GET_JOB_ATTRIBUTES = 0x0009
GET_JOBS = 0x000A
GET_PRINTER_ATTRIBUTES = 0x000B
IDENTIFY_PRINTER = 0x003C
CUPS_GET_PRINTERS = 0x4002


class PrintServer:
    def __init__(
        self,
        service,
        host: str = "0.0.0.0",
        ipp_port: int = 8631,
        raw_port: int = 9100,
        advertise: bool = True,
        ips: list[str] | None = None,
    ) -> None:
        self.service = service
        self.host = host
        self.ipp_port = ipp_port
        self.raw_port = raw_port
        self.advertise = advertise
        self.ips = list(ips or [])
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.bind_error: str | None = None
        self.raw_warning: str | None = None
        self.started = time.time()
        self._sockets: list[socket.socket] = []
        self._zc: Zeroconf | None = None
        self._services: list[ServiceInfo] = []
        self._partial: dict[int, bytearray] = {}
        self._bound = 0
        self._lock = threading.Lock()

    @property
    def display_ip(self) -> str:
        if self.ips:
            return self.ips[0]
        ip = getattr(self.service, "display_ip", "127.0.0.1")
        if not ip or ip == "sin red":
            return "127.0.0.1"
        return ip

    @property
    def uri(self) -> str:
        return f"ipp://{self.display_ip}:{self.ipp_port}/ipp/print"

    def start(self) -> None:
        threading.Thread(target=self._ipp_loop, name="caza-ipp", daemon=True).start()
        threading.Thread(target=self._raw_loop, name="caza-raw", daemon=True).start()
        self.ready.wait(8)

    def close(self) -> None:
        self.stop.set()
        for info in self._services:
            try:
                if self._zc is not None:
                    self._zc.unregister_service(info)
            except Exception:
                log.debug("no se pudo retirar el anuncio", exc_info=True)
        if self._zc is not None:
            self._zc.close()
            self._zc = None
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass

    def _mark_bound(self, error: str | None = None) -> None:
        with self._lock:
            if error:
                self.bind_error = f"{self.bind_error}; {error}" if self.bind_error else error
            self._bound += 1
            if self._bound >= 2:
                self.ready.set()

    def _ipp_loop(self) -> None:
        try:
            server = self._listen(self.ipp_port)
            self.ipp_port = server.getsockname()[1]
        except OSError as exc:
            self._mark_bound(f"AirPrint: {exc}")
            return
        try:
            self._advertise()
        except Exception:
            log.exception("Bonjour")
        self._mark_bound()
        self._accept_loop(server, self._handle_ipp)

    def _raw_loop(self) -> None:
        announced = False
        while not self.stop.is_set():
            try:
                server = self._listen(self.raw_port)
                self.raw_port = server.getsockname()[1]
            except OSError as exc:
                if self.raw_warning is None:
                    log.warning("puerto %s ocupado: %s", self.raw_port, exc)
                self.raw_warning = f"Puerto {self.raw_port} ocupado"
                if not announced:
                    self._mark_bound()
                    announced = True
                self.stop.wait(3)
                continue
            self.raw_warning = None
            log.info("ZPL escuchando en %s", self.raw_port)
            if not announced:
                self._mark_bound()
                announced = True
            self._accept_loop(server, self._handle_raw)
            return

    def _listen(self, port: int) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, port))
            server.listen(8)
        except OSError:
            server.close()
            raise
        server.settimeout(0.5)
        self._sockets.append(server)
        return server

    def _accept_loop(self, server: socket.socket, handler) -> None:
        while not self.stop.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=handler, args=(conn, addr), daemon=True).start()

    def _advertise(self) -> None:
        if not self.advertise:
            return
        ips = [ip for ip in self.ips if ip and not ip.startswith("127.")]
        if not ips:
            log.warning("sin IPv4 de red; AirPrint no se anuncia")
            return
        props = {
            "txtvers": "1",
            "qtotal": "1",
            "rp": "ipp/print",
            "ty": "CazaToy",
            "product": "(CazaToy)",
            "pdl": "application/pdf",
            "URF": "none",
            "Color": "F",
            "Duplex": "F",
            "Copies": "T",
            "usb_MFG": "Caza",
            "usb_MDL": "CazaToy",
            "note": "Etiquetas Caza Toy",
            "priority": "50",
            "Transparent": "F",
            "Binary": "F",
            "PaperMax": "legal-A4",
            "kind": "document",
            "UUID": str(getattr(self.service, "uuid", "")),
            "adminurl": f"http://{ips[0]}:{self.ipp_port}/",
        }
        label = socket.gethostname().split(".")[0] or "CazaToy"
        server_name = f"{label}.local."
        self._zc = Zeroconf()
        self._register("_ipp._tcp.local.", "CazaToy._ipp._tcp.local.", props, server_name, ips)
        try:
            self._register(
                "_universal._sub._ipp._tcp.local.",
                "CazaToy._universal._sub._ipp._tcp.local.",
                props,
                server_name,
                ips,
            )
        except Exception:
            log.exception("subtipo AirPrint")
        log.info("AirPrint anunciado en %s:%s", ips, self.ipp_port)

    def _register(self, type_: str, name: str, props: dict, server_name: str, ips: list[str]) -> None:
        info = ServiceInfo(
            type_,
            name,
            port=self.ipp_port,
            properties=props,
            server=server_name,
            parsed_addresses=ips,
        )
        if self._zc is None:
            return
        self._zc.register_service(info, allow_name_change=False)
        self._services.append(info)

    def _handle_raw(self, conn: socket.socket, addr) -> None:
        chunks: list[bytes] = []
        total = 0
        conn.settimeout(15)
        try:
            while total < 30_000_000:
                try:
                    data = conn.recv(65536)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
                total += len(data)
        finally:
            conn.close()
        payload = b"".join(chunks)
        if not payload.strip():
            return
        try:
            self.service.submit_bytes(payload, f"zpl-{addr[0]}")
            log.info("ZPL de %s (%s bytes)", addr[0], len(payload))
        except Exception:
            log.exception("puerto 9100 desde %s", addr[0])

    def _handle_ipp(self, conn: socket.socket, addr) -> None:
        conn.settimeout(120)
        pending = b""
        try:
            while not self.stop.is_set():
                parsed = _read_http(conn, pending)
                if parsed is None:
                    break
                request_line, headers, body, pending = parsed
                method = request_line.split(" ", 1)[0].upper() if request_line else ""
                closing = headers.get("connection", "").lower() == "close"
                if method == "GET":
                    conn.sendall(_http(200, "text/plain; charset=utf-8", self._status_page(), closing))
                elif method != "POST":
                    conn.sendall(_http(405, "text/plain", b"Usa POST\n", closing))
                elif len(body) > 30_000_000:
                    conn.sendall(_http(413, "text/plain", b"demasiado grande\n", closing))
                else:
                    conn.sendall(_http(200, "application/ipp", self.handle_ipp(body, addr), closing))
                if closing:
                    break
        except (TimeoutError, ConnectionError, OSError):
            pass
        finally:
            conn.close()

    def _status_page(self) -> bytes:
        paused = "sí" if self.service.paused else "no"
        text = (
            f"CazaToy\n"
            f"Impresora: Zebra ZD220\n"
            f"AirPrint: {self.uri}\n"
            f"ZPL: {self.display_ip}:{self.raw_port}\n"
            f"Pausada: {paused}\n"
        )
        return text.encode("utf-8")

    def handle_ipp(self, body: bytes, addr=("local", 0)) -> bytes:
        try:
            message = parse_message(body)
        except ValueError:
            return self._error(0, STATUS_BAD_REQUEST, "IPP mal formado")
        operation = message.code
        if operation in (GET_PRINTER_ATTRIBUTES, CUPS_GET_PRINTERS):
            return self._printer_attributes(message.request_id)
        if operation == VALIDATE_JOB:
            return self._validate(message)
        if operation == PRINT_JOB:
            return self._print_job(message, addr)
        if operation == CREATE_JOB:
            return self._create_job(message)
        if operation == SEND_DOCUMENT:
            return self._send_document(message)
        if operation == CANCEL_JOB:
            return self._cancel(message)
        if operation == GET_JOB_ATTRIBUTES:
            return self._job_attributes(message)
        if operation == GET_JOBS:
            return self._jobs(message)
        if operation == IDENTIFY_PRINTER:
            return self._ok(message.request_id).finish()
        return self._error(message.request_id, STATUS_UNSUPPORTED, "operación no soportada")

    def _ok(self, request_id: int, status: int = STATUS_OK) -> MessageBuilder:
        builder = MessageBuilder(status, request_id)
        builder.begin(0x01)
        builder.charset("attributes-charset", "utf-8")
        builder.language("attributes-natural-language", "es")
        return builder

    def _error(self, request_id: int, status: int, message: str) -> bytes:
        builder = self._ok(request_id, status)
        builder.text("status-message", message)
        return builder.finish()

    def _printer_attributes(self, request_id: int) -> bytes:
        paused = bool(self.service.paused)
        busy = bool(getattr(self.service, "busy", False))
        if paused:
            state = 5
            reasons = "paused"
        elif busy:
            state = 4
            reasons = "none"
        else:
            state = 3
            reasons = "none"
        queued = sum(
            1
            for job in self.service.snapshot_jobs()
            if job.queued and job.state in (JOB_PENDING, JOB_PROCESSING)
        )
        builder = self._ok(request_id)
        builder.begin(PRINTER)
        builder.charset("charset-configured", "utf-8")
        builder.charset("charset-supported", "utf-8")
        builder.language("natural-language-configured", "es")
        builder.language("generated-natural-language-supported", "es")
        builder.uri("printer-uri-supported", self.uri)
        builder.keyword("uri-security-supported", "none")
        builder.keyword("uri-authentication-supported", "none")
        builder.name_value("printer-name", "CazaToy")
        builder.text("printer-info", "Etiquetas Caza Toy")
        builder.text("printer-make-and-model", "CazaToy Zebra ZD220")
        builder.text("printer-location", "local")
        builder.enum("printer-state", state)
        builder.keyword("printer-state-reasons", reasons)
        builder.keywords("ipp-versions-supported", ["1.1", "2.0"])
        builder.enums(
            "operations-supported",
            [
                PRINT_JOB,
                VALIDATE_JOB,
                CREATE_JOB,
                SEND_DOCUMENT,
                CANCEL_JOB,
                GET_JOB_ATTRIBUTES,
                GET_JOBS,
                GET_PRINTER_ATTRIBUTES,
            ],
        )
        builder.mime("document-format-default", "application/pdf")
        builder.mimes("document-format-supported", ["application/pdf", "application/octet-stream"])
        builder.keyword("pdl-override-supported", "not-attempted")
        builder.boolean("printer-is-accepting-jobs", True)
        builder.integer("queued-job-count", queued)
        builder.boolean("color-supported", False)
        builder.integer("copies-default", 1)
        builder.range_of("copies-supported", 1, 20)
        builder.keyword("media-default", MEDIA)
        builder.keyword("media-supported", MEDIA)
        builder.keyword("media-ready", MEDIA)
        builder.keyword("media-type-supported", "labels")
        builder.keyword("sides-default", "one-sided")
        builder.keyword("sides-supported", "one-sided")
        builder.enum("orientation-requested-default", 3)
        builder.resolution("printer-resolution-default")
        builder.resolution("printer-resolution-supported")
        builder.enum("print-quality-default", 4)
        builder.keyword("compression-supported", "none")
        builder.integer("printer-up-time", max(1, int(time.time() - self.started)))
        builder.uri("printer-uuid", f"urn:uuid:{getattr(self.service, 'uuid', 'caza-toy')}")
        builder.boolean("multiple-document-jobs-supported", False)
        builder.integer("pages-per-minute", 20)
        return builder.finish()

    def _validate(self, message: IppMessage) -> bytes:
        fmt = _document_format(message)
        if fmt and fmt not in ACCEPTED_FORMATS:
            return self._error(message.request_id, STATUS_FORMAT, "usa PDF")
        return self._ok(message.request_id).finish()

    def _print_job(self, message: IppMessage, addr) -> bytes:
        fmt = _document_format(message)
        if fmt and fmt not in ACCEPTED_FORMATS:
            return self._error(message.request_id, STATUS_FORMAT, "usa PDF")
        if not message.document.strip():
            return self._error(message.request_id, STATUS_BAD_REQUEST, "documento vacío")
        name = _job_name(message, f"airprint-{addr[0]}")
        job = self.service.reserve_job(name)
        self.service.start_job(job, message.document, _copies(message))
        log.info("AirPrint de %s (%s bytes)", addr[0], len(message.document))
        builder = self._ok(message.request_id)
        self._write_job(builder, job)
        return builder.finish()

    def _create_job(self, message: IppMessage) -> bytes:
        job = self.service.reserve_job(_job_name(message, "airprint"))
        job.copies = _copies(message)
        self._partial[job.id] = bytearray()
        builder = self._ok(message.request_id)
        self._write_job(builder, job)
        return builder.finish()

    def _send_document(self, message: IppMessage) -> bytes:
        job_id = _job_id(message)
        job = self.service.jobs.get(job_id) if job_id is not None else None
        if job is None:
            return self._error(message.request_id, STATUS_NOT_FOUND, "trabajo inexistente")
        buffer = self._partial.setdefault(job.id, bytearray())
        buffer += message.document
        last = first(_group(message, 0x01), "last-document", True)
        if last:
            self.service.start_job(job, bytes(buffer), _copies(message) or job.copies)
            self._partial.pop(job.id, None)
        builder = self._ok(message.request_id)
        self._write_job(builder, job)
        return builder.finish()

    def _cancel(self, message: IppMessage) -> bytes:
        job_id = _job_id(message)
        job = self.service.jobs.get(job_id) if job_id is not None else None
        if job is None:
            return self._error(message.request_id, STATUS_NOT_FOUND, "trabajo inexistente")
        self.service.cancel_job(job)
        builder = self._ok(message.request_id)
        self._write_job(builder, job)
        return builder.finish()

    def _job_attributes(self, message: IppMessage) -> bytes:
        job_id = _job_id(message)
        job = self.service.jobs.get(job_id) if job_id is not None else None
        if job is None:
            return self._error(message.request_id, STATUS_NOT_FOUND, "trabajo inexistente")
        builder = self._ok(message.request_id)
        self._write_job(builder, job)
        return builder.finish()

    def _jobs(self, message: IppMessage) -> bytes:
        attrs = _group(message, 0x01)
        which = first(attrs, "which-jobs", "not-completed")
        limit = first(attrs, "limit", 50)
        if not isinstance(limit, int):
            limit = 50
        selected = []
        for job in self.service.snapshot_jobs():
            done = job.state in (JOB_CANCELED, JOB_ABORTED, JOB_COMPLETED)
            if which == "completed" and done:
                selected.append(job)
            elif which == "all":
                selected.append(job)
            elif which != "completed" and not done:
                selected.append(job)
        builder = self._ok(message.request_id)
        for job in selected[-limit:]:
            self._write_job(builder, job)
        return builder.finish()

    def _write_job(self, builder: MessageBuilder, job) -> None:
        if job.state == JOB_CANCELED:
            reason = "job-canceled"
        elif job.state == JOB_ABORTED:
            reason = "aborted-by-system"
        else:
            reason = "none"
        builder.begin(JOB)
        builder.integer("job-id", job.id)
        builder.uri("job-uri", f"{self.uri}/{job.id}")
        builder.uri("job-printer-uri", self.uri)
        builder.enum("job-state", job.state)
        builder.keyword("job-state-reasons", reason)
        builder.name_value("job-name", job.name)
        builder.integer("copies", job.copies)


def _group(message: IppMessage, tag: int) -> dict:
    for group_tag, attrs in message.groups:
        if group_tag == tag:
            return attrs
    return {}


def _document_format(message: IppMessage) -> str | None:
    for tag in (0x01, JOB):
        value = first(_group(message, tag), "document-format")
        if value:
            return str(value).split(";", 1)[0].strip().lower()
    return None


def _copies(message: IppMessage) -> int:
    for tag in (JOB, 0x01):
        value = first(_group(message, tag), "copies")
        if isinstance(value, int) and value > 0:
            return min(20, value)
    return 1


def _job_name(message: IppMessage, default: str) -> str:
    for key in ("job-name", "document-name"):
        for tag in (0x01, JOB):
            value = first(_group(message, tag), key)
            if value:
                return str(value)
    return default


def _job_id(message: IppMessage) -> int | None:
    for tag in (0x01, JOB):
        attrs = _group(message, tag)
        value = first(attrs, "job-id")
        if isinstance(value, int):
            return value
        uri = first(attrs, "job-uri")
        if uri:
            tail = str(uri).rstrip("/").split("/")[-1]
            if tail.isdigit():
                return int(tail)
    return None


def _http(code: int, content_type: str, body: bytes, closing: bool = False) -> bytes:
    reasons = {200: "OK", 405: "Method Not Allowed", 413: "Payload Too Large"}
    connection = "close" if closing else "keep-alive"
    head = (
        f"HTTP/1.1 {code} {reasons.get(code, 'OK')}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: {connection}\r\n"
        "\r\n"
    )
    return head.encode("ascii") + body


def _read_http(conn: socket.socket, pending: bytes):
    buf = pending
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        buf += chunk
        if len(buf) > 1_000_000 and b"\r\n\r\n" not in buf:
            raise ValueError("cabeceras demasiado grandes")
    header_blob, buf = buf.split(b"\r\n\r\n", 1)
    lines = header_blob.decode("iso-8859-1", "replace").split("\r\n")
    request_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    if "100-continue" in headers.get("expect", "").lower():
        conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
    if "content-length" in headers:
        needed = int(headers["content-length"])
        while len(buf) < needed:
            chunk = conn.recv(min(65536, needed - len(buf)))
            if not chunk:
                break
            buf += chunk
        return request_line, headers, buf[:needed], buf[needed:]
    if "chunked" in headers.get("transfer-encoding", "").lower():
        body, extra = _read_chunked(buf, conn)
        return request_line, headers, body, extra
    return request_line, headers, buf, b""


def _read_chunked(buf: bytes, conn: socket.socket) -> tuple[bytes, bytes]:
    body = bytearray()
    while True:
        while b"\r\n" not in buf:
            more = conn.recv(4096)
            if not more:
                return bytes(body), buf
            buf += more
        line, buf = buf.split(b"\r\n", 1)
        size = int(line.split(b";", 1)[0], 16)
        if size == 0:
            while True:
                while b"\r\n" not in buf:
                    more = conn.recv(4096)
                    if not more:
                        return bytes(body), b""
                    buf += more
                line, buf = buf.split(b"\r\n", 1)
                if line == b"":
                    return bytes(body), buf
        while len(buf) < size + 2:
            more = conn.recv(65536)
            if not more:
                break
            buf += more
        body += buf[:size]
        buf = buf[size + 2 :]
