"""Tests for the standalone Autoloop scheduler.

The scheduler module is imported directly (see ``conftest.py``); functions are
exercised in-process. A few thin helpers below match the legacy 2-tuple/no-args
shapes used by the tests, while delegating to the shared scheduler module.
"""

import re
from datetime import datetime, timezone, timedelta
from conftest import _funcs, autoloop_scheduler

# ---------------------------------------------------------------------------
# Functions exposed by the scheduler module
# ---------------------------------------------------------------------------
parse_schedule = _funcs["parse_schedule"]
parse_machine_state = _funcs["parse_machine_state"]
get_program_name = _funcs["get_program_name"]
parse_link_header = _funcs["parse_link_header"]
is_unconfigured = autoloop_scheduler.is_unconfigured
check_skip_conditions = autoloop_scheduler.check_skip_conditions
select_program = autoloop_scheduler.select_program


# ---------------------------------------------------------------------------
# Thin helpers preserving the legacy test-helper shapes.
# ---------------------------------------------------------------------------

def slugify_issue_title(title):
    """Slugify a title (the workflow's inline issue-scanning slug logic).

    The scheduler module's ``slugify_issue_title`` falls back to ``"issue"``
    when no number is provided and the title slugifies to empty; the original
    inline workflow code only fell back when ``number`` was known. This helper
    preserves the original behaviour by passing through an empty string.
    """
    slug = re.sub(r'[^a-z0-9]+', '-', (title or '').lower()).strip('-')
    slug = re.sub(r'-+', '-', slug)
    return slug


def parse_frontmatter(content):
    """Two-tuple wrapper over the scheduler's three-tuple frontmatter parser."""
    schedule_delta, target_metric, _ = autoloop_scheduler.parse_program_frontmatter(content)
    return schedule_delta, target_metric


def check_if_due(schedule_delta, last_run, now):
    """Replicates the inline due check: ``(is_due, next_due_iso_or_None)``."""
    if schedule_delta and last_run:
        if now - last_run < schedule_delta:
            return False, (last_run + schedule_delta).isoformat()
    return True, None


# ===========================================================================
# Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# parse_schedule (extracted from workflow)
# ---------------------------------------------------------------------------

class TestParseSchedule:
    def test_every_hours(self):
        assert parse_schedule("every 6h") == timedelta(hours=6)

    def test_every_1_hour(self):
        assert parse_schedule("every 1h") == timedelta(hours=1)

    def test_every_24_hours(self):
        assert parse_schedule("every 24h") == timedelta(hours=24)

    def test_every_minutes(self):
        assert parse_schedule("every 30m") == timedelta(minutes=30)

    def test_every_1_minute(self):
        assert parse_schedule("every 1m") == timedelta(minutes=1)

    def test_daily(self):
        assert parse_schedule("daily") == timedelta(hours=24)

    def test_weekly(self):
        assert parse_schedule("weekly") == timedelta(days=7)

    def test_whitespace(self):
        assert parse_schedule("  every  6h  ") == timedelta(hours=6)

    def test_case_insensitive(self):
        assert parse_schedule("Every 6H") == timedelta(hours=6)
        assert parse_schedule("DAILY") == timedelta(hours=24)
        assert parse_schedule("Weekly") == timedelta(days=7)

    def test_invalid_returns_none(self):
        assert parse_schedule("bogus") is None

    def test_empty_returns_none(self):
        assert parse_schedule("") is None

    def test_just_whitespace_returns_none(self):
        assert parse_schedule("   ") is None

    def test_monthly_not_supported(self):
        assert parse_schedule("monthly") is None

    def test_every_without_unit(self):
        assert parse_schedule("every 6") is None


# ---------------------------------------------------------------------------
# parse_machine_state (extracted from workflow)
# ---------------------------------------------------------------------------

SAMPLE_STATE = """\
# Autoloop: test-program

## ⚙️ Machine State

> Updated automatically.

| Field | Value |
|-------|-------|
| Last Run | 2025-01-15T12:00:00Z |
| Iteration Count | 42 |
| Best Metric | 0.85 |
| Target Metric | 0.95 |
| Paused | false |
| Pause Reason | — |
| Completed | false |
| Completed Reason | — |
| Consecutive Errors | 0 |
| Recent Statuses | accepted, rejected, accepted |

## 📋 Program Info

More content here.
"""


