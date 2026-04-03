---
schedule: every 6h
timeout-minutes: 40
---

# Signal Processing

## Goal

Improve the adaptive signal processing algorithm in `.autoloop/programs/signal_processing/code/initial_program.py` to filter volatile, non-stationary time series data in real time while preserving genuine signal dynamics.

The algorithm must process a noisy input signal using a sliding window approach and produce a filtered output. The initial implementation is a simple weighted moving average that over-smooths and introduces lag.

Each iteration should improve the functions inside the `# EVOLVE-BLOCK-START` / `# EVOLVE-BLOCK-END` markers (primarily `adaptive_filter`, `enhanced_filter_with_trend_preservation`, and `process_signal`) to better handle:

1. **Noise filtering**: Remove high-frequency noise from volatile, non-stationary signals
2. **Trend preservation**: Preserve genuine signal dynamics and trend changes
3. **Smoothness**: Minimize spurious directional reversals caused by noise
4. **Responsiveness**: Achieve near-zero phase delay for real-time applications
5. **Robustness**: Perform consistently across diverse signal types (sinusoidal, multi-frequency, non-stationary, step changes, random walk)

Consider techniques such as Kalman filtering, Savitzky-Golay filters, wavelet denoising, particle filters, adaptive exponential smoothing, empirical mode decomposition, or hybrid approaches.

The evaluation runs 5 different test signals and scores using a multi-objective composite metric:

- **Composite score** (40%): `J = 1/(1 + a1*S + a2*L_recent + a3*L_avg + a4*R)` where S=slope changes, L_recent=instantaneous lag, L_avg=average tracking error, R=false reversals (a1=a4=0.3, a2=a3=0.2)
- **Smoothness score** (20%): `1/(1 + slope_changes/20)`
- **Accuracy score** (20%): Pearson correlation with clean ground truth signal
- **Noise reduction** (10%): Variance reduction ratio vs noisy input
- **Success rate** (10%): Fraction of test signals processed without error

The metric is `overall_score`. **Higher is better.**

## Target

Only modify these files:

- `.autoloop/programs/signal_processing/code/initial_program.py` -- the signal processing algorithm (only code between `EVOLVE-BLOCK-START` and `EVOLVE-BLOCK-END`)

Do NOT modify:

- `.autoloop/programs/signal_processing/code/evaluator.py` -- the evaluation script
- `.autoloop/programs/signal_processing/code/config.yaml` -- configuration for OpenEvolve
- `.autoloop/programs/signal_processing/code/requirements.txt` -- dependencies
- The `generate_test_signal`, `run_signal_processing` functions outside the evolve block in `initial_program.py`

## Evaluation

