"""Merge Cursor malware + compatibility JSON outputs; format malware verdict via trusted loader."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

_INSTALL = Path(__file__).resolve().parent
_SCRIPT_CANDIDATES = (
    Path(".github/scripts"),
    Path("internal/workflowscripts"),
)
_COLD_START_PATH = _INSTALL / "trusted_formatter_loader_cold_start.py"


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
    for key in ("result", "output", "text", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and not value.startswith("Missing output file:"):
            if value.startswith("Error: agent exited"):
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


def main() -> None:
    ns = _host_namespace()
    resolve_loader_bundle = ns["resolve_loader_bundle"]
    loader, script_dir = resolve_loader_bundle(_SCRIPT_CANDIDATES)
    format_malware_review_verdict = loader.find_and_load_format_malware_review_verdict(script_dir)

    malware_payload = _load_any("cursor_output_malware.json")
    compatibility_payload = _load_any("cursor_output_compatibility.json")
    malware_text = format_malware_review_verdict(_extract_text(malware_payload))
    compatibility_text = _extract_text(compatibility_payload)

    combined_text = (
        f"## Supply-Chain Malware Review\n\n{malware_text}\n\n## Compatibility Analysis\n\n{compatibility_text}"
    )
    # complete is true only when both agent files were real analyses.
    # The post step stamps the skip marker only if this combined review
    # was written (complete, both section headings) and analysis succeeded.
    combined = {
        "result": combined_text,
        "complete": bool(_successful_analysis_text("cursor_output_malware.json"))
        and bool(_successful_analysis_text("cursor_output_compatibility.json")),
        "malware_review": malware_payload,
        "compatibility_review": compatibility_payload,
    }
    Path("cursor_output.json").write_text(json.dumps(combined, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
