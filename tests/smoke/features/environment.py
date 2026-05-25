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
import sys
import traceback

from qecore.sandbox import TestSandbox
from qecore.common_steps import *  # noqa: F401,F403 — registers all common @step definitions


def before_all(context) -> None:
    import time
    # Give GNOME Shell a moment to settle after qecore-headless restarts GDM.
    # Without this, get_application() races against AT-SPI bus initialization.
    time.sleep(8)
    try:
        context.sandbox = TestSandbox("gnome-shell", context=context)
        context.sandbox.attach_faf = False          # no ABRT integration in lab
        context.sandbox.production = False          # disable screencast/journal embeds locally

        # gnome-shell is always running — use context.sandbox.shell (qecore built-in)
        # rather than get_application() which just re-wraps the same object.
        context.shell = context.sandbox.shell
    except Exception as error:
        print(f"Environment error: before_all: {error}", flush=True)
        context.failed_setup = traceback.format_exc()


def before_scenario(context, scenario) -> None:
    try:
        context.sandbox.before_scenario(context, scenario)
    except Exception:
        tb = traceback.format_exc()
        print(f"HOOK_ERROR in before_scenario:\n{tb}", flush=True)
        sys.exit(1)


def after_scenario(context, scenario) -> None:
    context.sandbox.after_scenario(context, scenario)


def after_all(context) -> None:
    """Dump gnome-shell AT-SPI tree to results for node name discovery."""
    try:
        shell = context.sandbox.shell
        lines = []
        for child in shell.children[:60]:
            lines.append(f"role={child.roleName!r:30} name={child.name!r}")
            for gc in child.children[:20]:
                lines.append(f"  role={gc.roleName!r:30} name={gc.name!r}")
        import os
        os.makedirs("/tmp/results", exist_ok=True)
        with open("/tmp/results/atspi_tree.txt", "w") as f:
            f.write("\n".join(lines))
    except Exception:   # noqa: BLE001
        pass
