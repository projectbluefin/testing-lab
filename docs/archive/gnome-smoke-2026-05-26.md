# GNOME Smoke Strike Report — titan-bluefin + titan-lts

> Archived from [#108](https://github.com/projectbluefin/testing-lab/issues/108).
> Date: 2026-05-26. Workflow: `bluefin-titan-smoke-xb9c2`. Commit: `f9cef2521e6e`.

## Result

GNOME smoke green on both `latest` and `lts` titan VMs. 4/4 steps succeeded in 4m 50s.

```
STEP                          TEMPLATE                         DURATION
 ✔ bluefin-titan-smoke-xb9c2  run-smoke
 ├─┬─✔ preflight-latest       preflight                        28s
 │ └─✔ preflight-lts          preflight                        29s
 └─┬─✔ smoke-latest           run-gnome-tests/run-gnome-tests  4m
   └─✔ smoke-lts              run-gnome-tests/run-gnome-tests  3m
```

## VM state at test time

| VM | Namespace | IP | Status |
|---|---|---|---|
| titan-bluefin | bluefin-test | 10.42.0.28 | Running / Ready |
| titan-lts | bluefin-lts-test | 10.42.0.27 | Running / Ready |

## Workflow parameters

| Parameter | Value |
|---|---|
| `vm-ip-latest` | 10.42.0.28 |
| `vm-ip-lts` | 10.42.0.27 |
| `suite` | smoke |
| `branch` | main |

## Notes

No infrastructure fixes required. This was a clean green run — both the
titan fast path and the GNOME smoke suite were stable on the same day as
the Flatcar first green ([flatcar-first-green.md](flatcar-first-green.md)).
