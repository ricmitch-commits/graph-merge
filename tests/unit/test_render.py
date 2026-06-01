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


def test_fix_proposal_source_and_dest_refs_present():
    proposal = build_fix_proposal(
        mapping_result=_mapping_result(),
        branch_name="graph-merge/port-abc1234-20260521",
        source_repo="/src", source_before_ref="abc^", source_after_ref="abc1234",
        dest_repo="/dest", dest_base="main", commit_message="",
    )
    assert "/src" in proposal
    assert "abc^" in proposal
    assert "/dest" in proposal
    assert "main" in proposal


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