class TestParseMachineState:
    def test_basic_fields(self):
        state = parse_machine_state(SAMPLE_STATE)
        assert state["last_run"] == "2025-01-15T12:00:00Z"
        assert state["best_metric"] == "0.85"
        assert state["target_metric"] == "0.95"

    def test_int_coercion(self):
        state = parse_machine_state(SAMPLE_STATE)
        assert state["iteration_count"] == 42
        assert isinstance(state["iteration_count"], int)
        assert state["consecutive_errors"] == 0
        assert isinstance(state["consecutive_errors"], int)

    def test_bool_coercion_false(self):
        state = parse_machine_state(SAMPLE_STATE)
        assert state["paused"] is False
        assert state["completed"] is False

    def test_bool_coercion_true(self):
        content = SAMPLE_STATE.replace("| Paused | false |", "| Paused | true |")
        content = content.replace("| Completed | false |", "| Completed | true |")
        state = parse_machine_state(content)
        assert state["paused"] is True
        assert state["completed"] is True

    def test_dash_is_none(self):
        state = parse_machine_state(SAMPLE_STATE)
        assert state["pause_reason"] is None
        assert state["completed_reason"] is None

    def test_recent_statuses_list(self):
        state = parse_machine_state(SAMPLE_STATE)
        assert state["recent_statuses"] == ["accepted", "rejected", "accepted"]

    def test_recent_statuses_empty(self):
        content = SAMPLE_STATE.replace(
            "| Recent Statuses | accepted, rejected, accepted |",
            "| Recent Statuses | — |",
        )
        state = parse_machine_state(content)
        assert state["recent_statuses"] == []

    def test_missing_section(self):
        state = parse_machine_state("# No machine state here\n\nJust text.")
        assert state == {}

    def test_empty_content(self):
        state = parse_machine_state("")
        assert state == {}

    def test_malformed_int(self):
        content = SAMPLE_STATE.replace("| Iteration Count | 42 |", "| Iteration Count | not-a-number |")
        state = parse_machine_state(content)
        assert state["iteration_count"] == 0

    def test_skips_header_row(self):
        state = parse_machine_state(SAMPLE_STATE)
        assert "field" not in state
        assert "value" not in state

    def test_five_consecutive_rejections(self):
        content = SAMPLE_STATE.replace(
            "| Recent Statuses | accepted, rejected, accepted |",
            "| Recent Statuses | rejected, rejected, rejected, rejected, rejected |",
        )
        state = parse_machine_state(content)
        assert state["recent_statuses"] == ["rejected"] * 5

    def test_bool_string_true_case_insensitive(self):
        content = SAMPLE_STATE.replace("| Paused | false |", "| Paused | True |")
        state = parse_machine_state(content)
        assert state["paused"] is True

        content2 = SAMPLE_STATE.replace("| Paused | false |", "| Paused | TRUE |")
        state2 = parse_machine_state(content2)
        assert state2["paused"] is True


# ---------------------------------------------------------------------------
# get_program_name (extracted from workflow)
# ---------------------------------------------------------------------------

class TestGetProgramName:
    def test_directory_based(self):
        assert get_program_name("programs/function_minimization/program.md") == "function_minimization"

    def test_directory_based_nested(self):
        assert get_program_name("programs/my-experiment/program.md") == "my-experiment"

    def test_bare_markdown(self):
        assert get_program_name(".autoloop/programs/coverage.md") == "coverage"

    def test_issue_based(self):
        assert get_program_name("/tmp/gh-aw/issue-programs/improve-tests.md") == "improve-tests"

    def test_absolute_path_directory(self):
        assert get_program_name("/home/user/repo/programs/foo/program.md") == "foo"


# ---------------------------------------------------------------------------
# slugify_issue_title (inline pattern, issue scanning section)
# ---------------------------------------------------------------------------

