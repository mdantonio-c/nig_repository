"""#86: early ACK for long tasks, preserving retries and short-task late ACK."""

import ast
from pathlib import Path

import nig
import pytest

TASKS = Path(nig.__file__).parent / "tasks"


@pytest.mark.parametrize("name,late_ack", [
    ("launch_pipeline", False),
    ("launch_joint_analysis", False),
    ("omics_run_batch", False),
    ("omics_fetch_results", False),
    ("omics_poll_tasks", True),
    ("omics_cleanup", True),
    ("test_task", True),
])
def test_task_ack_and_autoretry_configuration(name: str, late_ack: bool) -> None:
    # The RAPyDo decorator is bound to an app at worker startup. Inspect the
    # declared options without connecting to a broker or launching a task.
    tree = ast.parse((TASKS / f"{name}.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    decorator = next(d for d in function.decorator_list if isinstance(d, ast.Call)
                     and isinstance(d.func, ast.Attribute) and d.func.attr == "task")
    options = {k.arg: k.value for k in decorator.keywords}
    assert ast.literal_eval(options["idempotent"]) is late_ack
    if name != "test_task":
        assert ast.unparse(options["autoretry_for"]) == "(ConnectionResetError,)"