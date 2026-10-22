"""Manifest and lockfile grammar for a Dependabot diff.

One parser reads each ecosystem. Those entries are the only source for the
changed-package labels and for whether the diff matches the listed update.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_GO_MOD_RE = re.compile(
    r"^\s*(?:require\s+)?([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)\s+(v\S+)",
    re.M,
)
_GO_SUM_RE = re.compile(r"^(\S+)\s+(v\S+)\s+", re.M)
_REQ_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:==|>=|<=|~=|!=|===)\s*([^\s#;]+)",
    re.M,
)
_YARN_HEADER_RE = re.compile(r'"?(@?[^@"\s]+)@[^:]*:')
_YARN_VERSION_RE = re.compile(r'^  version "([^"]+)"')
_VERSION_PREFIX_RE = re.compile(r"^(>=|<=|v|\^|~|=|>|<)")
_GO_BLOCK_STARTS = frozenset({"require(", "replace(", "exclude(", "retract("})
_OPAQUE_LOCKS = {
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Gemfile.lock",
    "composer.lock",
}
# PEP 503: lowercase, and collapse each run of `-`, `_`, or `.` to one `-`.
_PEP503_SEPARATORS = re.compile(r"[-_.]+")


def _direct_lock_name(key: str) -> str:
    """Package name for a lockfile path.

    Nested copies (`node_modules/a/node_modules/b`, and workspace paths such as
    `packages/gui/node_modules/b`) are the leaf package. A path that continues
    past the package name stays in residue.
    """
    marker = "node_modules/"
    index = key.rfind(marker)
    if index < 0:
        return ""
    parts = key[index + len(marker) :].split("/")
    if not parts or not parts[0]:
        return ""
    if parts[0].startswith("@"):
        if len(parts) != 2 or len(parts[0]) < 2 or not parts[1]:
            return ""
        return f"{parts[0]}/{parts[1]}"
    if len(parts) != 1:
        return ""
    return parts[0]


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


def _manifest_kind(path: str) -> str:
    name = Path(path).name
    lowered = path.replace("\\", "/")
    if name in {"package.json", "package-lock.json", "npm-shrinkwrap.json"}:
        return "json"
    if name == "go.mod":
        return "go.mod"
    if name == "go.sum":
        return "go.sum"
    if name == "yarn.lock":
        return "yarn"
    if name in _OPAQUE_LOCKS:
        return "opaque"
    if (name.startswith("requirements") or "/requirements/" in lowered) and name.endswith(".txt"):
        return "requirements"
    return ""


def _requirement_name(name: str) -> str:
    """PEP 503 name. Requirements parsing and Dependabot names both use this."""
    return _PEP503_SEPARATORS.sub("-", name).lower()


def _canonical_package_name(kind: str, name: str) -> str:
    if kind == "requirements":
        return _requirement_name(name)
    return name


def _names_listed(kind: str, names: set[str], listed: set[str]) -> bool:
    known = {_canonical_package_name(kind, name) for name in listed}
    return all(_canonical_package_name(kind, name) in known for name in names)


def _listed_versions(updates: list[dict], *, kind: str = "") -> dict[str, set[tuple[str, str]]]:
    found: dict[str, set[tuple[str, str]]] = {}
    for item in updates:
        name = _canonical_package_name(kind, str(item.get("packageName") or "").strip())
        if not name:
            continue
        pair = (str(item.get("fromVersion") or "").strip(), str(item.get("toVersion") or "").strip())
        found.setdefault(name, set()).add(pair)
    return found


def _version_body(value: str) -> str:
    match = _VERSION_PREFIX_RE.match(value)
    return value[match.end() :] if match else value


def _reached_listed_version(name: str, old: str, new: str, listed: dict[str, set[tuple[str, str]]]) -> bool:
    """True when this package moved from its listed version to its listed version.

    A leading v is optional. Any other prefix, such as an npm range, must be
    unchanged, and the version text after it must be the listed one.
    """
    if not old or not new or old == new:
        return False
    old_prefix = _VERSION_PREFIX_RE.match(old)
    new_prefix = _VERSION_PREFIX_RE.match(new)
    old_mark = old_prefix.group(1) if old_prefix else ""
    new_mark = new_prefix.group(1) if new_prefix else ""
    if old_mark != new_mark and (old_mark not in {"", "v"} or new_mark not in {"", "v"}):
        return False
    old_body, new_body = _version_body(old), _version_body(new)
    if not old_body or not new_body:
        return False
    return any(_version_body(frm) == old_body and _version_body(to) == new_body for frm, to in listed.get(name, ()))


def _take_specs(block: object, parts: dict[str, dict[str, object]]) -> None:
    if not isinstance(block, dict):
        return
    for name in list(block):
        spec = block[name]
        if isinstance(spec, str):
            parts.setdefault(str(name), {})["spec"] = spec
            del block[name]
            continue
        if not isinstance(spec, dict) or not spec.get("version"):
            continue
        nested = {
            key: spec.pop(key) for key in ("dependencies", "optionalDependencies") if isinstance(spec.get(key), dict)
        }
        parts.setdefault(str(name), {})["spec"] = spec
        if nested:
            block[name] = nested
        else:
            del block[name]


def _json_blocks(blob: dict[str, object], name: str) -> list[tuple[str, str]]:
    """One block per manifest spec and per lockfile path. Paths do not collapse."""
    blocks: list[tuple[str, str]] = []
    spec = blob.get("spec")
    if isinstance(spec, str):
        blocks.append((spec, json.dumps({"spec": spec}, separators=(",", ":"))))
    elif isinstance(spec, dict):
        # `name` is the dependencies key. Lockfile v1 has no packages path.
        blocks.append(
            (
                str(spec.get("version") or ""),
                json.dumps({"name": name, "spec": spec}, sort_keys=True, separators=(",", ":")),
            )
        )
    locks = blob.get("locks")
    if isinstance(locks, list):
        ordered = [item for item in locks if isinstance(item, tuple) and len(item) == 2]
        for path, meta in sorted(ordered, key=lambda item: item[0]):
            if not isinstance(path, str) or not isinstance(meta, dict):
                continue
            body = dict(meta)
            body["path"] = path
            blocks.append((str(meta.get("version") or ""), json.dumps(body, sort_keys=True, separators=(",", ":"))))
    return blocks


def _json_parts(text: str) -> tuple[dict[str, tuple[str, str]], str] | None:
    if not text.strip():
        return {}, ""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    parts: dict[str, dict[str, object]] = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        _take_specs(doc.get(section), parts)
        block = doc.get(section)
        if isinstance(block, dict) and not block:
            doc.pop(section, None)
    packages = doc.get("packages")
    if isinstance(packages, dict):
        root = packages.get("")
        if isinstance(root, dict):
            for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
                _take_specs(root.get(section), parts)
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
    entries: dict[str, tuple[str, str] | list[tuple[str, str]]] = {}
    for name, blob in parts.items():
        blocks = _json_blocks(blob, name)
        if len(blocks) == 1:
            entries[name] = blocks[0]
        elif blocks:
            entries[name] = blocks
    return entries, json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _go_mod_parts(text: str) -> tuple[dict[str, list[tuple[str, str]]], str]:
    entries: dict[str, list[tuple[str, str]]] = {}
    residue: list[str] = []
    for kind, line in _go_mod_lines(text):
        code = line.split("//", 1)[0]
        match = _GO_MOD_RE.match(code) if kind == "entry" else None
        if match:
            entries.setdefault(match.group(1), []).append((match.group(2), code.strip()))
            continue
        residue.append(line)
    return entries, "".join(residue)


def _go_sum_version(token: str) -> str:
    """Module version, without the `/go.mod` checksum suffix."""
    return token.split("/go.mod", 1)[0]


def _go_sum_parts(text: str) -> tuple[dict[str, list[tuple[str, str]]], str]:
    """One block per module version. Versions of a module stay a set."""
    grouped: dict[str, dict[str, list[str]]] = {}
    residue: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.strip()
        match = _GO_SUM_RE.match(body)
        if not body or not match:
            residue.append(line)
            continue
        module, version = match.group(1), _go_sum_version(match.group(2))
        grouped.setdefault(module, {}).setdefault(version, []).append(body)
    entries = {
        module: [(version, "\n".join(sorted(rows))) for version, rows in sorted(by_version.items())]
        for module, by_version in grouped.items()
    }
    return entries, "".join(residue)


def _req_parts(text: str) -> tuple[dict[str, list[tuple[str, str]]], str]:
    entries: dict[str, list[tuple[str, str]]] = {}
    residue: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _REQ_RE.match(line)
        if match:
            entries.setdefault(_requirement_name(match.group(1)), []).append((match.group(2), line.strip()))
            continue
        residue.append(line)
    return entries, "".join(residue)


def _yarn_parts(text: str) -> tuple[dict[str, list[tuple[str, str]]], str]:
    entries: dict[str, list[tuple[str, str]]] = {}
    residue: list[str] = []
    names: list[str] = []
    block: list[str] = []
    version = ""

    def flush() -> None:
        nonlocal names, block, version
        if names:
            item = (version, "\n".join(block))
            for name in names:
                entries.setdefault(name, []).append(item)
        elif block:
            residue.append("\n".join(block) + "\n")
        names, block, version = [], [], ""

    for raw in text.splitlines():
        if raw and not raw.startswith((" ", "\t")):
            flush()
            names = _YARN_HEADER_RE.findall(raw)
            block = [raw]
            version = ""
            continue
        block.append(raw)
        match = _YARN_VERSION_RE.match(raw)
        if match:
            version = match.group(1)
    flush()
    return entries, "".join(residue)


def _split_entries(kind: str, text: str) -> tuple[dict[str, tuple[str, str]], str] | None:
    if kind == "json":
        return _json_parts(text)
    if kind == "go.mod":
        return _go_mod_parts(text)
    if kind == "go.sum":
        return _go_sum_parts(text)
    if kind == "requirements":
        return _req_parts(text)
    if kind == "yarn":
        return _yarn_parts(text)
    return None


def _entry_blocks(entry: object) -> list[tuple[str, str]]:
    if isinstance(entry, tuple):
        return [entry]
    if isinstance(entry, list):
        return [item for item in entry if isinstance(item, tuple)]
    return []


def _stanza_entries(blocks: list[tuple[str, str]]) -> dict[str, tuple[str, str]] | None:
    found: dict[str, tuple[str, str]] = {}
    for version, payload in blocks:
        key = payload.split("\n", 1)[0]
        if not key or key in found:
            return None
        found[key] = (version, payload)
    return found


def _version_map(blocks: list[tuple[str, str]]) -> dict[str, str] | None:
    found: dict[str, str] = {}
    for version, payload in blocks:
        if version in found:
            return None
        found[version] = payload
    return found


def _version_named(versions: dict[str, str], listed: str) -> str | None:
    body = _version_body(listed)
    if not body:
        return None
    found = [version for version in versions if _version_body(version) == body]
    if len(found) != 1:
        return None
    return found[0]


def _sum_update_covers(old: dict[str, str], new: dict[str, str], frm: str, to: str) -> bool:
    """True when `to` is in the new set and `from` was in the old set.

    Removing `from` matches. Keeping those lines and adding `to` matches.
    A checksum rewrite of any version that stays does not.
    """
    to_key = _version_named(new, to)
    from_key = _version_named(old, frm)
    if to_key is None or from_key is None or _version_body(from_key) == _version_body(to_key):
        return False
    removed = set(old) - set(new)
    added = set(new) - set(old)
    if removed - {from_key} or added - {to_key}:
        return False
    stayed = set(old) & set(new)
    if any(old[key] != new[key] for key in stayed):
        return False
    return bool(removed or added)


def _go_sum_explained(
    name: str,
    old_blocks: list[tuple[str, str]],
    new_blocks: list[tuple[str, str]],
    listed: dict[str, set[tuple[str, str]]],
) -> bool:
    old = _version_map(old_blocks)
    new = _version_map(new_blocks)
    if old is None or new is None:
        return False
    if old == new:
        return True
    return any(_sum_update_covers(old, new, frm, to) for frm, to in listed.get(name, ()))


def _blocks_explain(
    name: str,
    old_blocks: list[tuple[str, str]],
    new_blocks: list[tuple[str, str]],
    listed: dict[str, set[tuple[str, str]]],
    *,
    keyed: bool,
) -> bool:
    old_left = list(old_blocks)
    new_left = list(new_blocks)
    for block in list(old_left):
        if block in new_left:
            old_left.remove(block)
            new_left.remove(block)
    if not old_left and not new_left:
        return True
    if keyed:
        old_map = _stanza_entries(old_left)
        new_map = _stanza_entries(new_left)
        if old_map is None or new_map is None or set(old_map) != set(new_map):
            return False
        return all(_pair_explained(name, old_map[key], new_map[key], listed) for key in old_map)
    pairs = _pair_blocks(old_left, new_left)
    if pairs is None:
        return False
    return all(_pair_explained(name, old, new, listed) for old, new in pairs)


def _name_explained(
    kind: str,
    name: str,
    old_blocks: list[tuple[str, str]],
    new_blocks: list[tuple[str, str]],
    listed: dict[str, set[tuple[str, str]]],
) -> bool:
    if kind == "go.sum":
        return _go_sum_explained(name, old_blocks, new_blocks, listed)
    return _blocks_explain(name, old_blocks, new_blocks, listed, keyed=kind == "yarn")


def _single_version(entry: object) -> str | None:
    """The version when a name has one entry. Several entries are not one label."""
    blocks = _entry_blocks(entry)
    if len(blocks) > 1:
        return None
    if not blocks:
        return ""
    return blocks[0][0]


_SEMVER = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?"
_TARBALL_RE = re.compile(
    r"^https://registry\.(?:npmjs\.org|yarnpkg\.com)/"
    r"(?:(?P<scope>@[^/]+)/)?(?P<name>[^/]+)/-/(?P<base>[^/]+)-(?P<version>" + _SEMVER + r")\.tgz$"
)
_FOLD_SPEC_RE = re.compile(rf"^(?:\^|=)?({_SEMVER})$")
_LOCATOR_KEYS = frozenset({"version", "resolved", "integrity", "checksum"})
_SPEC_SECTIONS = frozenset({"dependencies", "devDependencies", "optionalDependencies", "peerDependencies"})


def _canonical_tarball(url: str, version: str, package: str) -> bool:
    """True when `url` is the npm or Yarn registry tarball for this package version."""
    if not url or not version or not package:
        return False
    match = _TARBALL_RE.fullmatch(url.split("#", 1)[0])
    if not match or match.group("version") != version or match.group("base") != match.group("name"):
        return False
    scope = match.group("scope")
    found = f"{scope}/{match.group('name')}" if scope else match.group("name")
    return found == package


def _fold_spec(value: str) -> str:
    """Bare `X`, `^X`, and `=X` are the same residue spelling. `~`, `v`, and `V` are not."""
    match = _FOLD_SPEC_RE.fullmatch(value)
    return match.group(1) if match else value


def _fold_residue(node: object) -> object:
    """Fold bare, `^`, and `=` spellings in residue maps. Nested lock records stay as written."""
    if isinstance(node, list):
        return [_fold_residue(item) for item in node]
    if not isinstance(node, dict):
        return node
    folded: dict[str, object] = {}
    for key, value in node.items():
        if key in _SPEC_SECTIONS and isinstance(value, dict):
            section: dict[str, object] = {}
            for dep, spec in value.items():
                section[str(dep)] = _fold_spec(spec) if isinstance(spec, str) else _fold_residue(spec)
            folded[key] = section
            continue
        folded[key] = _fold_residue(value)
    return folded


def _lock_record(doc: object) -> tuple[str, dict[str, object]] | None:
    if not isinstance(doc, dict):
        return None
    spec = doc.get("spec")
    if isinstance(spec, str):
        return None
    if isinstance(spec, dict):
        name = doc.get("name") if isinstance(doc.get("name"), str) else ""
        return name, spec
    path = doc.get("path") if isinstance(doc.get("path"), str) else ""
    name = _direct_lock_name(path) if path else ""
    if not name and isinstance(doc.get("name"), str):
        name = str(doc["name"])
    if path or any(key in doc for key in _LOCATOR_KEYS):
        return name, doc
    return None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _both_resolved_canonical(old_name: str, old: dict[str, object], new_name: str, new: dict[str, object]) -> bool:
    """Both install locators are the registry tarball for that side's name and version."""
    old_resolved, new_resolved = _text(old.get("resolved")), _text(new.get("resolved"))
    if not old_resolved or not new_resolved:
        return False
    return _canonical_tarball(old_resolved, _text(old.get("version")), old_name) and _canonical_tarball(
        new_resolved, _text(new.get("version")), new_name
    )


