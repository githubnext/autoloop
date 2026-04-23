"""Test fixtures for the standalone Autoloop scheduler.

The scheduler logic lives in ``workflows/scripts/autoloop_scheduler.py`` and is
also distributed at ``.github/workflows/scripts/autoloop_scheduler.py`` (the
dogfooded deploy copy). Tests import the source module directly via importlib.
"""

import importlib.util
import os
import sys

# Path to the standalone scheduler script (source-of-truth lives in workflows/).
SCHEDULER_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "workflows",
        "scripts",
        "autoloop_scheduler.py",
    )
)

_spec = importlib.util.spec_from_file_location("autoloop_scheduler", SCHEDULER_PATH)
autoloop_scheduler = importlib.util.module_from_spec(_spec)
sys.modules["autoloop_scheduler"] = autoloop_scheduler
_spec.loader.exec_module(autoloop_scheduler)


# Backwards-compatible function map (mirrors the previous JS-extracting conftest).
_funcs = {
    "parse_schedule": autoloop_scheduler.parse_schedule,
    "parse_machine_state": autoloop_scheduler.parse_machine_state,
    "get_program_name": autoloop_scheduler.get_program_name,
    "read_program_state": autoloop_scheduler.read_program_state,
    "parse_link_header": autoloop_scheduler.parse_link_header,
}
