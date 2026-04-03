  # Autoloop
  
<img src="assets/icon.png" width="100" align="left" style="margin-right: 16px;">



  Autoloop automates any task you want done repeatedly in your repo. Define what you want done and how success is measured in a simple GitHub issue or a markdown file with optional supporting resources, and
  Autoloop runs it on a schedule — proposing changes, evaluating them against your metric, and keeping only improvements.

  <br clear="left">

Autoloop runs on [GitHub Agentic Workflows](https://github.github.com/gh-aw/setup/quick-start/) and [GitHub Copilot](https://github.com/features/copilot).

## Quick start

Paste this into your favorite coding agent session on the repo where you want to run Autoloop:

```
Install autoloop using https://github.com/githubnext/autoloop/blob/main/install.md
```

The agent will install [GitHub Agentic Workflows](https://github.github.com/gh-aw/setup/quick-start/) if needed, set up the Autoloop workflows, and walk you through creating your first program.

To create additional programs later, paste this:

```
Create a new autoloop program using https://github.com/githubnext/autoloop/blob/main/create-program.md
```

## How it works

You create a **program** — either as a GitHub issue (using the included issue template) or a file in your repo — that defines three things:

1. **Goal** — what to optimize, described in plain English
2. **Target** — which files the agent is allowed to modify
3. **Evaluation** — a command that outputs a numeric metric as JSON

Autoloop does the rest. On every scheduled run (default: every 6 hours):

1. Picks the most-overdue program
2. Reads the program definition and past iteration history
3. Proposes a single, targeted change on the program's branch
4. Runs the evaluation command and compares the metric to the previous best
5. If the metric improved: commits to the branch and updates the draft PR. If not: discards the change and logs what was tried.

All state — scheduling, iteration history, lessons learned, current priorities — is persisted in a per-program markdown file on a dedicated `memory/autoloop` branch using [repository memory](https://github.github.com/gh-aw/guides/memoryops/#repository-memory). This means the state is human-readable, version-controlled, and editable: you can browse the `memory/autoloop` branch to see exactly what the agent knows, or edit the state file directly to set priorities, add lessons, or flag approaches to avoid.

**You stay in control.** Each program gets its own long-running branch (`autoloop/<program-name>`) that you can merge whenever you're ready. You can provide feedback or steer the direction at any time by commenting on the program's issue or editing the state file on the memory branch.

### Scheduling

The workflow runs on a fixed schedule (every 6 hours by default) and runs **one program per trigger**. Each run, it picks the most-overdue program — so if you have 5 programs, they take turns rather than all running at once. Programs can set their own `schedule:` in their frontmatter (e.g. `every 1h`, `daily`, `weekly`), but they still only run when the workflow fires and it's their turn. To run more programs more often, you can increase the workflow's trigger frequency.

## What to use it for

- **Research** — run autonomous exploration and experimentation loops. Define a problem, a metric, and let the agent systematically explore the solution space — trying many approaches, maintaining a population of candidates, and discovering novel algorithms or configurations over hundreds of iterations.
- **Development** — continuously improve your codebase: grow test coverage, shrink bundle size, reduce build times, eliminate lint warnings, optimize performance. Anything with a measurable metric can be a program.

## Example programs

### Test Coverage

Increases test coverage across the repository by adding new test cases targeting untested code paths, edge cases, error handling, and boundary conditions.

- **Metric**: `coverage_percent` (higher is better)
- **Code**: [`.autoloop/programs/test_coverage/`](.autoloop/programs/test_coverage/)

### Autoresearch (LLM Training)

Minimizes validation bits-per-byte (`val_bpb`) for LLM pretraining within a fixed 5-minute training budget. Based on [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — the agent modifies the training script (architecture, optimizer, hyperparameters) and keeps only changes that improve the metric.

- **Metric**: `combined_score` = `1/val_bpb` (higher is better)
- **Code**: [`.autoloop/programs/autoresearch/`](.autoloop/programs/autoresearch/)
- **Example run**: [actions](https://github.com/githubnext/autoresearch_local/actions/runs/23924736866) | [PR](https://github.com/githubnext/autoresearch_local/pull/14)

### Function Minimization

Discovers optimization algorithms to find the global minimum of a multi-modal function `f(x,y) = sin(x)*cos(y) + sin(x*y) + (x^2+y^2)/20`. Starts from naive random search and evolves toward techniques like simulated annealing, basin-hopping, and gradient estimation.

- **Metric**: `combined_score` (higher is better), baseline 0.56
- **Code**: [`.autoloop/programs/function_minimization/`](.autoloop/programs/function_minimization/)
- **Example run**: [actions](https://github.com/githubnext/autoloop_examples/actions/runs/23503588936) | [PR](https://github.com/githubnext/autoloop_examples/pull/4)

### Signal Processing

Discovers and optimizes real-time adaptive filtering algorithms for noisy, non-stationary time series. Starts from a simple weighted moving average and evolves toward Kalman filters, wavelet denoising, and hybrid approaches.

- **Metric**: `overall_score` (higher is better), baseline 0.34
- **Code**: [`.autoloop/programs/signal_processing/`](.autoloop/programs/signal_processing/)
- **Example run**: [actions](https://github.com/githubnext/autoloop_examples/actions/runs/23511458560) | [PR](https://github.com/githubnext/autoloop_examples/pull/11)

### Circle Packing

Maximizes the sum of radii of 26 non-overlapping circles packed inside a unit square — a classic computational geometry problem. The target is AlphaEvolve's result of 2.635. Starts from a naive concentric-ring layout and evolves toward hexagonal grids with SLSQP optimization.

- **Metric**: `combined_score` (higher is better, 1.0 = matching AlphaEvolve)
- **Code**: [`.autoloop/programs/circle_packing/`](.autoloop/programs/circle_packing/)

## Adding a new program

Programs can be **open-ended** (run indefinitely, always optimizing) or **goal-oriented** (run until a target metric is reached). Set `target-metric` in the frontmatter to make a program goal-oriented — when the metric is reached, the `autoloop-program` label is removed and `autoloop-completed` is added.

### Option A: From a GitHub issue (quickest)

1. Open a new issue using the **Autoloop Program** template (or manually apply the `autoloop-program` label)
2. Fill in the Goal, Target, and Evaluation sections in the issue body — the format is identical to `program.md`
3. Optionally set `target-metric` in the frontmatter for a goal-oriented program
4. The next scheduled run picks it up automatically
5. Monitor progress via the status comment and per-run comments posted on the issue
6. Steer the program by adding comments to the issue — the agent reads them before each iteration

### Option B: From a directory (preferred for R&D experiments)

1. Create a directory under `.autoloop/programs/`:
   ```
   .autoloop/programs/my-experiment/
   ├── program.md
   └── code/
       └── ...
   ```

2. Define Goal, Target, and Evaluation in `program.md`:
   ```markdown
   ---
   schedule: every 6h
   target-metric: 0.95  # optional: program completes when metric reaches this value
   ---

   # My Experiment

   ## Goal
   Improve X by doing Y. The metric is Z. Higher is better.

   ## Target
   Only modify these files:
   - `.autoloop/programs/my-experiment/code/main.py`

   ## Evaluation
   ```bash
   python3 .autoloop/programs/my-experiment/code/evaluate.py
   ```
   The metric is `score`. **Higher is better.**

3. The next scheduled run picks it up automatically. No other configuration needed.

See [`create-program.md`](create-program.md) for a detailed guide.

## Slash command

Autoloop registers a `/autoloop` slash command that lets you trigger or steer programs directly from any GitHub issue or pull request comment.

**Syntax:**

```
/autoloop [<program-name>:] <instructions>
```

**Usage examples:**

| Command | What happens |
|---|---|
| `/autoloop` | Runs the next scheduled iteration (or asks which program if more than one exists) |
| `/autoloop training: try a different learning rate` | Runs one iteration of the `training` program with the given instructions |
| `/autoloop try cosine annealing` | Runs one iteration of the single active program using the instructions |
| `/autoloop training: set metric to accuracy instead of loss` | Updates the `training` program's configuration and confirms |

When a program name is given before the colon it must match a directory in `.autoloop/programs/` or a GitHub issue with the `autoloop-program` label. If no program name is provided and only one program exists, that program is used. If multiple programs exist and no name is specified, the agent will ask you to clarify.

The command is handled by the `autoloop` Agentic Workflow — it is **not** a GitHub CLI command. It works anywhere GitHub processes slash commands (issue comments, PR comments, discussions).

## Repository structure

```
autoloop/
├── workflows/                         ← Agentic Workflow definitions
│   ├── autoloop.md                    ← the workflow (compiled by gh aw)
│   ├── sync-branches.md               ← syncs default branch into autoloop/* branches
│   └── shared/
│       └── reporting.md
├── .autoloop/
│   └── programs/                      ← example programs
│       ├── function_minimization/
│       │   ├── program.md             ← goal, target, evaluation
│       │   └── code/                  ← code being optimized
│       ├── signal_processing/
│       │   ├── program.md
│       │   └── code/
│       ├── circle_packing/
│       │   ├── program.md
│       │   └── code/
│       └── autoresearch/
│           ├── program.md
│           └── code/
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── autoloop-program.md        ← issue template for creating programs
    └── workflows/                     ← compiled workflow (*.lock.yml, generated)
```

Programs are **self-contained directories**. Each one has a `program.md` that defines the optimization loop and a `code/` directory with the codebase being experimented on. Programs can also be created directly from **GitHub issues** using the `autoloop-program` label — the issue body uses the same format as `program.md`.

## How the evolution strategy works

Programs can include an **Evolution Strategy** section (inspired by [OpenEvolve](https://github.com/codelion/openevolve)) that guides the agent to:

- Maintain a **population** of solution variants, not just the single best
- Balance **exploration** (trying fundamentally new approaches) with **exploitation** (refining what works)
- Track solutions across **feature dimensions** (algorithm type, code complexity) to maintain diversity
- Detect **plateaus** and automatically shift strategy when progress stalls
- Draw **inspiration** across population members — combining the best ideas from different approaches

This makes Autoloop more than a simple hill-climber. It's closer to an evolutionary programming system where the agent acts as both the mutation operator and the selection mechanism. See the [example programs](.autoloop/programs/) — all four include an Evolution Strategy section you can use as a starting point.

## Built on

- [GitHub Agentic Workflows](https://github.com/github/gh-aw) — the orchestration platform
- [GitHub Copilot](https://github.com/features/copilot) — the agent engine
- [OpenEvolve](https://github.com/codelion/openevolve) — inspiration for the evolution strategy

## Contributing

We don't accept pull requests for this project. Instead, we ask that you use a coding agent to write a detailed issue describing the bug or feature request — we'll implement it agentically from there. See [GitHub Agentic Workflows' CONTRIBUTING.md](https://github.com/github/gh-aw/blob/main/CONTRIBUTING.md) for more on this philosophy.

## Credits

- Some of the examples in the `.autoloop/programs` folder are from [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve/tree/main/examples).
