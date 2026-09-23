"""Vigila Descargas y abre los ZIP en un temporal que no se queda."""

from __future__ import annotations

import io
import logging
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)

PRINT_SUFFIXES = {".pdf", ".zpl", ".txt", ".jpg", ".jpeg", ".png", ".csv", ".zip"}
_SKIP_SUFFIXES = {".crdownload", ".download", ".part", ".partial", ".tmp"}
_MAX_MEMBER = 30_000_000


def should_take(path: Path) -> bool:
    if path.name.startswith(".") or not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix in _SKIP_SUFFIXES:
        return False
    return suffix in PRINT_SUFFIXES


def file_ident(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return (path.name, stat.st_size, stat.st_mtime_ns)


def files_in_zip(data: bytes, depth: int = 0) -> list[tuple[str, bytes]]:
    """Descomprime en un temporal, devuelve los archivos imprimibles y borra el temporal."""
    if depth > 2:
        return []
    found: list[tuple[str, bytes]] = []
    with tempfile.TemporaryDirectory(prefix="cazatoy-") as folder:
        root = Path(folder)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir() or info.file_size > _MAX_MEMBER:
                    continue
                name = Path(info.filename).name
                if not name or name.startswith(".") or name.startswith("__MACOSX"):
                    continue
                suffix = Path(name).suffix.lower()
                if suffix not in PRINT_SUFFIXES:
                    continue
                blob = archive.read(info)
                (root / name).write_bytes(blob)
                if suffix == ".zip":
                    found.extend(files_in_zip(blob, depth + 1))
                else:
                    found.append((name, blob))
    found.sort(key=lambda item: (0 if item[0].lower().endswith(".zpl") else 1, item[0].lower()))
    return found


def run_inbox(inbox: Path, ingest, stop: threading.Event, skip_existing: bool = True) -> None:
    skipped: set[tuple[str, int, int]] = set()
    if skip_existing and inbox.exists():
        for path in inbox.iterdir():
            ident = file_ident(path)
            if ident is not None:
                skipped.add(ident)
    wake = threading.Event()

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                wake.set()

        def on_moved(self, event):
            if not event.is_directory:
                wake.set()

        def on_modified(self, event):
            if not event.is_directory:
                wake.set()

    observer = Observer()
    observer.schedule(Handler(), str(inbox), recursive=False)
    observer.start()
    try:
        while not stop.is_set():
            wake.wait(1.0)
            wake.clear()
            _scan(inbox, ingest, skipped)
    finally:
        observer.stop()
        observer.join(timeout=2)


def _scan(inbox: Path, ingest, skipped: set[tuple[str, int, int]]) -> None:
    try:
        paths = list(inbox.iterdir())
    except OSError:
        log.exception("no se pudo leer Descargas")
        return
    for path in paths:
        ident = file_ident(path)
        if ident is None or ident in skipped or not should_take(path):
            continue
        if not _stable(path):
            continue
        fresh = file_ident(path)
        if fresh is None or fresh in skipped:
            continue
        try:
            ingest(path)
        except Exception:
            log.exception("descargas %s", path.name)


def _stable(path: Path) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False
    time.sleep(0.35)
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False
