"""
Evaluator for the Real-Time Adaptive Signal Processing Algorithm.

This is the OpenEvolve evaluator. Autoloop uses the inline evaluation
command in program.md instead, but this file is kept for reference
and for running OpenEvolve independently.

Multi-objective optimization function:
J(theta) = a1*S(theta) + a2*L_recent(theta) + a3*L_avg(theta) + a4*R(theta)

Where:
- S(theta): Slope change penalty - counts directional reversals
- L_recent(theta): Instantaneous lag error - |y[n] - x[n]|
- L_avg(theta): Average tracking error over window
- R(theta): False reversal penalty - mismatched trend changes
- a1=0.3, a2=a3=0.2, a4=0.3: Weighting coefficients
"""

import importlib.util
import numpy as np
import time
import concurrent.futures
import traceback
from scipy.stats import pearsonr


def run_with_timeout(func, args=(), kwargs={}, timeout_seconds=30):
    """Run a function with a timeout."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Function timed out after {timeout_seconds} seconds")


def safe_float(value):
    """Convert a value to float safely."""
    try:
        if np.isnan(value) or np.isinf(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def calculate_slope_changes(signal_data):
    """Calculate slope change penalty S(theta)."""
    if len(signal_data) < 3:
        return 0
    diffs = np.diff(signal_data)
    sign_changes = 0
    for i in range(1, len(diffs)):
        if np.sign(diffs[i]) != np.sign(diffs[i - 1]) and diffs[i - 1] != 0:
            sign_changes += 1
    return sign_changes


def calculate_composite_score(S, L_recent, L_avg, R, alpha=[0.3, 0.2, 0.2, 0.3]):
    """Calculate composite metric J(theta)."""
    S_norm = min(S / 50.0, 2.0)
    L_recent_norm = min(L_recent, 2.0)
    L_avg_norm = min(L_avg, 2.0)
    R_norm = min(R / 25.0, 2.0)
    penalty = alpha[0] * S_norm + alpha[1] * L_recent_norm + alpha[2] * L_avg_norm + alpha[3] * R_norm
    return 1.0 / (1.0 + penalty)


def generate_test_signals(num_signals=5):
    """Generate multiple test signals with different characteristics."""
    test_signals = []
    for i in range(num_signals):
        np.random.seed(42 + i)
        length = 500 + i * 100
        noise_level = 0.2 + i * 0.1
        t = np.linspace(0, 10, length)
        if i == 0:
            clean = 2 * np.sin(2 * np.pi * 0.5 * t) + 0.1 * t
        elif i == 1:
            clean = np.sin(2 * np.pi * 0.5 * t) + 0.5 * np.sin(2 * np.pi * 2 * t) + 0.2 * np.sin(2 * np.pi * 5 * t)
        elif i == 2:
            clean = np.sin(2 * np.pi * (0.5 + 0.2 * t) * t)
        elif i == 3:
            clean = np.concatenate([np.ones(length // 3), 2 * np.ones(length // 3), 0.5 * np.ones(length - 2 * (length // 3))])
        else:
            clean = np.cumsum(np.random.randn(length) * 0.1) + 0.05 * t
        noise = np.random.normal(0, noise_level, length)
        test_signals.append((clean + noise, clean))
    return test_signals


def evaluate(program_path):
    """Main evaluation function."""
    try:
        spec = importlib.util.spec_from_file_location("program", program_path)
        program = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(program)

        if not hasattr(program, "run_signal_processing"):
            return {"overall_score": 0.0, "error": "Missing run_signal_processing function"}

        test_signals = generate_test_signals(5)
        all_scores = []
        successful_runs = 0

        for i, (noisy_signal, clean_signal) in enumerate(test_signals):
            try:
                result = run_with_timeout(
                    program.run_signal_processing,
                    kwargs={"signal_length": len(noisy_signal), "noise_level": 0.3, "window_size": 20},
                    timeout_seconds=10,
                )

                if not isinstance(result, dict) or "filtered_signal" not in result:
                    continue

                filtered_signal = np.array(result["filtered_signal"])
                if len(filtered_signal) == 0:
                    continue

                window_size = 20
                S = calculate_slope_changes(filtered_signal)

                delay = window_size - 1
                L_recent = abs(filtered_signal[-1] - noisy_signal[delay + len(filtered_signal) - 1]) if len(noisy_signal) > delay + len(filtered_signal) - 1 else 1.0

                aligned_noisy = noisy_signal[delay:delay + len(filtered_signal)]
                min_length = min(len(filtered_signal), len(aligned_noisy))
                L_avg = np.mean(np.abs(filtered_signal[:min_length] - aligned_noisy[:min_length])) if min_length > 0 else 1.0

                aligned_clean = clean_signal[delay:delay + len(filtered_signal)]
                min_length = min(len(filtered_signal), len(aligned_clean))

                filtered_diffs = np.diff(filtered_signal[:min_length])
                clean_diffs = np.diff(aligned_clean[:min_length])
                R = 0
                if min_length > 2:
                    for j in range(1, len(filtered_diffs)):
                        f_change = np.sign(filtered_diffs[j]) != np.sign(filtered_diffs[j-1]) and filtered_diffs[j-1] != 0
                        c_change = np.sign(clean_diffs[j]) != np.sign(clean_diffs[j-1]) and clean_diffs[j-1] != 0
                        if f_change and not c_change:
                            R += 1

                composite_score = calculate_composite_score(S, L_recent, L_avg, R)

                correlation = 0.0
                noise_reduction = 0.0
                if min_length > 1:
                    corr_result = pearsonr(filtered_signal[:min_length], aligned_clean[:min_length])
                    correlation = corr_result[0] if not np.isnan(corr_result[0]) else 0.0

                noise_before = np.var(aligned_noisy[:min_length] - aligned_clean[:min_length])
                noise_after = np.var(filtered_signal[:min_length] - aligned_clean[:min_length])
                noise_reduction = max(0, (noise_before - noise_after) / noise_before) if noise_before > 0 else 0

                smooth = 1.0 / (1.0 + S / 20.0)
                overall = 0.4 * composite_score + 0.2 * smooth + 0.2 * max(0, correlation) + 0.1 * noise_reduction + 0.1 * 1.0
                all_scores.append(overall)
                successful_runs += 1

            except Exception as e:
                print(f"Signal {i}: Error - {str(e)}")

        if successful_runs == 0:
            return {"overall_score": 0.0, "error": "All signals failed"}

        return {
            "overall_score": float(np.mean(all_scores)),
            "success_rate": successful_runs / 5,
        }

    except Exception as e:
        return {"overall_score": 0.0, "error": str(e)}
