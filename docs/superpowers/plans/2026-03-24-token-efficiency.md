# Token Efficiency Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant file reads and branch-switch cache reloads in multi-agent Claude Code sessions by patching three existing skill files, creating one new skill, and adding enforcement rules to CLAUDE.md.

**Architecture:** Five targeted file edits. No code — all changes are to Markdown skill files and CLAUDE.md. The plugin skills live in `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/`. Tasks 1–4 must complete before Task 5 (CLAUDE.md references the new skill by name).

**Tech Stack:** Markdown, Claude Code plugin system (superpowers v5.0.5)

---

## File Map

| File | Change |
|---|---|
| `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/subagent-driven-development/SKILL.md` | Add Context Injection Protocol section + update Red Flags |
| `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/dispatching-parallel-agents/SKILL.md` | Fix line 100 example + add Context Injection subsection |
| `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/using-git-worktrees/SKILL.md` | Add Branch Switch Budget section |
| `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/token-efficiency/SKILL.md` | Create new file |
| `/home/etor/code/dossier/CLAUDE.md` | Add Token Efficiency section |

---

## Task 1: Patch subagent-driven-development — Context Injection Protocol

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/subagent-driven-development/SKILL.md`

This is the highest-impact change. The skill currently has advisory text about providing context to agents but no structural enforcement. We add a mandatory protocol section and strengthen two Red Flags entries.

- [ ] **Step 1: Read the current state around the insertion points**

  Read lines 115–130 (around `## Prompt Templates`) and lines 235–250 (around the Red Flags list) to confirm exact text before editing.

  ```bash
  # Confirm line 120 is "## Prompt Templates"
  grep -n "Prompt Templates\|Make subagent read plan" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/subagent-driven-development/SKILL.md
  ```

  Expected output includes:
  ```
  120:## Prompt Templates
  241:- Make subagent read plan file (provide full text instead)
  ```

- [ ] **Step 2: Insert the Context Injection Protocol section before `## Prompt Templates`**

  Insert the following block immediately before the `## Prompt Templates` line (line 120):

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

- [ ] **Step 3: Replace the narrow Red Flags entry**

  Find the existing entry:
  ```
  - Make subagent read plan file (provide full text instead)
  ```

  Replace it with:
  ```
  - Make agents read any files themselves — read all needed files upfront and inject contents inline
  ```

- [ ] **Step 4: Add the branch switch Red Flag**

  In the same Red Flags list, add after the entry updated in Step 3:
  ```
  - Switch branches more than twice in a session — complete all worktree work before switching to main
  ```

- [ ] **Step 5: Verify all three changes are present**

  ```bash
  grep -n "Context Injection Protocol\|inject contents inline\|Switch branches more than twice" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/subagent-driven-development/SKILL.md
  ```

  Expected: three matching lines. If any are missing, re-apply the missing edit.

- [ ] **Step 6: Confirm the old narrow Red Flags entry is gone**

  ```bash
  grep -n "Make subagent read plan file" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/subagent-driven-development/SKILL.md
  ```

  Expected: no output. If the old entry still appears, remove it.

---

## Task 2: Patch dispatching-parallel-agents — Fix example + add injection subsection

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/dispatching-parallel-agents/SKILL.md`

Two edits: fix the example prompt that instructs agents to read files, and add a controller-side injection subsection.

- [ ] **Step 1: Confirm the current state of line 100 and the Agent Prompt Structure section**

  ```bash
  grep -n "Read the test file\|Agent Prompt Structure\|Common Mistakes" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/dispatching-parallel-agents/SKILL.md
  ```

  Expected output includes:
  ```
  84:## Agent Prompt Structure
  100:1. Read the test file and understand what each test verifies
  112:## Common Mistakes
  ```

- [ ] **Step 2: Replace the file-reading instruction at line 100**

  Find:
  ```
  1. Read the test file and understand what each test verifies
  ```

  Replace with:
  ```
  1. Review the test file (provided above) and understand what each test verifies
  ```

- [ ] **Step 3: Add the Context Injection subsection before `## Common Mistakes`**

  Insert the following block immediately before the `## Common Mistakes` line:

  ```markdown
  ### Context injection (required)

  Apply the same Context Injection Protocol as in `subagent-driven-development`:
  1. Identify every file the agent will need
  2. Read them all now in one parallel batch
  3. Embed contents inline using `<file path="...">` blocks
  4. Include "Do NOT read files — all context is provided above" in the prompt

  The agent prompt in this skill's "Real Example from Session" section does not demonstrate file injection (it predates this rule). Treat the updated template above as the canonical pattern, not the existing example.

  ```

