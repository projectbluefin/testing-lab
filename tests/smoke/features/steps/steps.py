"""
Custom step definitions for GNOME Shell smoke tests.

common_steps provides: Application is running, Item found/not found,
Left/Right click, Key combo, Press key, Type text, Run and save command output,
Last command output, Wait N seconds.

Custom steps here cover:
- GNOME Shell accessibility check (retrying via context.sandbox.shell)
- Activities overview state, search bar content.

NOTE: We do NOT redefine 'Application "{name}" is running' — behave raises
AmbiguousStep when a literal step conflicts with an existing wildcard step.
Instead we use a distinct step name: 'GNOME Shell is accessible via AT-SPI'.

Step patterns sourced from: modehnal/GNOMETerminalAutomation steps.py
dogtail API: root.application(), Node.findChild(), Node.child(roleName=)
"""
from time import sleep

from behave import step
from dogtail import tree
from qecore.common_steps import *  # noqa: F401,F403


@step("Dump gnome-shell AT-SPI tree to results")
def dump_atspi_tree(context) -> None:
    """Write the gnome-shell AT-SPI node tree to /tmp/results/atspi_tree.txt.

    Called from the first smoke scenario while the session is live, so the
    Wayland session and AT-SPI bus are both active.
    """
    import os
    lines = []
    shell = context.sandbox.shell
    for child in shell.children[:80]:
        lines.append(f"role={child.roleName!r:30} name={child.name!r}")
        for gc in child.children[:30]:
            lines.append(f"  role={gc.roleName!r:30} name={gc.name!r}")
    os.makedirs("/tmp/results", exist_ok=True)
    with open("/tmp/results/atspi_tree.txt", "w") as f:
        f.write("\n".join(lines))
    print(f"AT-SPI tree written: {len(lines)} lines", flush=True)



@step("GNOME Shell is accessible via AT-SPI")
def gnome_shell_is_accessible(context) -> None:
    """Retrying gnome-shell AT-SPI check via qecore's built-in shell getter.

    The common 'Application "{name}" is running' step calls is_open() which
    does not work for gnome-shell (compositor, not a regular window).
    context.sandbox.shell uses qecore's own retry path and is the recommended
    way to access gnome-shell per qecore docs.
    """
    last_exc = None
    for attempt in range(6):   # up to 30 s total
        try:
            shell = context.sandbox.shell
            assert shell is not None, "gnome-shell not registered in AT-SPI tree"
            return
        except Exception as exc:   # noqa: BLE001
            last_exc = exc
            sleep(5)
    raise AssertionError(
        f"gnome-shell not accessible via AT-SPI after 30 s: {last_exc}"
    )


@step('Last command output stripped "is" "{expected}"')
def last_command_output_stripped_is(context, expected) -> None:
    """Compare last command output after stripping whitespace/newlines.

    grep -c always appends a trailing newline; use this step instead of
    'Last command output "is"' when the command output has trailing whitespace.
    """
    actual = (context.last_command_output or "").strip()
    assert actual == expected, (
        f"\nWanted output: '{expected}'\nActual output: '{actual}'"
    )


@step("Overview is open")
def overview_is_open(context) -> None:
    # AT-SPI: gnome-shell exposes an "overview" named child when open
    shell = tree.root.application("gnome-shell")
    overview = shell.findChild(
        lambda n: n.name == "overview" and n.showing,
        requireResult=True,
    )
    assert overview is not None, "Activities overview did not open"


@step("Overview is closed")
def overview_is_closed(context) -> None:
    shell = tree.root.application("gnome-shell")
    results = shell.findChildren(
        lambda n: n.name == "overview" and n.showing,
    )
    assert len(results) == 0, "Activities overview is still showing"


@step('Overview search bar contains "{text}"')
def overview_search_bar_contains(context, text) -> None:
    shell = tree.root.application("gnome-shell")
    # search entry lives inside the overview
    entry = shell.findChild(
        lambda n: n.roleName == "text" and n.showing,
        requireResult=True,
    )
    assert text in entry.text, f"Search bar text '{entry.text}' does not contain '{text}'"
