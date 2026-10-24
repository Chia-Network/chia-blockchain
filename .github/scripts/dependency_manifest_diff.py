"""The dependency changes of a pull request, read from its manifests and lockfiles.

The diff is the update list. plan() reads each changed path on its own into a
_File of one kind, then resolves each file by the rule for its kind. Every
version move ends up in one of:

- primary: a declared dependency whose version moved. A lock beside a
  manifest records the installed versions, so a manifest with a parsed lock
  beside it only says which names are declared, and the lock supplies the
  versions; a name the manifest moved must also move in that lock. A primary
  is scanned, or reported by its ecosystem's policy.
- unchecked: every other package whose version moved, such as an undeclared
  or nested lock copy, a go.mod `// indirect` require, or a go.sum version
  that no version move beside it accounts for. Disclosed, not scanned.
- gaps: (path, reason) for a path that is not a dependency file, was deleted
  or changed type, does not parse, or changed in a way its versions do not
  account for: residue outside the entries, an entry whose text changed at an
  unchanged version, or a line entry whose text outside the version changed.
- unparsed_locks: a lockfile with no grammar beside a primary change. With no
  primary change beside it, it is a gap.

A name with several entries compares as a set of versions. old and new are the
versions removed and added, joined with ", ", so a name that moved more than
one copy is never an exact version.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import NamedTuple

import dependency_cursor_review_ecosystems as ecosystems
from dependency_cursor_review_ecosystems import CHECKSUMS, LOCK, MANIFEST, Ecosystem
from dependency_manifest_lines import Entry

# (revision, path) -> the file's text, "" when it is absent.
Read = Callable[[str, str], str]


class Change(NamedTuple):
    ecosystem: str
    dir: str
    name: str
    old: str
    new: str


class Plan(NamedTuple):
    primary: tuple[Change, ...] = ()
    unchecked: tuple[Change, ...] = ()
    gaps: tuple[tuple[str, str], ...] = ()
    unparsed_locks: tuple[str, ...] = ()


# Each (change, whether it is the top copy) one file moved.
Moves = list[tuple[Change, bool]]


# What one changed file contributes. VERSIONS: its moves are changes. NAMES: a
# manifest beside a lock, whose moved names must move in that lock. CHECKSUMS:
# every version it adds or drops must be one a change beside it adds or drops.
# OPAQUE: a lock with no grammar. GAP: the file is a gap on its own.
_VERSIONS, _NAMES, _CHECKSUMS, _OPAQUE, _GAP = "versions", "names", "checksums", "opaque", "gap"


class _File(NamedTuple):
    path: str
    group: tuple[str, str]  # (ecosystem, directory)
    kind: str
    reason: str = "unresolved"  # why a GAP file is a gap
    moves: tuple[tuple[Change, bool], ...] = ()  # (change, whether it is primary)


def _moves(row: ecosystems.FileKind, directory: str, before: list[Entry], after: list[Entry]) -> Moves | None:
    """Each (name, top) whose set of versions differs, with whether it is the top copy.

    None when an entry changed in a way its versions do not account for.
    """
    sides: dict[tuple[str, bool], tuple[dict[str, set[str]], dict[str, set[str]]]] = {}
    for side, entries in enumerate((before, after)):
        for name, version, top, text in entries:
            sides.setdefault((name, top), ({}, {}))[side].setdefault(version, set()).add(text)
    moved: Moves = []
    for (name, top), (old, new) in sorted(sides.items()):
        if any(old[version] != new[version] for version in old.keys() & new.keys()):
            return None
        if not row.records and old and new and set().union(*old.values()) != set().union(*new.values()):
            return None
        if old.keys() != new.keys():
            removed, added = ", ".join(sorted(old.keys() - new.keys())), ", ".join(sorted(new.keys() - old.keys()))
            moved.append((Change(row.ecosystem.name, directory, name, removed, added), top))
    return moved


def _file_moves(row: ecosystems.FileKind, old_path: str, path: str, read: Read, base: str) -> Moves | None:
    """The moves of one changed file with a grammar, or None when a side does not parse or its residue changed."""
    before, after = row.parse(read(base, old_path)), row.parse(read("HEAD", path))
    if before is None or after is None or before[1] != after[1]:
        return None
    return _moves(row, str(PurePosixPath(path).parent), before[0], after[0])


def _declared(ecosystem: Ecosystem, directory: str, read: Read, base: str) -> set[str] | None:
    """Names the manifests beside a lock declare at base or HEAD, or None when none is there or one does not parse."""
    names: set[str] = set()
    found = False
    for path, row in ecosystems.beside(ecosystem, MANIFEST, directory):
        for revision in (base, "HEAD"):
            text = read(revision, path)
            if not text:
                continue
            parsed = row.parse(text)
            if parsed is None:
                return None
            found = True
            names |= {name for name, _version, top, _text in parsed[0] if top}
    return names if found else None


def _has_lock(ecosystem: Ecosystem, directory: str, read: Read) -> bool:
    return any(read("HEAD", path) for path, _row in ecosystems.beside(ecosystem, LOCK, directory))


def _read(old_path: str, path: str, status: str, read: Read, base: str) -> list[_File]:
    """One changed path as _Files. A rename that is a gap is a gap under both of its paths."""
    row = ecosystems.file_kind(path)
    directory = str(PurePosixPath(path).parent)
    if status in {"D", "T"} or row is None:
        return [_File(label, ("", directory), _GAP) for label in dict.fromkeys((old_path, path))]
    group = (row.ecosystem.name, directory)
    if row.parse is None:
        return [_File(path, group, _GAP, "unparsed_manifest") if row.role == MANIFEST else _File(path, group, _OPAQUE)]
    moves = _file_moves(row, old_path, path, read, base)
    declared = _declared(row.ecosystem, directory, read, base) if row.role == LOCK else None
    if moves is None or (row.role == LOCK and declared is None):
        return [_File(path, group, _GAP)]
    if row.role == CHECKSUMS:
        kind = _CHECKSUMS
    elif row.role == MANIFEST and _has_lock(row.ecosystem, directory, read):
        kind = _NAMES
    else:
        kind = _VERSIONS
    primary = tuple((change, top and (declared is None or change.name in declared)) for change, top in moves)
    return [_File(path, group, kind, moves=primary)]


def _versions(joined: str) -> set[str]:
    """The versions in a Change's old or new. A checksum version names what it hashes after a `/`."""
    return {version.split("/", 1)[0] for version in joined.split(", ") if version}


