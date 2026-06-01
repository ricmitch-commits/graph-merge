# Design Spec: graph-merge

**Date:** 2026-05-21
**Revised:** 2026-06-01
**Status:** Approved
**Requirements:** `requirements.md`

---

## Problem Statement

Porting a bug fix from one branch or codebase to another fails when the target has diverged structurally. A fix that touches `validate_token()` in a Python auth module may need to touch `ValidateToken()` in a Go service — a string-match diff will never find that. `graph-merge` uses code knowledge graphs to reason about structural equivalence and proposes a semantically correct port of the fix, fully automated up to the PR.

---

## Approach

1. Check out the source repo at two refs (before and after the fix) and the destination repo at its base branch — all into isolated git worktrees.
2. Generate a knowledge graph for each of the three states using Graphify (vendored as a git submodule, invoked as a black-box subprocess).
3. Diff the before/after graphs algorithmically to produce a semantic change set.
4. Use an LLM to map each changed node onto its structural equivalent in the destination graph.
5. Render a unified patch and a human-readable proposal; apply the patch to a new branch in the destination repo.
6. Print the branch name and push command. The human reviews and opens the PR.

---

## Architecture

```
graph-merge
├── cli.py                      entry point — arg parsing, validate_args(), args_to_config()
├── pipeline/
│   ├── runner.py               stage orchestrator; artifacts_exist(); error.log; _NoChanges
│   ├── checkout.py             stage 1 — _ensure_local(), _add_worktree(), atexit cleanup
│   ├── graph.py                stage 2 — generate_graph(), load_graph(), discover_and_write_schema()
│   ├── diff.py                 stage 3 — compute_semantic_diff(), _build_fallback_id_map()
│   ├── pruning.py              context pruning — prune_graph(), load_god_nodes(), _bfs()
│   ├── mapper.py               stage 4 — run_mapping(), _parse_mapping_response()
│   └── render.py               stage 5 — run_render(), generate_patch_content(), build_fix_proposal()
├── models/
│   ├── types.py                GraphNode, GraphEdge, Change, SemanticDiff, Mapping, MappingResult, ...
│   └── config.py               Config dataclass (all parsed CLI args + computed paths)
├── llm/
│   ├── client.py               LLMClient Protocol, MockLLMClient, create_client() factory
│   ├── anthropic_client.py     AnthropicClient
│   ├── openai_client.py        OpenAIClient
│   └── gemini_client.py        GeminiClient
├── tests/
│   ├── unit/                   test_types, test_cli, test_diff, test_pruning, test_graph_loading,
│   │                           test_runner, test_render, test_llm_client, test_checkout
│   ├── integration/            test_pipeline (BDD Given/When/Then), conftest with fixture repos
│   ├── contract/               test_llm_parsing, test_graphify_output (skipped if Graphify absent)
│   └── fixtures/
│       ├── graphs/             before.json, after.json, dest.json
│       └── responses/          mapping_valid.json, mapping_invalid.json
└── vendor/graphify/            git submodule (pinned commit)
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
│   ├── dest.json
│   └── dest_report.md      GRAPH_REPORT.md from Graphify (god node identification)
├── semantic_diff.json      stage 3 artifact
├── mapping.json            stage 4 artifact
├── mapping_raw.txt         written only if LLM response fails JSON parsing twice
├── fix.patch               unified diff for destination
├── FIX_PROPOSAL.md         human-readable proposal with confidence levels
└── error.log               written on any stage failure
```

---

## Data Model

### `models/types.py`

```python
@dataclass
class GraphNode:
    id: str
    file: str
    symbol: str
    kind: str           # "function" | "class" | "variable" | "module"
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str       # "calls" | "imports" | "inherits" | ...
    confidence: str     # "EXTRACTED" | "INFERRED" | "AMBIGUOUS"

@dataclass
class Change:
    type: str           # "node_added" | "node_removed" | "node_modified"
                        # | "edge_added" | "edge_removed"
    node_id: str | None = None
    file: str | None = None
    symbol: str | None = None
    kind: str | None = None
    before: dict | None = None
    after: dict | None = None
    rationale: str | None = None
    edge: GraphEdge | None = None   # populated for edge_added / edge_removed

@dataclass
class SemanticDiff:
    commit_message: str
    changes: list[Change] = field(default_factory=list)

@dataclass
class SourceChange:
    node_id: str
    type: str = ""

@dataclass
class DestinationNode:
    file: str
    symbol: str

@dataclass
class Mapping:
    source_change: SourceChange
    destination_node: DestinationNode
    confidence: str     # "high" | "medium" | "low"
    rationale: str

@dataclass
class UnmappableChange:
    source_change: SourceChange
    reason: str

@dataclass
class MappingResult:
    mappings: list[Mapping] = field(default_factory=list)
    unmappable: list[UnmappableChange] = field(default_factory=list)
```