- [ ] **Step 4: Verify both changes**

  ```bash
  grep -n "provided above\|Context injection (required)\|predates this rule" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/dispatching-parallel-agents/SKILL.md
  ```

  Expected: three matching lines.

- [ ] **Step 5: Confirm old instruction is gone**

  ```bash
  grep -n "Read the test file and understand" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/dispatching-parallel-agents/SKILL.md
  ```

  Expected: no output.

---

## Task 3: Patch using-git-worktrees — Branch Switch Budget

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/using-git-worktrees/SKILL.md`

Add a Branch Switch Budget section between "Creation Steps" and "Quick Reference".

- [ ] **Step 1: Confirm the insertion point**

  ```bash
  grep -n "Quick Reference\|Common Mistakes\|Example Workflow" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/using-git-worktrees/SKILL.md
  ```

  Expected:
  ```
  144:## Quick Reference
  156:## Common Mistakes
  178:## Example Workflow
  ```

- [ ] **Step 2: Insert Branch Switch Budget section before `## Quick Reference`**

  Insert the following block immediately before the `## Quick Reference` line:

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

- [ ] **Step 3: Verify the section is present**

  ```bash
  grep -n "Branch Switch Budget\|40–70K tokens\|emergency return" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/using-git-worktrees/SKILL.md
  ```

  Expected: three matching lines.

---

## Task 4: Create token-efficiency skill

**Files:**
- Create: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/token-efficiency/SKILL.md`

This is a new pre-flight skill. Must be created before Task 5 (CLAUDE.md references it by name).

- [ ] **Step 1: Create the directory**

  ```bash
  mkdir -p ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/token-efficiency
  ```

- [ ] **Step 2: Create SKILL.md**

  Create `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/token-efficiency/SKILL.md` with this exact content:

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

- [ ] **Step 3: Verify the file exists and has the correct frontmatter**

  ```bash
  grep -n "name: token-efficiency\|description:\|File Audit\|Agent Budget\|Branch Plan\|No Re-reads" \
    ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.5/skills/token-efficiency/SKILL.md
  ```

  Expected: six matching lines (name, description, and the four section headers).

---

## Task 5: Add Token Efficiency section to CLAUDE.md

**Files:**
- Modify: `/home/etor/code/dossier/CLAUDE.md`

Add a Token Efficiency section after "What Claude Gets Wrong on This Stack". This is the durable safety net — always in context, survives plugin updates. Must be done after Task 4.

- [ ] **Step 1: Confirm the insertion point**

  ```bash
  grep -n "What Claude Gets Wrong\|Content Sourcing" /home/etor/code/dossier/CLAUDE.md
  ```

  Expected:
  ```
  106:## What Claude Gets Wrong on This Stack
  119:## Content Sourcing
  ```

  The new section goes between them (after the `---` separator at line 117).

- [ ] **Step 2: Insert the Token Efficiency section**

  Find the text block (the `---` separator followed by `## Content Sourcing`):
  ```
  ---

  ## Content Sourcing
  ```

  Replace with:
  ```
  ---

  ## Token Efficiency

  - Before any multi-agent session or worktree feature, invoke the `token-efficiency` skill.
  - When dispatching agents (subagent-driven-development or dispatching-parallel-agents): read all files the agent will need upfront and inject them inline. Agents must never read files themselves.
  - Branch switches cost a full context reload (~40–70K tokens). Budget: ≤2 per session. Complete all worktree work before switching to main.
  - After editing a file, do not re-read it in full. Use grep for targeted verification only.

  ---

  ## Content Sourcing
  ```

- [ ] **Step 3: Verify the section is present**

  ```bash
  grep -n "Token Efficiency\|token-efficiency\|inject them inline\|≤2 per session" \
    /home/etor/code/dossier/CLAUDE.md
  ```

  Expected: four matching lines.

- [ ] **Step 4: Commit all five changes in a single commit**

  ```bash
  git -C /home/etor/code/dossier add CLAUDE.md
  git -C /home/etor/code/dossier commit -m "feat(claude): add token efficiency rules and skill patches

  - Add Context Injection Protocol to subagent-driven-development skill
  - Fix file-reading example + add injection subsection to dispatching-parallel-agents skill
  - Add Branch Switch Budget section to using-git-worktrees skill
  - Create new superpowers:token-efficiency pre-flight skill
  - Add Token Efficiency section to CLAUDE.md

  Estimated 50-65% token reduction in multi-agent sessions."
  ```

  Note: The skill file changes are in `~/.claude/` (outside this git repo) and don't need to be staged. Only `CLAUDE.md` is committed.

- [ ] **Step 5: Verify the commit**

  ```bash
  git -C /home/etor/code/dossier log --oneline -3
  ```

  Expected: the new commit appears at the top.
