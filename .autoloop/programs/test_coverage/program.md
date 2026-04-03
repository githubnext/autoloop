---
schedule: every 6h
---

# Test Coverage

## Goal

Increase test coverage across the repository. Add new test cases targeting untested code paths, edge cases, error handling, and boundary conditions.

Focus on:
- Functions and branches with low or no coverage
- Edge cases in existing test classes (unusual inputs, boundary values, empty/null cases)
- Error paths and exception handling
- Integration-style tests that exercise multiple components together

The metric is `coverage_percent`. **Higher is better.**

## Target

Only modify or create files in the test directory (e.g., `tests/`).

Do NOT modify:
- Source code (only tests)
- Configuration files
- CI/CD workflows

## Evaluation

```bash
python -m pytest tests/ --cov --cov-report=json -q 2>/dev/null && python3 -c "
import json
with open('coverage.json') as f:
    data = json.load(f)
total = data['totals']
print(json.dumps({
    'coverage_percent': round(total['percent_covered'], 2),
    'covered_lines': total['covered_lines'],
    'missing_lines': total['missing_lines']
}))
"
```

The metric is `coverage_percent` from the JSON output. **Higher is better.**
