"""Scan every primary dependency change of a pull request.

The manifest diff (dependency_manifest_diff.plan) is the update list. A
primary change is scanned unless its ecosystem's policy warns; a dependency is
covered only when its scan is conclusive and both from_tag and to_tag are set.
Anything else makes the group inconclusive. Each covered scan carries the
binding of the scanned commit to the installed artifact, and where the
scanned repository's name came from. Policy warnings,
other upgraded packages and unparsed lockfiles are disclosed in the report and
the summary.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dependency_cursor_review_binding as _binding
import dependency_cursor_review_ecosystems as _ecosystems
import dependency_cursor_review_upstream as _upstream
import dependency_cursor_review_versions as _versions
import dependency_manifest_diff as _diff
from malware_verdict_formatter import DISCLOSED_KEYS, NOTHING_TO_SCAN

_FINDING_KEYS = ("unicode", "confusable", "ioc", "heuristic")
# Registry lookups and bindings run at once; each waits on the network, not on the others.
_LOOKUPS = 8


class Target(NamedTuple):
    """What one scan record is about: a primary change, or a path the diff could not account for."""

    package: str = ""
    path: str = ""
    repo: _upstream.Repo = _upstream.Repo()
    old: str = ""
    new: str = ""


class Disclosure(NamedTuple):
    """The changes the report lists and does not scan. Its fields are DISCLOSED_KEYS."""

    policy_warnings: tuple[dict, ...] = ()
    unchecked_upgrades: tuple[dict, ...] = ()
    unparsed_locks: tuple[str, ...] = ()


_NONE_DISCLOSED = Disclosure()


def _fields(target: Target) -> dict[str, str]:
    """The record fields that name a target."""
    return {
        "package_name": target.package,
        "path": target.path,
        "upstream_repo": target.repo.slug,
        "repo_source": target.repo.source,
        "from_version": target.old,
        "to_version": target.new,
    }


def uncovered(target: Target, reason: str) -> dict:
    fields = _fields(target)
    return {
        "status": "not_scanned",
        "scan_conclusive": False,
        "not_scanned_reason": reason,
        "verdict_token_in_tree": False,
        "resolution_strategy": "unresolved",
        "resolved_range": "",
        "resolved_from": "",
        "resolved_to": "",
        "from_tag": "",
        "to_tag": "",
        "changed_files_count": 0,
        "materialized_count": 0,
        "filtered_count": 0,
        "changed_files": [],
        "errors": [f"{_record_label(fields)}: {reason}"],
        "findings": {key: [] for key in _FINDING_KEYS},
        **fields,
    }


def _tag(target: Target, report: dict) -> dict:
    tagged = {**report, **_fields(target)}
    if tagged.get("scan_conclusive") is not True:
        tagged["scan_conclusive"] = False
    return tagged


def _tagged(report: dict) -> bool:
    return bool(str(report.get("from_tag") or "").strip()) and bool(str(report.get("to_tag") or "").strip())


def _covered(report: dict) -> bool:
    """Conclusive tag-to-tag scan. A branch or HEAD does not count; an action's commit SHA is its own tag."""
    return report.get("scan_conclusive") is True and _tagged(report)


def _apply_coverage(report: dict) -> dict:
    covered = _covered(report)
    stamped = dict(report)
    stamped["scan_conclusive"] = covered
    if not covered:
        if not str(stamped.get("not_scanned_reason") or "").strip():
            stamped["not_scanned_reason"] = "incomplete_coverage"
        if stamped.get("status") not in {"fail", "warn"}:
            stamped["status"] = "not_scanned"
    return stamped


def agent_target(records: list[dict]) -> tuple[str, str, str] | None:
    """Pure (package, repository, resolved commit) selection. Does not clone."""
    for record in records:
        repo = str(record.get("upstream_repo") or "")
        resolved_to = str(record.get("resolved_to") or "")
        if _covered(record) and repo and resolved_to:
            return (str(record.get("package_name") or ""), repo, resolved_to)
    return None


def _identity(record: dict) -> tuple[str, str, str]:
    return (
        str(record.get("package_name") or ""),
        str(record.get("upstream_repo") or ""),
        str(record.get("resolved_to") or ""),
    )


