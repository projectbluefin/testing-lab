# Vanguard Lab Strike Report — Canonical Template

> Vendored from `~/src/skills/ghost-testlab/report-template.md` so any agent
> reviewing a PR for this repo (or `knuckle` / `dakota`) can comply without
> external skill access.
>
> **Hard rule:** PR approval requires a Vanguard report on the PR with real
> lab evidence. Narrative-only reports do not satisfy the gate. Match the
> structure exactly: header order, verdict line, evidence sections, real
> command/output blocks. See [`agent-cheatsheet.md`](agent-cheatsheet.md) §8.

---

## Base Structure (shared by all targets)

```markdown
## ⚡ Vanguard Lab Strike Report: {hostname}
**Alpha**: Blue Universal CI Companion · {target designation}
**Guardian on Duty**: `castrojo` on Ghost Homelab

*"{flavor text}"*

| Field    | Value |
|---|---|
| **Branch**  | `{branch}` @ `{sha12}` |
| **PR**      | #{number}: {title} |
| **Closes**  | #{issues} |
| **Target**  | `{knuckle|dakota|bluefin-lts|testing-lab}` |
| **VM/Host** | `{vm-name}` ({host-detail}) |
| **Image**   | `{exact image string image-or-version}` |
| **Date**    | {ISO-8601 timestamp} |
| **Tier**    | {0|1|3} · {tier lore descriptor} |
| **Labels**  | {domain labels} |

{evidence sections — see "Evidence sections" below}

### Desktop Smoke Test

```
=== Desktop Smoke Test ===
{verbatim output of verify-desktop.sh / titan smoke / behave summary}
```

---

**🟢 GO** / **🔴 NOGO** — {one-line summary}

<!-- status:{PASS|FAIL} target:{...} label:{...} digest:{...} -->

---

## AGENT INSTRUCTIONS:
<!-- Reviewer: edit this section to leave requested changes. Agent reads here first. -->
- none
```

## Tier Lore Descriptors

| Tier | Descriptor          | What it means                                          |
|------|---------------------|--------------------------------------------------------|
| 0    | Ghost Uplink        | CI gate only — dev machine, no VM.                     |
| 1    | Recon Element       | Installer VM alive, tools verified, dry-run clean.     |
| 3    | Strike Confirmed    | Full install, system booted, Guardian on the ground.   |

## Evidence sections (pick what applies)

Use the sections that match what you actually ran. Do not invent sections.
Every section must contain real command output, not paraphrase.

- `### Tier 0 — Ghost Uplink · CI Gate` — lint, schema validation, dry-run.
- `### Tier 1 — Recon Element · VM Liveness` — `just list-vms`, IP / SSH reach.
- `### Tier 3 — Strike Confirmed · Full Loop` — full `just run-tests*` output.
- `### Desktop Smoke Test` — behave JSON summary or `verify-desktop.sh`.
- `### Loki Evidence` — pasted Loki query + first/last lines of result.
- `### Workflow Evidence` — `argo get <wf>` snippet + status.
- `### Blockers` — open issues filed in the **owning repo** with links.

## Verdict line

Single line, no qualifiers:

- `🟢 GO — <one-line summary>`
- `🔴 NOGO — <one-line summary referencing the blocker issue>`

The HTML comment at the end is parsed by automation. Keep it on its own line.

## Anti-patterns (the report is rejected if it has these)

- Narrative-only sections without command output.
- Paraphrased behave results instead of the actual JSON / summary block.
- Verdict without a referenced workflow name.
- Skipped Tier when one was actually run (e.g. "trusted the unit test layer").
- Missing blocker issue links when verdict is NOGO.

## Full example (bluefin latest, Tier 3, NOGO) — 2026-05-26

This example demonstrates a complete fresh-VM Tier 3 run that reached GNOME Shell
but failed the top-bar contract.  Use it as a reference for the full evidence shape,
NOGO verdict formatting, and blocker issue linking.

```markdown
## ⚡ Vanguard Lab Strike Report: bluefin-test-a4af2fb9
**Alpha**: Blue Universal CI Companion · testing-lab report example
**Guardian on Duty**: `castrojo` on Ghost Homelab

*"Fresh-VM smoke reached GNOME Shell, then the live top-bar contract broke wide open."*

| Field | Value |
|---|---|
| **Branch** | `main` @ `e0da826ff097` |
| **PR** | — |
| **Closes** | — |
| **Target** | `testing-lab` |
| **VM/Host** | `bluefin-test-a4af2fb9-0878-44da-ac72-89eb027aca92` (bluefin-test namespace on ghost; VM IP `10.42.0.220`) |
| **Image** | `ghcr.io/ublue-os/bluefin:latest` |
| **Date** | 2026-05-26T14:18:16Z |
| **Tier** | 3 · **Strike Confirmed** |
| **Labels** | `domain:testing` `domain:desktop` `domain:shell` `domain:data-capture` |

### Tier 3 — Strike Confirmed · Full Loop

```text
$ argo get bluefin-qa-smoke-qbpc2 -n argo --no-color
Name:                bluefin-qa-smoke-qbpc2
Namespace:           argo
ServiceAccount:      argo
Status:              Failed
Finished:            Tue May 26 10:18:16 -0400
Duration:            4 minutes 39 seconds
Parameters:
  image:             ghcr.io/ublue-os/bluefin:latest
  image-tag:         latest
  branch:            main

