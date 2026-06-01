"""
Feature: Port a bug fix between codebases using code knowledge graphs

Tests drive stages 3-5 with:
  - Real git repos (fixture repos built in conftest.py)
  - Fixture graph JSON files (bypass real Graphify invocation)
  - SequencedMockLLMClient (bypass real API calls)
"""
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from models.config import Config
from pipeline.runner import run_pipeline

FIXTURE_GRAPHS = Path(__file__).parent.parent / "fixtures" / "graphs"

pytestmark = pytest.mark.integration


def _make_config(tmp_path, src_repo, before_sha, after_sha, go_repo) -> Config:
    return Config(
        source_repo=str(src_repo),
        source_before=before_sha,
        source_after=after_sha,
        dest_repo=str(go_repo),
        dest_base="HEAD",
        model="claude/claude-opus-4-6",
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


def _make_worktrees(output_dir: Path, src_repo, before_sha, after_sha, go_repo) -> None:
    from pipeline.checkout import setup_worktrees
    setup_worktrees(
        source_repo=str(src_repo),
        source_before=before_sha,
        source_after=after_sha,
        dest_repo=str(go_repo),
        dest_base="HEAD",
        output_dir=output_dir,
        keep_worktrees=True,
    )


@pytest.mark.integration
class TestGraphMergePipeline:

    def test_given_python_source_and_go_dest_when_stages_3_to_5_run_then_proposal_created(
        self, python_source_repo, go_dest_repo, tmp_path, sequenced_llm,
    ):
        """
        Scenario: Full pipeline produces FIX_PROPOSAL.md
          Given a Python source repo with a committed bug fix
          And a Go destination repo
          And fixture graph JSON files in place of real Graphify output
          When graph-merge runs from stage 3
          Then FIX_PROPOSAL.md exists with at least one mapping
          And fix.patch exists
        """
        src_repo, before_sha, after_sha = python_source_repo
        config = _make_config(tmp_path, src_repo, before_sha, after_sha, go_dest_repo)

        _make_worktrees(config.output_dir, src_repo, before_sha, after_sha, go_dest_repo)
        _stub_graphs(config.output_dir)
        config.from_stage = 3

        with patch("llm.client.create_client", return_value=sequenced_llm):
            exit_code = run_pipeline(config)

        assert (config.output_dir / "FIX_PROPOSAL.md").exists()
        assert (config.output_dir / "fix.patch").exists()
        assert exit_code == 0

    def test_given_all_artifacts_exist_when_pipeline_runs_then_no_stages_execute(
        self, python_source_repo, go_dest_repo, tmp_path,
    ):
        """
        Scenario: Stage skipping
          Given all stage artifacts exist on disk
          When graph-merge runs
          Then no stage functions are called
        """
        src_repo, before_sha, after_sha = python_source_repo
        config = _make_config(tmp_path, src_repo, before_sha, after_sha, go_dest_repo)
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

    def test_given_partial_run_when_semantic_diff_absent_then_stage3_reruns(
        self, python_source_repo, go_dest_repo, tmp_path,
    ):
        """
        Scenario: Re-run after deleting artifact resumes from correct stage
          Given stage 1 and 2 artifacts exist
          And semantic_diff.json does not exist
          When graph-merge runs
          Then stage 3 runs (producing semantic_diff.json)
          And stages 1 and 2 are skipped
          And stages 4 and 5 do not run (no mapping.json yet)
        """
        src_repo, before_sha, after_sha = python_source_repo
        config = _make_config(tmp_path, src_repo, before_sha, after_sha, go_dest_repo)
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
        assert 4 not in called   # no mapping.json produced yet
        assert 5 not in called
        assert (out / "semantic_diff.json").exists()
