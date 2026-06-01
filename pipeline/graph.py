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
    known = {"id", "file", "symbol", "name", "kind", "type", "calls", "imports", "properties"}
    explicit_props = data.get("properties", {})
    extra_props = {k: v for k, v in data.items() if k not in known}
    return GraphNode(
        id=node_id or data.get("id", ""),
        file=data.get("file", ""),
        symbol=data.get("symbol", data.get("name", "")),
        kind=data.get("kind", data.get("type", "")),
        calls=data.get("calls", []),
        imports=data.get("imports", []),
        properties={**explicit_props, **extra_props},
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


def discover_and_write_schema(graph_path: Path, schema_doc_path: Path) -> None:
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
        "# graph.json Schema\n\n"
        "_Auto-generated from first successful Graphify run._\n\n"
        "## Node Fields\n"
        + "\n".join(f"- `{f}`" for f in node_fields)
        + "\n\n## Edge Fields\n"
        + "\n".join(f"- `{f}`" for f in edge_fields)
        + "\n\n## Sample Node\n\n```json\n"
        + json.dumps(vars(sample_node), indent=2)
        + "\n```\n"
    )
