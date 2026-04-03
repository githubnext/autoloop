---
description: |
  An iterative optimization loop inspired by Karpathy's Autoresearch and Claude Code's /loop.
  Runs on a configurable schedule to autonomously improve a target artifact toward a measurable goal.
  Each iteration: reads the program definition, proposes a change, evaluates against a metric,
  and accepts or rejects the change. Tracks all iterations in a rolling GitHub issue.
  - User defines the optimization goal and evaluation criteria in a program.md file
  - Accepts changes only when they improve the metric (ratchet pattern)
  - Persists all state via repo-memory (human-readable, human-editable)
  - Commits accepted improvements to a long-running branch per program
  - Maintains a single draft PR per program that accumulates all accepted iterations
  - Maintains a living experiment log as a GitHub issue

on:
  schedule: every 6h
  workflow_dispatch:
    inputs:
      program:
        description: "Run a specific program by name (bypasses scheduling)"
        required: false
        type: string
  slash_command:
    name: autoloop

permissions: read-all

timeout-minutes: 45

network:
  allowed:
  - defaults
  - node
  - python
  - rust
  - java
  - dotnet

safe-outputs:
  add-comment:
    max: 7
    target: "*"
    hide-older-comments: false
  create-pull-request:
    draft: true
    title-prefix: "[Autoloop] "
    labels: [automation, autoloop]
    protected-files: fallback-to-issue
    max: 2
  push-to-pull-request-branch:
    target: "*"
    title-prefix: "[Autoloop] "
    max: 2
  create-issue:
    title-prefix: "[Autoloop] "
    labels: [automation, autoloop]
    max: 2
  update-issue:
    target: "*"
    title-prefix: "[Autoloop] "
    max: 3
  add-labels:
    target: "*"
    max: 2
  remove-labels:
    target: "*"
    max: 2

checkout:
  fetch: ["*"]
  fetch-depth: 0

tools:
  web-fetch:
  github:
    toolsets: [all]
  bash: true
  repo-memory:
    branch-name: memory/autoloop
    file-glob: ["*.md"]

imports:
  - shared/reporting.md

