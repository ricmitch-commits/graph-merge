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

    def _serialize_change(c) -> dict:
        d = {k: v for k, v in vars(c).items() if v is not None and k != "edge"}
        if c.edge is not None:
            d["edge"] = vars(c.edge)
        return d

    changes_json = json.dumps(
        [_serialize_change(c) for c in semantic_diff.changes],
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
    return _parse_mapping_response(response, llm_client, raw_path=raw_path)


def _extract_json(text: str) -> str:
    """Strip markdown code fences and find the outermost JSON object."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Find first { in case there's still a preamble
    start = text.find("{")
    if start != -1:
        text = text[start:]
    return text


def _parse_mapping_response(
    response: str, llm_client, raw_path: Path | None = None
) -> MappingResult:
    try:
        return _build_mapping_result(json.loads(_extract_json(response)))
    except json.JSONDecodeError:
        retry_prompt = (
            "Your previous response was not valid JSON. "
            "Respond with a raw JSON object only — no markdown, no code fences.\n"
            + response
        )
        response2 = llm_client.complete(retry_prompt)
        try:
            return _build_mapping_result(json.loads(_extract_json(response2)))
        except json.JSONDecodeError as exc:
            if raw_path:
                raw_path.write_text(response2)
            raise ValueError(
                f"LLM response unparseable after retry"
                + (f" (saved to {raw_path})" if raw_path else "")
            ) from exc


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
