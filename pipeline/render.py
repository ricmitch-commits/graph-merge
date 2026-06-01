import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from models.types import MappingResult

_RENDER_PROMPT = """\
You are applying a bug fix to a destination codebase file.

## Source changes (from the fixed version):
{source_snippets}

## Mapping rationales:
{rationales}

## Destination file (current content):
```
{dest_file_content}
```

Apply the equivalent changes to the destination file. Output ONLY the modified \
file content — no explanation, no markdown fences."""


def run_render(
    mapping_result: MappingResult,
    worktrees: dict[str, Path],
    source_repo: str,
    source_before_ref: str,
    source_after_ref: str,
    dest_repo: str,
    dest_base: str,
    commit_message: str,
    llm_client,
    output_dir: Path,
) -> str:
    new_contents = generate_patch_content(mapping_result, worktrees, llm_client)

    dest_worktree = worktrees["dest"]
    for dest_file, content in new_contents.items():
        dest_path = dest_worktree / dest_file
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(content)

    patch_result = subprocess.run(
        ["git", "diff"], capture_output=True, text=True, cwd=str(dest_worktree)
    )
    unmappable_comment = ""
    if mapping_result.unmappable:
        lines = ["# graph-merge: unmappable changes (not applied)"]
        for u in mapping_result.unmappable:
            lines.append(f"#   {u.source_change.node_id}: {u.reason}")
        unmappable_comment = "\n".join(lines) + "\n"
    patch_path = output_dir / "fix.patch"
    patch_path.write_text(unmappable_comment + patch_result.stdout)

    sha = source_after_ref[:7]
    timestamp = datetime.now().strftime("%Y%m%d")
    branch_name = f"graph-merge/port-{sha}-{timestamp}"

    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=str(dest_worktree), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-am", f"graph-merge: port fix from {source_after_ref}"],
        cwd=str(dest_worktree), check=False, capture_output=True,
    )

    proposal = build_fix_proposal(
        mapping_result=mapping_result,
        branch_name=branch_name,
        source_repo=source_repo,
        source_before_ref=source_before_ref,
        source_after_ref=source_after_ref,
        dest_repo=dest_repo,
        dest_base=dest_base,
        commit_message=commit_message,
    )
    (output_dir / "FIX_PROPOSAL.md").write_text(proposal)

    return branch_name


def generate_patch_content(
    mapping_result: MappingResult,
    worktrees: dict[str, Path],
    llm_client,
) -> dict[str, str]:
    by_dest_file: dict[str, list] = defaultdict(list)
    for mapping in mapping_result.mappings:
        by_dest_file[mapping.destination_node.file].append(mapping)

    results: dict[str, str] = {}
    for dest_file, mappings in by_dest_file.items():
        dest_path = worktrees["dest"] / dest_file
        if not dest_path.exists():
            continue
        dest_content = dest_path.read_text()

        source_snippets: list[str] = []
        rationales: list[str] = []
        for m in mappings:
            if "::" in m.source_change.node_id:
                src_file = m.source_change.node_id.split("::")[0]
                src_path = worktrees["after"] / src_file
                if src_path.exists():
                    source_snippets.append(f"# {src_file}\n{src_path.read_text()}")
            rationales.append(
                f"- {m.source_change.node_id} → {m.destination_node.symbol}: {m.rationale}"
            )

        prompt = _RENDER_PROMPT.format(
            source_snippets="\n\n".join(source_snippets) or "(none)",
            rationales="\n".join(rationales),
            dest_file_content=dest_content,
        )
        results[dest_file] = llm_client.complete(prompt)

    return results


def build_fix_proposal(
    mapping_result: MappingResult,
    branch_name: str,
    source_repo: str,
    source_before_ref: str,
    source_after_ref: str,
    dest_repo: str,
    dest_base: str,
    commit_message: str,
) -> str:
    rows = "\n".join(
        f"| {m.source_change.node_id} | "
        f"{m.destination_node.file}::{m.destination_node.symbol} | "
        f"{m.confidence} | {m.rationale} |"
        for m in mapping_result.mappings
    )
    unmappable_lines = "\n".join(
        f"- `{u.source_change.node_id}`: {u.reason}"
        for u in mapping_result.unmappable
    ) or "_None_"

    return f"""# Fix Proposal
Source: {source_repo} {source_before_ref} → {source_after_ref}
Destination: {dest_repo} {dest_base}
Branch: {branch_name}

## Summary
{commit_message or "(no commit message provided)"}

## Mappings
| Source | Destination | Confidence | Rationale |
|--------|-------------|------------|-----------|
{rows}

## Unmappable Changes
{unmappable_lines}

## Next Steps
1. Review the mappings above and `fix.patch`
2. Test the branch: `{branch_name}`
3. Push and open a PR
"""