```bash
pip install -q numpy scipy && python3 -c "
import importlib.util, numpy as np, json, time
from scipy.stats import pearsonr

spec = importlib.util.spec_from_file_location('program', '.autoloop/programs/signal_processing/code/initial_program.py')
program = importlib.util.module_from_spec(spec)
spec.loader.exec_module(program)

def gen_signals():
    signals = []
    for i in range(5):
        np.random.seed(42 + i)
        length = 500 + i * 100
        noise_level = 0.2 + i * 0.1
        t = np.linspace(0, 10, length)
        if i == 0: clean = 2*np.sin(2*np.pi*0.5*t) + 0.1*t
        elif i == 1: clean = np.sin(2*np.pi*0.5*t) + 0.5*np.sin(2*np.pi*2*t) + 0.2*np.sin(2*np.pi*5*t)
        elif i == 2: clean = np.sin(2*np.pi*(0.5+0.2*t)*t)
        elif i == 3: clean = np.concatenate([np.ones(length//3), 2*np.ones(length//3), 0.5*np.ones(length-2*(length//3))])
        else: clean = np.cumsum(np.random.randn(length)*0.1) + 0.05*t
        signals.append((clean + np.random.normal(0, noise_level, length), clean))
    return signals

scores, successes = [], 0
for i, (noisy, clean) in enumerate(gen_signals()):
    try:
        result = program.run_signal_processing(signal_length=len(noisy), noise_level=0.3, window_size=20)
        if not isinstance(result, dict) or 'filtered_signal' not in result: continue
        filt = np.array(result['filtered_signal'])
        if len(filt) == 0: continue
        ws = 20; delay = ws - 1
        S = sum(1 for j in range(2, len(filt)) if np.sign(filt[j]-filt[j-1]) != np.sign(filt[j-1]-filt[j-2]) and filt[j-1] != filt[j-2])
        L_recent = abs(filt[-1] - noisy[delay+len(filt)-1]) if len(noisy) > delay+len(filt)-1 else 1.0
        ac = clean[delay:delay+len(filt)]; ml = min(len(filt), len(ac))
        L_avg = np.mean(np.abs(filt[:ml] - noisy[delay:delay+ml])) if ml > 0 else 1.0
        fd, cd = np.diff(filt[:ml]), np.diff(ac[:ml])
        R = sum(1 for j in range(1,len(fd)) if (np.sign(fd[j])!=np.sign(fd[j-1]) and fd[j-1]!=0) and not (np.sign(cd[j])!=np.sign(cd[j-1]) and cd[j-1]!=0)) if ml > 2 else 0
        comp = 1.0/(1.0 + 0.3*min(S/50,2) + 0.2*min(L_recent,2) + 0.2*min(L_avg,2) + 0.3*min(R/25,2))
        smooth = 1.0/(1.0+S/20.0)
        corr = pearsonr(filt[:ml], ac[:ml])[0] if ml > 1 else 0.0
        corr = 0.0 if np.isnan(corr) else corr
        nb = np.var(noisy[delay:delay+ml]-ac[:ml]); na = np.var(filt[:ml]-ac[:ml])
        nr = max(0, (nb-na)/nb) if nb > 0 else 0
        overall = 0.4*comp + 0.2*smooth + 0.2*max(0,corr) + 0.1*nr + 0.1*1.0
        scores.append(overall); successes += 1
    except Exception as e:
        print(f'Signal {i}: {e}')

if successes == 0:
    print(json.dumps({'overall_score': 0.0, 'initial_score': 0.0}))
else:
    avg = np.mean(scores)
    print(json.dumps({
        'overall_score': round(float(avg), 4),
        'success_rate': round(successes/5, 2),
        'initial_score': 0.34
    }))
"
```

The metric is `overall_score` from the JSON output. **Higher is better.**
The `initial_score` field (0.34) records the baseline from the naive weighted moving average for reference.

## Evolution Strategy (inspired by OpenEvolve)

This section guides how the autoloop agent should approach proposing changes across iterations.

### Configuration

At the start of each iteration, **read `.autoloop/programs/signal_processing/code/config.yaml`** and use its values to drive the evolution strategy. Do not assume hard-coded values -- always read the config file fresh, as the user may tune parameters between runs.

### 1. Population Tracking

In the **state file** (`signal_processing.md` in the repo-memory folder) under a **Population** subsection within Lessons Learned, maintain a **population** of distinct solution variants (sized proportionally to `database.population_size` from the config), each with:

- **code**: The full evolve block content
- **overall_score**: The evaluation metric
- **algorithm_type**: A short label (e.g., "moving_average", "kalman_filter", "savitzky_golay", "wavelet", "particle_filter", "hybrid")
- **code_complexity**: Approximate line count of the evolve block
- **generation**: Which iteration produced it
- **parent_id**: Which population member it was derived from (null for the initial program)
- **island**: Which conceptual island this solution belongs to

Store this in the state file as a markdown table or fenced code block. Do **not** store it in the machine-state JSON file.

### 2. Island Model (Conceptual)

Read `database.num_islands` from the config and organize the population into conceptual islands:

- **Island 0**: Moving average / exponential smoothing variants
- **Island 1**: Kalman filter / state-space model variants
- **Island 2**: Frequency-domain approaches (wavelets, Savitzky-Golay, FFT-based)
- **Island 3**: Hybrid / ensemble / novel approaches

### 3. Exploration vs Exploitation

Read `database.exploitation_ratio` from the config and choose strategy accordingly.

### 4. Cascade Evaluation

Read `evaluator.cascade_evaluation` and `evaluator.cascade_thresholds` from the config. Apply multi-stage mental filtering to proposed changes.

### 5. Diff-Based Evolution

Read `diff_based_evolution` from the config. If true, prefer **small, targeted diffs** over full rewrites.

### 6. Plateau Detection

If the last 3 consecutive iterations were rejected, switch strategy. If 5, try a radically different algorithm family.
