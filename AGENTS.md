# Autoloop

Autoloop is an automated Research, Development, and Experimentation platform built on [GitHub Agentic Workflows](https://github.github.com/gh-aw/setup/quick-start/).

It runs iterative optimization loops autonomously: each iteration proposes a change to a target codebase, evaluates it against a metric, and keeps only improvements. Inspired by Karpathy's Autoresearch and Claude Code's `/loop`.

## Architecture

```
autoloop/
├── AGENTS.md                          ← you are here
├── workflows/                         ← Agentic Workflow definitions
│   ├── autoloop.md                    ← main autoloop workflow (compiled by gh-aw)
│   ├── sync-branches.md               ← syncs default branch into autoloop/* branches
│   └── shared/                        ← shared workflow fragments
│       └── reporting.md
├── .autoloop/
│   └── programs/                      ← research programs (directory-based)
│       ├── function_minimization/
│       │   ├── program.md             ← goal, target, evaluation definition
│       │   └── code/                  ← code being optimized
│       │       ├── initial_program.py
│       │       ├── evaluator.py
│       │       ├── config.yaml
│       │       └── requirements.txt
│       ├── signal_processing/
│       │   ├── program.md
│       │   └── code/
│       │       ├── initial_program.py
│       │       ├── evaluator.py
│       │       ├── config.yaml
│       │       └── requirements.txt
│       ├── circle_packing/
│       │   ├── program.md
│       │   └── code/
│       └── autoresearch/
│           ├── program.md
│           └── code/
│               ├── train.py
│               ├── prepare.py
│               └── pyproject.toml
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── autoloop-program.md        ← issue template for creating programs
    └── workflows/                     ← compiled workflow (*.lock.yml, generated)
```

## Key Concepts

### Programs

A **program** defines a single optimization loop. Each program has:
- **Goal**: What to optimize (natural language description)
- **Target**: Which files the agent may modify
- **Evaluation**: A command that outputs a JSON metric

Programs can be either:
- **Directory-based** (`.autoloop/programs/<name>/program.md`): For programs with their own codebase. Code lives in `code/` subdirectory. Preferred for R&D experiments.
- **Bare markdown** (`.autoloop/programs/<name>.md`): For programs that modify existing repo code. Simpler but less organized.
- **Issue-based** (GitHub issue with `autoloop-program` label): For programs created and steered directly from a GitHub issue. The issue body uses the same format as `program.md`. The issue itself becomes the interface for monitoring and steering the program.

### Workflow

The workflow (`workflows/autoloop.md`) is compiled by `gh aw compile` into `.github/workflows/autoloop.lock.yml`. It:
1. Runs on a schedule (every 6h by default)
2. Checks which programs are due (by reading state files from repo-memory)
3. Selects the most-overdue program
4. Runs one iteration: propose → evaluate → accept/reject
5. Commits accepted improvements to the program's long-running branch `autoloop/<program-name>`
6. Updates the program's state file in repo-memory with all state (Machine State table + research sections)
7. If the program has a `target-metric` and the metric is reached, marks it as completed (removes `autoloop-program` label, adds `autoloop-completed` label for issue-based programs)

A companion workflow (`workflows/sync-branches.md`) runs on every push to the default branch and merges it into all active `autoloop/*` program branches, keeping them up to date.

### Evolution Strategy

Programs can include an Evolution Strategy section (inspired by OpenEvolve) that guides the agent to maintain a population of solutions, balance exploration vs exploitation, and avoid repeating failed approaches.

## Reference

- **Agentic Workflows**: https://github.com/github/gh-aw
- **Quick Start**: https://github.github.com/gh-aw/setup/quick-start/
- **Autoloop Examples**: See the [example programs](.autoloop/programs/) included in this repo

## Conventions

- Programs are self-contained: each program directory has everything needed to run its optimization loop
- The agent only modifies files listed in the program's Target section
- Evaluation commands must output JSON with a numeric metric
- Each program has a single **long-running branch** named `autoloop/<program-name>` that accumulates all accepted iterations
- A single **draft PR** per program is created on the first accepted iteration and accumulates subsequent commits
- A **steering issue** per program (`[Autoloop: <program-name>] Steering`) links the branch, PR, and state together
- All state lives in repo-memory — per-program state files on the `memory/autoloop` branch are the single source of truth for both scheduling/machine state and human-readable research context
- State files: `<program-name>.md` on the `memory/autoloop` branch (per-program with Machine State table + research sections)
- Experiment history is tracked in the state file's Iteration History section and via per-run comments on the source issue (for issue-based programs)
- The default branch is automatically merged into all `autoloop/*` branches whenever it changes
- Issue-based programs are discovered via the `autoloop-program` label; the issue body is the program definition
- For issue-based programs, a status comment (marked with `<!-- AUTOLOOP:STATUS -->`) is maintained on the source issue, and a per-run comment is posted after each iteration
- Programs can be **open-ended** (run indefinitely) or **goal-oriented** (run until `target-metric` in frontmatter is reached). When a goal-oriented program completes, the `autoloop-program` label is removed and `autoloop-completed` is added (for issue-based programs)
- When proposing a new program, always clarify whether it is open-ended or goal-oriented

## Adding a New Program

See `create-program.md` for a step-by-step guide. In short:

### Option A: Directory-based (preferred for R&D experiments)

1. Create `.autoloop/programs/<name>/` with a `program.md` and `code/` directory
2. Define Goal, Target, and Evaluation sections in `program.md`
3. Add code files to `code/`
4. Test the evaluation command locally
5. The next scheduled run will pick it up automatically

### Option B: Issue-based (quickest way to start)

1. Open a new issue using the "Autoloop Program" issue template
2. Fill in the Goal, Target, and Evaluation sections in the issue body
3. Ensure the `autoloop-program` label is applied
4. The next scheduled run will pick it up automatically
5. Monitor progress via the status comment and per-run comments on the issue

## Running Manually

Programs run on a schedule, but can also be triggered manually:

- **Slash command**: `/autoloop [<program-name>:] <instructions>` — post this in any GitHub issue or PR comment. The `autoloop` workflow picks it up and runs one iteration with the given instructions. For example: `/autoloop training: try a different learning rate`.
- **Workflow dispatch**: Trigger from the Actions tab. Use the optional `program` input to run a specific program by name (bypasses scheduling).
- **CLI**: `gh aw run autoloop` or `gh aw run autoloop --inputs program=<program-name>`

## Deploying

To deploy the workflow to a repository:

1. Copy `workflows/autoloop.md` to `.github/workflows/autoloop.md` in the target repo
2. Copy `workflows/sync-branches.md` to `.github/workflows/sync-branches.md` in the target repo
3. Copy `workflows/shared/` to `.github/workflows/shared/` in the target repo
4. Run `gh aw compile autoloop` and `gh aw compile sync-branches` to generate the lock files
5. Copy program directories to `.autoloop/programs/` in the target repo
6. Commit and push
