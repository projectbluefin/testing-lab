import re
import subprocess
import sys
import time

from dogtail.config import config as dogtail_config
from dogtail import tree as dtree


last_err = "unknown"
dogtail_config.searchShowingOnly = True


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
        err = result.stderr.strip() or result.stdout.strip() or "unknown gdbus failure"
        raise RuntimeError(f"Shell.Eval not ready: {err[:200]}")

    match = re.search(r"\((?:true|false),\s*'(.*)'\)", result.stdout.strip())
    if match is None:
        raise RuntimeError(f"unexpected Shell.Eval output: {result.stdout.strip()[:200]}")
    return match.group(1)


def _describe_shell(shell) -> str:
    top_level = [(child.roleName, child.name, child.showing) for child in shell.children[:12]]
    panels = shell.findChildren(lambda node: node.roleName == "panel")
    panel_children = []
    toggle_names = []
    if panels:
        panel_children = [
            (child.roleName, child.name, child.showing) for child in panels[0].children[:12]
        ]
        toggle_names = [toggle.name for toggle in panels[0].findChildren(lambda n: n.roleName == "toggle button")]
    return (
        f"top-level={top_level}; "
        f"panel-children={panel_children}; "
        f"toggle-names={toggle_names}"
    )


for attempt in range(1, 31):
    try:
        panel_ready = _shell_eval_inner(
            "global.context.unsafe_mode = true; (!!Main.panel).toString()"
        )
        if panel_ready != "true":
            last_err = f"Main.panel not ready yet (Shell.Eval inner={panel_ready!r})"
            print(f"Readiness attempt {attempt}: {last_err}", flush=True)
            time.sleep(2)
            continue

        shell = dtree.root.application("gnome-shell")
        panels = shell.findChildren(lambda n: n.roleName == "panel")
        if not panels:
            last_err = (
                "gnome-shell panel not exposed in AT-SPI yet; "
                f"{_describe_shell(shell)}"
            )
            print(f"Readiness attempt {attempt}: {last_err}", flush=True)
            time.sleep(2)
            continue

        toggles = panels[0].findChildren(lambda n: n.roleName == "toggle button")
        toggle_names = [t.name for t in toggles]
        if toggles:
            print(f"GNOME Shell ready (attempt {attempt}): {toggle_names}", flush=True)
            sys.exit(0)

        last_err = (
            "panel found but toggle buttons are not AT-SPI discoverable yet; "
            f"{_describe_shell(shell)}"
        )
        print(f"Readiness attempt {attempt}: {last_err}", flush=True)
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
        print(f"Readiness attempt {attempt} failed: {last_err}", flush=True)
    time.sleep(2)

print(
    f"ERROR: GNOME Shell AT-SPI readiness failed after 30 attempts ({last_err})",
    file=sys.stderr,
    flush=True,
)
sys.exit(1)
