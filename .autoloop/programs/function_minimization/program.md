---
schedule: every 6h
timeout-minutes: 40
---

# Function Minimization

## Goal

Improve the search algorithm in `.autoloop/programs/function_minimization/code/initial_program.py` to reliably find the global minimum of the complex function:

`f(x, y) = sin(x) * cos(y) + sin(x*y) + (x^2 + y^2) / 20`

The function has many local minima. The known global minimum is approximately at `(-1.704, 0.678)` with a value of approximately `-1.519`. The initial implementation is a naive random search that often gets stuck in local minima.

Each iteration should improve the `search_algorithm` function (inside the `# EVOLVE-BLOCK-START` / `# EVOLVE-BLOCK-END` markers) to better escape local minima, converge closer to the global minimum, and do so reliably across multiple trials. Consider techniques such as simulated annealing, gradient estimation, adaptive step sizing, multi-start strategies, basin-hopping, or other optimization methods.

The evaluation runs 10 trials and scores based on:

- **value_score** (50%): How close the found minimum value is to the global minimum
- **distance_score** (30%): How close the found (x, y) is to the known global minimum location
- **reliability_score** (20%): Fraction of trials that succeed (no timeouts or errors)
- A **solution quality multiplier** boosts the score when the average distance to the global minimum is < 0.5

The metric is `combined_score`. **Higher is better.**

## Target

Only modify these files:

- `.autoloop/programs/function_minimization/code/initial_program.py` -- the search algorithm to optimize (only code between `EVOLVE-BLOCK-START` and `EVOLVE-BLOCK-END`)

Do NOT modify:

- `.autoloop/programs/function_minimization/code/evaluator.py` -- the evaluation script
- `.autoloop/programs/function_minimization/code/config.yaml` -- configuration for OpenEvolve
- `.autoloop/programs/function_minimization/code/requirements.txt` -- dependencies
- The `evaluate_function` or `run_search` functions outside the evolve block in `initial_program.py`

## Evaluation

```bash
pip install -q numpy scipy && python3 -c "
import importlib.util, numpy as np, json

spec = importlib.util.spec_from_file_location('program', '.autoloop/programs/function_minimization/code/initial_program.py')
program = importlib.util.module_from_spec(spec)
spec.loader.exec_module(program)

GLOBAL_MIN_X, GLOBAL_MIN_Y, GLOBAL_MIN_VALUE = -1.704, 0.678, -1.519
num_trials = 10
values, distances, successes = [], [], 0

for trial in range(num_trials):
    try:
        x, y, value = program.run_search()
        x, y, value = float(x), float(y), float(value)
        if any(np.isnan(v) or np.isinf(v) for v in [x, y, value]):
            continue
        dist = np.sqrt((x - GLOBAL_MIN_X)**2 + (y - GLOBAL_MIN_Y)**2)
        values.append(value)
        distances.append(dist)
        successes += 1
    except Exception as e:
        print(f'Trial {trial}: {e}')

if successes == 0:
    print(json.dumps({'combined_score': 0.0, 'initial_score': 0.0}))
else:
    avg_val = np.mean(values)
    avg_dist = np.mean(distances)
    value_score = 1.0 / (1.0 + abs(avg_val - GLOBAL_MIN_VALUE))
    distance_score = 1.0 / (1.0 + avg_dist)
    reliability_score = successes / num_trials
    multiplier = 1.5 if avg_dist < 0.5 else 1.2 if avg_dist < 1.5 else 1.0 if avg_dist < 3.0 else 0.7
    combined = (0.5 * value_score + 0.3 * distance_score + 0.2 * reliability_score) * multiplier
    print(json.dumps({
        'combined_score': round(combined, 4),
        'value_score': round(value_score, 4),
        'distance_score': round(distance_score, 4),
        'reliability_score': round(reliability_score, 4),
        'avg_value': round(avg_val, 4),
        'avg_distance': round(avg_dist, 4),
        'multiplier': multiplier,
        'initial_score': 0.56
    }))
"
```

The metric is `combined_score` from the JSON output. **Higher is better.**
The `initial_score` field (0.56) records the baseline from the naive random search for reference.

## Evolution Strategy (inspired by OpenEvolve)

This section guides how the autoloop agent should approach proposing changes across iterations. The ideas are adapted from OpenEvolve's evolutionary programming framework.

### 1. Population Tracking

Do not just track the single best solution. In the **state file** (`function_minimization.md` in the repo-memory folder) under a **Population** subsection within Lessons Learned, maintain a **population** of up to 10 distinct solution variants, each with:

- **code**: The full `search_algorithm` function body
- **combined_score**: The evaluation metric
- **algorithm_type**: A short label (e.g., "simulated_annealing", "basin_hopping", "gradient_descent", "particle_swarm")
- **code_complexity**: Approximate line count of the evolve block
- **generation**: Which iteration produced it
- **parent_id**: Which population member it was derived from (null for the initial program)

Store this in the state file as a markdown table or fenced code block (JSON). Do **not** store it in the machine-state JSON file.

### 2. Exploration vs Exploitation

Each iteration, choose a strategy using these approximate probabilities:

- **Exploitation (70%)**: Take the current best-scoring solution (or one of the top 3) and make a small, targeted refinement.
- **Exploration (20%)**: Try a fundamentally different algorithmic approach that no current population member uses.
- **Weighted random (10%)**: Pick any population member (weighted by score) and make a moderate change.

### 3. Inspiration from Population

When proposing a change, don't just look at the parent solution. Draw **inspiration** from other population members:

- Always review the **best-scoring** solution's approach
- Review 1-2 **diverse** solutions that use different algorithm types
- Look for **unique features** in each that could be combined

### 4. Diff-Based Evolution

Prefer **small, targeted diffs** over full rewrites:

- When refining an existing approach (exploitation), change only the specific lines that matter
- Full rewrites are acceptable only during exploration when trying a completely different algorithm

### 5. Novelty Check

Before implementing a proposed change, check the state file's **Foreclosed Avenues** section and the population table:

- Do not repeat essentially the same approach as a foreclosed avenue
- Ensure meaningful differences from existing population members

### 6. Feature Diversity (MAP-Elites Style)

Track solutions along two feature dimensions:

- **algorithm_type**: The broad category (random_search, simulated_annealing, gradient_based, evolutionary, hybrid, etc.)
- **code_complexity**: Simple (< 20 lines), medium (20-50 lines), complex (> 50 lines)

When the population is full (10 members), a new solution replaces an existing member only if it scores higher in the same feature cell or occupies an empty niche.

### 7. Plateau Detection and Adaptation

If the last 3 consecutive iterations were rejected:
- Switch strategy: if you've been exploiting, try exploring (and vice versa)
- Consider combining techniques from the two best-scoring population members

If the last 5 consecutive iterations were rejected:
- Try a radically different approach: a completely new algorithm family
- Consider whether the evaluation metric rewards something the current approaches don't optimize for