class TestSlugifyIssueTitle:
    def test_simple(self):
        assert slugify_issue_title("Improve Test Coverage") == "improve-test-coverage"

    def test_special_characters(self):
        assert slugify_issue_title("Hello!!! World???") == "hello-world"

    def test_numbers(self):
        assert slugify_issue_title("Phase 2 Optimization") == "phase-2-optimization"

    def test_already_slug(self):
        assert slugify_issue_title("my-program") == "my-program"

    def test_leading_trailing_special(self):
        assert slugify_issue_title("---hello---") == "hello"

    def test_empty(self):
        assert slugify_issue_title("") == ""

    def test_only_special_chars(self):
        assert slugify_issue_title("!!!") == ""

    def test_unicode(self):
        result = slugify_issue_title("café latté")
        assert result == "caf-latt"

    def test_consecutive_hyphens_collapsed(self):
        assert slugify_issue_title("a   b   c") == "a-b-c"

    def test_collision_dedup(self):
        """Replicates the slug collision dedup in the workflow's issue scanning section."""
        # Simulate two issues that slugify to the same name
        issue_programs = {}
        titles = [("Improve Tests", 10), ("improve-tests", 20)]
        for title, number in titles:
            slug = slugify_issue_title(title)
            if not slug:
                slug = f"issue-{number}"
            if slug in issue_programs:
                slug = f"{slug}-{number}"
            issue_programs[slug] = number

        assert "improve-tests" in issue_programs
        assert "improve-tests-20" in issue_programs
        assert len(issue_programs) == 2


# ---------------------------------------------------------------------------
# parse_frontmatter (inline pattern, program scanning loop)
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_schedule_and_target(self):
        content = "---\nschedule: every 6h\ntarget-metric: 0.95\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert schedule == timedelta(hours=6)
        assert target == 0.95

    def test_schedule_only(self):
        content = "---\nschedule: daily\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert schedule == timedelta(hours=24)
        assert target is None

    def test_target_only(self):
        content = "---\ntarget-metric: 0.5\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert schedule is None
        assert target == 0.5

    def test_no_frontmatter(self):
        content = "# Program\n\nNo frontmatter here.\n"
        schedule, target = parse_frontmatter(content)
        assert schedule is None
        assert target is None

    def test_strips_html_comments(self):
        content = "<!-- AUTOLOOP:ISSUE-PROGRAM -->\n<!-- comment -->\n---\nschedule: every 1h\ntarget-metric: 0.8\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert schedule == timedelta(hours=1)
        assert target == 0.8

    def test_invalid_target_metric(self):
        content = "---\ntarget-metric: not-a-number\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert target is None

    def test_commented_target_metric(self):
        content = "---\nschedule: every 6h\n# target-metric: 0.95\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert schedule == timedelta(hours=6)
        assert target is None

    def test_extra_frontmatter_fields_ignored(self):
        content = "---\nschedule: weekly\ntimeout-minutes: 40\ntarget-metric: 1.0\n---\n\n# Program\n"
        schedule, target = parse_frontmatter(content)
        assert schedule == timedelta(days=7)
        assert target == 1.0


# ---------------------------------------------------------------------------
# is_unconfigured (inline pattern, program scanning loop)
# ---------------------------------------------------------------------------

class TestIsUnconfigured:
    def test_sentinel(self):
        assert is_unconfigured("<!-- AUTOLOOP:UNCONFIGURED -->\n# Program") is True

    def test_todo_placeholder(self):
        assert is_unconfigured("# Goal\n\nTODO: fill this in\n") is True

    def test_replace_placeholder(self):
        assert is_unconfigured("REPLACE THIS with your goal.\n") is True

    def test_configured(self):
        content = "---\nschedule: every 6h\n---\n\n# My Program\n\n## Goal\n\nOptimize coverage.\n"
        assert is_unconfigured(content) is False

    def test_replace_in_word_no_match(self):
        assert is_unconfigured("This was replaced.") is False  # lowercase, no match

    def test_issue_template_detected(self):
        content = """\
<!-- AUTOLOOP:ISSUE-PROGRAM -->
---
schedule: every 6h
---

# Program Name

## Goal

REPLACE THIS with your optimization goal.
"""
        assert is_unconfigured(content) is True


# ---------------------------------------------------------------------------
# check_skip_conditions (inline pattern, program scanning loop)
# ---------------------------------------------------------------------------

