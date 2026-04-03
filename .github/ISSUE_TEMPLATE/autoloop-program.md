---
name: Autoloop Program
about: Create a new Autoloop optimization program
title: ''
labels: autoloop-program
---

<!-- AUTOLOOP:ISSUE-PROGRAM -->
<!-- This issue defines an Autoloop program. The format is identical to program.md files. -->
<!-- Autoloop will discover this issue by its label and run iterations automatically. -->
<!-- After each run, a status comment will be posted/updated with links and results. -->

---
schedule: every 6h
# target-metric: 0.95  ← uncomment and set to make this a goal-oriented program that stops when reached
---

# Program Name

## Goal

<!-- Describe what you want to optimize. Be specific about what 'better' means. -->
<!-- Choose one of the following program types: -->
<!-- • Goal-oriented: Has a finish line. Set target-metric above and describe the target here. -->
<!--   Example: "Increase test coverage to at least 95%." -->
<!-- • Open-ended: Runs forever, always seeking improvement. Leave target-metric commented out. -->
<!--   Example: "Continuously improve algorithm performance." -->

REPLACE THIS with your optimization goal.

## Target

<!-- List files Autoloop may modify. Everything else is off-limits. -->

Only modify these files:
- `REPLACE_WITH_FILE` -- (describe what this file does)

Do NOT modify:
- (list files that must not be touched)

## Evaluation

<!-- Provide a command and the metric to extract. -->

```bash
REPLACE_WITH_YOUR_EVALUATION_COMMAND
```

The metric is `REPLACE_WITH_METRIC_NAME`. **Lower/Higher is better.** (pick one)
