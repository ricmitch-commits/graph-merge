import argparse
import sys
from pathlib import Path
from models.config import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-merge",
        description="Port a bug fix between codebases using code knowledge graphs.",
    )
    parser.add_argument("--source-repo", required=True, metavar="PATH|URL")
    parser.add_argument("--source-fix-commit", metavar="SHA")
    parser.add_argument("--source-before", metavar="REF")
    parser.add_argument("--source-after", metavar="REF")
    parser.add_argument("--dest-repo", required=True, metavar="PATH|URL")
    parser.add_argument("--dest-base", required=True, metavar="REF")
    parser.add_argument("--model", required=True, metavar="PROVIDER/MODEL-ID")
    parser.add_argument("--output", default="./graph-merge-out", metavar="DIR")
    parser.add_argument("--commit-message", default="", metavar="TEXT")
    parser.add_argument("--pr-description", metavar="FILE")
    parser.add_argument("--max-context-nodes", type=int, default=500, metavar="N")
    parser.add_argument("--keep-worktrees", action="store_true")
    parser.add_argument("--from-stage", type=int, choices=[1, 2, 3, 4, 5], metavar="1-5")
    parser.add_argument("--force-stage", type=int, choices=[1, 2, 3, 4, 5], metavar="1-5")
    return parser


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.source_fix_commit and (args.source_before or args.source_after):
        print(
            "error: --source-fix-commit is mutually exclusive with "
            "--source-before / --source-after",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.source_fix_commit:
        args.source_before = f"{args.source_fix_commit}^"
        args.source_after = args.source_fix_commit
    elif not (args.source_before and args.source_after):
        print(
            "error: provide --source-fix-commit or both --source-before and --source-after",
            file=sys.stderr,
        )
        sys.exit(1)
    return args


def args_to_config(args: argparse.Namespace) -> Config:
    commit_message = args.commit_message
    if args.pr_description:
        commit_message = Path(args.pr_description).read_text()
    return Config(
        source_repo=args.source_repo,
        source_before=args.source_before,
        source_after=args.source_after,
        dest_repo=args.dest_repo,
        dest_base=args.dest_base,
        model=args.model,
        output_dir=Path(args.output),
        commit_message=commit_message,
        max_context_nodes=args.max_context_nodes,
        keep_worktrees=args.keep_worktrees,
        from_stage=args.from_stage,
        force_stage=args.force_stage,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args = validate_args(args)
    config = args_to_config(args)

    from pipeline.runner import run_pipeline
    sys.exit(run_pipeline(config))


if __name__ == "__main__":
    main()
