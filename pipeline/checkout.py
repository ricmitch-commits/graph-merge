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

    # Prune stale worktree registrations left by a previous failed run
    _prune_worktrees(source_local)
    _prune_worktrees(dest_local)

    paths = {
        "before": worktrees_dir / "before",
        "after": worktrees_dir / "after",
        "dest": worktrees_dir / "dest",
    }
    created: list[tuple[Path, Path]] = []

    try:
        _add_worktree(source_local, paths["before"], _resolve_ref(source_local, source_before))
        created.append((source_local, paths["before"]))
        _add_worktree(source_local, paths["after"], _resolve_ref(source_local, source_after))
        created.append((source_local, paths["after"]))
        _add_worktree(dest_local, paths["dest"], _resolve_ref(dest_local, dest_base))
        created.append((dest_local, paths["dest"]))
    except RuntimeError:
        for repo, path in created:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force",
                 str(path.resolve())],
                capture_output=True,
            )
        raise

    if not keep_worktrees:
        def _cleanup() -> None:
            for repo, path in created:
                subprocess.run(
                    ["git", "-C", str(repo), "worktree", "remove", "--force",
                     str(path.resolve())],
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


def _resolve_ref(repo: Path, ref: str) -> str:
    """Resolve a git revision expression to a full commit SHA.

    Tries the ref as-is first, then falls back to origin/<ref> so that
    remote-tracking branches like 'openssl-3.4' work without needing a local
    branch of the same name.
    """
    for candidate in (ref, f"origin/{ref}"):
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", candidate],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    raise RuntimeError(
        f"Cannot resolve ref {ref!r} in {repo} (also tried 'origin/{ref}'):\n"
        f"{result.stderr.strip()}"
    )


def _prune_worktrees(repo: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "prune"],
        capture_output=True,
    )


def _add_worktree(repo: Path, path: Path, ref: str) -> None:
    abs_path = path.resolve()
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(abs_path), ref],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git worktree add {ref!r} -> {abs_path} failed:\n{result.stderr.strip()}"
        )