def _without_locators(record: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key not in _LOCATOR_KEYS}


def _plain_yarn_line(line: str) -> tuple[str, str] | None:
    for key in ("version", "resolved"):
        prefix = f'  {key} "'
        body = line[len(prefix) : -1]
        if line.startswith(prefix) and line.endswith('"') and '"' not in body:
            return key, body
    for key in ("integrity", "checksum"):
        prefix = f"  {key} "
        body = line[len(prefix) :]
        if line.startswith(prefix) and body and " " not in body and "," not in body:
            return key, body
    return None


def _yarn_keys(line: str) -> set[str]:
    """Key tokens of a body line. A comma joins keys; a colon follows a section key."""
    keys: set[str] = set()
    for part in line.strip().split(","):
        stripped = part.strip()
        if not stripped:
            continue
        head = re.split(r"[\s:]", stripped, maxsplit=1)[0].strip(' :"')
        if head:
            keys.add(head)
    return keys


def _yarn_rest(payload: str) -> str | None:
    """Header and dependency sub-blocks left; plain locator lines dropped.

    A stanza-body line keyed on version, resolved, integrity or checksum must be
    in the plain allowlisted form, or the stanza is not canonical. A line
    indented past the stanza body is a dependency entry and stays, even when a
    package is named like a locator.
    """
    lines = payload.splitlines()
    names = _YARN_HEADER_RE.findall(lines[0]) if lines else []
    if len(names) != 1:
        return None
    version = resolved = ""
    kept = [lines[0]]
    for line in lines[1:]:
        if not line:
            kept.append(line)
            continue
        if line.startswith("   "):
            kept.append(line)
            continue
        if not (_yarn_keys(line) & _LOCATOR_KEYS):
            kept.append(line)
            continue
        field = _plain_yarn_line(line)
        if field is None or (field[0] == "version" and version) or (field[0] == "resolved" and resolved):
            return None
        if field[0] == "version":
            version = field[1]
        elif field[0] == "resolved":
            resolved = field[1]
    return "\n".join(kept) if _canonical_tarball(resolved, version, names[0]) else None