class TestCheckSkipConditions:
    def test_completed_bool(self):
        skip, reason = check_skip_conditions({"completed": True})
        assert skip is True
        assert "completed" in reason

    def test_completed_string(self):
        skip, reason = check_skip_conditions({"completed": "true"})
        assert skip is True

    def test_not_completed(self):
        skip, reason = check_skip_conditions({"completed": False})
        assert skip is False

    def test_paused(self):
        skip, reason = check_skip_conditions({"paused": True, "pause_reason": "manual"})
        assert skip is True
        assert "paused" in reason
        assert "manual" in reason

    def test_not_paused(self):
        skip, reason = check_skip_conditions({"paused": False})
        assert skip is False

    def test_plateau(self):
        state = {"recent_statuses": ["rejected"] * 5}
        skip, reason = check_skip_conditions(state)
        assert skip is True
        assert "plateau" in reason

    def test_four_rejections_not_plateau(self):
        state = {"recent_statuses": ["rejected"] * 4}
        skip, reason = check_skip_conditions(state)
        assert skip is False

    def test_mixed_statuses_no_plateau(self):
        state = {"recent_statuses": ["rejected", "rejected", "accepted", "rejected", "rejected"]}
        skip, reason = check_skip_conditions(state)
        assert skip is False

    def test_plateau_checks_last_five(self):
        state = {"recent_statuses": ["accepted", "rejected", "rejected", "rejected", "rejected", "rejected"]}
        skip, reason = check_skip_conditions(state)
        assert skip is True

    def test_empty_state(self):
        skip, reason = check_skip_conditions({})
        assert skip is False

    def test_completed_takes_priority_over_paused(self):
        skip, reason = check_skip_conditions({"completed": True, "paused": True})
        assert skip is True
        assert "completed" in reason


# ---------------------------------------------------------------------------
# check_if_due (inline pattern, program scanning loop)
# ---------------------------------------------------------------------------

class TestCheckIfDue:
    def test_no_schedule_always_due(self):
        now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        is_due, _ = check_if_due(None, last, now)
        assert is_due is True

    def test_no_last_run_always_due(self):
        now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        is_due, _ = check_if_due(timedelta(hours=6), None, now)
        assert is_due is True

    def test_due_past_schedule(self):
        now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 15, 5, 0, tzinfo=timezone.utc)
        is_due, _ = check_if_due(timedelta(hours=6), last, now)
        assert is_due is True

    def test_not_due_yet(self):
        now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        is_due, next_due = check_if_due(timedelta(hours=6), last, now)
        assert is_due is False
        assert next_due is not None

    def test_exactly_on_schedule(self):
        now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 15, 6, 0, tzinfo=timezone.utc)
        is_due, _ = check_if_due(timedelta(hours=6), last, now)
        assert is_due is True

    def test_next_due_timestamp(self):
        now = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
        is_due, next_due = check_if_due(timedelta(hours=6), last, now)
        assert is_due is False
        expected = (last + timedelta(hours=6)).isoformat()
        assert next_due == expected


# ---------------------------------------------------------------------------
# select_program (inline pattern, program selection section)
# ---------------------------------------------------------------------------

class TestSelectProgram:
    def test_most_overdue_selected(self):
        due = [
            {"name": "b", "last_run": "2025-01-15T10:00:00Z", "file": "b.md", "target_metric": None},
            {"name": "a", "last_run": "2025-01-15T06:00:00Z", "file": "a.md", "target_metric": 0.9},
            {"name": "c", "last_run": "2025-01-15T11:00:00Z", "file": "c.md", "target_metric": None},
        ]
        selected, file, issue, target, deferred, err = select_program(due)
        assert selected == "a"
        assert file == "a.md"
        assert target == 0.9
        assert set(deferred) == {"b", "c"}
        assert err is None

    def test_never_run_first(self):
        due = [
            {"name": "old", "last_run": "2025-01-15T06:00:00Z", "file": "old.md", "target_metric": None},
            {"name": "new", "last_run": None, "file": "new.md", "target_metric": None},
        ]
        selected, *_ = select_program(due)
        assert selected == "new"

    def test_empty_due_list(self):
        selected, file, issue, target, deferred, err = select_program([])
        assert selected is None
        assert deferred == []

    def test_forced_program(self):
        due = [
            {"name": "a", "last_run": "2025-01-15T06:00:00Z", "file": "a.md", "target_metric": 0.5},
        ]
        all_progs = {"a": "a.md", "b": "b.md"}
        selected, file, issue, target, deferred, err = select_program(
            due, forced_program="b", all_programs=all_progs
        )
        assert selected == "b"
        assert file == "b.md"
        assert err is None

    def test_forced_program_not_found(self):
        selected, file, issue, target, deferred, err = select_program(
            [], forced_program="missing", all_programs={"a": "a.md"}
        )
        assert selected is None
        assert "not found" in err

    def test_forced_program_unconfigured(self):
        selected, file, issue, target, deferred, err = select_program(
            [], forced_program="a", all_programs={"a": "a.md"}, unconfigured=["a"]
        )
        assert selected is None
        assert "unconfigured" in err

    def test_forced_issue_program(self):
        due = []
        all_progs = {"my-issue": "/tmp/gh-aw/issue-programs/my-issue.md"}
        issue_progs = {"my-issue": {"issue_number": 42, "file": "/tmp/x", "title": "X"}}
        selected, file, issue, target, deferred, err = select_program(
            due, forced_program="my-issue", all_programs=all_progs, issue_programs=issue_progs
        )
        assert selected == "my-issue"
        assert issue == 42

    def test_issue_program_selected_normally(self):
        due = [
            {"name": "my-issue", "last_run": None, "file": "/tmp/my-issue.md", "target_metric": None},
        ]
        issue_progs = {"my-issue": {"issue_number": 7, "file": "/tmp/x", "title": "X"}}
        selected, file, issue, target, deferred, err = select_program(
            due, issue_programs=issue_progs
        )
        assert selected == "my-issue"
        assert issue == 7

    def test_forced_program_gets_target_metric_from_due(self):
        due = [
            {"name": "a", "last_run": "2025-01-15T06:00:00Z", "file": "a.md", "target_metric": 0.99},
        ]
        all_progs = {"a": "a.md"}
        selected, file, issue, target, deferred, err = select_program(
            due, forced_program="a", all_programs=all_progs
        )
        assert target == 0.99

    def test_forced_program_not_in_due_select_returns_none(self):
        # select_program itself returns None for target_metric when program isn't in due.
        # The workflow's forced-program path has a fallback that parses target_metric
        # directly from the program file (see forced-program fallback in the workflow).
        due = []
        all_progs = {"a": "a.md"}
        selected, file, issue, target, deferred, err = select_program(
            due, forced_program="a", all_programs=all_progs
        )
        assert selected == "a"
        assert target is None  # fallback parsing happens in the workflow, not here

    def test_forced_program_target_metric_fallback_via_frontmatter(self):
        # Verify the fallback works: parse_frontmatter extracts target-metric from file content
        content = "---\nschedule: every 6h\ntarget-metric: 0.95\n---\n\n# Program\n"
        _, target = parse_frontmatter(content)
        assert target == 0.95


