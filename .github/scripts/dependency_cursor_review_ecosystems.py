"""The one table of dependency files and the scan policy of each ecosystem.

A FileKind row names a file by its name or path shape, its ecosystem, its
role and the grammar that reads it (None when no grammar does). An Ecosystem
row carries the policy. A change in a `warn` ecosystem, or a change one of its
`ref_rules` matches, is never scanned and never benign: decide() reports it
inconclusive with a named warning and does not block on it. A change one of
its `unresolved_rules` matches is scanned, and reported that way only when the
scan reports that its refs do not resolve in the cloned repository. A scanned
change is benign only when its row's `bind` ties the scanned commit to the
installed artifact, and its repository is verified
(dependency_cursor_review_upstream.VERIFIED).

Roles: a manifest declares dependencies; a lock records the installed copies
of the dependencies the manifest beside it declares; checksums hash the
versions the manifest beside them names, so every version a checksum file adds
or drops must be one the manifest beside it adds or drops.

Each grammar returns (name, version, top, text) entries. An entry's text may
change only with its version. In a line grammar the text is the line with the
version masked, so it may not change at all; in a record grammar (a lock copy,
a provider block) it is the whole record, which changes with the version.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import NamedTuple

import dependency_cursor_review_binding as binding
import dependency_cursor_review_upstream as upstream
from dependency_cursor_review_versions import commit_ref, exact_body, moving_ref
from dependency_manifest_go import go_mod, go_sum, go_sum_hash
from dependency_manifest_lines import Entry, Parsed, dockerfile_from, terraform_config, terraform_lock, workflow_uses
from dependency_manifest_npm import package_json, package_lock, package_lock_integrity, yarn_lock, yarn_lock_integrity
from dependency_manifest_python import (
    pipfile_lock,
    pipfile_lock_hashes,
    poetry_lock,
    poetry_lock_hashes,
    requirements,
)

# Why a change is not scanned. Docker images and Terraform providers have no
# source tree to read; a moving tag can resolve to another commit after the review;
# a bump from one commit to another whose commits no branch or tag of the action's repository contains.
UNSCANNABLE_ECOSYSTEM = "unscannable_ecosystem"
MOVING_REF = "moving_ref"
UNRESOLVED_SHA = "unresolved_sha"
WARN_REASONS = frozenset({UNSCANNABLE_ECOSYSTEM, MOVING_REF, UNRESOLVED_SHA})

MANIFEST, LOCK, CHECKSUMS = "manifest", "lock", "checksums"
# The scan's not_scanned_reason for a ref the cloned repository does not resolve (upstream_malware_scan.sh).
_REFS_UNRESOLVED = frozenset({"from_ref_unresolved", "to_ref_unresolved"})


# The allowlist: (ecosystem, package name) -> the GitHub owner/repo it is built from, for a package whose
# repository is named only by publisher metadata. An entry replaces that lookup and makes the repository verified,
# so a scan of it can be benign once it is also bound to the installed artifact. Add one only after checking by
# hand that the package is published from that repository, e.g. ("go", "golang.org/x/net"): "golang/net".
KNOWN_REPOS: dict[tuple[str, str], str] = {}
# Prefix entries: (ecosystem, name prefix) -> GitHub owner. The first path segment after the prefix is the repository,
# so golang.org/x/net and golang.org/x/tools/gopls map to golang/net and golang/tools.
KNOWN_REPO_PREFIXES: dict[tuple[str, str], str] = {("go", "golang.org/x/"): "golang"}
_REPO_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")


def known_repo(ecosystem: str, name: str) -> str:
    """The allowlisted owner/repo for a package, or "" when no exact or prefix entry names it."""
    exact = KNOWN_REPOS.get((ecosystem, name))
    if exact:
        return exact
    for (eco, prefix), owner in KNOWN_REPO_PREFIXES.items():
        if eco != ecosystem or not name.startswith(prefix):
            continue
        segment = name[len(prefix) :].split("/", 1)[0]
        if _is_repo_name(segment):
            return f"{owner}/{segment}"
    return ""


def _is_repo_name(segment: str) -> bool:
    """A single GitHub repository name: allowed characters only, and not made of dots alone ("." or "..")."""
    return _REPO_SEGMENT.fullmatch(segment) is not None and segment.strip(".") != ""


def _no_repo(_name: str, _version: str) -> upstream.Repo:
    return upstream.Repo()


# (warn reason, applies to (old, new)).
_RefRule = tuple[str, Callable[[str, str], bool]]
_ACTION_REFS: tuple[_RefRule, ...] = (
    (MOVING_REF, lambda old, new: any(ref and moving_ref(ref) for ref in (old, new))),
)
_ACTION_COMMITS: tuple[_RefRule, ...] = ((UNRESOLVED_SHA, lambda old, new: commit_ref(old) and commit_ref(new)),)


class Ecosystem(NamedTuple):
    name: str
    warn: str = ""  # the warn reason for every change, "" when changes are scanned
    ref_rules: tuple[_RefRule, ...] = ()  # the first rule that applies names the warn reason
    repo: Callable[[str, str], upstream.Repo] = _no_repo  # GitHub repository of (name, exact version)
    unresolved_rules: tuple[_RefRule, ...] = ()  # the warn reason when the scan cannot resolve the refs
    bind: Callable[[binding.Subject], binding.Binding] = binding.unsupported


class FileKind(NamedTuple):
    ecosystem: Ecosystem
    role: str
    parse: Callable[[str], Parsed | None] | None
    names: frozenset[str] = frozenset()  # exact file names
    match: Callable[[PurePosixPath], bool] | None = None  # any other path shape
    records: bool = False  # entries are whole records, not lines
    # The artifact hash an installed copy's entry records, "" for none; None for an entry that is no installed copy.
    hashes: Callable[[Entry], str | None] | None = None


NPM = Ecosystem("npm", repo=upstream.npm, bind=binding.npm)
PIP = Ecosystem("pip", repo=upstream.pypi, bind=binding.pypi)
GO = Ecosystem("go", repo=upstream.go, bind=binding.go)
ACTIONS = Ecosystem(
    "github-actions",
    ref_rules=_ACTION_REFS,
    repo=upstream.action,
    unresolved_rules=_ACTION_COMMITS,
    bind=binding.intrinsic,
)
DOCKER = Ecosystem("docker", warn=UNSCANNABLE_ECOSYSTEM)
TERRAFORM = Ecosystem("terraform", warn=UNSCANNABLE_ECOSYSTEM)
# Ecosystems with no grammar: a manifest change is a gap, and so is a lock change without a primary change beside it.
CARGO, BUNDLER, COMPOSER, SWIFT, NUGET = (
    Ecosystem(name) for name in ("cargo", "bundler", "composer", "swift", "nuget")
)


def _top_copy(read: Callable[[str], str]) -> Callable[[Entry], str | None]:
    """A lock installs the top entry for a name; a nested entry is the copy another dependency installs."""
    return lambda entry: read(entry[3]) if entry[2] else None


def _requirements(path: PurePosixPath) -> bool:
    return path.suffix == ".txt" and (path.name.startswith("requirements") or "requirements" in path.parts[:-1])


def _workflow(path: PurePosixPath) -> bool:
    in_workflows = "/.github/workflows/" in f"/{path}"
    return path.suffix in {".yml", ".yaml"} and (in_workflows or path.stem == "action")


def _dockerfile(path: PurePosixPath) -> bool:
    return path.name == "Dockerfile" or path.name.startswith("Dockerfile.")


def _dotnet_project(path: PurePosixPath) -> bool:
    return path.suffix in {".csproj", ".fsproj", ".vbproj"}


def _terraform(path: PurePosixPath) -> bool:
    return path.suffix == ".tf"


_FILES = (
    FileKind(NPM, MANIFEST, package_json, frozenset({"package.json"})),
    FileKind(
        NPM,
        LOCK,
        package_lock,
        frozenset({"package-lock.json", "npm-shrinkwrap.json"}),
        records=True,
        hashes=_top_copy(package_lock_integrity),
    ),
    FileKind(NPM, LOCK, yarn_lock, frozenset({"yarn.lock"}), records=True, hashes=_top_copy(yarn_lock_integrity)),
    FileKind(NPM, LOCK, None, frozenset({"pnpm-lock.yaml"})),
    FileKind(GO, MANIFEST, go_mod, frozenset({"go.mod"})),
    FileKind(GO, CHECKSUMS, go_sum, frozenset({"go.sum"}), records=True, hashes=go_sum_hash),
    FileKind(
        PIP, MANIFEST, requirements, frozenset({"pyproject.toml", "setup.py", "setup.cfg", "Pipfile"}), _requirements
    ),
    FileKind(PIP, LOCK, poetry_lock, frozenset({"poetry.lock"}), records=True, hashes=_top_copy(poetry_lock_hashes)),
    FileKind(PIP, LOCK, pipfile_lock, frozenset({"Pipfile.lock"}), records=True, hashes=_top_copy(pipfile_lock_hashes)),
    FileKind(ACTIONS, MANIFEST, workflow_uses, match=_workflow),
    FileKind(DOCKER, MANIFEST, dockerfile_from, match=_dockerfile),
    FileKind(TERRAFORM, MANIFEST, terraform_lock, frozenset({".terraform.lock.hcl"}), records=True),
    FileKind(TERRAFORM, MANIFEST, terraform_config, match=_terraform),
    FileKind(CARGO, MANIFEST, None, frozenset({"Cargo.toml"})),
    FileKind(CARGO, LOCK, None, frozenset({"Cargo.lock"})),
    FileKind(BUNDLER, LOCK, None, frozenset({"Gemfile.lock"})),
    FileKind(COMPOSER, LOCK, None, frozenset({"composer.lock"})),
    FileKind(SWIFT, MANIFEST, None, frozenset({"Package.swift", "Package.resolved"})),
    FileKind(NUGET, MANIFEST, None, frozenset({"packages.config", "Directory.Packages.props"}), _dotnet_project),
)
_BY_NAME = {row.ecosystem.name: row.ecosystem for row in _FILES}


def file_kind(path: str) -> FileKind | None:
    """The row for a changed path, or None when it is not a dependency file."""
    posix = PurePosixPath(path)
    return next((row for row in _FILES if posix.name in row.names or (row.match and row.match(posix))), None)


def beside(ecosystem: Ecosystem, role: str, directory: str) -> list[tuple[str, FileKind]]:
    """Paths of the fixed-name files with this role and a grammar in `directory`, with their rows."""
    return [
        (str(PurePosixPath(directory) / name), row)
        for row in _FILES
        if row.ecosystem == ecosystem and row.role == role and row.parse is not None
        for name in sorted(row.names)
    ]


def _first(rules: tuple[_RefRule, ...], old: str, new: str) -> str:
    return next((reason for reason, applies in rules if applies(old, new)), "")


def locked(ecosystem: str, directory: str, name: str, version: str, read: Callable[[str], str]) -> tuple[str, ...]:
    """The hash each installed copy of `name` at exact `version` records in the locks and checksums beside `directory`.

    Each row's `hashes` reads which entries are installed copies and what they record. "" is a copy with no hash.
    """
    row = _BY_NAME.get(ecosystem)
    if row is None or not version:
        return ()
    found: list[str] = []
    for path, kind in [item for role in (LOCK, CHECKSUMS) for item in beside(row, role, directory)]:
        parsed = kind.parse(read(path)) if kind.hashes else None
        for entry in parsed[0] if parsed else ():
            recorded = kind.hashes(entry)
            if recorded is not None and entry[0] == name and exact_body(entry[1], mode=ecosystem) == version:
                found.append(recorded)
    return tuple(found)


def warn_reason(ecosystem: str, old: str, new: str) -> str:
    """Why a change in `ecosystem` from `old` to `new` is not scanned, or "" when it is scanned."""
    row = _BY_NAME.get(ecosystem)
    if row is None:
        return ""
    return row.warn or _first(row.ref_rules, old, new)


def unresolved_reason(ecosystem: str, old: str, new: str, record: dict) -> str:
    """The warn reason for a change whose scan `record` says its refs do not resolve, or "" when the record stands.

    Any other record, a failed clone included, stands as the scan reported it.
    """
    row = _BY_NAME.get(ecosystem)
    unresolved = record.get("status") == "not_scanned" and record.get("not_scanned_reason") in _REFS_UNRESOLVED
    return _first(row.unresolved_rules, old, new) if row and unresolved else ""


def upstream_repo(ecosystem: str, name: str, version: str) -> upstream.Repo:
    """The GitHub repository a change is scanned from, or Repo() when the ecosystem has none or the lookup failed.

    An allowlisted package skips the lookup.
    """
    known = known_repo(ecosystem, name)
    if known:
        return upstream.Repo(known, upstream.ALLOWLISTED)
    row = _BY_NAME.get(ecosystem)
    return row.repo(name, version) if row else upstream.Repo()


def bind(ecosystem: str, subject: binding.Subject) -> binding.Binding:
    """Whether a covered scan of a change in `ecosystem` is the artifact it installs."""
    row = _BY_NAME.get(ecosystem)
    return row.bind(subject) if row else binding.unsupported(subject)
