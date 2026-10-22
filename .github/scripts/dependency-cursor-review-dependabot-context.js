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

function stripLeadingV(version) {
  return String(version || '')
    .trim()
    .replace(/^v/i, '');
}

function githubRepoFromText(text) {
  const source = String(text || '');
  const url = source.match(/https?:\/\/(?:redirect\.)?github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)/i);
  if (url) return url[1].replace(/\.git$/i, '');
  const moduleName = source.match(/^github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)(?:\/|$)/i);
  return moduleName ? moduleName[1] : '';
}

function packageCell(cell) {
  const trimmed = cell.trim();
  const link = trimmed.match(/^\[([^\]]*)\]\(([^)]*)\)$/);
  if (!link) return { name: trimmed, repo: githubRepoFromText(trimmed) };
  return {
    name: link[1].trim(),
    repo: githubRepoFromText(link[2]) || githubRepoFromText(link[1]),
  };
}

function agree(record, key, incoming) {
  if (record.disputed[key]) return '';
  if (!incoming) return record[key];
  if (!record[key]) return incoming;
  if (record[key] === incoming) return record[key];
  record.disputed[key] = true;
  return '';
}

function rememberUpdate(byName, name, fromVersion, toVersion, repo) {
  const packageName = String(name || '').trim();
  if (!packageName || packageName.toLowerCase() === 'package') return;
  const from = stripLeadingV(fromVersion);
  const to = stripLeadingV(toVersion);
  const repoName = String(repo || '')
    .trim()
    .replace(/\.git$/i, '');
  const existing = byName.get(packageName);
  if (!existing) {
    byName.set(packageName, {
      packageName,
      fromVersion: from,
      toVersion: to,
      upstreamRepo: repoName,
      disputed: {},
    });
    return;
  }
  existing.fromVersion = agree(existing, 'fromVersion', from);
  existing.toVersion = agree(existing, 'toVersion', to);
  existing.upstreamRepo = agree(existing, 'upstreamRepo', repoName);
}

function groupPreamble(body) {
  if (/^(?:Updates |<details|\|)/i.test(body)) return '';
  const marks = ['\nUpdates ', '\n|', '\n<details', '\n### '];
  let cut = body.length;
  for (const mark of marks) {
    const index = body.indexOf(mark);
    if (index >= 0 && index < cut) cut = index;
  }
  return body.slice(0, cut);
}

// The Dependabot update table only. Release-note tables sit later, often inside
// <details>, and a row there must not invent a package or clear a real version.
function dependabotUpdateTable(body) {
  const source = String(body || '');
  const detailsAt = source.search(/<details\b/i);
  const region = detailsAt === -1 ? source : source.slice(0, detailsAt);
  const header = /^\|\s*Package\s*\|\s*From\s*\|\s*To\s*\|/im.exec(region);
  if (!header) return '';
  const kept = [];
  for (const line of region.slice(header.index).split('\n')) {
    if (!line.trim()) {
      if (kept.length > 0) break;
      continue;
    }
    if (!line.trim().startsWith('|')) break;
    kept.push(line);
  }
  return kept.join('\n');
}

