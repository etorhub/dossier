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

## Solution: Four Changes

### 1. Patch `subagent-driven-development/SKILL.md`

Add a **Context Injection Protocol** section before "Prompt Templates". This is a required checklist: before dispatching any implementer subagent, the controller must identify all files the agent will need, read them all in one parallel batch, and embed them inline in the prompt.

**Prompt template to add:**

```
<file path="path/to/file.ext">
[full file contents]
</file>

Your task: [description]
Constraint: Do NOT read files — all context is provided above.
```

Add to "Red Flags / Never" list:
- `Make the agent read files — inject all contents upfront`

**Why this is the highest-impact change:** agents reading files themselves was the single largest contributor to token waste. The skill already has a note about this in the Advantages section ("No file reading overhead — controller provides full text") but it is not enforced.

---

### 2. Patch `dispatching-parallel-agents/SKILL.md`

Add a **Context injection (required)** subsection to "Agent Prompt Structure":

```
Read all files the agent will need before dispatch. Embed them inline.
Never instruct the agent to read files — they lose the benefit of your context.
```

Same principle as patch 1, applied to the parallel dispatch workflow.

---

### 3. Patch `using-git-worktrees/SKILL.md`

Add a **Branch Switch Budget** section:

- A session budget of **2 branch switches**: worktree → main for integration, and one emergency return.
- Before switching to main, complete a checklist: all tasks done, tests passing, no half-finished edits.
- If a third switch is needed, stop and evaluate: was integration incomplete, or is this new scope?
- Surface the cost explicitly: each switch causes a full context reload (~40–70K tokens).

---

### 4. New local skill: `token-efficiency`

A global pre-flight skill at `~/.claude/skills/token-efficiency/SKILL.md`.

Invoked at the start of any session involving multiple agents or worktrees. Contains four steps:

1. **File Audit** — identify all files that will be touched; read them all now in one parallel batch.
2. **Agent Budget** — ≤3 agents: proceed; 4–7: confirm isolation; >7: split into two sessions.
3. **Branch Plan** — write down the branch, the one integration switch, and when it happens.
4. **No Re-reads** — after editing, do not re-read the full file. Use grep for targeted verification only.

This skill survives plugin updates and serves as the safety net when the patched skills are overwritten.

---

## Risk: Plugin Updates Overwriting Patches

Plugin cache files at `~/.claude/plugins/cache/` are managed by the plugin system and may be overwritten on update. Mitigations:

- The local `token-efficiency` skill is outside the plugin cache and always survives.
- The CLAUDE.md addition (see below) points to the skill, ensuring it stays in context.
- Patches should be reapplied after plugin updates. This is low-frequency (plugin updates are rare).

---

## CLAUDE.md Addition

Add a short "Token Efficiency" section to `CLAUDE.md`:

```markdown
## Token Efficiency

- Before any multi-agent session, invoke the `token-efficiency` skill.
- When dispatching agents (subagent-driven-development or dispatching-parallel-agents): read all files the agent will need upfront and inject them inline into the prompt. Agents must never read files themselves.
- Branch switches cost a full context reload. Complete worktree work fully before switching to main.
- After editing a file, do not re-read it. If verification is needed, grep for the specific change.
```

---

## Implementation Order

1. Create local skill `~/.claude/skills/token-efficiency/SKILL.md`
2. Patch `subagent-driven-development/SKILL.md`
3. Patch `dispatching-parallel-agents/SKILL.md`
4. Patch `using-git-worktrees/SKILL.md`
5. Add Token Efficiency section to `CLAUDE.md`
6. Commit all changes

---

## Success Criteria

- Agents dispatched with all needed file contents inline; zero "read the file yourself" instructions.
- Sessions involving worktrees complete with ≤2 branch switches.
- No full file re-reads after edits.
- Estimated token reduction: 50–65% on comparable multi-agent sessions.
