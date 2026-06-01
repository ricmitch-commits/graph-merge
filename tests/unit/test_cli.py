import pytest
from unittest.mock import patch
from cli import build_parser, validate_args


def test_source_fix_commit_expands_to_before_after():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc1234",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
    ])
    args = validate_args(args)
    assert args.source_before == "abc1234^"
    assert args.source_after == "abc1234"


def test_explicit_before_after_accepted():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-before", "abc1234^",
        "--source-after", "abc1234",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
    ])
    args = validate_args(args)
    assert args.source_before == "abc1234^"
    assert args.source_after == "abc1234"


def test_source_fix_commit_and_before_are_mutually_exclusive():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc",
        "--source-before", "abc^",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
    ])
    with pytest.raises(SystemExit):
        validate_args(args)


def test_missing_both_source_refs_raises():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
    ])
    with pytest.raises(SystemExit):
        validate_args(args)


def test_default_output_dir():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
    ])
    assert args.output == "./graph-merge-out"


def test_max_context_nodes_default():
    parser = build_parser()
    args = parser.parse_args([
        "--source-repo", "/src",
        "--source-fix-commit", "abc",
        "--dest-repo", "/dest",
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
    ])
    assert args.max_context_nodes == 500


def test_main_calls_run_pipeline(tmp_path):
    with patch("sys.argv", [
        "graph-merge",
        "--source-repo", str(tmp_path),
        "--source-fix-commit", "abc",
        "--dest-repo", str(tmp_path),
        "--dest-base", "main",
        "--model", "claude/claude-opus-4-6",
        "--output", str(tmp_path / "out"),
    ]), patch("pipeline.runner.run_pipeline", return_value=0) as mock_run, \
       patch("sys.exit") as mock_exit:
        from cli import main
        main()
        assert mock_run.called
        mock_exit.assert_called_with(0)
