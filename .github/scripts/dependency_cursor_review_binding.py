"""Whether the scanned release is the artifact a primary dependency installs.

The scan reads a commit in the GitHub repository the registry names, and the
publisher controls that name. A binding ties the installed artifact back to
the scanned commit:

- intrinsic: the ecosystem installs that git content itself. An action runs
  the commit its full tag or commit SHA resolves to in the action's own
  repository, which is the commit scanned.
- checksum: the module zip the Go proxy serves for the version hashes to the
  go.sum entry beside the change, and the proxy records that it built the
  zip from the scanned commit itself.
- provenance: every artifact hash the lockfile records is the registry's for
  a file of the version, and every provenance attestation the registry serves
  for that file names the scanned repository, the scanned commit itself and
  the file's digest.
- unbound: anything else, with a reason. decide() never reports it benign.

Provenance is read, not verified: the registry checks the Sigstore signature
when the attestation is published, and this module reads the repository and
commit from the Fulcio certificate's extensions and the digest from the
signed statement. A registry that gives no readable answer, or one that
records no artifact hash for the version (a 404 or an empty release), is
registry_unavailable, never a hash or provenance result.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.parse
from typing import NamedTuple

import dependency_cursor_review_certificate as certificate
import dependency_cursor_review_upstream as upstream
from dependency_manifest_go import GO_ZIP_LIMIT, go_zip_hash

INTRINSIC, CHECKSUM, PROVENANCE, UNBOUND = "intrinsic", "checksum", "provenance", "unbound"
BOUND = frozenset({INTRINSIC, CHECKSUM, PROVENANCE})
# Why a scan is unbound.
NO_LOCK_HASH = "no_lock_hash"  # no lock beside the change records a usable artifact hash for the version
HASH_MISMATCH = "hash_mismatch"  # the registry's artifact hash for the version is not the lock's
COMMIT_MISMATCH = "commit_mismatch"  # the registry names no commit, or another one, as the artifact's source
NO_PROVENANCE = "no_provenance"  # the registry serves no provenance attestation for the artifact
PROVENANCE_MISMATCH = "provenance_mismatch"  # an attestation names another repository, commit or digest
REGISTRY_UNAVAILABLE = "registry_unavailable"  # the registry gave no readable answer or no artifact hash to compare
UNSUPPORTED = "unsupported"  # the ecosystem has no binding
REASONS = frozenset(
    {
        NO_LOCK_HASH,
        HASH_MISMATCH,
        COMMIT_MISMATCH,
        NO_PROVENANCE,
        PROVENANCE_MISMATCH,
        REGISTRY_UNAVAILABLE,
        UNSUPPORTED,
    }
)

_SLSA_V1 = "https://slsa.dev/provenance/v1"
_GO_PROXY = "https://proxy.golang.org"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")


class Binding(NamedTuple):
    kind: str
    reason: str = ""


class Subject(NamedTuple):
    """A covered primary change: what was installed and what was scanned."""

    name: str
    version: str
    repo: str  # owner/repo that was scanned
    commit: str  # the scanned commit (the peeled to tag)
    locked: tuple[str, ...] = ()  # what each lock entry for name at version records (ecosystems.locked), "" for none


_INTRINSIC = Binding(INTRINSIC)
_CHECKSUM = Binding(CHECKSUM)
_PROVENANCE = Binding(PROVENANCE)


def _unbound(reason: str) -> Binding:
    return Binding(UNBOUND, reason)


_UNAVAILABLE = _unbound(REGISTRY_UNAVAILABLE)


def repo_source(source: str, found: Binding) -> str:
    """Where the scanned repository's name came from, once bound: a provenance binding attests the repository."""
    return upstream.ATTESTED if source == upstream.PUBLISHER and found.kind == PROVENANCE else source


def intrinsic(_subject: Subject) -> Binding:
    return _INTRINSIC


def unsupported(_subject: Subject) -> Binding:
    return _unbound(UNSUPPORTED)


def _decoded(text: object) -> bytes:
    return base64.b64decode(text, validate=True) if isinstance(text, str) else b""