// One map. Intro links, table rows, Updates lines, and the title all write it.
// A second non-empty repository or version that differs clears that field.
function collectPackageUpdates(title, body) {
  const byName = new Map();
  const preamble = groupPreamble(body);
  const linkRe = /\[([^\]]+)\]\(\s*(https?:\/\/[^)\s]+)[^)]*\)/gi;
  let link;
  while ((link = linkRe.exec(preamble)) !== null) {
    rememberUpdate(byName, link[1], '', '', githubRepoFromText(link[2]));
  }
  const bumpsRe = /\[([^\]]+)\]\(\s*(https?:\/\/[^)\s]+)[^)]*\)\s+from\s+(\S+)\s+to\s+(\S+)/gi;
  let bumps;
  while ((bumps = bumpsRe.exec(preamble)) !== null) {
    rememberUpdate(
      byName,
      bumps[1],
      bumps[3].replace(/[.,;:]+$/, ''),
      bumps[4].replace(/[.,;:]+$/, ''),
      githubRepoFromText(bumps[2]),
    );
  }
  const tableRe = /^\|\s*([^|\n]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|/gm;
  const table = dependabotUpdateTable(body);
  let row;
  while ((row = tableRe.exec(table)) !== null) {
    const cell = packageCell(row[1]);
    rememberUpdate(byName, cell.name, row[2], row[3], cell.repo);
  }
  const lineRe = /^Updates\s+`([^`]+)`\s+from\s+(\S+)\s+to\s+(\S+)/gm;
  let line;
  while ((line = lineRe.exec(body)) !== null) {
    rememberUpdate(
      byName,
      line[1].trim(),
      line[2].replace(/[.,;:]+$/, ''),
      line[3].replace(/[.,;:]+$/, ''),
      githubRepoFromText(line[1]),
    );
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
  if (titleMatch) {
    rememberUpdate(byName, titleMatch[1], titleMatch[2], titleMatch[3], '');
  } else if (renovateTitleMatch) {
    rememberUpdate(byName, renovateTitleMatch[1], '', renovateTitleMatch[2], '');
  }

  if (byName.size === 1) {
    const only = [...byName.values()][0];
    if (!only.fromVersion || !only.toVersion) {
      const arrow = body.match(/`([^`\s]+)`\s*(?:->|→)\s*`([^`\s]+)`/);
      if (arrow) {
        rememberUpdate(
          byName,
          only.packageName,
          only.fromVersion ? '' : arrow[1],
          only.toVersion ? '' : arrow[2],
          '',
        );
      }
    }
  }
  return [...byName.values()].map(({ disputed, ...item }) => item);
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

  const updates = collectPackageUpdates(title, body);
  const sole = updates.length === 1 ? updates[0] : null;
  return {
    upstreamRepo: sole ? sole.upstreamRepo : '',
    packageName: sole ? sole.packageName : '',
    fromVersion: sole ? sole.fromVersion : '',
    toVersion: sole ? sole.toVersion : '',
    releaseNotes,
    commits,
    updates,
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

function skipApplies(reviewedShas, resolvedSha) {
  if (typeof resolvedSha !== 'string' || !/^[0-9a-f]{40}$/.test(resolvedSha)) return false;
  return Array.isArray(reviewedShas) && reviewedShas.includes(resolvedSha);
}

function versionTextCameFromBody(title, body) {
  const fromTitle = parseDependencyUpdate(title, '');
  const parsed = parseDependencyUpdate(title, body);
  return parsed.fromVersion !== fromTitle.fromVersion || parsed.toVersion !== fromTitle.toVersion;
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

async function runDependabotContext({ core }) {
  const body = process.env.PR_BODY || '';
  const title = process.env.PR_TITLE || '';
  const prNumber = Number(process.env.PR_NUMBER || '0');
  const parsed = parseDependencyUpdate(title, body);
  fs.writeFileSync('dependency_updates.json', JSON.stringify(parsed.updates, null, 2));

  if (!parsed.updates.some((item) => item.upstreamRepo)) {
    core.warning('PR body is missing an upstream GitHub repository link; the scan will record no_upstream_link.');
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
  core.setOutput('version_range_from_body', versionTextCameFromBody(title, body) ? '1' : '0');
}

module.exports = runDependabotContext;
module.exports.parseDependencyUpdate = parseDependencyUpdate;
module.exports.MAX_DIFF_CHARS = MAX_DIFF_CHARS;
module.exports.patchIdFromDiff = patchIdFromDiff;
module.exports.reviewMarkerFromPatchId = reviewMarkerFromPatchId;
module.exports.reviewedShasForPatch = reviewedShasForPatch;
module.exports.skipApplies = skipApplies;
module.exports.versionTextCameFromBody = versionTextCameFromBody;
module.exports.isActionsBotMarkerComment = isActionsBotMarkerComment;
module.exports.LEGACY_REVIEW_MARKER = LEGACY_REVIEW_MARKER;
