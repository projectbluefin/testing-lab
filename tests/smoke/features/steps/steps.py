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


@step("Dump panel children to log")
def dump_panel_children(context) -> None:
    """Print the full gnome-shell AT-SPI tree to stdout (Argo logs).
    Helps discover clock/system-status area roles and names in Bluefin GNOME.
    """
    try:
        shell = context.sandbox.shell
        print("=== GNOME-SHELL AT-SPI TREE ===", flush=True)
        def _dump(node, depth=0, max_depth=3):
            prefix = "  " * depth
            print(f"{prefix}role={node.roleName!r:20} name={node.name!r:30} showing={node.showing}", flush=True)
            if depth < max_depth:
                for c in node.children[:30]:
                    _dump(c, depth + 1, max_depth)
        _dump(shell, max_depth=3)
        print("=== END AT-SPI TREE ===", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"dump_panel_children failed: {exc}", flush=True)


@step("Dump gnome-shell AT-SPI tree to results")
def dump_atspi_tree(context) -> None:
    """Write the gnome-shell AT-SPI node tree to /tmp/results/atspi_tree.txt.

    Called from the first smoke scenario while the session is live, so the
    Wayland session and AT-SPI bus are both active.
    """
    import os
    lines = []
    shell = context.sandbox.shell
    def _write_tree(node, depth=0, max_depth=4):
        prefix = "  " * depth
        lines.append(f"{prefix}role={node.roleName!r:25} name={node.name!r} showing={node.showing}")
        if depth < max_depth:
            for gc in node.children[:40]:
                _write_tree(gc, depth + 1, max_depth)
    _write_tree(shell, max_depth=4)
    os.makedirs("/tmp/results", exist_ok=True)
    with open("/tmp/results/atspi_tree.txt", "w") as f:
        f.write("\n".join(lines))
    print(f"AT-SPI tree written: {len(lines)} lines (depth=4)", flush=True)



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


@step('Panel is present in AT-SPI tree')
def panel_is_present(context) -> None:
    """Verify the GNOME Shell top bar panel is accessible.
    Searches by role='panel' — does NOT depend on accessible-name, which
    varies across GNOME versions (may be empty, 'panel', 'top-bar', etc.).
    """
    shell = context.sandbox.shell
    # dogtail 4.16 dropped requireResult kwarg — use findChildren instead
    panels = shell.findChildren(lambda n: n.roleName == "panel")
    if not panels:
        children = [(c.roleName, c.name) for c in shell.children[:15]]
        raise AssertionError(f"Panel (role='panel') not found in gnome-shell.\nTop-level children: {children}")
    context.panel = panels[0]


@step('Clock toggle is visible in top bar')
def clock_toggle_visible(context) -> None:
    """Verify the clock toggle button is visible in the panel.
    GNOME 47+ accessible-name for the clock is the formatted time string
    (e.g. '7:14 PM' or 'Sunday 25 May, 7:14 PM'), NOT the literal 'clock'.
    We match by role and exclude 'Activities' and known system-menu names.
    """
    import re
    shell = context.sandbox.shell
    # dogtail 4.16 dropped requireResult kwarg — use findChildren instead
    panels = shell.findChildren(lambda n: n.roleName == "panel")
    assert panels, "Panel not found"
    panel = panels[0]
    # dogtail.config.searchShowingOnly = True (set in before_all) makes the
    # implicit `.showing` filter redundant here.
    toggles = panel.findChildren(lambda n: n.roleName == "toggle button")
    SYSTEM_NAMES = {"Activities", "System", "System Menu", "System menu"}
    time_re = re.compile(r'\d{1,2}:\d{2}|clock', re.IGNORECASE)
    clock = next(
        (t for t in toggles
         if t.name and t.name not in SYSTEM_NAMES and time_re.search(t.name)),
        None,
    )
    # No lax fallback: accepting "any non-system toggle" caused silent false
    # passes when the actual clock was missing — see issue #5. If the time
    # pattern is absent, fail with full toggle inventory for diagnosis.
    if clock is None:
        toggle_info = [(t.name, t.roleName) for t in toggles]
        raise AssertionError(
            f"Clock toggle (time-pattern in accessible-name) not found.\n"
            f"All panel toggles: {toggle_info}"
        )
    context.clock_toggle = clock
    print(f"Clock toggle found: name={clock.name!r}", flush=True)


