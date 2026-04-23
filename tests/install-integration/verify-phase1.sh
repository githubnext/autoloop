#!/usr/bin/env bash
# verify-phase1.sh - assert install.md produced the expected files and that
# `gh aw compile autoloop` is idempotent.
#
# Usage: verify-phase1.sh <path-to-checkout-of-install-branch>
#
# The checkout must be on the install branch (post-`gh aw init`,
# post-copy-files, post-`gh aw compile autoloop`). All paths are relative
# to that checkout.
set -euo pipefail

CHECKOUT="${1:?usage: verify-phase1.sh <checkout-dir>}"
cd "$CHECKOUT"

fail() { echo "PHASE1 FAIL: $*" >&2; exit 1; }
ok()   { echo "PHASE1 ok:   $*"; }

require_file() {
  [ -f "$1" ] || fail "missing file: $1"
  ok "file exists: $1"
}

require_dir() {
  [ -d "$1" ] || fail "missing directory: $1"
  ok "dir exists:  $1"
}

# --- gh aw init artifacts -------------------------------------------------
require_file ".gitattributes"

# --- autoloop workflow files copied from this repo ------------------------
require_file ".github/workflows/autoloop.md"
require_dir  ".github/workflows/shared"

# Issue #52: when sync-branches is removed, only autoloop.md should exist.
# Until then, sync-branches.md must also be present. Detect from the
# autoloop source repo (cloned in the test driver) and verify accordingly.
if [ -n "${EXPECT_SYNC_BRANCHES:-}" ] && [ "$EXPECT_SYNC_BRANCHES" = "1" ]; then
  require_file ".github/workflows/sync-branches.md"
  require_file ".github/workflows/sync-branches.lock.yml"
fi

# --- compiled lock file ---------------------------------------------------
require_file ".github/workflows/autoloop.lock.yml"

# --- issue template -------------------------------------------------------
require_file ".github/ISSUE_TEMPLATE/autoloop-program.md"

# --- programs directory present (may be empty) ----------------------------
require_dir ".autoloop/programs"

# --- lock idempotency: re-running compile must not change the lock file --
LOCK=".github/workflows/autoloop.lock.yml"
sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
SHA_BEFORE="$(sha256 "$LOCK")"
ok "lock sha256 before: $SHA_BEFORE"

# Re-run the compiler. If it fails or changes the lock, that's a phase-1
# failure (install.md said this command is the way to compile, so it must
# be idempotent).
gh aw compile autoloop >/dev/null
SHA_AFTER="$(sha256 "$LOCK")"
ok "lock sha256 after:  $SHA_AFTER"

if [ "$SHA_BEFORE" != "$SHA_AFTER" ]; then
  echo "--- diff ---" >&2
  git --no-pager diff -- "$LOCK" >&2 || true
  fail "gh aw compile is non-idempotent: lock file changed on second run"
fi
ok "lock file is idempotent"

# --- install PR exists ----------------------------------------------------
# The driver passes the PR URL via INSTALL_PR. Sanity-check it points at the
# target repo and a real PR number.
if [ -n "${INSTALL_PR:-}" ]; then
  if ! [[ "$INSTALL_PR" =~ ^https://github\.com/[^/]+/[^/]+/pull/[0-9]+$ ]]; then
    fail "INSTALL_PR is not a well-formed PR URL: $INSTALL_PR"
  fi
  ok "install PR URL looks valid: $INSTALL_PR"
fi

echo "PHASE1 PASS"
