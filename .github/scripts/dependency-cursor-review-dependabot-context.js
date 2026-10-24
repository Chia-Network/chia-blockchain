'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// The review marker is produced once, here, and passed through as that single line.

const LEGACY_REVIEW_MARKER = '<!-- cursor-dependabot-review -->';
const ACTIONS_BOT_LOGIN = 'github-actions[bot]';

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// [start, end) of each top-level <details> block. An unclosed block runs to the end.
function detailsSpans(text) {
  const tagRe = /<details\b[^>]*>|<\/details>/gi;
  const spans = [];
  let depth = 0;
  let start = 0;
  let tag;
  while ((tag = tagRe.exec(text)) !== null) {
    const opens = tag[0].toLowerCase().startsWith('<details');
    if (!opens && depth === 0) continue; // a close with no open block hides nothing
    if (opens && depth === 0) start = tag.index;
    depth += opens ? 1 : -1;
    if (!opens && depth === 0) spans.push([start, tagRe.lastIndex, true]);
  }
  if (depth > 0) spans.push([start, text.length, false]);
  return spans;
}

function extractDetailsSection(text, summaryLabel) {
  const summaryRe = new RegExp(`^<details[^>]*>\\s*<summary>\\s*${escapeRegex(summaryLabel)}[^<]*</summary>`, 'i');
  for (const [start, end, closed] of detailsSpans(text)) {
    const block = text.slice(start, end);
    if (closed && summaryRe.test(block)) {
      return block
        .replace(summaryRe, '')
        .replace(/<\/details>\s*$/i, '')
        .trim();
    }
  }
  return '';
}

// Release notes and commits from the PR body, passed to the prompt as data.
// Package names and versions come from the manifest diff, never from this text.
function bodyNotes(body) {
  let releaseNotes = extractDetailsSection(body, 'Release notes');
  if (!releaseNotes) {
    const rnHeading = body.match(/###\s*Release\s+Notes?\s*\n([\s\S]*?)(?=\n---|\n###\s|$)/i);
    if (rnHeading) releaseNotes = rnHeading[1].trim();
  }

  let commits = extractDetailsSection(body, 'Commits');
  if (!commits) {
    const shaMatches = body.match(/\b[0-9a-f]{7,40}\b/gi);
    if (shaMatches && shaMatches.length > 0) commits = shaMatches.join('\n');
  }
  return { releaseNotes, commits };
}

// Above a normal GitHub pull-request diff. Larger inputs fail open.
const MAX_DIFF_CHARS = 5000000;

/**
 * Stable id of one unified diff. A multi-commit series (more than one id
 * line) and any git failure return '' so the review runs.
 */
function patchIdFromDiff(diffText) {
  if (typeof diffText !== 'string' || !diffText.trim() || diffText.length > MAX_DIFF_CHARS) return '';
  let result;
  try {
    result = spawnSync('git', ['patch-id', '--stable'], { input: diffText, encoding: 'utf8' });
  } catch (_) {
    return '';
  }
  if (!result || result.error || result.status !== 0) return '';
  const lines = String(result.stdout || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length !== 1) return '';
  const match = lines[0].match(/^([0-9a-f]{40})\s+[0-9a-f]{40}$/);
  return match ? match[1] : '';
}

function reviewMarkerFromPatchId(patchId, resolvedSha) {
  if (typeof patchId !== 'string' || !/^[0-9a-f]{40}$/.test(patchId)) return '';
  if (typeof resolvedSha !== 'string' || !/^[0-9a-f]{40}$/.test(resolvedSha)) return '';
  return `<!-- cursor-dependabot-review patch-id:${patchId} resolved:${resolvedSha} -->`;
}

const RELEASE_REVIEW_MARKER_RE = /^<!-- cursor-dependabot-review patch-id:([0-9a-f]{40}) resolved:([0-9a-f]{40}) -->$/;

function reviewedShasForPatch(comments, patchId) {
  if (typeof patchId !== 'string' || !/^[0-9a-f]{40}$/.test(patchId)) return [];
  if (!Array.isArray(comments)) return [];
  const shas = [];
  for (const comment of comments) {
    if (comment?.user?.login !== ACTIONS_BOT_LOGIN) continue;
    const match = RELEASE_REVIEW_MARKER_RE.exec(commentFirstLine(comment.body));
    if (match && match[1] === patchId) shas.push(match[2]);
  }
  return shas;
}

/**
 * The one skip rule, for single and grouped pull requests alike. reviewedShas
 * come from reviewedShasForPatch(comments, patchId). Skip only when this
 * patch-id and this resolved commit form a valid marker and a bot marker for
 * that patch-id names that commit. Anything else reviews again.
 */
function skipApplies(reviewedShas, patchId, resolvedSha) {
  if (!reviewMarkerFromPatchId(patchId, resolvedSha)) return false;
  return Array.isArray(reviewedShas) && reviewedShas.includes(resolvedSha);
}

/**
 * The scan job's bind_review step. Inputs are that step's env values: the
 * patch-id, the comma-joined reviewed SHAs and the resolved release commit.
 * Returns the step outputs.
 */
function bindReviewOutputs({ PATCH_ID, REVIEWED_SHAS, RESOLVED_TO }) {
  const patchId = PATCH_ID || '';
  const resolved = RESOLVED_TO || '';
  const reviewed = (REVIEWED_SHAS || '').split(',').filter(Boolean);
  return {
    review_marker: reviewMarkerFromPatchId(patchId, resolved),
    already_reviewed: skipApplies(reviewed, patchId, resolved) ? 'true' : 'false',
  };
}

function commentFirstLine(body) {
  if (typeof body !== 'string') return '';
  const end = body.indexOf('\n');
  return (end === -1 ? body : body.slice(0, end)).trim();
}

function isActionsBotMarkerComment(comment) {
  if (comment?.user?.login !== ACTIONS_BOT_LOGIN) return false;
  const line = commentFirstLine(comment.body);
  if (line === LEGACY_REVIEW_MARKER) return true;
  return /^<!-- cursor-dependabot-review patch-id:[0-9a-f]{40}(?: resolved:[0-9a-f]{40})? -->$/.test(line);
}

async function runDependabotContext() {
  const outDir = process.env.DCR_OUT;
  if (!outDir) throw new Error('DCR_OUT is not set.');
  const write = (name, text) => fs.writeFileSync(path.join(outDir, name), text);
  const parsed = bodyNotes(process.env.PR_BODY || '');
  const releaseNotes = parsed.releaseNotes || 'PR body did not include a Release notes details section.';
  const commits = parsed.commits || 'PR body did not include a Commits details section.';
  const out = { prNumber: Number(process.env.PR_NUMBER || '0'), releaseNotes, commits };
  write('dependabot_comment_context.json', JSON.stringify(out, null, 2));
  write('dependabot_release_notes.md', releaseNotes);
  write('dependabot_commits.md', commits);
}

module.exports = runDependabotContext;
module.exports.bodyNotes = bodyNotes;
module.exports.MAX_DIFF_CHARS = MAX_DIFF_CHARS;
module.exports.patchIdFromDiff = patchIdFromDiff;
module.exports.reviewMarkerFromPatchId = reviewMarkerFromPatchId;
module.exports.reviewedShasForPatch = reviewedShasForPatch;
module.exports.skipApplies = skipApplies;
module.exports.bindReviewOutputs = bindReviewOutputs;
module.exports.isActionsBotMarkerComment = isActionsBotMarkerComment;
module.exports.LEGACY_REVIEW_MARKER = LEGACY_REVIEW_MARKER;
