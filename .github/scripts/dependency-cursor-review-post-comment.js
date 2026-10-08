'use strict';

const fs = require('fs');

const { isActionsBotMarkerComment, LEGACY_REVIEW_MARKER } = require('./dependency-cursor-review-dependabot-context.js');

function readText(path, fallback = '') {
  try {
    return fs.readFileSync(path, 'utf8');
  } catch (_) {
    return fallback;
  }
}

function analysisTextFromRaw(raw) {
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    parsed = { result: raw };
  }
  const analysis = parsed.result || parsed.output || parsed.text || parsed.message || raw;
  return typeof analysis === 'string' ? analysis : JSON.stringify(analysis, null, 2) || String(analysis);
}

function successfulAnalysisText(filePath) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch (_) {
    return '';
  }
  if (!String(raw).trim()) return '';
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    return '';
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || payload.error || payload.is_error === true) {
    return '';
  }
  for (const key of ['result', 'output', 'text', 'message']) {
    const value = payload[key];
    if (typeof value !== 'string' || !value.trim() || value.startsWith('Missing output file:')) continue;
    if (value.startsWith('Error: agent exited')) return '';
    return value.trim();
  }
  return '';
}

const MALWARE_REVIEW_HEADING = '## Supply-Chain Malware Review';
const COMPATIBILITY_REVIEW_HEADING = '## Compatibility Analysis';
const FAILED_COMBINED_PREFIXES = [
  'Missing output file:',
  'Error: agent exited',
  'No Cursor output generated',
  'CURSOR_API_KEY is not set',
];

function isReviewObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/** Text of cursor_output.json only when combine finished a real review. */
function combinedReviewText(filePath) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch (_) {
    return '';
  }
  if (!String(raw).trim()) return '';
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    return '';
  }
  if (!isReviewObject(payload) || payload.error || payload.is_error === true || payload.complete !== true) {
    return '';
  }
  if (!isReviewObject(payload.malware_review) || !isReviewObject(payload.compatibility_review)) return '';
  const value = payload.result;
  if (typeof value !== 'string' || !value.trim()) return '';
  if (FAILED_COMBINED_PREFIXES.some((prefix) => value.startsWith(prefix))) return '';
  const malwareAt = value.indexOf(MALWARE_REVIEW_HEADING);
  const compatibilityAt = value.indexOf(COMPATIBILITY_REVIEW_HEADING);
  if (malwareAt === -1 || compatibilityAt === -1 || malwareAt > compatibilityAt) return '';
  return value.trim();
}

/** Stamp the upgrade marker only after combine wrote a real review and both agent files succeeded. */
function selectPostedMarker(marker) {
  const malware = successfulAnalysisText('cursor_output_malware.json');
  const compatibility = successfulAnalysisText('cursor_output_compatibility.json');
  const combined = combinedReviewText('cursor_output.json');
  if (!marker || !malware || !compatibility || !combined) return LEGACY_REVIEW_MARKER;
  return marker;
}

async function runPostComment({ github, context, core }) {
  const analysisMaxLen = 48000;
  const malwareMaxLen = 10000;
  const githubCommentLimit = 65536;
  const malwareScanStatus = process.env.MALWARE_SCAN_STATUS || '';
  const malwareScanChangedCount = process.env.MALWARE_SCAN_CHANGED_COUNT || '';
  const malwareScanSummaryOutput = process.env.MALWARE_SCAN_SUMMARY || '';
  const issueNumber = Number(process.env.PR_NUMBER || '0');
  const reviewMarker = process.env.REVIEW_MARKER || '';

  const raw = readText('cursor_output.json', '{"result":"No Cursor output generated.","complete":false}');
  const analysisText = analysisTextFromRaw(raw);
  const marker = selectPostedMarker(reviewMarker);
  const malwareSummaryFallback =
    (typeof malwareScanSummaryOutput === 'string' && malwareScanSummaryOutput.trim()) ||
    [
      '## Malware Scan Summary',
      '',
      `- Status: **${malwareScanStatus || 'unknown'}**`,
      `- Changed upstream files scanned: \`${malwareScanChangedCount || 'unknown'}\``,
      '- Scanner output file missing.',
    ].join('\n');
  const malwareSummary = readText('malware_scan_summary.md', malwareSummaryFallback);

  let trimmedAnalysis = analysisText.slice(0, analysisMaxLen);
  let trimmedMalware = malwareSummary.slice(0, malwareMaxLen);
  const renderBody = (analysisPart, malwarePart) =>
    [marker, '## 🤖 Cursor Dependency Analysis', '', analysisPart, '', '---', '', malwarePart].join('\n');
  let body = renderBody(trimmedAnalysis, trimmedMalware);
  if (body.length > githubCommentLimit) {
    const allowedAnalysis = Math.max(0, analysisMaxLen - (body.length - githubCommentLimit) - 256);
    trimmedAnalysis = analysisText.slice(0, allowedAnalysis);
    body = renderBody(trimmedAnalysis, trimmedMalware);
  }

  const { owner, repo } = context.repo;
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number: issueNumber,
    per_page: 100,
  });
  const markerComments = comments
    .filter(isActionsBotMarkerComment)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const latestMarker = markerComments.length > 0 ? markerComments[markerComments.length - 1] : null;

  const hasCommentaryAfterLatest =
    latestMarker &&
    comments.some(
      (comment) =>
        comment.id !== latestMarker.id &&
        !isActionsBotMarkerComment(comment) &&
        new Date(comment.created_at).getTime() > new Date(latestMarker.created_at).getTime(),
    );

  if (latestMarker && !hasCommentaryAfterLatest) {
    await github.rest.issues.updateComment({
      owner,
      repo,
      comment_id: latestMarker.id,
      body,
    });
  } else {
    await github.rest.issues.createComment({
      owner,
      repo,
      issue_number: issueNumber,
      body,
    });
  }
  if (typeof core?.info === 'function') {
    core.info(
      marker !== LEGACY_REVIEW_MARKER
        ? 'Posted Dependabot review marker for this dependency upgrade.'
        : 'Posted dependency review comment without an upgrade marker.',
    );
  }
}

module.exports = runPostComment;
module.exports.selectPostedMarker = selectPostedMarker;
module.exports.successfulAnalysisText = successfulAnalysisText;
