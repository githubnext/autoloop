# Creating Autoloop Programs

This prompt guides you, a coding agent, to create a new **Autoloop program** — an optimization loop that runs autonomously on a schedule, proposes changes, evaluates them against a metric, and keeps only improvements.

## What is an Autoloop Program?

Autoloop is a GitHub Agentic Workflow that runs iterative optimization loops. Each loop is defined by a **program** — a directory under `.autoloop/programs/`, a markdown file in `.autoloop/programs/`, or a GitHub issue with the `autoloop-program` label.

### Directory-based programs (preferred for programs with their own code)

```
.autoloop/programs/<program-name>/
├── program.md           ← program definition (Goal, Target, Evaluation)
└── code/                ← code files the agent optimizes
    ├── initial_program.py
    ├── evaluator.py
    ├── config.yaml
    └── requirements.txt
```

### Bare markdown programs (for simpler programs that modify existing repo code)

```
.autoloop/programs/<program-name>.md
```

A repository can have multiple programs running independently. Each gets its own schedule, metric tracking, long-running branch (`autoloop/<program-name>`), and draft PR.

## Step 1: Understand the Repository

Before creating a program, understand what's in the repository:

1. Read `README.md`, `AGENTS.md`, and `CLAUDE.md` (if they exist).
2. Check what build/test/lint commands are available.
3. Check for existing programs in `.autoloop/programs/` to avoid overlap.
4. Identify what aspects of the project could benefit from iterative optimization.

## Step 2: Choose an Optimization Goal

Good Autoloop programs have these properties:

- **Measurable**: There's a numeric metric that can be extracted from a command.
- **Incremental**: Small changes can move the metric in the right direction.
- **Bounded scope**: The set of files to modify is well-defined and limited.
- **Safe to iterate**: A bad change can be rejected without breaking anything.

### Open-Ended vs. Goal-Oriented Programs

When creating a program, decide whether it is **open-ended** or **goal-oriented**:

- **Open-ended**: The program runs indefinitely, always seeking further improvement. Use this for research experiments, continuous optimization, or when there is no clear "done" threshold. Omit `target-metric` from the frontmatter.
- **Goal-oriented**: The program has a finish line — a specific metric value that, once reached, completes the program. Use this for concrete targets like "reach 95% test coverage" or "reduce build time below 30 seconds". Set `target-metric` in the frontmatter.

When the agent proposes a new program, it should **always clarify** which type it is creating and why. If a goal-oriented program's target metric is reached, the program completes automatically: the `autoloop-program` label is removed, an `autoloop-completed` label is added (for issue-based programs), and the state file is marked as completed.

## Step 3: Choose a Layout

**Prefer issue-based programs whenever possible.** They are the easiest to create, manage, and steer. Only use directory-based or bare markdown programs when there is a clear reason to do so. If it's not clear which layout is best, **ask the user** before proceeding.

- Use an **issue-based program** (GitHub issue with `autoloop-program` label) by default — open an issue, fill in the template, and the workflow picks it up. The issue body uses the same format as a program file. You can steer the program by commenting on the issue.
- Use a **directory-based program** (`.autoloop/programs/<name>/`) when the program has its own codebase to experiment on (e.g., algorithm optimization, ML training).
- Use a **bare markdown program** (`.autoloop/programs/<name>.md`) when the program modifies existing repository code and you need it checked into the repo (e.g., test coverage, build performance).

## Step 4: Write the Program File

The program file (`program.md` or `<name>.md`) defines three things:

1. **Goal**: What to optimize (natural language)
2. **Target**: Which files the agent may modify
3. **Evaluation**: Command that outputs a JSON metric

### Frontmatter

```yaml
---
schedule: every 6h    # Options: every Nh, every Nm, daily, weekly
timeout-minutes: 40   # Optional
target-metric: 0.95   # Optional: halting condition — program completes when this metric is reached
---
```

If `target-metric` is set, the program is **goal-oriented** and will stop running once the metric reaches or surpasses the target value. If omitted, the program is **open-ended** and runs indefinitely.

### Evaluation Output

The evaluation command must print JSON with the metric:

```json
{"metric_name": 42.5}
```

## Step 5: Validate and Test

1. Run the evaluation command locally and verify JSON output.
2. Verify target files exist.
3. Ensure no `<!-- AUTOLOOP:UNCONFIGURED -->` or `REPLACE`/`TODO` placeholders remain.
4. Ensure the program name is unique.

## Running Manually

- **Slash command**: `/autoloop <program-name>: <optional instructions>`
- **Workflow dispatch**: Trigger from the Actions tab. Use the optional `program` input to run a specific program by name (bypasses scheduling).
- **CLI**: `gh aw run autoloop` or `gh aw run autoloop --inputs program=<program-name>`

## Creating a Program from an Issue

The quickest way to create a program:

1. Open a new issue using the **Autoloop Program** issue template (or create one manually with the `autoloop-program` label).
2. Fill in the Goal, Target, and Evaluation sections — the format is identical to `program.md`.
3. The next scheduled run discovers the issue and includes it in scheduling.
4. A status comment is posted/updated on the issue after each run with links and current state.
5. Per-run comments are posted with the Actions run link and a summary of what happened.
6. Steer the program by adding comments to the issue — the agent reads them before each iteration.
