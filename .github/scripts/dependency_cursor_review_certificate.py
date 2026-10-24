"""The source repository a Fulcio signing certificate names.

Fulcio writes the repository URI (1.3.6.1.4.1.57264.1.12) and the source
commit (1.3.6.1.4.1.57264.1.13) of the workflow that signed into certificate
extensions, each a DER UTF8String. This is a parser only: it reads DER and
never verifies a signature or a chain.
"""

from __future__ import annotations

from typing import NamedTuple

_FULCIO = bytes.fromhex("2b0601040183bf3001")
_SOURCE_REPO, _SOURCE_COMMIT = _FULCIO + b"\x0c", _FULCIO + b"\x0d"


class Source(NamedTuple):
    repo_uri: str = ""
    commit: str = ""


def _tlvs(data: bytes) -> list[tuple[int, bytes]]:
    """The DER (tag, value) items in `data`. ValueError when they do not fill it exactly."""
    items, index = [], 0
    while index < len(data):
        if index + 2 > len(data):
            raise ValueError("truncated DER")
        tag, length, index = data[index], data[index + 1], index + 2
        if length & 0x80:
            width = length & 0x7F
            length, index = int.from_bytes(data[index : index + width], "big"), index + width
        if index + length > len(data):
            raise ValueError("truncated DER")
        items.append((tag, data[index : index + length]))
        index += length
    return items


def _extensions(der: bytes, found: dict[bytes, str]) -> dict[bytes, str]:
    """The two source extensions under `der` as OID bytes -> UTF8String value.

    Older Fulcio extensions hold raw strings, not DER, so only these two are decoded.
    """
    for tag, value in _tlvs(der):
        if not tag & 0x20:
            continue
        children = _tlvs(value)
        (oid_tag, oid), (last_tag, last) = (children[0], children[-1]) if children else ((0, b""), (0, b""))
        if tag == 0x30 and oid_tag == 0x06 and oid in {_SOURCE_REPO, _SOURCE_COMMIT} and last_tag == 0x04:
            inner = _tlvs(last)
            if len(inner) == 1 and inner[0][0] == 0x0C:
                found[oid] = inner[0][1].decode("utf-8")
        else:
            _extensions(value, found)
    return found


def source(der: bytes) -> Source:
    """The source repository extensions of a DER certificate, "" for each one it lacks.

    ValueError, UnicodeDecodeError, IndexError or RecursionError when the DER is malformed.
    """
    found = _extensions(der, {})
    return Source(found.get(_SOURCE_REPO, ""), found.get(_SOURCE_COMMIT, ""))
