import socket
import tempfile
import time
import unittest
from pathlib import Path

from caza_toy.ipp import JOB, PRINTER, STATUS_FORMAT, STATUS_OK, MessageBuilder, first, parse_message
from caza_toy.jobs import JOB_PROCESSING, Job
from caza_toy.server import PrintServer
from caza_toy.watch import should_take


class FakePrinter:
    def __init__(self) -> None:
        self.jobs = {}
        self.started = []
        self.paused = False
        self.busy = False
        self.uuid = "11111111-1111-1111-1111-111111111111"
        self.display_ip = "127.0.0.1"
        self.seq = 0

    def reserve_job(self, name: str) -> Job:
        self.seq += 1
        job = Job(id=self.seq, name=name, path=Path(f"/tmp/caza-{self.seq}"))
        self.jobs[job.id] = job
        return job

    def start_job(self, job: Job, data: bytes, copies: int = 1) -> None:
        job.copies = copies
        job.state = JOB_PROCESSING
        job.queued = True
        self.started.append((job.id, data, copies))

    def submit_bytes(self, data: bytes, name: str, copies: int = 1) -> Job:
        job = self.reserve_job(name)
        self.start_job(job, data, copies)
        return job

    def cancel_job(self, job: Job) -> None:
        job.state = 7

    def snapshot_jobs(self) -> list[Job]:
        return list(self.jobs.values())


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakePrinter()
        self.server = PrintServer(
            self.fake,
            host="127.0.0.1",
            ipp_port=0,
            raw_port=0,
            advertise=False,
            ips=["127.0.0.1"],
        )
        self.server.start()
        self.assertIsNone(self.server.bind_error)

    def tearDown(self) -> None:
        self.server.close()

    def test_get_printer_attributes(self):
        body = self._post(self._request(0x000B))
        message = parse_message(body)
        self.assertEqual(message.code, STATUS_OK)
        attrs = _group(message, PRINTER)
        self.assertEqual(first(attrs, "printer-name"), "CazaToy")
        self.assertIn("application/pdf", first(attrs, "document-format-supported") and attrs["document-format-supported"])
        self.assertEqual(first(attrs, "media-default"), "na_index-4x6_4x6in")

    def test_print_job_queues_the_pdf(self):
        pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        request = self._request(0x0002)
        builder = MessageBuilder(0x0002, 7)
        builder.begin(0x01)
        builder.charset("attributes-charset", "utf-8")
        builder.language("attributes-natural-language", "es")
        builder.uri("printer-uri", self.server.uri)
        builder.mime("document-format", "application/pdf")
        builder.name_value("job-name", "guia")
        builder.begin(JOB)
        builder.integer("copies", 2)
        raw = builder.finish_with_document(pdf)
        self._post(raw)
        self.assertEqual(len(self.fake.started), 1)
        job_id, data, copies = self.fake.started[0]
        self.assertEqual(job_id, 1)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(copies, 2)
        self.assertIsNotNone(request)

    def test_urf_is_rejected(self):
        builder = MessageBuilder(0x0004, 3)
        builder.begin(0x01)
        builder.charset("attributes-charset", "utf-8")
        builder.language("attributes-natural-language", "es")
        builder.uri("printer-uri", self.server.uri)
        builder.mime("document-format", "image/urf")
        message = parse_message(self._post(builder.finish()))
        self.assertEqual(message.code, STATUS_FORMAT)

    def test_raw_port_accepts_zpl(self):
        conn = socket.create_connection(("127.0.0.1", self.server.raw_port), timeout=5)
        conn.sendall(b"^XA^FO10,10^FDHola^FS^XZ")
        conn.close()
        deadline = time.time() + 2
        while not self.fake.started and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.fake.started)
        self.assertTrue(self.fake.started[0][1].startswith(b"^XA"))

    def test_hidden_downloads_are_ignored(self):
        self.assertFalse(should_take(Path(".guia.pdf")))
        self.assertFalse(should_take(Path("guia.pdf.crdownload")))
        folder = Path(tempfile.mkdtemp())
        pdf = folder / "guia.pdf"
        pdf.write_bytes(b"%PDF")
        other = folder / "foto.heic"
        other.write_bytes(b"x")
        jpg = folder / "foto.jpg"
        jpg.write_bytes(b"x")
        self.assertTrue(should_take(pdf))
        self.assertFalse(should_take(jpg))
        self.assertTrue(should_take(jpg, images=True))
        self.assertFalse(should_take(other))

    def _request(self, operation: int) -> bytes:
        builder = MessageBuilder(operation, 1)
        builder.begin(0x01)
        builder.charset("attributes-charset", "utf-8")
        builder.language("attributes-natural-language", "es")
        builder.uri("printer-uri", self.server.uri)
        return builder.finish()

    def _post(self, body: bytes) -> bytes:
        conn = socket.create_connection(("127.0.0.1", self.server.ipp_port), timeout=5)
        header = (
            f"POST /ipp/print HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.server.ipp_port}\r\n"
            f"Content-Type: application/ipp\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        conn.sendall(header + body)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        length = 0
        for line in head.decode("iso-8859-1").split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        while len(rest) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            rest += chunk
        conn.close()
        return rest[:length]


def _group(message, tag):
    for group_tag, attrs in message.groups:
        if group_tag == tag:
            return attrs
    return {}


if __name__ == "__main__":
    unittest.main()
