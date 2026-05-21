# Requirements: Graph-Guided Bug Fix Porting

## Problem Statement

Porting a bug fix from one branch or codebase to another is error-prone. A fix that touches `auth.py` in one repo may need to touch `authentication/service.go` in another. Naive diff-and-apply fails when the target has diverged structurally. The goal is to use code knowledge graphs to reason about structural equivalence and propose a semantically correct port of the fix.

---

## Approach

1. Generate a knowledge graph of the **source codebase before the fix**.
2. Generate a knowledge graph of the **source codebase after the fix**.
3. Diff the two graphs to extract a **semantic change set** (which nodes/edges were added, removed, or modified).
4. Generate a knowledge graph of the **destination codebase**.
5. Map the semantic change set onto the destination graph using an LLM.
6. Produce a **proposed fix** for the destination branch: file paths, diffs, and a rationale.

---

## Functional Requirements

### FR-1: Graph Generation

| ID | Requirement |
|----|-------------|
| FR-1.1 | Accept a path to a local directory as the codebase input. |
| FR-1.2 | Generate a `graph.json` for each of the three states: source-before, source-after, destination. |
| FR-1.3 | Use Graphify (`/graphify .` or its API) to produce graphs; do not re-implement AST parsing. |
| FR-1.4 | Support at minimum Python, TypeScript, Go, Java, and Rust source files. |
| FR-1.5 | Capture node metadata: file path, symbol name, type (function, class, variable, module), and relationships (calls, imports, inherits). |

### FR-2: Semantic Diff

| ID | Requirement |
|----|-------------|
| FR-2.1 | Compute a graph diff between source-before and source-after graphs. |
| FR-2.2 | Diff output must classify each change as: node added, node removed, node modified, edge added, edge removed. |
| FR-2.3 | Group related changes into a single **change set** representing one logical fix. |
| FR-2.4 | Preserve rationale metadata extracted from comments (`# WHY:`, `# HACK:`, etc.) in the diff. |

### FR-3: Fix Mapping

| ID | Requirement |
|----|-------------|
| FR-3.1 | Submit the semantic change set and the destination graph to an LLM. |
| FR-3.2 | The LLM prompt must ask the LLM to identify equivalent nodes in the destination graph for each changed node in the source. |
| FR-3.3 | Matching must account for structural equivalence (same role in call graph, same data flow) not just name similarity. |
| FR-3.4 | Where no equivalent node exists, the LLM must flag the change as **unmappable** and explain why. |
| FR-3.5 | Support pluggable LLM backend (Claude, Gemini, OpenAI) consistent with Graphify's own model support. |

### FR-4: Proposed Fix Output

| ID | Requirement |
|----|-------------|
| FR-4.1 | Produce a unified diff (`.patch` file) for each mapped change in the destination codebase. |
| FR-4.2 | Produce a human-readable `FIX_PROPOSAL.md` that explains: what changed, where it maps, confidence level, and any unmappable items. |
| FR-4.3 | Include the original fix commit message or PR description in the proposal context. |
| FR-4.4 | Confidence levels: `high` (exact structural match), `medium` (inferred match), `low` (ambiguous). |

### FR-5: CLI Interface

| ID | Requirement |
|----|-------------|
| FR-5.1 | Provide a single CLI entry point: `graph-merge`. |
| FR-5.2 | Accept arguments: `--source-before <path>`, `--source-after <path>`, `--destination <path>`, `--output <dir>`. |
| FR-5.3 | Optionally accept `--commit-message <text>` or `--pr-description <file>` for additional fix context. |
| FR-5.4 | Support `--model <provider/model>` to select the LLM backend. |
| FR-5.5 | Exit with a non-zero code if any required graph generation step fails. |

---

## Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Code must never be sent to an external service unless the user explicitly selects a cloud LLM backend. |
| NFR-2 | Graph generation for a codebase up to 100k LOC must complete in under 5 minutes on a modern laptop. |
| NFR-3 | The tool must be runnable as a Claude Code slash command for inline use during development. |
| NFR-4 | All intermediate artifacts (graphs, diffs, prompts) must be written to the output directory for auditability. |
| NFR-5 | The tool must not modify the source or destination codebases; it is read-only until the user applies the patch. |

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
| [Graphify](https://github.com/safishamsi/graphify) | Knowledge graph generation from source code |
| tree-sitter | Local AST parsing (used internally by Graphify) |
| Claude / Gemini / OpenAI API | LLM for fix mapping and proposal generation |
| Python 3.11+ | Implementation language |

---

## Assumptions

- The bug fix is already committed; source-before and source-after are two distinct directory snapshots or git refs.
- The destination codebase is a local directory.
- The user has valid API credentials for the chosen LLM backend if using a cloud model.
- Graphify is installed and accessible on `PATH` or as a Python package.
