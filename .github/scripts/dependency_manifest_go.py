"""go.mod and go.sum grammar.

go_mod returns (entries, residue). An entry is (module, version, top, text);
a require marked `// indirect` is not top, and text is the line with its
version masked. Replace, exclude and retract lines, and every other
directive, stay in residue.

go_sum returns one entry per checksum line: (module, version, False, line).
The version keeps a `/go.mod` suffix, so the hash of a module's go.mod and the
hash of its tree are separate entries. Any other line is residue.
go_sum_hash reads the `h1:` hash an entry records.

go_zip_hash computes that `h1:` hash of a module zip, as the go command does
before it installs the zip.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
import zlib

from dependency_manifest_lines import Entry, Parsed

# golang.org/x/mod/zip.MaxZipFile: the go command reads no module zip, and extracts no content, larger than this.
GO_ZIP_LIMIT = 500 << 20

_GO_MOD_RE = re.compile(r"^\s*(?:require\s+)?([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)\s+(v\S+)")
_INDIRECT_RE = re.compile(r"\s*indirect\s*(?:;|$)")
_GO_SUM_RE = re.compile(r"^([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+) (v[^\s/]+(?:/go\.mod)?) h1:\S+$")
_GO_BLOCK_STARTS = frozenset({"require(", "replace(", "exclude(", "retract("})


def _go_mod_lines(text: str) -> list[tuple[str, str]]:
    """Classify go.mod lines. Only require lines are entries."""
    classified: list[tuple[str, str]] = []
    block = ""
    for line in text.splitlines(keepends=True):
        compact = "".join(line.split("//", 1)[0].split())
        if block:
            classified.append(("entry" if block == "require" else "residue", line))
            if compact == ")":
                block = ""
            continue
        if compact in _GO_BLOCK_STARTS:
            block = compact[:-1]
            classified.append(("residue", line))
            continue
        if compact.startswith(("replace", "exclude", "retract")):
            classified.append(("residue", line))
            continue
        classified.append(("entry", line))
    return classified


def go_mod(text: str) -> Parsed:
    entries: list[Entry] = []
    residue: list[str] = []
    for kind, line in _go_mod_lines(text):
        code, _, comment = line.partition("//")
        match = _GO_MOD_RE.match(code) if kind == "entry" else None
        if match:
            masked = line[: match.start(2)] + "\0" + line[match.end(2) :]
            entries.append((match.group(1), match.group(2), not _INDIRECT_RE.match(comment), masked.strip()))
            continue
        residue.append(line)
    return entries, "".join(residue)


def go_sum(text: str) -> Parsed:
    entries: list[Entry] = []
    residue: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _GO_SUM_RE.match(line.strip())
        if match:
            entries.append((match.group(1), match.group(2), False, line.strip()))
        else:
            residue.append(line)
    return entries, "".join(residue)


def go_sum_hash(entry: Entry) -> str:
    """The `h1:` hash a go_sum entry records. Every line hashes a version the go command may install."""
    return entry[3].rsplit(" ", 1)[-1]


def go_zip_hash(archive: bytes) -> str:
    """Go's dirhash.Hash1 of a module zip, as go.sum records it, or "" when it is not a zip the go command reads.

    Hash1 is the sha256 of one `<sha256 hex>  <name>` line per file, in byte order of the names the zip stores.
    """
    lines: dict[bytes, bytes] = {}
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            for info in zipped.infolist():
                name = info.orig_filename.encode("utf-8" if info.flag_bits & 0x800 else "cp437")
                if b"\n" in name or name in lines:
                    return ""
                digest = hashlib.sha256()
                with zipped.open(info) as handle:
                    while chunk := handle.read(1 << 20):
                        total += len(chunk)
                        if total > GO_ZIP_LIMIT:
                            return ""
                        digest.update(chunk)
                lines[name] = digest.hexdigest().encode() + b"  " + name + b"\n"
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, OSError, ValueError, zlib.error):
        return ""
    summary = hashlib.sha256(b"".join(lines[name] for name in sorted(lines)))
    return "h1:" + base64.b64encode(summary.digest()).decode()
