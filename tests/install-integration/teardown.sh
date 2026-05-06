#!/usr/bin/env bash
# teardown.sh - reset the integration-test target repo to a known-good base
# state. Idempotent: safe to re-run.
#
# Usage:
#   teardown.sh <owner/repo> <base-sha>
#
# What it does (all against the *remote* repo via gh / git push --force):
#   1. Force-reset main to <base-sha>.
#   2. Close all issues labeled `autoloop-program` (also the
#      `[Autoloop: ...]` status issues).
#   3. Close all open PRs whose head branch starts with `autoloop/` or
#      whose head branch is `install-autoloop`.
#   4. Delete all remote branches matching `autoloop/*`,
#      `install-autoloop`, and `memory/autoloop`.
#
# Requires: gh authenticated with write access to <owner/repo>; git on PATH.
set -euo pipefail

REPO="${1:?usage: teardown.sh <owner/repo> <base-sha>}"
BASE_SHA="${2:?usage: teardown.sh <owner/repo> <base-sha>}"

log() { echo "TEARDOWN: $*"; }
warn() { echo "TEARDOWN WARN: $*" >&2; }

# 1. Force-reset main to base-sha. Use a temp clone to avoid touching the
#    caller's working dir.
TMP="$(mktemp -d -t autoloop-teardown-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

log "cloning $REPO to reset main -> $BASE_SHA"
git clone --quiet "https://github.com/${REPO}.git" "$TMP/repo"
(
  cd "$TMP/repo"
  # Only force-push if main is not already at base sha.
  CURRENT="$(git rev-parse origin/main)"
  if [ "$CURRENT" != "$BASE_SHA" ]; then
    log "main is at $CURRENT; resetting to $BASE_SHA"
    git checkout --quiet -B main "$BASE_SHA"
    git push --force --quiet origin main
  else
    log "main already at $BASE_SHA; no reset needed"
  fi
) || warn "main reset failed (continuing)"

# 2. Close `autoloop-program`-labelled issues.
log "closing autoloop-program issues"
mapfile -t ISSUES < <(gh issue list --repo "$REPO" --label autoloop-program \
  --state open --json number --jq '.[].number' 2>/dev/null || true)
for n in "${ISSUES[@]:-}"; do
  [ -z "$n" ] && continue
  gh issue close "$n" --repo "$REPO" --reason "not planned" \
    --comment "Closed by install-integration test teardown." \
    >/dev/null 2>&1 || warn "could not close issue #$n"
  log "closed issue #$n"
done

# Also catch `[Autoloop: ...]`-titled issues that lost the label or were
# auto-created without it (defensive).
mapfile -t TITLED < <(gh issue list --repo "$REPO" --state open --search '[Autoloop:' \
  --json number,title --jq '.[] | select(.title | startswith("[Autoloop:")) | .number' 2>/dev/null || true)
for n in "${TITLED[@]:-}"; do
  [ -z "$n" ] && continue
  gh issue close "$n" --repo "$REPO" --reason "not planned" \
    --comment "Closed by install-integration test teardown." \
    >/dev/null 2>&1 || warn "could not close titled issue #$n"
  log "closed titled issue #$n"
done

# 3. Close open PRs from autoloop/* and install-autoloop branches.
log "closing test PRs"
mapfile -t PRS < <(gh pr list --repo "$REPO" --state open \
  --json number,headRefName \
  --jq '.[] | select(.headRefName | startswith("autoloop/") or . == "install-autoloop") | .number' \
  2>/dev/null || true)
for n in "${PRS[@]:-}"; do
  [ -z "$n" ] && continue
  gh pr close "$n" --repo "$REPO" --delete-branch \
    --comment "Closed by install-integration test teardown." \
    >/dev/null 2>&1 || warn "could not close PR #$n"
  log "closed PR #$n"
done

# 4. Delete any remaining branches we created (gh pr close --delete-branch
#    handles most, but autoloop/* branches without a PR also exist).
log "deleting test branches"
mapfile -t BRANCHES < <(gh api "repos/${REPO}/branches" --paginate \
  --jq '.[].name' 2>/dev/null || true)
for b in "${BRANCHES[@]:-}"; do
  case "$b" in
    autoloop/*|install-autoloop|memory/autoloop)
      gh api -X DELETE "repos/${REPO}/git/refs/heads/${b}" \
        >/dev/null 2>&1 || warn "could not delete branch $b"
      log "deleted branch $b"
      ;;
  esac
done

log "done"
