# Token Efficiency Optimization Design

**Date:** 2026-03-24
**Status:** Approved

---

## Problem

Analysis of the Mar 23 session (3.9 MB, ~1,400 records) identified five root causes of excessive token usage, estimated at 60–70% above optimal:

1. **Agent context fragmentation** — 10–15 subagents each reloaded codebase files from scratch instead of receiving them inline from the controller.
2. **Redundant file reads** — `base.html` and `article_card.html` were each read 5–8 times across agents and the main thread.
3. **Branch-switching cache loss** — 4–5 switches between `main` and `frontend-redesign` each cost a full context reload (40–70K tokens each).
4. **No pre-flight coordination** — no step before agent dispatch to batch-read files or plan branch usage.
5. **Post-edit re-reads** — files were re-read after editing to verify changes, adding unnecessary turns.

---

## Root Cause to Change Mapping

| Root Cause | Change(s) That Address It |
|---|---|
| 1. Agent context fragmentation | Change 1, Change 2 |
| 2. Redundant file reads | Change 1, Change 2 |
| 3. Branch-switching cache loss | Change 3 (+ Change 1 branch budget section) |
| 4. No pre-flight coordination | Change 4 (new skill) + CLAUDE.md |
| 5. Post-edit re-reads | Change 4 (step 4 of skill) + CLAUDE.md |

All five causes are covered. Root causes 4 and 5 are addressed via the pre-flight skill and CLAUDE.md rather than the skill patches, because they are habits that apply to the main thread, not agent dispatch specifically.

---

## Goals

- Eliminate redundant file reads across agent dispatches.
- Reduce branch-switch cache reloads to ≤2 per session.
- Establish a lightweight pre-flight habit before multi-agent sessions.
- Make enforcement structural (in the skills Claude uses) not just advisory.

---

## Out of Scope

- Changes to how agents are selected or how many are used — the user intentionally uses multi-agent execution.
- Changes to brainstorming or planning skills.
- Prompt summarization or tool result filtering (behavioral, not addressable via documentation).

---

## Solution: Four Changes + CLAUDE.md

### 1. Patch `subagent-driven-development/SKILL.md`

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/subagent-driven-development/SKILL.md`

Add a **Context Injection Protocol** section before "Prompt Templates". This is a required checklist: before dispatching any implementer subagent, the controller must identify all files the agent will need, read them all in one parallel batch, and embed them inline in the prompt.

**New section to add:**

```markdown
## Context Injection Protocol

**REQUIRED before every agent dispatch.** Agents must never read files themselves — the controller reads all needed files upfront and passes them inline.

### Steps
1. Identify every file the agent will read or edit
2. Read all of them now, in one parallel batch (multiple Read tool calls in one message)
3. Embed contents inline in the agent prompt:

### Prompt template

<file path="app/templates/base.html">
[full file contents here]
</file>

<file path="app/templates/partials/article_card.html">
[full file contents here]
</file>

Your task: [task description]
Constraint: Do NOT read files — all context is provided above.
```

**Red Flags change (line 241):** Replace the existing entry:
```
- Make subagent read plan file (provide full text instead)
```
with the broader:
```
- Make agents read any files themselves — read all needed files upfront and inject contents inline
```
The old entry is too narrow (plan file only). The new entry replaces it entirely.

**Also add branch switch budget here** (not only in `using-git-worktrees`, since this skill governs the whole session):
```
- Switch branches more than twice in a session — complete all worktree work before switching to main
```

---

### 2. Patch `dispatching-parallel-agents/SKILL.md`

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/dispatching-parallel-agents/SKILL.md`

Two changes in this file:

**A. Update the example prompt at line 100**, which currently reads:
```
1. Read the test file and understand what each test verifies
```
Replace with:
```
1. Review the test file (provided above) and understand what each test verifies
```

**B. Add a "Context Injection Protocol" subsection** to "Agent Prompt Structure". This mirrors the protocol in Change 1 — the controller side is identical. Rather than duplicating the full text, add a cross-reference and a condensed version:

```markdown
### Context injection (required)

Apply the same Context Injection Protocol as in `subagent-driven-development`:
1. Identify every file the agent will need
2. Read them all now in one parallel batch
3. Embed contents inline using `<file path="...">` blocks
4. Include "Do NOT read files — all context is provided above" in the prompt

The agent prompt in this skill's "Real Example from Session" section does not demonstrate file injection (it predates this rule). Treat the updated template above as the canonical pattern, not the existing example.
```

---

