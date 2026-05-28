"""
Custom step definitions for developer suite tests.

common_steps covers: Start/Close application, Item found/not found,
Key combo, Press key, Type text, Run and save command output.

Custom steps here:
  - Make sure window is focused for wayland testing
  - Terminal output in ptyxis contains <text>
  - Ptyxis has N tabs
  - No Flatpak missing-runtime error
  - Homebrew bootstrap and profile checks
  - Rootless Podman and Docker runtime checks
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from time import sleep

from behave import step
from qecore.common_steps import *  # noqa: F401,F403


QUADLET_EXTENSIONS = {
    ".build",
    ".container",
    ".image",
    ".kube",
    ".network",
    ".pod",
    ".volume",
}


def _run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True)


def _require_command(name: str) -> str:
    path = shutil.which(name)
    assert path, f"{name} is not available on PATH"
    return path


def _parse_key_value_output(output: str) -> dict[str, str]:
    parsed = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key] = value
    return parsed


def _quadlet_files_in(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [
        path for path in directory.iterdir() if path.is_file() and path.suffix in QUADLET_EXTENSIONS
    ]


@step("Make sure window is focused for wayland testing")
def make_sure_window_is_focused(context) -> None:
    # Pattern from GNOMETerminalAutomation steps.py — prevents input race on Wayland
    sleep(2)
    if context.sandbox.session_type == "wayland":
        context.ptyxis.instance.children[0].click()


@step('Terminal output in ptyxis contains "{text}"')
def terminal_output_contains(context, text) -> None:
    # Ptyxis terminal widget uses roleName "terminal" (VTE-backed)
    terminal_widget = context.ptyxis.instance.child(roleName="terminal")
    assert text in terminal_widget.text, (
        f"Terminal output does not contain '{text}'"
    )


@step('Ptyxis has "{number}" tabs')
def ptyxis_has_n_tabs(context, number) -> None:
    tab_lists = context.ptyxis.instance.findChildren(
        lambda n: n.roleName == "page tab list" and n.showing
    )
    assert tab_lists, "Could not find a visible Ptyxis tab list"
    tabs = tab_lists[0].findChildren(lambda n: n.roleName == "page tab")
    assert len(tabs) == int(number), (
        f"Expected {number} tabs, found {len(tabs)}"
    )


@step('No Flatpak missing-runtime error for "{flatpak_id}"')
def no_flatpak_missing_runtime_error(context, flatpak_id) -> None:
    since = getattr(context, "test_start_time", None)
    if not since:
        since = _run_command(["date", "--iso-8601=seconds"]).stdout.strip()

    result = _run_command(
        [
            "journalctl",
            "--no-pager",
            "--since",
            since,
            "-g",
            f"{flatpak_id}.*runtime.*missing",
        ]
    )
    assert result.returncode in {0, 1}, result.stderr
    assert result.stdout.strip() == "", (
        f"Flatpak runtime-missing error found for {flatpak_id}:\n{result.stdout}"
    )


@step('Last command output contains "{text}"')
def last_command_output_contains(context, text) -> None:
    output = (
        getattr(context, "command_stdout", "")
        or getattr(context, "last_command_output", "")
        or getattr(context, "last_run_output", "")
    )
    assert text in output, f"Expected {text!r} in output:\n{output[:500]}"


@step("Homebrew bootstrap service completed successfully")
def homebrew_bootstrap_service_completed_successfully(context) -> None:
    result = _run_command(
        [
            "systemctl",
            "--user",
            "show",
            "brew-setup.service",
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
            "--property=Result",
            "--property=ExecMainStatus",
        ]
    )
    assert result.returncode == 0, result.stderr
    properties = _parse_key_value_output(result.stdout)
    assert properties.get("LoadState") == "loaded", properties
    assert properties.get("ActiveState") != "failed", properties
    assert properties.get("Result") == "success", properties
    assert properties.get("ExecMainStatus") == "0", properties


@step("Homebrew binary is available on PATH")
def homebrew_binary_is_available_on_path(context) -> None:
    result = _run_command(["which", "brew"])
    assert result.returncode == 0, result.stderr or "brew was not found by which"
    assert result.stdout.strip(), "which brew returned an empty path"


@step("Homebrew doctor completes without unexpected warnings")
def homebrew_doctor_completes_without_unexpected_warnings(context) -> None:
    brew = _require_command("brew")
    env = os.environ | {"HOMEBREW_NO_ANALYTICS": "1"}
    result = subprocess.run(
        [brew, "doctor"], capture_output=True, text=True, env=env
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode == 0:
        return

    assert "Warning:" in output, output
    assert "Error:" not in output, output


@step("Homebrew profile integration is configured")
def homebrew_profile_integration_is_configured(context) -> None:
    brew = _require_command("brew")
    brew_prefix = _run_command([brew, "--prefix"])
    assert brew_prefix.returncode == 0, brew_prefix.stderr

    needles = {"brew shellenv", brew_prefix.stdout.strip(), "linuxbrew"}
    candidate_files = [Path.home() / ".profile", Path.home() / ".bashrc"]
    profile_dir = Path("/etc/profile.d")
    if profile_dir.exists():
        candidate_files.extend(sorted(profile_dir.glob("*.sh")))

    for candidate in candidate_files:
        if not candidate.exists():
            continue
        contents = candidate.read_text(encoding="utf-8", errors="ignore")
        if any(needle in contents for needle in needles):
            return

    searched = ", ".join(str(path) for path in candidate_files)
    raise AssertionError(f"No Homebrew shell integration found in: {searched}")


@step("Podman info reports rootless execution")
def podman_info_reports_rootless_execution(context) -> None:
    podman = _require_command("podman")
    result = _run_command([podman, "info", "--format", "json"])
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)

    host = info.get("host", {})
    store = info.get("store", {})
    rootless = host.get("rootless")
    if rootless is None:
        rootless = host.get("security", {}).get("rootless")

    storage_driver = store.get("graphDriverName") or store.get("graphDriver")
    assert rootless is True, info
    assert isinstance(storage_driver, str) and storage_driver, info


@step("Podman user quadlet directories are supported")
def podman_user_quadlet_directories_are_supported(context) -> None:
    allowed_dirs = [
        Path("/etc/containers/systemd"),
        Path.home() / ".config/containers/systemd",
    ]
    unsupported_dirs = [
        Path.home() / ".config/systemd/user",
        Path("/etc/systemd/user"),
    ]

    unsupported_quadlets = {
        str(directory): [str(path) for path in _quadlet_files_in(directory)]
        for directory in unsupported_dirs
        if _quadlet_files_in(directory)
    }
    assert not unsupported_quadlets, (
        "Quadlet files found outside supported Podman locations: "
        f"{unsupported_quadlets}"
    )

    allowed_quadlets = {
        str(directory): [str(path) for path in _quadlet_files_in(directory)]
        for directory in allowed_dirs
        if directory.exists()
    }
    assert allowed_quadlets or any(directory.exists() for directory in allowed_dirs), (
        "Expected supported quadlet directories under /etc/containers/systemd or "
        "~/.config/containers/systemd"
    )


@step("Podman auto-update timer is active for the user")
def podman_auto_update_timer_is_active_for_the_user(context) -> None:
    result = _run_command(
        [
            "systemctl",
            "--user",
            "show",
            "podman-auto-update.timer",
            "--property=LoadState",
            "--property=ActiveState",
            "--property=UnitFileState",
        ]
    )
    assert result.returncode == 0, result.stderr
    properties = _parse_key_value_output(result.stdout)
    assert properties.get("LoadState") == "loaded", properties
    assert properties.get("ActiveState") == "active", properties


@step("User lingering is enabled")
def user_lingering_is_enabled(context) -> None:
    username = os.environ.get("USER") or _run_command(["id", "-un"]).stdout.strip()
    result = _run_command(
        ["loginctl", "show-user", username, "--property=Linger"]
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Linger=yes", result.stdout


@step("Homebrew Docker runtime mapping is valid when docker is installed")
def homebrew_docker_runtime_mapping_is_valid_when_docker_is_installed(context) -> None:
    docker = shutil.which("docker")
    if not docker:
        return

    brew = shutil.which("brew")
    if not brew:
        return

    brew_prefix = _run_command([brew, "--prefix"])
    assert brew_prefix.returncode == 0, brew_prefix.stderr
    docker_is_homebrew = docker.startswith(brew_prefix.stdout.strip())
    docker_is_homebrew = docker_is_homebrew or (
        _run_command([brew, "list", "--versions", "docker"]).returncode == 0
    )
    if not docker_is_homebrew:
        return

    env_host = os.environ.get("DOCKER_HOST", "").strip()
    active_context = _run_command([docker, "context", "show"])
    assert active_context.returncode == 0, active_context.stderr
    context_name = active_context.stdout.strip()

    context_host = ""
    if context_name:
        inspect = _run_command([docker, "context", "inspect", context_name])
        assert inspect.returncode == 0, inspect.stderr
        context_data = json.loads(inspect.stdout)
        context_host = (
            context_data[0]
            .get("Endpoints", {})
            .get("docker", {})
            .get("Host", "")
            .strip()
        )

    effective_host = env_host or context_host
    assert context_name or env_host, "Neither docker context nor DOCKER_HOST is configured"
    assert effective_host, "Could not determine Docker endpoint from context or DOCKER_HOST"

    uid = os.getuid()
    expected_hosts = {
        f"unix:///run/user/{uid}/podman/podman.sock",
        f"unix://{Path.home()}/.colima/default/docker.sock",
    }
    assert effective_host in expected_hosts, (
        f"Unexpected Docker endpoint: {effective_host} (context={context_name!r}, "
        f"DOCKER_HOST={env_host!r})"
    )

    socket_path = Path(effective_host.removeprefix("unix://"))
    assert socket_path.exists(), f"Docker socket is missing: {socket_path}"