steps:
  - name: Check which programs are due
    env:
      GITHUB_TOKEN: ${{ github.token }}
      GITHUB_REPOSITORY: ${{ github.repository }}
      AUTOLOOP_PROGRAM: ${{ github.event.inputs.program }}
    run: |
      python3 - << 'PYEOF'
      import os, json, re, glob, sys
      import urllib.request, urllib.error
      from datetime import datetime, timezone, timedelta

      programs_dir = ".autoloop/programs"
      autoloop_dir = ".autoloop/programs"
      template_file = os.path.join(autoloop_dir, "example.md")

      # Read program state from repo-memory (persistent git-backed storage)
      github_token = os.environ.get("GITHUB_TOKEN", "")
      repo = os.environ.get("GITHUB_REPOSITORY", "")
      forced_program = os.environ.get("AUTOLOOP_PROGRAM", "").strip()

      # Repo-memory files are cloned to /tmp/gh-aw/repo-memory/{id}/ where {id}
      # is derived from the branch-name configured in the tools section (memory/autoloop → autoloop)
      repo_memory_dir = "/tmp/gh-aw/repo-memory/autoloop"

      def parse_machine_state(content):
          """Parse the ⚙️ Machine State table from a state file. Returns a dict."""
          state = {}
          m = re.search(r'## ⚙️ Machine State.*?\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
          if not m:
              return state
          section = m.group(0)
          for row in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|', section):
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

      def read_program_state(program_name):
          """Read scheduling state from the repo-memory state file."""
          state_file = os.path.join(repo_memory_dir, f"{program_name}.md")
          if not os.path.isfile(state_file):
              print(f"  {program_name}: no state file found (first run)")
              return {}
          with open(state_file, encoding="utf-8") as f:
              content = f.read()
          return parse_machine_state(content)

      # Bootstrap: create autoloop programs directory and template if missing
      if not os.path.isdir(autoloop_dir):
          os.makedirs(autoloop_dir, exist_ok=True)
          bt = chr(96)  # backtick — avoid literal backticks that break gh-aw compiler
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
              f"- {bt}REPLACE_WITH_FILE{bt} -- (describe what this file does)",
              "",
              "Do NOT modify:",
              "- (list files that must not be touched)",
              "",
              "## Evaluation",
              "",
              "<!-- Provide a command and the metric to extract. -->",
              "",
              f"{bt}{bt}{bt}bash",
              "REPLACE_WITH_YOUR_EVALUATION_COMMAND",
              f"{bt}{bt}{bt}",
              "",
              f"The metric is {bt}REPLACE_WITH_METRIC_NAME{bt}. **Lower/Higher is better.** (pick one)",
              "",
          ])
          with open(template_file, "w") as f:
              f.write(template)
          # Leave the template unstaged — the agent will create a draft PR with it
          print(f"BOOTSTRAPPED: created {template_file} locally (agent will create a draft PR)")

      # Find all program files from all locations:
      # 1. Directory-based programs: .autoloop/programs/<name>/program.md (preferred)
      # 2. Bare markdown programs: .autoloop/programs/<name>.md (simple)
      # 3. Issue-based programs: GitHub issues with the 'autoloop-program' label
      program_files = []
      issue_programs = {}  # name -> {issue_number, file}

      # Scan .autoloop/programs/ for directory-based programs
      if os.path.isdir(programs_dir):
          for entry in sorted(os.listdir(programs_dir)):
              prog_dir = os.path.join(programs_dir, entry)
              if os.path.isdir(prog_dir):
                  # Look for program.md inside the directory
                  prog_file = os.path.join(prog_dir, "program.md")
                  if os.path.isfile(prog_file):
                      program_files.append(prog_file)

      # Scan .autoloop/programs/ for bare markdown programs
      bare_programs = sorted(glob.glob(os.path.join(autoloop_dir, "*.md")))
      for pf in bare_programs:
          program_files.append(pf)

      # Scan GitHub issues with the 'autoloop-program' label
      issue_programs_dir = "/tmp/gh-aw/issue-programs"
      os.makedirs(issue_programs_dir, exist_ok=True)
      try:
          api_url = f"https://api.github.com/repos/{repo}/issues?labels=autoloop-program&state=open&per_page=100"
          req = urllib.request.Request(api_url, headers={
              "Authorization": f"token {github_token}",
              "Accept": "application/vnd.github.v3+json",
          })
          with urllib.request.urlopen(req, timeout=30) as resp:
              issues = json.loads(resp.read().decode())
          for issue in issues:
              if issue.get("pull_request"):
                  continue  # skip PRs
              body = issue.get("body") or ""
              title = issue.get("title") or ""
              number = issue["number"]
              # Derive program name from issue title: slugify to lowercase with hyphens
              slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
              slug = re.sub(r'-+', '-', slug)  # collapse consecutive hyphens
              if not slug:
                  slug = f"issue-{number}"
              # Avoid slug collisions: if another issue already claimed this slug, append issue number
              if slug in issue_programs:
                  print(f"  Warning: slug '{slug}' (issue #{number}) collides with issue #{issue_programs[slug]['issue_number']}, appending issue number")
                  slug = f"{slug}-{number}"
              # Write issue body to a temp file so the scheduling loop can process it
              issue_file = os.path.join(issue_programs_dir, f"{slug}.md")
              with open(issue_file, "w") as f:
                  f.write(body)
              program_files.append(issue_file)
              issue_programs[slug] = {"issue_number": number, "file": issue_file, "title": title}
              print(f"  Found issue-based program: '{slug}' (issue #{number})")
      except Exception as e:
          print(f"  Warning: could not fetch issue-based programs: {e}")

      if not program_files:
          # Fallback to single-file locations
          for path in [".autoloop/program.md", "program.md"]:
              if os.path.isfile(path):
                  program_files = [path]
                  break

      if not program_files:
          print("NO_PROGRAMS_FOUND")
          os.makedirs("/tmp/gh-aw", exist_ok=True)
          with open("/tmp/gh-aw/autoloop.json", "w") as f:
              json.dump({"due": [], "skipped": [], "unconfigured": [], "no_programs": True}, f)
          sys.exit(0)

      os.makedirs("/tmp/gh-aw", exist_ok=True)
      now = datetime.now(timezone.utc)
      due = []
      skipped = []
      unconfigured = []
      all_programs = {}  # name -> file path (populated during scanning)

      # Schedule string to timedelta
      def parse_schedule(s):
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
          return None  # No per-program schedule — always due

      def get_program_name(pf):
          """Extract program name from file path.
          Directory-based: .autoloop/programs/<name>/program.md -> <name>
          Bare markdown: .autoloop/programs/<name>.md -> <name>
          Issue-based: /tmp/gh-aw/issue-programs/<name>.md -> <name>
          """
          if pf.endswith("/program.md"):
              # Directory-based program: name is the parent directory
              return os.path.basename(os.path.dirname(pf))
          else:
              # Bare markdown or issue-based program: name is the filename without .md
              return os.path.splitext(os.path.basename(pf))[0]

      for pf in program_files:
          name = get_program_name(pf)
          all_programs[name] = pf
          with open(pf) as f:
              content = f.read()

          # Check sentinel (skip for issue-based programs which use AUTOLOOP:ISSUE-PROGRAM)
          if "<!-- AUTOLOOP:UNCONFIGURED -->" in content:
              unconfigured.append(name)
              continue

          # Check for TODO/REPLACE placeholders
          if re.search(r'\bTODO\b|\bREPLACE', content):
              unconfigured.append(name)
              continue

          # Parse optional YAML frontmatter for schedule and target-metric
          # Strip leading HTML comments before checking (issue-based programs may have them)
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
                          print(f"  Warning: {name} has invalid target-metric value: {line.split(':', 1)[1].strip()}")

          # Read state from repo-memory
          state = read_program_state(name)
          if state:
              print(f"  {name}: last_run={state.get('last_run')}, iteration_count={state.get('iteration_count')}")
          else:
              print(f"  {name}: no state found (first run)")

          last_run = None
          lr = state.get("last_run")
          if lr:
              try:
                  last_run = datetime.fromisoformat(lr.replace("Z", "+00:00"))
              except ValueError:
                  pass

          # Check if completed (target metric was reached)
          if str(state.get("completed", "")).lower() == "true":
              skipped.append({"name": name, "reason": f"completed: target metric reached"})
              continue

          # Check if paused (e.g., plateau or recurring errors)
          if state.get("paused"):
              skipped.append({"name": name, "reason": f"paused: {state.get('pause_reason', 'unknown')}"})
              continue

          # Auto-pause on plateau: 5+ consecutive rejections
          recent = state.get("recent_statuses", [])[-5:]
          if len(recent) >= 5 and all(s == "rejected" for s in recent):
              skipped.append({"name": name, "reason": "plateau: 5 consecutive rejections"})
              continue

          # Check if due based on per-program schedule
          if schedule_delta and last_run:
              if now - last_run < schedule_delta:
                  skipped.append({"name": name, "reason": "not due yet",
                                  "next_due": (last_run + schedule_delta).isoformat()})
                  continue

          due.append({"name": name, "last_run": lr, "file": pf, "target_metric": target_metric})

      # Pick the program to run
      selected = None
      selected_file = None
      selected_issue = None
      selected_target_metric = None
      deferred = []

      if forced_program:
          # Manual dispatch requested a specific program — bypass scheduling
          # (paused, not-due, and plateau programs can still be forced)
          if forced_program not in all_programs:
              print(f"ERROR: requested program '{forced_program}' not found.")
              print(f"  Available programs: {list(all_programs.keys())}")
              sys.exit(1)
          if forced_program in unconfigured:
              print(f"ERROR: requested program '{forced_program}' is unconfigured (has placeholders).")
              sys.exit(1)
          selected = forced_program
          selected_file = all_programs[forced_program]
          deferred = [p["name"] for p in due if p["name"] != forced_program]
          if selected in issue_programs:
              selected_issue = issue_programs[selected]["issue_number"]
          # Find target_metric: check the due list first, then parse from the program file
          for p in due:
              if p["name"] == forced_program:
                  selected_target_metric = p.get("target_metric")
                  break
          if selected_target_metric is None:
              # Program may have been skipped (completed/paused/plateau) — parse directly
              try:
                  with open(selected_file) as _f:
                      _content = _f.read()
                  _content_stripped = re.sub(r'^(\s*<!--.*?-->\s*\n)*', '', _content, flags=re.DOTALL)
                  _fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", _content_stripped, re.DOTALL)
                  if _fm:
                      for _line in _fm.group(1).split("\n"):
                          if _line.strip().startswith("target-metric:"):
                              selected_target_metric = float(_line.split(":", 1)[1].strip())
                              break
              except (OSError, ValueError, TypeError):
                  pass
          print(f"FORCED: running program '{forced_program}' (manual dispatch)")
      elif due:
          # Normal scheduling: pick the single most-overdue program
          due.sort(key=lambda p: p["last_run"] or "")  # None/empty sorts first (never run)
          selected = due[0]["name"]
          selected_file = due[0]["file"]
          selected_target_metric = due[0].get("target_metric")
          deferred = [p["name"] for p in due[1:]]
          # Check if the selected program is issue-based
          if selected in issue_programs:
              selected_issue = issue_programs[selected]["issue_number"]

      result = {
          "selected": selected,
          "selected_file": selected_file,
          "selected_issue": selected_issue,
          "selected_target_metric": selected_target_metric,
          "issue_programs": {name: info["issue_number"] for name, info in issue_programs.items()},
          "deferred": deferred,
          "skipped": skipped,
          "unconfigured": unconfigured,
          "no_programs": False,
      }

      os.makedirs("/tmp/gh-aw", exist_ok=True)
      with open("/tmp/gh-aw/autoloop.json", "w") as f:
          json.dump(result, f, indent=2)

      print("=== Autoloop Program Check ===")
      print(f"Selected program:      {selected or '(none)'} ({selected_file or 'n/a'})")
      print(f"Deferred (next run):   {deferred or '(none)'}")
      print(f"Programs skipped:      {[s['name'] for s in skipped] or '(none)'}")
      print(f"Programs unconfigured: {unconfigured or '(none)'}")

      if not selected and not unconfigured:
          print("\nNo programs due this run. Exiting early.")
          sys.exit(1)  # Non-zero exit skips the agent step
      PYEOF

