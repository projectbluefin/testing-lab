---
name: skill-improvement
description: >
  Self-learning and skill-maintenance loop for the testing-lab. Run at the
  end of every session that produces non-trivial work. Enforces the
  write-back loop so the next agent starts smarter than this one did.
  Use when wrapping up any session, before creating a PR, or when a pattern
  was discovered through trial and error.
---

# Skill Improvement — testing-lab Self-Learning Loop

Every session produces exactly **two** outputs: the work and the learning.
Output 1 without Output 2 leaves the lab no smarter than before you arrived.

**Canonical skill standard:** [`/addyosmani/agent-skills`](https://context7.com/addyosmani/agent-skills)

---

## When to Use

- End of any session that produced non-trivial code, config, or ops work
- Before creating a PR or marking work done
- When a pattern was discovered by trial and error
- When a tool, API, or cluster behaviour surprised you

## When NOT to Use

- Read-only research sessions with no output
- Doc-only passes that update no skill file and create no new pattern

---

## Core Process

### Step 1 — Skill routing

Route by area changed:

| Area changed | Skill file to update |
|---|---|
| `argo/workflow-templates/` or `argo/*.yaml` | `docs/skills/argo-workflows.md` |
| `provision-vm`, `KubeVirt`, `btrfs reflink` | `docs/skills/kubevirt-vms.md` |
| ArgoCD Applications, `argocd/`, `manifests/` | `docs/skills/gitops-argocd.md` |
| `tests/`, `behave`, `dogtail`, `qecore` | `docs/skills/test-authoring.md` |
| Bootstrap cluster setup, `argo/bootstrap/` | `docs/bootstrap.md` |
| Cluster topology, namespaces, RBAC | `AGENTS.md` |
| Agent operations, MCP tools | `docs/agent-cheatsheet.md` |
| Failure modes, architecture | `RUNBOOK.md` |

Ask: *"If this finding had been in the skill file when I started, would I have avoided the trial-and-error?"* If yes — update the skill file.

### Step 2 — Context7 freshness

Whenever a skill file covers a named library or tool, verify its examples against current docs **before** updating:

```
DETECT → FETCH → EMBED → CITE
```

1. `resolve-library-id("<library>")` → get the Context7 library ID
2. `query-docs("<id>", "<specific pattern>")` → fetch current docs
3. Embed the verified pattern in the skill
4. Note the library ID in frontmatter: `context7-sources: [/org/project]`

Key library IDs for this repo:
- Argo Workflows: `/argoproj/argo-workflows`
- Argo CD: `/argoproj/argo-cd`

### Step 3 — Canonical skill spec audit

Every skill file must meet the [`/addyosmani/agent-skills`](https://context7.com/addyosmani/agent-skills) standard:

```
✓ Frontmatter: name + description with "Use when" trigger phrases
✓ ## When to Use
✓ ## When NOT to Use
✓ ## Core Process  (numbered workflow)
✓ ## Common Rationalizations  (excuses + rebuttals)
✓ ## Red Flags  (anti-patterns)
✓ ## Verification  (exit criteria checklist)
```

### Step 4 — Documentation hygiene

Skill files are **evergreen procedures**. Remove from any skill file:

| ✗ Remove | ✓ Where it belongs |
|---|---|
| Resolved items (`✅ done`, `PR#123 merged`) | Git history |
| Running gap tables with live issue numbers | GitHub issues |
| Session-dated entries (`2026-06-11: found X`) | Extract the timeless pattern; drop the date |
| Current PR numbers as inline state | File a GitHub issue; link from there |

The model test: *"Read this as a fresh agent with zero session context. Does it tell you how to operate — or does it make you dig through history?"*

### Step 5 — Live gaps → GitHub issues

Any gap, blocker, or open question you cannot fix this session:

```bash
gh issue create --repo castrojo/testing-lab \
  --title "infra: <what is broken>" \
  --label "bug" \
  --body "What: ...\nFix: ...\nAutomatable: yes/no"
```

**Do not append gaps to skill files.** Skill files are not backlogs.

---

## Skill directory

All skill files live in `docs/skills/`:

```
docs/skills/
├── argo-workflows.md     WorkflowTemplate authoring, lint, parameter passing
├── gitops-argocd.md      ArgoCD sync model, managed vs bootstrap distinction
├── kubevirt-vms.md       Ephemeral VM lifecycle, btrfs reflink, golden disk
├── test-authoring.md     behave + qecore + dogtail patterns, bootc contract
└── skill-improvement.md  This file — the self-learning loop
```

---

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll update the skill next session." | You won't. The loop only compounds if agents write back immediately. |
| "I already know Argo Workflows — no need for Context7." | Training data is stale. Fetch and verify before embedding examples. |
| "The skill file is good enough." | Check for Red Flags and Verification sections — most common gaps. |
| "This pattern is obvious — no need to document it." | If you found it by trial and error, it isn't obvious. Write it. |

## Red Flags

- Session ending with no skill update after discovering a non-obvious pattern
- A pattern being fixed a second time that wasn't written down after the first
- Skill files with no `## Verification` section
- Skill files covering Argo or ArgoCD with unverified code examples
- Any `docs/skills/*.md` file missing the canonical sections

## Verification

Before marking any session done:

- [ ] Skill file updated for the area worked in (or created if missing)
- [ ] Code examples verified against Context7 if the skill covers a library
- [ ] Library ID noted in `metadata.context7-sources` frontmatter
- [ ] No resolved items or dated entries left in skill files
- [ ] Any unresolved gaps filed as GitHub issues in `castrojo/testing-lab`
- [ ] Skill file has: When to Use, When NOT to Use, Core Process, Common Rationalizations, Red Flags, Verification
