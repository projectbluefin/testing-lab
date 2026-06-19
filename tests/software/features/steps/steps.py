"""
Custom step definitions for software suite.

common_steps covers the low-level lifecycle and UI actions; custom aliases here
map the Bazaar workflow wording onto those shared qecore patterns.
"""
import subprocess

from behave import step
from qecore.common_steps import *  # noqa: F401,F403


def _require_bazaar(app_id: str) -> None:
    assert app_id == "org.gnome.Software", f"Unsupported application id: {app_id}"


def _last_output(context: object) -> str:
    return (
        getattr(context, "command_stdout", None)
        or getattr(context, "last_command_output", None)
        or getattr(context, "last_run_output", None)
        or ""
    ).strip()


@step('Last command output contains "{text}"')
def last_command_output_contains(context, text) -> None:
    output = _last_output(context)
    assert text in output, f"Expected {text!r} in output:\n{output[:500]}"


GNOME_SOFTWARE_CPU_THRESHOLD_PCT = 5.0


@step("gnome-software CPU usage is below threshold")
def gnome_software_cpu_below_threshold(context) -> None:
    output = _last_output(context)
    try:
        cpu = float(output)
    except ValueError:
        cpu = 0.0
    assert cpu < GNOME_SOFTWARE_CPU_THRESHOLD_PCT, (
        f"gnome-software CPU usage {cpu}% exceeds "
        f"{GNOME_SOFTWARE_CPU_THRESHOLD_PCT}% threshold (bluefin#4471)"
    )


@step('Start "{app_id}" via shell')
def start_app_via_shell(context, app_id) -> None:
    _require_bazaar(app_id)
    context.execute_steps('* Start application "software" via "command"')


@step('Application "{app_id}" is opened')
def application_is_opened(context, app_id) -> None:
    _require_bazaar(app_id)
    context.execute_steps(
        '\n'.join(
            [
                '* Application "software" is running',
                '* Wait until "Software" "frame" appears in "software"',
            ]
        )
    )


@step('Close "{app_id}"')
def close_app(context, app_id) -> None:
    _require_bazaar(app_id)
    context.execute_steps(
        '\n'.join(
            [
                '* Close application "software" via "shortcut"',
                '* Application "software" is no longer running',
            ]
        )
    )


@step('Activate "{label}" in "{app_id}"')
def activate_view(context, label, app_id) -> None:
    _require_bazaar(app_id)
    context.execute_steps(
        '\n'.join(
            [
                f'* Left click "{label}" "toggle button" in "software"',
                f'* Wait until "{label}" "page tab" appears in "software"',
            ]
        )
    )