def _payloads_match(old: str, new: str) -> bool:
    """Drop version and registry locators only when `resolved` is canonical on both sides.

    Every other entry is compared as written, version included. `resolution` does not make an entry canonical.
    """
    if old == new:
        return True
    try:
        old_doc = json.loads(old)
        new_doc = json.loads(new)
    except json.JSONDecodeError:
        old_rest, new_rest = _yarn_rest(old), _yarn_rest(new)
        return old_rest is not None and old_rest == new_rest
    old_record, new_record = _lock_record(old_doc), _lock_record(new_doc)
    if old_record is None or new_record is None:
        return False
    old_name, old_body = old_record
    new_name, new_body = new_record
    if not _both_resolved_canonical(old_name, old_body, new_name, new_body):
        return False
    return _without_locators(old_body) == _without_locators(new_body)


def _payload_id(payload: str) -> str:
    try:
        doc = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if not isinstance(doc, dict):
        return ""
    path = doc.get("path")
    if isinstance(path, str) and path:
        return "path:" + path
    if "spec" in doc:
        return "spec"
    return ""


def _pair_blocks(
    old: list[tuple[str, str]], new: list[tuple[str, str]]
) -> list[tuple[tuple[str, str], tuple[str, str]]] | None:
    """Pair lock paths. One unkeyed block pairs with one. Added or ambiguous paths do not."""
    if len(old) == 1 and len(new) == 1 and not _payload_id(old[0][1]) and not _payload_id(new[0][1]):
        return [(old[0], new[0])]
    old_ids = [_payload_id(block[1]) for block in old]
    new_ids = [_payload_id(block[1]) for block in new]
    if not all(old_ids) or not all(new_ids):
        return None
    if len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids) or set(old_ids) != set(new_ids):
        return None
    new_by_id = dict(zip(new_ids, new))
    return [(block, new_by_id[key]) for key, block in zip(old_ids, old)]


