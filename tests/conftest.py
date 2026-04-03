"""
Extract scheduling functions directly from the workflow pre-step heredoc.

Instead of duplicating the workflow's Python code in a separate module, we parse
workflows/autoloop.md, extract the Python heredoc, pull out function definitions
via the AST, and exec them into a namespace that tests can import from.

This ensures tests always run against the actual workflow code.
"""

import ast
import os
import re
import textwrap

WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), "..", "workflows", "autoloop.md")


def _load_workflow_functions():
    """Parse workflows/autoloop.md and extract Python function defs from the pre-step."""
    with open(WORKFLOW_PATH) as f:
        content = f.read()

    # Extract the Python heredoc between PYEOF markers
    m = re.search(r"python3 - << 'PYEOF'\n(.*?)\n\s*PYEOF", content, re.DOTALL)
    assert m, "Could not find PYEOF heredoc in workflows/autoloop.md"
    source = textwrap.dedent(m.group(1))

    # Parse AST and extract only top-level FunctionDef nodes
    tree = ast.parse(source)
    source_lines = source.splitlines(keepends=True)
    func_sources = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            func_sources.append("".join(source_lines[node.lineno - 1 : node.end_lineno]))

    # Execute function defs with their required imports
    ns = {}
    preamble = "import os, re, json\nfrom datetime import datetime, timezone, timedelta\n\n"
    exec(preamble + "\n".join(func_sources), ns)  # noqa: S102
    return ns


# Load once at import time
_funcs = _load_workflow_functions()


def _extract_inline_pattern(name):
    """Extract an inline code pattern from the workflow by name.

    This is a helper for extracting small inline patterns (like the slugify regex)
    that aren't wrapped in function defs in the workflow source.
    """
    with open(WORKFLOW_PATH) as f:
        content = f.read()
    m = re.search(r"python3 - << 'PYEOF'\n(.*?)\n\s*PYEOF", content, re.DOTALL)
    return textwrap.dedent(m.group(1)) if m else ""
