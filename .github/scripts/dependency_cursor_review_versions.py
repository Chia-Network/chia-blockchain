"""The one version model: an exact-version grammar per ecosystem, action refs, release tags and version jumps.

The manifest diff, the coverage scan and the upstream scan shell all read
versions here. Each mode is an ecosystem and names which prefix its tokens
may drop and which version shape is exact. A range, wildcard, tag name or
moving major such as an action's `v4` is never an exact version in any mode.

The shell calls the command line. Python itself exits 1 or 2 when the
script fails, so every answer other than success uses its own code above 2:
  dependency_cursor_review_versions.py release-tag REPO VERSION [MODE]
      prints "<sha>\\t<tag>", or "<sha>\\t<sha>" for an action's commit SHA;
      exit 3 when no spelling peels, 4 when spellings disagree
  dependency_cursor_review_versions.py jump FROM TO
      exit 0 when the bump is a version-jump anomaly, 3 when it is not
"""

from __future__ import annotations

import enum
import re
import subprocess
import sys
from dataclasses import dataclass

# A PEP 440 pre/post/dev release (`1.2.3rc1`, `1.2.3.post1`, `1.2.3.dev0`)
# or a separator-prefixed pre/build suffix may spell out an exact version.
_SUFFIX = (
    r"(?:"
    r"(?:a|b|c|rc)[0-9]+(?:\.post[0-9]+)?(?:\.dev[0-9]+)?"
    r"|\.post[0-9]+(?:\.dev[0-9]+)?"
    r"|\.dev[0-9]+"
    r"|[-+][0-9A-Za-z][0-9A-Za-z.-]*"
    r")?"
)
# `==` and `===` are Python exact-pin operators; every range operator stays on the token.
_PIN_PREFIX_RE = re.compile(r"^(?:===|==|[vV])")
# Outside a Python manifest only a tag-style `v`/`V` is dropped.
_V_PREFIX_RE = re.compile(r"^[vV]")
# Dot-separated numeric parts are the version. An x/X or * part is a wildcard.
_EXACT_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+)*" + _SUFFIX)
# `1` or `1.2` is an npm X-range and a moving action tag, never an exact
# version, so npm and action versions have exactly three numeric parts.
_SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+" + _SUFFIX)
# A release such as 1.2.3, 2024.2 or 1.2.3.4 is exact; a bare `1` or `v4` is a moving major.
_RELEASE_RE = re.compile(r"(?P<release>[0-9]+(?:\.[0-9]+)+)" + _SUFFIX)
# A full commit SHA, in either case, pins an action ref without being a release tag.
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")

# Keyed by the ecosystem a token comes from: pip drops `==`, `===`, `v` or `V`;
# the others drop only `v`/`V`. npm and github-actions need three numeric parts,
# and an action's commit SHA is exact too.
_MODES: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "pip": (_PIN_PREFIX_RE, _EXACT_VERSION_RE),
    "npm": (_V_PREFIX_RE, _SEMVER_RE),
    "go": (_V_PREFIX_RE, _RELEASE_RE),
    "github-actions": (_V_PREFIX_RE, _SEMVER_RE),
}


def _version_body(value: str, prefix: re.Pattern[str]) -> str:
    """The version with one prefix that `prefix` matches removed."""
    value = value.strip()
    match = prefix.match(value)
    return value[match.end() :].strip() if match else value


def exact_body(value: str, *, mode: str) -> str:
    """The exact version a token pins in ecosystem `mode`, or "" for a range, wildcard, empty token or unknown mode."""
    if mode not in _MODES:
        return ""
    if mode == "github-actions" and commit_ref(value.strip()):
        return value.strip().lower()
    prefix, pattern = _MODES[mode]
    match = pattern.fullmatch(_version_body(value, prefix))
    return match.group(0) if match else ""


def commit_ref(ref: str) -> bool:
    """True for a GitHub Actions ref that is a full commit SHA."""
    return bool(_COMMIT_RE.fullmatch(ref))


def moving_ref(ref: str) -> bool:
    """True for a GitHub Actions ref that is neither a full release tag nor a commit SHA: `v4`, `v4.1`, a branch."""
    return not commit_ref(ref) and not exact_body(ref, mode="github-actions")


class TagStatus(enum.IntEnum):
    """How a release-tag lookup ended. The value is the command-line exit code."""

    FOUND = 0
    ABSENT = 3
    DISAGREE = 4


