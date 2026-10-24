#!/usr/bin/env bash
# Prepare what the agent reads, without following a link out of the tree.
#
# The review paths may hold symlinks from the pull request checkout or from
# upstream content. None of .dcr-strip, .upstream-dependency or dcr-scan-input
# may be a link, and dcr-scan-input (the scan prompts and report) may hold only
# regular files; anything else fails the step before anything is read.
#
# .upstream-dependency is then detached at the agent target, every symlink in
# it is deleted, and agent instruction files are stripped. Git history stays in
# the checkout. An empty target deletes that tree so the agent cannot review
# the default branch; the not_scanned comment still posts.
set -euo pipefail

for root in .dcr-strip .upstream-dependency dcr-scan-input; do
  if [ -L "$root" ]; then
    echo "Refusing ${root}: it is a symbolic link." >&2
    exit 1
  fi
done
if [ -e dcr-scan-input ] && {
  [ ! -d dcr-scan-input ] || [ -n "$(find -P dcr-scan-input -mindepth 1 ! -type f -print -quit)" ]
}; then
  echo "Refusing dcr-scan-input: it holds something other than regular files." >&2
  exit 1
fi

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

# find -P never follows a link, so it does not descend into a symlinked
# directory. Prune every directory named .git so find does not stat the object
# store of a full clone. With every link gone, each path left is a real file or
# directory inside the checkout.
find -P .upstream-dependency -mindepth 1 '(' -type d -name .git -prune ')' -o -type l -exec rm -f -- {} +

find -P .upstream-dependency -mindepth 1 '(' -type d -name .git -prune ')' -o \
  '(' -type d '(' -name .cursor -o -name .agents -o -name .claude -o -name .codex ')' -prune -exec rm -rf -- {} + ')' -o \
  '(' -type f '(' -name AGENTS.md -o -name CLAUDE.md -o -name .cursorrules -o -name .cursorignore ')' -exec rm -f -- {} + ')'