source: githubnext/autoloop
engine: copilot
---

# Autoloop

An iterative optimization agent that proposes changes, evaluates them against a metric, and keeps only improvements — running autonomously on a schedule.

## Command Mode

Take heed of **instructions**: "${{ steps.sanitized.outputs.text }}"

If these are non-empty (not ""), then you have been triggered via `/autoloop <instructions>`. The instructions may be:
- **A one-off directive targeting a specific program**: e.g., `/autoloop training: try a different approach to the loss function`. The text before the colon is the program name (matching a directory in `.autoloop/programs/` or an issue with the `autoloop-program` label). Execute it as a single iteration for that program, then report results.
- **A general directive**: e.g., `/autoloop try cosine annealing`. If no program name prefix is given and only one program exists, use that one. If multiple exist, ask which program to target.
- **A configuration change**: e.g., `/autoloop training: set metric to accuracy instead of loss`. Update the relevant program file and confirm.

Then exit — do not run the normal loop after completing the instructions.

## Program Locations

Autoloop supports three program layouts:

### Directory-based programs (preferred)

Each program is a directory under `.autoloop/programs/` containing a `program.md` and all related code:

```
.autoloop/programs/
├── function_minimization/
│   ├── program.md         ← program definition (goal, target, evaluation)
│   └── code/              ← code files the agent optimizes
│       ├── initial_program.py
│       ├── evaluator.py
│       ├── config.yaml
│       └── requirements.txt
├── signal_processing/
│   ├── program.md
│   └── code/
│       ├── initial_program.py
│       ├── evaluator.py
│       ├── config.yaml
│       └── requirements.txt
```

The **program name** is the directory name (e.g., `function_minimization`).

### Bare markdown programs (simple/legacy)

For simpler programs that don't need their own code directory:

```
.autoloop/programs/
├── coverage.md
└── build-perf.md
```

The **program name** is the filename without `.md`.

### Issue-based programs