@dataclass(frozen=True)
class ReleaseTag:
    status: TagStatus
    commit: str = ""
    name: str = ""


_ABSENT = ReleaseTag(TagStatus.ABSENT)
_DISAGREE = ReleaseTag(TagStatus.DISAGREE)
# `jump` exits 0 for an anomaly and this code for an ordinary bump.
NO_JUMP = 3


def _tag_name_ok(name: str) -> bool:
    proc = subprocess.run(
        ["git", "check-ref-format", "--allow-onelevel", f"refs/tags/{name}"], capture_output=True, check=False
    )
    return proc.returncode == 0


def _peel(repo: str, rev: str) -> str:
    """The commit `rev` peels to in `repo`, or "" when there is none."""
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _tag(repo: str, name: str) -> str:
    """The commit `refs/tags/<name>` peels to, or "" when it is not a valid, existing tag."""
    return _peel(repo, f"refs/tags/{name}") if _tag_name_ok(name) else ""


def _commit(repo: str, sha: str) -> ReleaseTag:
    """A commit SHA names itself when a branch or tag of `repo` contains it.

    GitHub serves a commit that only a fork of the repository has under the
    repository's name, so a commit off every branch and tag is ABSENT.
    """
    if _peel(repo, sha) != sha:
        return _ABSENT
    proc = subprocess.run(
        [
            "git",
            "-C",
            repo,
            "for-each-ref",
            "--count=1",
            f"--contains={sha}",
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return ReleaseTag(TagStatus.FOUND, sha, sha) if proc.returncode == 0 and proc.stdout.strip() else _ABSENT


def release_tag(repo: str, version: str, mode: str = "") -> ReleaseTag:
    """The commit and tag name of the release tag for `version` in `repo`.

    In github-actions mode a commit SHA is its own release: its commit and name are the SHA.

    One leading `v` or `V` is noted. Every existing spelling of the bare
    version (`<bare>`, `v<bare>`, `V<bare>`) must peel to the same commit.
    A `V` version takes only `V<bare>`; any other version takes `<bare>`,
    then `v<bare>`. DISAGREE means the spellings peel to different commits,
    or a prefixed version would be satisfied only by the other case. ABSENT
    means no accepted spelling peels; branches and raw revisions are not tags.
    """
    if mode == "github-actions" and commit_ref(version):
        return _commit(repo, version.lower())
    lead = version[:1] if version[:1] in {"v", "V"} else ""
    bare = version[len(lead) :]
    if not bare or not _tag_name_ok(bare):
        return _ABSENT
    found = {name: _tag(repo, name) for name in (bare, f"v{bare}", f"V{bare}")}
    if len({commit for commit in found.values() if commit}) > 1:
        return _DISAGREE
    for name in (f"V{bare}",) if lead == "V" else (bare, f"v{bare}"):
        if found[name]:
            return ReleaseTag(TagStatus.FOUND, found[name], name)
    return _DISAGREE if lead and any(found.values()) else _ABSENT


def _major_minor(version: str) -> tuple[int, int] | None:
    """Major and minor of an exact release with two or more numeric parts, or None when it is not one."""
    match = _RELEASE_RE.fullmatch(_version_body(version, _V_PREFIX_RE))
    if not match:
        return None
    major, minor = match.group("release").split(".")[:2]
    return int(major), int(minor)


def version_jump(frm: str, to: str) -> bool:
    """True for a major bump, or for more than five minors within one major.

    Both versions are read like the scan's own from/to versions, so an empty
    from version (a scan with no from tag) is never a jump.
    """
    old, new = _major_minor(frm), _major_minor(to)
    if old is None or new is None:
        return False
    return new[0] > old[0] or (new[0] == old[0] and new[1] - old[1] > 5)


def main(argv: list[str]) -> int:
    command, args = argv[:1], argv[1:]
    if command == ["release-tag"] and len(args) in {2, 3}:
        found = release_tag(*args)
        if found.status is TagStatus.FOUND:
            print(f"{found.commit}\t{found.name}")
        return found.status.value
    if command == ["jump"] and len(args) == 2:
        return 0 if version_jump(*args) else NO_JUMP
    print("usage: dependency_cursor_review_versions.py release-tag REPO VERSION [MODE] | jump FROM TO", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
