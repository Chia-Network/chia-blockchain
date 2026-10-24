"""Line grammars: workflow and composite-action `uses:`, Dockerfile `FROM`, and Terraform versions.

Entry and Parsed are the one shape every grammar returns: (entries, residue),
or None when the text does not parse.
An entry is (name, version, top, text) and every entry here is a declaration,
so top. A line entry's text is its line with the version masked, so the rest of
the line cannot change unseen; a .terraform.lock.hcl provider block is one
entry whose text is the whole block. Residue is every line that is not an entry.
"""

from __future__ import annotations

import re

# (name, version, top, text)
Entry = tuple[str, str, bool, str]
Parsed = tuple[list[Entry], str]

# `uses: owner/repo[/path]@ref`, optionally a list item, optionally quoted, optionally with a trailing comment.
_USES_RE = re.compile(
    r"""^\s*(?:-\s+)?uses:\s*(["']?)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?)@([^\s"'#]+)\1\s*(?:#.*)?$"""
)
_FROM_RE = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+\S+)?\s*$", re.IGNORECASE)
_PROVIDER_RE = re.compile(r'^provider\s+"([^"]+)"\s*\{\s*$')
_TF_VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]*)"\s*$')
_TF_SOURCE_RE = re.compile(r'^\s*source\s*=\s*"([^"]*)"\s*$')


def _masked(line: str, match: re.Match[str], group: int, keep: str = "") -> str:
    return (line[: match.start(group)] + keep + "\0" + line[match.end(group) :]).strip()


def workflow_uses(text: str) -> Parsed:
    entries: list[Entry] = []
    residue: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _USES_RE.match(line)
        if match:
            entries.append((match.group(2), match.group(3), True, _masked(line, match, 3)))
        else:
            residue.append(line)
    return entries, "".join(residue)


def dockerfile_from(text: str) -> Parsed:
    """Image and `tag[@digest]` of each FROM instruction. A registry port is part of the image name.

    A line that continues the instruction before it (after a trailing `\\`, across comment lines) is never a FROM.
    """
    entries: list[Entry] = []
    residue: list[str] = []
    continued = False
    for line in text.splitlines(keepends=True):
        match = None if continued else _FROM_RE.match(line)
        # Docker drops a comment line inside a continuation, so it does not end one.
        if not (continued and line.lstrip().startswith("#")):
            continued = line.rstrip().endswith("\\")
        if not match:
            residue.append(line)
            continue
        image, _, digest = match.group(1).partition("@")
        name, colon, tag = image.rpartition(":")
        if not colon or "/" in tag:
            name, tag = image, ""
        entries.append((name, tag + (f"@{digest}" if digest else ""), True, _masked(line, match, 1, name)))
    return entries, "".join(residue)


def terraform_lock(text: str) -> Parsed | None:
    """One entry per `provider "address" { ... }` block. An unclosed or versionless block does not parse."""
    entries: list[Entry] = []
    residue: list[str] = []
    provider: str | None = None
    version = ""
    block: list[str] = []
    for line in text.splitlines(keepends=True):
        if provider is None:
            match = _PROVIDER_RE.match(line)
            if match:
                provider, version, block = match.group(1), "", [line]
            else:
                residue.append(line)
            continue
        block.append(line)
        if line.rstrip() == "}":
            if not version:
                return None
            entries.append((provider, version, True, "".join(block)))
            provider = None
            continue
        match = _TF_VERSION_RE.match(line)
        if match:
            version = match.group(1)
    return None if provider is not None else (entries, "".join(residue))


def terraform_config(text: str) -> Parsed:
    """Each `version = "..."` line of a .tf file, named by the `source` line before it. Every other line is residue."""
    entries: list[Entry] = []
    residue: list[str] = []
    source = ""
    for line in text.splitlines(keepends=True):
        named = _TF_SOURCE_RE.match(line)
        source = named.group(1) if named else source
        match = _TF_VERSION_RE.match(line)
        if match:
            entries.append((source, match.group(1), True, _masked(line, match, 1)))
        else:
            residue.append(line)
    return entries, "".join(residue)
