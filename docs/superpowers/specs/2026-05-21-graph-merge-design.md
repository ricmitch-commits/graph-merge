# Design Spec: graph-merge

**Date:** 2026-05-21
**Status:** Approved
**Requirements:** `requirements.md`

---

## Problem Statement

Porting a bug fix from one branch or codebase to another fails when the target has diverged structurally. A fix that touches `validate_token()` in a Python auth module may need to touch `ValidateToken()` in a Go service — a string-match diff will never find that. `graph-merge` uses code knowledge graphs to reason about structural equivalence and proposes a semantically correct port of the fix, fully automated up to the PR.

---

## Approach

1. Check out the source repo at two refs (before and after the fix) and the destination repo at its base branch — all into isolated git worktrees.
2. Generate a knowledge graph for each of the three states using Graphify (vendored).
3. Diff the before/after graphs algorithmically to produce a semantic change set.
4. Use an LLM to map each changed node onto its structural equivalent in the destination graph.
5. Render a unified patch and a human-readable proposal; apply the patch to a new branch in the destination repo.
6. Print the branch name and push command. The human reviews and opens the PR.

---

## Architecture

```
graph-merge
├── cli.py                  entry point, argument parsing
├── pipeline/
│   ├── runner.py           stage orchestrator (skip if artifacts exist)
│   ├── checkout.py         stage 1 — git clone + worktree management
│   ├── graph.py            stage 2 — Graphify invocation
│   ├── diff.py             stage 3 — semantic graph diff
│   ├── mapper.py           stage 4 — LLM fix mapping
│   └── render.py           stage 5 — patch + FIX_PROPOSAL.md + branch creation
├── models/
│   └── types.py            dataclasses: GraphNode, GraphEdge, Change, Mapping
├── llm/
│   └── client.py           pluggable LLM client (Claude / Gemini / OpenAI)
├── tests/
│   └── fixtures/           two minimal git repos (Python + Go) with a known fix
└── vendor/
    └── graphify/           git submodule (pinned commit)
```

### Output Directory Layout

```
<--output>/
├── clones/
│   ├── source/             cloned if --source-repo is a URL
│   └── dest/               cloned if --dest-repo is a URL
├── worktrees/
│   ├── before/             git worktree at source-before ref
│   ├── after/              git worktree at source-after ref
│   └── dest/               git worktree at dest-base ref
├── graphs/
│   ├── before.json
│   ├── after.json
│   └── dest.json
├── semantic_diff.json      stage 3 artifact
├── mapping.json            stage 4 artifact
├── fix.patch               unified diff for destination
├── FIX_PROPOSAL.md         human-readable proposal with confidence levels
└── error.log               written on any stage failure
```

---

## Data Model

### `GraphNode` / `GraphEdge`

Graphify's `graph.json` schema is not publicly documented. On first successful graph generation, `pipeline/graph.py` infers the schema and writes it to `docs/graph_schema.md` (committed as a reference). The pipeline wraps nodes and edges in typed dataclasses:

```python
@dataclass
class GraphNode:
    id: str
    file: str
    symbol: str
    kind: str           # "function" | "class" | "variable" | "module"
    calls: list[str]    # node IDs
    imports: list[str]
    properties: dict    # anything else Graphify emits

@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str       # "calls" | "imports" | "inherits" | ...
    confidence: str     # "EXTRACTED" | "INFERRED" | "AMBIGUOUS"
```

### `semantic_diff.json`

```json
{
  "commit_message": "...",
  "changes": [
    {
      "type": "node_modified",
      "node_id": "src/auth.py::validate_token",
      "file": "src/auth.py",
      "symbol": "validate_token",
      "kind": "function",
      "before": { "calls": ["db.query"], "properties": {} },
      "after":  { "calls": ["db.query", "logger.warn"], "properties": {} },
      "rationale": "WHY comment if present"
    }
  ]
}
```

### `mapping.json`

