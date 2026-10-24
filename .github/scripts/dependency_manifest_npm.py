"""package.json, package-lock.json, npm-shrinkwrap.json and yarn.lock grammar.

Each reader returns (entries, residue), or None when the text does not parse.
An entry is (name, version, top, text). A package.json spec is a declaration,
so it is top, and its text is its section. In a lock, top marks the copy a
declaration installs, which is the top-level `node_modules/<name>` path, a
lockfile v1 top-level record, or any Yarn stanza; a nested or workspace copy
is not top. A lock entry's text is its whole record, or its whole stanza with
the descriptor header; package_lock_integrity and yarn_lock_integrity read the
integrity it records. A lock restates each root declaration as an entry at
the version its top copy installs, so a declaration in a lock can change only
with that version. Residue is the document left once the entries are taken out.

A lock copy installed from anywhere but the registry tarball for its own name
and version keeps its version with the source appended, so it is never read as
an exact registry version: a git, aliased or other-host copy is not scanned as
the registry package.
"""

from __future__ import annotations

import json
import re

from dependency_manifest_lines import Entry, Parsed

_YARN_DESCRIPTOR_RE = re.compile(r'(@?[^@"\s]+)@')
_LOCK_PREFIX = "node_modules/"
_YARN_VERSION_RE = re.compile(r'^  version "([^"]+)"')
_YARN_RESOLVED_RE = re.compile(r'^  resolved "([^"]+)"')
_YARN_INTEGRITY_RE = re.compile(r"^  integrity (\S+)$")
_REGISTRIES = ("https://registry.npmjs.org/", "https://registry.yarnpkg.com/")
_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _direct_lock_name(key: str) -> str:
    """Leaf package name of a lockfile path, or "" when the path is not a package.

    Nested copies (`node_modules/a/node_modules/b`) and workspace paths (such
    as `packages/gui/node_modules/b`) name the leaf package too. A path that
    continues past the package name stays in residue.
    """
    index = key.rfind(_LOCK_PREFIX)
    if index < 0:
        return ""
    parts = key[index + len(_LOCK_PREFIX) :].split("/")
    if not parts or not parts[0]:
        return ""
    if parts[0].startswith("@"):
        if len(parts) != 2 or len(parts[0]) < 2 or not parts[1]:
            return ""
        return f"{parts[0]}/{parts[1]}"
    if len(parts) != 1:
        return ""
    return parts[0]


def _take_specs(block: object, parts: dict[str, dict[str, object]], section: str) -> None:
    """Move each spec out of one section. A name listed in several sections keeps one spec per section."""
    if not isinstance(block, dict):
        return
    for name in list(block):
        spec = block[name]
        specs = parts.setdefault(str(name), {}).setdefault("specs", [])
        if isinstance(spec, str):
            specs.append((section, spec))
            del block[name]
            continue
        if not isinstance(spec, dict) or not spec.get("version"):
            continue
        # Lockfile v1 nests transitive copies under the parent; each becomes its own package entry.
        for key in ("dependencies", "optionalDependencies"):
            nested = spec.pop(key, None)
            _take_specs(nested, parts, f"{section}>{name}")
            if nested:
                spec[key] = nested
        specs.append((section, spec))
        del block[name]