Programs can also be defined as GitHub issues with the `autoloop-program` label. The issue body uses the same format as a `program.md` file (with Goal, Target, and Evaluation sections). The **program name** is derived from the issue title (slugified to lowercase with hyphens).

The pre-step fetches open issues with the `autoloop-program` label via the GitHub API and writes each issue body to a temporary file for scheduling. Issue-based programs participate in the same scheduling and selection logic as file-based programs.

When a program is issue-based, `/tmp/gh-aw/autoloop.json` includes:
- **`selected_issue`**: The issue number (e.g., `42`) if the selected program came from an issue, or `null` if it came from a file.
- **`issue_programs`**: A mapping of program name → issue number for all issue-based programs found.

### Reading Programs

The pre-step has already determined which program to run. Read `/tmp/gh-aw/autoloop.json` at the start of your run to get:

- **`selected`**: The single program name to run this iteration, or `null` if none are due.
- **`selected_file`**: The full path to the program's markdown file (either `.autoloop/programs/<name>/program.md`, `.autoloop/programs/<name>.md`, or `/tmp/gh-aw/issue-programs/<name>.md` for issue-based programs).
- **`selected_issue`**: The GitHub issue number if the selected program came from an issue, or `null` if it came from a file.
- **`selected_target_metric`**: The `target-metric` value from the program's frontmatter (a number), or `null` if the program is open-ended. Used to check the [halting condition](#halting-condition) after each accepted iteration.
- **`issue_programs`**: A mapping of program name → issue number for all discovered issue-based programs.
- **`deferred`**: Other programs that were due but will be handled in future runs.
- **`unconfigured`**: Programs that still have the sentinel or placeholder content.
- **`skipped`**: Programs not due yet based on their per-program schedule.
- **`no_programs`**: If `true`, no program files exist at all.

If `selected` is not null:
1. Read the program file from the `selected_file` path.
2. Parse the three sections: Goal, Target, Evaluation.
3. Read the current state of all target files.
4. Read the state file `{selected}.md` from the repo-memory folder for all state: the ⚙️ Machine State table (scheduling fields) plus the research sections (priorities, lessons, foreclosed avenues, iteration history).
5. If `selected_issue` is not null, this is an issue-based program — also read the issue comments for any human steering input.

## Multiple Programs

Autoloop supports **multiple independent optimization loops** in the same repository. Each loop is defined by a directory in `.autoloop/programs/`, a markdown file in `.autoloop/programs/`, or a GitHub issue with the `autoloop-program` label. For example:

```
.autoloop/programs/
├── function_minimization/    ← optimize search algorithm
│   ├── program.md
│   └── code/
├── signal_processing/        ← optimize signal filter
│   ├── program.md
│   └── code/
├── coverage.md               ← maximize test coverage
└── build-perf.md             ← minimize build time

GitHub Issues (labeled 'autoloop-program'):
├── Issue #5: "Reduce Latency" ← optimize API response time
└── Issue #8: "Improve Accuracy" ← optimize model accuracy
```

Each program runs independently with its own:
- Goal, target files, and evaluation command
- Metric tracking and best-metric history
- Experiment log issue: `[Autoloop: {program-name}] Experiment Log {YYYY-MM}`
- Steering issue: `[Autoloop: {program-name}] Steering` (persistent, links branch/PR/state)
- Long-running branch: `autoloop/{program-name}` (persists across iterations)
- Single draft PR per program: `[Autoloop: {program-name}]` (accumulates all accepted iterations)
- State file: `{program-name}.md` in repo-memory (all state: scheduling, research context, iteration history)

**One program per run**: On each scheduled trigger, a lightweight pre-step checks which programs are due and selects the **single most-overdue program** (oldest `last_run`, with never-run programs first). The agent runs one iteration for that program only.

### Per-Program Schedule

Programs can optionally specify their own schedule in a YAML frontmatter block:

```markdown
---
schedule: every 1h
---

# Autoloop Program
...
```

### Target Metric (Halting Condition)

Programs can optionally specify a `target-metric` in the frontmatter to define a halting condition. When the metric reaches or surpasses the target, the program is automatically **completed**: the `autoloop-program` label is removed and an `autoloop-completed` label is added (for issue-based programs), and the state file is marked `Completed: true`.

Programs without a `target-metric` are **open-ended** and run indefinitely until manually stopped.

```markdown
---
schedule: every 6h
target-metric: 0.95
---

# Autoloop Program
...
```

## Program Definition

Each program file defines three things:

1. **Goal**: What the agent is trying to optimize (natural language description)
2. **Target**: Which files the agent is allowed to modify
3. **Evaluation**: How to measure whether a change is an improvement

### Setup Guard

A template program file is installed at `.autoloop/programs/example.md`. **Programs will not run until the user has edited them.** Each template contains a sentinel line:

```
<!-- AUTOLOOP:UNCONFIGURED -->
```

At the start of every run, check each program file for this sentinel. For any program where it is present:

1. **Skip that program — do not run any iterations for it.**
2. If no setup issue exists for that program, create one titled `[Autoloop: {program-name}] Action required: configure your program`.

## Branching Model

Each program uses a **single long-running branch** named `autoloop/{program-name}`. This branch persists across iterations — every accepted improvement is committed to it, building up a history of successful changes.

### Branch Naming Convention

```
autoloop/{program-name}
```

Examples:
- `autoloop/function_minimization`
- `autoloop/signal_processing`
- `autoloop/coverage`

### How It Works

