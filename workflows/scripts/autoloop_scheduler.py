#!/usr/bin/env python3
"""Autoloop scheduler.

Decides which Autoloop program (if any) is due for an iteration. Reads
program definitions from ``.autoloop/programs/`` (directory- and bare-
markdown-based) and from open GitHub issues labelled ``autoloop-program``,
combines them with persisted per-program scheduling state from the
``memory/autoloop`` repo-memory branch, and writes the selection to
``/tmp/gh-aw/autoloop.json`` for the agent step to consume.

Side effects:
    * May bootstrap ``.autoloop/programs/example.md`` on first run.
    * May materialise issue-based program bodies under
      ``/tmp/gh-aw/issue-programs/``.
    * Always writes ``/tmp/gh-aw/autoloop.json``.

Exit codes:
    0  - a program was selected, or there are unconfigured programs to
         report on (the agent step should run).
    1  - nothing to do this run (no due programs, no unconfigured
         programs); the workflow should skip the agent step.

Environment variables:
    GITHUB_TOKEN       - token used to query the issues API.
    GITHUB_REPOSITORY  - ``owner/repo`` slug.
    AUTOLOOP_PROGRAM   - optional program name to force (bypasses
                         scheduling, but unconfigured programs are still
                         rejected).

This file is the standalone counterpart of the inline scheduler that
previously lived in ``workflows/autoloop.md``. Extracting it keeps the
compiled ``run:`` step small (avoiding GitHub Actions' inline-expression
size limit) and makes the logic unit-testable from ``tests/``.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PROGRAMS_DIR = ".autoloop/programs"
TEMPLATE_FILE = os.path.join(PROGRAMS_DIR, "example.md")

# Repo-memory files are cloned to /tmp/gh-aw/repo-memory/{id}/ where {id}
# is derived from the branch-name configured in the tools section
# (memory/autoloop -> autoloop).
REPO_MEMORY_DIR = "/tmp/gh-aw/repo-memory/autoloop"

ISSUE_PROGRAMS_DIR = "/tmp/gh-aw/issue-programs"
OUTPUT_DIR = "/tmp/gh-aw"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "autoloop.json")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def parse_machine_state(content):
    """Parse the ⚙️ Machine State table from a state file. Returns a dict."""
    state = {}
    m = re.search(r"## ⚙️ Machine State.*?\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not m:
        return state
    section = m.group(0)
    for row in re.finditer(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|", section):
        raw_key = row.group(1).strip()
        raw_val = row.group(2).strip()
        if raw_key.lower() in ("field", "---", ":---", ":---:", "---:"):
            continue
        key = raw_key.lower().replace(" ", "_")
        val = None if raw_val in ("—", "-", "") else raw_val
        state[key] = val
    # Coerce types
    for int_field in ("iteration_count", "consecutive_errors"):
        if int_field in state:
            try:
                state[int_field] = int(state[int_field])
            except (ValueError, TypeError):
                state[int_field] = 0
    if "paused" in state:
        state["paused"] = str(state.get("paused", "")).lower() == "true"
    if "completed" in state:
        state["completed"] = str(state.get("completed", "")).lower() == "true"
    # recent_statuses: stored as comma-separated words (e.g. "accepted, rejected, error")
    rs_raw = state.get("recent_statuses") or ""
    if rs_raw:
        state["recent_statuses"] = [s.strip().lower() for s in rs_raw.split(",") if s.strip()]
    else:
        state["recent_statuses"] = []
    return state


def parse_schedule(s):
    """Schedule string to a ``timedelta``; returns ``None`` for invalid input."""
    s = s.strip().lower()
    m = re.match(r"every\s+(\d+)\s*h", s)
    if m:
        return timedelta(hours=int(m.group(1)))
    m = re.match(r"every\s+(\d+)\s*m", s)
    if m:
        return timedelta(minutes=int(m.group(1)))
    if s == "daily":
        return timedelta(hours=24)
    if s == "weekly":
        return timedelta(days=7)
    return None


def get_program_name(pf):
    """Extract program name from a program file path.

    Directory-based: ``.autoloop/programs/<name>/program.md`` -> ``<name>``
    Bare markdown:   ``.autoloop/programs/<name>.md`` -> ``<name>``
    Issue-based:     ``/tmp/gh-aw/issue-programs/<name>.md`` -> ``<name>``
    """
    if pf.endswith("/program.md"):
        return os.path.basename(os.path.dirname(pf))
    return os.path.splitext(os.path.basename(pf))[0]


def slugify_issue_title(title, number=None):
    """Slugify a GitHub issue title into a program name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)  # collapse consecutive hyphens
    if not slug:
        slug = "issue-{}".format(number) if number is not None else "issue"
    return slug


