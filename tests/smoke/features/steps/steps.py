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
import json
import subprocess
from time import sleep

from behave import step
from dogtail import tree
from dogtail.rawinput import pressKey
from qecore.common_steps import *  # noqa: F401,F403


_APP_ID_ALIASES = {
    "org.gnome.Nautilus": ("org.gnome.nautilus", "nautilus", "files"),
    "org.gnome.Settings": ("org.gnome.settings", "gnome-control-center", "settings"),
}


def _enabled_extensions(context) -> set[str]:
    enabled = getattr(context, "_enabled_extensions", None)
    if enabled is not None:
        return enabled

    result = subprocess.run(
        ["gnome-extensions", "list", "--enabled"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "gnome-extensions list failed")

    enabled = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    context._enabled_extensions = enabled
    return enabled


def _shell_eval_json(js: str):
    inner = _shell_eval_inner(js)
    try:
        return json.loads(inner)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Shell.Eval did not return JSON: {inner!r}") from exc


def _dbus_name_has_owner(name: str) -> bool:
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.NameHasOwner",
            name,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or f"NameHasOwner failed for {name}")
    return "(true,)" in result.stdout


def _node_text(node) -> str:
    parts = []
    for attr in ("name", "text", "description"):
        value = getattr(node, attr, None)
        if value:
            parts.append(str(value))
    return " ".join(parts)


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


def _find_panels(shell):
    """Find gnome-shell panel nodes by role."""
    return shell.findChildren(lambda n: n.roleName == "panel")


@step('Panel is present in AT-SPI tree')
def panel_is_present(context) -> None:
    """Verify the GNOME Shell top bar panel is accessible.
    Searches by role='panel' — does NOT depend on accessible-name, which
    varies across GNOME versions (may be empty, 'panel', 'top-bar', etc.).
    """
    shell = context.sandbox.shell
    panels = _find_panels(shell)
    if not panels:
        children = [(c.roleName, c.name) for c in shell.children[:15]]
        raise AssertionError(f"Panel (role='panel') not found in gnome-shell.\nTop-level children: {children}")
    context.panel = panels[0]


@step('Activities toggle is visible in top bar')
def activities_toggle_visible(context) -> None:
    """Verify the Activities toggle button exists in the top bar."""
    shell = context.sandbox.shell
    panels = _find_panels(shell)
    assert panels, "Panel (role='panel') not found in gnome-shell"
    toggles = panels[0].findChildren(lambda n: n.roleName == "toggle button")
    activities = next((t for t in toggles if t.name == "Activities"), None)
    if activities is None:
        toggle_info = [(t.name, t.roleName) for t in toggles]
        raise AssertionError(
            f"Activities toggle button not found in panel.\nAll toggles: {toggle_info}"
        )
    print(f"Activities toggle found: name={activities.name!r}", flush=True)


@step('Clock toggle is visible in top bar')
def clock_toggle_visible(context) -> None:
    """Verify the clock / dateMenu is present in GNOME Shell.

    On GNOME Shell 50 the clock button reports an empty accessible-name in
    AT-SPI, so a time-pattern regex cannot match it.  Use Shell.Eval to check
    Main.panel.statusArea.dateMenu directly (authoritative on all versions).
    """
    inner = _shell_eval_inner(
        "Main.panel.statusArea.dateMenu !== null && "
        "Main.panel.statusArea.dateMenu !== undefined ? 'present' : 'absent'"
    )
    if inner != "present":
        raise AssertionError(
            "dateMenu not found via Shell.Eval "
            f"(Main.panel.statusArea.dateMenu returned {inner!r})"
        )
    print("Clock/dateMenu present via Shell.Eval", flush=True)
    # Also log AT-SPI toggle inventory for diagnosis without failing on it.
    try:
        panels = _find_panels(context.sandbox.shell)
        if panels:
            toggles = panels[0].findChildren(lambda n: n.roleName == "toggle button")
            print(f"Panel toggle inventory: {[(t.name, t.roleName) for t in toggles]}", flush=True)
    except Exception:  # noqa: BLE001
        pass


