# install-integration

End-to-end integration test for [`install.md`](../../install.md). Runs the
install flow as a real coding agent (Copilot CLI) against a long-lived
target repo (`mrjf/autoloop-test` by default), then exercises Phase 2 by
running one iteration each of three programs across the program-source ×
strategy matrix.

This test is **manual-dispatch only**. It is not part of CI.

## Local mode

```bash
# from the autoloop repo root:
./tests/install-integration/run.sh
```

Requirements:

- `gh` CLI authenticated as a user with write access to the target repo.
- `copilot` CLI on PATH.
- `python3` and `git` on PATH.

Optional env / flags:

- `INSTALL_TEST_REPO=<owner>/<repo>` -- override the target (default
  `mrjf/autoloop-test`).
- `--keep` (or `KEEP_STATE_ON_FAILURE=1`) -- skip teardown on failure so
  the failure state can be inspected. Run `teardown.sh <repo> <base-sha>`
  manually afterwards.

## Actions mode

Trigger the **Install Integration Test** workflow from the Actions tab. It
runs the same script on a GitHub-hosted runner. Requires the
`INSTALL_TEST_TOKEN` repo secret -- a PAT with `repo` scope on the target
repo (the default `GITHUB_TOKEN` has no access to repos outside the host).

## What it tests

See [the issue that introduced this harness](https://github.com/githubnext/autoloop/issues)
for the full motivation. In short:

- **Phase 1** (file presence + lock idempotency) -- catches regressions in
  `install.md` and in `gh aw compile`.
- **Phase 2** (3 programs × 1 iteration each) -- catches regressions in
  the scheduler, in strategy discovery, and in the iteration loop. The
  three programs cover:

  | # | Source     | Strategy        |
  |---|------------|-----------------|
  | 1 | file-based | OpenEvolve      |
  | 2 | issue-based| Test-Driven     |
  | 3 | file-based | plain (default) |

- **Phase 3** (teardown) -- resets the target repo to the captured base
  SHA, closes test issues/PRs, and deletes test branches.

## Files

| File                  | Purpose                                          |
|-----------------------|--------------------------------------------------|
| `run.sh`              | Driver. Orchestrates phases 1-3.                 |
| `prompt.md`           | Prompt fed to Copilot CLI (edit without touching the driver). |
| `verify-phase1.sh`    | File-presence + lock-idempotency assertions.     |
| `verify-phase2.sh`    | Per-program assertions (one call per program).   |
| `teardown.sh`         | Idempotent cleanup. Safe to re-run.              |