# ---------------------------------------------------------------------------
# parseLinkHeader — extract next-page URL from GitHub API Link header
# ---------------------------------------------------------------------------

class TestParseLinkHeader:
    def test_returns_null_for_none(self):
        assert parse_link_header(None) is None

    def test_returns_null_for_empty_string(self):
        assert parse_link_header("") is None

    def test_extracts_next_url(self):
        header = '<https://api.github.com/repos/o/r/issues?page=2&per_page=100>; rel="next", <https://api.github.com/repos/o/r/issues?page=5&per_page=100>; rel="last"'
        assert parse_link_header(header) == "https://api.github.com/repos/o/r/issues?page=2&per_page=100"

    def test_returns_null_when_no_next(self):
        header = '<https://api.github.com/repos/o/r/issues?page=1&per_page=100>; rel="prev", <https://api.github.com/repos/o/r/issues?page=5&per_page=100>; rel="last"'
        assert parse_link_header(header) is None

    def test_next_not_first(self):
        """next rel is not the first segment."""
        header = '<https://api.github.com/repos/o/r/issues?page=1&per_page=100>; rel="prev", <https://api.github.com/repos/o/r/issues?page=3&per_page=100>; rel="next", <https://api.github.com/repos/o/r/issues?page=5&per_page=100>; rel="last"'
        assert parse_link_header(header) == "https://api.github.com/repos/o/r/issues?page=3&per_page=100"

    def test_single_next_segment(self):
        header = '<https://api.github.com/repos/o/r/issues?page=2&per_page=100>; rel="next"'
        assert parse_link_header(header) == "https://api.github.com/repos/o/r/issues?page=2&per_page=100"


# ---------------------------------------------------------------------------
# Extraction sanity check — verify conftest.py found the expected functions
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_parse_schedule_extracted(self):
        assert callable(parse_schedule)

    def test_parse_machine_state_extracted(self):
        assert callable(parse_machine_state)

    def test_get_program_name_extracted(self):
        assert callable(get_program_name)

    def test_parse_link_header_extracted(self):
        assert callable(parse_link_header)

    def test_read_program_state_extracted(self):
        # read_program_state exists in the workflow but depends on file I/O
        assert "read_program_state" in _funcs


# ---------------------------------------------------------------------------
# Workflow step ordering — repo-memory must be available before scheduling
# ---------------------------------------------------------------------------

