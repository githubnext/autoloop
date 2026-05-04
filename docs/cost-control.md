# Cost Control for Autoloop

Status: design report (not yet implemented). Resolves the "Dig in to
cost control possibilities" issue.

Autoloop runs autonomously and indefinitely. Each iteration spends
both GitHub Actions minutes and AI inference tokens, so cost control
is a first-class concern: a misconfigured program could run every six
hours forever, and one bad iteration could blow a per-run token
budget.

This document is a deep dive into what cost-control mechanisms are
*available today* (in [GitHub Agentic Workflows][gh-aw], the harness
that Autoloop is built on, and in the engines it can drive), what we
*currently use*, and what we *should add* — both at the gh-aw layer
and at the Autoloop layer.

[gh-aw]: https://github.github.com/gh-aw/

## TL;DR

- **Today, `workflows/autoloop.md` sets only one cost lever:**
  `engine: copilot` plus `timeout-minutes: 45`. There is no model
  pin, no per-iteration token cap, no per-program $/token budget,
  and no daily/weekly/monthly cap.
- **gh-aw already gives us most of the primitives we need at the
  workflow level:** `engine.model` (cheap-model selection),
  `timeout-minutes` / `stop-after` (wall-clock caps), `rate-limit`
  (per-user trigger caps), `skip-if-match` (skip the agent before
  inference), `safe-outputs.*.max` (cap write-amplification), and
  `gh aw logs` / `gh aw audit` for measurement.
- **gh-aw does *not* currently expose a hard per-run "max $" or
  "max tokens" knob** for most engines. The only token-budget-shaped
  knob is Claude's `max-turns`, plus the BYOK overrides
  `COPILOT_PROVIDER_MAX_PROMPT_TOKENS` /
  `COPILOT_PROVIDER_MAX_OUTPUT_TOKENS` for Copilot in BYOK mode.
- **Autoloop should add cost control at three layers:**
  1. **Per-program frontmatter** in `program.md` — `model:`,
     `cost.per-iteration.max-{tokens,usd}`, `cost.budget` with a
     `day/week/month` window.
  2. **Scheduler-side enforcement** in
     `workflows/scripts/autoloop_scheduler.py` — read accumulated
     spend from `gh aw logs --json`, compare against the program's
     budget, and refuse to schedule a program that has exceeded it.
     This is the only mechanism today that can enforce a real
     `$/week` cap.
  3. **In-iteration cheap-model selection** — let a program declare a
     `model:` override that the workflow honours when it dispatches
     the agent for that program (instead of a single global engine).
- **Cheap-model strategy:** the highest-leverage default is to switch
  the autoloop *workflow* itself to a small model
  (`gpt-4.1-mini` / `claude-haiku-4-5`) for the bookkeeping/scheduling
  work, and only escalate to a frontier model for the iteration's
  actual proposal step — ideally as a per-program choice.

---

## 1. Where cost is incurred in one Autoloop iteration

A single scheduled run of `autoloop.md` executes (in order):

| Phase | Job(s) | Tokens? | Actions minutes? |
|---|---|---|---|
| **Pre-activation** | runner setup, repo checkout, repo-memory clone | none | yes (~30–60 s + ~1.5 min runner overhead) |
| **Scheduler** | `autoloop_scheduler.py` (Python, stdlib-only) | none | yes (~5–15 s) |
| **Agent** | gh-aw runs the engine (Copilot today) on the autoloop prompt | **yes — dominant** | yes (1–15+ min) |
| **Evaluation sub-process** | `program.md`'s `Evaluation` command, run inside the agent step | depends on the program | counted in the agent step |
| **Safe outputs** | commit, push, PR/issue update jobs | none | yes (~30–60 s each) |

The cost picture is therefore:

```
total_iteration_cost ≈ Actions_minutes_cost(all jobs)
                     + inference_cost(agent job)
                     + program_eval_cost
```

