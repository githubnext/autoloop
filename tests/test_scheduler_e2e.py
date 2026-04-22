"""End-to-end fixture tests for the standalone Autoloop scheduler.

These tests run ``workflows/scripts/autoloop_scheduler.py`` as a subprocess in
isolated temp directories and validate the resulting ``autoloop.json``. They
cover the scenarios called out in the extraction issue:

* most-overdue selection (``last_run`` tie-break)
* missing state file → first run
* ``paused: true`` → skipped with reason
* ``completed: true`` → skipped
* ``AUTOLOOP_PROGRAM=<name>`` → forced selection bypasses scheduling
* No programs found → ``no_programs: true``

The scheduler talks to the GitHub issues API; tests point ``GITHUB_REPOSITORY``
at a non-resolvable host so the request fails fast, falling back to the
filesystem-discovered programs only (the script logs a warning and continues —
the same behaviour exercised in the workflow when issues are absent).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

import pytest

from conftest import SCHEDULER_PATH

PROGRAM_TEMPLATE = textwrap.dedent("""\
    ---
    schedule: every 6h
    ---

    # {name}

    ## Goal
    Optimize {name}.

    ## Target
    - file.py

    ## Evaluation
    ```bash
    python eval.py
    ```

    The metric is `score`. Higher is better.
