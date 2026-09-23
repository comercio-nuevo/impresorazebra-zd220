"""Trabajos de impresión que comparten la cola, el menú y la red."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

JOB_PENDING = 3
JOB_PROCESSING = 5
JOB_CANCELED = 7
JOB_ABORTED = 8
JOB_COMPLETED = 9


@dataclass
class Job:
    id: int
    name: str
    path: Path | None = None
    data: bytes = b""
    source: Path | None = None
    ident: tuple | None = None
    copies: int = 1
    state: int = JOB_PENDING
    reasons: str = "none"
    queued: bool = False
    created: float = field(default_factory=time.time)