def _attested(subject: Subject, cert: object, statement: object, algorithm: str, digest: str) -> bool:
    """One attestation names the scanned repository, the scanned commit and the artifact digest."""
    try:
        source = certificate.source(_decoded(cert))
        doc = json.loads(_decoded(statement))
    except (ValueError, UnicodeDecodeError, binascii.Error, IndexError, RecursionError):
        return False
    items = doc.get("subject") if isinstance(doc, dict) else None
    digests = [item.get("digest") for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return (
        source.repo_uri.lower() == f"https://github.com/{subject.repo}".lower()
        and bool(subject.commit)
        and source.commit == subject.commit
        and any(isinstance(item, dict) and item.get(algorithm) == digest for item in digests)
    )


def _provenance(subject: Subject, attestations: list[tuple[object, object]], algorithm: str, digest: str) -> Binding:
    if not attestations:
        return _unbound(NO_PROVENANCE)
    if all(_attested(subject, cert, statement, algorithm, digest) for cert, statement in attestations):
        return _PROVENANCE
    return _unbound(PROVENANCE_MISMATCH)


def _dig(doc: object, *keys: str | int) -> object:
    for key in keys:
        if isinstance(key, int) and isinstance(doc, list) and len(doc) > key:
            doc = doc[key]
        elif isinstance(key, str) and isinstance(doc, dict):
            doc = doc.get(key)
        else:
            return None
    return doc


def npm(subject: Subject) -> Binding:
    """The lock's sha512 integrity is the registry's, and the SLSA attestations are for it and the scan."""
    integrities = set(subject.locked) - {""}
    integrity = integrities.pop() if len(integrities) == 1 else ""
    if not integrity.startswith("sha512-"):
        return _unbound(NO_LOCK_HASH)
    try:
        digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True).hex()
    except binascii.Error:
        return _unbound(NO_LOCK_HASH)
    version = urllib.parse.quote(subject.version, safe="")
    registered = _dig(upstream.fetch_json(f"https://registry.npmjs.org/{subject.name}/{version}"), "dist", "integrity")
    if not isinstance(registered, str) or not registered:
        return _UNAVAILABLE
    if registered != integrity:
        return _unbound(HASH_MISMATCH)
    escaped = urllib.parse.quote(subject.name, safe="@")
    found = upstream.fetch_json(f"https://registry.npmjs.org/-/npm/v1/attestations/{escaped}@{version}")
    if found is None:
        return _UNAVAILABLE
    bundles = [
        _dig(item, "bundle")
        for item in _dig(found, "attestations") or []
        if isinstance(item, dict) and item.get("predicateType") == _SLSA_V1
    ]
    pairs = [
        (
            _dig(bundle, "verificationMaterial", "x509CertificateChain", "certificates", 0, "rawBytes")
            or _dig(bundle, "verificationMaterial", "certificate", "rawBytes"),
            _dig(bundle, "dsseEnvelope", "payload"),
        )
        for bundle in bundles
    ]
    return _provenance(subject, pairs, "sha512", digest)


def _go_escaped(text: str) -> str:
    """A module path or version as the module proxy spells it: an upper-case letter is `!` and its lower case."""
    escaped = re.sub(r"[A-Z]", lambda match: "!" + match.group(0).lower(), text)
    return urllib.parse.quote(escaped, safe="/!+")


def go(subject: Subject) -> Binding:
    """The proxy's module zip hashes to the go.sum entry, and the proxy built that zip from the scanned commit.

    The go command installs a module only when its zip hashes to the go.sum entry, so that zip is the one checked.
    """
    sums = set(subject.locked) - {""}
    want = sums.pop() if len(sums) == 1 else ""
    if not want.startswith("h1:"):
        return _unbound(NO_LOCK_HASH)
    base = f"{_GO_PROXY}/{_go_escaped(subject.name)}/@v/{_go_escaped('v' + subject.version)}"
    archive = upstream.fetch_archive(base + ".zip", GO_ZIP_LIMIT)
    found = go_zip_hash(archive) if archive else ""
    if not found:
        return _UNAVAILABLE
    if found != want:
        return _unbound(HASH_MISMATCH)
    info = upstream.fetch_json(base + ".info")
    if info is None:
        return _UNAVAILABLE
    if not subject.commit or _dig(info, "Origin", "Hash") != subject.commit:
        return _unbound(COMMIT_MISMATCH)
    return _CHECKSUM


def pypi(subject: Subject) -> Binding:
    """Each sha256 the lock records is a file of the release, with publish attestations for its digest and the scan.

    pip, Poetry and Pipenv install only a file whose hash the lock records, so each of those files is checked.
    """
    entries = [set(hashes.split()) for hashes in subject.locked]
    locked = sorted(set().union(*entries))
    if not entries or not all(entries) or not all(_SHA256_RE.fullmatch(digest) for digest in locked):
        return _unbound(NO_LOCK_HASH)
    project, version = subject.name, urllib.parse.quote(subject.version, safe="")
    urls, files = _dig(upstream.fetch_json(f"https://pypi.org/pypi/{project}/{version}/json"), "urls"), {}
    for item in urls if isinstance(urls, list) else []:
        filename, sha256 = _dig(item, "filename"), _dig(item, "digests", "sha256")
        if isinstance(filename, str) and isinstance(sha256, str):
            files.setdefault(f"sha256:{sha256}", filename)
    if not files:
        return _UNAVAILABLE
    if not all(digest in files for digest in locked):
        return _unbound(HASH_MISMATCH)
    for digest in locked:
        quoted = urllib.parse.quote(files[digest], safe="")
        found = upstream.fetch_json(f"https://pypi.org/integrity/{project}/{version}/{quoted}/provenance")
        if found is None:
            return _UNAVAILABLE
        pairs = [
            (_dig(attestation, "verification_material", "certificate"), _dig(attestation, "envelope", "statement"))
            for bundle in _dig(found, "attestation_bundles") or []
            for attestation in _dig(bundle, "attestations") or []
        ]
        binding = _provenance(subject, pairs, "sha256", digest.removeprefix("sha256:"))
        if binding != _PROVENANCE:
            return binding
    return _PROVENANCE