def parse_link_header(header):
    """Parse the GitHub API ``Link`` header and return the ``rel="next"`` URL."""
    if not header:
        return None
    for part in header.split(","):
        section = part.strip()
        m = re.match(r'^<([^>]+)>;\s*rel="next"$', section)
        if m:
            return m.group(1)
    return None


def parse_program_frontmatter(content):
    """Parse optional YAML frontmatter for ``schedule`` and ``target-metric``.

    Returns ``(schedule_delta, target_metric, target_metric_invalid_value)``.
    The third element is the raw string of an invalid ``target-metric`` value
    (so the caller can warn), or ``None`` when the value parsed cleanly or was
    absent.
    """
    # Strip leading HTML comments before checking (issue-based programs may have them).
    content_stripped = re.sub(r"^(\s*<!--.*?-->\s*\n)*", "", content, flags=re.DOTALL)
    schedule_delta = None
    target_metric = None
    target_metric_invalid = None
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content_stripped, re.DOTALL)
    if not fm_match:
        return schedule_delta, target_metric, target_metric_invalid
    for line in fm_match.group(1).split("\n"):
        if line.strip().startswith("schedule:"):
            schedule_str = line.split(":", 1)[1].strip()
            schedule_delta = parse_schedule(schedule_str)
        if line.strip().startswith("target-metric:"):
            raw = line.split(":", 1)[1].strip()
            try:
                target_metric = float(raw)
            except (ValueError, TypeError):
                target_metric_invalid = raw
    return schedule_delta, target_metric, target_metric_invalid


def is_unconfigured(content):
    """Return True if a program file still contains the unconfigured sentinel
    or any TODO/REPLACE placeholder."""
    if "<!-- AUTOLOOP:UNCONFIGURED -->" in content:
        return True
    if re.search(r"\bTODO\b|\bREPLACE", content):
        return True
    return False


def check_skip_conditions(state):
    """Return ``(should_skip, reason)`` based on the program state."""
    if str(state.get("completed", "")).lower() == "true" or state.get("completed") is True:
        return True, "completed: target metric reached"
    if state.get("paused"):
        return True, "paused: {}".format(state.get("pause_reason", "unknown"))
    recent = state.get("recent_statuses", [])[-5:]
    if len(recent) >= 5 and all(s == "rejected" for s in recent):
        return True, "plateau: 5 consecutive rejections"
    return False, None


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def read_program_state(program_name, repo_memory_dir=REPO_MEMORY_DIR):
    """Read scheduling state from the repo-memory state file (or ``{}``)."""
    state_file = os.path.join(repo_memory_dir, "{}.md".format(program_name))
    if not os.path.isfile(state_file):
        print("  {}: no state file found (first run)".format(program_name))
        return {}
    with open(state_file, encoding="utf-8") as f:
        content = f.read()
    return parse_machine_state(content)


def _bootstrap_template_if_missing():
    """Create ``.autoloop/programs/example.md`` if the directory is missing."""
    if os.path.isdir(PROGRAMS_DIR):
        return
    os.makedirs(PROGRAMS_DIR, exist_ok=True)
    bt = chr(96)  # backtick — keep gh-aw compiler happy if this ever gets inlined
    template = "\n".join([
        "<!-- AUTOLOOP:UNCONFIGURED -->",
        "<!-- Remove the line above once you have filled in your program. -->",
        "<!-- Autoloop will NOT run until you do. -->",
        "",
        "# Autoloop Program",
        "",
        "<!-- Rename this file to something meaningful (e.g. training.md, coverage.md).",
        "     The filename (minus .md) becomes the program name used in issues, PRs,",
        "     and slash commands. Want multiple loops? Add more .md files here. -->",
        "",
        "## Goal",
        "",
        "<!-- Describe what you want to optimize. Be specific about what 'better' means. -->",
        "",
        "REPLACE THIS with your optimization goal.",
        "",
        "## Target",
        "",
        "<!-- List files Autoloop may modify. Everything else is off-limits. -->",
        "",
        "Only modify these files:",
        "- {bt}REPLACE_WITH_FILE{bt} -- (describe what this file does)".format(bt=bt),
        "",
        "Do NOT modify:",
        "- (list files that must not be touched)",
        "",
        "## Evaluation",
        "",
        "<!-- Provide a command and the metric to extract. -->",
        "",
        "{bt}{bt}{bt}bash".format(bt=bt),
        "REPLACE_WITH_YOUR_EVALUATION_COMMAND",
        "{bt}{bt}{bt}".format(bt=bt),
        "",
        "The metric is {bt}REPLACE_WITH_METRIC_NAME{bt}. **Lower/Higher is better.** (pick one)".format(bt=bt),
        "",
    ])
    with open(TEMPLATE_FILE, "w") as f:
        f.write(template)
    # Leave the template unstaged — the agent will create a draft PR with it
    print("BOOTSTRAPPED: created {} locally (agent will create a draft PR)".format(TEMPLATE_FILE))


