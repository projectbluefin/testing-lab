"""
System suite environment — minimal behave setup for non-GUI OS contract checks.
Steps run shell commands directly in the guest via subprocess.
"""
import subprocess
import sys
import traceback


def before_scenario(context, scenario):
    context.command_stdout = ""
    context.last_command_output = ""


def after_step(context, step):
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