```json
{
  "mappings": [
    {
      "source_change": { "node_id": "src/auth.py::validate_token", "type": "node_modified" },
      "destination_node": { "file": "internal/auth/service.go", "symbol": "ValidateToken" },
      "confidence": "high",
      "rationale": "Same role in call graph — validates token before DB access"
    }
  ],
  "unmappable": [
    {
      "source_change": { "node_id": "src/auth.py::TokenCache" },
      "reason": "No structural equivalent found in destination graph"
    }
  ]
}
```

Confidence is always exactly one of `high | medium | low`. The LLM is prompted to use these three values only.

---

## Stage 1: Checkout

`--source-repo` and `--dest-repo` accept either a local path or a remote git URL. If a URL is given, the tool clones into `<output>/clones/` before creating worktrees.

```python
# for each of the three states:
git -C <repo> worktree add <output>/worktrees/<label> <ref>

# cleanup via atexit handler (unless --keep-worktrees):
git -C <repo> worktree remove <output>/worktrees/<label>
```

The `atexit` handler runs for any worktree successfully created in the current run, including on crash. If `--keep-worktrees` is passed, cleanup is skipped and paths are printed at exit.

**Stage skipping:** If all three worktree directories exist, stage 1 is skipped.

---

## Stage 2: Graph Generation

Graphify is invoked via subprocess from the vendored copy. No `--backend` flag is passed — pure tree-sitter AST parsing, no code leaves the machine during this stage.

```python
subprocess.run([
    "python", "-m", "graphify.extract",
    str(worktree_path),
    "--output", str(graphs_dir / f"{label}.json"),
    "--no-html",
], check=True)
```

If Graphify does not support `--no-html`, the `graphify-out/` directory is generated and `graph.json` is moved to `graphs/<label>.json`. `GRAPH_REPORT.md` is also captured to `graphs/<label>_report.md` — stage 4 reads it to identify god nodes for context pruning.

**Stage skipping:** If all three `graphs/*.json` files exist, stage 2 is skipped.

---

## Stage 3: Semantic Diff

Pure Python — no LLM. Answers: *"What changed in the source codebase?"*

**Algorithm:**
1. Load both graphs into dicts keyed by node ID.
2. Compute: `added = after_ids - before_ids`, `removed = before_ids - after_ids`, `common = before_ids & after_ids`.
3. For nodes in `common`, compare `calls`, `imports`, and `properties` field by field. Any difference → `node_modified`.
4. For edges, repeat on `(source, target, relation)` triples.
5. Group changes sharing a file or direct call/import relationship into one `change_group` (FR-2.3).

**Node identity:** Matched by ID. If IDs are not stable across runs (discovered via schema discovery), fallback matches on `(file, symbol, kind)` tuple.

**Rationale extraction:** Node properties containing keys matching `WHY`, `HACK`, `NOTE`, or `FIXME` (case-insensitive) are copied into the change record's `rationale` field.

**Stage skipping:** If `semantic_diff.json` exists, stage 3 is skipped.

---

## Stage 4: LLM Fix Mapping

Answers: *"Where do those changes belong in the destination codebase?"* This is the only stage that calls an external service (when a cloud model is selected).

### Prompt Structure

```
You are a senior engineer porting a bug fix between two codebases.

## The Fix
<commit message or PR description if provided>

## What Changed (Semantic Diff)
<semantic_diff.json changes array, pretty-printed>

## Destination Codebase Graph
<dest.json nodes and edges, pruned — see Context Pruning below>

## Your Task
For each change in the diff, identify the structurally equivalent node
in the destination graph. Match by role in the call graph and data flow,
not by name. For each mapping output:
  - source_change: the node_id from the diff
  - destination_node: file and symbol in the destination
  - confidence: exactly one of "high" | "medium" | "low"
  - rationale: one sentence explaining the structural match

If no equivalent exists, add it to unmappable with a reason.

Respond with valid JSON only, matching this schema:
<mapping.json schema>
```

### Context Pruning

