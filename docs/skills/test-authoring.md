---
name: test-authoring
description: >
  Writing, debugging, and running behave/qecore/dogtail GNOME GUI tests in
  the testing-lab. Use when adding test scenarios, fixing AT-SPI failures,
  debugging Shell.Eval interactions, or working with the qecore-headless
  session.
---

# Test Authoring — testing-lab Skill

## When to Use

- Adding a new `.feature` file or step definition
- Fixing a failing AT-SPI test (`findChild`, `findChildren`, `Shell.Eval`)
- Debugging `qecore-headless` startup failures
- Working with GNOME Shell 50 top-bar interactions
- Understanding why a test passes locally but fails in the workflow

## When NOT to Use

- Argo Workflows template YAML → `argo-workflows.md`
- VM boot failures before tests start → `kubevirt-vms.md`
- `run-gnome-tests` Argo template changes → `argo-workflows.md`

## Core Process

### 1. Test directory layout

```
tests/
├── smoke/features/              Phase 1 — GNOME Shell, Activities, top-bar
├── developer/features/          Phase 2 — Ptyxis, Homebrew, Podman, micro
├── software/features/           Phase 3 — Flatpak, Bazaar, GNOME Software
├── system/features/             Phase 4 — bootc contract, atomic OS checks
└── flatcar/features/            Phase 5 — Flatcar systemd + containers
```

Add `.feature` files to the appropriate `features/` directory.
Add step implementations in `features/steps/`.

Tag new/unstable scenarios `@wip` until they pass reliably in CI.

### 2. qecore-headless session startup (required incantation)

```bash
qecore-headless --session-type wayland --session-desktop gnome <test-script>
```

Both flags are required. `wayland` only — Xorg is not available. `gnome` session desktop
matches the GNOME Shell environment Bluefin boots into.

### 3. AT-SPI tree traversal — findChildren vs findChild

```python
# ✅ No-raise presence check (returns empty list, not exception)
nodes = app.findChildren(pred)
if nodes:
    nodes[0].click()

# ✅ Fast failure without the default long retry loop
node = app.findChild(pred, retry=False)

# ✗ INVALID in this repo's dogtail stack
app.findChild(pred, requireResult=True)   # requireResult kwarg doesn't exist here
app.findChild(pred, requireResult=False)  # same — will TypeError
```

`findChild(pred, requireResult=...)` is invalid. Use `findChildren(pred)` for
no-raise checks or `findChild(pred, retry=False)` for fast failure.

### 4. GNOME Shell 50 — top-bar limitations

On Bluefin (GNOME Shell 50.1), the clock and system-status area are **not reliably
actionable via AT-SPI**. The AT-SPI tree normally exposes only `Activities` and
`Show Apps` in the top bar.

**Use Shell.Eval for top-bar interactions:**

```python
# Enable unsafe mode first
global.context.unsafe_mode = True  # required for top-bar AT-SPI

# Or drive via gdbus Shell.Eval
import subprocess
result = subprocess.run([
    'gdbus', 'call', '--session',
    '--dest', 'org.gnome.Shell',
    '--object-path', '/org/gnome/Shell',
    '--method', 'org.gnome.Shell.Eval',
    'Main.panel.statusArea.dateMenu.menu.toggle()'
], capture_output=True, text=True)
```

Clock, quick-settings, and calendar interactions **must** use Shell.Eval.

### 5. bootc system assertions (system/ suite)

The `system/` suite is the most important. It validates the bootc contract:

```gherkin
Scenario: bootc status shows a valid image
  When I run "bootc status --format json"
  Then the output contains a valid image reference
  And the transport is "registry"

Scenario: /usr is read-only
  When I run "touch /usr/test-file"
  Then the command fails with permission denied

Scenario: bootc upgrade is staged not immediate
  When I run "bootc upgrade"
  Then the output contains "Queued for next boot"
  And the current boot is unchanged
```

Prioritize system/ tests over cosmetic UI checks. The lab's north star is proving
the bootc contract holds in real user workflows.

### 6. Unsafe mode for top-bar interactions

```python
# In your environment setup or conftest
from dogtail.utils import run
run('gdbus call --session --dest org.gnome.Shell '
    '--object-path /org/gnome/Shell '
    '--method org.gnome.Shell.Eval '
    '"global.context.unsafe_mode = true"')
```

Must be called before any AT-SPI interaction with the top bar.

### 7. Debugging test failures in the workflow

Tests run inside `run-gnome-tests` — a Fedora pod SSHing into the VM. Artifacts land in `/tmp/results/` inside the pod.

```bash
# Get workflow logs
just logs
# or
argo logs -n argo <workflow-name>

# Get specific step logs
argo logs -n argo <workflow-name> --node-name run-gnome-tests

# SSH directly if VM IP is known (from workflow outputs)
ssh -i /path/to/id_ed25519 bluefin-test@<pod-ip>
```

Common failure table from RUNBOOK.md:

| Symptom | Root cause | Fix |
|---|---|---|
| `TypeError` with `requireResult` | Stale dogtail pattern | Use `findChildren()` or `findChild(retry=False)` |
| Clock/quick-settings miss targets | GNOME Shell 50 AT-SPI gap | Use Shell.Eval |
| `outputs.result` has debug text | Script wrote to stdout | Move debug to `>&2` |
| Test hangs on `qecore-headless` | Missing Wayland session flag | Add `--session-type wayland --session-desktop gnome` |

### 8. Writing bootc-contract tests (system/ suite)

When choosing between a new UI test and a new bootc contract test — prefer the
contract test. Bias toward:

- `bootc status` / `bootc upgrade` / `bootc switch` behavior
- `/usr` read-only, `/var` writable
- `composefs` / fs-verity integrity
- `uupd` orchestration
- OCI layer signature verification

See `docs/homelab-contracts.md` for the full contract specification.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll use `findChild(pred, requireResult=False)` — it's cleaner." | `requireResult` kwarg doesn't exist in this repo's dogtail. Use `findChildren()`. |
| "The top-bar items are in the AT-SPI tree, I can click them directly." | GNOME Shell 50 doesn't expose clock/system-status reliably. Use Shell.Eval. |
| "The system/ tests are slow — I'll focus on smoke tests." | The bootc contract is the lab's north star. System tests are the highest-value suite. |
| "I'll add `@wip` and clean it up later." | `@wip` scenarios are skipped in nightly runs. Fix before merging or they rot. |

## Red Flags

- `findChild(pred, requireResult=...)` — will TypeError
- Clicking the clock or system-status area without Shell.Eval on GNOME Shell 50
- New UI scenarios added while zero `system/` bootc contract coverage exists
- Test that only passes in smoke/developer suites but never validates bootc behavior
- `qecore-headless` invoked without `--session-type wayland --session-desktop gnome`

## Verification

Before marking a test change done:

- [ ] New scenario tagged appropriately (remove `@wip` when stable)
- [ ] All AT-SPI traversal uses `findChildren()` or `findChild(retry=False)` — no `requireResult`
- [ ] Top-bar interactions use Shell.Eval (no direct AT-SPI click on clock/system-status)
- [ ] Step definition file is in `tests/<suite>/features/steps/`
- [ ] `python -m pytest --collect-only tests/` passes (CI collection check)
- [ ] `python -m ruff check tests/` passes
