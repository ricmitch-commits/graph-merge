# Requirements: Graph-Guided Bug Fix Porting

## Problem Statement

Porting a bug fix from one branch or codebase to another is error-prone and time consuming. A fix that touches `auth.py` in one repo may need to touch `authentication/service.go` in another. Naive diff-and-apply fails when the target has diverged structurally. The goal is to reason about structural equivalence across codebases and propose a semantically correct port of the fix.

A single bug may exist across many active branches simultaneously — both older release branches (requiring backports) and newer feature branches (requiring forward ports). Each branch may use different symbol names, file layouts, or call structures for the same logical component. The tool must discover all affected branches, resolve symbols across them, and produce a correct proposed fix for each.

---

## Approach

1. Produce a semantic model of the **source codebase before the fix**.
2. Produce a semantic model of the **source codebase after the fix**.
3. Diff the two models to extract a **semantic change set** (which symbols and relationships were added, removed, or modified).
4. **Enumerate all active branches** in the repository and determine which contain the vulnerable code using semantic signature matching.
5. For each affected branch, produce a semantic model of that **destination codebase**.
6. **Resolve symbols cross-branch**: map source symbol identities to their equivalents in each destination branch, accounting for renames, refactors, and structural drift.
7. Submit the semantic change set, the destination model, and resolved symbol mappings to an LLM.
8. Produce a **proposed fix** for each destination branch: file paths, diffs, and a rationale.
9. Append an entry to a **fix log** recording the target branch, a summary of what was changed, and the risk level of the port.

---

## Functional Requirements

### FR-1: Code Analysis

| ID | Requirement |
|----|-------------|
| FR-1.1 | Accept a path to a local directory as the codebase input. |
| FR-1.2 | Produce a semantic model for each of the three states: source-before, source-after, and each destination branch. |
| FR-1.3 | Support at minimum Python, TypeScript, Go, Java, and Rust source files. |
| FR-1.4 | Capture symbol metadata: file path, symbol name, type (function, class, variable, module), and relationships (calls, imports, inherits). |

### FR-2: Semantic Diff

| ID | Requirement |
|----|-------------|
| FR-2.1 | Compute a semantic diff between the source-before and source-after models. |
| FR-2.2 | Diff output must classify each change as: symbol added, symbol removed, symbol modified, relationship added, relationship removed. |
| FR-2.3 | Group related changes into a single **change set** representing one logical fix. |
| FR-2.4 | Preserve rationale metadata extracted from comments (`# WHY:`, `# HACK:`, etc.) in the diff. |

### FR-3: Fix Mapping

| ID | Requirement |
|----|-------------|
| FR-3.1 | Submit the semantic change set and the destination model to an LLM per affected branch. |
| FR-3.2 | The LLM prompt must ask the LLM to identify equivalent symbols in the destination codebase for each changed symbol in the source. |
| FR-3.3 | Matching must account for structural equivalence (same role in call structure, same data flow) not just name similarity. |
| FR-3.4 | Where no equivalent symbol exists, the LLM must flag the change as **unmappable** and explain why. |
| FR-3.5 | Support pluggable LLM backend (Claude, Gemini, OpenAI). |

### FR-4: Proposed Fix Output

| ID | Requirement |
|----|-------------|
| FR-4.1 | Produce a unified diff (`.patch` file) for each mapped change in each destination branch. |
| FR-4.2 | Produce a human-readable `FIX_PROPOSAL.md` per branch that explains: what changed, where it maps, confidence level, risk level with a plain-language justification, and any unmappable items. |
| FR-4.3 | Include the original fix commit message or PR description in the proposal context. |
| FR-4.4 | Confidence levels: `high` (exact structural match), `medium` (inferred match), `low` (ambiguous). |
| FR-4.5 | Produce a top-level `BRANCH_SUMMARY.md` listing all affected branches, their porting direction (backport or forward port), per-branch confidence, and risk level. |
| FR-4.6 | Derive a port risk level for each branch: `low` (all changes map at high confidence with no unmappable items), `medium` (any change maps at medium confidence, or structural drift required LLM-assisted symbol resolution), `high` (any change maps at low confidence, any unmappable items are present, or the branch has diverged significantly from the source). |
| FR-4.7 | Append one entry per branch to a `fix.log` file in the output directory. Each entry must record: timestamp, target branch name, porting direction (backport or forward port), a concise description of what was changed, and the risk level. The log must be human-readable and appendable across multiple runs. |

### FR-5: CLI Interface

