from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    source_repo: str
    source_before: str
    source_after: str
    dest_repo: str
    dest_base: str
    model: str
    output_dir: Path
    commit_message: str
    max_context_nodes: int
    keep_worktrees: bool
    from_stage: int | None
    force_stage: int | None