Two important observations:

1. **Inference dominates** for any non-trivial program. The autoloop
   prompt is large (~2k–5k tokens of system prompt plus the program
   state file plus iteration history) and the agent is allowed up to
   45 minutes to think and call tools. A single iteration with a
   frontier Copilot model is in the order of one to a few "premium
   requests"; with `claude` or `codex` on direct API keys it is
   typically a few cents to a few dollars depending on prompt and
   tool-call volume.
2. **The evaluation step is part of the program**, not the harness.
   Programs whose evaluation calls an LLM (e.g. autoresearch-style
   training/inference loops) can spend orders of magnitude more than
   the agent itself. Cost control must therefore be expressible at
   the *program* level, not just the workflow level.

There are also two failure modes that pure budgeting must catch:

- **Runaway iteration** — the agent gets stuck in a tool loop and
  burns the full 45-minute timeout every time. Today, only
  `timeout-minutes` bounds this.
- **Runaway schedule** — a program with `every 5m` keeps firing
  forever, well after it has stopped making progress. Today, nothing
  bounds this except humans noticing and editing the schedule.

---

## 2. What gh-aw gives us today

This section catalogues every cost-relevant lever exposed by gh-aw
that Autoloop could (but mostly does not) use.

### 2.1 Engine and model selection

`engine:` accepts `copilot` (default), `claude`, `codex`, `gemini`,
`crush` (experimental), or `opencode` (experimental). Each engine has
distinct billing:

| Engine | Billed to | Unit | Per-run order of magnitude |
|---|---|---|---|
| `copilot` | account owning `COPILOT_GITHUB_TOKEN` | premium requests | 1–2 per run |
| `claude` | Anthropic account on `ANTHROPIC_API_KEY` | tokens | $0.01–$1+ per run |
| `codex` | OpenAI account on `OPENAI_API_KEY` | tokens | $0.01–$1+ per run |
| `gemini` | Google account on `GEMINI_API_KEY` | tokens | $0.005–$0.50+ per run |
| `crush`, `opencode` | varies (typically Copilot token) | varies | varies |

**Cheap-model selection** is via `engine.model`:

```yaml
engine:
  id: copilot
  model: gpt-4.1-mini       # ~10–20× cheaper than gpt-5
# or
engine:
  id: claude
  model: claude-haiku-4-5   # ~10× cheaper than claude-sonnet
# or
engine:
  id: codex
  model: gpt-4o-mini
# or
engine:
  id: gemini
  model: gemini-2.5-flash   # cheapest reliable Gemini tier
```

This is the single biggest cost lever and is currently unused by
Autoloop.

### 2.2 Per-engine turn / token caps

| Knob | Engines | What it caps |
|---|---|---|
| `max-turns` | claude only | number of agent turns per run |
| `max-continuations` | copilot only | autopilot continuation runs |
| `COPILOT_PROVIDER_MAX_PROMPT_TOKENS` (BYOK env) | copilot in BYOK mode | input tokens per call |
| `COPILOT_PROVIDER_MAX_OUTPUT_TOKENS` (BYOK env) | copilot in BYOK mode | output tokens per call |

There is **no portable `token-budget:` field** in current gh-aw —
inference token caps only exist for Claude (via `max-turns`, which is
indirect) and for Copilot in BYOK mode.

### 2.3 Wall-clock caps (Actions-minutes control)

- `timeout-minutes:` — caps the agent step. Autoloop sets `45`.
- `stop-after: +48h` — cancels the run if too much time has passed
  since the trigger. Useful for never-let-an-iteration-loop-overnight
  semantics. Currently unused by Autoloop.
- Job-level `timeout-minutes` on safe-output jobs is implicit
  (defaults to 360 minutes).

### 2.4 Skip-the-agent gates (highest-leverage savings)

`skip-if-match` / `skip-if-no-match` run during the cheap
pre-activation job and cancel the workflow before the agent fires:

