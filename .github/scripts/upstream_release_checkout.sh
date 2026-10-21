#!/usr/bin/env bash
# Detach .upstream-dependency at the agent target, then strip agent instructions.
# Git history stays in the checkout. An empty target deletes that tree so the
# agent cannot review the default branch; the not_scanned comment still posts.
set -euo pipefail

resolved_to="${RESOLVED_TO:-}"
if [ -z "$resolved_to" ]; then
  rm -rf .upstream-dependency .malware-scan
  exit 0
fi

if ! want="$(git -C .upstream-dependency rev-parse --verify --end-of-options "${resolved_to}^{commit}")"; then
  echo "Failed to resolve upstream release ${resolved_to}." >&2
  exit 1
fi
if ! git -C .upstream-dependency checkout --detach "$want"; then
  echo "Failed to detach .upstream-dependency at ${resolved_to}." >&2
  exit 1
fi
head_sha="$(git -C .upstream-dependency rev-parse HEAD)"
if [ "$head_sha" != "$want" ]; then
  echo "Upstream HEAD ${head_sha} is not resolved_to ${resolved_to} (${want})." >&2
  exit 1
fi

# at-to-ref copies keep real instruction-file names.
rm -rf .malware-scan

root="$(realpath -P -- .upstream-dependency)"

inside_checkout() {
  local path="$1"
  local resolved
  case "$path" in
  .upstream-dependency | .upstream-dependency/*) ;;
  *) return 1 ;;
  esac
  resolved="$(realpath -P -- "$path")" || return 1
  case "$resolved" in
  "$root" | "$root"/*) return 0 ;;
  *) return 1 ;;
  esac
}

# find -P does not descend into symlinked directories. Prune every directory
# named .git so find does not stat the object store of a full clone. Symlink
# hits are unlinked without following. A real path whose realpath leaves the
# checkout fails the step.
strip_matches() {
  local kind="$1"
  shift
  local path
  while IFS= read -r -d '' path; do
    if [ -L "$path" ]; then
      rm -- "$path"
      continue
    fi
    if ! inside_checkout "$path"; then
      echo "Refusing to strip ${path}: realpath leaves .upstream-dependency." >&2
      exit 1
    fi
    if [ "$kind" = dir ]; then
      rm -rf -- "$path"
    else
      rm -f -- "$path"
    fi
  done < <(find -P .upstream-dependency -mindepth 1 '(' -type d -name .git -prune ')' -o "$@")
}

strip_matches dir \
  '(' -type d -o -type l ')' \
  '(' -name .cursor -o -name .agents -o -name .claude -o -name .codex ')' \
  -prune -print0
strip_matches file \
  '(' -type f -o -type l ')' \
  '(' -name AGENTS.md -o -name CLAUDE.md -o -name .cursorrules -o -name .cursorignore ')' \
  -print0
