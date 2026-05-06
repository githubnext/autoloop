#!/usr/bin/env bash
# run.sh - end-to-end install integration test driver.
#
# Runs against $INSTALL_TEST_REPO (default: mrjf/autoloop-test). See the
# README in this directory for prerequisites and what the test verifies.
#
# Flags / env:
#   --keep                    leave the test repo in failure state for inspection
#   KEEP_STATE_ON_FAILURE=1   same as --keep (used by the Actions wrapper)
#   INSTALL_TEST_REPO=...     target repo (default: mrjf/autoloop-test)
#   AUTOLOOP_REF=main         git ref of install.md to follow (default: main)
#
# Exits non-zero on any failed assertion. Cleanup runs in `trap EXIT` so it
# happens even on abort.
set -euo pipefail

# --------------------------------------------------------------------------
# Args / env
# --------------------------------------------------------------------------
KEEP="${KEEP_STATE_ON_FAILURE:-0}"
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
  esac
done

INSTALL_TEST_REPO="${INSTALL_TEST_REPO:-mrjf/autoloop-test}"
AUTOLOOP_REF="${AUTOLOOP_REF:-main}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log()   { echo "[run.sh] $*"; }
hr()    { echo "[run.sh] ----------------------------------------"; }

PASS=0
EXIT_CODE=1
BASE_SHA=""
WORKDIR=""