def _candidate(record: dict) -> dict:
    return {
        "package_name": str(record.get("package_name") or ""),
        "upstream_repo": str(record.get("upstream_repo") or ""),
        "resolved_to": str(record.get("resolved_to") or ""),
        "resolved_from": str(record.get("resolved_from") or ""),
        "from_version": str(record.get("from_version") or ""),
        "to_version": str(record.get("to_version") or ""),
        "from_tag": str(record.get("from_tag") or ""),
        "to_tag": str(record.get("to_tag") or ""),
        "scan_conclusive": _covered(record),
    }


def _stamp(report: dict, records: list[dict], target: tuple[str, str, str] | None, disclosed: Disclosure) -> dict:
    report["agent_candidates"] = [_candidate(record) for record in records]
    report["agent_target"] = list(target) if target else None
    report.update({key: list(items) for key, items in zip(DISCLOSED_KEYS, disclosed, strict=True)})
    return report


def _selected(records: list[dict], target: tuple[str, str, str] | None) -> dict:
    if target is None:
        return {}
    return next((record for record in records if _identity(record) == target), {})


def agent_fields(records: list[dict]) -> dict[str, str]:
    """Prompt fields for agent_target. Empty when no dependency was scanned conclusively."""
    target = agent_target(records)
    if target is None:
        return {
            "package": "",
            "from_version": "",
            "to_version": "",
            "resolved_from": "",
            "resolved_to": "",
        }
    chosen = _selected(records, target)
    return {
        "package": target[0],
        "from_version": str(chosen.get("from_version") or ""),
        "to_version": str(chosen.get("to_version") or ""),
        "resolved_from": str(chosen.get("resolved_from") or ""),
        "resolved_to": target[2],
    }


def _unread_items(records: list[dict]) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        for item in record.get("unread") or []:
            if not isinstance(item, dict):
                continue
            file_name = item.get("file")
            cause = item.get("cause")
            if not isinstance(file_name, str) or not file_name.strip():
                continue
            why = cause.strip() if isinstance(cause, str) and cause.strip() else "incomplete"
            key = (file_name.strip(), why)
            if key in seen:
                continue
            seen.add(key)
            found.append({"file": file_name.strip(), "cause": why})
    return found


def aggregate(records: list[dict], disclosed: Disclosure = _NONE_DISCLOSED) -> dict:
    """Covered only when every record was scanned conclusively.

    With no record, a change that was only disclosed (a policy warning, an
    unchecked upgrade or an unparsed lockfile) is NOTHING_TO_SCAN. With
    nothing at all, coverage is incomplete.
    """
    target = agent_target(records)
    if len(records) == 1:
        return _stamp(_apply_coverage(records[0]), records, target, disclosed)
    if not records:
        if any(disclosed):
            return _stamp({**uncovered(Target(), NOTHING_TO_SCAN), "errors": []}, records, None, disclosed)
        return _stamp(uncovered(Target(), "incomplete_coverage"), records, None, disclosed)

    findings = {key: [] for key in _FINDING_KEYS}
    errors: list[str] = []
    changed: list[str] = []
    for record in records:
        name = _record_label(record)
        if not _covered(record):
            reason = str(record.get("not_scanned_reason") or "not_conclusive")
            errors.append(f"{name}: {reason}")
        for key in _FINDING_KEYS:
            items = (record.get("findings") or {}).get(key) or []
            if isinstance(items, list):
                findings[key].extend(items)
        for item in record.get("errors") or []:
            if item not in errors:
                errors.append(str(item))
        for path in record.get("changed_files") or []:
            changed.append(f"{name}:{path}")

    conclusive = all(_covered(record) for record in records)
    warned = any(record.get("status") == "warn" or record.get("verdict_token_in_tree") is True for record in records)
    if any(record.get("status") == "fail" for record in records):
        status = "fail"
    elif warned or any(findings.values()):
        status = "warn"
    elif not conclusive:
        status = "not_scanned"
    else:
        status = "clean"

    chosen = _selected(records, target)
    return _stamp(
        {
            "status": status,
            "scan_conclusive": conclusive,
            "not_scanned_reason": "" if conclusive else "incomplete_coverage",
            "verdict_token_in_tree": any(record.get("verdict_token_in_tree") is True for record in records),
            "resolution_strategy": "group",
            "package_name": chosen.get("package_name") or "",
            "upstream_repo": chosen.get("upstream_repo") or "",
            "from_version": chosen.get("from_version") or "",
            "to_version": chosen.get("to_version") or "",
            "resolved_range": chosen.get("resolved_range") or "",
            "resolved_from": chosen.get("resolved_from") or "",
            "resolved_to": chosen.get("resolved_to") or "",
            "from_tag": chosen.get("from_tag") or "",
            "to_tag": chosen.get("to_tag") or "",
            "changed_files_count": sum(int(record.get("changed_files_count") or 0) for record in records),
            "materialized_count": sum(int(record.get("materialized_count") or 0) for record in records),
            "filtered_count": sum(int(record.get("filtered_count") or 0) for record in records),
            "changed_files": changed,
            "errors": errors,
            "findings": findings,
            "unread": _unread_items(records),
            "binding": _weakest(records, "binding", _bound),
            "repo_source": _weakest(records, "repo_source", _verified),
            "dependencies": [
                {
                    "package_name": record.get("package_name") or "",
                    "upstream_repo": record.get("upstream_repo") or "",
                    "from_version": record.get("from_version") or "",
                    "to_version": record.get("to_version") or "",
                    "scan_conclusive": _covered(record),
                    "not_scanned_reason": record.get("not_scanned_reason") or "",
                    "binding": record.get("binding"),
                    "repo_source": record.get("repo_source"),
                }
                for record in records
            ],
        },
        records,
        target,
        disclosed,
    )


