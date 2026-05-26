import json
import subprocess

from behave import step


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


def run_bootc(*args, acceptable=(0,)):
    command = " ".join(args)
    result = run(command)
    if result.returncode in acceptable:
        return result

    stderr = (result.stderr or "").lower()
    needs_sudo = "must be executed as the root user" in stderr or "permission denied" in stderr
    if needs_sudo:
        sudo_result = run(f"sudo -n {command}")
        if sudo_result.returncode in acceptable:
            return sudo_result
        result = sudo_result

    raise AssertionError(
        f"{command} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def bootc_status_json():
    last_error = None
    for args in (("bootc", "status", "--format=json"), ("bootc", "status", "--json")):
        try:
            result = run_bootc(*args)
            return json.loads(result.stdout)
        except (AssertionError, json.JSONDecodeError) as error:
            last_error = error
    raise last_error


@step("bootc status reports a valid active deployment")
def step_bootc_status(context):
    data = bootc_status_json()
    booted = data.get("status", {}).get("booted")
    assert booted is not None, f"No booted deployment in bootc status: {json.dumps(data, indent=2)[:500]}"


@step("/usr is mounted read-only")
def step_usr_ro(context):
    result = run("findmnt /usr -o OPTIONS -n")
    assert result.returncode == 0, f"findmnt /usr failed: {result.stderr}"
    options = result.stdout.strip()
    assert "ro" in options.split(","), f"/usr is not mounted read-only, options: {options}"


@step("active deployment image reference is present and non-empty")
def step_deployment_image(context):
    data = bootc_status_json()
    booted = data.get("status", {}).get("booted", {})
    image = (
        booted.get("image", {}).get("image", {}).get("image")
        or booted.get("image", {}).get("image")
        or booted.get("imageReference")
        or ""
    )
    assert image, f"No image reference in active deployment: {json.dumps(data, indent=2)[:500]}"


@step("bootc status can query for staged updates without error")
def step_bootc_staged(context):
    result = run_bootc("bootc", "upgrade", "--check", acceptable=(0, 1))
    output = f"{result.stdout}\n{result.stderr}".lower()
    assert "panic" not in output, f"bootc upgrade --check panicked: {result.stdout or result.stderr}"
    assert "traceback" not in output, f"bootc upgrade --check traceback: {result.stdout or result.stderr}"
    assert result.returncode in (0, 1), f"bootc upgrade --check failed: {result.stdout or result.stderr}"
