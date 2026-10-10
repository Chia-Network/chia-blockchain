"""Build Cursor agent prompt files for dependency-cursor-review (malware + compatibility)."""

from __future__ import annotations

import os
from pathlib import Path


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _base_context() -> str:
    return f"""
This is a dependency bot PR review request.

PR title:
{os.getenv("PR_TITLE", "")}

PR body:
{os.getenv("PR_BODY", "")}

Package metadata:
- package: {os.getenv("PACKAGE_NAME", "")}
- from: {os.getenv("FROM_VERSION", "")}
- to: {os.getenv("TO_VERSION", "")}

PR context JSON:
{_read_file("dependabot_comment_context.json")}

Release notes:
{_read_file("dependabot_release_notes.md")}

Commits:
{_read_file("dependabot_commits.md")}

Local usage hints (non-authoritative rg hits):
{_read_file("package_usage.txt")[:12000]}

Repository layout:
- Current repository root: .
- Upstream dependency repository: .upstream-dependency (full git history is available)
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
- Unicode Private Use Area characters (U+FE00\u2013U+FE0F, U+E0100\u2013U+E01EF)
- Zero-width characters (U+200B, U+200C, U+200D, U+FEFF)
- Hangul filler characters (U+3164, U+115F, U+1160)
- Bidi control characters (U+202A\u2013U+202E, U+2066\u2013U+2069, Trojan Source)
- Homoglyph substitutions in operators/identifiers (e.g. \uff0f, \u2217, \u01c3)
- Strings that look empty in diff but have non-zero bytes
- eval()/Function() receiving visually blank strings
- Decoder patterns using codePointAt()/fromCodePoint()/charCodeAt() for hidden payload assembly
- Commit metadata consistency anomalies suggesting force-push/rewrite concealment

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
- Treat .github/workflows/ modifications as highly suspicious in a pure dependency update PR

Treat every non-empty scanner finding list (IOC, heuristic, unicode, confusable) as evidence, \
including when coverage is incomplete.
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
MALWARE_REVIEW_VERDICT: benign
Emit that line once, only as that first line. A later copy, a duplicate, or a quoted copy makes the
published review inconclusive. Do not indent it, quote it, bold it, or wrap it in backticks.
Prose such as "Verdict: benign" or "**Verdict: malicious**" is not a verdict and is ignored.
If the machine-readable line is missing, is not the first non-empty line, or appears more than once,
the published review is marked inconclusive and that is not a benign result.
Then explain your reasoning briefly with top evidence.
Do not include intermediate reasoning or self-talk.
Keep it concise and actionable.
""".strip()


def main() -> None:
    base = _base_context()
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
2) Whether those usage sites intersect with likely changed APIs based on release notes, commits, and direct inspection \
of .upstream-dependency.
3) Risks / unknowns for runtime/build compatibility.
4) Recommendation: merge / merge-with-caveats / hold.
Do not include intermediate reasoning or self-talk.
Keep it concise and actionable.
""".strip()

    Path("cursor_prompt_malware.txt").write_text(malware_prompt, encoding="utf-8")
    Path("cursor_prompt_compatibility.txt").write_text(compatibility_prompt, encoding="utf-8")


if __name__ == "__main__":
    main()