def _bound(record: dict) -> bool:
    found = record.get("binding")
    return isinstance(found, dict) and found.get("kind") in _binding.BOUND


def _verified(record: dict) -> bool:
    return _upstream.verified(record.get("repo_source"))


def _weakest(records: list[dict], key: str, holds: Callable[[dict], bool]) -> object:
    """The first `key` of a record it does not hold for, else the first record's: one value for the group."""
    return next((record.get(key) for record in records if not holds(record)), records[0].get(key))


def _record_label(record: dict) -> str:
    return str(record.get("package_name") or record.get("path") or record.get("upstream_repo") or "dependency")


def _code(text: object) -> str:
    """Upstream text as one inline code span. Backticks and line breaks are dropped."""
    return "`" + " ".join(str(text).replace("`", "").split()) + "`"


def _change(item: dict) -> str:
    name, old, new = item.get("name"), item.get("old") or "?", item.get("new") or "?"
    return f"{item.get('ecosystem')} {_code(f'{name} {old} -> {new}')} in {_code(item.get('dir'))}"


def _disclosure(report: dict) -> list[str]:
    lines = [
        f"- Not scanned by policy: {_change(item)} (`{item.get('reason')}`)"
        for item in report.get("policy_warnings") or []
    ]
    unchecked = report.get("unchecked_upgrades") or []
    if unchecked:
        noun, verb = ("package", "was") if len(unchecked) == 1 else ("packages", "were")
        lines.append(f"- {len(unchecked)} other {noun} {verb} upgraded and {verb} not checked by this run:")
        lines.extend(f"  - {_change(item)}" for item in unchecked)
    locks = report.get("unparsed_locks") or []
    if locks:
        lines.append("- These lockfiles were not parsed, so the packages they changed were not checked:")
        lines.extend(f"  - {_code(path)}" for path in locks)
    return lines


def render_summary(report: dict, records: list[dict]) -> str:
    lines = ["## Malware Scan Summary", ""]
    if report.get("scan_conclusive") is True:
        lines.append("- Scan coverage: **conclusive**.")
    else:
        reason = report.get("not_scanned_reason") or "incomplete_coverage"
        lines.append(f"- Scan coverage: **incomplete** (`{reason}`).")
        lines.append("- A dependency is covered only when its scan is conclusive.")
        lines.append("- This is not a benign result.")
    for record in records:
        span = f"{record.get('from_version') or '?'} -> {record.get('to_version') or '?'}"
        label = _code(f"{_record_label(record)} {span}") if record.get("package_name") else _code(_record_label(record))
        repo = record.get("upstream_repo") or "no repository"
        named = "" if _verified(record) else ", repository named only by publisher metadata"
        if _covered(record) and _bound(record):
            lines.append(f"- {label} ({repo}): covered, artifact binding `{record['binding']['kind']}`{named}")
        elif _covered(record):
            reason = (record.get("binding") or {}).get("reason") or "missing"
            lines.append(f"- {label} ({repo}): covered, artifact not bound (`{reason}`){named}")
        else:
            reason = record.get("not_scanned_reason") or "not_conclusive"
            lines.append(f"- {label} ({repo}): not covered ({reason})")
    lines.extend(_disclosure(report))
    if not any_read(report):
        lines.append("- No release tree was read. This is not evidence the package is benign.")
    return "\n".join(lines) + "\n"


