"""The GitHub repository a primary dependency is scanned from.

A GitHub Action and a github.com Go module name their repository in the
package identity. An npm or PyPI package, and a Go module on another host,
name it in registry or go-get metadata that the publisher controls. Every
answer is a Repo: an `owner/repo` and where the name came from, or Repo()
when none is found.

A repository is verified when the package identity names it, when a
provenance attestation for the installed artifact names it
(dependency_cursor_review_binding.repo_source), or when the allowlist in
dependency_cursor_review_ecosystems maps the package to it. A repository
named only by publisher metadata is not, and decide() never reports a scan
of it benign.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.parse
from typing import NamedTuple

_PART = r"[A-Za-z0-9_.-]+"
_GITHUB_URL_RE = re.compile(
    rf"(?:git\+)?(?:(?:https?|git|ssh)://(?:git@)?|git@)(?:www\.)?github\.com[/:]({_PART})/({_PART})(?:[/#?].*)?",
    re.IGNORECASE,
)
_NPM_SHORTHAND_RE = re.compile(rf"(?:github:)?({_PART})/({_PART})")
_NPM_NAME_RE = re.compile(r"(?:@[A-Za-z0-9._~-]+/)?[A-Za-z0-9._~-]+")
_PYPI_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
# A module path starts with a dotted host name, never an address or a port.
_GO_MODULE_RE = re.compile(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[A-Za-z0-9_.~+-]+)+")
_GO_META_RE = re.compile(r"""<meta\s+name=["'](go-import|go-source)["']\s+content=["']([^"']*)["']""", re.IGNORECASE)
_SOURCE_LABEL_RE = re.compile(r"source|repo|code|github", re.IGNORECASE)
_LIMIT = 4 * 1024 * 1024

# Where a repository name came from.
IDENTITY = "identity"  # the package identity: an action's owner/repo, a github.com Go module path
ATTESTED = "attested"  # a provenance attestation for the installed artifact
ALLOWLISTED = "allowlisted"  # dependency_cursor_review_ecosystems.KNOWN_REPOS
PUBLISHER = "publisher"  # registry or go-get metadata the publisher writes
VERIFIED = frozenset({IDENTITY, ATTESTED, ALLOWLISTED})


def verified(source: object) -> bool:
    """A repo_source names a verified repository; a list or object from the JSON never does."""
    return isinstance(source, str) and source in VERIFIED


class Repo(NamedTuple):
    slug: str = ""  # owner/repo, "" when none was found
    source: str = ""  # IDENTITY, ATTESTED, ALLOWLISTED or PUBLISHER; "" with no slug


def _found(slug: str, source: str) -> Repo:
    return Repo(slug, source) if slug else Repo()


def _repo(owner: str, name: str) -> str:
    name = name[:-4] if name.lower().endswith(".git") else name
    if not name or {owner, name} & {".", ".."}:
        return ""
    return f"{owner}/{name}"


def github_repo(url: object) -> str:
    """`owner/repo` of a github.com URL in any git or browser spelling, or ""."""
    match = _GITHUB_URL_RE.fullmatch(url.strip()) if isinstance(url, str) else None
    return _repo(match.group(1), match.group(2)) if match else ""


def _fetch(url: str, limit: int = _LIMIT) -> bytes | None:
    """The body of a 200 response to an https GET, b"" for a 404, or None when there is no readable answer.

    Redirects are not followed.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    connection = http.client.HTTPSConnection(parts.hostname, timeout=20)
    try:
        connection.request("GET", target, headers={"Accept": "application/json", "User-Agent": "dependency-review"})
        response = connection.getresponse()
        status, body = response.status, response.read(limit + 1)
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()
    if status == 404:
        return b""
    return body if status == 200 and len(body) <= limit else None


def fetch_archive(url: str, limit: int) -> bytes | None:
    """The body of a 200 response to an https GET of at most `limit` bytes, or None for anything else."""
    return _fetch(url, limit) or None


def fetch_json(url: str) -> dict | None:
    """The JSON object an https GET answers with, {} for a 404, or None when there is no readable object."""
    body = _fetch(url)
    if not body:
        return None if body is None else {}
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def action(name: str, _version: str) -> Repo:
    """`owner/repo` of `owner/repo[/path]`."""
    owner, _, rest = name.partition("/")
    return _found(_repo(owner, rest.split("/", 1)[0]) if re.fullmatch(_PART, owner) and rest else "", IDENTITY)


def _npm_repository(name: str, version: str) -> str:
    if not _NPM_NAME_RE.fullmatch(name):
        return ""
    doc = fetch_json(f"https://registry.npmjs.org/{name}/{urllib.parse.quote(version, safe='')}") or {}
    repository = doc.get("repository")
    url = repository.get("url") if isinstance(repository, dict) else repository
    if not isinstance(url, str):
        return ""
    shorthand = _NPM_SHORTHAND_RE.fullmatch(url.strip())
    return _repo(shorthand.group(1), shorthand.group(2)) if shorthand else github_repo(url)


def npm(name: str, version: str) -> Repo:
    """The version document's `repository`: a URL, `{url}`, or `owner/repo` / `github:owner/repo` shorthand."""
    return _found(_npm_repository(name, version), PUBLISHER)


def _pypi_repository(name: str, version: str) -> str:
    if not _PYPI_NAME_RE.fullmatch(name):
        return ""
    quoted = urllib.parse.quote(version, safe="")
    info = (fetch_json(f"https://pypi.org/pypi/{name}/{quoted}/json") or {}).get("info")
    if not isinstance(info, dict):
        return ""
    urls = info.get("project_urls") if isinstance(info.get("project_urls"), dict) else {}
    labelled = sorted(urls.items(), key=lambda item: not _SOURCE_LABEL_RE.search(str(item[0])))
    return next(filter(None, map(github_repo, [url for _label, url in labelled] + [info.get("home_page")])), "")


def pypi(name: str, version: str) -> Repo:
    """The first GitHub project URL, source-like labels before the home page."""
    return _found(_pypi_repository(name, version), PUBLISHER)


def _go_get_repository(module: str) -> str:
    page = (_fetch(f"https://{module}?go-get=1") or b"").decode("utf-8", errors="replace")
    metas = [(kind.lower(), content.split()) for kind, content in _GO_META_RE.findall(page)]
    for want, index in (("go-import", 2), ("go-source", 1)):
        for kind, fields in metas:
            prefix = fields[0] if fields else ""
            if kind == want and len(fields) > index and (module == prefix or module.startswith(prefix + "/")):
                found = github_repo(fields[index])
                if found:
                    return found
    return ""


def go(module: str, _version: str) -> Repo:
    """github.com/owner/repo from the module path, else the go-import or go-source GitHub URL for the module."""
    if not _GO_MODULE_RE.fullmatch(module):
        return Repo()
    parts = module.split("/")
    if parts[0] == "github.com":
        return _found(_repo(parts[1], parts[2]) if len(parts) >= 3 else "", IDENTITY)
    return _found(_go_get_repository(module), PUBLISHER)
