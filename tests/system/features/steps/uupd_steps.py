import json
import subprocess

from behave import step


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


def run_bootc_upgrade_check():
    result = run("bootc upgrade --check")
    if result.returncode == 0:
        return result

    stderr = (result.stderr or "").lower()
    if "must be executed as the root user" in stderr or "permission denied" in stderr:
        sudo_result = run("sudo -n bootc upgrade --check")
        if sudo_result.returncode in (0, 1):
            return sudo_result
        result = sudo_result

    return result


@step("/etc/uupd/config.json exists and parses as valid JSON")
def step_uupd_config(context):
    result = run("cat /etc/uupd/config.json")
    assert result.returncode == 0, "/etc/uupd/config.json is missing or unreadable"
    try:
        context.uupd_config = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"/etc/uupd/config.json is not valid JSON: {error}\nContent: {result.stdout[:500]}"
        ) from error


@step("uupd.service unit is present on the system")
def step_uupd_service(context):
    result = run("systemctl show uupd.service --property=LoadState --value")
    assert result.returncode == 0, "uupd.service unit not found"
    assert result.stdout.strip() and result.stdout.strip() != "not-found", "uupd.service unit not found"


@step("bootc upgrade --check exits cleanly")
def step_bootc_upgrade_check(context):
    result = run_bootc_upgrade_check()
    output = f"{result.stdout}\n{result.stderr}".lower()
    assert "panic" not in output, f"bootc upgrade --check panicked: {(result.stdout or result.stderr)[:500]}"
    assert "traceback" not in output, f"bootc upgrade --check traceback: {(result.stdout or result.stderr)[:500]}"
    assert result.returncode in (0, 1), f"bootc upgrade --check unexpected output: {(result.stdout or result.stderr)[:500]}"


@step("at least one uupd module is enabled in config")
def step_uupd_modules(context):
    config = getattr(context, "uupd_config", None)
    if config is None:
        result = run("cat /etc/uupd/config.json")
        assert result.returncode == 0, "/etc/uupd/config.json missing"
        config = json.loads(result.stdout)

    modules = config.get("modules", config.get("checks", []))
    assert isinstance(modules, list) and modules, f"No modules/checks found in uupd config: {json.dumps(config)[:500]}"

    enabled = [module for module in modules if not isinstance(module, dict) or module.get("enabled", True)]
    assert enabled, f"No enabled modules/checks found in uupd config: {json.dumps(config)[:500]}"
