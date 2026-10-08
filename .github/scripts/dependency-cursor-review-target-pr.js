'use strict';

/**
 * Resolve Dependabot/Renovate PR context for dependency-cursor-review (workflow step target_pr).
 *
 * Dependabot pull_request events also fire on rebase, recreate, and rebuild.
 * Those later pushes skip the review when github-actions[bot] has already
 * commented the marker for this same upgrade. "Same" is the GitHub PR number
 * plus the stable patch id of the PR diff, not the head SHA or a commit
 * message. A new PR has no marker, so it is reviewed. Any content change
 * produces a new patch id, so it is reviewed. Renovate and workflow_dispatch
 * always run.
 */
const {
  isActionsBotUpgradeReview,
  patchIdFromDiff,
  reviewMarkerFromPatchId,
} = require('./dependency-cursor-review-dependabot-context.js');

const DEPENDABOT_BOT = 'dependabot[bot]';
const WEB_FLOW_BOT = 'web-flow';
// Above one unpaginated page, and above a normal Dependabot PR. Longer lists fail open.
const MAX_PR_COMMITS = 100;

async function listIssueComments(github, context, prNumber) {
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: prNumber,
    per_page: 100,
  });
  return Array.isArray(comments) ? comments : [];
}

async function listPullRequestCommits(github, context, prNumber) {
  const commits = await github.paginate(github.rest.pulls.listCommits, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: prNumber,
    per_page: 100,
  });
  return Array.isArray(commits) ? commits : [];
}

function commitsAreVerifiedDependabot(commits) {
  if (!Array.isArray(commits) || commits.length === 0 || commits.length > MAX_PR_COMMITS) return false;
  return commits.every(
    (item) =>
      item?.author?.login === DEPENDABOT_BOT &&
      item?.committer?.login === WEB_FLOW_BOT &&
      item?.commit?.verification?.verified === true,
  );
}

async function pullRequestDiff(github, context, prNumber) {
  const response = await github.rest.pulls.get({
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: prNumber,
    mediaType: { format: 'diff' },
  });
  return typeof response?.data === 'string' ? response.data : '';
}

async function dependabotReviewMarker({ github, context, core, pr }) {
  if (pr.user?.login !== DEPENDABOT_BOT) return '';
  let commits;
  try {
    commits = await listPullRequestCommits(github, context, pr.number);
  } catch (err) {
    core.warning(`Could not list PR commits to identify the upgrade (${err.message}); running review.`);
    return '';
  }
  if (!commitsAreVerifiedDependabot(commits)) {
    core.notice('Dependabot PR commits are not all verified web-flow Dependabot commits; running review.');
    return '';
  }
  let diff;
  try {
    diff = await pullRequestDiff(github, context, pr.number);
  } catch (err) {
    core.warning(`Could not read the PR diff to identify the upgrade (${err.message}); running review.`);
    return '';
  }
  const marker = reviewMarkerFromPatchId(patchIdFromDiff(diff));
  if (!marker) {
    core.notice('Dependabot PR diff did not produce a stable patch id; running review.');
  }
  return marker;
}

async function dependabotReviewAlreadyPosted({ github, context, core, pr, marker }) {
  if (context.eventName !== 'pull_request') return false;
  if (pr.user?.login !== DEPENDABOT_BOT) return false;
  if (!marker) return false;
  let comments;
  try {
    comments = await listIssueComments(github, context, pr.number);
  } catch (err) {
    core.warning(`Could not list PR comments to detect an existing review (${err.message}); running review.`);
    return false;
  }
  const matched = comments.some((comment) => isActionsBotUpgradeReview(comment, marker));
  if (matched) {
    core.notice(`Dependabot PR #${pr.number} already has a Cursor review for this dependency upgrade; skipping.`);
  }
  return matched;
}

async function run({ github, context, core }) {
  core.setOutput('already_reviewed', 'false');
  core.setOutput('review_marker', '');
  let pr;
  if (context.eventName === 'pull_request') {
    pr = context.payload.pull_request;
  } else {
    const raw = context.payload.inputs?.pr_number;
    const prNumber = Number(raw);
    if (!Number.isInteger(prNumber) || prNumber <= 0) {
      core.setFailed(`Invalid pr_number input: ${raw}`);
      return;
    }
    const { data } = await github.rest.pulls.get({
      owner: context.repo.owner,
      repo: context.repo.repo,
      pull_number: prNumber,
    });
    pr = data;
  }
  if (!pr) {
    core.setFailed('Could not resolve target pull request context.');
    return;
  }
  const allowedBots = [DEPENDABOT_BOT, 'renovate[bot]'];
  if (!allowedBots.includes(pr.user?.login)) {
    core.setFailed(`Target PR #${pr.number} is not opened by an allowed bot. Author: ${pr.user?.login}`);
    return;
  }
  const marker = await dependabotReviewMarker({ github, context, core, pr });
  core.setOutput('number', String(pr.number));
  core.setOutput('title', pr.title || '');
  core.setOutput('body', pr.body || '');
  core.setOutput('head_sha', pr.head?.sha || '');
  core.setOutput('review_marker', marker);
  const alreadyReviewed = await dependabotReviewAlreadyPosted({
    github,
    context,
    core,
    pr,
    marker,
  });
  core.setOutput('already_reviewed', alreadyReviewed ? 'true' : 'false');
}

module.exports = { run, MAX_PR_COMMITS };
