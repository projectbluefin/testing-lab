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

## Full example (titan fast path, Tier 3, GO) — 2026-05-26

This example demonstrates a complete titan fast-path Tier 3 run against both
`latest` and `lts` variants, with all four workflow steps passing.  Use it as
a reference for parallel-titan report shape, GO verdict formatting, and the
Workflow Evidence section when no fresh-VM provisioning is involved.

```markdown
## ⚡ Vanguard Lab Strike Report: titan-bluefin + titan-lts
**Alpha**: Blue Universal CI Companion · testing-lab GNOME E2E
**Guardian on Duty**: `castrojo` on Ghost Homelab

*"All icons hold. Smoke clears clean across both variants."*

| Field | Value |
|---|---|
| **Branch** | `main` @ `f9cef2521e6e` |
| **Target** | `testing-lab` |
| **VM/Host** | `titan-bluefin` (bluefin-test ns, ghost) · `titan-lts` (bluefin-lts-test ns, ghost) |
| **Image** | `ghcr.io/ublue-os/bluefin:latest` + `ghcr.io/ublue-os/bluefin:lts` |
| **Date** | 2026-05-26T21:14:25-04:00 |
| **Tier** | 3 · **Strike Confirmed** |
| **Labels** | `area:smoke-test` |

---

### Tier 1 — Recon Element · VM Liveness

```text
=== bluefin-test ===
NAME            AGE   STATUS    READY
titan-bluefin   80m   Running   True

=== bluefin-lts-test ===
NAME        AGE   STATUS    READY
titan-lts   80m   Running   True

titan-bluefin IP: 10.42.0.28
titan-lts IP:     10.42.0.27
```

---

### Tier 3 — Strike Confirmed · Full Loop

```text
$ just run-titan-smoke

STEP                          TEMPLATE                         PODNAME                                               DURATION  MESSAGE
 ✔ bluefin-titan-smoke-xb9c2  run-smoke
 ├─┬─✔ preflight-latest       preflight                        bluefin-titan-smoke-xb9c2-preflight-2557673761        28s
 │ └─✔ preflight-lts          preflight                        bluefin-titan-smoke-xb9c2-preflight-1719761299        29s
 └─┬─✔ smoke-latest           run-gnome-tests/run-gnome-tests  bluefin-titan-smoke-xb9c2-run-gnome-tests-299232976   4m
   └─✔ smoke-lts              run-gnome-tests/run-gnome-tests  bluefin-titan-smoke-xb9c2-run-gnome-tests-3595901320  3m

Status:   Succeeded
Duration: 4 minutes 50 seconds
Progress: 4/4
```

### Workflow Evidence

```text
Workflow:  bluefin-titan-smoke-xb9c2
Namespace: argo
Status:    Succeeded
Created:   Tue May 26 21:14:25 -0400
Finished:  Tue May 26 21:19:15 -0400
Duration:  4 minutes 50 seconds
Parameters:
  vm-ip-latest: 10.42.0.28
  vm-ip-lts:    10.42.0.27
  suite:        smoke
  branch:       main
```

---

**🟢 GO** — `bluefin-titan-smoke-xb9c2` succeeded 4/4; GNOME smoke green on both `latest` and `lts` titans.

<!-- status:PASS target:testing-lab label:area:smoke-test digest:f9cef2521e6e -->
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
