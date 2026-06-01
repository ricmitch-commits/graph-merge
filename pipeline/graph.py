import json
import subprocess
import sys
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
    # Handle both our fixture schema and real Graphify output schema.
    # Graphify uses: label, source_file, source_location, file_type
    # Our fixtures use: file, symbol, kind, calls, imports, properties
    label = data.get("label", "")
    source_file = data.get("source_file", data.get("file", ""))

    # Derive symbol: strip trailing "()" from Graphify function labels
    symbol = data.get("symbol", data.get("name", ""))
    if not symbol and label:
        symbol = label.rstrip("()").strip().rstrip("(").strip()

    # Derive kind from label suffix or explicit field
    kind = data.get("kind", data.get("type", ""))
    if not kind and label:
        if label.endswith("()"):
            kind = "function"
        elif label.endswith((".py", ".go", ".js", ".ts", ".java", ".c", ".cpp", ".rs")):
            kind = "module"

    # Node id: prefer explicit id field over the key passed in
    nid = data.get("id", node_id) or node_id

    known = {
        "id", "file", "symbol", "name", "kind", "type", "calls", "imports", "properties",
        "label", "source_file", "source_location", "file_type", "weight",
    }
    explicit_props = data.get("properties", {})
    extra_props = {k: v for k, v in data.items() if k not in known}

    return GraphNode(
        id=nid,
        file=source_file,
        symbol=symbol,
        kind=kind,
        calls=data.get("calls", []),
        imports=data.get("imports", []),
        properties={**explicit_props, **extra_props},
    )


def generate_graph(worktree_path: Path, output_path: Path, label: str) -> None:
    """Run Graphify on worktree_path and write the JSON graph to output_path.

    Graphify writes its output to stdout; source_file paths in the output are
    absolute (rooted at worktree_path) and are made relative before saving.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    result = subprocess.run(
        [py, "-m", "graphify.extract", str(worktree_path.resolve())],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "No module named 'graphify'" in stderr or "No module named 'tree_sitter'" in stderr:
            raise RuntimeError(
                "Graphify is not installed in the active Python environment.\n"
                f"Run: {py} -m pip install graphifyy\n\n{stderr}"
            )
        raise RuntimeError(f"Graphify failed:\n{stderr}")

    # Make source_file paths relative to the worktree so they're portable
    data = json.loads(result.stdout)
    worktree_abs = str(worktree_path.resolve())
    for node in data.get("nodes", []):
        sf = node.get("source_file", "")
        if sf.startswith(worktree_abs):
            node["source_file"] = sf[len(worktree_abs):].lstrip("/")
    for edge in data.get("edges", []):
        sf = edge.get("source_file", "")
        if sf.startswith(worktree_abs):
            edge["source_file"] = sf[len(worktree_abs):].lstrip("/")

    output_path.write_text(json.dumps(data, indent=2))


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