@step('System menu toggle is visible in top bar')
def system_menu_toggle_visible(context) -> None:
    """Verify the system menu / quick-settings toggle is visible.
    In GNOME 47/48 the accessible-name is 'System' (not 'System menu').
    Also accepts 'System menu' for forward compatibility.
    """
    shell = context.sandbox.shell
    # dogtail 4.16 dropped requireResult kwarg — use findChildren instead
    panels = shell.findChildren(lambda n: n.roleName == "panel")
    assert panels, "Panel not found"
    panel = panels[0]
    CANDIDATE_NAMES = {"System", "System menu", "System Menu"}
    toggles = panel.findChildren(lambda n: n.roleName == "toggle button")
    system = next((t for t in toggles if t.name in CANDIDATE_NAMES), None)
    # No "first non-clock toggle" fallback: it accepted unrelated buttons
    # (e.g. notification indicator) and produced silent false passes — issue #5.
    if system is None:
        toggle_info = [(t.name, t.roleName) for t in toggles]
        raise AssertionError(
            f"System menu toggle not found (looked for {sorted(CANDIDATE_NAMES)}).\n"
            f"All panel toggles: {toggle_info}"
        )
    context.system_toggle = system
    print(f"System menu toggle found: name={system.name!r}", flush=True)


@step('Last command output stripped "is" "{expected}"')
def last_command_output_stripped_is(context, expected) -> None:
    """Compare last command output after stripping whitespace/newlines.

    grep -c always appends a trailing newline; use this step instead of
    'Last command output "is"' when the command output has trailing whitespace.
    Supports qecore versions that use last_command_output or last_run_output.
    """
    # qecore 4.16 stores under command_stdout; older versions used last_command_output
    actual = (
        getattr(context, 'command_stdout', None)
        or getattr(context, 'last_command_output', None)
        or getattr(context, 'last_run_output', None)
        or ""
    ).strip()
    assert actual == expected, (
        f"\nWanted output: '{expected}'\nActual output: '{actual}'"
    )