```yaml
on:
  schedule: every 6h
  skip-if-no-match: 'label:autoloop-program -label:autoloop-paused'
```

Today the Autoloop scheduler itself decides whether to run anything,
so this is partially redundant — but it could be used to *guarantee*
that paused programs can never trigger an agent run.

### 2.5 Trigger throttling

- `rate-limit: { max, window, ignored-roles }` — caps per-user
  triggers. Useful for slash-command floods, irrelevant for the
  scheduled trigger.
- `concurrency` — serialises runs. Autoloop should set this to
  prevent two scheduled runs racing if the previous one ran long.

### 2.6 Safe-output caps

`safe-outputs.*.max` and `safe-outputs.*.environment` cap the number
of writes per run and gate them behind manual approval. These cap
*amplification*, not inference cost, but are still important for
governance.

### 2.7 Measurement: `gh aw logs` and `gh aw audit`

The most important fact for budget enforcement is that gh-aw exposes
historical per-run cost as JSON:

```bash
gh aw logs --start-date -7d --json \
  | jq '.runs[] | {workflow, duration, estimated_cost, token_usage}'
```

Per-run fields include `duration`, `token_usage`, `estimated_cost`,
`workflow_name`, `agent` (engine ID); per-episode roll-ups include
`total_tokens`, `total_effective_tokens`, `total_estimated_cost`.

For Copilot, `total_estimated_cost` is a heuristic — the source of
truth is `total_effective_tokens`. For Claude/Codex/Gemini the cost
is directly billable.

This is the hook Autoloop needs for a real per-program $/week budget:
the scheduler can read recent cost, attribute it to programs by
parsing the per-iteration commit message, and enforce a cap.

The same data is also exposed as an MCP tool (`agentic-workflows`),
so an Autoloop iteration could itself read its program's recent cost
and decide to throttle.

### 2.8 Bring-your-own-key (BYOK) for Copilot

Copilot can be redirected to OpenAI / Anthropic / Azure / Ollama via
`COPILOT_PROVIDER_BASE_URL`. This lets a single-engine workflow swap
billing accounts without changing the harness — useful for routing
expensive autoloop runs to a sponsored Anthropic account while
keeping cheap routine runs on the default Copilot account.

---

## 3. What Autoloop uses today

From `workflows/autoloop.md`:

```yaml
engine: copilot
timeout-minutes: 45
safe-outputs:
  add-comment: { max: 7 }
  create-pull-request: { max: 1 }
  push-to-pull-request-branch: { max: 1 }
  create-issue: { max: 1 }
  update-issue: { max: 3 }
  add-labels: { max: 2 }
  remove-labels: { max: 2 }
```

That is the entire cost-control surface today:

- ✅ uses Copilot (cheapest tier per request, but uses the default
  frontier model — no `engine.model` override)
- ✅ caps wall clock at 45 minutes
- ✅ caps write amplification via `safe-outputs.*.max`
- ❌ no `engine.model` (always uses the Copilot default)
- ❌ no `stop-after` (a stuck run can re-fire on the next schedule)
- ❌ no `rate-limit` (slash-command floods cost real money)
- ❌ no `concurrency` group (two scheduled runs can race)
- ❌ no per-program model override
- ❌ no per-program $/token budget (the only "budget" is the
  human-edited `target-metric` — once met, the program is marked
  completed)
- ❌ no daily/weekly/monthly spend cap at any layer

---

## 4. How to express cost control per job

This is the core of the question. The answers split by *time scale*
and *enforcement layer*.

### 4.1 Per-iteration ($ or tokens per run)

**Goal:** an iteration is allowed up to `$X` or `T` tokens; if it
exceeds the cap, the agent step is killed and the iteration is
logged as `error`.

**Today, with stock gh-aw:**

