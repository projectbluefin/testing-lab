import subprocess

from behave import step


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


@step("composefs is used for the root filesystem mount")
def step_composefs_root(context):
    root_mount = run("findmnt / -o FSTYPE,SOURCE -n")
    usr_mount = run("findmnt /usr -o FSTYPE,SOURCE -n")
    proc_mounts = run("grep -E 'composefs|erofs|overlay' /proc/mounts || true")

    assert root_mount.returncode == 0, f"findmnt / failed: {root_mount.stderr}"
    assert usr_mount.returncode == 0, f"findmnt /usr failed: {usr_mount.stderr}"

    combined = "\n".join(
        part.strip()
        for part in (root_mount.stdout, usr_mount.stdout, proc_mounts.stdout)
        if part.strip()
    )
    assert any(token in combined for token in ("composefs", "overlay", "erofs")), (
        "No composefs-style mount found.\n"
        f"findmnt /: {root_mount.stdout}\n"
        f"findmnt /usr: {usr_mount.stdout}\n"
        f"/proc/mounts matches:\n{proc_mounts.stdout}"
    )


@step("/etc/prepare-root.conf exists and is readable")
def step_prepare_root_conf(context):
    result = run("test -r /etc/prepare-root.conf && cat /etc/prepare-root.conf")
    assert result.returncode == 0, "/etc/prepare-root.conf is missing or unreadable"


@step("/usr mount shows composefs or overlay backing")
def step_usr_composefs(context):
    result = run("findmnt /usr -o FSTYPE,SOURCE -n")
    assert result.returncode == 0, f"findmnt /usr failed: {result.stderr}"
    output = result.stdout.strip()
    assert any(fs in output for fs in ("overlay", "composefs", "erofs")), (
        f"/usr does not use composefs/overlay/erofs: {output}"
    )


@step("/etc/containers/policy.json exists and is readable")
def step_signature_policy(context):
    result = run(
        "test -r /etc/containers/policy.json && python3 -m json.tool /etc/containers/policy.json > /dev/null"
    )
    assert result.returncode == 0, "/etc/containers/policy.json is missing, unreadable, or not valid JSON"