def _residues_match(kind: str, old: str, new: str) -> bool:
    if old == new:
        return True
    if kind != "json":
        return False
    try:
        old_doc = json.loads(old)
        new_doc = json.loads(new)
    except json.JSONDecodeError:
        return False
    return _fold_residue(old_doc) == _fold_residue(new_doc)


def _payload_kind(payload: str) -> str:
    """'spec' for a manifest string spec, 'json' for a lock record, 'text' otherwise."""
    try:
        doc = json.loads(payload)
    except json.JSONDecodeError:
        return "text"
    if isinstance(doc, dict) and set(doc) == {"spec"} and isinstance(doc.get("spec"), str):
        return "spec"
    return "json"


def _lock_text(payloads: list[str]) -> bool:
    """Yarn stanza text. A module or requirement line keeps its version in the entry label."""
    return any(
        re.search(r"(?m)^\s*(?:version|resolved|integrity|checksum|resolution)\b", payload) for payload in payloads
    )


def _payload_ok(old_blocks: list[tuple[str, str]], new_blocks: list[tuple[str, str]]) -> bool:
    """True when a string spec or version line moved, or lock locators are canonical."""
    payloads = [payload for _version, payload in (*old_blocks, *new_blocks)]
    kinds = {_payload_kind(payload) for payload in payloads}
    if kinds <= {"spec"}:
        return True
    if "text" in kinds:
        return _version_bump(old_blocks, new_blocks) if _lock_text(payloads) else True
    return _version_bump(old_blocks, new_blocks)


