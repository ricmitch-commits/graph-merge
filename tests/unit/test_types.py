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
        dest_repo="/tmp/dest", dest_base="main", model="claude/claude-opus-4-6",
        output_dir=Path("/tmp/out"), commit_message="", max_context_nodes=500,
        keep_worktrees=False, from_stage=None, force_stage=None,
    )
    assert isinstance(config.output_dir, Path)