| Engine | Per-iteration cap mechanism |
|---|---|
| `claude` | `max-turns: N` (indirect: bounds turns, not tokens) + `timeout-minutes` |
| `codex`, `gemini` | `timeout-minutes` only |
| `copilot` (default) | `timeout-minutes` only — but per-run cost is naturally bounded to ~1–2 premium requests |
| `copilot` (BYOK) | `COPILOT_PROVIDER_MAX_PROMPT_TOKENS` / `COPILOT_PROVIDER_MAX_OUTPUT_TOKENS` per call |

**Recommended Autoloop addition:**

Add a frontmatter field on each program:

```markdown
---
schedule: every 6h
target-metric: 0.95
metric-direction: higher
cost:
  per-iteration:
    max-tokens: 200000     # hard cap; iteration is rejected if exceeded
    max-usd: 1.00          # hard cap; iteration is rejected if exceeded
---
```

This is enforced in two places:

1. **Pre-iteration**, the workflow translates the cap to whatever
   per-engine knob exists (`max-turns` for Claude;
   `COPILOT_PROVIDER_MAX_*` for Copilot BYOK; `timeout-minutes` for
   everything else).
2. **Post-iteration**, the agent reads the run's actual cost from
   `gh aw audit <run-id>` (the `agentic-workflows` MCP tool) and, if
   it exceeded the cap, marks the iteration `rejected: cost-overrun`
   in the state file's Iteration History — even if the metric
   improved. This produces the ratchet behaviour we want: a one-off
   spike does not pollute the budget but also gets recorded as a
   lesson.

### 4.2 Per-program ($ or tokens per day / week / month)

**Goal:** a program is allowed up to `$X / week`. Once exceeded, the
scheduler skips it until the window rolls.

**Today, with stock gh-aw:** *no native mechanism.* This is the gap
the issue is asking us to fill.

**Recommended Autoloop addition:**

The scheduler in `workflows/scripts/autoloop_scheduler.py` already
owns the "which program runs next" decision. Extend it to:

1. Parse a `cost.budget` block from the program frontmatter:

   ```markdown
   ---
   cost:
     budget:
       window: weekly         # daily | weekly | monthly | rolling-Nh
       max-usd: 20.00
       max-tokens: 5000000
       on-exceeded: pause     # pause | skip-until-window-rolls | warn
   ---
   ```

2. On each scheduling pass, fetch recent runs via
   `gh aw logs --start-date -<window> --json` and group by program
   (using a label or commit-message convention; see §6.1). Sum
   `estimated_cost` and `token_usage` per program.

3. If a program is over budget, treat it as not-due and append a
   `pause_reason: "budget-exceeded: $21.40 of $20.00 weekly cap"` to
   its state file. Optionally post a status comment.

4. When the budget window rolls (or a human edits the cap), the
   program becomes due again automatically.

This is a small change to the scheduler — it already reads JSON
state — and it gives us the only real `$/week` cap available without
upstream gh-aw changes.

### 4.3 Repository-wide cap

**Goal:** the whole Autoloop installation in this repo costs no more
than `$X / month`, regardless of how many programs exist.

Same scheduler hook as §4.2, with a single `repo-budget.md` (or a
section in `AGENTS.md`) declaring the cap. If the repo-wide cap is
exceeded, *all* programs are skipped until the window rolls, and a
single status issue is opened/updated.

This is important because Autoloop encourages adding programs
liberally: without a repo cap, N programs scale cost linearly with
no safety net.

### 4.4 Per-engine / per-account cap

For `copilot`, the practical cap is "premium requests on the service
account that owns `COPILOT_GITHUB_TOKEN`". This is set in the GitHub
billing UI for that account, not in gh-aw, and is enforced by GitHub
itself — over-budget runs simply fail at the API layer.

**Recommendation:** document the convention of using a *dedicated
service account* per Autoloop installation, with a GitHub-billing-side
spending limit set explicitly. This is the only truly hard cap
available for Copilot today.

