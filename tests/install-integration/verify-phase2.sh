#!/usr/bin/env bash
# verify-phase2.sh - per-program assertions for one Phase-2 program run.
#
# Usage:
#   verify-phase2.sh <owner/repo> <program-name> <run-id> <strategy>
#
# <strategy> is one of: openevolve | test-driven | plain
#
# Asserts:
#   1. Workflow run completed with conclusion `success` (the `agent` job exited
#      success, regardless of accept/reject of the iteration).
#   2. A program issue exists for <program-name>.
#   3. The status comment (<!-- AUTOLOOP:STATUS -->) is present on the issue.
#   4. State file `<program-name>.md` exists on the `memory/autoloop` branch.
#   5. Branch `autoloop/<program-name>` exists OR the iteration was rejected.
#   6. Strategy-specific subsection in the state file:
#        openevolve  -> contains `## 🧬 Population`
#        test-driven -> contains `## ✅ Test Harness`
#        plain       -> contains `## 📊 Iteration History`
#                        and does NOT contain Population or Test Harness
#                        (negative assertion).
set -euo pipefail

REPO="${1:?usage: verify-phase2.sh <owner/repo> <program-name> <run-id> <strategy>}"
PROGRAM="${2:?missing <program-name>}"
RUN_ID="${3:?missing <run-id>}"
STRATEGY="${4:?missing <strategy>}"

fail() { echo "PHASE2 [$PROGRAM] FAIL: $*" >&2; exit 1; }
ok()   { echo "PHASE2 [$PROGRAM] ok:   $*"; }

# 1. Workflow run conclusion.
CONCLUSION="$(gh run view "$RUN_ID" --repo "$REPO" --json conclusion --jq '.conclusion' 2>/dev/null || echo "")"
if [ "$CONCLUSION" != "success" ]; then
  fail "workflow run $RUN_ID conclusion=$CONCLUSION (want: success)"
fi
ok "workflow run $RUN_ID conclusion=success"

# 2. Program issue exists. For issue-based programs the issue was created by
#    the test driver before the run; for file-based programs the iteration
#    auto-creates one. Either way, search by title.
ISSUE_NUMBER="$(gh issue list --repo "$REPO" --state all --search "[Autoloop: $PROGRAM]" \
  --json number,title \
  --jq ".[] | select(.title == \"[Autoloop: $PROGRAM]\") | .number" \
  2>/dev/null | head -1)"
if [ -z "$ISSUE_NUMBER" ]; then
  fail "no program issue titled [Autoloop: $PROGRAM] found"
fi
ok "program issue: #$ISSUE_NUMBER"

# 3. Status comment present.
STATUS_HIT="$(gh issue view "$ISSUE_NUMBER" --repo "$REPO" --comments \
  --json comments --jq '.comments[].body' 2>/dev/null \
  | grep -c '<!-- AUTOLOOP:STATUS -->' || true)"
if [ "${STATUS_HIT:-0}" -lt 1 ]; then
  fail "no <!-- AUTOLOOP:STATUS --> comment on issue #$ISSUE_NUMBER"
fi
ok "status comment present on #$ISSUE_NUMBER"

# 4. State file on memory/autoloop branch.
STATE_FILE="${PROGRAM}.md"
STATE_BODY="$(gh api "repos/${REPO}/contents/${STATE_FILE}?ref=memory/autoloop" \
  --jq '.content' 2>/dev/null | base64 --decode 2>/dev/null || true)"
if [ -z "$STATE_BODY" ]; then
  fail "state file ${STATE_FILE} missing on memory/autoloop branch"
fi
ok "state file present: memory/autoloop:${STATE_FILE}"

if ! echo "$STATE_BODY" | grep -q 'Machine State'; then
  fail "state file has no 'Machine State' table"
fi
ok "state file has Machine State table"

# 5. autoloop/<program-name> branch exists OR iteration was rejected.
BRANCH_OK=0
if gh api "repos/${REPO}/branches/autoloop/${PROGRAM}" >/dev/null 2>&1; then
  BRANCH_OK=1
  ok "branch autoloop/${PROGRAM} exists"
else
  # Acceptable only if the iteration was rejected. Look for the marker in
  # the latest per-iteration comment on the issue.
  if gh issue view "$ISSUE_NUMBER" --repo "$REPO" --comments \
       --json comments --jq '.comments[].body' 2>/dev/null \
       | grep -qiE 'reject|rejected'; then
    ok "no autoloop branch, but iteration was rejected (acceptable)"
    BRANCH_OK=1
  fi
fi
[ "$BRANCH_OK" = "1" ] || fail "no autoloop/${PROGRAM} branch and no rejection marker"

# 6. Strategy-specific subsection.
case "$STRATEGY" in
  openevolve)
    echo "$STATE_BODY" | grep -q '## 🧬 Population' \
      || fail "openevolve: state file missing '## 🧬 Population'"
    ok "state file has '## 🧬 Population'"
    ;;
  test-driven)
    echo "$STATE_BODY" | grep -q '## ✅ Test Harness' \
      || fail "test-driven: state file missing '## ✅ Test Harness'"
    ok "state file has '## ✅ Test Harness'"
    ;;
  plain)
    echo "$STATE_BODY" | grep -q '## 📊 Iteration History' \
      || fail "plain: state file missing '## 📊 Iteration History'"
    ok "state file has '## 📊 Iteration History'"
    if echo "$STATE_BODY" | grep -q '## 🧬 Population'; then
      fail "plain: state file unexpectedly contains '## 🧬 Population' (strategy bleed)"
    fi
    if echo "$STATE_BODY" | grep -q '## ✅ Test Harness'; then
      fail "plain: state file unexpectedly contains '## ✅ Test Harness' (strategy bleed)"
    fi
    ok "no strategy-section bleed into plain program"
    ;;
  *)
    fail "unknown strategy: $STRATEGY"
    ;;
esac

echo "PHASE2 [$PROGRAM] PASS"