class TestWorkflowStepOrdering:
    """Verify that the repo-memory clone step appears before the scheduling step.

    The scheduling pre-step reads persisted state from repo-memory.  If the
    clone happens after scheduling, the script cannot see previous-run state,
    causing incorrect selection/skip behaviour.
    """

    CLONE_STEP = "Clone repo-memory for scheduling"
    SCHED_STEP = "Check which programs are due"

    def _load_steps(self):
        """Return the list of pre-step names from workflows/autoloop.md."""
        import os
        import re

        wf_path = os.path.join(os.path.dirname(__file__), "..", "workflows", "autoloop.md")
        with open(wf_path) as f:
            content = f.read()
        step_names = []
        for m in re.finditer(r'^\s*-\s*name:\s*(.+)$', content, re.MULTILINE):
            step_names.append(m.group(1).strip())
        return step_names

    def test_clone_step_exists(self):
        """A step that clones repo-memory for scheduling must exist."""
        steps = self._load_steps()
        assert self.CLONE_STEP in steps, (
            f"Expected step '{self.CLONE_STEP}' not found. Steps: {steps}"
        )

    def test_clone_before_scheduling(self):
        """The repo-memory clone step must come before 'Check which programs are due'."""
        steps = self._load_steps()
        clone_idx = steps.index(self.CLONE_STEP)
        sched_idx = steps.index(self.SCHED_STEP)
        assert clone_idx < sched_idx, (
            f"'{self.CLONE_STEP}' (index {clone_idx}) must come before "
            f"'{self.SCHED_STEP}' (index {sched_idx}). Steps: {steps}"
        )


class TestSyncBranchesCredentialOrdering:
    """Verify that Git credentials are configured before the merge/push step.

    The sync-branches workflow merges the default branch into autoloop/*
    branches.  Merge commits require a Git identity (user.name/user.email)
    and pushes/fetches need an authenticated remote URL.  Both must be
    configured before the merge step runs.
    """

    CRED_STEP = "Set up Git identity and authentication"
    MERGE_STEP = "Merge default branch into all autoloop program branches"

    def _load_steps(self):
        """Return the list of pre-step names from workflows/sync-branches.md."""
        import os

        wf_path = os.path.join(os.path.dirname(__file__), "..", "workflows", "sync-branches.md")
        with open(wf_path) as f:
            content = f.read()
        step_names = []
        for m in re.finditer(r'^\s*-\s*name:\s*(.+)$', content, re.MULTILINE):
            step_names.append(m.group(1).strip())
        return step_names

    def _load_lock_steps(self):
        """Return the list of step names from .github/workflows/sync-branches.lock.yml."""
        import os
        import yaml

        lock_path = os.path.join(
            os.path.dirname(__file__), "..", ".github", "workflows", "sync-branches.lock.yml"
        )
        with open(lock_path) as f:
            data = yaml.safe_load(f)
        # Collect step names from the 'agent' job
        steps = data.get("jobs", {}).get("agent", {}).get("steps", [])
        return [s.get("name", "") for s in steps if s.get("name")]

    def test_cred_step_exists(self):
        """A step that configures Git identity/auth must exist in the source."""
        steps = self._load_steps()
        assert self.CRED_STEP in steps, (
            f"Expected step '{self.CRED_STEP}' not found. Steps: {steps}"
        )

    def test_creds_before_merge(self):
        """The credential step must come before the merge step in the source."""
        steps = self._load_steps()
        cred_idx = steps.index(self.CRED_STEP)
        merge_idx = steps.index(self.MERGE_STEP)
        assert cred_idx < merge_idx, (
            f"'{self.CRED_STEP}' (index {cred_idx}) must come before "
            f"'{self.MERGE_STEP}' (index {merge_idx}). Steps: {steps}"
        )

    def test_lock_creds_before_merge(self):
        """In the compiled lock file, Configure Git credentials must come before the merge step."""
        steps = self._load_lock_steps()
        cred_names = [s for s in steps if "Configure Git credentials" in s]
        assert cred_names, (
            f"No 'Configure Git credentials' step found in lock file. Steps: {steps}"
        )
        merge_names = [s for s in steps if "Merge default branch" in s]
        assert merge_names, (
            f"No merge step found in lock file. Steps: {steps}"
        )
        cred_idx = steps.index(cred_names[0])
        merge_idx = steps.index(merge_names[0])
        assert cred_idx < merge_idx, (
            f"'Configure Git credentials' (index {cred_idx}) must come before "
            f"merge step (index {merge_idx}). Steps: {steps}"
        )