Large destination graphs are pruned before sending:
1. All nodes within 2 hops of any node whose symbol shares a token with a changed node.
2. All god nodes (highest degree centrality, flagged in Graphify's `GRAPH_REPORT.md`).
3. Hard cap: if still over `--max-context-nodes` (default 500), drop lowest-degree nodes first.

### LLM Client

`llm/client.py` wraps Anthropic / Gemini / OpenAI SDKs behind a single interface:

```python
class LLMClient:
    def complete(self, prompt: str) -> str: ...
```

`--model` format: `<provider>/<model-id>` — e.g. `claude/claude-opus-4-7`, `openai/gpt-4o`, `gemini/gemini-2.0-flash`.

### Response Parsing

If JSON parsing fails, one retry with: `"Your previous response was not valid JSON. Respond with JSON only."` If the second attempt fails, exit code 2, raw response written to `mapping_raw.txt`.

**Stage skipping:** If `mapping.json` exists, stage 4 is skipped.

---

## Stage 5: Output Rendering

### `fix.patch`

For each mapping (all confidence levels), the renderer:
1. Groups mappings by destination file to minimize LLM calls.
2. For each destination file, reads all changed source snippets (from `after/`) and the full destination file (from `dest/`).
3. Calls the LLM once per destination file with all relevant snippets and mapping rationales to produce the exact code changes.
4. Writes the result as unified diff entries for that file.

Unmappable items produce a comment block in the patch explaining what was skipped.

### `FIX_PROPOSAL.md`

```markdown
# Fix Proposal
Source: <repo> <before-ref> → <after-ref>
Destination: <repo> <dest-base>
Branch: graph-merge/port-<sha>-<timestamp>

## Summary
<commit message / PR description>

## Mappings
| Source | Destination | Confidence | Rationale |
|--------|-------------|------------|-----------|
| src/auth.py::validate_token | internal/auth/service.go::ValidateToken | high | ... |

## Unmappable Changes
- `src/auth.py::TokenCache`: No equivalent found. Reason: ...

## Next Steps
1. Review the mappings above and fix.patch
2. Test the branch: graph-merge/port-<sha>-<timestamp>
3. Push and open a PR
```

### Branch Creation

```python
subprocess.run(["git", "apply", "fix.patch"], cwd=worktrees/dest, check=False)
# fallback to --reject if apply fails partially
subprocess.run(["git", "checkout", "-b", branch_name], cwd=dest_repo)
subprocess.run(["git", "commit", "-am", f"graph-merge: port fix from {source_after_ref}"])
```

If `git apply` fails entirely, exit code 3: `fix.patch` is left on disk, manual instructions are printed. The tool never pushes or opens a PR.

**At successful exit:**
```
Branch created: graph-merge/port-a1b2c3d-20260521
To push:  git -C <dest-repo> push origin graph-merge/port-a1b2c3d-20260521
Review:   ./run-out/FIX_PROPOSAL.md
```

---

## CLI Interface

```
graph-merge \
  --source-repo        <path|url>    local path or remote git URL
  --source-before      <ref>         git ref: pre-fix state
  --source-after       <ref>         git ref: post-fix state
  --source-fix-commit  <sha>         shorthand: expands to --source-before <sha>^ --source-after <sha>
                                    mutually exclusive with --source-before / --source-after
  --dest-repo          <path|url>    local path or remote git URL
  --dest-base          <ref>         base branch/commit to create the fix branch from
  --model              <p/model>     required: e.g. claude/claude-opus-4-7
  --output             <dir>         default: ./graph-merge-out
  --commit-message     <text>        optional LLM context
  --pr-description     <file>        optional markdown file, alternative to --commit-message
  --max-context-nodes  <n>           default: 500
  --keep-worktrees                   skip worktree cleanup on exit
  --from-stage         <1-5>         resume from a specific stage
  --force-stage        <1-5>         re-run a stage even if its artifact exists
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | All stages completed, branch created |
| 1 | A required stage failed |
| 2 | LLM response unparseable after retry |
| 3 | `git apply` failed; `fix.patch` written but branch not created |

---

## Error Handling

Each stage fails fast and writes to `error.log` before exiting.

| Stage | Failure | Behavior |
|-------|---------|----------|
| 1 | Clone fails (bad URL, no auth) | Exit 1, print auth hint |
| 1 | Ref not found | Exit 1, print available branches/tags |
| 2 | Graphify non-zero exit | Exit 1, surface Graphify stderr |
| 2 | `graph.json` not produced | Exit 1, hint at flag compatibility |
| 3 | No structural changes detected | Exit 0 with warning |
| 4 | `--model` not provided | Exit 1 before any stage runs |
| 4 | LLM auth failure | Exit 1, print missing env var |
| 4 | JSON parse fails twice | Exit 2, write `mapping_raw.txt` |
| 5 | `git apply` fails | Exit 3, print manual instructions |
| 5 | All mappings unmappable | Exit 0 with warning, write `FIX_PROPOSAL.md` |

---

## Testing

| Layer | What | How |
|-------|------|-----|
| Unit | Semantic diff algorithm | Fixture graph pairs; assert expected `semantic_diff.json` |
| Unit | Context pruning | Synthetic graphs with known hop distances; assert node counts |
| Unit | CLI argument parsing | `--source-fix-commit` expansion, mutual exclusivity |
| Integration | Full pipeline | Two fixture repos under `tests/fixtures/` (Python + Go); golden-file assert on `FIX_PROPOSAL.md` structure |
| Integration | Stage skipping | Run pipeline, delete one artifact, re-run; assert skipped stages via log |
| Contract | LLM response parsing | Fixture responses (valid, invalid, partial JSON); assert retry and exit behavior |
| Contract | Graphify output | Run Graphify on fixture repo; assert dataclasses parse without error |

LLM calls in tests use a mock client returning fixture JSON — no real API calls in CI.

---

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Input refs accept any git ref (SHA, branch, tag, relative) | Passed directly to `git worktree add`; no need to restrict the format |
| 2 | `--source-fix-commit <sha>` shorthand expands to `--source-before <sha>^ --source-after <sha>` | Common case is a single commit; shorthand avoids error-prone manual SHA arithmetic |
| 3 | `--dest-ref` renamed to `--dest-base` | The flag specifies the *base* the fix branch is created from, not the final destination ref — which doesn't exist yet |
| 4 | No default LLM backend; `--model` is required | NFR-1: code must not leave the machine without explicit user opt-in |
| 5 | `--model` format is `<provider>/<model-id>` | Single flag selects both SDK and model; unambiguous, extensible |
| 6 | Graph generation uses no LLM backend (pure tree-sitter) | Graphify's AST parsing is local; avoids sending code to cloud during graph stage |
| 7 | Graphify vendored as a git submodule at `vendor/graphify/` | Pins behavior against upstream changes; submodule allows deliberate updates |
| 8 | Parse `graph.json` directly rather than via Graphify's MCP server | Full control over diff algorithm; no running daemon required; schema discovered once and committed |
| 9 | Schema discovery on first run, written to `docs/graph_schema.md` | `graph.json` format is undocumented; discovery makes the schema explicit and reviewable |
| 10 | Staged pipeline with artifact caching | Expensive steps (graph gen, LLM) can be re-run independently; aligns with NFR-4 (all intermediates on disk) |
| 11 | Stage skipping is automatic; `--from-stage` and `--force-stage` for manual control | Default UX is resume-on-rerun; explicit flags for iteration on a specific stage |
| 12 | Always emit output regardless of confidence level; annotate with `high/medium/low` | User decides whether to apply; blocking on low confidence would hinder automation |
| 13 | Stage 5 creates a branch in the destination repo with the patch applied | Full automation up to the PR; human reviews `FIX_PROPOSAL.md` and opens the PR manually |
| 14 | Tool never pushes or opens a PR | Human in the loop for the final step; avoids unreviewed changes hitting remote |
| 15 | `atexit` handler cleans up worktrees on crash | Prevents orphaned git worktrees across runs |
| 16 | LLM called twice in stage 5 (once per mapped node for code snippet) | Mapping (stage 4) reasons structurally; rendering (stage 5) reasons about actual code — different tasks, different prompts |
| 17 | Single `fix.patch` for all changes | `git apply` is the standard handoff; one file is simpler than per-change patches |
| 18 | Fixture repos in `tests/fixtures/` are Python + Go | Tests cross-language porting, which is the hardest and most representative case |