def any_read(report: dict) -> bool:
    return int(report.get("materialized_count") or 0) > 0


_BASE_REF_RE = re.compile(r"\A[A-Za-z0-9._/-]+\Z")


def _git_text(rev: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _verify_commit(rev: str) -> str:
    # Concatenate the peel. An f-string brace escape is a Go text/template action.
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", rev + "^{commit}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


# The workflow passes a read-only token here because checkout runs with
# persist-credentials: false. main() removes it from the environment so no
# child process inherits it.
FETCH_AUTH_VARIABLE = "DCR_FETCH_TOKEN"


def _fetch_env(token: str) -> dict[str, str]:
    """Environment for one authenticated fetch.

    The Basic auth header goes in through GIT_CONFIG_* variables, the same
    one-time header the trusted checkout action uses, so the token is never
    in argv or in the persisted git config.
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if not token:
        return env
    try:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        index = 0
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env[f"GIT_CONFIG_KEY_{index}"] = "http.extraheader"
    env[f"GIT_CONFIG_VALUE_{index}"] = f"AUTHORIZATION: basic {basic}"
    env["GIT_CONFIG_COUNT"] = str(index + 1)
    return env


def _fetch_commit(sha: str, token: str = "") -> str:
    found = _verify_commit(sha)
    if found:
        return found
    # Output is discarded rather than logged.
    subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", sha],
        check=False,
        capture_output=True,
        text=True,
        env=_fetch_env(token),
    )
    return _verify_commit(sha)


def _base_commit(token: str = "") -> str:
    """Resolved base commit, or '' when no base is named or the named one cannot be read."""
    if not Path(".git").exists():
        return ""
    sha = os.environ.get("PR_BASE_SHA", "").strip()
    if sha:
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
            return ""
        return _fetch_commit(sha, token)
    ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if not _BASE_REF_RE.fullmatch(ref):
        return ""
    return _verify_commit(ref) or _verify_commit(f"origin/{ref}") or ""


def _changed_paths(base: str) -> list[tuple[str, str, str]] | None:
    """(before path, after path, status letter) for each file changed since base, deletions included."""
    diff = subprocess.run(
        ["git", "diff", "--name-status", "-z", "-M", "--diff-filter=AMRCTD", base, "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        return None
    fields = diff.stdout.split("\0")
    while fields and not fields[-1]:
        fields.pop()
    changed: list[tuple[str, str, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index][:1]
        need = 3 if status in {"R", "C"} else 2
        if index + need > len(fields):
            return None
        before = fields[index + 1]
        after = fields[index + 2] if need == 3 else before
        changed.append((before, after, status))
        index += need
    return changed


def _plan(token: str = "") -> _diff.Plan | None:
    """The diff's Plan, or None when the base is unnamed or unreadable.

    The workflow only runs this for a pull request, so a missing base never means "no changes".
    """
    base = _base_commit(token)
    changed = _changed_paths(base) if base else None
    return None if changed is None else _diff.plan(changed, _git_text, base)


def _warning(change: _diff.Change, reason: str) -> dict:
    return {**change._asdict(), "reason": reason}


def _split(plan: _diff.Plan) -> tuple[list[_diff.Change], tuple[dict, ...]]:
    """The primary changes to scan, and the policy warnings of the rest."""
    scanned: list[_diff.Change] = []
    warnings: list[dict] = []
    for change in plan.primary:
        reason = _ecosystems.warn_reason(change.ecosystem, change.old, change.new)
        if reason:
            warnings.append(_warning(change, reason))
        else:
            scanned.append(change)
    return scanned, tuple(warnings)


def remove_entry(path: Path) -> None:
    """Remove the entry at path; a link is unlinked, never followed."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _write_report(out: Path, report: dict, summary: str) -> None:
    (out / "malware_scan_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "malware_scan_summary.md").write_text(summary, encoding="utf-8")


def _clone(repo: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    proc = subprocess.run(
        ["git", "clone", "--", url, str(dest)],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and dest.is_dir()


def _exact(change: _diff.Change) -> tuple[Target, str]:
    """The Target of one primary change, and "unresolved" unless both versions are exact in its ecosystem's grammar.

    An empty from version stays inconclusive. A range, wildcard, tag name, operator or moving major could resolve to a
    tree other than the one installed, so it is never scanned.
    """
    old = _versions.exact_body(change.old, mode=change.ecosystem)
    new = _versions.exact_body(change.new, mode=change.ecosystem)
    target = Target(package=change.name, old=old or change.old, new=new or change.new)
    return target, "" if new and (old or not change.old) else "unresolved"


def _targets(changes: list[_diff.Change]) -> list[tuple[_diff.Change, Target, str]]:
    """Each change as (change, Target with its repository, why it is not scanned or "").

    Each distinct (ecosystem, name, version) is looked up once, and the lookups run concurrently.
    """
    exact = [(change, *_exact(change)) for change in changes]
    keys = [(change.ecosystem, change.name, target.new) for change, target, _why in exact]
    wanted = list(dict.fromkeys(key for key, (_change, _target, why) in zip(keys, exact) if not why))
    with ThreadPoolExecutor(max_workers=_LOOKUPS) as pool:
        repos = dict(zip(wanted, pool.map(lambda key: _ecosystems.upstream_repo(*key), wanted)))
    resolved: list[tuple[_diff.Change, Target, str]] = []
    for key, (change, target, why) in zip(keys, exact):
        repo = _upstream.Repo() if why else repos[key]
        found = target._replace(repo=repo)
        resolved.append((change, found, why or ("" if repo.slug else "no_upstream_link")))
    return resolved


def _bind(change: _diff.Change, target: Target, record: dict) -> _binding.Binding:
    """The binding of a covered scan to the artifact the change installs."""
    subject = _binding.Subject(
        name=target.package,
        version=target.new,
        repo=target.repo.slug,
        commit=str(record.get("resolved_to") or ""),
        locked=_ecosystems.locked(
            change.ecosystem, change.dir, target.package, target.new, lambda path: _git_text("HEAD", path)
        ),
    )
    return _ecosystems.bind(change.ecosystem, subject)


def _scan_one(target: Target, dest: Path, scan_script: Path, ecosystem: str = "") -> dict:
    dest = dest.absolute()
    checkout = dest / ".upstream-dependency"
    if not _clone(target.repo.slug, checkout):
        return uncovered(target, "unresolved")
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(dest / "github_output.txt")
    env["PACKAGE_NAME"] = target.package
    env["FROM_VERSION"] = target.old
    env["TO_VERSION"] = target.new
    env["DEPENDENCY_ECOSYSTEM"] = ecosystem
    proc = subprocess.run(
        ["bash", str(scan_script)],
        cwd=dest,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    report_path = dest / "malware_scan_report.json"
    if not report_path.is_file():
        return uncovered(target, "not_scanned")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return uncovered(target, "not_scanned")
    if not isinstance(report, dict):
        return uncovered(target, "not_scanned")
    tagged = _tag(target, report)
    if proc.returncode != 0 and tagged.get("status") != "fail":
        tagged["scan_conclusive"] = False
        tagged["not_scanned_reason"] = "scanner_error"
        stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-5:]) if proc.stderr and proc.stderr.strip() else ""
        errors = list(tagged.get("errors") or [])
        if stderr_tail:
            errors.append(stderr_tail)
        tagged["errors"] = errors
    return tagged


def _output_field(value: object) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")


def _emitted_fields(report: dict) -> dict:
    """Outputs follow agent_target. A scan record's own commit is not a second choice."""
    target = report.get("agent_target")
    if not isinstance(target, list) or len(target) != 3:
        return {}
    want = (str(target[0]), str(target[1]), str(target[2]))
    for item in report.get("agent_candidates") or []:
        if isinstance(item, dict) and _identity(item) == want:
            return item
    return {"package_name": want[0], "upstream_repo": want[1], "resolved_to": want[2]}


def _emit(report: dict, summary: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output:
        return
    fields = _emitted_fields(report)
    delim = f"GHEOF_{uuid.uuid4().hex}"
    conclusive = "true" if report.get("scan_conclusive") is True else "false"
    body = summary.rstrip("\n")
    text = (
        f"package_name={_output_field(fields.get('package_name'))}\n"
        f"upstream_repo={_output_field(fields.get('upstream_repo'))}\n"
        f"from_version={_output_field(fields.get('from_version'))}\n"
        f"to_version={_output_field(fields.get('to_version'))}\n"
        f"resolved_from={_output_field(fields.get('resolved_from'))}\n"
        f"resolved_to={_output_field(fields.get('resolved_to'))}\n"
        f"from_tag={_output_field(fields.get('from_tag'))}\n"
        f"to_tag={_output_field(fields.get('to_tag'))}\n"
        f"scan_conclusive={conclusive}\n"
        f"summary<<{delim}\n"
        f"{body}\n"
        f"{delim}\n"
    )
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(text)


def _keep_checkout(records: list[dict], scans: list[tuple[dict, Path]]) -> None:
    target = agent_target(records)
    kept = Path(".upstream-dependency")
    remove_entry(kept)
    if target is None:
        return
    for record, dest in scans:
        if _identity(record) != target:
            continue
        checkout = dest / ".upstream-dependency"
        if checkout.is_dir():
            shutil.move(str(checkout), str(kept))
        return


def _scan_all(
    changes: list[_diff.Change], work: Path, scan_script: Path
) -> tuple[list[dict], list[tuple[dict, Path]], tuple[dict, ...]]:
    """(records, (record, scan directory) per scan, policy warnings the scans found) for the changes to scan.

    Scans run one at a time; the bindings of the covered ones run concurrently once every scan is done.
    """
    records: list[dict] = []
    scans: list[tuple[dict, Path]] = []
    warnings: list[dict] = []
    covered: list[tuple[_diff.Change, Target, dict]] = []
    for index, (change, target, why) in enumerate(_targets(changes)):
        if why:
            records.append(uncovered(target, why))
            continue
        dest = work / str(index)
        dest.mkdir()
        record = _scan_one(target, dest, scan_script, change.ecosystem)
        reason = _ecosystems.unresolved_reason(change.ecosystem, change.old, change.new, record)
        if reason:
            warnings.append(_warning(change, reason))
            continue
        if _covered(record):
            covered.append((change, target, record))
        records.append(record)
        scans.append((record, dest))
    with ThreadPoolExecutor(max_workers=_LOOKUPS) as pool:
        for (_change, target, record), found in zip(covered, pool.map(lambda item: _bind(*item), covered)):
            record["binding"] = found._asdict()
            record["repo_source"] = _binding.repo_source(target.repo.source, found)
    return records, scans, tuple(warnings)


def main() -> None:
    fetch_token = os.environ.pop(FETCH_AUTH_VARIABLE, "")
    scan_script = Path(__file__).resolve().parent / "upstream_malware_scan.sh"
    out = Path(os.environ["DCR_OUT"])
    plan = _plan(fetch_token)
    gaps = plan.gaps if plan else (("pull request diff", "unresolved"),)
    plan = plan or _diff.Plan()
    changes, warnings = _split(plan)
    work = Path(".dcr-dependency-scans")
    remove_entry(work)
    work.mkdir()
    try:
        scanned, scans, found = _scan_all(changes, work, scan_script)
        records = [uncovered(Target(path=path), reason) for path, reason in gaps] + scanned
        unchecked = tuple(change._asdict() for change in plan.unchecked)
        report = aggregate(records, Disclosure(warnings + found, unchecked, plan.unparsed_locks))
        summary = render_summary(report, records)
        _write_report(out, report, summary)
        _keep_checkout(records, scans)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    _emit(report, summary)


if __name__ == "__main__":
    main()
