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
