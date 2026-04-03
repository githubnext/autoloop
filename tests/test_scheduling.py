"""Tests for the scheduling pre-step in workflows/autoloop.md.

Functions are extracted directly from the workflow heredoc at import time
(see conftest.py) — there is no separate copy of the scheduling code.

For inline logic (slugify, frontmatter parsing, skip conditions, etc.) that
isn't wrapped in a function def in the workflow, we write thin test helpers
that replicate the exact inline pattern. These are documented with the
workflow source lines they correspond to.
"""

import re
from datetime import datetime, timezone, timedelta
from conftest import _funcs

# ---------------------------------------------------------------------------
# Functions extracted from the workflow via AST (see conftest.py)
# ---------------------------------------------------------------------------
parse_schedule = _funcs["parse_schedule"]
parse_machine_state = _funcs["parse_machine_state"]
get_program_name = _funcs["get_program_name"]


# ---------------------------------------------------------------------------
# Thin helpers that replicate inline workflow patterns (not function defs).
# Each documents the workflow source lines it mirrors.
# ---------------------------------------------------------------------------

def slugify_issue_title(title):
    """Replicates the inline slug logic at workflows/autoloop.md lines 236-237."""
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    slug = re.sub(r'-+', '-', slug)
    return slug


def parse_frontmatter(content):
    """Replicates the inline frontmatter parsing at workflows/autoloop.md lines 316-330."""
    content_stripped = re.sub(r'^(\s*<!--.*?-->\s*\n)*', '', content, flags=re.DOTALL)
    schedule_delta = None
    target_metric = None
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content_stripped, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split("\n"):
            if line.strip().startswith("schedule:"):
                schedule_str = line.split(":", 1)[1].strip()
                schedule_delta = parse_schedule(schedule_str)
            if line.strip().startswith("target-metric:"):
                try:
                    target_metric = float(line.split(":", 1)[1].strip())
                except (ValueError, TypeError):
                    pass
    return schedule_delta, target_metric


def is_unconfigured(content):
    """Replicates the inline unconfigured check at workflows/autoloop.md lines 306-312."""
    if "<!-- AUTOLOOP:UNCONFIGURED -->" in content:
        return True
    if re.search(r'\bTODO\b|\bREPLACE', content):
        return True
    return False


def check_skip_conditions(state):
    """Replicates the inline skip logic at workflows/autoloop.md lines 347-361.

    Returns (should_skip, reason).
    """
    # Line 348: completed check
    if str(state.get("completed", "")).lower() == "true" or state.get("completed") is True:
        return True, "completed: target metric reached"
    # Line 353: paused check
    if state.get("paused"):
        return True, f"paused: {state.get('pause_reason', 'unknown')}"
    # Lines 357-361: plateau check
    recent = state.get("recent_statuses", [])[-5:]
    if len(recent) >= 5 and all(s == "rejected" for s in recent):
        return True, "plateau: 5 consecutive rejections"
    return False, None


def check_if_due(schedule_delta, last_run, now):
    """Replicates the inline due check at workflows/autoloop.md lines 363-368.

    Returns (is_due, next_due_iso).
    """
    if schedule_delta and last_run:
        if now - last_run < schedule_delta:
            return False, (last_run + schedule_delta).isoformat()
    return True, None


def select_program(due, forced_program=None, all_programs=None, unconfigured=None, issue_programs=None):
    """Replicates the selection logic at workflows/autoloop.md lines 379-409.

    Returns (selected, selected_file, selected_issue, selected_target_metric, deferred, error).
    """
    all_programs = all_programs or {}
    unconfigured = unconfigured or []
    issue_programs = issue_programs or {}

    if forced_program:
        if forced_program not in all_programs:
            return None, None, None, None, [], f"program '{forced_program}' not found"
        if forced_program in unconfigured:
            return None, None, None, None, [], f"program '{forced_program}' is unconfigured"
        selected = forced_program
        selected_file = all_programs[forced_program]
        deferred = [p["name"] for p in due if p["name"] != forced_program]
        selected_issue = issue_programs.get(selected)
        selected_target_metric = None
        for p in due:
            if p["name"] == forced_program:
                selected_target_metric = p.get("target_metric")
                break
        return selected, selected_file, selected_issue, selected_target_metric, deferred, None
    elif due:
        due.sort(key=lambda p: p["last_run"] or "")
        selected = due[0]["name"]
        selected_file = due[0]["file"]
        selected_target_metric = due[0].get("target_metric")
        deferred = [p["name"] for p in due[1:]]
        selected_issue = issue_programs.get(selected)
        return selected, selected_file, selected_issue, selected_target_metric, deferred, None

    return None, None, None, None, [], None


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
# slugify_issue_title (inline pattern, lines 236-237)
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
        """Replicates the slug collision dedup at workflows/autoloop.md lines 240-242."""
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
# parse_frontmatter (inline pattern, lines 316-330)
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
# is_unconfigured (inline pattern, lines 306-312)
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
# check_skip_conditions (inline pattern, lines 347-361)
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
# check_if_due (inline pattern, lines 363-368)
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
# select_program (inline pattern, lines 379-409)
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
        issue_progs = {"my-issue": 42}
        selected, file, issue, target, deferred, err = select_program(
            due, forced_program="my-issue", all_programs=all_progs, issue_programs=issue_progs
        )
        assert selected == "my-issue"
        assert issue == 42

    def test_issue_program_selected_normally(self):
        due = [
            {"name": "my-issue", "last_run": None, "file": "/tmp/my-issue.md", "target_metric": None},
        ]
        issue_progs = {"my-issue": 7}
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
        # directly from the program file (workflows/autoloop.md lines 399-410).
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
# Extraction sanity check — verify conftest.py found the expected functions
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_parse_schedule_extracted(self):
        assert callable(parse_schedule)

    def test_parse_machine_state_extracted(self):
        assert callable(parse_machine_state)

    def test_get_program_name_extracted(self):
        assert callable(get_program_name)

    def test_read_program_state_extracted(self):
        # read_program_state exists in the workflow but depends on file I/O
        assert "read_program_state" in _funcs