@step("No gnome-shell journal errors since test start")
def no_gnome_shell_journal_errors_since_start(context) -> None:
    import subprocess

    since = getattr(context, "test_start_time", None)
    cmd = ["journalctl", "--no-pager", "-p", "err..emerg", "--lines=50"]
    if since:
        cmd += ["--since", since]
    else:
        cmd += ["-b"]
    cmd += ["-g", "gnome-shell"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    count = len([line for line in result.stdout.splitlines() if "gnome-shell" in line])
    assert count == 0, (
        f"Found {count} gnome-shell journal errors since {since or 'boot'}:\n"
        f"{result.stdout[:1000]}"
    )


# ── Shell.Eval helpers (GNOME 50: uinput Super + AT-SPI toggle click broken) ──

def _shell_eval(js: str) -> str:
    """Run JS in GNOME Shell and return stdout. Requires unsafe_mode=true."""
    import subprocess
    r = subprocess.run(
        ['gdbus', 'call', '--session',
         '--dest', 'org.gnome.Shell',
         '--object-path', '/org/gnome/Shell',
         '--method', 'org.gnome.Shell.Eval',
         js],
        capture_output=True, text=True, timeout=5,
    )
    print(f"Shell.Eval({js!r}) → {r.stdout.strip()}", flush=True)
    return r.stdout


def _shell_eval_inner(js: str) -> str:
    """Return the inner JS-result string from Shell.Eval's (bs) GVariant tuple.

    gdbus output format: ``(true, 'value')`` — the outer bool is the DBus
    call-success flag, NOT the JS result.  ``'true' in out.lower()`` is a
    false-positive trap because the wrapper always contains 'true'.
    This helper extracts only the inner quoted value.
    """
    import re
    out = _shell_eval(js)
    m = re.search(r"\((?:true|false),\s*'(.*)'\)", out.strip())
    return m.group(1) if m else ""


@step('Open Activities overview via Shell.Eval')
def open_overview_eval(context) -> None:
    _shell_eval('Main.overview.show()')
    sleep(1)


@step('Close Activities overview via Shell.Eval')
def close_overview_eval(context) -> None:
    _shell_eval('Main.overview.hide()')
    sleep(0.5)


@step('Open Quick Settings via Shell.Eval')
def open_quick_settings_eval(context) -> None:
    # menu.toggle() is stable across GNOME 49/50
    _shell_eval('Main.panel.statusArea.quickSettings.menu.toggle()')
    sleep(0.5)


@step('Quick Settings panel is open via Shell.Eval')
def quick_settings_open_eval(context) -> None:
    inner = _shell_eval_inner('Main.panel.statusArea.quickSettings.menu.isOpen.toString()')
    assert inner == 'true', f"Quick Settings not open — Shell.Eval inner: {inner!r}"


@step('Quick Settings panel is closed via Shell.Eval')
def quick_settings_closed_eval(context) -> None:
    for _ in range(8):
        inner = _shell_eval_inner('Main.panel.statusArea.quickSettings.menu.isOpen.toString()')
        if inner == 'false':
            return
        sleep(0.5)
    raise AssertionError(f"Quick Settings still open after 4s — Shell.Eval inner: {inner!r}")


@step('Open date menu via Shell.Eval')
def open_date_menu_eval(context) -> None:
    # menu.toggle() is stable across GNOME 49/50; _toggleMenu() is GNOME 50+ only
    _shell_eval('Main.panel.statusArea.dateMenu.menu.toggle()')
    sleep(0.5)


@step('Close Quick Settings via Shell.Eval')
def close_quick_settings_eval(context) -> None:
    # close(0) = BoxPointer.PopupAnimation.NONE — explicit close, not toggle
    _shell_eval('Main.panel.statusArea.quickSettings.menu.close(0)')
    sleep(0.5)


@step('Close date menu via Shell.Eval')
def close_date_menu_eval(context) -> None:
    _shell_eval('Main.panel.statusArea.dateMenu.menu.close(0)')
    sleep(0.5)


@step('Date menu panel is open via Shell.Eval')
def date_menu_open_eval(context) -> None:
    inner = _shell_eval_inner('Main.panel.statusArea.dateMenu.menu.isOpen.toString()')
    assert inner == 'true', f"Date menu not open — Shell.Eval inner: {inner!r}"


@step('Date menu panel is closed via Shell.Eval')
def date_menu_closed_eval(context) -> None:
    for _ in range(8):
        inner = _shell_eval_inner('Main.panel.statusArea.dateMenu.menu.isOpen.toString()')
        if inner == 'false':
            return
        sleep(0.5)
    raise AssertionError(f"Date menu still open after 4s — Shell.Eval inner: {inner!r}")


@step('Set overview search text to "{text}" via Shell.Eval')
def set_overview_search_eval(context, text) -> None:
    """Populate overview search bar via GNOME Shell JS.
    uinput typing is broken on these VMs — use Shell.Eval instead.
    set_text() fires St.Entry::changed which the SearchController is connected to;
    _onSearchChanged() is a private method removed in GNOME 50 and must not be called.
    """
    _shell_eval(f'Main.overview.searchEntry.set_text("{text}")')
    sleep(0.5)


@step("Overview is open")
def overview_is_open(context) -> None:
    shell = tree.root.application("gnome-shell")
    for _ in range(8):
        # GNOME 49/50: name may be 'Overview' or 'overview' — match case-insensitively
        results = shell.findChildren(lambda n: n.name.lower() == "overview" and n.showing)
        if results:
            return
        sleep(0.5)
    raise AssertionError("Activities overview did not open after 4s")


@step("Overview is closed")
def overview_is_closed(context) -> None:
    shell = tree.root.application("gnome-shell")
    for _ in range(8):
        results = shell.findChildren(lambda n: n.name.lower() == "overview" and n.showing)
        if not results:
            return
        sleep(0.5)
    raise AssertionError("Activities overview is still showing after 4s")


@step('Overview search bar contains "{text}"')
def overview_search_bar_contains(context, text) -> None:
    shell = tree.root.application("gnome-shell")
    # dogtail 4.16 dropped requireResult kwarg
    entries = shell.findChildren(lambda n: n.roleName == "text" and n.showing)
    assert entries, f"Search bar text entry not found"
    entry = entries[0]
    assert text in entry.text, f"Search bar text '{entry.text}' does not contain '{text}'"
