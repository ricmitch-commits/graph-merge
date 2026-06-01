import json
import subprocess
from pathlib import Path
import pytest

FIXTURE_GRAPHS = Path(__file__).parent.parent / "fixtures" / "graphs"
FIXTURE_RESPONSES = Path(__file__).parent.parent / "fixtures" / "responses"


class SequencedMockLLMClient:
    """Returns responses in order; repeats the last response once exhausted."""
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, prompt: str) -> str:
        idx = min(self.call_count, len(self._responses) - 1)
        self.call_count += 1
        return self._responses[idx]


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True)


@pytest.fixture
def python_source_repo(tmp_path):
    repo = tmp_path / "py_source"
    repo.mkdir()
    _init_repo(repo)
    (repo / "src").mkdir()
    (repo / "src" / "auth.py").write_text(
        "def validate_token(token):\n    return db.query(token)\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    before_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    (repo / "src" / "auth.py").write_text(
        "def validate_token(token):\n"
        "    result = db.query(token)\n"
        "    if not result:\n"
        "        logger.warn('Invalid token')  # WHY: audit trail\n"
        "    return result\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: add warning for invalid token"],
        cwd=repo, check=True, capture_output=True,
    )
    after_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    return repo, before_sha, after_sha


@pytest.fixture
def go_dest_repo(tmp_path):
    repo = tmp_path / "go_dest"
    repo.mkdir()
    _init_repo(repo)
    service = repo / "internal" / "auth" / "service.go"
    service.parent.mkdir(parents=True)
    service.write_text(
        "package auth\n\nfunc (s *Service) ValidateToken(token string) bool {\n"
        "    return s.db.QueryRow(token) != nil\n}\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def sequenced_llm():
    """LLM mock that serves mapping JSON for stage 4 then Go content for stage 5."""
    mapping_json = (FIXTURE_RESPONSES / "mapping_valid.json").read_text()
    go_content = (
        "package auth\n\nfunc (s *Service) ValidateToken(token string) bool {\n"
        "    result := s.db.QueryRow(token) != nil\n"
        "    if !result { log.Warn(\"Invalid token\") }\n"
        "    return result\n}\n"
    )
    return SequencedMockLLMClient([mapping_json, go_content])
