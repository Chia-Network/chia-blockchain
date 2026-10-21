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
_YARN_VERSION_RE = re.compile(r'^\s+version\s+"([^"]+)"')
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
    prefix = "node_modules/"
    if not key.startswith(prefix) or "/node_modules/" in key[len(prefix) :]:
        return ""
    return key[len(prefix) :]


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


def _json_entry_version(parts: dict[str, object]) -> str:
    lock = parts.get("lock")
    if isinstance(lock, dict) and lock.get("version"):
        return str(lock["version"])
    spec = parts.get("spec")
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict) and spec.get("version"):
        return str(spec["version"])
    return ""


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
            parts.setdefault(name, {})["lock"] = meta
            del packages[key]
        if not packages:
            doc.pop("packages", None)
    entries = {
        name: (_json_entry_version(blob), json.dumps(blob, sort_keys=True, separators=(",", ":")))
        for name, blob in parts.items()
    }
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
        return all(
            _reached_listed_version(name, old_map[key][0], new_map[key][0], listed)
            and _payload_ok([old_map[key]], [new_map[key]])
            for key in old_map
        )
    if len(old_left) != 1 or len(new_left) != 1:
        return False
    return _reached_listed_version(name, old_left[0][0], new_left[0][0], listed) and _payload_ok(old_left, new_left)


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


def _without_version(payload: str) -> str:
    """Entry text with version labels removed."""

    def strip(node: object) -> object:
        if isinstance(node, dict):
            return {key: strip(value) for key, value in node.items() if key != "version"}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    try:
        return json.dumps(strip(json.loads(payload)), sort_keys=True, separators=(",", ":"))
    except json.JSONDecodeError:
        kept = [line for line in payload.splitlines() if not re.match(r"^\s*version\s", line)]
        return "\n".join(kept)


def _lock_doc(doc: object) -> bool:
    if not isinstance(doc, dict):
        return False
    if "lock" in doc:
        return True
    spec = doc.get("spec")
    return isinstance(spec, dict) and any(key in spec for key in ("integrity", "resolved"))


def _lock_text(payloads: list[str]) -> bool:
    """Yarn stanza text. A module or requirement line keeps its version in the entry label."""
    return any(re.search(r"(?m)^\s*(?:version|resolved|integrity)\s", payload) for payload in payloads)


def _payload_ok(old_blocks: list[tuple[str, str]], new_blocks: list[tuple[str, str]]) -> bool:
    """A lock entry may change only its version text. A manifest spec is not a lock payload."""
    payloads = [payload for _version, payload in (*old_blocks, *new_blocks)]
    parsed: list[object] = []
    for payload in payloads:
        try:
            parsed.append(json.loads(payload))
        except json.JSONDecodeError:
            return _version_bump(old_blocks, new_blocks) if _lock_text(payloads) else True
    if any(_lock_doc(doc) for doc in parsed):
        return _version_bump(old_blocks, new_blocks)
    return True


def _version_bump(old_blocks: list[tuple[str, str]], new_blocks: list[tuple[str, str]]) -> bool:
    """True when entries match, or one entry changes only its version text."""
    if old_blocks == new_blocks:
        return True
    if len(old_blocks) != 1 or len(new_blocks) != 1:
        return False
    old_version, old_payload = old_blocks[0]
    new_version, new_payload = new_blocks[0]
    return old_version != new_version and _without_version(old_payload) == _without_version(new_payload)


def _lock_covers_listed(kind: str, before: str, after: str, updates: list[dict], names: set[str]) -> bool:
    """True when a listed package moves to its listed version.

    A listed name must be explained. Every other name may change only its
    version text. A resolved URL, an integrity hash, leftover bytes, or a
    lock that never moves a listed package stays unresolved.
    """
    listed = _listed_versions(updates, kind=kind)
    if not any(_canonical_package_name(kind, name) in listed for name in names):
        return False
    old_split = _split_entries(kind, before)
    new_split = _split_entries(kind, after)
    if old_split is None or new_split is None:
        return False
    old_entries, old_residue = old_split
    new_entries, new_residue = new_split
    if old_residue != new_residue:
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

    A lock entry is explained only when the rest of that entry is unchanged.
    A same-version entry, an unlisted package, a replace line, a yarn key
    that appears or disappears, or any other residue is not.

    go.sum keeps one block per version. The listed bump matches when `to`
    is present and `from` was present before, including when `from` was removed.
    """
    old_split = _split_entries(kind, before)
    new_split = _split_entries(kind, after)
    if old_split is None or new_split is None:
        return False
    old_entries, old_residue = old_split
    new_entries, new_residue = new_split
    if old_residue != new_residue:
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
