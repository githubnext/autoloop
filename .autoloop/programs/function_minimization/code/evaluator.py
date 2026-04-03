"""
Evaluator for the function minimization example.

This is the OpenEvolve evaluator. Autoloop uses the inline evaluation
command in program.md instead, but this file is kept for reference
and for running OpenEvolve independently.
"""

import importlib.util
import numpy as np
import time
import concurrent.futures
import traceback


def run_with_timeout(func, args=(), kwargs={}, timeout_seconds=5):
    """Run a function with a timeout using concurrent.futures."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            result = future.result(timeout=timeout_seconds)
            return result
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Function timed out after {timeout_seconds} seconds")


def safe_float(value):
    """Convert a value to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        print(f"Warning: Could not convert {value} of type {type(value)} to float")
        return 0.0


def evaluate(program_path):
    """
    Evaluate the program by running it multiple times and checking how close
    it gets to the known global minimum.
    """
    GLOBAL_MIN_X = -1.704
    GLOBAL_MIN_Y = 0.678
    GLOBAL_MIN_VALUE = -1.519

    try:
        spec = importlib.util.spec_from_file_location("program", program_path)
        program = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(program)

        if not hasattr(program, "run_search"):
            print(f"Error: program does not have 'run_search' function")
            return {
                "value_score": 0.0,
                "distance_score": 0.0,
                "reliability_score": 0.0,
                "combined_score": 0.0,
                "error": "Missing run_search function",
            }

        num_trials = 10
        x_values = []
        y_values = []
        values = []
        distances = []
        times = []
        success_count = 0

        for trial in range(num_trials):
            try:
                start_time = time.time()
                result = run_with_timeout(program.run_search, timeout_seconds=5)

                if isinstance(result, tuple):
                    if len(result) == 3:
                        x, y, value = result
                    elif len(result) == 2:
                        x, y = result
                        value = np.sin(x) * np.cos(y) + np.sin(x * y) + (x**2 + y**2) / 20
                    else:
                        continue
                else:
                    continue

                end_time = time.time()

                x = safe_float(x)
                y = safe_float(y)
                value = safe_float(value)

                if any(np.isnan(v) or np.isinf(v) for v in [x, y, value]):
                    continue

                distance_to_global = np.sqrt((x - GLOBAL_MIN_X)**2 + (y - GLOBAL_MIN_Y)**2)

                x_values.append(x)
                y_values.append(y)
                values.append(value)
                distances.append(distance_to_global)
                times.append(end_time - start_time)
                success_count += 1

            except TimeoutError as e:
                print(f"Trial {trial}: {str(e)}")
            except Exception as e:
                print(f"Trial {trial}: Error - {str(e)}")

        if success_count == 0:
            return {
                "value_score": 0.0,
                "distance_score": 0.0,
                "reliability_score": 0.0,
                "combined_score": 0.0,
                "error": "All trials failed",
            }

        avg_value = float(np.mean(values))
        avg_distance = float(np.mean(distances))

        value_score = float(1.0 / (1.0 + abs(avg_value - GLOBAL_MIN_VALUE)))
        distance_score = float(1.0 / (1.0 + avg_distance))
        reliability_score = float(success_count / num_trials)

        if avg_distance < 0.5:
            multiplier = 1.5
        elif avg_distance < 1.5:
            multiplier = 1.2
        elif avg_distance < 3.0:
            multiplier = 1.0
        else:
            multiplier = 0.7

        base_score = 0.5 * value_score + 0.3 * distance_score + 0.2 * reliability_score
        combined_score = float(base_score * multiplier)

        return {
            "value_score": value_score,
            "distance_score": distance_score,
            "reliability_score": reliability_score,
            "combined_score": combined_score,
        }

    except Exception as e:
        print(f"Evaluation failed: {str(e)}")
        return {
            "value_score": 0.0,
            "distance_score": 0.0,
            "reliability_score": 0.0,
            "combined_score": 0.0,
            "error": str(e),
        }
