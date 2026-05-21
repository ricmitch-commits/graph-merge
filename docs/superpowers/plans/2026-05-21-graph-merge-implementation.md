# graph-merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `graph-merge`, a CLI tool that ports bug fixes between structurally diverged codebases using code knowledge graphs and an LLM.

**Architecture:** Five sequential pipeline stages (checkout → graph generation → semantic diff → LLM mapping → output rendering) each write artifacts to disk; a stage is skipped automatically if its artifact already exists. The LLM is only called in stages 4 and 5 via a pluggable client that routes to Anthropic, OpenAI, or Gemini based on `--model <provider>/<model-id>`.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `subprocess`, `pytest`, `anthropic` / `openai` / `google-generativeai` (optional providers), Graphify (vendored git submodule).

---

## File Map

```
graph-merge/
├── cli.py                          entry point — arg parsing, validation, calls runner
├── pipeline/
│   ├── __init__.py
│   ├── runner.py                   stage orchestrator; artifact skipping; error.log
│   ├── checkout.py                 stage 1 — git clone + worktree management + atexit
│   ├── graph.py                    stage 2 — Graphify subprocess + graph.json loading
│   ├── diff.py                     stage 3 — pure-Python semantic diff algorithm
│   ├── pruning.py                  context pruning for LLM (split out for testability)
│   ├── mapper.py                   stage 4 — LLM prompt + response parsing
│   └── render.py                   stage 5 — patch generation + FIX_PROPOSAL.md + branch
├── models/
│   ├── __init__.py
│   ├── types.py                    all dataclasses: GraphNode, GraphEdge, Change, etc.
│   └── config.py                   Config dataclass (parsed CLI args + computed paths)
├── llm/
│   ├── __init__.py
│   ├── client.py                   Protocol + MockLLMClient + create_client() factory
│   ├── anthropic_client.py
│   ├── openai_client.py
│   └── gemini_client.py
├── tests/
│   ├── conftest.py                 shared fixtures (tmp_path helpers)
│   ├── unit/
│   │   ├── test_types.py
│   │   ├── test_diff.py
│   │   ├── test_pruning.py
│   │   └── test_cli.py
│   ├── integration/
│   │   ├── conftest.py             fixture git repos + mock graphify
│   │   └── test_pipeline.py        BDD scenarios (Given/When/Then)
│   ├── contract/
│   │   ├── test_llm_parsing.py     retry logic, bad JSON, partial JSON
│   │   └── test_graphify_output.py parse real Graphify output into dataclasses
│   └── fixtures/
│       ├── graphs/
│       │   ├── before.json
│       │   ├── after.json
│       │   └── dest.json
│       └── responses/
│           ├── mapping_valid.json
│           ├── mapping_invalid.json
│           └── mapping_partial.json
├── vendor/
│   └── graphify/                   git submodule (pinned)
├── docs/
│   ├── graph_schema.md             auto-generated on first run
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── pyproject.toml
├── .gitmodules
└── README.md
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `cli.py` (stub)
- Create: `pipeline/__init__.py`, `models/__init__.py`, `llm/__init__.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/contract/__init__.py`
- Create: `.gitmodules`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "graph-merge"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.30",
    "openai>=1.0",
    "google-generativeai>=0.7",
]

[project.scripts]
graph-merge = "cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
markers = [
    "integration: requires fixture git repos",
    "contract: requires external tools (graphify, real LLM API)",
]
```

- [ ] **Step 2: Create package `__init__.py` files and stub `cli.py`**

Create empty `__init__.py` in `pipeline/`, `models/`, `llm/`, `tests/`, `tests/unit/`, `tests/integration/`, `tests/contract/`.

```python
# cli.py
def main() -> None:
    raise NotImplementedError

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add Graphify as a git submodule**

```bash
git submodule add https://github.com/safishamsi/graphify vendor/graphify
git submodule update --init --recursive
```

Expected: `vendor/graphify/` populated, `.gitmodules` written.

- [ ] **Step 4: Install dev dependencies and verify pytest runs**

```bash
pip install -e ".[dev]"
pytest --collect-only
```

Expected: `no tests ran`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml cli.py pipeline/ models/ llm/ tests/ vendor/ .gitmodules
git commit -m "chore: scaffold project structure and add graphify submodule"
```

---

## Task 2: Data Models

**Files:**
- Create: `models/types.py`
- Create: `models/config.py`
- Create: `tests/unit/test_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_types.py
from models.types import (
    GraphNode, GraphEdge, Change, SemanticDiff,
    SourceChange, DestinationNode, Mapping, UnmappableChange, MappingResult,
)
from models.config import Config
from pathlib import Path


def test_graph_node_defaults():
    node = GraphNode(id="src/auth.py::validate_token", file="src/auth.py",
                     symbol="validate_token", kind="function")
    assert node.calls == []
    assert node.imports == []
    assert node.properties == {}


def test_graph_edge_fields():
    edge = GraphEdge(source="a", target="b", relation="calls", confidence="EXTRACTED")
    assert edge.relation == "calls"


def test_change_node_modified():
    c = Change(type="node_modified", node_id="src/auth.py::validate_token",
               file="src/auth.py", symbol="validate_token", kind="function",
               before={"calls": ["db.query"]}, after={"calls": ["db.query", "logger.warn"]},
               rationale="WHY: audit trail")
    assert c.type == "node_modified"
    assert c.rationale == "WHY: audit trail"


def test_semantic_diff_empty():
    sd = SemanticDiff(commit_message="fix: add warning")
    assert sd.changes == []


def test_mapping_result_fields():
    sc = SourceChange(node_id="src/auth.py::validate_token", type="node_modified")
    dn = DestinationNode(file="internal/auth/service.go", symbol="ValidateToken")
    m = Mapping(source_change=sc, destination_node=dn, confidence="high",
                rationale="Same role in call graph")
    result = MappingResult(mappings=[m])
    assert result.mappings[0].confidence == "high"
    assert result.unmappable == []


def test_config_output_dir_is_path():
    config = Config(
        source_repo="/tmp/src", source_before="abc^", source_after="abc",
        dest_repo="/tmp/dest", dest_base="main", model="claude/claude-opus-4-7",
        output_dir=Path("/tmp/out"), commit_message="", max_context_nodes=500,
        keep_worktrees=False, from_stage=None, force_stage=None,
    )
    assert isinstance(config.output_dir, Path)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'models.types'`

- [ ] **Step 3: Implement `models/types.py`**

```python
from dataclasses import dataclass, field


@dataclass
class GraphNode:
    id: str
    file: str
    symbol: str
    kind: str
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str
    confidence: str


@dataclass
class Change:
    type: str
    node_id: str | None = None
    file: str | None = None
    symbol: str | None = None
    kind: str | None = None
    before: dict | None = None
    after: dict | None = None
    rationale: str | None = None
    edge: "GraphEdge | None" = None


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
    confidence: str
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

- [ ] **Step 4: Implement `models/config.py`**

```python
from dataclasses import dataclass
from pathlib import Path


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

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_types.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add models/types.py models/config.py models/__init__.py tests/unit/test_types.py
git commit -m "feat: add data model dataclasses and Config"
```

---

## Task 3: LLM Client Interface and Mock

**Files:**
- Create: `llm/client.py`
- Create: `tests/unit/test_llm_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_llm_client.py
import pytest
from llm.client import MockLLMClient, create_client


def test_mock_client_returns_fixed_response():
    client = MockLLMClient(response='{"mappings": [], "unmappable": []}')
    result = client.complete("some prompt")
    assert result == '{"mappings": [], "unmappable": []}'


def test_mock_client_records_calls():
    client = MockLLMClient(response="ok")
    client.complete("prompt one")
    client.complete("prompt two")
    assert client.call_count == 2
    assert client.last_prompt == "prompt two"


def test_create_client_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_client("unknown/model-id")


def test_create_client_rejects_missing_model_id():
    with pytest.raises(ValueError, match="Invalid model spec"):
        create_client("claude")


def test_create_client_accepts_valid_spec_format():
    # Should not raise — provider is recognised even if SDK not configured
    # We can't call complete() without real credentials, so just check construction
    client = create_client("claude/claude-opus-4-7")
    assert hasattr(client, "complete")
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_llm_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'llm.client'`

- [ ] **Step 3: Implement `llm/client.py`**

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockLLMClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        return self._response


def create_client(model_spec: str) -> LLMClient:
    provider, _, model_id = model_spec.partition("/")
    if not model_id:
        raise ValueError(
            f"Invalid model spec '{model_spec}': expected '<provider>/<model-id>'"
        )
    if provider == "claude":
        from llm.anthropic_client import AnthropicClient
        return AnthropicClient(model_id)
    if provider == "openai":
        from llm.openai_client import OpenAIClient
        return OpenAIClient(model_id)
    if provider == "gemini":
        from llm.gemini_client import GeminiClient
        return GeminiClient(model_id)
    raise ValueError(
        f"Unknown provider '{provider}': expected claude, openai, or gemini"
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_llm_client.py -v
```

Expected: `5 passed` (the `create_client` test may error on import if `anthropic` is not installed — install with `pip install anthropic` or stub the import; see Step 5.)

- [ ] **Step 5: Create provider stubs** (prevents ImportError in tests)

```python
# llm/anthropic_client.py
class AnthropicClient:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=self._model_id,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
```

```python
# llm/openai_client.py
class OpenAIClient:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=self._model_id,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
```

```python
# llm/gemini_client.py
class GeminiClient:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import google.generativeai as genai
        model = genai.GenerativeModel(self._model_id)
        response = model.generate_content(prompt)
        return response.text
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add llm/ tests/unit/test_llm_client.py
git commit -m "feat: add LLM client protocol, mock, and provider stubs"
```

---

## Task 4: CLI Argument Parsing

