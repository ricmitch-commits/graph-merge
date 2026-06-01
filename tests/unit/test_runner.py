from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from models.config import Config
from pipeline.runner import artifacts_exist, run_pipeline


def _config(tmp_path: Path, from_stage=None, force_stage=None) -> Config:
    return Config(
        source_repo="/src", source_before="abc^", source_after="abc",
        dest_repo="/dest", dest_base="main", model="claude/claude-opus-4-6",
        output_dir=tmp_path, commit_message="", max_context_nodes=500,
        keep_worktrees=False, from_stage=from_stage, force_stage=force_stage,
    )


def test_artifacts_exist_stage1_false_when_worktrees_missing(tmp_path):
    assert not artifacts_exist(tmp_path, 1)


def test_artifacts_exist_stage1_true_when_all_worktrees_present(tmp_path):
    for label in ("before", "after", "dest"):
        (tmp_path / "worktrees" / label).mkdir(parents=True)
    assert artifacts_exist(tmp_path, 1)


def test_artifacts_exist_stage3_true_when_semantic_diff_present(tmp_path):
    (tmp_path / "semantic_diff.json").write_text("{}")
    assert artifacts_exist(tmp_path, 3)


def test_artifacts_exist_stage4_true_when_mapping_present(tmp_path):
    (tmp_path / "mapping.json").write_text("{}")
    assert artifacts_exist(tmp_path, 4)


def test_artifacts_exist_stage5_requires_both_files(tmp_path):
    (tmp_path / "FIX_PROPOSAL.md").write_text("")
    assert not artifacts_exist(tmp_path, 5)   # fix.patch missing
    (tmp_path / "fix.patch").write_text("")
    assert artifacts_exist(tmp_path, 5)        # both present


def test_stage_skipped_when_artifacts_exist(tmp_path):
    config = _config(tmp_path)
    for label in ("before", "after", "dest"):
        (tmp_path / "worktrees" / label).mkdir(parents=True)
    for label in ("before", "after", "dest"):
        (tmp_path / "graphs").mkdir(exist_ok=True)
        (tmp_path / "graphs" / f"{label}.json").write_text("{}")
    (tmp_path / "semantic_diff.json").write_text("{}")
    (tmp_path / "mapping.json").write_text("{}")
    (tmp_path / "fix.patch").write_text("")
    (tmp_path / "FIX_PROPOSAL.md").write_text("")

    called = []
    with patch("pipeline.runner.STAGES", [
        (i, f"S{i}", lambda c, i=i: called.append(i)) for i in range(1, 6)
    ]):
        run_pipeline(config)

    assert called == [], "No stages should run when all artifacts exist"


def test_force_stage_reruns_despite_artifact(tmp_path):
    config = _config(tmp_path, force_stage=3)
    (tmp_path / "semantic_diff.json").write_text("{}")

    called = []
    def fake_stage3(c):
        called.append(3)

    with patch("pipeline.runner.STAGES", [(3, "Diff", fake_stage3)]):
        try:
            run_pipeline(config)
        except Exception:
            pass

    assert 3 in called


def test_failed_stage_writes_error_log(tmp_path):
    config = _config(tmp_path)

    def bad_stage(c):
        raise RuntimeError("something broke")

    with patch("pipeline.runner.STAGES", [(1, "Checkout", bad_stage)]):
        exit_code = run_pipeline(config)

    assert exit_code == 1
    assert (tmp_path / "error.log").exists()
    assert "something broke" in (tmp_path / "error.log").read_text()
