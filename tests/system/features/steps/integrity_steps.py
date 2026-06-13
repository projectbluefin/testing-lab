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


@step("newuidmap has cap_setuid file capability")
def step_newuidmap_caps(context):
    _assert_file_capability("/usr/bin/newuidmap", "cap_setuid")


@step("newgidmap has cap_setgid file capability")
def step_newgidmap_caps(context):
    _assert_file_capability("/usr/bin/newgidmap", "cap_setgid")


@step("ping has cap_net_raw file capability")
def step_ping_caps(context):
    _assert_file_capability("/usr/bin/ping", "cap_net_raw")


def _assert_file_capability(path, expected_cap):
    """Check that `path` has the named file capability set.

    Regression guard: dakota#841 / bluefin-lts boot failure 2026-06-13.
    security.capability xattrs are injected by chunka during image export.
    A broken export (e.g. buildah commit multi-layer) causes chunka to miss
    the xattr injection, stripping capabilities from executables.
    """
    result = run(f"getcap {path}")
    if result.returncode != 0 or not result.stdout.strip():
        # getcap returns 0 with empty output when no caps are set
        actual = result.stdout.strip() or "(none)"
        raise AssertionError(
            f"{path} has no file capabilities (expected {expected_cap}).\n"
            "This indicates composefs xattr injection failed during image export.\n"
            "See: dakota#841 — buildah commit multi-layer export strips xattrs.\n"
            f"getcap output: {actual}\n"
            f"getcap stderr: {result.stderr}"
        )
    if expected_cap not in result.stdout:
        raise AssertionError(
            f"{path} is missing {expected_cap}.\n"
            f"Got: {result.stdout.strip()}\n"
            "See: dakota#841 — composefs xattr injection failure."
        )
