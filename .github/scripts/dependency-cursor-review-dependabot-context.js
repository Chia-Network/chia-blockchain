'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');

// The review marker is produced once, here, and passed through as that single line.

const LEGACY_REVIEW_MARKER = '<!-- cursor-dependabot-review -->';
const ACTIONS_BOT_LOGIN = 'github-actions[bot]';

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function extractDetailsSection(text, summaryLabel) {
  const summaryRe = new RegExp(`<details[^>]*>\\s*<summary>\\s*${escapeRegex(summaryLabel)}[^<]*</summary>`, 'i');
  const summaryMatch = summaryRe.exec(text);
  if (!summaryMatch) return '';

  const start = summaryMatch.index;
  const tagRe = /<details\b[^>]*>|<\/details>/gi;
  tagRe.lastIndex = start;
  let depth = 0;
  let end = -1;
  let tag;

  while ((tag = tagRe.exec(text)) !== null) {
    if (tag[0].toLowerCase().startsWith('<details')) {
      depth += 1;
    } else {
      depth -= 1;
    }
    if (depth === 0) {
      end = tagRe.lastIndex;
      break;
    }
  }

  if (end === -1) return '';
  const block = text.slice(start, end);
  return block
    .replace(summaryRe, '')
    .replace(/<\/details>\s*$/i, '')
    .trim();
}

function parseDependencyUpdate(title, body) {
  const dependencyRepoMatch = body.match(
    /^\s*(?:Bumps|Update(?:s|d)?)\s+\[[^\]]+\]\(\s*https?:\/\/(?:redirect\.)?github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)(?:[\/#?][^)\s]*)?\s*\)/im,
  );
  const repoMatch =
    dependencyRepoMatch ||
    body.match(/https?:\/\/(?:redirect\.)?github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)(?=\/|$|[)\]>\s"'?#])/i);
  const upstreamRepo = repoMatch ? repoMatch[1].replace(/\.git$/i, '') : '';

  let releaseNotes = extractDetailsSection(body, 'Release notes');
  if (!releaseNotes && upstreamRepo) {
    releaseNotes = extractDetailsSection(body, upstreamRepo);
  }
  if (!releaseNotes) {
    const rnHeading = body.match(/###\s*Release\s+Notes?\s*\n([\s\S]*?)(?=\n---|\n###\s|$)/i);
    if (rnHeading) releaseNotes = rnHeading[1].trim();
  }

  let commits = extractDetailsSection(body, 'Commits');
  if (!commits) {
    const shaMatches = body.match(/\b[0-9a-f]{7,40}\b/gi);
    if (shaMatches && shaMatches.length > 0) commits = shaMatches.join('\n');
  }

  const titleMatch =
    title.match(/[Uu]pdate\s+(.+?)\s+requirement\s+from\s+([^\s]+)\s+to\s+([^\s]+)/) ||
    title.match(/[Bb]ump\s+(.+?)\s+from\s+([^\s]+)\s+to\s+([^\s]+)/) ||
    title.match(/[Uu]pdate\s+(.+?)\s+from\s+([^\s]+)\s+to\s+([^\s]+)/);
  const renovateTitleMatch =
    !titleMatch &&
    (title.match(/(?:update|pin)\s+dependency\s+(.+?)\s+to\s+v?([^\s]+)/i) ||
      title.match(/(?:update|pin)\s+(.+?)\s+(?:action|digest|docker\s+tag)\s+to\s+v?([^\s]+)/i) ||
      title.match(/(?:update|pin)\s+(.+?)\s+to\s+v?([^\s]+)/i));

  let packageName;
  let fromVersion;
  let toVersion;
  if (titleMatch) {
    packageName = titleMatch[1].trim();
    fromVersion = titleMatch[2].trim();
    toVersion = titleMatch[3].trim();
  } else if (renovateTitleMatch) {
    packageName = renovateTitleMatch[1].trim();
    fromVersion = '';
    toVersion = renovateTitleMatch[2].trim();
  } else {
    packageName = '';
    fromVersion = '';
    toVersion = '';
  }

  if (!fromVersion || !toVersion) {
    const bodyVersionMatch = body.match(/`([^`\s]+)`\s*(?:->|→)\s*`([^`\s]+)`/);
    if (bodyVersionMatch) {
      if (!fromVersion) fromVersion = bodyVersionMatch[1].replace(/^v/i, '');
      if (!toVersion) toVersion = bodyVersionMatch[2].replace(/^v/i, '');
    }
  }

  return {
    upstreamRepo,
    packageName,
    fromVersion,
    toVersion,
    releaseNotes,
    commits,
  };
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

function reviewMarkerFromPatchId(patchId) {
  if (typeof patchId !== 'string' || !/^[0-9a-f]{40}$/.test(patchId)) return '';
  return `<!-- cursor-dependabot-review patch-id:${patchId} -->`;
}

function commentFirstLine(body) {
  if (typeof body !== 'string') return '';
  const end = body.indexOf('\n');
  return (end === -1 ? body : body.slice(0, end)).trim();
}

function isActionsBotMarkerComment(comment) {
  if (comment?.user?.login !== ACTIONS_BOT_LOGIN) return false;
  const line = commentFirstLine(comment.body);
  return line === LEGACY_REVIEW_MARKER || /^<!-- cursor-dependabot-review \S+ -->$/.test(line);
}

function isActionsBotUpgradeReview(comment, marker) {
  return Boolean(marker) && comment?.user?.login === ACTIONS_BOT_LOGIN && commentFirstLine(comment.body) === marker;
}

async function runDependabotContext({ core }) {
  const body = process.env.PR_BODY || '';
  const title = process.env.PR_TITLE || '';
  const prNumber = Number(process.env.PR_NUMBER || '0');
  const parsed = parseDependencyUpdate(title, body);

  if (!parsed.upstreamRepo) {
    core.setFailed('PR body is missing an upstream GitHub repository link.');
    return;
  }

  const normalizedReleaseNotes = parsed.releaseNotes || 'PR body did not include a Release notes details section.';
  const normalizedCommits = parsed.commits || 'PR body did not include a Commits details section.';

  const out = {
    prNumber,
    upstreamRepo: parsed.upstreamRepo,
    packageName: parsed.packageName,
    fromVersion: parsed.fromVersion,
    toVersion: parsed.toVersion,
    releaseNotes: normalizedReleaseNotes,
    commits: normalizedCommits,
  };
  fs.writeFileSync('dependabot_comment_context.json', JSON.stringify(out, null, 2));
  fs.writeFileSync('dependabot_release_notes.md', normalizedReleaseNotes);
  fs.writeFileSync('dependabot_commits.md', normalizedCommits);
  core.setOutput('upstream_repo', parsed.upstreamRepo);
  core.setOutput('package_name', parsed.packageName);
  core.setOutput('from_version', parsed.fromVersion);
  core.setOutput('to_version', parsed.toVersion);
}

module.exports = runDependabotContext;
module.exports.parseDependencyUpdate = parseDependencyUpdate;
module.exports.MAX_DIFF_CHARS = MAX_DIFF_CHARS;
module.exports.patchIdFromDiff = patchIdFromDiff;
module.exports.reviewMarkerFromPatchId = reviewMarkerFromPatchId;
module.exports.isActionsBotMarkerComment = isActionsBotMarkerComment;
module.exports.isActionsBotUpgradeReview = isActionsBotUpgradeReview;
module.exports.LEGACY_REVIEW_MARKER = LEGACY_REVIEW_MARKER;
