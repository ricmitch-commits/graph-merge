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


def test_fallback_match_by_file_symbol_kind():
    """Nodes with differing IDs but matching (file, symbol, kind) → node_modified, not removed+added."""
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
