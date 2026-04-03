---
schedule: every 6h
timeout-minutes: 30
---

# Autoresearch

## Goal

Minimize `val_bpb` (validation bits-per-byte) for LLM training within a fixed 5-minute training budget on available hardware (GPU if available, otherwise CPU).

This is an autonomous AI research loop inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch): each iteration modifies the training code, runs a 5-minute training experiment, and keeps changes only if they improve the metric. Everything in `train.py` is fair game: model architecture, optimizer, hyperparameters, training loop, batch size, model size, etc.

**The goal is simple: get the lowest val_bpb.** Lower is better.

**VRAM** is a soft constraint. Some increase is acceptable for meaningful val_bpb gains, but it should not blow up dramatically.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win.

Key context:
- Read `.autoloop/programs/autoresearch/code/prepare.py` for fixed constants, data prep, tokenizer, dataloader, evaluation (DO NOT MODIFY)
- Read `.autoloop/programs/autoresearch/code/train.py` for the current model architecture, optimizer, and training loop (THIS is what you modify)
- Data and tokenizer are prepared automatically by `prepare.py` on first run

## Target

Only modify these files:

- `.autoloop/programs/autoresearch/code/train.py` -- the training script: model architecture, optimizer, hyperparameters, training loop

Do NOT modify:

- `.autoloop/programs/autoresearch/code/prepare.py` -- fixed evaluation harness, data loading, tokenizer, training constants
- `.autoloop/programs/autoresearch/code/pyproject.toml` -- dependencies (you can only use what's already available)

## Evaluation

```bash
cd .autoloop/programs/autoresearch/code && timeout 360 uv run train.py > run.log 2>&1; cat run.log | python3 -c "
import sys, json, re

log = sys.stdin.read()
val_bpb = None
peak_vram = None

for line in log.split('\n'):
    m = re.match(r'^val_bpb:\s+([\d.]+)', line)
    if m:
        val_bpb = float(m.group(1))
    m = re.match(r'^peak_vram_mb:\s+([\d.]+)', line)
    if m:
        peak_vram = float(m.group(1))

if val_bpb is not None:
    score = 1.0 / val_bpb
    memory_gb = round(peak_vram / 1024, 1) if peak_vram else 0.0
    print(json.dumps({
        'combined_score': round(score, 6),
        'val_bpb': round(val_bpb, 6),
        'memory_gb': memory_gb
    }))
else:
    last_lines = '\n'.join(log.split('\n')[-20:])
    print(json.dumps({
        'combined_score': 0.0,
        'val_bpb': 0.0,
        'error': 'Training did not produce val_bpb output',
        'log_tail': last_lines[:500]
    }))
"
```

The metric is `combined_score`. **Higher is better** (it is `1/val_bpb`, so lower val_bpb = higher score).

## Evolution Strategy

### Population Tracking

Maintain a population of up to 10 distinct training configurations, each with:
- Key hyperparameters / architecture choices that differ from baseline
- `val_bpb` and `combined_score`
- Peak memory usage
- Strategy label (e.g., "baseline", "wider_model", "cosine_lr", "muon_optimizer")

### Island Model

Organize the population into 4 conceptual islands:

- **Island 0: Architecture** — model width, depth, attention heads, activation functions, normalization, positional encodings
- **Island 1: Optimizer & LR** — optimizer choice, learning rate schedules, warmup, weight decay, gradient clipping
- **Island 2: Training efficiency** — batch size, gradient accumulation, mixed precision, compilation flags, data loading, sequence packing
- **Island 3: Hybrid & novel** — combining techniques from other islands, unconventional training schemes

### Exploration vs Exploitation

- **Exploitation (60%)**: Refine the current best solution — tweak hyperparameters, small architecture adjustments
- **Exploration (30%)**: Try a fundamentally different approach from an under-explored island
- **Weighted random (10%)**: Pick any population member and make a moderate change

### Training Design Principles

- **Crashes waste time**: Validate changes mentally before running
- **VRAM is finite**: Be conservative with memory-hungry changes
- **Simplicity wins**: A simpler model that trains faster within the budget may beat a complex model that doesn't converge in time
- **Only use available packages**: Check `pyproject.toml` — do not install new packages

### Plateau Detection

- After 3 consecutive rejections: switch strategy family (e.g., from hyperparams to architecture)
- After 5 consecutive rejections: try a radically different approach from an unexplored island
