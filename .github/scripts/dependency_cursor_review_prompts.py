"""Build Cursor agent prompt files for dependency-cursor-review (malware + compatibility)."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}\Z")


def _out_dir() -> Path:
    return Path(os.environ["DCR_OUT"])


def _read_file(name: str) -> str:
    try:
        return (_out_dir() / name).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _shown_sha(value: str) -> str:
    text = value.strip()
    return text if _SHA_RE.fullmatch(text) else "(unresolved)"


def _shown_version(value: str) -> str:
    text = value.strip()
    return text if text else "(none)"


def _layout_tag_line(label: str, token: str) -> str:
    return f"- {label}: (none) dcr-slot-{token}"


def _empty_fields() -> dict[str, str]:
    return {
        "package": "",
        "from_version": "",
        "to_version": "",
        "resolved_from": "",
        "resolved_to": "",
    }


def _fields_for_target(report: dict) -> dict[str, str]:
    """Read the stored agent_target. Do not reselect a package."""
    target = report.get("agent_target")
    if not isinstance(target, list) or len(target) != 3:
        return _empty_fields()
    package, repo, resolved_to = (str(target[0]), str(target[1]), str(target[2]))
    chosen: dict = {}
    raw = report.get("agent_candidates")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("package_name") or "") == package
                and str(item.get("upstream_repo") or "") == repo
                and str(item.get("resolved_to") or "") == resolved_to
            ):
                chosen = item
                break
    return {
        "package": package,
        "from_version": str(chosen.get("from_version") or ""),
        "to_version": str(chosen.get("to_version") or ""),
        "resolved_from": str(chosen.get("resolved_from") or ""),
        "resolved_to": resolved_to,
    }


def _prompt_fields() -> dict[str, str]:
    """Package and commit come from the scan's agent_target when that key is present."""
    env_fields = {
        "package": os.getenv("PACKAGE_NAME", ""),
        "from_version": os.getenv("FROM_VERSION", ""),
        "to_version": os.getenv("TO_VERSION", ""),
        "resolved_from": os.getenv("RESOLVED_FROM", ""),
        "resolved_to": os.getenv("RESOLVED_TO", ""),
    }
    try:
        report = json.loads((_out_dir() / "malware_scan_report.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return env_fields
    if not isinstance(report, dict) or "agent_target" not in report:
        return env_fields
    return _fields_for_target(report)


def _upstream_layout(token: str, fields: dict[str, str]) -> str:
    from_sha = _shown_sha(fields["resolved_from"])
    to_sha = _shown_sha(fields["resolved_to"])
    lines = [
        "Repository layout:",
        "- Current repository root: .",
        "- Upstream dependency repository: .upstream-dependency",
        "- HEAD and refs/dcr/to are the to commit when that commit was fetched.",
        "- refs/dcr/from is the from commit when that commit was fetched. It is not a second worktree.",
        "- Only those two commits and the version tags named below are fetched.",
        "- Intermediate commits were not fetched. Compare the trees with git diff, not git log.",
        f"- from version: {_shown_version(fields['from_version'])}",
        _layout_tag_line("from tag", token),
        f"- from commit: {from_sha}",
        f"- to version: {_shown_version(fields['to_version'])}",
        _layout_tag_line("to tag", token),
        f"- to commit: {to_sha}",
    ]
    if from_sha != "(unresolved)" and to_sha != "(unresolved)":
        lines.append(f"- From-to comparison: git -C .upstream-dependency diff {from_sha} {to_sha}")
    lines.append("- Read a named tag with git -C .upstream-dependency show <tag> when its line is not (none).")
    lines.append(
        "- If .upstream-dependency is absent, the release commit was not checked out "
        "(status not_scanned). Do not search for another tree and do not review a default-branch checkout."
    )
    return "\n".join(lines)


def _base_context(token: str, fields: dict[str, str]) -> str:
    return f"""
This is a dependency bot PR review request.

PR title:
{os.getenv("PR_TITLE", "")}

PR body:
{os.getenv("PR_BODY", "")}

Package metadata:
- package: {fields["package"]}
- from: {fields["from_version"]}
- to: {fields["to_version"]}

PR context JSON:
{_read_file("dependabot_comment_context.json")}

Release notes:
{_read_file("dependabot_release_notes.md")}

Commits:
{_read_file("dependabot_commits.md")}

Local usage hints (non-authoritative rg hits):
{_read_file("package_usage.txt")[:12000]}

{_upstream_layout(token, fields)}
""".strip()


_MALWARE_TASK = """
Task 1: Supply-chain malware review.
Review the dependency update for signs of compromise. Use this checklist and explicitly consider each category:

### Classic obfuscation
- Obfuscated code (base64, exec, eval, XOR, encoded strings)
- Network calls to unexpected hosts (non-package-related URLs)
- File system writes to startup/persistence locations
- Process spawning, shell commands
- Steganography or data hiding in media files
- Credential/token exfiltration
- Typosquatting indicators
- Suspicious npm lifecycle scripts (preinstall, install, postinstall) in package.json
- Dynamic require() or import() of obfuscated or encoded URLs
- Minified or bundled payloads added outside normal build artifacts

### Invisible Unicode / GlassWorm technique
This class of attack can appear blank in rendered code review. Flag:
- Unicode Private Use Area characters (U+E0100\u2013U+E01EF)
- Zero-width characters (U+200B, U+200C)
- A byte-order mark (U+FEFF) embedded inside a token rather than after whitespace
- Hangul filler characters (U+3164, U+115F, U+1160)
- Bidi control characters (U+202A\u2013U+202E, U+2066\u2013U+2069, Trojan Source)
- Homoglyph substitutions in operators/identifiers (e.g. \uff0f, \u2217, \u01c3)
- Strings that look empty in diff but have non-zero bytes
- eval()/Function() receiving visually blank strings
- Decoder patterns using codePointAt()/fromCodePoint()/charCodeAt() for hidden payload assembly
- Commit metadata consistency anomalies suggesting force-push/rewrite concealment

Variation selectors (U+FE00\u2013U+FE0F) and the zero-width joiner (U+200D) are normal emoji
rendering. They are not evidence on their own. Binary and media blobs (images, archives,
wheels) are not text; a codepoint match there is byte coincidence, not a hidden glyph.

### Dependency integrity
- Unexpected new transitive dependencies vs prior dependency graph
- Known-safe packages with sudden dependency count increase (e.g., axios expected dependency count)
- Lock file hashes/checksums inconsistent with expected integrity formats or release metadata
- Version jumps skipping many semver minors, or ghost versions missing corresponding tags/releases
- Maintainer/publisher identity drift from historical account patterns

### Dependabot-specific context
- Focus on files changed in node_modules/, vendor/, and dependency/lock manifests (package-lock.json, yarn.lock, \
pnpm-lock.yaml, Gemfile.lock, go.sum, Cargo.toml, Cargo.lock, .cargo/config.toml, .cargo/config, pyproject.toml, \
poetry.lock, Pipfile.lock, requirements.txt, requirements-dev.txt, requirements/*.txt, etc.)
- Flag new transitive dependencies introduced alongside the direct update
- Flag new preinstall/postinstall scripts that were not present previously
- Treat .github/workflows/ modifications in the PR under review as highly suspicious in a pure dependency update PR. \
Upstream release workflow files are not executed by this repository; a path-touch finding there is context unless the \
workflow content itself adds a payload.
- Unchanged or removed submodule pointers are recorded in the report and their contents are not scanned. \
An added or moved submodule pointer is reported as unread with cause "submodule changed".

IOC matches, and Unicode or confusable-character findings in files changed by this update, are blocking. \
Do not clear them.
Pre-existing Unicode or confusable findings in unchanged release files are context for this update, \
not a reason to block.
Codepoint matches in binary or media blobs are not text findings and are context for this update.
A changed media path is still a steganography signal.
You may only agree with blocking findings or escalate them.
Generic exec, spawn, child_process, base64, and eval hits are context, including inside compiled
bundles. Other heuristic hits are blocking.
status clean with scan_conclusive true means release blobs were read and no findings were produced.
status warn or fail means findings were produced from blobs that were read. Incorporate them.
If scan_conclusive is false, coverage was incomplete, so do not treat the absence of further findings as a clean result.
status not_scanned means coverage was incomplete and no content findings were produced from release blobs.
An empty findings list with that status is not evidence the package is benign.
If scanner findings and your interpretation disagree, call that out explicitly.

Your response MUST start with exactly one machine-readable verdict line.
That line must be the first non-empty line, with no leading whitespace, not inside a code fence,
and not inside quotation marks:
MALWARE_REVIEW_VERDICT: malicious
or:
MALWARE_REVIEW_VERDICT: suspicious
or:
MALWARE_REVIEW_VERDICT: benign
Emit that line once, only as that first line. A later copy, a duplicate, or a quoted copy is not a
verdict. Do not indent it, quote it, bold it, or wrap it in backticks.
Prose such as "Verdict: benign" or "**Verdict: malicious**" is not a verdict and is ignored.
suspicious is accepted only when you also cite evidence, one finding per line:
EVIDENCE: path/file.js:123: why this line is a problem
benign and malicious do not need EVIDENCE lines.
Then explain your reasoning briefly with top evidence.
Do not include intermediate reasoning or self-talk.
Keep it concise and actionable.
""".strip()


def main() -> None:
    base = _base_context(secrets.token_hex(16), _prompt_fields())
    malware_context = f"""
{base}

Malware scan summary:
{_read_file("malware_scan_summary.md")}

Malware scan report JSON:
{_read_file("malware_scan_report.json")[:16000]}
""".strip()

    malware_prompt = f"{malware_context}\n\n{_MALWARE_TASK}"

    compatibility_prompt = f"""
{base}

Task 2: Compatibility and adoption analysis.
1) Where in this repo the dependency appears to be used (treat rg hints as directional, not exhaustive).
2) Whether those usage sites intersect with likely changed APIs based on release notes and direct inspection \
of the from and to commits named above. Use the git diff of those two SHAs. Read a version tag only when one is \
named. Do not treat missing intermediate history as an empty change list.
3) Risks / unknowns for runtime/build compatibility.
4) End with exactly one recommendation line, once, with the reasons above it or below it:
COMPATIBILITY_RECOMMENDATION: Merge
or:
COMPATIBILITY_RECOMMENDATION: Don't merge
A missing or repeated recommendation line is published as Don't merge.
Do not include intermediate reasoning or self-talk.
Keep it concise and actionable.
""".strip()

    (_out_dir() / "cursor_prompt_malware.txt").write_text(malware_prompt, encoding="utf-8")
    (_out_dir() / "cursor_prompt_compatibility.txt").write_text(compatibility_prompt, encoding="utf-8")


if __name__ == "__main__":
    main()