1. On the **first accepted iteration**, the branch is created from the default branch.
2. On **subsequent iterations**, the agent checks out the existing branch and ensures it is up to date with the default branch (by merging the default branch into it).
3. **Accepted iterations** are committed and pushed to the branch. Each commit message references the GitHub Actions run URL.
4. **Rejected or errored iterations** do not commit — changes are discarded.
5. A **single draft PR** is created for the branch on the first accepted iteration. Future accepted iterations push additional commits to the same PR.
6. The branch may be **merged into the default branch** at any time (by a maintainer or CI). After merging, the branch continues to be used for future iterations — it is never deleted while the program is active.
7. A **sync workflow** automatically merges the default branch into all active `autoloop/*` branches whenever the default branch changes, keeping them up to date.

### Cross-Linking

Each program has three coordinated resources:
- **Branch + PR**: `autoloop/{program-name}` with a single draft PR
- **Steering Issue**: `[Autoloop: {program-name}] Steering` — persistent GitHub issue linking branch, PR, and state
- **State File**: `{program-name}.md` in repo-memory — all state, history, and research context

All three reference each other. The steering issue is created on the first accepted iteration and updated with links to the PR and state.

## Iteration Loop

Each run executes **one iteration for the single selected program**:

### Step 1: Read State

1. Read the program file to understand the goal, targets, and evaluation method.
2. Read the **state file** `{program-name}.md` from the repo-memory folder. This is the **single source of truth** for all program state. The file contains:
   - **⚙️ Machine State** table: `last_run`, `best_metric`, `target_metric`, `iteration_count`, `paused`, `pause_reason`, `completed`, `completed_reason`, `consecutive_errors`, `recent_statuses`. These are machine-readable scheduling and control fields visible to both humans and the pre-step.
   - **🎯 Current Priorities**: Human-set guidance for the next iterations (editable by maintainers).
   - **📚 Lessons Learned**: Key findings from past iterations.
   - **🚧 Foreclosed Avenues**: Approaches definitively ruled out, with reasons.
   - **🔭 Future Directions**: Promising ideas not yet tried.
   - **📊 Iteration History**: Reverse-chronological log of all past iterations.
   
   If the state file does not yet exist, create it in the repo-memory folder using the template defined in the [Repo Memory](#repo-memory) section.

### Step 2: Analyze and Propose

1. Read the target files and understand the current state.
2. Review the state file's **Lessons Learned**, **Foreclosed Avenues**, and **Current Priorities** — what worked, what didn't, and what the maintainer wants.
3. **Think carefully** about what change is most likely to improve the metric. Consider:
   - What has been tried before and ruled out (Foreclosed Avenues — don't repeat failures).
   - What the Current Priorities section asks for.
   - What the evaluation criteria reward.
   - Small, targeted changes are more likely to succeed than large rewrites.
   - If many small optimizations have been exhausted, consider a larger architectural change.
4. Describe the proposed change in your reasoning before implementing it.

### Step 3: Implement

1. Check out the program's long-running branch `autoloop/{program-name}`. If the branch does not yet exist, create it from the default branch. If it does exist, ensure it is up to date with the default branch (merge the default branch into it).
2. Make the proposed changes to the target files only.
3. **Respect the program constraints**: do not modify files outside the target list.

### Step 4: Evaluate

1. Run the evaluation command specified in the program file.
2. Parse the metric from the output.
3. Compare against `best_metric` from the state file.

### Step 5: Accept or Reject

**If the metric improved** (or this is the first run establishing a baseline):
1. Commit the changes to the long-running branch `autoloop/{program-name}` with a commit message referencing the actions run:
   - Commit message subject line: `[Autoloop: {program-name}] Iteration <N>: <short description>`
   - Commit message body (after a blank line): `Run: {run_url}` referencing the GitHub Actions run URL.
2. Push the commit to the long-running branch.
3. If a draft PR does not already exist for this branch, create one:
   - Title: `[Autoloop: {program-name}]`
   - Body includes: a summary of the program goal, link to the steering issue, the current best metric, and AI disclosure: `🤖 *This PR is maintained by Autoloop. Each accepted iteration adds a commit to this branch.*`
   If a draft PR already exists, update the PR body with the latest metric and a summary of the most recent accepted iteration. Add a comment to the PR summarizing the iteration: what changed, old metric, new metric, improvement delta, and a link to the actions run.
4. Ensure the steering issue exists (see [Steering Issue](#steering-issue) below). Add a comment to the steering issue linking to the commit and actions run.
5. Add an entry to the experiment log issue.
6. Update the state file `{program-name}.md` in the repo-memory folder:
   - Update the **⚙️ Machine State** table: reset `consecutive_errors` to 0, set `best_metric`, increment `iteration_count`, set `last_run` to current UTC timestamp, append `"accepted"` to `recent_statuses` (keep last 10), set `paused` to false.
   - Prepend an entry to **📊 Iteration History** (newest first) with status ✅, metric, PR link, and a one-line summary of what changed and why it worked.
   - Update **📚 Lessons Learned** if this iteration revealed something new about the problem or what works.
   - Update **🔭 Future Directions** if this iteration opened new promising paths.
7. **If this is an issue-based program** (`selected_issue` is not null): update the status comment and post a per-run comment on the source issue (see [Issue-Based Program Updates](#issue-based-program-updates)).
8. **Check halting condition** (see [Halting Condition](#halting-condition)): If the program has a `target-metric` in its frontmatter and the new `best_metric` meets or surpasses the target, mark the program as completed.

**If the metric did not improve**:
1. Discard the code changes (do not commit them to the long-running branch).
2. Add a "rejected" entry to the experiment log issue.
3. Update the state file `{program-name}.md` in the repo-memory folder:
   - Update the **⚙️ Machine State** table: increment `iteration_count`, set `last_run`, append `"rejected"` to `recent_statuses` (keep last 10).
   - Prepend an entry to **📊 Iteration History** with status ❌, metric, and a one-line summary of what was tried.
   - If this approach is conclusively ruled out (e.g., tried multiple variations and all fail), add it to **🚧 Foreclosed Avenues** with a clear explanation.
   - Update **🔭 Future Directions** if this rejection clarified what to try next.
4. **If this is an issue-based program** (`selected_issue` is not null): update the status comment and post a per-run comment on the source issue (see [Issue-Based Program Updates](#issue-based-program-updates)).

**If evaluation could not run** (build failure, missing dependencies, etc.):
1. Discard the code changes (do not commit them to the long-running branch).
2. Add an "error" entry to the experiment log issue.
3. Update the state file `{program-name}.md` in the repo-memory folder:
   - Update the **⚙️ Machine State** table: increment `consecutive_errors`, increment `iteration_count`, set `last_run`, append `"error"` to `recent_statuses` (keep last 10).
   - If `consecutive_errors` reaches 3+, set `paused` to `true` and set `pause_reason` in the Machine State table, and create an issue describing the problem.
   - Prepend an entry to **📊 Iteration History** with status ⚠️ and a brief error description.
4. **If this is an issue-based program** (`selected_issue` is not null): update the status comment and post a per-run comment on the source issue (see [Issue-Based Program Updates](#issue-based-program-updates)).

## Experiment Log Issue

Maintain a single open issue **per program** titled `[Autoloop: {program-name}] Experiment Log {YYYY}-{MM}` as a rolling record of that program's iterations.

### Issue Body Format

```markdown
🤖 *Autoloop — an iterative optimization agent for this repository.*

## Program

**Goal**: {one-line summary from program.md}
**Target files**: {list of target files}
**Metric**: {metric name} ({higher/lower} is better)
**Current best**: {best_metric} (established in iteration {N})

## Iteration History

### Iteration {N} — {YYYY-MM-DD HH:MM UTC} — [Run]({run_url})
- **Status**: ✅ Accepted / ❌ Rejected / ⚠️ Error
- **Change**: {one-line description}
- **Metric**: {value} (previous best: {previous_best}, delta: {delta})
- **Commit**: {short_sha} (if accepted)

### Iteration {N-1} — {YYYY-MM-DD HH:MM UTC} — [Run]({run_url})
- **Status**: ❌ Rejected
- **Change**: {one-line description}
- **Metric**: {value} (previous best: {previous_best}, delta: {delta})
- **Reason**: {why it was rejected}
```

### Format Rules

- Iterations in **reverse chronological order** (newest first).
- Each iteration heading links to its GitHub Actions run.
- Use `${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}` for the current run URL.
- Close the previous month's issue and create a new one at month boundaries.
- Maximum 50 iterations per issue; create a continuation issue if exceeded.

## Steering Issue

Maintain a single **persistent** open issue per program titled `[Autoloop: {program-name}] Steering`. Unlike experiment log issues (which rotate monthly), the steering issue lives for the entire lifetime of the program.

The steering issue serves as the central coordination point linking together the program's three key resources:
- The **long-running branch** `autoloop/{program-name}` and its draft PR
- The **state file** `{program-name}.md` in repo-memory (on the `memory/autoloop` branch)
- The **experiment log** issues

### Steering Issue Body Format

```markdown
🤖 *Autoloop — steering issue for the `{program-name}` program.*

## Links

- **Branch**: [`autoloop/{program-name}`](https://github.com/{owner}/{repo}/tree/autoloop/{program-name})
- **Pull Request**: #{pr_number}
- **State File**: [`{program-name}.md`](https://github.com/{owner}/{repo}/blob/memory/autoloop/{program-name}.md)
- **Experiment Log**: #{experiment_log_issue_number}

## Program

**Goal**: {one-line summary from program.md}
**Metric**: {metric-name} ({higher/lower} is better)
**Current best**: {best_metric}
**Iterations**: {iteration_count}
```

### Steering Issue Rules

- Create the steering issue on the **first accepted iteration** for the program if it does not already exist.
- **Update the issue body** whenever the best metric, PR number, or experiment log issue changes.
- **Add a comment** on each accepted iteration with a link to the commit and actions run.
- The steering issue is labeled `[automation, autoloop]`.
- Do NOT close the steering issue when the PR is merged — the branch continues to accumulate future iterations.

## Issue-Based Program Updates

When a program is defined via a GitHub issue (i.e., `selected_issue` is not null in `/tmp/gh-aw/autoloop.json`), the source issue itself serves as the program definition **and** as the primary interface for steering and monitoring the program. In addition to the normal iteration workflow (state file, experiment log, steering issue, PR), you must also update the source issue.

### Status Comment

On the **first iteration** for an issue-based program, post a comment on the source issue. On **every subsequent iteration**, update that same comment (edit it, do not post a new one). This is the "status comment" — always the earliest bot comment on the issue.

Find the status comment by searching for a comment containing `<!-- AUTOLOOP:STATUS -->`. If multiple comments contain this sentinel, use the earliest one (lowest comment ID) and ignore the others.

**Status comment format:**

```markdown
<!-- AUTOLOOP:STATUS -->
🤖 **Autoloop Status**

| | |
|---|---|
| **Status** | 🟢 Active / ⏸️ Paused / ⚠️ Error / ✅ Completed |
| **Best Metric** | {best_metric} |
| **Target Metric** | {target_metric or "— (open-ended)"} |
| **Iterations** | {iteration_count} |
| **Last Run** | [{YYYY-MM-DD HH:MM UTC}]({run_url}) |
| **Branch** | [`autoloop/{program-name}`](https://github.com/{owner}/{repo}/tree/autoloop/{program-name}) |
| **Pull Request** | #{pr_number} |
| **State File** | [`{program-name}.md`](https://github.com/{owner}/{repo}/blob/memory/autoloop/{program-name}.md) |
| **Experiment Log** | #{experiment_log_issue_number} |
| **Steering Issue** | #{steering_issue_number} |

### Summary

{2-3 sentence summary of current state: what has been accomplished so far, what the current best approach is, and what direction the next iteration will likely take.}
```

### Per-Run Comment

After **every iteration** (accepted, rejected, or error), post a **new comment** on the source issue with a summary of what happened:

```markdown
🤖 **Iteration {N}** — [{status_emoji} {status}]({run_url})

- **Change**: {one-line description of what was tried}
- **Metric**: {value} (best: {best_metric}, delta: {+/-delta})
- **Commit**: {short_sha} *(if accepted)*
- **Result**: {one-sentence summary of what this iteration revealed}
```

### Steering via Issue Comments

For issue-based programs, **human comments on the source issue act as steering input** (in addition to the state file's Current Priorities section). Before proposing a change, read all comments on the source issue and treat any human comments as directives — similar to how the Current Priorities section works in the state file.

### Issue-Based Program Rules

- The source issue body IS the program definition — do not modify it (the user owns it).
- The `autoloop-program` label must remain on the issue for the program to be discovered. When a program completes (target metric reached), the label is removed automatically and replaced with `autoloop-completed`.
- Closing the issue stops the program from being discovered (equivalent to deleting a program.md file).
- Issue-based programs use the same branching model, state files, experiment log, and steering issue as file-based programs.
- For issue-based programs, the steering issue is optional — the source issue itself serves a similar coordination role. However, if the program grows complex, a separate steering issue may still be created.

## Halting Condition

Programs can be **open-ended** (run indefinitely until manually stopped) or **goal-oriented** (run until a target metric is reached). This is controlled by the optional `target-metric` frontmatter field.

### How It Works

1. Parse the `target-metric` value from the program's YAML frontmatter (if present).
2. After each **accepted** iteration, compare the new `best_metric` against the `target-metric`.
3. Determine whether the target is met based on the metric direction:
   - If the program says "**higher is better**": the target is met when `best_metric >= target-metric`.
   - If the program says "**lower is better**": the target is met when `best_metric <= target-metric`.
4. When the target is met, **complete** the program:
   - Set `Completed` to `true` in the state file's **⚙️ Machine State** table.
   - Set `Completed Reason` to a human-readable message (e.g., `target metric 0.95 reached with value 0.97`).
   - **For issue-based programs** (`selected_issue` is not null):
     - Remove the `autoloop-program` label from the source issue.
     - Add the `autoloop-completed` label to the source issue.
   - Update the status comment to show ✅ Completed status.
   - Post a per-run comment celebrating the achievement: `🎉 **Target metric reached!** The program has achieved its goal.`
   - Add a comment on the steering issue (if one exists) noting the completion.
   - The program will not be selected for future runs (the pre-step skips completed programs).

### Example

```markdown
---
schedule: every 6h
target-metric: 0.95
---

# Improve Test Coverage

## Goal

Increase test coverage to at least 95%. **Higher is better.**

## Target

Only modify these files:
- `src/tests/**`

## Evaluation

```bash
npm run coverage -- --json
```

The metric is `coverage_pct`. **Higher is better.**
```

In this example, once `coverage_pct` reaches or exceeds `0.95`, the program completes automatically.

### Programs Without a Target Metric

Programs that omit `target-metric` are **open-ended** — they run indefinitely, always seeking further improvement. They can only be stopped by:
- Closing the issue (issue-based programs)
- Deleting or removing the program file
- Setting `Paused: true` in the state file
- Auto-pause from plateau (5 consecutive rejections) or errors (3 consecutive failures)

## State and Memory

Autoloop uses the gh-aw **repo-memory** tool for persistent state storage. Each program's state is stored as a markdown file (`{program-name}.md`) on the `memory/autoloop` branch, automatically managed by the repo-memory infrastructure.

This means:
- Maintainers can see **everything** in the state file on the `memory/autoloop` branch: current best metric, last run, iteration history, lessons, priorities — all in one place.
- Maintainers can **edit any section** of the state file to set priorities, give feedback, or flag foreclosed approaches.
- The pre-step reads state files from the repo-memory directory to determine scheduling.
- The agent reads and writes state files in the repo-memory folder; changes are automatically committed and pushed after the workflow completes.

### Per-Program State File

Each program has a state file at `{program-name}.md` in the repo-memory folder. This file is divided into two logical areas:

1. **⚙️ Machine State** — a structured table at the top of the file that the pre-step can parse and the agent must keep updated after every iteration.
2. **Research sections** — human-editable sections: 🎯 Current Priorities, 📚 Lessons Learned, 🚧 Foreclosed Avenues, 🔭 Future Directions, 📊 Iteration History.

**After every iteration** (accepted, rejected, or error), update the state file — both the Machine State table and the relevant research sections.

See the [Repo Memory](#repo-memory) section for the full file structure, templates, and update rules.

## Repo Memory

Autoloop uses the gh-aw `repo-memory` tool with branch `memory/autoloop` and file glob `*.md`. Each program's state is stored as `{program-name}.md` in the repo-memory folder.

### Per-Program State File

When creating or updating a program's state file in the repo-memory folder, use this structure:

```markdown
# Autoloop: {program-name}

🤖 *This file is maintained by the Autoloop agent. Maintainers may freely edit any section.*

---

## ⚙️ Machine State

> 🤖 *Updated automatically after each iteration. The pre-step scheduler reads this table — keep it accurate.*

| Field | Value |
|-------|-------|
| Last Run | — |
| Iteration Count | 0 |
| Best Metric | — |
| Target Metric | — |
| Branch | `autoloop/{program-name}` |
| PR | — |
| Steering Issue | — |
| Paused | false |
| Pause Reason | — |
| Completed | false |
| Completed Reason | — |
| Consecutive Errors | 0 |
| Recent Statuses | — |

---

## 📋 Program Info

**Goal**: {one-line summary from program.md}
**Metric**: {metric-name} ({higher/lower} is better)
**Branch**: [`autoloop/{program-name}`](../../tree/autoloop/{program-name})
**Pull Request**: #{pr_number}
**Steering Issue**: #{steering_issue_number}

---

## 🎯 Current Priorities

<!-- Maintainers: edit this section to guide the next iterations. The agent will read and follow these priorities. -->

*(No specific priorities set — agent is exploring freely.)*

---

## 📚 Lessons Learned

Key findings and insights accumulated over iterations. Updated by the agent when an iteration reveals something useful.

- *(none yet)*

---

## 🚧 Foreclosed Avenues

Approaches that have been tried and definitively ruled out. The agent will not repeat these.

- *(none yet)*

---

## 🔭 Future Directions

Promising ideas yet to be explored. Maintainers and the agent both contribute here.

- *(none yet)*

---

## 📊 Iteration History

All iterations in reverse chronological order (newest first).

<!-- Agent prepends entries here after each iteration -->

*(No iterations yet.)*
```

### Machine State Field Reference

| Field | Type | Description |
|-------|------|-------------|
| Last Run | ISO timestamp (e.g. `2025-01-15T12:00:00Z`) | UTC timestamp of the last iteration |
| Iteration Count | integer | Total iterations completed |
| Best Metric | number | Best metric value achieved so far |
| Target Metric | number or `—` | Target metric from program frontmatter (halting condition). `—` if open-ended |
| Branch | branch name | Long-running branch: `autoloop/{program-name}` |
| PR | `#number` or `—` | Draft PR number for this program |
| Steering Issue | `#number` or `—` | Steering issue number for this program |
| Paused | `true` or `false` | Whether the program is paused |
| Pause Reason | text or `—` | Why it is paused (if applicable) |
| Completed | `true` or `false` | Whether the program has reached its target metric |
| Completed Reason | text or `—` | Why it completed (e.g., `target metric 0.95 reached with value 0.97`) |
| Consecutive Errors | integer | Count of consecutive evaluation failures |
| Recent Statuses | comma-separated words | Last 10 outcomes: `accepted`, `rejected`, or `error` |

### Iteration History Entry Format

After each iteration, prepend an entry to the **📊 Iteration History** section. Use `${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}` for the run URL.

```markdown
### Iteration {N} — {YYYY-MM-DD HH:MM UTC} — [Run](https://github.com/{owner}/{repo}/actions/runs/{run_id})

- **Status**: ✅ Accepted / ❌ Rejected / ⚠️ Error
- **Change**: {one-line description of what was tried}
- **Metric**: {value} (previous best: {previous_best}, delta: {+/-delta})
- **Commit**: {short_sha} *(if accepted)*
- **Notes**: {one or two sentences on what this iteration revealed}
```

### Update Rules

- **Always** read the state file before proposing a change. It contains human guidance you must follow.
- **Always** update the state file after each iteration, regardless of outcome.
- **Update the Machine State table first** — the scheduling pre-step depends on it.
- **Prepend** iteration history entries (newest first).
- **Accumulate** Lessons Learned — add new insights, don't overwrite existing ones.
- **Add to Foreclosed Avenues** only when an approach is conclusively ruled out (not just rejected once).
- **Respect Current Priorities** — if a maintainer has written priorities, follow them in your next proposal.
- **Write the state file** to the repo-memory folder. Changes are automatically committed and pushed to the `memory/autoloop` branch after the workflow completes.

## Guidelines

- **One change per iteration.** Keep changes small and targeted.
- **No breaking changes.** Target files must remain functional even if the iteration is rejected.
- **Respect the evaluation budget.** If the evaluation command has a time constraint, respect it.
- **Repo-memory state file is the single source of truth.** All state lives in `{program-name}.md` in the repo-memory folder — scheduling fields, history, lessons, priorities. Keep it up to date.
- **Learn from the state file.** The Foreclosed Avenues and Lessons Learned sections exist to prevent repeating failures. Read them before every proposal.
- **Respect human input.** The Current Priorities section is set by maintainers — follow it.
- **Diminishing returns.** If the last 5 consecutive iterations were rejected, post a comment suggesting the user review the program definition or update the state file's Current Priorities.
- **Transparency.** Every PR and comment must include AI disclosure with 🤖.
- **Safety.** Never modify files outside the target list. Never modify the evaluation script. Never modify the program definition (except via `/autoloop` command mode).
- **Read AGENTS.md first**: before starting work, read the repository's `AGENTS.md` file (if present) to understand project-specific conventions.
- **Build and test**: run any build/test commands before creating PRs.
