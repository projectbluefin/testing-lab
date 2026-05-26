"""
Smoke test environment — qecore TestSandbox for GNOME Shell.

Pattern sourced from: modehnal/GNOMETerminalAutomation features/environment.py
qecore source: gitlab.com/dogtail/qecore

qecore-headless (invoked by the Argo runner) handles:
  - DBUS_SESSION_BUS_ADDRESS
  - WAYLAND_DISPLAY / XDG_RUNTIME_DIR
  - gnome-ponytail-daemon activation
  - AT-SPI bus bridge
"""
import os
import re
import subprocess
import sys
import time
import traceback

from dogtail.config import config as dogtail_config
from qecore.sandbox import TestSandbox
from qecore.common_steps import *  # noqa: F401,F403 — registers all common @step definitions


def _shell_eval_inner(js: str) -> str:
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.Shell",
            "--object-path",
            "/org/gnome/Shell",
            "--method",
            "org.gnome.Shell.Eval",
            js,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown gdbus failure"
        raise RuntimeError(stderr[:200])

    match = re.search(r"\((?:true|false),\s*'(.*)'\)", result.stdout.strip())
    if match is None:
        raise RuntimeError(f"unexpected Shell.Eval output: {result.stdout.strip()[:200]}")
    inner = match.group(1)
    if inner.startswith('"') and inner.endswith('"'):
        return inner[1:-1]
    return inner


def _shell_snapshot(shell) -> str:
    lines = []

    def _walk(node, depth=0, max_depth=3):
        prefix = "  " * depth
        lines.append(
            f"{prefix}role={node.roleName!r:25} name={node.name!r:30} showing={node.showing}"
        )
        if depth < max_depth:
            for child in node.children[:25]:
                _walk(child, depth + 1, max_depth)

    _walk(shell, max_depth=3)
    return "\n".join(lines)


def _write_atspi_tree(shell) -> None:
    import os

    os.makedirs("/tmp/results", exist_ok=True)
    with open("/tmp/results/atspi_tree.txt", "w") as handle:
        handle.write(_shell_snapshot(shell))


def _ensure_unsafe_mode(stage: str, attempts: int = 5, delay: int = 2) -> None:
    last_error = "unknown"

    for attempt in range(1, attempts + 1):
        try:
            inner = _shell_eval_inner(
                "global.context.unsafe_mode = true; "
                "global.context.unsafe_mode === true ? 'true' : 'false'"
            )
            if inner == "true":
                return
            last_error = f"unsafe_mode inner result was {inner!r} at {stage} attempt {attempt}"
        except Exception as error:  # noqa: BLE001
            last_error = f"{stage} attempt {attempt}: {error}"

        if attempt < attempts:
            time.sleep(delay)

    raise RuntimeError(
        f"unsafe_mode activation failed during {stage} after {attempts} attempts: {last_error}"
    )


def _wait_for_panel(context, attempts: int = 6, delay: int = 5) -> None:
    last_snapshot = "unavailable"
    last_error = "unknown"

    for attempt in range(1, attempts + 1):
        try:
            shell = context.sandbox.shell
            panels = shell.findChildren(lambda node: node.roleName == "panel")
            if panels:
                toggles = panels[0].findChildren(lambda node: node.roleName == "toggle button")
                if toggles:
                    context.panel = panels[0]
                    return
                last_error = f"panel found but no visible toggle buttons yet (attempt {attempt})"
            else:
                last_error = f"panel not exposed in AT-SPI yet (attempt {attempt})"
            last_snapshot = _shell_snapshot(shell)
        except Exception as error:  # noqa: BLE001
            last_error = str(error)
            last_snapshot = f"unable to snapshot shell: {error}"
        if attempt < attempts:
            time.sleep(delay)

    try:
        _write_atspi_tree(context.sandbox.shell)
    except Exception:  # noqa: BLE001
        pass

    raise RuntimeError(
        "GNOME Shell panel/top-bar readiness failed inside behave before_all.\n"
        f"Last error: {last_error}\n"
        f"Last shell snapshot:\n{last_snapshot}"
    )


def before_all(context) -> None:
    # searchShowingOnly=True: all dogtail searches implicitly filter to .showing
    # nodes — removes need for redundant `.showing` predicates in step code.
    dogtail_config.searchShowingOnly = True

    # Initialize sandbox
    try:
        context.sandbox = TestSandbox("gnome-shell", context=context)
        context.sandbox.attach_faf = False
        context.sandbox.production = False
        context.shell_ready = False
        # Read test start time written by workflow before behave started (issue #6)
        _start_time_file = "/tmp/results/test-start-time.txt"
        if os.path.exists(_start_time_file):
            with open(_start_time_file) as _f:
                context.test_start_time = _f.read().strip()
        else:
            context.test_start_time = subprocess.run(
                ["date", "--iso-8601=seconds"], capture_output=True, text=True
            ).stdout.strip()
    except Exception as error:
        raise RuntimeError(f"before_all sandbox setup failed: {error}") from error

def before_scenario(context, scenario) -> None:
    # Initialize qecore command output attributes (attribute name varies by version)
    # qecore 4.16: command_stdout; older: last_command_output
    context.command_stdout = ""
    context.last_command_output = ""
    try:
        if not hasattr(context, "sandbox"):
            raise RuntimeError("TestSandbox was not initialized in before_all")
        context.sandbox.before_scenario(context, scenario)
        if not getattr(context, "shell_ready", False):
            _ensure_unsafe_mode("before_scenario post-sandbox")
            _wait_for_panel(context)
            context.shell_ready = True
    except Exception as error:
        tb = traceback.format_exc()
        raise RuntimeError(
            f"before_scenario failed for {scenario.name}: {error}\n{tb}"
        ) from error


def after_scenario(context, scenario) -> None:
    context.sandbox.after_scenario(context, scenario)


def after_step(context, step) -> None:
    """Print full traceback for errored steps — needed because behave JSON
    serialises error_message as empty when the exception has no str()."""
    if step.status.name in ("error", "failed") and step.exception is not None:
        print(
            f"\nSTEP_ERROR [{step.name!r}]: "
            f"{type(step.exception).__name__}: {step.exception}",
            flush=True,
        )
        traceback.print_exception(
            type(step.exception),
            step.exception,
            step.exception.__traceback__,
            file=sys.stderr,
        )


def after_all(context) -> None:
    """Dump gnome-shell AT-SPI tree to results for node name discovery.
    Runs after the last scenario while the session is still active enough
    for the sandbox to have a valid shell handle.
    """
    try:
        import os
        if os.path.exists("/tmp/results/atspi_tree.txt") or not hasattr(context, "sandbox"):
            return  # already written by after_scenario
        _write_atspi_tree(context.sandbox.shell)
    except Exception:   # noqa: BLE001
        pass
