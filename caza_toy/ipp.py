"""Codificación mínima de IPP/2.0 para AirPrint."""

from __future__ import annotations

from dataclasses import dataclass

OP = 0x01
JOB = 0x02
PRINTER = 0x04
END = 0x03

TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_RESOLUTION = 0x32
TAG_RANGE = 0x33
TAG_TEXT = 0x41
TAG_NAME = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_MIME = 0x49

STATUS_OK = 0x0000
STATUS_BAD_REQUEST = 0x0400
STATUS_NOT_FOUND = 0x0406
STATUS_FORMAT = 0x040B
STATUS_UNSUPPORTED = 0x0501


@dataclass
class IppMessage:
    code: int
    request_id: int
    groups: list[tuple[int, dict[str, list]]]
    document: bytes


def first(attrs: dict, name: str, default=None):
    values = attrs.get(name)
    if not values:
        return default
    return values[0]


def parse_message(data: bytes) -> IppMessage:
    if len(data) < 8:
        raise ValueError("IPP incompleto")
    code = int.from_bytes(data[2:4], "big")
    request_id = int.from_bytes(data[4:8], "big")
    index = 8
    groups: list[tuple[int, dict[str, list]]] = []
    current_tag: int | None = None
    current: dict[str, list] = {}
    last_name: str | None = None
    while index < len(data):
        tag = data[index]
        if tag == END:
            if current_tag is not None:
                groups.append((current_tag, current))
            index += 1
            break
        if tag < 0x10:
            if current_tag is not None:
                groups.append((current_tag, current))
            current_tag = tag
            current = {}
            last_name = None
            index += 1
            continue
        if index + 3 > len(data):
            raise ValueError("atributo truncado")
        name_len = int.from_bytes(data[index + 1 : index + 3], "big")
        index += 3
        if index + name_len + 2 > len(data):
            raise ValueError("nombre truncado")
        name = data[index : index + name_len].decode("utf-8", "replace")
        index += name_len
        value_len = int.from_bytes(data[index : index + 2], "big")
        index += 2
        if index + value_len > len(data):
            raise ValueError("valor truncado")
        raw = data[index : index + value_len]
        index += value_len
        if name:
            last_name = name
        if not last_name:
            continue
        current.setdefault(last_name, []).append(_decode(tag, raw))
    return IppMessage(code, request_id, groups, data[index:])


def _decode(tag: int, raw: bytes):
    if tag in (TAG_INTEGER, TAG_ENUM):
        return int.from_bytes(raw, "big", signed=True) if raw else 0
    if tag == TAG_BOOLEAN:
        return bool(raw and raw[0])
    if tag == TAG_RANGE and len(raw) == 8:
        return (
            int.from_bytes(raw[:4], "big", signed=True),
            int.from_bytes(raw[4:], "big", signed=True),
        )
    if tag == TAG_RESOLUTION and len(raw) == 9:
        return (int.from_bytes(raw[:4], "big"), int.from_bytes(raw[4:8], "big"), raw[8])
    return raw.decode("utf-8", "replace")


class MessageBuilder:
    def __init__(self, code: int, request_id: int) -> None:
        self.buf = bytearray((2, 0))
        self.buf += int(code).to_bytes(2, "big")
        self.buf += int(request_id).to_bytes(4, "big")

    def begin(self, tag: int) -> None:
        self.buf.append(tag)

    def _add(self, tag: int, name: str, raw: bytes) -> None:
        encoded = name.encode("utf-8")
        self.buf.append(tag)
        self.buf += len(encoded).to_bytes(2, "big")
        self.buf += encoded
        self.buf += len(raw).to_bytes(2, "big")
        self.buf += raw

    def keyword(self, name: str, value: str) -> None:
        self._add(TAG_KEYWORD, name, value.encode("utf-8"))

    def keywords(self, name: str, values: list[str]) -> None:
        for index, value in enumerate(values):
            self.keyword(name if index == 0 else "", value)

    def text(self, name: str, value: str) -> None:
        self._add(TAG_TEXT, name, value.encode("utf-8"))

    def name_value(self, name: str, value: str) -> None:
        self._add(TAG_NAME, name, value.encode("utf-8"))

    def uri(self, name: str, value: str) -> None:
        self._add(TAG_URI, name, value.encode("utf-8"))

    def mime(self, name: str, value: str) -> None:
        self._add(TAG_MIME, name, value.encode("utf-8"))

    def mimes(self, name: str, values: list[str]) -> None:
        for index, value in enumerate(values):
            self.mime(name if index == 0 else "", value)

    def charset(self, name: str, value: str) -> None:
        self._add(TAG_CHARSET, name, value.encode("utf-8"))

    def language(self, name: str, value: str) -> None:
        self._add(TAG_LANGUAGE, name, value.encode("utf-8"))

    def integer(self, name: str, value: int) -> None:
        self._add(TAG_INTEGER, name, int(value).to_bytes(4, "big", signed=True))

    def enum(self, name: str, value: int) -> None:
        self._add(TAG_ENUM, name, int(value).to_bytes(4, "big", signed=True))

    def enums(self, name: str, values: list[int]) -> None:
        for index, value in enumerate(values):
            self.enum(name if index == 0 else "", value)

    def boolean(self, name: str, value: bool) -> None:
        self._add(TAG_BOOLEAN, name, bytes((1 if value else 0,)))

    def range_of(self, name: str, low: int, high: int) -> None:
        raw = int(low).to_bytes(4, "big", signed=True) + int(high).to_bytes(4, "big", signed=True)
        self._add(TAG_RANGE, name, raw)

    def resolution(self, name: str, x: int = 203, y: int = 203) -> None:
        raw = int(x).to_bytes(4, "big") + int(y).to_bytes(4, "big") + bytes((3,))
        self._add(TAG_RESOLUTION, name, raw)

    def finish(self) -> bytes:
        self.buf.append(END)
        return bytes(self.buf)

    def finish_with_document(self, document: bytes) -> bytes:
        self.buf.append(END)
        self.buf += document
        return bytes(self.buf)