cleanup() {
  local rc=$?
  hr
  if [ "$PASS" = "1" ]; then
    log "test PASSED"
    EXIT_CODE=0
  else
    log "test FAILED (exit=$rc)"
    EXIT_CODE=1
  fi

  if [ "$KEEP" = "1" ] && [ "$PASS" != "1" ]; then
    log "KEEP=1 set: skipping teardown so failure state can be inspected"
    log "remember to run teardown.sh manually:"
    log "  $SCRIPT_DIR/teardown.sh $INSTALL_TEST_REPO $BASE_SHA"
  else
    if [ -n "$BASE_SHA" ]; then
      log "running teardown..."
      "$SCRIPT_DIR/teardown.sh" "$INSTALL_TEST_REPO" "$BASE_SHA" || true
    fi
  fi

  if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
    rm -rf "$WORKDIR"
  fi

  exit "$EXIT_CODE"
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------
hr
log "pre-flight"
command -v gh       >/dev/null || { log "gh CLI not on PATH"; exit 1; }
command -v copilot  >/dev/null || { log "copilot CLI not on PATH"; exit 1; }
command -v python3  >/dev/null || { log "python3 not on PATH"; exit 1; }
command -v git      >/dev/null || { log "git not on PATH"; exit 1; }
gh auth status >/dev/null 2>&1 || { log "gh is not authenticated"; exit 1; }
log "tools ok; target repo: $INSTALL_TEST_REPO"

# Detect whether the autoloop source has sync-branches.md so phase-1
# verification can require its lock file (issue #52 may remove it).
if [ -f "$REPO_ROOT/workflows/sync-branches.md" ]; then
  export EXPECT_SYNC_BRANCHES=1
  log "sync-branches.md present in source repo: phase-1 will require its lock file"
else
  export EXPECT_SYNC_BRANCHES=0
fi

# --------------------------------------------------------------------------
# Capture base-state SHA and reset target repo to it.
# --------------------------------------------------------------------------
hr
log "capturing base-state SHA on $INSTALL_TEST_REPO@main"
BASE_SHA="$(gh api "repos/${INSTALL_TEST_REPO}/branches/main" --jq '.commit.sha')"
log "base SHA: $BASE_SHA"

log "pre-test reset (discards any debris from prior failed runs)"
"$SCRIPT_DIR/teardown.sh" "$INSTALL_TEST_REPO" "$BASE_SHA"

# --------------------------------------------------------------------------
# Clone target locally and feed install.md to copilot.
# --------------------------------------------------------------------------
WORKDIR="$(mktemp -d -t autoloop-install-int-XXXXXX)"
CHECKOUT="$WORKDIR/repo"
log "cloning $INSTALL_TEST_REPO -> $CHECKOUT"
git clone --quiet "https://github.com/${INSTALL_TEST_REPO}.git" "$CHECKOUT"

hr
log "running copilot CLI against install.md (this can take several minutes)"
COPILOT_LOG="$WORKDIR/copilot.log"
PROMPT="$(cat "$SCRIPT_DIR/prompt.md")"
(
  cd "$CHECKOUT"
  # `--allow-all-tools` lets the agent run the shell commands install.md
  # tells it to run; without that the test can't actually exercise the flow.
  copilot --allow-all-tools -p "$PROMPT" 2>&1 | tee "$COPILOT_LOG"
)

# Extract install PR URL from the agent's output. Tolerate quoting/extra ws.
INSTALL_PR="$(grep -Eo 'INSTALL_PR=https://github\.com/[^ ]+' "$COPILOT_LOG" \
  | tail -1 | cut -d= -f2- || true)"
if [ -z "$INSTALL_PR" ]; then
  log "could not find INSTALL_PR=... in copilot output"
  exit 1
fi
export INSTALL_PR
log "install PR: $INSTALL_PR"

# --------------------------------------------------------------------------
# Phase 1 verification (against the install branch checkout).
# --------------------------------------------------------------------------
hr
log "PHASE 1: verifying install artifacts"
# Make sure the local checkout is on the install branch the agent used.
HEAD_REF="$(gh pr view "$INSTALL_PR" --repo "$INSTALL_TEST_REPO" --json headRefName --jq '.headRefName')"
(
  cd "$CHECKOUT"
  git fetch --quiet origin "$HEAD_REF"
  git checkout --quiet -B "$HEAD_REF" "origin/$HEAD_REF"
)
"$SCRIPT_DIR/verify-phase1.sh" "$CHECKOUT"

# --------------------------------------------------------------------------
# Merge the install PR and wait for it to land.
# --------------------------------------------------------------------------
hr
log "merging install PR via squash"
gh pr merge "$INSTALL_PR" --repo "$INSTALL_TEST_REPO" --squash --admin --delete-branch
# Brief wait so subsequent gh api calls see the new main SHA.
sleep 5

# --------------------------------------------------------------------------
# Phase 2: create three programs (file/openevolve, issue/test-driven,
# file/plain) and run one iteration of each, sequentially.
# --------------------------------------------------------------------------
hr
log "PHASE 2: program × strategy matrix"

# Refresh local checkout to merged main.
(
  cd "$CHECKOUT"
  git fetch --quiet origin main
  git checkout --quiet -B main origin/main
)

# Helper: commit a file-based program to main and push.
push_program() {
  local name="$1"
  local body_file="$2"
  (
    cd "$CHECKOUT"
    mkdir -p ".autoloop/programs/${name}"
    cp "$body_file" ".autoloop/programs/${name}/program.md"
    git add ".autoloop/programs/${name}/program.md"
    git -c user.email=integration-test@autoloop -c user.name="autoloop integration test" \
      commit -m "test: add program ${name}" --quiet
    git push --quiet origin main
  )
}

# Helper: trigger one iteration for a program and echo the run id.
run_iteration() {
  local name="$1"
  log "dispatching autoloop.lock.yml for program=$name"
  # Capture the timestamp just before dispatch so we can find the run we
  # just kicked off.
  local before
  before="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  gh workflow run autoloop.lock.yml --repo "$INSTALL_TEST_REPO" \
    -f program="$name" >/dev/null

  # Poll for the run.
  local run_id="" attempts=0
  while [ -z "$run_id" ] && [ "$attempts" -lt 30 ]; do
    sleep 5
    run_id="$(gh run list --repo "$INSTALL_TEST_REPO" --workflow autoloop.lock.yml \
      --created ">${before}" --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
    attempts=$((attempts + 1))
  done
  [ -n "$run_id" ] || { log "could not find dispatched run for $name"; return 1; }
  log "run id: $run_id; waiting for completion..."
  gh run watch "$run_id" --repo "$INSTALL_TEST_REPO" --exit-status >/dev/null 2>&1 \
    || log "run $run_id finished with non-zero status (will be checked by verify-phase2.sh)"
  echo "$run_id"
}

# ---- Program 1: file-based + OpenEvolve ----------------------------------
PROG1=rastrigin-openevolve
PROG1_FILE="$WORKDIR/${PROG1}.md"
cat > "$PROG1_FILE" <<'EOF'
---
schedule: every 6h
---

# Rastrigin (OpenEvolve)

## Goal

Improve `src/minimize.py` to find lower minima of the Rastrigin function more
reliably. Lower metric is better.

## Target

Only modify these files:
- `src/minimize.py` -- the minimizer

Do NOT modify:
- `src/evaluate.py`
- `tests/test_minimize.py`

## Evaluation

```bash
python3 src/evaluate.py
```

The metric is `metric`. **Lower is better.**

## Evolution Strategy

See `strategy/openevolve.md`. Maintain a small population across these islands:
- `grid-search` (baseline)
- `scipy-minimize`
- `gradient-descent`
EOF

# ---- Program 3: file-based + plain prose (no strategy) -------------------
# Defined here so we can push both file-based programs in one push later.
PROG3=rastrigin-plain
PROG3_FILE="$WORKDIR/${PROG3}.md"
cat > "$PROG3_FILE" <<'EOF'
---
schedule: every 6h
---

# Rastrigin (Plain)

## Goal

Improve `src/minimize.py` to find lower minima of the Rastrigin function. Lower
metric is better.

## Target

Only modify these files:
- `src/minimize.py`

Do NOT modify:
- `src/evaluate.py`
- `tests/test_minimize.py`

## Evaluation

```bash
python3 src/evaluate.py
```

The metric is `metric`. **Lower is better.**
EOF

push_program "$PROG1" "$PROG1_FILE"
push_program "$PROG3" "$PROG3_FILE"

# ---- Program 2: issue-based + Test-Driven --------------------------------
PROG2=rastrigin-tdd
log "creating issue-based program $PROG2"
PROG2_BODY=$(cat <<'EOF'
<!-- AUTOLOOP:ISSUE-PROGRAM -->

---
schedule: every 6h
---

# rastrigin-tdd

## Goal

Cover the public API of `src/minimize.py` with tighter correctness tests.
Higher passing test count is better.

## Target

Only modify these files:
- `tests/test_minimize.py`

Do NOT modify:
- `src/minimize.py`
- `src/evaluate.py`

## Evaluation

```bash
python3 -m pytest tests/ -q | tail -1
```

The metric is `passing_tests`. **Higher is better.**

## Evolution Strategy

See `strategy/test-driven.md`. Maintain a test harness with at least one
candidate per iteration.
EOF
)
gh issue create --repo "$INSTALL_TEST_REPO" \
  --title "[Autoloop: ${PROG2}]" \
  --label "autoloop-program" \
  --body "$PROG2_BODY" >/dev/null
log "issue created for $PROG2"

# ---- Run the three programs sequentially ---------------------------------
RUN1="$(run_iteration "$PROG1")"
"$SCRIPT_DIR/verify-phase2.sh" "$INSTALL_TEST_REPO" "$PROG1" "$RUN1" "openevolve"

RUN2="$(run_iteration "$PROG2")"
"$SCRIPT_DIR/verify-phase2.sh" "$INSTALL_TEST_REPO" "$PROG2" "$RUN2" "test-driven"

RUN3="$(run_iteration "$PROG3")"
"$SCRIPT_DIR/verify-phase2.sh" "$INSTALL_TEST_REPO" "$PROG3" "$RUN3" "plain"

# --------------------------------------------------------------------------
# All assertions passed -- mark for the cleanup trap.
# --------------------------------------------------------------------------
hr
log "all phases passed"
PASS=1
