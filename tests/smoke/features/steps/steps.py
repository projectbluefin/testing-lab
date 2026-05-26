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
from dogtail.rawinput import pressKey
from qecore.common_steps import *  # noqa: F401,F403


_APP_ID_ALIASES = {
    "org.gnome.Nautilus": ("org.gnome.nautilus", "nautilus", "files"),
    "org.gnome.Settings": ("org.gnome.settings", "gnome-control-center", "settings"),
}


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


# ── App launch helpers (#65, #87, #88) ───────────────────────────────────


def _app_aliases(app_id: str) -> tuple[str, ...]:
    aliases = {app_id.lower(), app_id.split(".")[-1].lower()}
    aliases.update(_APP_ID_ALIASES.get(app_id, ()))
    return tuple(sorted(aliases))


def _wait_for_application_node(app_id: str, attempts: int = 10, delay: float = 1.0):
    aliases = _app_aliases(app_id)
    last_seen = []
    for _ in range(attempts):
        apps = tree.root.findChildren(
            lambda n: n.roleName == "application"
            and any(alias in (n.name or "").lower() for alias in aliases)
        )
        if apps:
            return apps[0]
        last_seen = [(n.name, n.roleName) for n in tree.root.children[:15]]
        sleep(delay)
    raise AssertionError(
        f"Application {app_id!r} not found in AT-SPI tree. Top-level nodes: {last_seen}"
    )


def _click_node_or_ancestor(node) -> None:
    current = node
    for _ in range(5):
        if current is None:
            break
        if hasattr(current, "click"):
            try:
                current.click()
                return
            except Exception:  # noqa: BLE001
                pass
        current = getattr(current, "parent", None)
    raise AssertionError(f"Unable to click node or ancestor for {getattr(node, 'name', None)!r}")


@step("Launch first overview search result via Shell.Eval")
def launch_first_search_result(context) -> None:
    """Launch the selected overview result with the focused Return keypress."""
    pressKey("Return")
    sleep(2)


@step('Application "{app_id}" is open in AT-SPI')
def app_is_open_in_atspi(context, app_id) -> None:
    context.current_application = _wait_for_application_node(app_id)


@step('Close application "{app_id}" via Shell.Eval')
def close_app_via_shell_eval(context, app_id) -> None:
    import json

    aliases = json.dumps(list(_app_aliases(app_id)))
    _shell_eval(
        "const aliases = %s;"
        "for (const actor of global.get_window_actors()) {"
        "  const win = actor.get_meta_window();"
        "  const fields = ["
        "    win.get_wm_class(),"
        "    win.get_title(),"
        "    typeof win.get_gtk_application_id === 'function' ? win.get_gtk_application_id() : ''"
        "  ].filter(Boolean).map(value => value.toLowerCase());"
        "  if (aliases.some(alias => fields.some(value => value.includes(alias)))) {"
        "    win.delete(global.get_current_time());"
        "  }"
        "}"
        % aliases
    )
    for _ in range(8):
        apps = tree.root.findChildren(
            lambda n: n.roleName == "application"
            and any(alias in (n.name or "").lower() for alias in _app_aliases(app_id))
        )
        if not apps:
            if getattr(context, "current_application", None) is not None:
                context.current_application = None
            return
        sleep(0.5)
    raise AssertionError(f"Application {app_id!r} is still open after close request")


@step('Files sidebar contains "{item}"')
def files_sidebar_contains(context, item) -> None:
    app = getattr(context, "current_application", None) or _wait_for_application_node("org.gnome.Nautilus")
    matches = app.findChildren(
        lambda n: (n.name or "").strip() == item
        and n.roleName in {"label", "push button", "list item", "table cell", "icon"}
    )
    assert matches, f"Files sidebar item {item!r} not found"


@step('Open Settings panel "{panel_name}"')
def open_settings_panel(context, panel_name) -> None:
    app = getattr(context, "current_application", None) or _wait_for_application_node("org.gnome.Settings")
    candidates = app.findChildren(
        lambda n: (n.name or "").strip() == panel_name
        and n.roleName in {"label", "push button", "list item", "table cell", "row header"}
    )
    assert candidates, f"Settings panel {panel_name!r} not found"
    _click_node_or_ancestor(candidates[0])
    sleep(1)


@step('Settings panel "{panel_name}" shows "{text}"')
def settings_panel_shows_text(context, panel_name, text) -> None:
    app = getattr(context, "current_application", None) or _wait_for_application_node("org.gnome.Settings")
    matches = app.findChildren(
        lambda n: text in (n.name or "")
        and n.roleName in {"label", "heading", "page tab", "push button", "text", "static"}
    )
    assert matches, f"Settings panel {panel_name!r} does not show {text!r}"


# ── Quick Settings state change (#90) ────────────────────────────────────


def _desktop_color_scheme() -> str:
    import subprocess

    result = subprocess.run(
        ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "gsettings get failed")
    return result.stdout.strip().strip("'")


@step("Toggle dark style via Shell.Eval")
def toggle_dark_style(context) -> None:
    current = _desktop_color_scheme()
    if not hasattr(context, "_color_scheme_initial"):
        context._color_scheme_initial = current
    context._color_scheme_previous = current
    new_value = _shell_eval_inner(
        "const Gio = imports.gi.Gio;"
        "let settings = new Gio.Settings({ schema_id: 'org.gnome.desktop.interface' });"
        "let next = settings.get_string('color-scheme') === 'prefer-dark' ? 'default' : 'prefer-dark';"
        "settings.set_string('color-scheme', next);"
        "settings.get_string('color-scheme');"
    )
    sleep(1)
    context._color_scheme_current = _desktop_color_scheme()
    assert context._color_scheme_current == new_value, (
        f"Expected color-scheme {new_value!r}, got {context._color_scheme_current!r}"
    )


@step("Dark style setting changed")
def dark_style_setting_changed(context) -> None:
    previous = getattr(context, "_color_scheme_previous", None)
    current = getattr(context, "_color_scheme_current", None)
    assert previous is not None, "dark style toggle was not called"
    assert current is not None, "dark style state was not recorded"
    assert current != previous, f"Dark style did not change: still {current!r}"