def _version_bump(old_blocks: list[tuple[str, str]], new_blocks: list[tuple[str, str]]) -> bool:
    """True when each paired entry matches, or both resolved URLs are the registry tarball."""
    if old_blocks == new_blocks:
        return True
    pairs = _pair_blocks(old_blocks, new_blocks)
    if pairs is None:
        return False
    for old, new in pairs:
        if old == new:
            continue
        if old[0] == new[0] or not _payloads_match(old[1], new[1]):
            return False
    return True


def _pair_explained(
    name: str,
    old: tuple[str, str],
    new: tuple[str, str],
    listed: dict[str, set[tuple[str, str]]],
) -> bool:
    return _reached_listed_version(name, old[0], new[0], listed) and _payload_ok([old], [new])


def _lock_covers_listed(kind: str, before: str, after: str, updates: list[dict], names: set[str]) -> bool:
    """True when a listed package moves to its listed version.

    A listed name must be explained. Every other name may change only its
    version and registry locators. Another resolved host, a same-version
    hash swap, leftover bytes, or a lock that never moves a listed package
    stays unresolved.
    """
    listed = _listed_versions(updates, kind=kind)
    old_split = _split_entries(kind, before)
    new_split = _split_entries(kind, after)
    if old_split is None or new_split is None:
        return False
    old_entries, old_residue = old_split
    new_entries, new_residue = new_split
    listed_moved = any(
        _canonical_package_name(kind, name) in listed
        and _entry_blocks(old_entries.get(name)) != _entry_blocks(new_entries.get(name))
        for name in set(old_entries) | set(new_entries)
    )
    named = any(_canonical_package_name(kind, name) in listed for name in names)
    if not listed_moved and not named:
        return False
    if not _residues_match(kind, old_residue, new_residue):
        return False
    for name in set(old_entries) | set(new_entries):
        old_blocks = _entry_blocks(old_entries.get(name))
        new_blocks = _entry_blocks(new_entries.get(name))
        if _canonical_package_name(kind, name) in listed:
            if not _name_explained(kind, name, old_blocks, new_blocks, listed):
                return False
            continue
        if not _version_bump(old_blocks, new_blocks):
            return False
    return True