### `models/config.py`

```python
@dataclass
class Config:
    source_repo: str
    source_before: str
    source_after: str
    dest_repo: str
    dest_base: str
    model: str
    output_dir: Path
    commit_message: str
    max_context_nodes: int
    keep_worktrees: bool
    from_stage: int | None
    force_stage: int | None
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
      "rationale": "Log invalid token attempts for audit trail"
    }
  ]
}
```

Edge-type changes serialize `GraphEdge` inline:

```json
{
  "type": "edge_added",
  "edge": { "source": "src/auth.py::validate_token", "target": "logger.warn",
            "relation": "calls", "confidence": "EXTRACTED" }
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

`--source-repo` and `--dest-repo` accept either a local path or a remote git URL. `_ensure_local` detects URLs by prefix (`http`, `git@`) and clones into `<output>/clones/` if needed; local paths are returned as-is.

```python
def _add_worktree(repo: Path, path: Path, ref: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(path), ref],
        check=True, capture_output=True,
    )
```

Three worktrees are created: `before`, `after`, `dest`. If any `_add_worktree` call fails, already-created worktrees are removed before the exception propagates.

**Cleanup:** An `atexit` handler removes all worktrees created in the current run, including on crash. If `--keep-worktrees` is passed, the handler is not registered and paths are printed at exit.

**Stage skipping:** If all three worktree directories exist, stage 1 is skipped.

---

## Stage 2: Graph Generation

Graphify is invoked via subprocess from the vendored copy. It is treated as a black-box: only `graph.json` and `GRAPH_REPORT.md` outputs are consumed.

```python
def generate_graph(worktree_path: Path, output_path: Path, label: str) -> None:
    # Primary: --no-html suppresses HTML output
    result = subprocess.run(
        ["python", "-m", "graphify.extract", str(worktree_path),
         "--output", str(output_path), "--no-html"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return

    # Fallback: --no-html not supported; Graphify writes to graphify-out/
    if "--no-html" in result.stderr or "unrecognized arguments" in result.stderr:
        result2 = subprocess.run(
            ["python", "-m", "graphify.extract", str(worktree_path)],
            capture_output=True, text=True, cwd=worktree_path,
        )
        if result2.returncode != 0:
            raise RuntimeError(f"Graphify failed:\n{result2.stderr}")
        src = worktree_path / "graphify-out" / "graph.json"
        if not src.exists():
            raise RuntimeError("Graphify ran but did not produce graph.json")
        shutil.copy(src, output_path)
        report_src = worktree_path / "graphify-out" / "GRAPH_REPORT.md"
        if report_src.exists():
            shutil.copy(report_src, output_path.parent / f"{label}_report.md")
    else:
        raise RuntimeError(f"Graphify failed:\n{result.stderr}")
```

**Graph loading** (`load_graph`): normalizes graphify output regardless of whether nodes are emitted as a `dict` (keyed by ID) or a `list` (each item has an `id` field). Both formats are normalized to `dict[str, GraphNode]`. Known fields consumed: `id`, `file`, `symbol`/`name`, `kind`/`type`, `calls`, `imports`. All other fields are captured in `properties`.

**Schema discovery:** On first successful run, `discover_and_write_schema()` infers node and edge fields from the actual output and writes `docs/graph_schema.md`. Called once from `runner._stage2` after graph generation; skipped if the file already exists.

**Stage skipping:** If all three `graphs/*.json` files exist, stage 2 is skipped.

---

## Stage 3: Semantic Diff

Pure Python — no LLM. Answers: *"What changed in the source codebase?"*

**Algorithm:**
1. Load both graphs into dicts keyed by node ID.
2. Run `_build_fallback_id_map` to remap unstable before-IDs to their after equivalents.
3. Compute: `added = after_ids - before_ids`, `removed = before_ids - after_ids`, `common = before_ids & after_ids`.
4. For nodes in `common`, compare `calls`, `imports`, and `properties` field by field. Any difference → `node_modified`.
5. For edges, repeat on `(source, target, relation)` triples → `edge_added` / `edge_removed`.

**Fallback ID matching** (`_build_fallback_id_map`): before diffing, builds a `dict[before_id → after_id]` for nodes where IDs differ but `(file, symbol, kind)` matches. Runs unconditionally — is a no-op (empty dict) when IDs are stable. Prevents graphify non-deterministic IDs from producing spurious `node_removed` + `node_added` pairs.

**Rationale extraction:** `_RATIONALE_KEYS = {"why", "hack", "note", "fixme"}`. Node `properties` keys matching any entry (case-insensitive) are copied into `Change.rationale`.

**`_NoChanges` exit path:** if `compute_semantic_diff` returns zero changes, `runner._stage3` raises `_NoChanges` (private exception class). The runner catches it, prints a warning, and exits 0. This is not an error — it means the two refs are semantically identical.

**Serialization:** `semantic_diff.json` is written by the runner, not by `diff.py`. `Change` objects with a non-None `edge` field serialize `vars(c.edge)` as a nested dict.

**Stage skipping:** If `semantic_diff.json` exists, stage 3 is skipped.

---

## Stage 4: LLM Fix Mapping

Answers: *"Where do those changes belong in the destination codebase?"* This is the only stage that calls an external service (when a cloud model is selected).

### `run_mapping` signature

```python
def run_mapping(
    semantic_diff: SemanticDiff,
    dest_nodes: dict[str, GraphNode],
    dest_edges: list[GraphEdge],
    fix_context: str,
    llm_client: LLMClient,
    output_dir: Path,
    max_context_nodes: int = 500,
) -> MappingResult
```

### Context Pruning (delegated to `pipeline/pruning.py`)

1. Extract `changed_symbols` from all `Change` objects with a non-None `symbol`.
2. `load_god_nodes(output_dir / "graphs" / "dest_report.md")` — parses `GRAPH_REPORT.md` for lines containing "god node" or "highest degree"; extracts backtick-quoted symbol names. Returns empty set if file absent.
3. `prune_graph(dest_nodes, dest_edges, changed_symbols, god_nodes, max_context_nodes)`:
   - `_tokenize(symbol)` splits camelCase, PascalCase, and snake_case into lowercase tokens; filters tokens shorter than 2 chars.
   - Seed nodes: destination nodes whose symbol shares at least one token with any changed symbol.
   - Expand 2 hops via BFS over the bidirectional adjacency graph (`_bfs`).
   - Remove god nodes from result.
   - If still over `max_context_nodes`, drop lowest-degree nodes first.

### Prompt Structure

```
You are a senior engineer porting a bug fix between two codebases.

## The Fix
<commit message or PR description if provided>

## What Changed (Semantic Diff)
<semantic_diff.json changes array, pretty-printed>

## Destination Codebase Graph
<dest.json nodes and edges, pruned>

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

### Response Parsing (`_parse_mapping_response`)

```python
def _parse_mapping_response(
    response: str,
    llm_client: LLMClient,
    raw_path: Path | None = None,
) -> MappingResult
```

- Attempt `json.loads(response)` → build `MappingResult`.
- On `JSONDecodeError`: send one retry prompt: `"Your previous response was not valid JSON. Respond with JSON only.\n" + response`.
- On second `JSONDecodeError`: write raw response to `mapping_raw.txt` (if `raw_path` provided), raise `ValueError("LLM response unparseable after retry")` → runner catches as exit code 2.

### LLM Client

`llm/client.py` defines the `LLMClient` Protocol, `MockLLMClient`, and `create_client()` factory. Provider SDK imports are lazy — each provider module is imported only when its prefix is matched.

```python
class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...
```

`--model` format: `<provider>/<model-id>` — e.g. `claude/claude-opus-4-6`, `openai/gpt-4o`, `gemini/gemini-2.0-flash`.

**Stage skipping:** If `mapping.json` exists, stage 4 is skipped.

---

## Stage 5: Output Rendering

### `generate_patch_content`

```python
def generate_patch_content(
    mapping_result: MappingResult,
    worktrees: dict[str, Path],
    llm_client: LLMClient,
) -> dict[str, str]   # dest_file → new file content
```

Groups mappings by destination file. For each file: reads the full destination file from `worktrees["dest"]` and source snippets from `worktrees["after"]` (resolved from `node_id` via `file::symbol` split). Calls the LLM once per destination file requesting only the modified file content (no markdown fences, no explanation). Returns new file contents — not diffs.

### `run_render`

```python
def run_render(
    mapping_result: MappingResult,
    worktrees: dict[str, Path],
    dest_repo_path: Path,
    source_after_ref: str,
    llm_client: LLMClient,
    output_dir: Path,
) -> str   # branch name
```

1. Calls `generate_patch_content` → writes new file contents into `worktrees["dest"]`.
2. Runs `git diff` in `worktrees["dest"]` to capture the unified diff as `fix.patch`. Prepends unmappable items as `# graph-merge: unmappable changes (not applied)` comment lines.
3. Creates branch `graph-merge/port-<sha7>-<YYYYMMDD>` in `worktrees["dest"]` via `git checkout -b`.
4. Commits with `git commit -am "graph-merge: port fix from <source_after_ref>"` in `worktrees["dest"]`.
5. Writes `FIX_PROPOSAL.md` via `build_fix_proposal`.

### `build_fix_proposal`

```python
def build_fix_proposal(
    mapping_result: MappingResult,
    branch_name: str,
    source_repo: str,
    source_before_ref: str,
    source_after_ref: str,
    dest_repo: str,
    dest_base: str,
    commit_message: str,
) -> str   # markdown content
```

Pure function. Produces:

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

### All-Unmappable Exit Path

If `mapping_result.mappings` is empty, `runner._stage5` skips `run_render` entirely, calls `build_fix_proposal` directly with `branch_name="(none — all changes unmappable)"`, writes `FIX_PROPOSAL.md`, and returns exit code 0 with a warning. No branch is created, no patch is written.

The tool never pushes or opens a PR regardless of outcome.

**Stage skipping:** If both `fix.patch` and `FIX_PROPOSAL.md` exist, stage 5 is skipped.

**At successful exit:**
```
Branch created: graph-merge/port-a1b2c3d-20260601
To push:  git -C <dest-repo> push origin graph-merge/port-a1b2c3d-20260601
Review:   ./graph-merge-out/FIX_PROPOSAL.md
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
  --model              <p/model>     required: e.g. claude/claude-opus-4-6
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
| 0 | All stages completed, branch created (or all changes unmappable — see FIX_PROPOSAL.md) |
| 1 | A required stage failed |
| 2 | LLM response unparseable after retry |

---

## Error Handling

Each stage fails fast and writes to `error.log` before exiting.

| Stage | Failure | Behavior |
|-------|---------|----------|
| 1 | Clone fails (bad URL, no auth) | Exit 1, print auth hint |
| 1 | Ref not found | Exit 1, print available branches/tags |
| 2 | Graphify non-zero exit | Exit 1, surface Graphify stderr |
| 2 | `graph.json` not produced | Exit 1, hint at flag compatibility |
| 3 | No structural changes detected | Exit 0 with warning (`_NoChanges`) |
| 4 | `--model` not provided | Exit 1 before any stage runs |
| 4 | LLM auth failure | Exit 1, print missing env var |
| 4 | JSON parse fails twice | Exit 2, write `mapping_raw.txt` |
| 5 | Stage 5 LLM or git failure | Exit 1, write `error.log` |
| 5 | All mappings unmappable | Exit 0 with warning, write `FIX_PROPOSAL.md` |

---

## Testing

| Layer | File | What it tests |
|-------|------|---------------|
| Unit | `test_types.py` | Dataclass defaults, field types, `MappingResult` construction |
| Unit | `test_cli.py` | `--source-fix-commit` expansion, mutual exclusivity, default values, `main()` wiring |
| Unit | `test_graph_loading.py` | `load_graph` with dict and list node formats, field mapping, `properties` capture |
| Unit | `test_diff.py` | Empty diff, `node_modified`, `edge_added`, rationale extraction, fallback ID map |
| Unit | `test_pruning.py` | Seed selection, 2-hop BFS, god node exclusion, hard cap, camelCase token matching |
| Unit | `test_runner.py` | `artifacts_exist()` per stage, stage skipping, `--force-stage` override, error log written on failure |
| Unit | `test_render.py` | `build_fix_proposal` content, `generate_patch_content` LLM call count |
| Unit | `test_llm_client.py` | `MockLLMClient` call recording, `create_client` format validation, unknown provider rejection |
| Unit | `test_checkout.py` | `_ensure_local` local vs URL, worktree dirs created, before/after content isolation |
| Integration | `test_pipeline.py` | Full run (stages 1–2 bypassed via fixture graphs + mock LLM); stage skipping (all artifacts present); partial resume (semantic_diff.json deleted, stage 3 reruns) |
| Contract | `test_llm_parsing.py` | Valid JSON parsed, invalid JSON triggers one retry, two failures raises `ValueError`, missing `type` field in unmappable |
| Contract | `test_graphify_output.py` | `generate_graph` produces parseable JSON; nodes have required fields. Skipped if Graphify not installed (`@pytest.mark.skipif`). |

**LLM calls in all unit and integration tests use `MockLLMClient` — no real API calls in CI.**

**Test markers:** `integration` (requires fixture git repos), `contract` (requires Graphify subprocess and/or real API keys).

```bash
pytest tests/unit tests/integration -m "not contract"   # fast suite
pytest tests/contract -v -m contract                    # requires Graphify + API keys
```

---

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Input refs accept any git ref (SHA, branch, tag, relative) | Passed directly to `git worktree add`; no need to restrict the format |
| 2 | `--source-fix-commit <sha>` expands to `--source-before <sha>^ --source-after <sha>` | Common case is a single commit; shorthand avoids error-prone manual SHA arithmetic |
| 3 | `--dest-ref` renamed to `--dest-base` | The flag specifies the base the fix branch is created from, not the final destination ref — which doesn't exist yet |
| 4 | No default LLM backend; `--model` is required | NFR-1: code must not leave the machine without explicit user opt-in |
| 5 | `--model` format is `<provider>/<model-id>` | Single flag selects both SDK and model; unambiguous, extensible |
| 6 | Graph generation uses no LLM backend (pure tree-sitter) | Graphify's AST parsing is local; avoids sending code to cloud during graph stage |
| 7 | Graphify vendored as a git submodule at `vendor/graphify/` | Pins behavior against upstream changes; submodule allows deliberate updates |
| 8 | Graphify treated as a black-box subprocess; only `graph.json` and `GRAPH_REPORT.md` consumed | Decouples graph-merge from Graphify's internal module paths and dependency versions; a Graphify update can't silently break imports |
| 9 | Schema discovery on first run, written to `docs/graph_schema.md` | `graph.json` format is undocumented; discovery makes the schema explicit and reviewable |
| 10 | Staged pipeline with artifact caching | Expensive steps (graph gen, LLM) can be re-run independently; aligns with NFR-4 (all intermediates on disk) |
| 11 | Stage skipping is automatic; `--from-stage` and `--force-stage` for manual control | Default UX is resume-on-rerun; explicit flags for iteration on a specific stage |
| 12 | Always emit output regardless of confidence level; annotate with `high/medium/low` | User decides whether to apply; blocking on low confidence would hinder automation |
| 13 | Stage 5 creates a branch in the destination repo with the patch applied | Full automation up to the PR; human reviews `FIX_PROPOSAL.md` and opens the PR manually |
| 14 | Tool never pushes or opens a PR | Human in the loop for the final step; avoids unreviewed changes hitting remote |
| 15 | `atexit` handler cleans up worktrees on crash | Prevents orphaned git worktrees across runs |
| 16 | LLM called twice in stage 5 (once per mapped destination file for code content) | Mapping (stage 4) reasons structurally; rendering (stage 5) reasons about actual code — different tasks, different prompts |
| 17 | Single `fix.patch` for all changes | `git apply` is the standard handoff; one file is simpler than per-change patches |
| 18 | Fixture repos in `tests/fixtures/` are Python + Go | Tests cross-language porting, which is the hardest and most representative case |
| 19 | `pruning.py` is a separate module from `mapper.py` | Pruning is independently testable with synthetic graphs; embedding it in `mapper.py` would require a real LLM client in pruning tests |
| 20 | `_NoChanges` is a private exception, not a return value | A sentinel return value would require every call site to check it; the exception lets `runner.run_pipeline` intercept cleanly and exit 0 without polluting the `compute_semantic_diff` signature |
| 21 | `load_graph` handles both dict and list node formats | Graphify's schema is undocumented and has varied across versions; normalizing both formats at load time isolates the variability to one function |
| 22 | Provider clients in separate files (`anthropic_client.py`, etc.) | Provider SDK imports are lazy — `openai` not imported unless `--model openai/...` is passed; prevents import errors for users who have only one SDK installed |
| 23 | `models/config.py` is separate from `models/types.py` | `Config` depends on `pathlib.Path` and is CLI-specific; `types.py` is pure domain model. Separation makes `types.py` importable in any context |
| 24 | `generate_patch_content` returns new file content, not diffs | Generating a diff from LLM output is brittle; writing content to the worktree and running `git diff` produces a well-formed patch regardless of LLM output formatting |
| 25 | All-unmappable exit writes `FIX_PROPOSAL.md` and exits 0 | The user still needs to see which changes were unmappable and why; exiting non-zero would suppress the proposal and give no actionable output |
| 26 | `_build_fallback_id_map` runs before every diff, not only on detected mismatch | Checking for ID stability adds complexity for marginal benefit; the fallback map is a no-op (empty dict) when IDs are stable |
| 27 | `run_render` writes new content into `worktrees["dest"]` then captures `git diff` | Avoids constructing unified diff format manually; `git diff` produces correct hunks, handles whitespace consistently, and produces the same format `git apply` expects |