For `claude` / `codex` / `gemini`, set per-key spending limits in the
respective provider consoles. Same logic.

---

## 5. How to better use cheaper models

Three independent strategies, in increasing leverage:

### 5.1 Strategy A: cheap default, expensive escalation

The autoloop prompt is *mostly* bookkeeping: read state, parse
history, decide what to try, run a tool, write a comment, update a
state file. A small model (`gpt-4.1-mini`, `claude-haiku-4-5`,
`gemini-2.5-flash`) is more than capable of the bookkeeping; the
expensive part is the *proposal* (the actual code change).

**Implementation:** keep `engine: copilot` but add
`engine.model: gpt-4.1-mini` as the default. Programs that want a
frontier model for proposals declare:

```markdown
---
model: gpt-5           # opt in to the expensive default
---
```

The workflow reads this via the scheduler's output (already a JSON
blob written to `/tmp/gh-aw/autoloop.json`) and, if present, sets
`COPILOT_MODEL` for that run via `engine.env`.

### 5.2 Strategy B: per-phase routing

Split the iteration into phases and route each to a different model:

| Phase | Suggested model | Why |
|---|---|---|
| State parsing, scheduling decision | smallest available | pure structured-data work |
| Lessons-learned summarisation / compaction | small reasoning model | summarisation, no code |
| Proposal (the actual change) | frontier reasoning model | the only step where capability matters |
| Evaluation log analysis | small model | structured output |
| State file update / commit message | smallest available | templated text |

This is harder to express in stock gh-aw (one workflow = one engine).
Two paths:

1. **Multi-job workflow:** split the autoloop workflow into a chain
   of runs (`workflow_call` or `dispatch-workflow`), each with its
   own `engine.model`. Episode-level cost data
   (`gh aw logs --json .episodes[]`) makes this observable.
2. **In-iteration BYOK switching:** the agent itself, mid-run,
   shells out to a cheaper model for sub-tasks via a small helper
   script. Less elegant; only worth it if (1) is too disruptive.

For now, Strategy A captures most of the savings of Strategy B with
a fraction of the complexity.

### 5.3 Strategy C: quality-aware downgrade based on history

The state file's Iteration History records, per iteration, whether
the proposal was accepted, rejected, or errored. The scheduler can
read this to *automatically* choose the model:

- N consecutive `accepted` iterations → downgrade to a cheaper model
  (the program is "easy" right now).
- M consecutive `rejected` iterations on the cheap model → upgrade
  back to the frontier model (the program is "hard" right now).

This is the autoresearch-flavoured approach: let the optimisation
loop optimise its own cost. Fits naturally into Autoloop's existing
ratchet philosophy.

---

## 6. Concrete proposals for Autoloop

Roughly in priority order; each is independently shippable.

### 6.1 (P0) Add a `program` label to runs for cost attribution

`gh aw logs --json` reports per-run cost but does not natively
distinguish *which program* a given run was for — they all share the
workflow name `autoloop`. Without attribution, no per-program budget
is possible.

**Fix:** when the autoloop workflow starts, write the selected
program name to a run-level annotation that survives in the logs
output. Two cheap options:

- Set a `concurrency.group: gh-aw-autoloop-<program>` (already would
  be useful for serialisation; doubles as an attribution key visible
  in `gh aw logs --json`).