def _changed_names(kind: str, before: str, after: str) -> set[str] | None:
    """Names whose one parsed version changed.

    Versions come from the same entries `_entries_explain` reads.
    A name with more than one entry is reported by `_multi_entry_names`.
    """
    old_split = _split_entries(kind, before)
    new_split = _split_entries(kind, after)
    if old_split is None or new_split is None:
        return None
    old_entries = old_split[0]
    new_entries = new_split[0]
    changed: set[str] = set()
    for name in set(old_entries) | set(new_entries):
        old_version = _single_version(old_entries.get(name))
        new_version = _single_version(new_entries.get(name))
        if old_version is None or new_version is None or old_version == new_version:
            continue
        changed.add(name)
    return changed


def _multi_entry_names(kind: str, before: str, after: str, updates: list[dict]) -> set[str]:
    """Multi-entry names whose own blocks are not the listed change.

    Several Yarn descriptors for one package are normal. They are a gap
    only when those blocks are unexplained. An unchanged set is not.
    """
    old_split = _split_entries(kind, before)
    new_split = _split_entries(kind, after)
    if old_split is None or new_split is None:
        return set()
    old_entries = old_split[0]
    new_entries = new_split[0]
    listed = _listed_versions(updates, kind=kind)
    found: set[str] = set()
    for name in set(old_entries) | set(new_entries):
        old_blocks = _entry_blocks(old_entries.get(name))
        new_blocks = _entry_blocks(new_entries.get(name))
        if len(old_blocks) <= 1 and len(new_blocks) <= 1:
            continue
        if _name_explained(kind, name, old_blocks, new_blocks, listed):
            continue
        found.add(name)
    return found


def _entries_explain(kind: str, before: str, after: str, updates: list[dict]) -> bool:
    """True when every changed entry moved to its listed version.

    A lock entry is explained when it moves to the listed version and the
    rest is unchanged aside from registry locators. A same-version entry,
    an unlisted package, a replace line, a yarn key that appears or
    disappears, or any other residue is not.

    go.sum keeps one block per version. The listed bump matches when `to`
    is present and `from` was present before, including when `from` was removed.
    """
    old_split = _split_entries(kind, before)
    new_split = _split_entries(kind, after)
    if old_split is None or new_split is None:
        return False
    old_entries, old_residue = old_split
    new_entries, new_residue = new_split
    if not _residues_match(kind, old_residue, new_residue):
        return False
    listed = _listed_versions(updates, kind=kind)
    names = set(old_entries) | set(new_entries)
    return all(
        _name_explained(
            kind,
            name,
            _entry_blocks(old_entries.get(name)),
            _entry_blocks(new_entries.get(name)),
            listed,
        )
        for name in names
    )