def _scan_directory_programs():
    """Return paths of directory-based programs under ``PROGRAMS_DIR``."""
    out = []
    if not os.path.isdir(PROGRAMS_DIR):
        return out
    for entry in sorted(os.listdir(PROGRAMS_DIR)):
        prog_dir = os.path.join(PROGRAMS_DIR, entry)
        if os.path.isdir(prog_dir):
            prog_file = os.path.join(prog_dir, "program.md")
            if os.path.isfile(prog_file):
                out.append(prog_file)
    return out


def _scan_bare_programs():
    """Return paths of bare-markdown programs under ``PROGRAMS_DIR``."""
    return sorted(glob.glob(os.path.join(PROGRAMS_DIR, "*.md")))


def _fetch_issue_programs(repo, github_token):
    """Fetch open issues with the ``autoloop-program`` label and write their
    bodies to ``ISSUE_PROGRAMS_DIR``. Returns ``(program_files, issue_programs)``.

    Errors are swallowed (with a warning) so a transient API failure doesn't
    block the run for non-issue-based programs.
    """
    program_files = []
    issue_programs = {}
    os.makedirs(ISSUE_PROGRAMS_DIR, exist_ok=True)
    next_url = (
        "https://api.github.com/repos/{}/issues"
        "?labels=autoloop-program&state=open&per_page=100".format(repo)
    )
    headers = {
        "Authorization": "token {}".format(github_token),
        "Accept": "application/vnd.github.v3+json",
    }
    issues = []
    try:
        while next_url:
            req = urllib.request.Request(next_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                page = json.loads(resp.read().decode())
                link_header = resp.headers.get("link") or resp.headers.get("Link")
            issues.extend(page)
            next_url = parse_link_header(link_header)
        for issue in issues:
            if issue.get("pull_request"):
                continue  # skip PRs
            body = issue.get("body") or ""
            title = issue.get("title") or ""
            number = issue["number"]
            slug = slugify_issue_title(title, number)
            if slug in issue_programs:
                print(
                    "  Warning: slug '{}' (issue #{}) collides with issue #{}, "
                    "appending issue number".format(
                        slug, number, issue_programs[slug]["issue_number"]
                    )
                )
                slug = "{}-{}".format(slug, number)
            issue_file = os.path.join(ISSUE_PROGRAMS_DIR, "{}.md".format(slug))
            with open(issue_file, "w") as f:
                f.write(body)
            program_files.append(issue_file)
            issue_programs[slug] = {"issue_number": number, "file": issue_file, "title": title}
            print("  Found issue-based program: '{}' (issue #{})".format(slug, number))
    except Exception as e:  # noqa: BLE001 -- best-effort; logged below
        print("  Warning: could not fetch issue-based programs: {}".format(e))
    return program_files, issue_programs


def _parse_target_metric_from_file(path):
    """Re-parse a program file to extract its ``target-metric``, if any."""
    try:
        with open(path) as f:
            _, target_metric, _ = parse_program_frontmatter(f.read())
        return target_metric
    except (OSError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Existing PR lookup (single-PR-per-program invariant)
# ---------------------------------------------------------------------------


def _http_get_json(url, headers, timeout=30):
    """Open ``url`` and return ``(parsed_body, link_header)``.

    Returns ``(None, None)`` on any HTTP/network error so callers can fall
    through to the next strategy. Broken out into a module-level helper so
    tests can monkey-patch it without touching ``urllib`` directly.
    """
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            link_header = resp.headers.get("link") or resp.headers.get("Link")
            return body, link_header
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None, None


def find_existing_pr_for_branch(repo, program_name, github_token, http_get_json=_http_get_json):
    """Look up the open draft PR (if any) for ``autoloop/{program_name}``.

    Returns the PR number, or ``None`` if none is found.

    The single-PR-per-program invariant requires that we never open a second
    draft PR for the same program. The agent uses the returned ``existing_pr``
    to decide between ``create-pull-request`` (only if ``None``) and
    ``push-to-pull-request-branch`` (always preferred when an open PR exists).

    We also tolerate legacy framework-suffixed branch names of the form
    ``autoloop/{program}-<6-40 hex chars>`` so installations upgrading from
    before ``preserve-branch-name: true`` was set find their in-flight PR
    rather than opening a second one.
    """
    if not repo or not program_name or not github_token:
        return None
    owner = repo.split("/", 1)[0]
    canonical_branch = "autoloop/{}".format(program_name)
    headers = {
        "Authorization": "token {}".format(github_token),
        "Accept": "application/vnd.github.v3+json",
    }
    # Strategy 1: exact canonical branch name via the head= filter.
    head_q = urllib.parse.quote("{}:{}".format(owner, canonical_branch), safe="")
    url = "https://api.github.com/repos/{}/pulls?head={}&state=open".format(repo, head_q)
    body, _ = http_get_json(url, headers)
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, dict) and first.get("number"):
            return first["number"]

    # Strategy 2: paginate open PRs and match either a legacy framework-suffixed
    # branch (``autoloop/{name}-<6-40 hex>``) or a ``[Autoloop: {name}]`` title prefix.
    suffix_regex = re.compile(
        r"^autoloop/" + re.escape(program_name) + r"(-[0-9a-f]{6,40})?$"
    )
    title_prefix = "[Autoloop: {}]".format(program_name)
    next_url = "https://api.github.com/repos/{}/pulls?state=open&per_page=100".format(repo)
    while next_url:
        body, link_header = http_get_json(next_url, headers)
        if not isinstance(body, list):
            break
        for pr in body:
            if not isinstance(pr, dict):
                continue
            head_ref = ""
            head = pr.get("head") or {}
            if isinstance(head, dict):
                head_ref = head.get("ref") or ""
            if suffix_regex.match(head_ref):
                return pr.get("number")
            title = pr.get("title")
            if isinstance(title, str) and title.startswith(title_prefix):
                return pr.get("number")
        next_url = parse_link_header(link_header)
    return None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def select_program(due, forced_program=None, all_programs=None, unconfigured=None, issue_programs=None):
    """Pick the program to run.

    Returns ``(selected, selected_file, selected_issue, selected_target_metric,
    deferred, error)``. ``error`` is a string describing why a forced selection
    failed (and the caller should ``sys.exit(1)``); otherwise it is ``None``.
    """
    all_programs = all_programs or {}
    unconfigured = unconfigured or []
    issue_programs = issue_programs or {}
    if forced_program:
        if forced_program not in all_programs:
            return (
                None, None, None, None, [],
                "requested program '{}' not found. Available programs: {}".format(
                    forced_program, list(all_programs.keys())
                ),
            )
        if forced_program in unconfigured:
            return (
                None, None, None, None, [],
                "requested program '{}' is unconfigured (has placeholders).".format(
                    forced_program
                ),
            )
        selected = forced_program
        selected_file = all_programs[forced_program]
        deferred = [p["name"] for p in due if p["name"] != forced_program]
        selected_issue = (
            issue_programs[selected]["issue_number"] if selected in issue_programs else None
        )
        selected_target_metric = None
        for p in due:
            if p["name"] == forced_program:
                selected_target_metric = p.get("target_metric")
                break
        if selected_target_metric is None:
            selected_target_metric = _parse_target_metric_from_file(selected_file)
        return selected, selected_file, selected_issue, selected_target_metric, deferred, None

    if due:
        # Normal scheduling: pick the single most-overdue program.
        # ``last_run`` of None/empty sorts first (never run).
        due_sorted = sorted(due, key=lambda p: p["last_run"] or "")
        selected = due_sorted[0]["name"]
        selected_file = due_sorted[0]["file"]
        selected_target_metric = due_sorted[0].get("target_metric")
        deferred = [p["name"] for p in due_sorted[1:]]
        selected_issue = (
            issue_programs[selected]["issue_number"] if selected in issue_programs else None
        )
        return selected, selected_file, selected_issue, selected_target_metric, deferred, None

    return None, None, None, None, [], None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    forced_program = os.environ.get("AUTOLOOP_PROGRAM", "").strip()

    _bootstrap_template_if_missing()

    # Find all program files from all locations:
    # 1. Directory-based programs: .autoloop/programs/<name>/program.md (preferred)
    # 2. Bare markdown programs: .autoloop/programs/<name>.md (simple)
    # 3. Issue-based programs: GitHub issues with the 'autoloop-program' label
    program_files = []
    program_files.extend(_scan_directory_programs())
    program_files.extend(_scan_bare_programs())
    issue_files, issue_programs = _fetch_issue_programs(repo, github_token)
    program_files.extend(issue_files)

    if not program_files:
        # Fallback to single-file locations
        for path in [".autoloop/program.md", "program.md"]:
            if os.path.isfile(path):
                program_files = [path]
                break

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not program_files:
        print("NO_PROGRAMS_FOUND")
        with open(OUTPUT_FILE, "w") as f:
            json.dump(
                {
                    "due": [],
                    "skipped": [],
                    "unconfigured": [],
                    "no_programs": True,
                    "head_branch": None,
                    "existing_pr": None,
                },
                f,
            )
        sys.exit(0)

    now = datetime.now(timezone.utc)
    due = []
    skipped = []
    unconfigured = []
    all_programs = {}  # name -> file path

    for pf in program_files:
        name = get_program_name(pf)
        all_programs[name] = pf
        with open(pf) as f:
            content = f.read()

        if is_unconfigured(content):
            unconfigured.append(name)
            continue

        schedule_delta, target_metric, invalid_target = parse_program_frontmatter(content)
        if invalid_target is not None:
            print("  Warning: {} has invalid target-metric value: {}".format(name, invalid_target))

        # Read state from repo-memory
        state = read_program_state(name)
        if state:
            print(
                "  {}: last_run={}, iteration_count={}".format(
                    name, state.get("last_run"), state.get("iteration_count")
                )
            )
        else:
            print("  {}: no state found (first run)".format(name))

        last_run = None
        lr = state.get("last_run")
        if lr:
            try:
                last_run = datetime.fromisoformat(lr.replace("Z", "+00:00"))
            except ValueError:
                pass

        should_skip, reason = check_skip_conditions(state)
        if should_skip:
            skipped.append({"name": name, "reason": reason})
            continue

        # Check if due based on per-program schedule
        if schedule_delta and last_run and now - last_run < schedule_delta:
            skipped.append(
                {
                    "name": name,
                    "reason": "not due yet",
                    "next_due": (last_run + schedule_delta).isoformat(),
                }
            )
            continue

        due.append({"name": name, "last_run": lr, "file": pf, "target_metric": target_metric})

    selected, selected_file, selected_issue, selected_target_metric, deferred, error = (
        select_program(due, forced_program, all_programs, unconfigured, issue_programs)
    )

    if error:
        print("ERROR: {}".format(error))
        sys.exit(1)

    if forced_program and selected:
        print("FORCED: running program '{}' (manual dispatch)".format(forced_program))

    # Look up the existing draft PR (if any) for the selected program, so the
    # agent can enforce the single-PR-per-program invariant: never call
    # create-pull-request when a PR for autoloop/{name} already exists.
    # head_branch is always the canonical name (no suffix, no hash).
    head_branch = None
    existing_pr = None
    if selected:
        head_branch = "autoloop/{}".format(selected)
        try:
            existing_pr = find_existing_pr_for_branch(repo, selected, github_token)
        except Exception as e:  # noqa: BLE001 -- best-effort lookup
            print("  Warning: existing PR lookup failed for {}: {}".format(selected, e))
            existing_pr = None

    result = {
        "selected": selected,
        "selected_file": selected_file,
        "selected_issue": selected_issue,
        "selected_target_metric": selected_target_metric,
        "issue_programs": {
            name: info["issue_number"] for name, info in issue_programs.items()
        },
        "deferred": deferred,
        "skipped": skipped,
        "unconfigured": unconfigured,
        "no_programs": False,
        "head_branch": head_branch,
        "existing_pr": existing_pr,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print("=== Autoloop Program Check ===")
    print("Selected program:      {} ({})".format(selected or "(none)", selected_file or "n/a"))
    print("Deferred (next run):   {}".format(deferred or "(none)"))
    print("Programs skipped:      {}".format([s["name"] for s in skipped] or "(none)"))
    print("Programs unconfigured: {}".format(unconfigured or "(none)"))

    if not selected and not unconfigured:
        print("\nNo programs due this run. Exiting early.")
        sys.exit(1)  # Non-zero exit skips the agent step


if __name__ == "__main__":
    main()