@step('System menu toggle is visible in top bar')
def system_menu_toggle_visible(context) -> None:
    """Verify the system menu / quick-settings toggle is visible.

    On GNOME Shell 50 the system-status area accessible-name may be empty in
    AT-SPI headless mode.  Use Shell.Eval as primary check; AT-SPI name match
    as a secondary diagnostic.
    """
    inner = _shell_eval_inner(
        "Main.panel.statusArea.quickSettings !== null && "
        "Main.panel.statusArea.quickSettings !== undefined ? 'present' : 'absent'"
    )
    if inner == "present":
        print("System menu (quickSettings) present via Shell.Eval", flush=True)
        return

    # Fallback: AT-SPI name match (GNOME < 50 or managed environments).
    shell = context.sandbox.shell
    panels = _find_panels(shell)
    assert panels, "Panel not found"
    panel = panels[0]
    CANDIDATE_NAMES = {"System", "System menu", "System Menu"}
    toggles = panel.findChildren(lambda n: n.roleName == "toggle button")
    system = next((t for t in toggles if t.name in CANDIDATE_NAMES), None)
    if system is None:
        toggle_info = [(t.name, t.roleName) for t in toggles]
        raise AssertionError(
            f"System menu toggle not found (Shell.Eval: {inner!r}; "
            f"looked for {sorted(CANDIDATE_NAMES)}).\n"
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


@step('Last command output stripped contains "{expected}"')
def last_command_output_stripped_contains(context, expected) -> None:
    actual = (
        getattr(context, 'command_stdout', None)
        or getattr(context, 'last_command_output', None)
        or getattr(context, 'last_run_output', None)
        or ""
    ).strip()
    assert expected in actual, f"Expected {expected!r} in output: {actual!r}"


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
    call-success flag, NOT the JS result.

    GNOME Shell JSON-encodes string results.  When the JS evaluates to a string
    (including JSON.stringify output), Shell.Eval wraps it in an additional JSON
    layer so the gdbus variant contains ``'"{\\"key\\":val}"'``.  We must use
    ``json.loads`` to properly unescape, not a simple slice.
    """
    import json as _json
    import re
    out = _shell_eval(js)
    m = re.search(r"\((?:true|false),\s*'(.*)'\)", out.strip())
    if not m:
        return ""
    inner = m.group(1)
    if inner.startswith('"') and inner.endswith('"'):
        # GVariant single-quoted string format escapes '\' as '\\', so
        # JSON.stringify output arrives double-escaped: first undo the
        # GVariant layer (\\→\), then JSON-decode the shell-level encoding.
        try:
            return _json.loads(inner.replace('\\\\', '\\'))
        except _json.JSONDecodeError:
            return inner[1:-1]          # fallback: dumb slice
    return inner


@step('Open Activities overview via Shell.Eval')
def open_overview_eval(context) -> None:
    _shell_eval('Main.overview.show()')
    sleep(2)  # GNOME Shell 50 may need >1 s to expose the overview node



@step('Close Activities overview via Shell.Eval')
def close_overview_eval(context) -> None:
    _shell_eval('Main.overview.hide()')
    sleep(0.5)


@step('Open Quick Settings via Shell.Eval')
def open_quick_settings_eval(context) -> None:
    # menu.toggle() is stable across GNOME 49/50
    _shell_eval('Main.panel.statusArea.quickSettings.menu.toggle()')
    sleep(1)  # GNOME Shell 50 may need >0.5 s for the menu to open


@step('Quick Settings panel is open via Shell.Eval')
def quick_settings_open_eval(context) -> None:
    for _ in range(6):
        inner = _shell_eval_inner('Main.panel.statusArea.quickSettings.menu.isOpen.toString()')
        if inner == 'true':
            return
        sleep(0.5)
    raise AssertionError(f"Quick Settings not open after 3s — Shell.Eval inner: {inner!r}")


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
    sleep(1)  # GNOME Shell 50 may need >0.5 s for the menu to open


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
    # Primary: Shell.Eval — authoritative and unaffected by AT-SPI showing=False
    for _ in range(8):
        visible = _shell_eval_inner('Main.overview.visible.toString()')
        if visible == 'true':
            return
        # Secondary: AT-SPI node with showing filter relaxed
        shell = tree.root.application("gnome-shell")
        results = shell.findChildren(lambda n: n.name.lower() == "overview")
        if results:
            return
        sleep(0.5)
    raise AssertionError("Activities overview did not open after 4s")


@step("Overview is closed")
def overview_is_closed(context) -> None:
    # Primary: Shell.Eval — authoritative and unaffected by AT-SPI showing=False
    for _ in range(8):
        visible = _shell_eval_inner('Main.overview.visible.toString()')
        if visible == 'false':
            return
        sleep(0.5)
    raise AssertionError("Activities overview is still showing after 4s")


@step('Overview search bar contains "{text}"')
def overview_search_bar_contains(context, text) -> None:
    shell = tree.root.application("gnome-shell")
    entries = shell.findChildren(lambda n: n.roleName == "text")
    # Filter to entries that have text content matching the search query
    text_entries = [e for e in entries if e.text]
    assert text_entries, "Search bar text entry not found"
    texts = [e.text for e in text_entries]
    found = any(text.lower() in t.lower() for t in texts)
    assert found, f"'{text}' not found in any search bar entry. Entry texts: {texts}"


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
        last_seen = [(n.name, n.roleName) for n in tree.root.children[:15]]
        if apps:
            return apps[0]
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
    """Activate the first overview search result via Shell.Eval JS.

    Tries SearchController internal APIs first (version-specific), then falls
    back to Shell.AppSystem name-match which works across all GNOME Shell versions.
    """
    result = _shell_eval_inner(
        "(() => {"
        # GNOME 44–46 style: sc.activateDefault() or sc._searchResults.activateDefault()
        "const sc = Main.overview._overview"
        "  && Main.overview._overview.controls"
        "  && Main.overview._overview.controls._searchController;"
        "if (sc) {"
        "  if (typeof sc.activateDefault === 'function') { sc.activateDefault(); return 'sc-activated'; }"
        "  const sr = sc._searchResults;"
        "  if (sr && typeof sr.activateDefault === 'function') { sr.activateDefault(); return 'sr-activated'; }"
        "  if (sr && sr._defaultResult && typeof sr._defaultResult.activate === 'function') {"
        "    sr._defaultResult.activate(); return 'dr-activated';"
        "  }"
        "}"
        # Universal fallback: match installed app by search-entry text via AppSystem
        "const text = (Main.overview.searchEntry.get_text() || '').toLowerCase();"
        "if (!text) return 'no-search-text';"
        "const apps = Shell.AppSystem.get_default().get_installed();"
        "const match = apps.find(app => (app.get_name() || '').toLowerCase().includes(text));"
        "if (!match) return 'appsystem-no-match:' + text;"
        "Main.overview.hide();"
        "match.activate();"
        "return 'appsystem-launched:' + match.get_id();"
        "})()"
    )
    ok_prefixes = ('sc-activated', 'sr-activated', 'dr-activated', 'appsystem-launched:')
    assert any(result.startswith(p) for p in ok_prefixes), (
        f"Could not launch first overview search result: {result!r}"
    )
    sleep(3)  # give Flatpak app time to start and register in AT-SPI


@step('Application "{app_id}" is open in AT-SPI')
def app_is_open_in_atspi(context, app_id) -> None:
    # Firefox (Flatpak) can take 20-30 s; other Flatpak apps (Nautilus, Settings) need ~15-20 s
    attempts = 30 if "firefox" in app_id.lower() else 20
    context.current_application = _wait_for_application_node(app_id, attempts=attempts)


@step('Close application "{app_id}" via Shell.Eval')
def close_app_via_shell_eval(context, app_id) -> None:
    import json

    aliases = json.dumps(list(_app_aliases(app_id)))
    # Close windows AND quit the application process so the next test scenario
    # gets a clean cold-start launch (avoids stale AT-SPI registration on re-activate).
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
        "Shell.AppSystem.get_default().get_running().forEach(app => {"
        "  const id = (app.get_id() || '').toLowerCase();"
        "  const name = (app.get_name() || '').toLowerCase();"
        "  if (aliases.some(alias => id.includes(alias) || name.includes(alias))) {"
        "    app.request_quit();"
        "  }"
        "});"
        % aliases
    )
    # With searchShowingOnly=False the application node persists after all windows
    # are destroyed (the process keeps running).  Check for open *windows* (frame
    # nodes) rather than the application node itself.
    for _ in range(20):
        apps = tree.root.findChildren(
            lambda n: n.roleName == "application"
            and any(alias in (n.name or "").lower() for alias in _app_aliases(app_id))
        )
        has_windows = any(
            app.findChildren(lambda n: n.roleName == "frame")
            for app in apps
        )
        if not has_windows:
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
    # The sidebar labels (Network, Appearance, System…) are always in the AT-SPI
    # tree as ('label', 'PanelName').  Click the first matching one and let
    # _click_node_or_ancestor traverse to the clickable parent row.
    sidebar_entries = app.findChildren(
        lambda n: (n.name or "").strip() == panel_name and n.roleName == "label"
    )
    if sidebar_entries:
        _click_node_or_ancestor(sidebar_entries[0])
        sleep(1.5)
        return
    # Fallback for sub-panels not in the top-level sidebar (e.g. "About" under System).
    # Use subprocess activation — works on cold launch because Settings starts on About.
    panel_id = panel_name.lower().replace(" ", "-")
    _shell_eval(
        "const p = new Gio.Subprocess({"
        f"  argv: ['gnome-control-center', '{panel_id}'],"
        "  flags: Gio.SubprocessFlags.NONE"
        "});"
        "p.init(null);"
    )
    sleep(2)


@step('Settings panel "{panel_name}" shows "{text}"')
def settings_panel_shows_text(context, panel_name, text) -> None:
    app = getattr(context, "current_application", None) or _wait_for_application_node("org.gnome.Settings")
    matches = app.findChildren(
        lambda n: text in (n.name or "")
        and n.roleName in {"label", "heading", "page tab", "push button", "text", "static"}
    )
    if not matches:
        # Dump visible node names to aid diagnosis of panel content changes.
        all_nodes = app.findChildren(
            lambda n: n.roleName in {"label", "heading", "push button", "text", "static", "list item"}
            and (n.name or "").strip()
        )
        node_dump = [(n.roleName, n.name) for n in all_nodes[:30]]
        raise AssertionError(
            f"Settings panel {panel_name!r} does not show {text!r}. "
            f"Available nodes (role, name): {node_dump}"
        )


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


# ── Extension behavior + notifications (#91, #68) ──────────────────────────


@step('Extension "{uuid}" is enabled')
def extension_is_enabled(context, uuid) -> None:
    enabled = _enabled_extensions(context)
    assert uuid in enabled, f"Extension {uuid!r} not enabled. Enabled extensions: {sorted(enabled)}"


@step("AT-SPI root contains a desktop canvas or icon surface")
def atspi_root_contains_desktop_surface(context) -> None:
    needles = ("desktop icons", "ding", "desktop", "trash", "home")
    role_names = {"application", "desktop frame", "canvas", "icon", "layered pane", "frame", "list"}

    for _ in range(6):
        matches = tree.root.findChildren(
            lambda n: (n.roleName or "").lower() in role_names
            and any(needle in _node_text(n).lower() for needle in needles)
        )
        if matches:
            return
        sleep(1)

    top_level = [(child.roleName, child.name) for child in tree.root.children[:20]]
    raise AssertionError(
        "Desktop Icons NG surface not found in AT-SPI tree. "
        f"Top-level nodes: {top_level}"
    )


@step("Dash to Dock exposes a visible dock actor")
def dash_to_dock_exposes_visible_dock(context) -> None:
    data = _shell_eval_json(
        "JSON.stringify((() => {"
        "const ext = Main.extensionManager.lookup('dash-to-dock@micxgx.gmail.com');"
        "const manager = ext && ext.stateObj ? ext.stateObj.dockManager : null;"
        "const docks = manager && manager._allDocks ? manager._allDocks : [];"
        "const dock = docks.find(candidate => candidate && (candidate.visible || candidate.mapped)) || docks[0] || null;"
        "return {"
        "dockCount: docks.length,"
        "visible: !!(dock && (dock.visible || dock.mapped)),"
        "hasDash: !!(dock && dock.dash),"
        "hasShowApps: !!(dock && dock.dash && dock.dash.showAppsButton),"
        "name: dock && dock.name ? dock.name : null"
        "};"
        "})())"
    )
    assert data["dockCount"] > 0, f"Dash to Dock did not register any dock actors: {data}"
    assert data["visible"], f"Dash to Dock dock actor is not visible: {data}"
    assert data["hasDash"] and data["hasShowApps"], f"Dash to Dock dash surface missing expected children: {data}"


@step("Overview blur effect is active via Shell.Eval")
def overview_blur_effect_is_active(context) -> None:
    data = _shell_eval_json(
        "JSON.stringify((() => {"
        "const matches = [];"
        "const visit = (actor, depth = 0) => {"
        "  if (!actor || depth > 4) return;"
        "  let effects = [];"
        "  if (typeof actor.get_effects === 'function') {"
        "    effects = actor.get_effects().map(effect => {"
        "      try {"
        "        return effect.constructor && effect.constructor.name ? effect.constructor.name : String(effect);"
        "      } catch (error) {"
        "        return String(effect);"
        "      }"
        "    });"
        "  }"
        "  if (effects.some(name => String(name).toLowerCase().includes('blur'))) {"
        "    matches.push({name: actor.name || null, effects});"
        "  }"
        "  const children = typeof actor.get_children === 'function' ? actor.get_children() : [];"
        "  for (const child of children) visit(child, depth + 1);"
        "};"
        "visit(Main.layoutManager.overviewGroup || (Main.overview && Main.overview._overview) || global.stage);"
        "return {count: matches.length, matches: matches.slice(0, 8)};"
        "})())"
    )
    assert data["count"] > 0, f"No overview blur effects detected: {data}"


@step("App Indicators registers a panel tray host")
def app_indicators_registers_panel_tray_host(context) -> None:
    data = _shell_eval_json(
        "JSON.stringify((() => {"
        "const actors = Main.panel._rightBox.get_children().map(actor => ({"
        "  name: actor.name || '',"
        "  style: actor.style_class || '',"
        "  visible: !!actor.visible,"
        "  hasIndicatorChild: typeof actor.get_children === 'function' && actor.get_children().some(child => !!(child && (child._indicator || (child._delegate && child._delegate._indicator))))"
        "}));"
        "const indicatorActors = actors.filter(actor => actor.visible && (actor.hasIndicatorChild || actor.name.toLowerCase().includes('indicator') || actor.style.toLowerCase().includes('indicator')));"
        "const statusAreaKeys = Object.keys(Main.panel.statusArea).filter(key => ['indicator', 'statusnotifier', 'tray'].some(needle => key.toLowerCase().includes(needle)));"
        "return {indicatorActors, statusAreaKeys};"
        "})())"
    )
    watcher_owner = _dbus_name_has_owner("org.kde.StatusNotifierWatcher")
    assert watcher_owner, "App Indicators DBus watcher is not owned"
    assert data["indicatorActors"] or data["statusAreaKeys"], f"App Indicators tray host not exposed in panel: {data}"


@step("Windows Navigator shows workspace navigation hints via Shell.Eval")
def windows_navigator_shows_workspace_hints(context) -> None:
    data = _shell_eval_json(
        "JSON.stringify((() => {"
        "const overview = Main.overview && Main.overview._overview ? Main.overview._overview : Main.overview;"
        "const controls = overview && overview._controls ? overview._controls : (overview && overview.controls ? overview.controls : null);"
        "const display = controls && controls._workspacesDisplay ? controls._workspacesDisplay : null;"
        "const views = display && display._workspacesViews ? display._workspacesViews : [];"
        "const view = views.length > 0 ? views[0] : null;"
        "const workspace = view && view._workspaces && view._workspaces.length > 0 ? view._workspaces[0] : null;"
        "if (workspace && typeof workspace.showTooltip === 'function') workspace.showTooltip();"
        "const result = {"
        "  hasView: !!view,"
        "  pickWindowPatched: typeof (view && view._pickWindow) === 'boolean',"
        "  pickWorkspacePatched: typeof (view && view._pickWorkspace) === 'boolean',"
        "  hintVisible: !!(workspace && workspace._tip && workspace._tip.visible),"
        "  hintText: workspace && workspace._tip ? workspace._tip.text : null"
        "};"
        "if (workspace && typeof workspace.hideTooltip === 'function') workspace.hideTooltip();"
        "return result;"
        "})())"
    )
    assert data["hasView"], f"Overview workspaces view not found: {data}"
    assert data["pickWindowPatched"] and data["pickWorkspacePatched"], f"Windows Navigator did not patch overview state: {data}"
    assert data["hintVisible"], f"Windows Navigator workspace hint is not visible: {data}"
    assert data["hintText"] == "1", f"Unexpected Windows Navigator workspace hint text: {data}"


@step('Send desktop notification "{title}" "{body}"')
def send_desktop_notification(context, title, body) -> None:
    result = subprocess.run(
        ["notify-send", "--app-name=bluefin-test", "--icon=dialog-information", title, body],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "notify-send failed")
    context.last_notification = {"title": title, "body": body}
    sleep(1)


@step('Date menu shows notification "{title}" with body "{body}"')
def date_menu_shows_notification(context, title, body) -> None:
    shell = context.sandbox.shell
    expected = {title.lower(), body.lower()}

    for _ in range(10):
        matches = shell.findChildren(
            lambda n: any(needle in _node_text(n).lower() for needle in expected)
        )
        combined = " ".join(_node_text(node).lower() for node in matches)
        if all(needle in combined for needle in expected):
            return
        sleep(0.5)

    visible = [
        (node.roleName, _node_text(node))
        for node in shell.findChildren(lambda n: any(needle in _node_text(n).lower() for needle in expected))[:20]
    ]
    raise AssertionError(
        f"Notification title/body not found in date menu AT-SPI tree. Matches: {visible}"
    )
