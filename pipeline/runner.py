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
    from pipeline.graph import generate_graph, discover_and_write_schema
    graphs_dir = config.output_dir / "graphs"
    worktrees_dir = config.output_dir / "worktrees"
    for label in ("before", "after", "dest"):
        generate_graph(
            worktree_path=worktrees_dir / label,
            output_path=graphs_dir / f"{label}.json",
            label=label,
        )
    schema_path = Path("docs/graph_schema.md")
    discover_and_write_schema(graphs_dir / "before.json", schema_path)


class _NoChanges(Exception):
    pass


def _deserialize_change(c: dict):
    """Reconstruct a Change, handling the edge field as a nested GraphEdge dict."""
    from models.types import Change, GraphEdge
    edge_data = c.pop("edge", None)
    edge = GraphEdge(**edge_data) if edge_data else None
    return Change(**c, edge=edge)


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
    from models.types import SemanticDiff

    graphs_dir = config.output_dir / "graphs"
    dest_nodes, dest_edges = load_graph(graphs_dir / "dest.json")

    diff_data = json.loads((config.output_dir / "semantic_diff.json").read_text())
    changes = [_deserialize_change(dict(c)) for c in diff_data["changes"]]
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
    from pipeline.render import run_render, build_fix_proposal
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
        proposal = build_fix_proposal(
            mapping_result=result,
            branch_name="(none — all changes unmappable)",
            source_repo=config.source_repo,
            source_before_ref=config.source_before,
            source_after_ref=config.source_after,
            dest_repo=config.dest_repo,
            dest_base=config.dest_base,
            commit_message=config.commit_message,
        )
        (config.output_dir / "fix.patch").write_text("")
        (config.output_dir / "FIX_PROPOSAL.md").write_text(proposal)
        return

    llm = create_client(config.model)
    worktrees = {
        label: config.output_dir / "worktrees" / label
        for label in ("before", "after", "dest")
    }
    branch = run_render(
        mapping_result=result,
        worktrees=worktrees,
        source_repo=config.source_repo,
        source_before_ref=config.source_before,
        source_after_ref=config.source_after,
        dest_repo=config.dest_repo,
        dest_base=config.dest_base,
        commit_message=config.commit_message,
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
            return 0
        except ValueError as exc:
            _write_error_log(config.output_dir, stage_num, stage_name, exc)
            return 2
        except Exception as exc:
            _write_error_log(config.output_dir, stage_num, stage_name, exc)
            return 1

    return 0


def _write_error_log(output_dir: Path, stage_num: int, stage_name: str, exc: Exception) -> None:
    msg = f"Stage {stage_num} ({stage_name}) failed:\n{exc}\n"
    print(f"Error: {exc}", file=sys.stderr)
    (output_dir / "error.log").write_text(msg)
