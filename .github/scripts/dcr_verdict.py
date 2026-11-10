from __future__ import annotations

import json
import os
import re
from pathlib import Path

MAX_REASON_CHARS = 300
# The block must sit within this many final non-empty lines; ordinary text may follow it.
END_BLOCK_WINDOW = 10
PREFIXES = ("MALWARE:", "MERGE:", "REASON:")
# Each line must match exactly: no indentation, no trailing whitespace.
END_BLOCK = (
    re.compile(rf"{PREFIXES[0]} (clean|suspicious|malicious)"),
    re.compile(rf"{PREFIXES[1]} (yes|no)"),
    re.compile(PREFIXES[2] + r" (\S(?:.{0," + str(MAX_REASON_CHARS - 2) + r"}\S)?)"),
)
FENCES = ("```", "~~~")
MARKER = "<!-- dcr-artifact-review -->"
TRANSITIVE_NOTE = "Dependencies added transitively and not listed as updates are not artifact-reviewed."
MAX_COMMENT_CHARS = 65536


def parse_end_block(text: str) -> tuple[str, str, str] | None:
    """Return (malware, merge, reason) from the strict end block, or None if it is missing or malformed."""
    lines = [line for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    hits = [i for i, line in enumerate(lines) if line.lstrip(" \t>").startswith(PREFIXES)]
    if len(hits) != 3 or hits[2] - hits[0] != 2:
        return None
    start = hits[0]
    if start < len(lines) - END_BLOCK_WINDOW:
        return None
    if _open_fence(lines[:start]):
        return None
    matches = [pattern.fullmatch(line) for pattern, line in zip(END_BLOCK, lines[start : start + 3])]
    if not all(matches):
        return None
    return (matches[0].group(1), matches[1].group(1), matches[2].group(1))


def _open_fence(lines: list[str]) -> bool:
    return sum(line.lstrip(" \t>").startswith(FENCES) for line in lines) % 2 == 1


def _inline_code(text: str) -> str:
    """Render untrusted one-line text as a code span: no links, mentions, HTML or comments."""
    return "`" + " ".join(text.replace("`", "'").split()) + "`"


def _statuses(updates: tuple[dict[str, object], ...]) -> set[object]:
    return {update.get("status") for update in updates}


def all_updates_not_reviewed(updates: tuple[dict[str, object], ...]) -> bool:
    return bool(updates) and _statuses(updates) == {"not_reviewed"}


def decide(
    meta_ok: bool, updates: tuple[dict[str, object], ...], verdict: str | None, warn_only: bool
) -> tuple[str, str]:
    statuses = _statuses(updates)
    if not meta_ok:
        return ("failure", "metadata is missing or malformed")
    if not statuses <= {"reviewed", "not_reviewed"}:
        return ("failure", "an update was not reviewed to completion")
    if not updates:
        return ("failure", "the PR listed no updates")
    if all_updates_not_reviewed(updates):
        return ("success", "all updates are not reviewed (outside the reviewed ecosystems)")
    if verdict is None:
        return ("failure", "the end block is missing or malformed")
    if verdict == "malicious":
        return ("failure", "the agent verdict is malicious")
    if verdict == "suspicious" and not warn_only:
        return ("failure", "the agent verdict is suspicious")
    suffix = " (warn only)" if verdict == "suspicious" else ""
    return ("success", f"the agent verdict is {verdict}{suffix}")


def verdicts(
    updates: tuple[dict[str, object], ...], block: tuple[str, str, str] | None, conclusion: str
) -> tuple[str, str]:
    if conclusion == "success" and all_updates_not_reviewed(updates):
        return ("not reviewed", "not reviewed")
    if block is None:
        return ("unknown", "no")
    return (block[0], block[1] if conclusion == "success" and block[0] == "clean" else "no")


def _update_line(update: dict[str, object]) -> str:
    name, old, new = (update.get(key, "") for key in ("name", "prev_version", "new_version"))
    note = update.get("note")
    line = f"- `{name}` {old} -> {new}: {update.get('status', 'unknown')}"
    return line + (f" - {note}" if isinstance(note, str) and note else "")


def _message_body(
    updates: tuple[dict[str, object], ...], decision: tuple[str, str], facts: tuple[str, ...] = (), reason: str = ""
) -> str:
    parts = [MARKER, "## Dependency Artifact Review"]
    parts.append(f"**Result:** {decision[0]}\n**Reason:** {decision[1]}")
    if reason:
        parts.append(f"**Agent reason:** {_inline_code(reason)}")
    if updates:
        parts.append("### Updates\n" + "\n".join(map(_update_line, updates)))
    if facts:
        parts.append("### Facts\n" + "\n".join(f"- {fact}" for fact in facts))
    parts.append(TRANSITIVE_NOTE)
    return "\n\n".join(parts)


def comment_body(
    updates: tuple[dict[str, object], ...],
    decision: tuple[str, str],
    agent_text: str,
    malware_verdict: str,
    merge: str,
    facts: tuple[str, ...] = (),
    reason: str = "",
) -> str:
    head = _message_body(updates, decision, facts, reason)
    verdict_line = f"**Verdict:** Malware: {malware_verdict} | Merge: {merge}"
    tail = f"\n\n{verdict_line}\n"
    head_note = "\n\n[... truncated]"
    if len(head) + len(tail) > MAX_COMMENT_CHARS:
        head = head[: MAX_COMMENT_CHARS - len(tail) - len(head_note)] + head_note
    if not agent_text:
        return head + tail

    open_details = "\n\n<details>\n<summary>Agent review</summary>\n\n"
    close_details = "\n\n</details>"
    close_fence = "\n```"
    note = "\n\n[agent output truncated]"
    budget = MAX_COMMENT_CHARS - len(head) - len(open_details) - len(close_details) - len(tail) - len(close_fence)
    truncated = len(agent_text) > budget
    if truncated:
        if budget <= len(note):
            return head + tail
        agent_text = agent_text[: budget - len(note)]
    if _open_fence(agent_text.splitlines()):
        agent_text += close_fence
    if truncated:
        agent_text += note
    return head + open_details + agent_text + close_details + tail


def main() -> int:
    try:
        meta = json.loads(Path(os.environ.get("DCR_META", "meta.json")).read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        meta = None
    updates = meta.get("updates") if isinstance(meta, dict) else None
    if not isinstance(updates, list) or not all(isinstance(item, dict) for item in updates):
        updates = None
    facts = meta.get("facts") if isinstance(meta, dict) else None
    facts = tuple(f for f in facts if isinstance(f, str)) if isinstance(facts, list) else ()
    try:
        agent = Path(os.environ.get("DCR_AGENT_OUTPUT", "agent_output.txt")).read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        agent = ""
    warn_only = os.environ.get("MALWARE_WARN_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}
    items = tuple(updates or ())
    block = parse_end_block(agent)
    decision = decide(updates is not None, items, block[0] if block else None, warn_only)
    malware, merge = verdicts(items, block, decision[0])
    reason = block[2] if block else ""
    comment = os.environ.get("DCR_COMMENT", "comment.md")
    body = comment_body(items, decision, agent, malware, merge, facts, reason)
    Path(comment).write_text(body, encoding="utf-8")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"conclusion={decision[0]}\n")
    print(f"conclusion={decision[0]}\nreason={decision[1]}\nmalware={malware}\nmerge={merge}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
