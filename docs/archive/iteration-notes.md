# Historical iteration notes

These notes were moved out of `RUNBOOK.md` so the runbook can stay timeless.
They are preserved here for debugging history and migration context.

## GNOME smoke baseline (2026-05-26)

First recorded clean GNOME smoke run on both titan VMs. Workflow
`bluefin-titan-smoke-xb9c2` succeeded 4/4 in 4m 50s with no fixes needed.
Full report: [gnome-smoke-2026-05-26.md](gnome-smoke-2026-05-26.md).

This establishes the baseline for titan fast-path regression detection.

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