- Tag the agent commit with `Autoloop-Program: <name>` in the commit
  trailer (already done by the workflow's accepted commits) and use
  that for offline attribution.

### 6.2 (P0) Add `engine.model` to `workflows/autoloop.md`

Default the workflow to a cheap model (e.g. `gpt-4.1-mini`).
Document the override path for programs that need a frontier model.

This is a one-line frontmatter change with the largest expected cost
reduction (estimated 5–10× for typical programs).

### 6.3 (P0) Add `concurrency` and `stop-after` to the workflow

```yaml
concurrency:
  group: gh-aw-autoloop
  cancel-in-progress: false
stop-after: +90m
```

Prevents two schedules racing and prevents a stuck run from re-firing
on the next 6h schedule until the current one is done.

### 6.4 (P1) Frontmatter `cost:` block in `program.md`

Spec proposed in §4.1 and §4.2. Implementation in
`workflows/scripts/autoloop_scheduler.py`:

- Extend `parse_program_frontmatter` to return a 6-tuple, adding a
  `cost_config` dict — or, preferably, refactor it to return a
  dataclass; the 5-tuple is already at the readability cliff.
- Extend the scheduling decision to consult cost.

### 6.5 (P1) Repo-wide budget in `AGENTS.md`

A single fenced block:

````markdown
```autoloop-budget
window: monthly
max-usd: 100.00
on-exceeded: pause-all
```
````

Read once per scheduler invocation; enforced before per-program
checks. Cheapest possible governance lever.

### 6.6 (P2) Quality-aware model downgrade (Strategy C)

Implement after 6.1–6.5 are in and we have ≥ 1 month of cost data
to validate the heuristics on.

### 6.7 (P2) Per-phase model routing (Strategy B)

Defer. Only worth doing if Strategy A + Strategy C combined still
leave inference cost as the dominant line item.

### 6.8 (P3) Upstream `token-budget:` to gh-aw

The cleanest end state is a portable `token-budget: N` in gh-aw
frontmatter that all engines respect. This is an upstream feature
request; track separately. Until it lands, Autoloop's per-program
budget is enforced post-hoc by the scheduler (§4.1 step 2), which is
sufficient for a $/week ratchet but does not stop a single runaway
iteration mid-flight.

---

## 7. Summary of the cost-control surface (proposed final state)

| Layer | Mechanism | Time scale | Hard or soft |
|---|---|---|---|
| GitHub billing | per-token-account spend cap | month | hard (provider-enforced) |
| gh-aw workflow | `engine.model` (cheap default) | per-iteration | soft (cost reduction, not cap) |
| gh-aw workflow | `timeout-minutes` (45) | per-iteration | hard (kills agent) |
| gh-aw workflow | `stop-after: +90m` | per-trigger | hard (cancels run) |
| gh-aw workflow | `concurrency` | parallel runs | hard (queues) |
| gh-aw workflow | `safe-outputs.*.max` | per-iteration | hard (caps writes) |
| gh-aw engine | `max-turns` (claude) / `COPILOT_PROVIDER_MAX_*` (BYOK) | per-iteration | hard (engine-enforced) |
| Autoloop program | `cost.per-iteration.max-{tokens,usd}` | per-iteration | soft (post-hoc reject) |
| Autoloop program | `cost.budget.{window,max-*}` | day/week/month | hard (scheduler refuses) |
| Autoloop repo | `autoloop-budget` block in `AGENTS.md` | day/week/month | hard (scheduler refuses) |
| Autoloop scheduler | quality-aware downgrade | rolling | soft (cost reduction) |

The combination of *cheap default*, *per-iteration soft cap*,
*per-program hard $/week cap*, and *per-account hard $/month cap*
gives defense in depth without leaning on any one mechanism.

---

## 8. References

- gh-aw cost management: <https://github.github.com/gh-aw/reference/cost-management/>
- gh-aw engines reference: <https://github.github.com/gh-aw/reference/engines/>
- gh-aw rate-limiting controls: <https://github.github.com/gh-aw/reference/rate-limiting-controls/>
- gh-aw effective-tokens spec: <https://github.github.com/gh-aw/reference/effective-tokens-specification/>
- GitHub Copilot billing: <https://docs.github.com/en/copilot/about-github-copilot/subscription-plans-for-github-copilot>
- `workflows/autoloop.md` — current Autoloop workflow definition
- `workflows/scripts/autoloop_scheduler.py` — scheduler that owns the
  "which program runs next" decision and is the natural enforcement
  point for budgets
