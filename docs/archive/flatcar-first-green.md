# Flatcar E2E First Green Run — Strike Report

> Archived from [#106](https://github.com/projectbluefin/testing-lab/issues/106).
> Date: 2026-05-26. Workflow: `flatcar-smoke-b9ngr`. Commit: `f0f8714`.

## Result

7/7 boot scenarios passed. Workflow succeeded in 1m 30s.

```
STEP                           TEMPLATE                DURATION
 ✔ flatcar-smoke-b9ngr         flatcar-test-pipeline
 ├─✔ provision                 provision-flatcar-vm
 │ ├───✔ prepare-disk          prepare-flatcar-disk       4s
 │ ├───✔ create-vm             create-flatcar-vm          2s
 │ └───✔ wait-for-vm           wait-for-flatcar-ready    15s
 └─✔ run-tests                 run-flatcar-tests         19s

 ✔ flatcar-smoke-b9ngr.onExit  cleanup
 └───✔ teardown                teardown-flatcar-vm
     ├───✔ delete-vm           delete-vm                  6s
     └───✔ delete-hostdisk     delete-hostdisk            3s
```

## Infrastructure fixes applied before first green

Seven bugs discovered and fixed during the bringup session:

| # | Commit | Problem | Fix |
|---|---|---|---|
| 1 | `e9e9085` | Fedora minimal has no `pip3` binary | `pip3` → `python3 -m pip` |
| 2 | `e9be83c` | Runner pod missing Python and SSH | `dnf install python3 python3-pip openssh-clients` in runner |
| 3 | `c3c8339` | SSH pubkey not available to Flatcar provisioner | Read from `bluefin-test-ssh-key` secret via `secretKeyRef` |
| 4 | `ce4eae7` | `html-pretty` behave formatter not installed | Drop `html-pretty`; use `json.pretty` only |
| 5 | `5614971` | Tests read from stale hostPath `/var/tmp/bluefin-tests` | Clone tests from git at runtime |
| 6 | `f0f8714` | Argo artifact storage not configured | Remove artifact `outputs:` (causes exit 64) |
| 7 | `698c61f` | `ctr version` fails as `core` user | `ctr version` → `sudo ctr version` (containerd socket requires root) |

## Durable lessons

- **Fedora minimal images lack `pip3`**: always use `python3 -m pip` in workflow pods.
- **Never rely on hostPath for test files**: clone from git at runtime via `git-sync` or inline clone.
- **Argo artifact `outputs:` requires storage config**: omit artifact outputs if Argo's artifact repository is not configured; the workflow exits 64 silently.
- **Flatcar `core` user cannot access containerd socket directly**: use `sudo` for `ctr` commands. The `core` user has passwordless sudo.
- **SSH key injection for Flatcar**: use `secretKeyRef` from the shared `bluefin-test-ssh-key` secret, same as Bluefin pipelines.
