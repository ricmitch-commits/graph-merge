import atexit
import subprocess
from pathlib import Path


def setup_worktrees(
    source_repo: str,
    source_before: str,
    source_after: str,
    dest_repo: str,
    dest_base: str,
    output_dir: Path,
    keep_worktrees: bool = False,
) -> dict[str, Path]:
    clones_dir = output_dir / "clones"
    worktrees_dir = output_dir / "worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    source_local = _ensure_local(source_repo, clones_dir / "source")
    dest_local = _ensure_local(dest_repo, clones_dir / "dest")

    paths = {
        "before": worktrees_dir / "before",
        "after": worktrees_dir / "after",
        "dest": worktrees_dir / "dest",
    }
    created: list[tuple[Path, Path]] = []

    try:
        _add_worktree(source_local, paths["before"], source_before)
        created.append((source_local, paths["before"]))
        _add_worktree(source_local, paths["after"], source_after)
        created.append((source_local, paths["after"]))
        _add_worktree(dest_local, paths["dest"], dest_base)
        created.append((dest_local, paths["dest"]))
    except subprocess.CalledProcessError:
        for repo, path in created:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
                capture_output=True,
            )
        raise

    if not keep_worktrees:
        def _cleanup() -> None:
            for repo, path in created:
                subprocess.run(
                    ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
                    capture_output=True,
                )
        atexit.register(_cleanup)

    return paths


def _ensure_local(repo: str, clone_target: Path) -> Path:
    if repo.startswith("http") or repo.startswith("git@"):
        if not clone_target.exists():
            clone_target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", repo, str(clone_target)], check=True)
        return clone_target
    return Path(repo)


def _add_worktree(repo: Path, path: Path, ref: str) -> None:
    # path must be absolute — git -C changes cwd so relative paths resolve wrongly
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(path.resolve()), ref],
        check=True, capture_output=True,
    )