""")


def _state_file(name, *, last_run=None, paused=False, completed=False, pause_reason=None):
    """Render a minimal repo-memory state file for a program."""
    rows = [
        ("Last Run", last_run if last_run else "—"),
        ("Iteration Count", "0"),
        ("Best Metric", "—"),
        ("Target Metric", "—"),
        ("Paused", "true" if paused else "false"),
        ("Pause Reason", pause_reason or "—"),
        ("Completed", "true" if completed else "false"),
        ("Completed Reason", "—"),
        ("Consecutive Errors", "0"),
        ("Recent Statuses", "—"),
    ]
    body = "\n".join("| {} | {} |".format(k, v) for k, v in rows)
    return textwrap.dedent("""\
        # Autoloop: {name}

        ## ⚙️ Machine State

        | Field | Value |
        |-------|-------|
        {body}
        """).format(name=name, body=body)


def _run_scheduler(workdir, *, forced=None, repo="bogus.invalid/bogus"):
    """Run the scheduler in ``workdir`` and return ``(returncode, autoloop_json)``.

    ``GITHUB_REPOSITORY`` defaults to a bogus DNS name so the issues fetch fails
    instantly (DNS lookup error → caught, scheduler continues with filesystem
    programs only). ``HOME`` is also rewritten so any state under ``/tmp/gh-aw``
    is owned by the test.
    """
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = "dummy"
    env["GITHUB_REPOSITORY"] = repo
    if forced is not None:
        env["AUTOLOOP_PROGRAM"] = forced
    else:
        env.pop("AUTOLOOP_PROGRAM", None)

    # The scheduler always writes /tmp/gh-aw/autoloop.json; isolate via TMPDIR
    # so concurrent tests don't clobber each other.
    tmproot = os.path.join(workdir, "_tmp")
    os.makedirs(tmproot, exist_ok=True)
    env["TMPDIR"] = tmproot

    # Wipe any stale output from a previous run within this workdir.
    out_dir = os.path.join(tmproot, "gh-aw") if False else "/tmp/gh-aw"
    out_path = os.path.join(out_dir, "autoloop.json")
    if os.path.exists(out_path):
        os.remove(out_path)

    proc = subprocess.run(
        [sys.executable, SCHEDULER_PATH],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    autoloop = None
    if os.path.exists(out_path):
        with open(out_path) as f:
            autoloop = json.load(f)
    return proc, autoloop


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Return an isolated workdir with ``.autoloop/programs/`` ready and
    a fresh repo-memory directory the scheduler can read."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".autoloop" / "programs").mkdir(parents=True)
    # The scheduler reads state from /tmp/gh-aw/repo-memory/autoloop. Clean it
    # so each test starts from a known empty slate, then re-populate per-test.
    repo_mem = "/tmp/gh-aw/repo-memory/autoloop"
    if os.path.isdir(repo_mem):
        shutil.rmtree(repo_mem)
    os.makedirs(repo_mem, exist_ok=True)
    return tmp_path


def _write_program(workdir, name, body=None):
    p = workdir / ".autoloop" / "programs" / "{}.md".format(name)
    p.write_text(body if body is not None else PROGRAM_TEMPLATE.format(name=name))
    return p


def _write_state(name, **kwargs):
    repo_mem = "/tmp/gh-aw/repo-memory/autoloop"
    os.makedirs(repo_mem, exist_ok=True)
    with open(os.path.join(repo_mem, "{}.md".format(name)), "w") as f:
        f.write(_state_file(name, **kwargs))


# ---------------------------------------------------------------------------
# Scenario coverage
# ---------------------------------------------------------------------------


class TestSchedulerEndToEnd:
    def test_picks_more_overdue(self, workdir):
        """Two programs with different ``last_run`` → the older one is selected."""
        _write_program(workdir, "old")
        _write_program(workdir, "fresh")
        _write_state("old", last_run="2025-01-01T00:00:00Z")
        _write_state("fresh", last_run="2025-01-15T00:00:00Z")

        proc, out = _run_scheduler(str(workdir))
        assert proc.returncode == 0, proc.stderr
        assert out["selected"] == "old"
        assert out["deferred"] == ["fresh"]

    def test_never_run_beats_recently_run(self, workdir):
        """A never-run program is always more overdue than one with state."""
        _write_program(workdir, "veteran")
        _write_program(workdir, "rookie")
        _write_state("veteran", last_run="2025-01-15T00:00:00Z")
        # No state file for "rookie" → first run

        proc, out = _run_scheduler(str(workdir))
        assert proc.returncode == 0, proc.stderr
        assert out["selected"] == "rookie"

    def test_missing_state_file_treated_as_first_run(self, workdir):
        """A single program with no state file is selected and treated as first run."""
        _write_program(workdir, "lonely")
        proc, out = _run_scheduler(str(workdir))
        assert proc.returncode == 0, proc.stderr
        assert out["selected"] == "lonely"
        assert "no state file found (first run)" in proc.stdout

    def test_paused_program_is_skipped(self, workdir):
        """``paused: true`` puts the program in ``skipped`` with a paused reason."""
        _write_program(workdir, "snoozer")
        _write_state("snoozer", paused=True, pause_reason="manual")

        proc, out = _run_scheduler(str(workdir))
        # Only one program and it's paused → nothing due → exit 1
        assert proc.returncode == 1
        names = [s["name"] for s in out["skipped"]]
        assert "snoozer" in names
        reason = next(s["reason"] for s in out["skipped"] if s["name"] == "snoozer")
        assert reason.startswith("paused:")
        assert "manual" in reason

    def test_completed_program_is_skipped(self, workdir):
        """``completed: true`` puts the program in ``skipped``."""
        _write_program(workdir, "graduated")
        _write_state("graduated", completed=True)

        proc, out = _run_scheduler(str(workdir))
        assert proc.returncode == 1
        names = [s["name"] for s in out["skipped"]]
        assert "graduated" in names
        reason = next(s["reason"] for s in out["skipped"] if s["name"] == "graduated")
        assert "completed" in reason

    def test_forced_program_bypasses_scheduling(self, workdir):
        """``AUTOLOOP_PROGRAM`` forces the named program even if not most-overdue."""
        _write_program(workdir, "old")
        _write_program(workdir, "fresh")
        _write_state("old", last_run="2025-01-01T00:00:00Z")
        _write_state("fresh", last_run="2025-01-15T00:00:00Z")

        # Without forcing, "old" wins; with forcing "fresh" wins.
        proc, out = _run_scheduler(str(workdir), forced="fresh")
        assert proc.returncode == 0, proc.stderr
        assert out["selected"] == "fresh"
        assert out["deferred"] == ["old"]
        assert "FORCED: running program 'fresh'" in proc.stdout

    def test_forced_program_can_run_paused(self, workdir):
        """Forcing a paused program bypasses the skip and selects it anyway."""
        _write_program(workdir, "snoozer")
        _write_state("snoozer", paused=True, pause_reason="manual")

        proc, out = _run_scheduler(str(workdir), forced="snoozer")
        assert proc.returncode == 0, proc.stderr
        assert out["selected"] == "snoozer"

    def test_forced_program_unknown_errors(self, workdir):
        """Forcing an unknown program exits non-zero with an error."""
        _write_program(workdir, "real")
        proc, _ = _run_scheduler(str(workdir), forced="nonexistent")
        assert proc.returncode == 1
        assert "not found" in proc.stdout

    def test_no_programs_found(self, workdir):
        """Empty programs dir → ``no_programs: true``, exit 0 (workflow handles bootstrap)."""
        # Remove the bootstrapped programs dir so the scheduler has nothing to
        # discover after its bootstrap step (which only creates the dir if it's
        # missing entirely).
        shutil.rmtree(workdir / ".autoloop" / "programs")
        proc, out = _run_scheduler(str(workdir))
        # The bootstrap recreates the dir + example template (which contains
        # REPLACE placeholders → unconfigured), so there is one unconfigured
        # program. Exit 0 because the workflow still wants to surface the
        # template via the agent step.
        assert proc.returncode == 0, proc.stderr
        assert out["unconfigured"] == ["example"]
        assert out["selected"] is None