def _accounts_for(change: Change, checksum: Change) -> bool:
    return (
        change.name == checksum.name
        and _versions(checksum.old) <= _versions(change.old)
        and _versions(checksum.new) <= _versions(change.new)
    )


def _resolve(file: _File, changes: list[tuple[Change, bool]]) -> Plan:
    """What one file adds to the Plan, given every (change, primary) the VERSIONS files of the diff moved."""
    beside = [(change, primary) for change, primary in changes if (change.ecosystem, change.dir) == file.group]
    if file.kind == _VERSIONS:
        return Plan(
            primary=tuple(change for change, primary in file.moves if primary),
            unchecked=tuple(change for change, primary in file.moves if not primary),
        )
    if file.kind == _NAMES:
        locked = {change.name for change, primary in beside if primary}
        if all(change.name in locked for change, _top in file.moves):
            return Plan()
        return Plan(gaps=((file.path, file.reason),))
    if file.kind == _CHECKSUMS:
        return Plan(
            unchecked=tuple(
                checksum
                for checksum, _top in file.moves
                if not any(_accounts_for(change, checksum) for change, _primary in beside)
            )
        )
    if file.kind == _OPAQUE and any(primary for _change, primary in beside):
        return Plan(unparsed_locks=(file.path,))
    return Plan(gaps=((file.path, file.reason),))


def plan(changed: list[tuple[str, str, str]], read: Read, base: str) -> Plan:
    """Sort (before path, after path, status letter) for each changed path into a Plan."""
    files = [file for old_path, path, status in changed for file in _read(old_path, path, status, read, base)]
    changes = [move for file in files if file.kind == _VERSIONS for move in file.moves]
    parts = [_resolve(file, changes) for file in files]
    return Plan(*(tuple(dict.fromkeys(item for items in column for item in items)) for column in zip(*parts)))