| ID | Requirement |
|----|-------------|
| FR-5.1 | Provide a single CLI entry point: `graph-merge`. |
| FR-5.2 | Accept arguments: `--source-before <path>`, `--source-after <path>`, `--destination <path>`, `--output <dir>`. |
| FR-5.3 | Optionally accept `--commit-message <text>` or `--pr-description <file>` for additional fix context. |
| FR-5.4 | Support `--model <provider/model>` to select the LLM backend. |
| FR-5.5 | Exit with a non-zero code if any required analysis step fails. |
| FR-5.6 | Accept `--repo <path>` to point at a git repository; when provided, enable multi-branch mode (see FR-6). |
| FR-5.7 | Accept `--branches <branch1,branch2,...>` to manually specify destination branches; when omitted in multi-branch mode, branches are auto-discovered (FR-6.1). |
| FR-5.8 | Accept `--direction <backport\|forward\|both>` (default: `both`) to restrict porting to branches older or newer than the source. |

### FR-6: Multi-Branch Discovery and Porting

| ID | Requirement |
|----|-------------|
| FR-6.1 | When operating in multi-branch mode, enumerate all active remote branches in the target repository. |
| FR-6.2 | For each branch, check out or snapshot the codebase at that branch ref without modifying the working tree. |
| FR-6.3 | Determine whether a branch contains the vulnerable code by matching the semantic signature of the pre-fix change set against the branch's semantic model. A branch is considered affected if the structural pattern of changed symbols is present. |
| FR-6.4 | Classify each affected branch as requiring a **backport** (branch diverged before the fix was introduced) or a **forward port** (branch diverged after the fix was introduced but does not include it), based on merge-base analysis. |
| FR-6.5 | Skip branches that already contain the fix (i.e., the post-fix structural signature is already present in the branch model). |
| FR-6.6 | Skip branches that have been archived, deleted, or marked stale (no commits in the last 90 days by default; configurable via `--stale-threshold <days>`). |
| FR-6.7 | Produce one output subdirectory per affected branch under `--output`, named by sanitized branch name. |
| FR-6.8 | Process destination branches in parallel where analysis and LLM calls permit; respect a `--concurrency <n>` limit (default: 4). |

### FR-7: Cross-Branch Symbol Resolution

| ID | Requirement |
|----|-------------|
| FR-7.1 | Before submitting to the LLM, resolve each source symbol to its counterpart in the destination branch using a multi-pass strategy. |
| FR-7.2 | **Pass 1 — Exact match**: locate symbols with identical qualified name and type in the destination codebase. |
| FR-7.3 | **Pass 2 — Rename detection**: if exact match fails, compare call-neighborhood fingerprints (callers, callees, depth-2 neighbors) to find structurally equivalent symbols with different names. |
| FR-7.4 | **Pass 3 — LLM-assisted resolution**: if neighborhood fingerprinting yields no confident match (score below a configurable threshold), submit the unresolved symbol with its source context and the candidate symbols from the destination codebase to the LLM for disambiguation. |
| FR-7.5 | Record the resolution pass that produced each mapping (`exact`, `structural`, `llm`) in the output artifacts for auditability. |
| FR-7.6 | When a symbol has been split into multiple symbols in the destination branch, record a one-to-many mapping and include all candidate sites in the proposed fix. |
| FR-7.7 | When multiple source symbols have been merged into one in the destination branch, record a many-to-one mapping and deduplicate patch hunks before output. |
| FR-7.8 | Expose `--symbol-threshold <0.0–1.0>` (default: `0.75`) to tune the minimum fingerprint similarity score required before falling back to LLM resolution. |

---

## Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Code must never be sent to an external service unless the user explicitly selects a cloud LLM backend. |
| NFR-2 | Code analysis for a codebase up to 100k LOC must complete in under 5 minutes on a modern laptop. |
| NFR-3 | The tool must be runnable as a Claude Code slash command for inline use during development. |
| NFR-4 | All intermediate artifacts (semantic models, diffs, prompts, symbol resolution tables) must be written to the output directory for auditability. |
| NFR-5 | The tool must not modify the source or destination codebases; it is read-only until the user applies the patch. |
| NFR-6 | In multi-branch mode, total wall-clock time must not exceed 3× the single-branch time when processing up to 10 branches concurrently on a modern laptop. |

---

## Out of Scope

- Automatically applying the patch (user applies manually via `git apply`).
- Multi-commit or multi-bug fix porting in a single run.
- Resolving merge conflicts in the destination branch before porting.
- IDE plugin or UI; CLI only for v1.

---

## Dependencies

| Dependency | Role |
|------------|------|
| Claude / Gemini / OpenAI API | LLM for fix mapping, symbol resolution, and proposal generation |
| Python 3.11+ | Implementation language |
| GitPython or `pygit2` | Branch enumeration, ref checkout, and merge-base analysis |

---

## Assumptions

- The bug fix is already committed; source-before and source-after are two distinct directory snapshots or git refs.
- The destination codebase(s) are local directories or refs within the same git repository.
- The user has valid API credentials for the chosen LLM backend if using a cloud model.
- In multi-branch mode, the user has fetch access to all remote refs they wish to target.
