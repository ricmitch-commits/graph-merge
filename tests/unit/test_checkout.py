import subprocess
from pathlib import Path
import pytest
from pipeline.checkout import setup_worktrees, _ensure_local


def _make_bare_repo(path: Path, initial_file: str = "README.md") -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True)
    (path / initial_file).write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def test_ensure_local_returns_path_for_local_dir(tmp_path):
    result = _ensure_local(str(tmp_path), tmp_path / "clone")
    assert result == tmp_path


def test_setup_worktrees_creates_three_directories(tmp_path):
    src = _make_bare_repo(tmp_path / "src_repo")
    dst = _make_bare_repo(tmp_path / "dst_repo")

    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()
    (src / "fix.py").write_text("fixed")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix"], cwd=src, check=True, capture_output=True)
    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()

    output_dir = tmp_path / "out"
    paths = setup_worktrees(
        source_repo=str(src),
        source_before=before_sha,
        source_after=after_sha,
        dest_repo=str(dst),
        dest_base="HEAD",
        output_dir=output_dir,
        keep_worktrees=True,
    )

    assert paths["before"].exists()
    assert paths["after"].exists()
    assert paths["dest"].exists()


def test_setup_worktrees_before_does_not_contain_fix(tmp_path):
    src = _make_bare_repo(tmp_path / "src_repo")
    dst = _make_bare_repo(tmp_path / "dst_repo")
    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()
    (src / "fix.py").write_text("fixed")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix"], cwd=src, check=True, capture_output=True)
    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True
    ).stdout.strip()

    output_dir = tmp_path / "out"
    paths = setup_worktrees(
        source_repo=str(src), source_before=before_sha, source_after=after_sha,
        dest_repo=str(dst), dest_base="HEAD", output_dir=output_dir, keep_worktrees=True,
    )
    assert not (paths["before"] / "fix.py").exists()
    assert (paths["after"] / "fix.py").exists()