def _json_split(text: str) -> tuple[dict[str, dict[str, object]], dict[str, object]] | None:
    """Specs and lock paths per package name, and the document left once they are taken out."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    parts: dict[str, dict[str, object]] = {}
    for section in _SECTIONS:
        _take_specs(doc.get(section), parts, section)
        block = doc.get(section)
        if isinstance(block, dict) and not block:
            doc.pop(section, None)
    packages = doc.get("packages")
    if isinstance(packages, dict):
        root = packages.get("")
        if isinstance(root, dict):
            for section in _SECTIONS:
                _take_specs(root.get(section), parts, "packages:" + section)
                block = root.get(section)
                if isinstance(block, dict) and not block:
                    root.pop(section, None)
        for key in list(packages):
            if not isinstance(key, str):
                continue
            name = _direct_lock_name(key)
            meta = packages.get(key)
            if not name or not isinstance(meta, dict):
                continue
            locks = parts.setdefault(name, {}).setdefault("locks", [])
            if isinstance(locks, list):
                locks.append((key, meta))
            del packages[key]
        if not packages:
            doc.pop("packages", None)
    return parts, doc


def _json_entries(text: str, *, lock: bool) -> Parsed | None:
    """A string spec is a declaration. In a lock it is an entry at the version the top copy installs, "" with none."""
    if not text.strip():
        return [], ""
    split = _json_split(text)
    if split is None:
        return None
    parts, doc = split
    entries: list[Entry] = []
    for name, blob in parts.items():
        locks = blob.get("locks") or ()
        top = next((_installed(name, meta) for path, meta in locks if path == _LOCK_PREFIX + name), "")
        for section, spec in blob.get("specs") or ():
            if isinstance(spec, dict):
                entries.append((name, _installed(name, spec), ">" not in section, _record(section, spec)))
            else:
                entries.append((name, top, True, _record(section, spec)) if lock else (name, spec, True, section))
        for path, meta in locks:
            entries.append((name, _installed(name, meta), path == _LOCK_PREFIX + name, _record(path, meta)))
    return entries, json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _registry_version(name: str, version: str, resolved: str) -> str:
    """`version` when `resolved` is the registry tarball for name@version, else the version with its source."""
    tarball = f"{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz"
    if version and resolved.split("#", 1)[0] in {registry + tarball for registry in _REGISTRIES}:
        return version
    return f"{version} ({resolved or 'no resolved source'})"


def _installed(name: str, record: dict) -> str:
    """The installed version of a lock record. An alias installs another package, so it is never the registry copy."""
    version, resolved, alias = str(record.get("version") or ""), record.get("resolved"), record.get("name", name)
    if not version or record.get("link") is True:
        return version
    if alias != name:
        return f"{version} (alias of {alias})"
    return _registry_version(name, version, resolved if isinstance(resolved, str) else "")


def _record(where: str, record: dict) -> str:
    return json.dumps([where, record], sort_keys=True, separators=(",", ":"))


def package_lock_integrity(text: str) -> str:
    """The `integrity` of a package_lock entry's text, or "" when its record has none."""
    record = json.loads(text)[1]
    integrity = record.get("integrity") if isinstance(record, dict) else None
    return integrity if isinstance(integrity, str) else ""


def package_json(text: str) -> Parsed | None:
    return _json_entries(text, lock=False)


def package_lock(text: str) -> Parsed | None:
    return _json_entries(text, lock=True)


def _yarn_names(header: str) -> list[str]:
    """Package names of a Yarn stanza header, one per distinct comma-separated `name@range` descriptor."""
    names: list[str] = []
    for part in header.rstrip().rstrip(":").split(","):
        match = _YARN_DESCRIPTOR_RE.match(part.strip().strip('"'))
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def yarn_lock(text: str) -> Parsed | None:
    """Yarn classic stanzas. A stanza with no quoted `version` line, such as a Yarn Berry lock, does not parse."""
    entries: list[Entry] = []
    residue: list[str] = []
    names: list[str] = []
    block: list[str] = []
    version = resolved = ""
    complete = True

    def flush() -> None:
        nonlocal names, block, version, resolved, complete
        if names:
            complete = complete and bool(version)
            body = "\n".join(block)
            entries.extend((name, _registry_version(name, version, resolved), True, body) for name in names)
        elif block:
            residue.append("\n".join(block) + "\n")
        names, block, version, resolved = [], [], "", ""

    for raw in text.splitlines():
        if raw and not raw.startswith((" ", "\t")):
            flush()
            names = _yarn_names(raw)
            block = [raw]
            continue
        block.append(raw)
        match = _YARN_VERSION_RE.match(raw)
        version = match.group(1) if match else version
        located = _YARN_RESOLVED_RE.match(raw)
        resolved = located.group(1) if located else resolved
    flush()
    return (entries, "".join(residue)) if complete else None


def yarn_lock_integrity(text: str) -> str:
    """The `integrity` of a yarn_lock entry's stanza, or "" when it has none or several."""
    found = {match.group(1) for line in text.splitlines() if (match := _YARN_INTEGRITY_RE.match(line))}
    return found.pop() if len(found) == 1 else ""
