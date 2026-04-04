"""
Extract scheduling functions directly from the workflow pre-step heredoc.

Instead of duplicating the workflow's JavaScript code in a separate module, we parse
workflows/autoloop.md, extract the JavaScript heredoc, write the function definitions
to a temp CommonJS module, and call them via Node.js subprocess.

This ensures tests always run against the actual workflow code.
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import timedelta

WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), "..", "workflows", "autoloop.md")

# Path to the extracted JS module
_JS_MODULE_PATH = os.path.join(tempfile.gettempdir(), "autoloop_test_functions.cjs")


def _load_workflow_functions():
    """Parse workflows/autoloop.md and extract JS function defs from the pre-step."""
    with open(WORKFLOW_PATH) as f:
        content = f.read()

    # Extract the JavaScript heredoc between JSEOF markers
    m = re.search(r"node - << 'JSEOF'\n(.*?)\n\s*JSEOF", content, re.DOTALL)
    assert m, "Could not find JSEOF heredoc in workflows/autoloop.md"
    source = m.group(1)

    # Extract function definitions: everything up to the main() async function.
    # Functions are defined before 'async function main()'
    lines = source.split("\n")
    func_lines = []
    for line in lines:
        if line.strip().startswith("async function main"):
            break
        func_lines.append(line)

    func_source = "\n".join(func_lines)

    # Write to a temp .cjs file with module.exports
    with open(_JS_MODULE_PATH, "w") as f:
        f.write(func_source)
        f.write(
            "\n\nmodule.exports = "
            "{ parseMachineState, parseSchedule, getProgramName, readProgramState, parseLinkHeader };\n"
        )

    return True


def _call_js(func_name, *args):
    """Call a JS function from the extracted workflow module and return the result."""
    args_json = json.dumps(list(args))
    escaped_path = json.dumps(_JS_MODULE_PATH)
    script = (
        "const m = require(" + escaped_path + ");\n"
        "const result = m." + func_name + "(..." + args_json + ");\n"
        "process.stdout.write(JSON.stringify(result === undefined ? null : result));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("Node.js error calling " + func_name + ": " + result.stderr)
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


# Initialize at import time
_load_workflow_functions()


def _parse_schedule_wrapper(s):
    """Python wrapper for JS parseSchedule. Converts milliseconds to timedelta."""
    ms = _call_js("parseSchedule", s)
    if ms is None:
        return None
    return timedelta(milliseconds=ms)


def _parse_machine_state_wrapper(content):
    """Python wrapper for JS parseMachineState."""
    return _call_js("parseMachineState", content)


def _get_program_name_wrapper(pf):
    """Python wrapper for JS getProgramName."""
    return _call_js("getProgramName", pf)


_funcs = {
    "parse_schedule": _parse_schedule_wrapper,
    "parse_machine_state": _parse_machine_state_wrapper,
    "get_program_name": _get_program_name_wrapper,
    "read_program_state": lambda name: _call_js("readProgramState", name),
    "parse_link_header": lambda header: _call_js("parseLinkHeader", header),
}


def _extract_inline_pattern(name):
    """Extract the JavaScript heredoc source from the workflow.

    This is a helper for inspecting the full inline source if needed.
    """
    with open(WORKFLOW_PATH) as f:
        content = f.read()
    m = re.search(r"node - << 'JSEOF'\n(.*?)\n\s*JSEOF", content, re.DOTALL)
    return m.group(1) if m else ""
