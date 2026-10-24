"""Merge Cursor malware + compatibility JSON outputs; format the malware verdict.

The verdict job passes DCR_SCAN_REPORT and MALWARE_SCAN_REPORT_SHA256 from the
scan job. Combine reads that report and exits unless hashlib.sha256 matches.
Agent JSON is untrusted data read from DCR_MALWARE_JSON and DCR_COMPAT_JSON.
main and --enforce-check load the same inputs and reach the same decide().
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import malware_verdict_formatter as formatter

_REPORT_SHA256_ENV = "MALWARE_SCAN_REPORT_SHA256"
_WARN_ONLY_ENV = "MALWARE_WARN_ONLY"
_TEXT_KEYS = ("result", "output", "text", "message")
_FAILED_PREFIXES = ("Error: agent exited", "CURSOR_API_KEY is not set", "No Cursor output generated")


class _AgentOutput(NamedTuple):
    text: str  # the concatenated result, or a readable dump of whatever was written
    final: str  # the final assistant message, written separately from the result
    ok: bool  # a successful, non-empty analysis


def _extract_text(payload: object) -> str:
    if isinstance(payload, dict):
        for key in _TEXT_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    try:
        return json.dumps(payload, indent=2)
    except (TypeError, ValueError):
        return str(payload)


def _final_message(payload: object) -> str:
    value = payload.get("final_message") if isinstance(payload, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _succeeded(payload: object) -> bool:
    if not isinstance(payload, dict) or payload.get("error") or payload.get("is_error") is True:
        return False
    if payload.get("complete") is False:
        return False
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and not value.startswith("Missing output file:"):
            return not value.startswith(_FAILED_PREFIXES)
    return False


def _agent_output(path: Path) -> _AgentOutput:
    """One agent JSON file. Missing or unparsable output is never a successful analysis."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _AgentOutput(f"Missing output file: {path}", "", ok=False)
    try:
        payload = json.loads(raw)
    except ValueError:
        return _AgentOutput(raw, "", ok=False)
    return _AgentOutput(_extract_text(payload), _final_message(payload), ok=_succeeded(payload))


def _fail_closed(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def _digest_is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _env_path(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        _fail_closed(f"{name} is missing.")
    return Path(value)


def _sealed_report() -> object:
    """Fail closed unless the scan-job digest matches DCR_SCAN_REPORT."""
    expected = os.environ.get(_REPORT_SHA256_ENV, "").strip()
    if not _digest_is_sha256(expected):
        _fail_closed("Malware scan report digest is missing.")
    path = _env_path("DCR_SCAN_REPORT")
    try:
        data = path.read_bytes()
    except OSError:
        _fail_closed("Malware scan report is missing.")
    if hashlib.sha256(data).hexdigest() != expected:
        _fail_closed("Malware scan report digest mismatch.")
    try:
        report = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _warn_only() -> bool:
    """The one read of MALWARE_WARN_ONLY, a policy input to decide(). Unset keeps the fleet default, warn-only."""
    return os.environ.get(_WARN_ONLY_ENV, "").strip() not in {"0", "false", "False", "no"}


class _Inputs(NamedTuple):
    malware: _AgentOutput
    compatibility: _AgentOutput
    published: dict[str, object]


def _load_and_decide() -> _Inputs:
    """The one loader. A skipped agent leaves its file absent, which can only block."""
    report = _sealed_report()
    malware = _agent_output(_env_path("DCR_MALWARE_JSON"))
    compatibility = _agent_output(_env_path("DCR_COMPAT_JSON"))
    published = formatter.compose_published_review(
        report,
        malware.text,
        compatibility.final or compatibility.text,
        agent_final_text=malware.final or malware.text,
        warn_only=_warn_only(),
    )
    return _Inputs(malware, compatibility, published)


def main() -> None:
    combined_path = _env_path("DCR_COMBINED_JSON")
    malware, compatibility, published = _load_and_decide()
    malware_text = published["malware_text"]
    compatibility_text = published["compatibility_text"]
    # The patch-id marker is stamped only for a complete review whose decision passed.
    complete = malware.ok and compatibility.ok and published["may_complete"] is True
    sections = (
        f"## Supply-Chain Malware Review\n\n{malware_text}",
        f"## Compatibility Analysis\n\n{compatibility_text}",
    )
    combined = {
        "result": "\n\n".join(sections),
        "complete": complete,
        "check": published["check"],
        "malware_review": {"result": malware_text},
        "compatibility_review": {"result": compatibility_text},
    }
    combined_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")


def _enforce_published_check() -> None:
    """Recompute the decision from the sealed inputs. A stored check string is ignored."""
    if _load_and_decide().published["check"] != formatter.PASS:
        _fail_closed("Dependency review did not pass.")


if __name__ == "__main__":
    if "--enforce-check" in sys.argv:
        _enforce_published_check()
    else:
        main()
