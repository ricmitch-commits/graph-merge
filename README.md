# graph-merge

Port a bug fix between structurally diverged codebases using code knowledge graphs.

## How it works

1. Checks out the source repo at two refs (before and after the fix) and the destination repo
2. Generates a knowledge graph for each using [Graphify](https://github.com/safishamsi/graphify)
3. Diffs the before/after graphs to produce a semantic change set
4. Uses an LLM to map each changed node onto its structural equivalent in the destination graph
5. Renders a unified patch and a human-readable `FIX_PROPOSAL.md`; creates a branch

## Installation

```bash
git clone <this-repo> --recurse-submodules
pip install -e ".[dev]"
```

## Usage

```bash
graph-merge \
  --source-repo https://github.com/org/py-service \
  --source-fix-commit a1b2c3d \
  --dest-repo /path/to/go-service \
  --dest-base main \
  --model claude/claude-opus-4-6
```

Or with explicit refs:

```bash
graph-merge \
  --source-repo /path/to/source \
  --source-before a1b2c3d^ \
  --source-after a1b2c3d \
  --dest-repo /path/to/dest \
  --dest-base main \
  --model openai/gpt-4o \
  --output ./my-run-output
```

## All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--source-repo` | _required_ | Local path or remote git URL |
| `--source-fix-commit` | — | SHA of the fix commit; expands to `--source-before <sha>^ --source-after <sha>` |
| `--source-before` | — | git ref for pre-fix state (mutually exclusive with `--source-fix-commit`) |
| `--source-after` | — | git ref for post-fix state (mutually exclusive with `--source-fix-commit`) |
| `--dest-repo` | _required_ | Local path or remote git URL |
| `--dest-base` | _required_ | Base branch/commit to create the fix branch from |
| `--model` | _required_ | `<provider>/<model-id>` — e.g. `claude/claude-opus-4-6` |
| `--output` | `./graph-merge-out` | Output directory |
| `--commit-message` | — | Optional fix description for LLM context |
| `--pr-description` | — | Path to markdown file (alternative to `--commit-message`) |
| `--max-context-nodes` | `500` | Max destination graph nodes sent to LLM |
| `--keep-worktrees` | false | Skip worktree cleanup on exit |
| `--from-stage` | — | Resume from stage N |
| `--force-stage` | — | Re-run stage N even if its artifact exists |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success — branch created (or all changes unmappable — see FIX_PROPOSAL.md) |
| 1 | A required stage failed |
| 2 | LLM response unparseable after retry |

## Output directory

```
graph-merge-out/
├── worktrees/before|after|dest     git worktrees (deleted on exit unless --keep-worktrees)
├── graphs/before.json|after.json|dest.json
├── semantic_diff.json              stage 3 artifact
├── mapping.json                    stage 4 artifact
├── fix.patch                       unified diff for destination
├── FIX_PROPOSAL.md                 human-readable proposal
└── error.log                       written on failure
```

## Models supported

| Provider | Format | Example |
|----------|--------|---------|
| Anthropic | `claude/<model-id>` | `claude/claude-opus-4-6` |
| OpenAI | `openai/<model-id>` | `openai/gpt-4o` |
| Gemini | `gemini/<model-id>` | `gemini/gemini-2.0-flash` |

Set the relevant API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) before running.

## Development

```bash
pytest tests/unit tests/integration -v          # fast tests (no real LLM)
pytest tests/contract -v -m contract            # requires Graphify + real API keys
```
