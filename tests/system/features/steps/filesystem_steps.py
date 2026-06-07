import subprocess

from behave import step


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


@step("root filesystem compression is enabled if btrfs")
def step_btrfs_compression(context):
    fstype = run("findmnt / -o FSTYPE -n")
    assert fstype.returncode == 0, f"findmnt / failed: {fstype.stderr}"
    fs = fstype.stdout.strip()

    if fs != "btrfs":
        context.scenario.skip(f"root filesystem is {fs}, not btrfs — skipping compression check")
        return

    opts = run("findmnt / -o OPTIONS -n")
    assert opts.returncode == 0, f"findmnt / -o OPTIONS failed: {opts.stderr}"
    mount_options = opts.stdout.strip()

    assert "compress" in mount_options, (
        f"btrfs root mount is missing compression option (bluefin#4655).\n"
        f"Mount options: {mount_options}\n"
        f"Expected 'compress=zstd' or similar in mount options."
    )