STEP                              TEMPLATE                           PODNAME                                              DURATION  MESSAGE
 ✖ bluefin-qa-smoke-qbpc2         bluefin-test-pipeline
 ├─✔ ensure-disk                  bib-build-and-push/ensure-disk
 │ ├───✔ check                    bib-disk-check                     bluefin-qa-smoke-qbpc2-bib-disk-check-3186093576     4s
 │ ├───○ pull-image               bib-img-pull                                                                                      when 'exists != exists' evaluated false
 │ ├───○ build                    bib-img-build                                                                                     when 'exists != exists' evaluated false
 │ └───○ configure                bib-disk-configure                                                                                when 'exists != exists' evaluated false
 ├─✔ provision                    provision-bluefin-vm/provision-vm
 │ ├───✔ reflink-disk             reflink-disk                       bluefin-qa-smoke-qbpc2-reflink-disk-2562694658       4s
 │ ├───✔ create-vm                create-vm                          bluefin-qa-smoke-qbpc2-create-vm-2881440482          2s
 │ └───✔ wait-for-vm              wait-for-vm-ready                  bluefin-qa-smoke-qbpc2-wait-for-vm-ready-3689230188  12s
 └─✖ run-tests                    run-gnome-tests/run-gnome-tests    bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209    3m        main: Error (exit code 1)
```

### Workflow Evidence

```text
$ argo logs bluefin-qa-smoke-qbpc2 -n argo --no-color | rg 'Waiting for SSH|SSH ready|Dependencies ready|ASSERT FAILED'
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209: Waiting for SSH on 10.42.0.220 (variant=latest, suite=smoke)...
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209: SSH ready.
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209: Dependencies ready.
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209:               "ASSERT FAILED: Panel (role='panel') not found in gnome-shell.",
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209:             "error_message": "ASSERT FAILED: Activities overview did not open after 4s",
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209:             "error_message": "ASSERT FAILED: Quick Settings not open — Shell.Eval inner: '\"true\"'",
bluefin-qa-smoke-qbpc2-run-gnome-tests-3392667209:             "error_message": "ASSERT FAILED: Date menu not open — Shell.Eval inner: '\"true\"'"
```

### Desktop Smoke Test

```text
$ python3 summarize-results.py /tmp/bluefin-qa-smoke-qbpc2-results.json
3 passed, 11 failed, 14 total
- Panel is present in AT-SPI tree
- Activities toggle button is visible in panel
- Clock toggle button is visible in panel
- System menu toggle button is visible in panel
- Super key opens Activities overview
- Typing in overview populates search bar
- Escape closes Activities overview
- Clicking System menu opens Quick Settings
- Escape closes Quick Settings
- Clicking clock opens calendar popup
- Escape closes calendar popup
```

### Blockers

```text
$ gh issue view 101 --repo castrojo/testing-lab
#101 bug: fresh latest smoke run loses GNOME Shell panel/top-bar coverage
https://github.com/castrojo/testing-lab/issues/101
```

---

**🔴 NOGO** — `bluefin-qa-smoke-qbpc2` completed the full fresh-VM loop but failed GNOME Shell smoke coverage; blocker: #101.

<!-- status:FAIL target:testing-lab label:kind:report digest:bluefin-qa-smoke-qbpc2 -->
```

---

## Minimum example (testing-lab self-PR, Tier 1)

```markdown
## ⚡ Vanguard Lab Strike Report: titan-bluefin
**Alpha**: Blue Universal CI Companion · testing-lab self-PR
**Guardian on Duty**: `castrojo` on Ghost Homelab

| Field   | Value |
|---|---|
| **Branch** | `feat/x` @ `abcdef012345` |
| **PR**     | #99: feat(x): … |
| **Target** | `testing-lab` |
| **VM/Host**| `titan-bluefin` (bluefin-test ns on ghost) |
| **Image**  | `ghcr.io/ublue-os/bluefin:latest` |
| **Date**   | 2026-05-26T13:00:00Z |
| **Tier**   | 1 · **Recon Element** |
| **Labels** | `area:workflow` |

### Tier 1 — Recon Element · VM Liveness

```
$ just list-vms
NAMESPACE       NAME             AGE  STATUS    READY
bluefin-test    titan-bluefin    7d   Running   True
bluefin-lts-test titan-lts       7d   Running   True
```

### Desktop Smoke Test

```
=== Desktop Smoke Test ===
1 feature passed, 0 failed
6 scenarios passed, 0 failed
```

---

**🟢 GO** — titan smoke green against `latest`; no behave regressions vs main.

<!-- status:PASS target:testing-lab label:agent-tested digest:abcdef012345 -->

---

## AGENT INSTRUCTIONS:
<!-- Reviewer: edit this section to leave requested changes. Agent reads here first. -->
- none
```