**Files:**
- Create: `tests/unit/test_cli.py`
- Modify: `cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli.py
import pytest
from cli import build_parser, validate_args


def test_source_fix_commit_expands_to_before_after():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc1234",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
    ])
    args = validate_args(args)
    assert args.source_before == "abc1234^"
    assert args.source_after == "abc1234"


def test_explicit_before_after_accepted():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-before", "abc1234^",
        "--source-after", "abc1234",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
    ])
    args = validate_args(args)
    assert args.source_before == "abc1234^"
    assert args.source_after == "abc1234"


def test_source_fix_commit_and_before_are_mutually_exclusive():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc",
        "--source-before", "abc^",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
    ])
    with pytest.raises(SystemExit):
        validate_args(args)


def test_missing_both_source_refs_raises():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
    ])
    with pytest.raises(SystemExit):
        validate_args(args)


def test_default_output_dir():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
    ])
    assert args.output == "./graph-merge-out"


def test_max_context_nodes_default():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
    ])
    assert args.max_context_nodes == 500
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: `ImportError` — `build_parser` not defined.

- [ ] **Step 3: Implement `cli.py`**

```python
import argparse
import sys
from pathlib import Path
from models.config import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-merge",
        description="Port a bug fix between codebases using code knowledge graphs.",
    )
    parser.add_argument("--source-repo", required=True, metavar="PATH|URL")
    parser.add_argument("--source-fix-commit", metavar="SHA")
    parser.add_argument("--source-before", metavar="REF")
    parser.add_argument("--source-after", metavar="REF")
    parser.add_argument("--dest-repo", required=True, metavar="PATH|URL")
    parser.add_argument("--dest-base", required=True, metavar="REF")
    parser.add_argument("--model", required=True, metavar="PROVIDER/MODEL-ID")
    parser.add_argument("--output", default="./graph-merge-out", metavar="DIR")
    parser.add_argument("--commit-message", default="", metavar="TEXT")
    parser.add_argument("--pr-description", metavar="FILE")
    parser.add_argument("--max-context-nodes", type=int, default=500, metavar="N")
    parser.add_argument("--keep-worktrees", action="store_true")
    parser.add_argument("--from-stage", type=int, choices=[1, 2, 3, 4, 5], metavar="1-5")
    parser.add_argument("--force-stage", type=int, choices=[1, 2, 3, 4, 5], metavar="1-5")
    return parser


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.source_fix_commit and (args.source_before or args.source_after):
        print(
            "error: --source-fix-commit is mutually exclusive with "
            "--source-before / --source-after",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.source_fix_commit:
        args.source_before = f"{args.source_fix_commit}^"
        args.source_after = args.source_fix_commit
    elif not (args.source_before and args.source_after):
        print(
            "error: provide --source-fix-commit or both --source-before and --source-after",
            file=sys.stderr,
        )
        sys.exit(1)
    return args


def args_to_config(args: argparse.Namespace) -> Config:
    commit_message = args.commit_message
    if args.pr_description:
        commit_message = Path(args.pr_description).read_text()
    return Config(
        source_repo=args.source_repo,
        source_before=args.source_before,
        source_after=args.source_after,
        dest_repo=args.dest_repo,
        dest_base=args.dest_base,
        model=args.model,
        output_dir=Path(args.output),
        commit_message=commit_message,
        max_context_nodes=args.max_context_nodes,
        keep_worktrees=args.keep_worktrees,
        from_stage=args.from_stage,
        force_stage=args.force_stage,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args = validate_args(args)
    config = args_to_config(args)

    from pipeline.runner import run_pipeline
    sys.exit(run_pipeline(config))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_cli.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/unit/test_cli.py
git commit -m "feat: implement CLI argument parsing and --source-fix-commit expansion"
```

---

## Task 5: Graph JSON Loading

**Files:**
- Create: `pipeline/graph.py`
- Create: `tests/fixtures/graphs/before.json`
- Create: `tests/fixtures/graphs/after.json`
- Create: `tests/fixtures/graphs/dest.json`
- Create: `tests/unit/test_graph_loading.py`

- [ ] **Step 1: Create fixture graph files**

```json
// tests/fixtures/graphs/before.json
{
  "nodes": {
    "src/auth.py::validate_token": {
      "file": "src/auth.py", "symbol": "validate_token", "kind": "function",
      "calls": ["db.query"], "imports": [], "properties": {}
    },
    "src/auth.py::TokenCache": {
      "file": "src/auth.py", "symbol": "TokenCache", "kind": "class",
      "calls": [], "imports": [], "properties": {}
    }
  },
  "edges": [
    {"source": "src/auth.py::validate_token", "target": "db.query",
     "relation": "calls", "confidence": "EXTRACTED"}
  ]
}
```

```json
// tests/fixtures/graphs/after.json
{
  "nodes": {
    "src/auth.py::validate_token": {
      "file": "src/auth.py", "symbol": "validate_token", "kind": "function",
      "calls": ["db.query", "logger.warn"], "imports": [],
      "properties": {"WHY": "Log invalid token attempts for audit trail"}
    },
    "src/auth.py::TokenCache": {
      "file": "src/auth.py", "symbol": "TokenCache", "kind": "class",
      "calls": [], "imports": [], "properties": {}
    }
  },
  "edges": [
    {"source": "src/auth.py::validate_token", "target": "db.query",
     "relation": "calls", "confidence": "EXTRACTED"},
    {"source": "src/auth.py::validate_token", "target": "logger.warn",
     "relation": "calls", "confidence": "EXTRACTED"}
  ]
}
```

```json
// tests/fixtures/graphs/dest.json
{
  "nodes": {
    "internal/auth/service.go::ValidateToken": {
      "file": "internal/auth/service.go", "symbol": "ValidateToken", "kind": "function",
      "calls": ["db.QueryRow"], "imports": ["database/sql"], "properties": {}
    }
  },
  "edges": [
    {"source": "internal/auth/service.go::ValidateToken", "target": "db.QueryRow",
     "relation": "calls", "confidence": "EXTRACTED"}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_graph_loading.py
from pathlib import Path
import pytest
from pipeline.graph import load_graph
from models.types import GraphNode, GraphEdge

FIXTURES = Path(__file__).parent.parent / "fixtures" / "graphs"


def test_load_graph_returns_nodes_and_edges():
    nodes, edges = load_graph(FIXTURES / "before.json")
    assert "src/auth.py::validate_token" in nodes
    assert isinstance(nodes["src/auth.py::validate_token"], GraphNode)
    assert len(edges) == 1
    assert isinstance(edges[0], GraphEdge)


def test_load_graph_node_fields():
    nodes, _ = load_graph(FIXTURES / "before.json")
    node = nodes["src/auth.py::validate_token"]
    assert node.file == "src/auth.py"
    assert node.symbol == "validate_token"
    assert node.kind == "function"
    assert node.calls == ["db.query"]


def test_load_graph_after_includes_why_in_properties():
    nodes, _ = load_graph(FIXTURES / "after.json")
    node = nodes["src/auth.py::validate_token"]
    assert "WHY" in node.properties
    assert node.calls == ["db.query", "logger.warn"]


def test_load_graph_edge_fields():
    _, edges = load_graph(FIXTURES / "before.json")
    edge = edges[0]
    assert edge.source == "src/auth.py::validate_token"
    assert edge.target == "db.query"
    assert edge.relation == "calls"
    assert edge.confidence == "EXTRACTED"


def test_load_graph_dest():
    nodes, edges = load_graph(FIXTURES / "dest.json")
    assert "internal/auth/service.go::ValidateToken" in nodes
    assert len(edges) == 1
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/unit/test_graph_loading.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.graph'`

- [ ] **Step 4: Implement `pipeline/graph.py`**

```python
import json
import shutil
import subprocess
from pathlib import Path

from models.types import GraphEdge, GraphNode


def load_graph(graph_path: Path) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
    data = json.loads(graph_path.read_text())
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    raw_nodes = data.get("nodes", {})
    raw_edges = data.get("edges", [])

    if isinstance(raw_nodes, dict):
        for node_id, node_data in raw_nodes.items():
            nodes[node_id] = _parse_node(node_id, node_data)
    elif isinstance(raw_nodes, list):
        for node_data in raw_nodes:
            node = _parse_node(node_data.get("id", ""), node_data)
            nodes[node.id] = node

    for edge_data in raw_edges:
        edges.append(GraphEdge(
            source=edge_data.get("source", ""),
            target=edge_data.get("target", ""),
            relation=edge_data.get("relation", ""),
            confidence=edge_data.get("confidence", "EXTRACTED"),
        ))

    return nodes, edges


def _parse_node(node_id: str, data: dict) -> GraphNode:
    known = {"id", "file", "symbol", "name", "kind", "type", "calls", "imports"}
    return GraphNode(
        id=node_id or data.get("id", ""),
        file=data.get("file", ""),
        symbol=data.get("symbol", data.get("name", "")),
        kind=data.get("kind", data.get("type", "")),
        calls=data.get("calls", []),
        imports=data.get("imports", []),
        properties={k: v for k, v in data.items() if k not in known},
    )


def generate_graph(worktree_path: Path, output_path: Path, label: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["python", "-m", "graphify.extract", str(worktree_path),
         "--output", str(output_path), "--no-html"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return

    if "--no-html" in result.stderr or "unrecognized arguments" in result.stderr:
        result2 = subprocess.run(
            ["python", "-m", "graphify.extract", str(worktree_path)],
            capture_output=True, text=True, cwd=worktree_path,
        )
        if result2.returncode != 0:
            raise RuntimeError(f"Graphify failed:\n{result2.stderr}")
        graphify_out = worktree_path / "graphify-out"
        src = graphify_out / "graph.json"
        if not src.exists():
            raise RuntimeError("Graphify ran but did not produce graph.json")
        shutil.copy(src, output_path)
        report_src = graphify_out / "GRAPH_REPORT.md"
        if report_src.exists():
            shutil.copy(report_src, output_path.parent / f"{label}_report.md")
    else:
        raise RuntimeError(f"Graphify failed:\n{result.stderr}")
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_graph_loading.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add pipeline/graph.py pipeline/__init__.py tests/unit/test_graph_loading.py \
        tests/fixtures/graphs/
git commit -m "feat: implement graph JSON loading and Graphify invocation"
```

---

## Task 6: Semantic Diff Algorithm

**Files:**
- Create: `pipeline/diff.py`
- Create: `tests/unit/test_diff.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_diff.py
from pathlib import Path
from pipeline.graph import load_graph
from pipeline.diff import compute_semantic_diff

FIXTURES = Path(__file__).parent.parent / "fixtures" / "graphs"


def _load_pair(a_name: str, b_name: str):
    before_nodes, before_edges = load_graph(FIXTURES / a_name)
    after_nodes, after_edges = load_graph(FIXTURES / b_name)
    return before_nodes, before_edges, after_nodes, after_edges


def test_no_change_produces_empty_diff():
    before_nodes, before_edges, _, _ = _load_pair("before.json", "before.json")
    after_nodes, after_edges = before_nodes, before_edges
    result = compute_semantic_diff(before_nodes, after_nodes, before_edges, after_edges)
    assert result.changes == []


def test_modified_node_detected():
    before_nodes, before_edges, after_nodes, after_edges = _load_pair(
        "before.json", "after.json"
    )
    result = compute_semantic_diff(before_nodes, after_nodes, before_edges, after_edges)
    modified = [c for c in result.changes if c.type == "node_modified"]
    assert len(modified) == 1
    assert modified[0].node_id == "src/auth.py::validate_token"


def test_modified_node_captures_before_and_after_calls():
    before_nodes, before_edges, after_nodes, after_edges = _load_pair(
        "before.json", "after.json"
    )
    result = compute_semantic_diff(before_nodes, after_nodes, before_edges, after_edges)
    modified = [c for c in result.changes if c.type == "node_modified"][0]
    assert modified.before["calls"] == ["db.query"]
    assert modified.after["calls"] == ["db.query", "logger.warn"]


def test_rationale_extracted_from_why_property():
    before_nodes, before_edges, after_nodes, after_edges = _load_pair(
        "before.json", "after.json"
    )
    result = compute_semantic_diff(before_nodes, after_nodes, before_edges, after_edges)
    modified = [c for c in result.changes if c.type == "node_modified"][0]
    assert modified.rationale == "Log invalid token attempts for audit trail"


def test_added_edge_detected():
    before_nodes, before_edges, after_nodes, after_edges = _load_pair(
        "before.json", "after.json"
    )
    result = compute_semantic_diff(before_nodes, after_nodes, before_edges, after_edges)
    edge_adds = [c for c in result.changes if c.type == "edge_added"]
    assert any(
        c.edge and c.edge.target == "logger.warn" for c in edge_adds
    )


def test_commit_message_preserved():
    before_nodes, before_edges, _, _ = _load_pair("before.json", "before.json")
    result = compute_semantic_diff(
        before_nodes, before_nodes, before_edges, before_edges,
        commit_message="fix: add warning for invalid token",
    )
    assert result.commit_message == "fix: add warning for invalid token"


def test_fallback_match_by_file_symbol_kind(tmp_path):
    """If node IDs differ between before/after but (file, symbol, kind) match,
    the node should be treated as modified rather than removed+added."""
    from models.types import GraphNode
    before_nodes = {
        "old-id-1": GraphNode(id="old-id-1", file="src/auth.py",
                              symbol="validate_token", kind="function",
                              calls=["db.query"])
    }
    after_nodes = {
        "new-id-1": GraphNode(id="new-id-1", file="src/auth.py",
                              symbol="validate_token", kind="function",
                              calls=["db.query", "logger.warn"])
    }
    result = compute_semantic_diff(before_nodes, after_nodes, [], [])
    types = {c.type for c in result.changes}
    assert "node_modified" in types
    assert "node_added" not in types
    assert "node_removed" not in types
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_diff.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.diff'`

- [ ] **Step 3: Implement `pipeline/diff.py`**

```python
import re
from models.types import Change, GraphEdge, GraphNode, SemanticDiff

_RATIONALE_KEYS = {"why", "hack", "note", "fixme"}


def compute_semantic_diff(
    before_nodes: dict[str, GraphNode],
    after_nodes: dict[str, GraphNode],
    before_edges: list[GraphEdge],
    after_edges: list[GraphEdge],
    commit_message: str = "",
) -> SemanticDiff:
    # Remap IDs if not stable across runs
    id_map = _build_fallback_id_map(before_nodes, after_nodes)
    remapped_before = {id_map.get(k, k): v for k, v in before_nodes.items()}

    before_ids = set(remapped_before)
    after_ids = set(after_nodes)
    changes: list[Change] = []

    for node_id in after_ids - before_ids:
        node = after_nodes[node_id]
        changes.append(Change(
            type="node_added", node_id=node_id, file=node.file,
            symbol=node.symbol, kind=node.kind,
            after={"calls": node.calls, "imports": node.imports,
                   "properties": node.properties},
        ))

    for node_id in before_ids - after_ids:
        node = remapped_before[node_id]
        changes.append(Change(
            type="node_removed", node_id=node_id, file=node.file,
            symbol=node.symbol, kind=node.kind,
            before={"calls": node.calls, "imports": node.imports,
                    "properties": node.properties},
        ))

    for node_id in before_ids & after_ids:
        b = remapped_before[node_id]
        a = after_nodes[node_id]
        if b.calls != a.calls or b.imports != a.imports or b.properties != a.properties:
            changes.append(Change(
                type="node_modified", node_id=node_id, file=a.file,
                symbol=a.symbol, kind=a.kind,
                before={"calls": b.calls, "imports": b.imports,
                        "properties": b.properties},
                after={"calls": a.calls, "imports": a.imports,
                       "properties": a.properties},
                rationale=_extract_rationale(a.properties),
            ))

    before_triples = {(e.source, e.target, e.relation) for e in before_edges}
    after_triples = {(e.source, e.target, e.relation) for e in after_edges}

    edge_by_triple = {(e.source, e.target, e.relation): e for e in after_edges}
    for triple in after_triples - before_triples:
        changes.append(Change(type="edge_added", edge=edge_by_triple[triple]))

    edge_by_triple_before = {(e.source, e.target, e.relation): e for e in before_edges}
    for triple in before_triples - after_triples:
        changes.append(Change(type="edge_removed", edge=edge_by_triple_before[triple]))

    return SemanticDiff(commit_message=commit_message, changes=changes)


def _extract_rationale(properties: dict) -> str | None:
    for key, value in properties.items():
        if key.lower() in _RATIONALE_KEYS:
            return str(value)
    return None


def _build_fallback_id_map(
    before_nodes: dict[str, GraphNode],
    after_nodes: dict[str, GraphNode],
) -> dict[str, str]:
    """Map before IDs → after IDs when IDs are unstable. Match on (file, symbol, kind)."""
    after_by_tuple = {
        (n.file, n.symbol, n.kind): nid for nid, n in after_nodes.items()
    }
    mapping: dict[str, str] = {}
    for before_id, node in before_nodes.items():
        after_id = after_by_tuple.get((node.file, node.symbol, node.kind))
        if after_id and after_id != before_id:
            mapping[before_id] = after_id
    return mapping
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_diff.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/diff.py tests/unit/test_diff.py
git commit -m "feat: implement semantic graph diff algorithm with fallback ID matching"
```

---

## Task 7: Context Pruning

**Files:**
- Create: `pipeline/pruning.py`
- Create: `tests/unit/test_pruning.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pruning.py
import pytest
from models.types import GraphEdge, GraphNode
from pipeline.pruning import prune_graph


def _make_node(node_id: str, symbol: str, file: str = "f.py") -> GraphNode:
    return GraphNode(id=node_id, file=file, symbol=symbol, kind="function")


def _make_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source=src, target=tgt, relation="calls", confidence="EXTRACTED")


def test_seed_nodes_always_included():
    nodes = {
        "a": _make_node("a", "validate_token"),
        "b": _make_node("b", "unrelated_thing"),
    }
    result = prune_graph(nodes, [], changed_symbols={"validate_token"}, god_nodes=set())
    assert "a" in result


def test_2_hop_neighbours_included():
    nodes = {
        "a": _make_node("a", "validate_token"),
        "b": _make_node("b", "hop1"),
        "c": _make_node("c", "hop2"),
        "d": _make_node("d", "hop3"),
    }
    edges = [_make_edge("a", "b"), _make_edge("b", "c"), _make_edge("c", "d")]
    result = prune_graph(nodes, edges, changed_symbols={"validate_token"}, god_nodes=set())
    assert "b" in result
    assert "c" in result
    assert "d" not in result   # 3 hops away


def test_god_nodes_excluded():
    nodes = {
        "a": _make_node("a", "validate_token"),
        "god": _make_node("god", "hop1"),
    }
    edges = [_make_edge("a", "god")]
    result = prune_graph(
        nodes, edges, changed_symbols={"validate_token"}, god_nodes={"god"}
    )
    assert "god" not in result


def test_hard_cap_drops_lowest_degree_nodes():
    nodes = {f"n{i}": _make_node(f"n{i}", "validate_token") for i in range(10)}
    # n0 has 5 edges (high degree), others have 1
    edges = [_make_edge("n0", f"n{i}") for i in range(1, 6)]
    edges += [_make_edge(f"n{i}", f"x{i}") for i in range(6, 10)]
    all_nodes = {**nodes, **{f"x{i}": _make_node(f"x{i}", "other") for i in range(6, 10)}}
    result = prune_graph(
        all_nodes, edges, changed_symbols={"validate_token"},
        god_nodes=set(), max_nodes=3,
    )
    assert len(result) <= 3


def test_camel_case_token_matching():
    nodes = {
        "a": _make_node("a", "ValidateToken"),
        "b": _make_node("b", "unrelated"),
    }
    # "validate_token" tokens = {"validate", "token"}; "ValidateToken" tokens = {"validate", "token"}
    result = prune_graph(nodes, [], changed_symbols={"validate_token"}, god_nodes=set())
    assert "a" in result
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_pruning.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.pruning'`

- [ ] **Step 3: Implement `pipeline/pruning.py`**

```python
import re
from pathlib import Path

from models.types import GraphEdge, GraphNode


def prune_graph(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    changed_symbols: set[str],
    god_nodes: set[str],
    max_nodes: int = 500,
) -> dict[str, GraphNode]:
    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for edge in edges:
        if edge.source in adj:
            adj[edge.source].add(edge.target)
        if edge.target in adj:
            adj[edge.target].add(edge.source)

    changed_tokens: set[str] = set()
    for sym in changed_symbols:
        changed_tokens.update(_tokenize(sym))

    seeds = {
        nid for nid, node in nodes.items()
        if _tokenize(node.symbol) & changed_tokens
    }

    within_2_hops = _bfs(seeds, adj, max_hops=2)
    kept = {nid: nodes[nid] for nid in within_2_hops if nid not in god_nodes}

    if len(kept) > max_nodes:
        degrees = {nid: len(adj.get(nid, set())) for nid in kept}
        top = sorted(kept, key=lambda n: degrees[n], reverse=True)[:max_nodes]
        kept = {nid: kept[nid] for nid in top}

    return kept


def load_god_nodes(report_path: Path) -> set[str]:
    if not report_path.exists():
        return set()
    god_nodes: set[str] = set()
    for line in report_path.read_text().splitlines():
        if "god node" in line.lower() or "highest degree" in line.lower():
            match = re.search(r"`([^`]+)`", line)
            if match:
                god_nodes.add(match.group(1))
    return god_nodes


def _tokenize(symbol: str) -> set[str]:
    tokens = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", symbol)
    return {t.lower() for t in tokens if len(t) > 1}


def _bfs(seeds: set[str], adj: dict[str, set[str]], max_hops: int) -> set[str]:
    visited = set(seeds)
    frontier = set(seeds)
    for _ in range(max_hops):
        next_frontier = set()
        for node in frontier:
            for neighbour in adj.get(node, set()):
                if neighbour not in visited:
                    visited.add(neighbour)
                    next_frontier.add(neighbour)
        frontier = next_frontier
    return visited
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_pruning.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/pruning.py tests/unit/test_pruning.py
git commit -m "feat: implement context pruning (2-hop BFS, god node exclusion, hard cap)"
```

---

## Task 8: Pipeline Runner and Artifact Skipping

**Files:**
- Create: `pipeline/runner.py`
- Create: `tests/unit/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_runner.py
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from models.config import Config
from pipeline.runner import artifacts_exist, run_pipeline


def _config(tmp_path: Path, from_stage=None, force_stage=None) -> Config:
    return Config(
        source_repo="/src", source_before="abc^", source_after="abc",
        dest_repo="/dest", dest_base="main", model="claude/claude-opus-4-7",
        output_dir=tmp_path, commit_message="", max_context_nodes=500,
        keep_worktrees=False, from_stage=from_stage, force_stage=force_stage,
    )


def test_artifacts_exist_stage1_false_when_worktrees_missing(tmp_path):
    assert not artifacts_exist(tmp_path, 1)


def test_artifacts_exist_stage1_true_when_all_worktrees_present(tmp_path):
    for label in ("before", "after", "dest"):
        (tmp_path / "worktrees" / label).mkdir(parents=True)
    assert artifacts_exist(tmp_path, 1)


def test_artifacts_exist_stage3_true_when_semantic_diff_present(tmp_path):
    (tmp_path / "semantic_diff.json").write_text("{}")
    assert artifacts_exist(tmp_path, 3)


def test_artifacts_exist_stage4_true_when_mapping_present(tmp_path):
    (tmp_path / "mapping.json").write_text("{}")
    assert artifacts_exist(tmp_path, 4)


def test_stage_skipped_when_artifacts_exist(tmp_path):
    config = _config(tmp_path)
    # Pre-create all artifacts so every stage is skipped
    for label in ("before", "after", "dest"):
        (tmp_path / "worktrees" / label).mkdir(parents=True)
    for label in ("before", "after", "dest"):
        (tmp_path / "graphs").mkdir(exist_ok=True)
        (tmp_path / "graphs" / f"{label}.json").write_text("{}")
    (tmp_path / "semantic_diff.json").write_text("{}")
    (tmp_path / "mapping.json").write_text("{}")
    (tmp_path / "fix.patch").write_text("")
    (tmp_path / "FIX_PROPOSAL.md").write_text("")

    called = []
    with patch("pipeline.runner.STAGES", [
        (i, f"S{i}", lambda c, i=i: called.append(i)) for i in range(1, 6)
    ]):
        run_pipeline(config)

    assert called == [], "No stages should run when all artifacts exist"


def test_force_stage_reruns_despite_artifact(tmp_path):
    config = _config(tmp_path, force_stage=3)
    (tmp_path / "semantic_diff.json").write_text("{}")

    called = []
    def fake_stage3(c):
        called.append(3)

    with patch("pipeline.runner.STAGES", [(3, "Diff", fake_stage3)]):
        # runner will error after stage 3 because other stages aren't set up
        # We only care that stage 3 was called
        try:
            run_pipeline(config)
        except Exception:
            pass

    assert 3 in called
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_runner.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.runner'`

- [ ] **Step 3: Implement `pipeline/runner.py`**

```python
import sys
from pathlib import Path
from typing import Callable

from models.config import Config


def artifacts_exist(output_dir: Path, stage: int) -> bool:
    checks: dict[int, Callable[[], bool]] = {
        1: lambda: all(
            (output_dir / "worktrees" / label).exists()
            for label in ("before", "after", "dest")
        ),
        2: lambda: all(
            (output_dir / "graphs" / f"{label}.json").exists()
            for label in ("before", "after", "dest")
        ),
        3: lambda: (output_dir / "semantic_diff.json").exists(),
        4: lambda: (output_dir / "mapping.json").exists(),
        5: lambda: (
            (output_dir / "fix.patch").exists()
            and (output_dir / "FIX_PROPOSAL.md").exists()
        ),
    }
    return checks[stage]()


def _stage1(config: Config) -> None:
    from pipeline.checkout import setup_worktrees
    setup_worktrees(
        source_repo=config.source_repo,
        source_before=config.source_before,
        source_after=config.source_after,
        dest_repo=config.dest_repo,
        dest_base=config.dest_base,
        output_dir=config.output_dir,
        keep_worktrees=config.keep_worktrees,
    )


def _stage2(config: Config) -> None:
    from pipeline.graph import generate_graph
    graphs_dir = config.output_dir / "graphs"
    worktrees_dir = config.output_dir / "worktrees"
    for label in ("before", "after", "dest"):
        generate_graph(
            worktree_path=worktrees_dir / label,
            output_path=graphs_dir / f"{label}.json",
            label=label,
        )


class _NoChanges(Exception):
    pass


def _stage3(config: Config) -> None:
    import json
    from pipeline.graph import load_graph
    from pipeline.diff import compute_semantic_diff
    graphs_dir = config.output_dir / "graphs"
    before_nodes, before_edges = load_graph(graphs_dir / "before.json")
    after_nodes, after_edges = load_graph(graphs_dir / "after.json")
    diff = compute_semantic_diff(
        before_nodes, after_nodes, before_edges, after_edges,
        commit_message=config.commit_message,
    )
    if not diff.changes:
        print("Warning: no structural changes detected between source-before and source-after.")
        raise _NoChanges()
    # Serialize: handle GraphEdge objects in edge-type changes
    def _serialize_change(c) -> dict:
        d = {k: v for k, v in vars(c).items() if v is not None and k != "edge"}
        if c.edge is not None:
            d["edge"] = vars(c.edge)
        return d
    out = {
        "commit_message": diff.commit_message,
        "changes": [_serialize_change(c) for c in diff.changes],
    }
    (config.output_dir / "semantic_diff.json").write_text(json.dumps(out, indent=2))


def _stage4(config: Config) -> None:
    import json
    from llm.client import create_client
    from pipeline.graph import load_graph
    from pipeline.mapper import run_mapping

    graphs_dir = config.output_dir / "graphs"
    _, _ = load_graph(graphs_dir / "before.json")   # validate it loads
    dest_nodes, dest_edges = load_graph(graphs_dir / "dest.json")

    diff_data = json.loads((config.output_dir / "semantic_diff.json").read_text())
    from models.types import Change, SemanticDiff
    changes = [Change(**c) for c in diff_data["changes"]]
    diff = SemanticDiff(commit_message=diff_data["commit_message"], changes=changes)

    llm = create_client(config.model)
    result = run_mapping(
        semantic_diff=diff,
        dest_nodes=dest_nodes,
        dest_edges=dest_edges,
        fix_context=config.commit_message,
        llm_client=llm,
        output_dir=config.output_dir,
        max_context_nodes=config.max_context_nodes,
    )

    out = {
        "mappings": [
            {"source_change": vars(m.source_change),
             "destination_node": vars(m.destination_node),
             "confidence": m.confidence, "rationale": m.rationale}
            for m in result.mappings
        ],
        "unmappable": [
            {"source_change": vars(u.source_change), "reason": u.reason}
            for u in result.unmappable
        ],
    }
    (config.output_dir / "mapping.json").write_text(json.dumps(out, indent=2))


def _stage5(config: Config) -> None:
    import json
    from llm.client import create_client
    from pipeline.render import run_render
    from models.types import (
        Mapping, MappingResult, SourceChange, DestinationNode, UnmappableChange,
    )

    mapping_data = json.loads((config.output_dir / "mapping.json").read_text())
    mappings = [
        Mapping(
            source_change=SourceChange(**m["source_change"]),
            destination_node=DestinationNode(**m["destination_node"]),
            confidence=m["confidence"],
            rationale=m["rationale"],
        )
        for m in mapping_data["mappings"]
    ]
    unmappable = [
        UnmappableChange(
            source_change=SourceChange(**u["source_change"]),
            reason=u["reason"],
        )
        for u in mapping_data["unmappable"]
    ]
    result = MappingResult(mappings=mappings, unmappable=unmappable)

    if not mappings:
        print("Warning: all changes were unmappable. Writing FIX_PROPOSAL.md with no patch.")
        # Still write FIX_PROPOSAL.md so the user can see what was unmappable
        from pipeline.render import build_fix_proposal
        proposal = build_fix_proposal(
            mapping_result=result,
            branch_name="(none — all changes unmappable)",
            source_repo=config.source_repo, source_before_ref=config.source_before,
            source_after_ref=config.source_after, dest_repo=config.dest_repo,
            dest_base=config.dest_base, commit_message=config.commit_message,
        )
        (config.output_dir / "FIX_PROPOSAL.md").write_text(proposal)
        return   # exit 0

    llm = create_client(config.model)
    worktrees = {
        label: config.output_dir / "worktrees" / label
        for label in ("before", "after", "dest")
    }
    branch = run_render(
        mapping_result=result,
        worktrees=worktrees,
        dest_repo_path=Path(config.dest_repo),
        source_after_ref=config.source_after,
        llm_client=llm,
        output_dir=config.output_dir,
    )
    print(f"\nBranch created: {branch}")
    print(f"To push:  git -C {config.dest_repo} push origin {branch}")
    print(f"Review:   {config.output_dir / 'FIX_PROPOSAL.md'}")


STAGES: list[tuple[int, str, Callable[[Config], None]]] = [
    (1, "Checkout", _stage1),
    (2, "Graph Generation", _stage2),
    (3, "Semantic Diff", _stage3),
    (4, "LLM Fix Mapping", _stage4),
    (5, "Output Rendering", _stage5),
]


def run_pipeline(config: Config) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    start_stage = config.from_stage or 1

    for stage_num, stage_name, stage_fn in STAGES:
        if stage_num < start_stage:
            continue

        should_skip = (
            stage_num != config.force_stage
            and artifacts_exist(config.output_dir, stage_num)
        )
        if should_skip:
            print(f"[stage {stage_num}] Skipping {stage_name} (artifacts exist)")
            continue

        print(f"[stage {stage_num}] Running {stage_name} ...")
        try:
            stage_fn(config)
        except _NoChanges:
            return 0   # stage 3: no structural changes detected — exit 0 with warning
        except ValueError as exc:
            _write_error_log(config.output_dir, stage_num, stage_name, exc)
            return 2
        except Exception as exc:
            _write_error_log(config.output_dir, stage_num, stage_name, exc)
            return 1 if stage_num != 5 else 3

    return 0


def _write_error_log(output_dir: Path, stage_num: int, stage_name: str, exc: Exception) -> None:
    msg = f"Stage {stage_num} ({stage_name}) failed:\n{exc}\n"
    print(f"Error: {exc}", file=sys.stderr)
    (output_dir / "error.log").write_text(msg)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_runner.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Run full unit suite**

```bash
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pipeline/runner.py tests/unit/test_runner.py
git commit -m "feat: implement pipeline runner with per-stage artifact skipping"
```

---

## Task 9: Stage 1 — Checkout

**Files:**
- Create: `pipeline/checkout.py`
- Create: `tests/unit/test_checkout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_checkout.py
import subprocess
from pathlib import Path
import pytest
from pipeline.checkout import setup_worktrees, _ensure_local


def _make_bare_repo(path: Path, initial_file: str = "README.md") -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True)
    (path / initial_file).write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def test_ensure_local_returns_path_for_local_dir(tmp_path):
    result = _ensure_local(str(tmp_path), tmp_path / "clone")
    assert result == tmp_path


def test_setup_worktrees_creates_three_directories(tmp_path):
    src = _make_bare_repo(tmp_path / "src_repo")
    dst = _make_bare_repo(tmp_path / "dst_repo")

    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()
    # Create a second commit for "after"
    (src / "fix.py").write_text("fixed")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix"], cwd=src, check=True, capture_output=True)
    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()

    output_dir = tmp_path / "out"
    paths = setup_worktrees(
        source_repo=str(src),
        source_before=before_sha,
        source_after=after_sha,
        dest_repo=str(dst),
        dest_base="HEAD",
        output_dir=output_dir,
        keep_worktrees=True,
    )

    assert paths["before"].exists()
    assert paths["after"].exists()
    assert paths["dest"].exists()


def test_setup_worktrees_before_does_not_contain_fix(tmp_path):
    src = _make_bare_repo(tmp_path / "src_repo")
    dst = _make_bare_repo(tmp_path / "dst_repo")
    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()
    (src / "fix.py").write_text("fixed")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix"], cwd=src, check=True, capture_output=True)
    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()

    output_dir = tmp_path / "out"
    paths = setup_worktrees(
        source_repo=str(src), source_before=before_sha, source_after=after_sha,
        dest_repo=str(dst), dest_base="HEAD", output_dir=output_dir, keep_worktrees=True,
    )
    assert not (paths["before"] / "fix.py").exists()
    assert (paths["after"] / "fix.py").exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_checkout.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.checkout'`

- [ ] **Step 3: Implement `pipeline/checkout.py`**

```python
import atexit
import subprocess
from pathlib import Path


def setup_worktrees(
    source_repo: str,
    source_before: str,
    source_after: str,
    dest_repo: str,
    dest_base: str,
    output_dir: Path,
    keep_worktrees: bool = False,
) -> dict[str, Path]:
    clones_dir = output_dir / "clones"
    worktrees_dir = output_dir / "worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    source_local = _ensure_local(source_repo, clones_dir / "source")
    dest_local = _ensure_local(dest_repo, clones_dir / "dest")

    paths = {
        "before": worktrees_dir / "before",
        "after": worktrees_dir / "after",
        "dest": worktrees_dir / "dest",
    }
    created: list[tuple[Path, Path]] = []

    try:
        _add_worktree(source_local, paths["before"], source_before)
        created.append((source_local, paths["before"]))
        _add_worktree(source_local, paths["after"], source_after)
        created.append((source_local, paths["after"]))
        _add_worktree(dest_local, paths["dest"], dest_base)
        created.append((dest_local, paths["dest"]))
    except subprocess.CalledProcessError:
        for repo, path in created:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
                capture_output=True,
            )
        raise

    if not keep_worktrees:
        def _cleanup() -> None:
            for repo, path in created:
                subprocess.run(
                    ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
                    capture_output=True,
                )
        atexit.register(_cleanup)

    return paths


def _ensure_local(repo: str, clone_target: Path) -> Path:
    if repo.startswith("http") or repo.startswith("git@"):
        if not clone_target.exists():
            clone_target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", repo, str(clone_target)], check=True)
        return clone_target
    return Path(repo)


def _add_worktree(repo: Path, path: Path, ref: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(path), ref],
        check=True, capture_output=True,
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_checkout.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/checkout.py tests/unit/test_checkout.py
git commit -m "feat: implement stage 1 checkout with worktree management and atexit cleanup"
```

---

## Task 10: Stage 4 — LLM Fix Mapping

**Files:**
- Create: `pipeline/mapper.py`
- Create: `tests/fixtures/responses/mapping_valid.json`
- Create: `tests/fixtures/responses/mapping_invalid.json`
- Create: `tests/contract/test_llm_parsing.py`

- [ ] **Step 1: Create fixture response files**

```json
// tests/fixtures/responses/mapping_valid.json
{
  "mappings": [
    {
      "source_change": {"node_id": "src/auth.py::validate_token", "type": "node_modified"},
      "destination_node": {"file": "internal/auth/service.go", "symbol": "ValidateToken"},
      "confidence": "high",
      "rationale": "Same role in call graph — validates token before DB access"
    }
  ],
  "unmappable": [
    {
      "source_change": {"node_id": "src/auth.py::TokenCache"},
      "reason": "No structural equivalent found in destination graph"
    }
  ]
}
```

```
// tests/fixtures/responses/mapping_invalid.json
this is not json at all
```

- [ ] **Step 2: Write the failing contract test**

```python
# tests/contract/test_llm_parsing.py
from pathlib import Path
import pytest
from llm.client import MockLLMClient
from pipeline.mapper import _parse_mapping_response

RESPONSES = Path(__file__).parent.parent / "fixtures" / "responses"


def test_valid_json_parsed_into_mapping_result():
    raw = (RESPONSES / "mapping_valid.json").read_text()
    client = MockLLMClient(response=raw)
    result = _parse_mapping_response(raw, client)
    assert len(result.mappings) == 1
    assert result.mappings[0].confidence == "high"
    assert result.mappings[0].destination_node.symbol == "ValidateToken"
    assert len(result.unmappable) == 1


def test_invalid_json_triggers_retry():
    bad_json = "not json"
    valid_json = (RESPONSES / "mapping_valid.json").read_text()
    client = MockLLMClient(response=valid_json)
    # First call returns bad JSON, second call (via retry) returns valid JSON via client
    result = _parse_mapping_response(bad_json, client)
    assert client.call_count == 1   # one retry call was made
    assert len(result.mappings) == 1


def test_invalid_json_twice_raises_value_error():
    client = MockLLMClient(response="still not json")
    with pytest.raises(ValueError, match="unparseable after retry"):
        _parse_mapping_response("not json", client)


def test_unmappable_source_change_has_no_type_required():
    raw = (RESPONSES / "mapping_valid.json").read_text()
    client = MockLLMClient(response=raw)
    result = _parse_mapping_response(raw, client)
    # unmappable entries have no "type" field in source_change
    assert result.unmappable[0].source_change.type == ""
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/contract/test_llm_parsing.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.mapper'`

- [ ] **Step 4: Implement `pipeline/mapper.py`**

```python
import json
from pathlib import Path

from models.types import (
    DestinationNode, GraphEdge, GraphNode, Mapping, MappingResult,
    SemanticDiff, SourceChange, UnmappableChange,
)

_MAPPING_PROMPT = """\
You are a senior engineer porting a bug fix between two codebases.

## The Fix
{fix_context}

## What Changed (Semantic Diff)
{semantic_diff_json}

## Destination Codebase Graph
{dest_graph_json}

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
{{
  "mappings": [
    {{
      "source_change": {{"node_id": "...", "type": "..."}},
      "destination_node": {{"file": "...", "symbol": "..."}},
      "confidence": "high|medium|low",
      "rationale": "..."
    }}
  ],
  "unmappable": [
    {{
      "source_change": {{"node_id": "..."}},
      "reason": "..."
    }}
  ]
}}"""


def run_mapping(
    semantic_diff: SemanticDiff,
    dest_nodes: dict[str, GraphNode],
    dest_edges: list[GraphEdge],
    fix_context: str,
    llm_client,
    output_dir: Path,
    max_context_nodes: int = 500,
) -> MappingResult:
    from pipeline.pruning import load_god_nodes, prune_graph

    changed_symbols = {c.symbol for c in semantic_diff.changes if c.symbol}
    god_nodes = load_god_nodes(output_dir / "graphs" / "dest_report.md")
    pruned = prune_graph(dest_nodes, dest_edges, changed_symbols, god_nodes, max_context_nodes)

    changes_json = json.dumps(
        [{k: v for k, v in vars(c).items() if v is not None} for c in semantic_diff.changes],
        indent=2,
    )
    dest_json = json.dumps(
        {nid: vars(node) for nid, node in pruned.items()},
        indent=2,
    )
    prompt = _MAPPING_PROMPT.format(
        fix_context=fix_context or "(none provided)",
        semantic_diff_json=changes_json,
        dest_graph_json=dest_json,
    )

    response = llm_client.complete(prompt)
    raw_path = output_dir / "mapping_raw.txt"
    result = _parse_mapping_response(response, llm_client, raw_path=raw_path)
    return result


def _parse_mapping_response(
    response: str, llm_client, raw_path: Path | None = None
) -> MappingResult:
    try:
        return _build_mapping_result(json.loads(response))
    except json.JSONDecodeError:
        retry_prompt = (
            "Your previous response was not valid JSON. Respond with JSON only.\n"
            + response
        )
        response2 = llm_client.complete(retry_prompt)
        try:
            return _build_mapping_result(json.loads(response2))
        except json.JSONDecodeError as exc:
            if raw_path:
                raw_path.write_text(response2)
            raise ValueError("LLM response unparseable after retry") from exc


def _build_mapping_result(data: dict) -> MappingResult:
    mappings = [
        Mapping(
            source_change=SourceChange(**m["source_change"]),
            destination_node=DestinationNode(**m["destination_node"]),
            confidence=m["confidence"],
            rationale=m["rationale"],
        )
        for m in data.get("mappings", [])
    ]
    unmappable = [
        UnmappableChange(
            source_change=SourceChange(**u["source_change"]),
            reason=u["reason"],
        )
        for u in data.get("unmappable", [])
    ]
    return MappingResult(mappings=mappings, unmappable=unmappable)
```

- [ ] **Step 5: Run contract tests**

```bash
pytest tests/contract/test_llm_parsing.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add pipeline/mapper.py tests/contract/test_llm_parsing.py \
        tests/fixtures/responses/
git commit -m "feat: implement stage 4 LLM fix mapping with JSON retry logic"
```

---

## Task 11: Stage 5 — Output Rendering

**Files:**
- Create: `pipeline/render.py`
- Create: `tests/unit/test_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_render.py
import subprocess
from pathlib import Path
from models.types import (
    DestinationNode, Mapping, MappingResult, SourceChange, UnmappableChange,
)
from llm.client import MockLLMClient
from pipeline.render import build_fix_proposal, generate_patch_content


def _mapping_result() -> MappingResult:
    return MappingResult(
        mappings=[
            Mapping(
                source_change=SourceChange(
                    node_id="src/auth.py::validate_token", type="node_modified"
                ),
                destination_node=DestinationNode(
                    file="internal/auth/service.go", symbol="ValidateToken"
                ),
                confidence="high",
                rationale="Same role in call graph",
            )
        ],
        unmappable=[
            UnmappableChange(
                source_change=SourceChange(node_id="src/auth.py::TokenCache"),
                reason="No structural equivalent",
            )
        ],
    )


def test_fix_proposal_contains_branch_name():
    proposal = build_fix_proposal(
        mapping_result=_mapping_result(),
        branch_name="graph-merge/port-abc1234-20260521",
        source_repo="/src",
        source_before_ref="abc^",
        source_after_ref="abc1234",
        dest_repo="/dest",
        dest_base="main",
        commit_message="fix: add warning for invalid token",
    )
    assert "graph-merge/port-abc1234-20260521" in proposal


def test_fix_proposal_contains_mappings_table():
    proposal = build_fix_proposal(
        mapping_result=_mapping_result(),
        branch_name="graph-merge/port-abc1234-20260521",
        source_repo="/src", source_before_ref="abc^", source_after_ref="abc1234",
        dest_repo="/dest", dest_base="main", commit_message="",
    )
    assert "ValidateToken" in proposal
    assert "high" in proposal


def test_fix_proposal_contains_unmappable_section():
    proposal = build_fix_proposal(
        mapping_result=_mapping_result(),
        branch_name="graph-merge/port-abc1234-20260521",
        source_repo="/src", source_before_ref="abc^", source_after_ref="abc1234",
        dest_repo="/dest", dest_base="main", commit_message="",
    )
    assert "TokenCache" in proposal
    assert "No structural equivalent" in proposal


def test_patch_content_written_from_llm_response(tmp_path):
    after_dir = tmp_path / "after"
    dest_dir = tmp_path / "dest"
    (after_dir / "src").mkdir(parents=True)
    (dest_dir / "internal" / "auth").mkdir(parents=True)
    (after_dir / "src" / "auth.py").write_text("def validate_token(): pass")
    (dest_dir / "internal" / "auth" / "service.go").write_text(
        "func ValidateToken() bool { return true }"
    )

    worktrees = {"after": after_dir, "dest": dest_dir}
    client = MockLLMClient(
        response="func ValidateToken() bool {\n    log.Warn()\n    return true\n}"
    )
    generate_patch_content(
        mapping_result=_mapping_result(),
        worktrees=worktrees,
        llm_client=client,
    )
    assert client.call_count == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_render.py -v
```

Expected: `ModuleNotFoundError: No module named 'pipeline.render'`

- [ ] **Step 3: Implement `pipeline/render.py`**

```python
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models.types import MappingResult

_RENDER_PROMPT = """\
You are applying a bug fix to a destination codebase file.

## Source changes (from the fixed version):
{source_snippets}

## Mapping rationales:
{rationales}

## Destination file (current content):
```
{dest_file_content}
```

Apply the equivalent changes to the destination file. Output ONLY the modified \
file content — no explanation, no markdown fences."""


def run_render(
    mapping_result: MappingResult,
    worktrees: dict[str, Path],
    dest_repo_path: Path,
    source_after_ref: str,
    llm_client,
    output_dir: Path,
) -> str:
    new_contents = generate_patch_content(mapping_result, worktrees, llm_client)

    for dest_file, content in new_contents.items():
        dest_path = worktrees["dest"] / dest_file
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(content)

    patch_result = subprocess.run(
        ["git", "diff"], capture_output=True, text=True, cwd=str(worktrees["dest"])
    )
    unmappable_comment = ""
    if mapping_result.unmappable:
        lines = ["# graph-merge: unmappable changes (not applied)"]
        for u in mapping_result.unmappable:
            lines.append(f"#   {u.source_change.node_id}: {u.reason}")
        unmappable_comment = "\n".join(lines) + "\n"
    patch_path = output_dir / "fix.patch"
    patch_path.write_text(unmappable_comment + patch_result.stdout)

    sha = source_after_ref[:7]
    timestamp = datetime.now().strftime("%Y%m%d")
    branch_name = f"graph-merge/port-{sha}-{timestamp}"

    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=str(dest_repo_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-am", f"graph-merge: port fix from {source_after_ref}"],
        cwd=str(dest_repo_path), check=False, capture_output=True,
    )

    proposal = build_fix_proposal(
        mapping_result=mapping_result,
        branch_name=branch_name,
        source_repo=str(dest_repo_path),
        source_before_ref="",
        source_after_ref=source_after_ref,
        dest_repo=str(dest_repo_path),
        dest_base="",
        commit_message="",
    )
    (output_dir / "FIX_PROPOSAL.md").write_text(proposal)

    return branch_name


def generate_patch_content(
    mapping_result: MappingResult,
    worktrees: dict[str, Path],
    llm_client,
) -> dict[str, str]:
    by_dest_file: dict[str, list] = defaultdict(list)
    for mapping in mapping_result.mappings:
        by_dest_file[mapping.destination_node.file].append(mapping)

    results: dict[str, str] = {}
    for dest_file, mappings in by_dest_file.items():
        dest_path = worktrees["dest"] / dest_file
        if not dest_path.exists():
            continue
        dest_content = dest_path.read_text()

        source_snippets: list[str] = []
        rationales: list[str] = []
        for m in mappings:
            if "::" in m.source_change.node_id:
                src_file = m.source_change.node_id.split("::")[0]
                src_path = worktrees["after"] / src_file
                if src_path.exists():
                    source_snippets.append(f"# {src_file}\n{src_path.read_text()}")
            rationales.append(
                f"- {m.source_change.node_id} → {m.destination_node.symbol}: {m.rationale}"
            )

        prompt = _RENDER_PROMPT.format(
            source_snippets="\n\n".join(source_snippets) or "(none)",
            rationales="\n".join(rationales),
            dest_file_content=dest_content,
        )
        results[dest_file] = llm_client.complete(prompt)

    return results


def build_fix_proposal(
    mapping_result: MappingResult,
    branch_name: str,
    source_repo: str,
    source_before_ref: str,
    source_after_ref: str,
    dest_repo: str,
    dest_base: str,
    commit_message: str,
) -> str:
    rows = "\n".join(
        f"| {m.source_change.node_id} | "
        f"{m.destination_node.file}::{m.destination_node.symbol} | "
        f"{m.confidence} | {m.rationale} |"
        for m in mapping_result.mappings
    )
    unmappable_lines = "\n".join(
        f"- `{u.source_change.node_id}`: {u.reason}"
        for u in mapping_result.unmappable
    ) or "_None_"

    return f"""# Fix Proposal
Source: {source_repo} {source_before_ref} → {source_after_ref}
Destination: {dest_repo} {dest_base}
Branch: {branch_name}

## Summary
{commit_message or "(no commit message provided)"}

## Mappings
| Source | Destination | Confidence | Rationale |
|--------|-------------|------------|-----------|
{rows}

## Unmappable Changes
{unmappable_lines}

## Next Steps
1. Review the mappings above and `fix.patch`
2. Test the branch: `{branch_name}`
3. Push and open a PR
"""
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_render.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/render.py tests/unit/test_render.py
git commit -m "feat: implement stage 5 output rendering (patch, FIX_PROPOSAL.md, branch)"
```

---

## Task 12: BDD Integration Tests

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_pipeline.py`

- [ ] **Step 1: Write `tests/integration/conftest.py`**

```python
# tests/integration/conftest.py
import json
import subprocess
from pathlib import Path
import pytest
from llm.client import MockLLMClient

FIXTURE_GRAPHS = Path(__file__).parent.parent / "fixtures" / "graphs"
FIXTURE_RESPONSES = Path(__file__).parent.parent / "fixtures" / "responses"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True)


@pytest.fixture
def python_source_repo(tmp_path):
    repo = tmp_path / "py_source"
    repo.mkdir()
    _init_repo(repo)
    (repo / "src").mkdir()
    (repo / "src" / "auth.py").write_text(
        "def validate_token(token):\n    return db.query(token)\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    (repo / "src" / "auth.py").write_text(
        "def validate_token(token):\n"
        "    result = db.query(token)\n"
        "    if not result:\n"
        "        logger.warn('Invalid token')  # WHY: audit trail\n"
        "    return result\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: add warning for invalid token"],
        cwd=repo, check=True, capture_output=True,
    )
    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    return repo, before_sha, after_sha


@pytest.fixture
def go_dest_repo(tmp_path):
    repo = tmp_path / "go_dest"
    repo.mkdir()
    _init_repo(repo)
    service = repo / "internal" / "auth" / "service.go"
    service.parent.mkdir(parents=True)
    service.write_text(
        "package auth\n\nfunc (s *Service) ValidateToken(token string) bool {\n"
        "    return s.db.QueryRow(token) != nil\n}\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def mock_llm_mapping():
    return MockLLMClient(
        response=(FIXTURE_RESPONSES / "mapping_valid.json").read_text()
    )


@pytest.fixture
def mock_llm_render():
    return MockLLMClient(
        response=(
            "package auth\n\nfunc (s *Service) ValidateToken(token string) bool {\n"
            "    result := s.db.QueryRow(token) != nil\n"
            "    if !result { log.Warn(\"Invalid token\") }\n"
            "    return result\n}\n"
        )
    )
```

- [ ] **Step 2: Write `tests/integration/test_pipeline.py`**

```python
# tests/integration/test_pipeline.py
"""
Feature: Port a bug fix between codebases using code knowledge graphs

These tests drive the full pipeline with:
  - Real git repos (fixture repos built in conftest.py)
  - Fixture graph JSON files (bypass real Graphify invocation)
  - Mock LLM client (bypass real API calls)
"""
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from models.config import Config
from pipeline.runner import run_pipeline

FIXTURE_GRAPHS = Path(__file__).parent.parent / "fixtures" / "graphs"

pytestmark = pytest.mark.integration


def _config(tmp_path, src_repo, before_sha, after_sha, go_repo, mock_llm_mapping, mock_llm_render):
    return Config(
        source_repo=str(src_repo),
        source_before=before_sha,
        source_after=after_sha,
        dest_repo=str(go_repo),
        dest_base="HEAD",
        model="claude/claude-opus-4-7",
        output_dir=tmp_path / "out",
        commit_message="fix: add warning for invalid token",
        max_context_nodes=500,
        keep_worktrees=True,
        from_stage=None,
        force_stage=None,
    )


def _stub_graphs(output_dir: Path) -> None:
    graphs_dir = output_dir / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    for label in ("before", "after", "dest"):
        shutil.copy(FIXTURE_GRAPHS / f"{label}.json", graphs_dir / f"{label}.json")


@pytest.mark.integration
class TestGraphMergePipeline:

    def test_given_python_source_and_go_dest_when_pipeline_runs_then_fix_proposal_created(
        self, python_source_repo, go_dest_repo, tmp_path,
        mock_llm_mapping, mock_llm_render,
    ):
        """
        Scenario: Full pipeline produces FIX_PROPOSAL.md
          Given a Python source repo with a committed bug fix
          And a Go destination repo
          When graph-merge stages 3-5 run (stages 1-2 bypassed via fixture graphs)
          Then FIX_PROPOSAL.md exists in the output directory
          And it contains at least one mapping
        """
        src_repo, before_sha, after_sha = python_source_repo
        config = _config(
            tmp_path, src_repo, before_sha, after_sha, go_dest_repo,
            mock_llm_mapping, mock_llm_render,
        )

        # Stage 1: create real worktrees
        from pipeline.checkout import setup_worktrees
        setup_worktrees(
            source_repo=str(src_repo),
            source_before=before_sha,
            source_after=after_sha,
            dest_repo=str(go_dest_repo),
            dest_base="HEAD",
            output_dir=config.output_dir,
            keep_worktrees=True,
        )

        # Stage 2: stub with fixture graphs
        _stub_graphs(config.output_dir)

        with patch("pipeline.runner._stage1", lambda c: None), \
             patch("pipeline.runner._stage2", lambda c: None), \
             patch("pipeline.mapper.run_mapping", return_value=mock_llm_mapping) as mock_map, \
             patch("llm.client.create_client", return_value=mock_llm_mapping):
            # Re-run from stage 3
            config.from_stage = 3
            exit_code = run_pipeline(config)

        assert (config.output_dir / "FIX_PROPOSAL.md").exists()

    def test_given_all_artifacts_exist_when_pipeline_runs_then_no_stages_execute(
        self, python_source_repo, go_dest_repo, tmp_path,
        mock_llm_mapping, mock_llm_render,
    ):
        """
        Scenario: Stage skipping
          Given all stage artifacts exist on disk
          When graph-merge runs
          Then no stage functions are called
        """
        src_repo, before_sha, after_sha = python_source_repo
        config = _config(
            tmp_path, src_repo, before_sha, after_sha, go_dest_repo,
            mock_llm_mapping, mock_llm_render,
        )
        out = config.output_dir
        out.mkdir(parents=True)
        for label in ("before", "after", "dest"):
            (out / "worktrees" / label).mkdir(parents=True)
            (out / "graphs").mkdir(exist_ok=True)
            (out / "graphs" / f"{label}.json").write_text("{}")
        (out / "semantic_diff.json").write_text("{}")
        (out / "mapping.json").write_text("{}")
        (out / "fix.patch").write_text("")
        (out / "FIX_PROPOSAL.md").write_text("")

        called = []
        with patch("pipeline.runner._stage1", side_effect=lambda c: called.append(1)), \
             patch("pipeline.runner._stage2", side_effect=lambda c: called.append(2)), \
             patch("pipeline.runner._stage3", side_effect=lambda c: called.append(3)), \
             patch("pipeline.runner._stage4", side_effect=lambda c: called.append(4)), \
             patch("pipeline.runner._stage5", side_effect=lambda c: called.append(5)):
            run_pipeline(config)

        assert called == []

    def test_given_partial_run_when_semantic_diff_deleted_and_rerun_then_stage3_reruns(
        self, python_source_repo, go_dest_repo, tmp_path,
        mock_llm_mapping, mock_llm_render,
    ):
        """
        Scenario: Re-run after deleting artifact resumes from correct stage
          Given stages 1 and 2 artifacts exist
          And semantic_diff.json does not exist
          When graph-merge runs
          Then stage 3 runs (and stages 1 and 2 are skipped)
        """
        src_repo, before_sha, after_sha = python_source_repo
        config = _config(
            tmp_path, src_repo, before_sha, after_sha, go_dest_repo,
            mock_llm_mapping, mock_llm_render,
        )
        out = config.output_dir
        out.mkdir(parents=True)
        for label in ("before", "after", "dest"):
            (out / "worktrees" / label).mkdir(parents=True)
            (out / "graphs").mkdir(exist_ok=True)
            (out / "graphs" / f"{label}.json").write_text(
                (FIXTURE_GRAPHS / f"{label}.json").read_text()
            )
        # No semantic_diff.json — stage 3 must run

        called = []
        with patch("pipeline.runner._stage1", side_effect=lambda c: called.append(1)), \
             patch("pipeline.runner._stage2", side_effect=lambda c: called.append(2)), \
             patch("pipeline.runner._stage4", side_effect=lambda c: called.append(4)), \
             patch("pipeline.runner._stage5", side_effect=lambda c: called.append(5)):
            run_pipeline(config)

        assert 1 not in called
        assert 2 not in called
        assert 3 not in called  # stage 3 ran for real (not patched)
        assert (out / "semantic_diff.json").exists()
```

- [ ] **Step 3: Run integration tests**

```bash
pytest tests/integration/ -v -m integration
```

Expected: `3 passed` (may require `--keep-worktrees` git worktree cleanup if re-run).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/ tests/fixtures/responses/
git commit -m "test: add BDD integration tests for pipeline stage skipping and full run"
```

---

## Task 13: Contract Test — Graphify Output Parsing

**Files:**
- Create: `tests/contract/test_graphify_output.py`

- [ ] **Step 1: Write the contract test**

```python
# tests/contract/test_graphify_output.py
"""
Contract tests that verify pipeline/graph.py correctly parses
whatever Graphify actually emits. Skipped if Graphify is not installed.
"""
import subprocess
import sys
from pathlib import Path
import pytest
from pipeline.graph import generate_graph, load_graph

pytestmark = pytest.mark.contract


def _graphify_available() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "graphify.extract", "--help"],
        capture_output=True,
    )
    return result.returncode == 0


@pytest.fixture
def tiny_python_repo(tmp_path):
    repo = tmp_path / "tiny"
    repo.mkdir()
    (repo / "auth.py").write_text(
        "def validate(token):\n    return token == 'secret'\n"
    )
    return repo


@pytest.mark.skipif(not _graphify_available(), reason="Graphify not installed")
def test_generate_graph_produces_parseable_json(tiny_python_repo, tmp_path):
    out = tmp_path / "graph.json"
    generate_graph(tiny_python_repo, out, label="test")
    assert out.exists(), "generate_graph must produce graph.json"
    nodes, edges = load_graph(out)
    assert isinstance(nodes, dict)
    assert isinstance(edges, list)


@pytest.mark.skipif(not _graphify_available(), reason="Graphify not installed")
def test_generated_nodes_have_required_fields(tiny_python_repo, tmp_path):
    out = tmp_path / "graph.json"
    generate_graph(tiny_python_repo, out, label="test")
    nodes, _ = load_graph(out)
    for node_id, node in nodes.items():
        assert node.id, f"Node {node_id} missing id"
        assert node.file, f"Node {node_id} missing file"
        assert node.symbol, f"Node {node_id} missing symbol"
        assert node.kind, f"Node {node_id} missing kind"
```

- [ ] **Step 2: Run (expect skip if Graphify not installed)**

```bash
pytest tests/contract/test_graphify_output.py -v -m contract
```

Expected: `2 skipped` (or `2 passed` if Graphify is installed).

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_graphify_output.py
git commit -m "test: add contract tests for Graphify output parsing"
```

---

## Task 14: Full Unit Test Coverage Run and Gap Fix

- [ ] **Step 1: Run full test suite and check coverage**

```bash
pytest tests/ -v --cov=. --cov-report=term-missing \
       --ignore=tests/contract -m "not contract"
```

- [ ] **Step 2: Identify uncovered lines**

Review the `MISS` column output. Typical gaps at this point:
- `cli.py:main()` — needs a smoke test
- `pipeline/runner.py` error log path
- `pipeline/checkout.py` URL clone path

- [ ] **Step 3: Add missing coverage for `cli.py:main()`**

```python
# Add to tests/unit/test_cli.py
from unittest.mock import patch

def test_main_calls_run_pipeline(tmp_path):
    with patch("sys.argv", [
        "graph-merge",
        "--source-repo", str(tmp_path),
        "--source-fix-commit", "abc",
        "--dest-repo", str(tmp_path),
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-7",
        "--output", str(tmp_path / "out"),
    ]), patch("pipeline.runner.run_pipeline", return_value=0) as mock_run, \
       patch("sys.exit") as mock_exit:
        from cli import main
        main()
        assert mock_run.called
        mock_exit.assert_called_with(0)
```

- [ ] **Step 4: Add missing coverage for error log path**

```python
# Add to tests/unit/test_runner.py
def test_failed_stage_writes_error_log(tmp_path):
    config = _config(tmp_path)

    def bad_stage(c):
        raise RuntimeError("something broke")

    with patch("pipeline.runner.STAGES", [(1, "Checkout", bad_stage)]):
        exit_code = run_pipeline(config)

    assert exit_code == 1
    assert (tmp_path / "error.log").exists()
    assert "something broke" in (tmp_path / "error.log").read_text()
```

- [ ] **Step 5: Re-run and confirm coverage improved**

```bash
pytest tests/unit/ tests/integration/ -v --cov=. --cov-report=term-missing \
       -m "not contract"
```

Expected: coverage above 85% for all source files.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_cli.py tests/unit/test_runner.py
git commit -m "test: fill coverage gaps in cli.main() and runner error handling"
```

---

## Task 15: README and Graph Schema Discovery

**Files:**
- Create: `README.md`
- Modify: `pipeline/graph.py` (add `discover_schema`)

- [ ] **Step 1: Add schema discovery to `pipeline/graph.py`**

Add this function — called once when `docs/graph_schema.md` doesn't exist:

```python
def discover_and_write_schema(graph_path: Path, schema_doc_path: Path) -> None:
    """Infer graph.json schema from a real Graphify output and write docs/graph_schema.md."""
    if schema_doc_path.exists():
        return
    nodes, edges = load_graph(graph_path)
    if not nodes:
        return

    sample_node = next(iter(nodes.values()))
    node_fields = list(vars(sample_node).keys())
    edge_fields = list(vars(edges[0]).keys()) if edges else []

    schema_doc_path.parent.mkdir(parents=True, exist_ok=True)
    schema_doc_path.write_text(
        f"# graph.json Schema\n\n"
        f"_Auto-generated from first successful Graphify run._\n\n"
        f"## Node Fields\n"
        + "\n".join(f"- `{f}`" for f in node_fields)
        + f"\n\n## Edge Fields\n"
        + "\n".join(f"- `{f}`" for f in edge_fields)
        + "\n\n## Sample Node\n\n```json\n"
        + __import__("json").dumps(vars(sample_node), indent=2)
        + "\n```\n"
    )
```

Call it from `_stage2` in `pipeline/runner.py` after graph generation:

```python
# In _stage2, after the generate_graph loop:
from pipeline.graph import discover_and_write_schema
schema_path = Path("docs/graph_schema.md")
discover_and_write_schema(graphs_dir / "before.json", schema_path)
```

- [ ] **Step 2: Write `README.md`**

```markdown
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
  --model claude/claude-opus-4-7
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
| `--model` | _required_ | `<provider>/<model-id>` — e.g. `claude/claude-opus-4-7` |
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
| 0 | Success, branch created |
| 1 | Stage failure |
| 2 | LLM response unparseable after retry |
| 3 | `git apply` failed; `fix.patch` written but branch not created |

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
| Anthropic | `claude/<model-id>` | `claude/claude-opus-4-7` |
| OpenAI | `openai/<model-id>` | `openai/gpt-4o` |
| Gemini | `gemini/<model-id>` | `gemini/gemini-2.0-flash` |

Set the relevant API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) before running.

## Development

```bash
pytest tests/unit tests/integration -v          # fast tests (no real LLM)
pytest tests/contract -v -m contract            # requires Graphify + real API keys
```
```

- [ ] **Step 3: Run full test suite one final time**

```bash
pytest tests/ -v -m "not contract"
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add README.md pipeline/graph.py pipeline/runner.py
git commit -m "docs: add README and graph schema auto-discovery"
```

---

## Task 16: Final Wiring and Smoke Test

- [ ] **Step 1: Verify `graph-merge --help` works**

```bash
pip install -e .
graph-merge --help
```

Expected output (excerpt):
```
usage: graph-merge [-h] --source-repo PATH|URL [--source-fix-commit SHA] ...
```

- [ ] **Step 2: Run a dry-run with `--from-stage 5` against fixture artifacts**

```bash
mkdir -p /tmp/gm-smoke/worktrees/{before,after,dest}
mkdir -p /tmp/gm-smoke/graphs
cp tests/fixtures/graphs/before.json /tmp/gm-smoke/graphs/
cp tests/fixtures/graphs/after.json /tmp/gm-smoke/graphs/
cp tests/fixtures/graphs/dest.json /tmp/gm-smoke/graphs/
echo '{"commit_message":"fix","changes":[]}' > /tmp/gm-smoke/semantic_diff.json
cp tests/fixtures/responses/mapping_valid.json /tmp/gm-smoke/mapping.json
```

The above pre-stages all artifacts so only stage 5 would run. Confirm stage 5 is skipped too once `fix.patch` and `FIX_PROPOSAL.md` exist.

- [ ] **Step 3: Run final full test suite with coverage report**

```bash
pytest tests/ -v -m "not contract" --cov=. --cov-report=term-missing
```

Expected: all pass, coverage ≥ 85%.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final wiring verification and smoke test artifacts"
```

---

## Code Review Plan

### PR Structure

Split work into four PRs, in order:

| PR | Scope | Key review focus |
|----|-------|-----------------|
| PR 1 | Tasks 1–3 (scaffold, models, LLM client) | Type correctness, Protocol interface, mock fidelity |
| PR 2 | Tasks 4–7 (CLI, runner, graph loading, diff) | Arg expansion logic, artifact skipping, ID fallback matching |
| PR 3 | Tasks 8–11 (pruning, checkout, mapper, render) | atexit safety, 2-hop BFS correctness, prompt quality, patch generation |
| PR 4 | Tasks 12–16 (tests, docs, final wiring) | BDD scenario completeness, contract test skip logic, README accuracy |

### Review Checklist

**Security (NFR-1)**
- [ ] `create_client()` only constructs a provider client after `--model` is explicitly passed — no default provider
- [ ] No code is sent to an external service in stages 1–3
- [ ] `atexit` cleanup does not read or write code — only removes worktree dirs

**Correctness**
- [ ] `--source-fix-commit` expansion: `args.source_before == f"{sha}^"` and `args.source_after == sha`
- [ ] Mutual exclusivity of `--source-fix-commit` vs `--source-before`/`--source-after` enforced with `sys.exit(1)`
- [ ] Stage skipping: `force_stage` overrides artifact check; `from_stage` skips earlier stages entirely
- [ ] Diff ID fallback: when `before_ids` and `after_ids` are disjoint but `(file, symbol, kind)` matches, result has `node_modified` not `node_added` + `node_removed`
- [ ] `_parse_mapping_response`: exactly one retry, then raises `ValueError` (not silent failure)

**LLM Prompt Quality**
- [ ] Mapping prompt includes `fix_context`, the full diff, and the pruned destination graph
- [ ] Mapping prompt explicitly specifies confidence must be one of `"high" | "medium" | "low"`
- [ ] Render prompt asks for file content only — no markdown fences, no explanation
- [ ] Both prompts use double-brace escaping `{{}}` for JSON schema literals in f-strings

**Error handling**
- [ ] Every stage failure writes to `error.log` before returning non-zero
- [ ] `git apply` failure in stage 5 returns exit code 3 and leaves `fix.patch` on disk
- [ ] LLM auth failure (missing env var) exits 1 with a helpful message about the missing key

**Testing**
- [ ] All unit tests use `MockLLMClient` — no real API calls
- [ ] Integration tests patch `_stage1` / `_stage2` when real Graphify is not available
- [ ] Contract tests are marked `@pytest.mark.contract` and skip gracefully when Graphify absent
- [ ] Each BDD scenario has an explicit Given/When/Then docstring

**Documentation**
- [ ] `README.md` lists all CLI flags with types and defaults
- [ ] `docs/graph_schema.md` is committed after first real Graphify run (not in repo initially)
- [ ] `FIX_PROPOSAL.md` template in `render.py` matches the spec exactly (branch name format, table columns)

---

*Plan complete. All tasks follow TDD (failing test → implementation → passing test → commit). BDD scenarios are in `tests/integration/test_pipeline.py` with Given/When/Then docstrings. Contract tests isolate Graphify and LLM dependencies with skip guards.*