### 3. Patch `using-git-worktrees/SKILL.md`

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/using-git-worktrees/SKILL.md`

Add a **Branch Switch Budget** section after "Creation Steps":

```markdown
## Branch Switch Budget

Each branch switch costs a full context reload (~40–70K tokens). A session has a budget of **2 switches**:
- Switch 1: worktree → main for integration
- Switch 2: one emergency return only

Before switching to main, complete this checklist:
- [ ] All planned tasks complete
- [ ] Tests passing
- [ ] No half-finished edits

If you need a third switch, stop and assess: was integration incomplete, or is this new scope? Either way, do not proceed without a clear plan.
```

---

### 4. New skill: `superpowers:token-efficiency`

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/token-efficiency/SKILL.md`

Skills in Claude Code live inside plugins — there is no standalone `~/.claude/skills/` path. This skill is added directly to the superpowers plugin cache. It will be accessible as `superpowers:token-efficiency`.

**Risk:** The superpowers plugin cache may be overwritten on plugin update. Mitigation: the CLAUDE.md addition (below) contains a condensed version of the same rules, which is always in context and survives any plugin update. After a plugin update, reapply this skill file.

**Skill content:**

```markdown
---
name: token-efficiency
description: Pre-flight checklist before any multi-agent session or worktree-based feature work — batch reads, agent budget, branch plan
---

# Token Efficiency Pre-flight

Run this before any session involving multiple agent dispatches or worktrees.

## 1. File Audit
Identify all files that will be touched this session.
Read them ALL now in a single parallel batch (one message with multiple Read tool calls).
Do not read them again later — these reads are the only reads.

## 2. Agent Budget
Count planned agent dispatches. These thresholds are heuristic, based on observed context costs:
- ≤3 agents: proceed
- 4–7 agents: verify each is truly isolated; tasks with shared file state belong on the main thread
- >7 agents: this is likely two sessions; decompose before starting

## 3. Branch Plan
State now: which branch, one integration switch, when.
Do not switch branches mid-session unless worktree work is fully complete (all tasks done, tests passing).

## 4. No Re-reads
After editing a file, do not re-read it in full. If verification is needed, grep for the specific change.
Full re-reads after edits are the second most common source of redundant tokens.
```

---

### 5. CLAUDE.md Addition

Add a **Token Efficiency** section to `CLAUDE.md`. This is the durable safety net — always in context, survives plugin updates:

```markdown
## Token Efficiency

- Before any multi-agent session or worktree feature, invoke the `token-efficiency` skill.
- When dispatching agents (subagent-driven-development or dispatching-parallel-agents): read all files the agent will need upfront and inject them inline. Agents must never read files themselves.
- Branch switches cost a full context reload (~40–70K tokens). Budget: ≤2 per session. Complete all worktree work before switching to main.
- After editing a file, do not re-read it in full. Use grep for targeted verification only.
```

---

## Risk: Plugin Updates Overwriting Patches

Plugin cache files at `~/.claude/plugins/cache/` may be overwritten on `claude plugin update`. Mitigations:
- CLAUDE.md addition is always in context and survives any update.
- Plugin updates are infrequent. After an update, reapply skill file Changes 1–4.
- The new `token-efficiency` skill (Change 4) is the one most likely to be lost; the CLAUDE.md rules cover the same ground.

---

## Implementation Order

Steps 1–4 must complete before step 5. The CLAUDE.md addition (step 5) references the `token-efficiency` skill by name — if that skill does not exist when CLAUDE.md is updated, every invocation will fail. Steps 1–4 and step 5 must be committed atomically (single commit) or step 5 must be committed only after step 4.

1. Patch `subagent-driven-development/SKILL.md` (highest impact)
2. Patch `dispatching-parallel-agents/SKILL.md`
3. Patch `using-git-worktrees/SKILL.md`
4. Create `token-efficiency/SKILL.md` inside superpowers plugin
5. Add Token Efficiency section to `CLAUDE.md` **(must follow step 4)**
6. Commit all changes in a single commit

---

## Success Criteria

| Criterion | How to Verify |
|---|---|
| Agents receive files inline | In session `.jsonl` log: no `tool_use` records with `name: Read` from subagent contexts |
| ≤2 branch switches per session | Session log: count `worktree` branch change events |
| No full re-reads after edits | Session log: no `Read` tool call on the same path after an `Edit` on that path in the same turn sequence |
| Token reduction 50–65% | Session `.jsonl` file size as proxy (Mar 23 baseline: 3.9 MB); a comparable multi-agent frontend session should be ≤2 MB |
