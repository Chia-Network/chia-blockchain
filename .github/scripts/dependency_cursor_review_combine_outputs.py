"""Merge Cursor malware + compatibility JSON outputs; format malware verdict via trusted loader.

The verdict job passes DCR_SCAN_REPORT and MALWARE_SCAN_REPORT_SHA256 from the
scan job. Combine reads that report and exits unless hashlib.sha256 matches.
Agent JSON is untrusted data read from DCR_MALWARE_JSON and DCR_COMPAT_JSON.
"""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

_INSTALL = Path(__file__).resolve().parent
# The running script's directory is the trusted checkout (runner temp). Prefer it
# over the PR workspace .github/scripts so a PR-head formatter cannot win.
_SCRIPT_CANDIDATES = (
    _INSTALL,
    Path(".github/scripts"),
    Path("internal/workflowscripts"),
)
_COLD_START_PATH = _INSTALL / "trusted_formatter_loader_cold_start.py"


def _drop_pr_head_scripts_from_sys_path() -> None:
    """Keep the PR checkout's .github/scripts off sys.path.

    Trusted modules load by file path from this script's directory. A PR-head
    directory on sys.path can shadow stdlib (dataclasses, json) in the step
    that has CURSOR_API_KEY.
    """
    workspace_scripts = (Path.cwd() / ".github" / "scripts").resolve()
    if workspace_scripts == _INSTALL.resolve():
        return
    kept: list[str] = []
    for entry in sys.path:
        if not entry:
            kept.append(entry)
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            kept.append(entry)
            continue
        if resolved == workspace_scripts:
            continue
        kept.append(entry)
    sys.path[:] = kept


def _host_namespace() -> dict[str, object]:
    """Canonical python3 -I host entry (no sibling imports)."""
    return runpy.run_path(str(_COLD_START_PATH))


def _load_any(path: str) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"result": f"Missing output file: {path}"}
    try:
        return json.loads(raw)
    except Exception:
        return {"result": raw}


def _successful_analysis_text(path: str) -> str:
    """Non-empty analysis text from a successful agent JSON result, or ''."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    if not raw.strip():
        return ""
    try:
        payload = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(payload, dict) or payload.get("error") or payload.get("is_error") is True:
        return ""
    if payload.get("complete") is False:
        return ""
    for key in ("result", "output", "text", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and not value.startswith("Missing output file:"):
            if value.startswith(("Error: agent exited", "CURSOR_API_KEY is not set", "No Cursor output generated")):
                return ""
            return value.strip()
    return ""


def _extract_text(payload) -> str:
    if not isinstance(payload, dict):
        try:
            return json.dumps(payload, indent=2)
        except Exception:
            return str(payload)
    for key in ("result", "output", "text", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    try:
        return json.dumps(payload, indent=2)
    except Exception:
        return str(payload)


# Fixed text. Agent prose is not published on this path, so it cannot carry a verdict banner.
_TRUSTED_INCONCLUSIVE = "**Verdict: inconclusive (needs human review)**"
_TRUSTED_COMPAT = "Compatibility analysis withheld because the malware scan did not pass."
_REPORT_SHA256_ENV = "MALWARE_SCAN_REPORT_SHA256"


def _report_allows_agent_verdict(data: bytes) -> bool:
    """Trust the agent only for a conclusive clean scan with no findings."""
    try:
        report = json.loads(data.decode("utf-8"))
    except Exception:
        return False
    if not isinstance(report, dict):
        return False
    findings = report.get("findings")
    if isinstance(findings, dict):
        findings_present = any(findings.values())
    else:
        findings_present = bool(findings)
    return (
        report.get("status") == "clean"
        and report.get("scan_conclusive") is True
        and report.get("verdict_token_in_tree") is not True
        and not findings_present
    )


def _fail_closed(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def _digest_is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _env_path(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        _fail_closed(f"{name} is missing.")
    return Path(value)


def _scan_allows_agent() -> bool:
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
    return _report_allows_agent_verdict(data)


def main() -> None:
    _drop_pr_head_scripts_from_sys_path()
    # Check the sealed report before loading any sibling module.
    blocked = not _scan_allows_agent()
    malware_path = str(_env_path("DCR_MALWARE_JSON"))
    compatibility_path = str(_env_path("DCR_COMPAT_JSON"))
    combined_path = _env_path("DCR_COMBINED_JSON")
    if blocked:
        malware_text = _TRUSTED_INCONCLUSIVE
        compatibility_text = _TRUSTED_COMPAT
        complete = False
        malware_review = {"result": malware_text}
        compatibility_review = {"result": compatibility_text}
    else:
        malware_payload = _load_any(malware_path)
        compatibility_payload = _load_any(compatibility_path)
        ns = _host_namespace()
        resolve_loader_bundle = ns["resolve_loader_bundle"]
        loader, script_dir = resolve_loader_bundle(_SCRIPT_CANDIDATES)
        format_malware_review_verdict = loader.find_and_load_format_malware_review_verdict(script_dir)
        malware_text = format_malware_review_verdict(_extract_text(malware_payload))
        compatibility_text = _extract_text(compatibility_payload)
        complete = bool(_successful_analysis_text(malware_path)) and bool(_successful_analysis_text(compatibility_path))
        malware_review = malware_payload
        compatibility_review = compatibility_payload

    combined_text = (
        f"## Supply-Chain Malware Review\n\n{malware_text}\n\n## Compatibility Analysis\n\n{compatibility_text}"
    )
    combined = {
        "result": combined_text,
        "complete": complete,
        "malware_review": malware_review,
        "compatibility_review": compatibility_review,
    }
    combined_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
