from pathlib import Path
import pytest
from pipeline.graph import load_graph, discover_and_write_schema
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


def test_discover_and_write_schema_creates_file(tmp_path):
    schema_path = tmp_path / "graph_schema.md"
    discover_and_write_schema(FIXTURES / "before.json", schema_path)
    assert schema_path.exists()
    content = schema_path.read_text()
    assert "Node Fields" in content
    assert "id" in content


def test_discover_and_write_schema_skips_if_exists(tmp_path):
    schema_path = tmp_path / "graph_schema.md"
    schema_path.write_text("existing content")
    discover_and_write_schema(FIXTURES / "before.json", schema_path)
    assert schema_path.read_text() == "existing content"
