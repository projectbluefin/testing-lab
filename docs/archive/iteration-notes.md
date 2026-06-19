# Historical iteration notes

These notes were moved out of `RUNBOOK.md` so the runbook can stay timeless.
They are preserved here for debugging history and migration context.

## Flatcar E2E bringup lessons (2026-05-26)

Seven infra bugs fixed to achieve the first green Flatcar run. Full report:
[flatcar-first-green.md](flatcar-first-green.md).

### Runner pod image assumptions

Fedora minimal images (`quay.io/fedora/fedora:latest`) do not include `pip3` as a
standalone binary. Always use `python3 -m pip install` instead of `pip3 install`.
The runner also needs `openssh-clients` installed explicitly.

### Test delivery: git clone, not hostPath

The original Flatcar runner read tests from a stale hostPath (`/var/tmp/bluefin-tests`).
This is fragile — the same pattern that Bluefin runners already fixed with `git-sync`.
Always clone tests from git at runtime.

### Argo artifact outputs require storage config

Adding `outputs.artifacts` to a template causes exit code 64 if the Argo artifact
repository is not configured. Since this cluster does not use artifact storage,
workflow evidence goes to pod stdout (captured by Loki). Omit artifact outputs.

### Flatcar containerd socket permissions

The `core` user cannot access `/run/containerd/containerd.sock` directly. Use
`sudo ctr version` in tests. The `core` user has passwordless sudo on Flatcar.

## Iteration 2 lessons (2026-05-25)

### dogtail API changes — root cause + migration

**Root cause of `requireResult` `TypeError`:**
`findChild(self, predicate, retry=True)` declares no `**kwargs`. The logging decorator binds the
call before the function body runs, so an unknown kwarg such as `requireResult` raises `TypeError`
before `find_descendant` can process it.

**`retry=True` causes long waits:** the default `findChild(pred)` path retries repeatedly when the
node is missing. Use `retry=False` for fast-fail lookups.

**Migration table:**

```python
# OLD (broken)
node = root.findChild(pred, requireResult=True)   # TypeError
node = root.findChild(pred, requireResult=False)  # TypeError
node = root.findChild(pred)                       # works but waits a long time if missing

# NEW
node = root.findChild(pred, retry=True)    # require node exists
node = root.findChild(pred, retry=False)   # fast fail
nodes = root.findChildren(pred)            # no-raise presence check
node = nodes[0] if nodes else None

if root.findChildren(pred):
    ...
```

### qecore `run_and_save` timeout rule

- Output lands in `context.command_stdout`.
- Bound noisy commands. Example:

```bash
journalctl --lines=50 -p err..emerg
```

### GNOME Shell 50.1 AT-SPI gaps

On Bluefin 44 / GNOME Shell 50.1, the top-bar panel exposes only `Activities` and `Show Apps`
reliably. Clock and system-status interactions need `Shell.Eval` or another non-AT-SPI path.

```bash
gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
  --method org.gnome.Shell.Eval 'global.context.unsafe_mode = true'
```

### Test file delivery

`run-gnome-tests` delivers tests via the `git-sync` initContainer. No ConfigMap sync and no hostPath
for test files.

### Artifact reading

`run-gnome-tests` prints `results.json` to stderr near the end of the run. Use Argo logs or Loki to
retrieve it after pod cleanup.
