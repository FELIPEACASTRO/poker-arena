"""Validate that the published workspace has one canonical, auditable solution."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

REQUIRED_PROJECT_FILES = frozenset(
    {
        ".gitignore",
        "CANONICAL_SOLUTION.json",
        "CITATION.cff",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
    }
)
FORBIDDEN_LEGACY_NAMES = frozenset({"CLAUDE"})
SENSITIVE_ROOT_NAMES = frozenset({"chave.txt", "kaggle.json"})


class DistributionContractError(RuntimeError):
    """The distribution root is ambiguous, unversioned, or unsafe."""


def _git_evidence(distribution_root: Path, *, require_clean: bool) -> None:
    git = shutil.which("git")
    if git is None:
        raise DistributionContractError("git executable is unavailable")

    def run(*args: str) -> str:
        completed = subprocess.run(  # noqa: S603 - resolved executable and fixed argv only
            [git, "-C", str(distribution_root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if completed.returncode != 0:
            raise DistributionContractError(f"git {' '.join(args)} failed")
        return completed.stdout.strip()

    top = Path(run("rev-parse", "--show-toplevel")).resolve()
    if top != distribution_root:
        raise DistributionContractError("git top-level does not match distribution root")
    commit = run("rev-parse", "--verify", "HEAD")
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
        raise DistributionContractError("git HEAD is not a full immutable commit id")
    if require_clean and run("status", "--porcelain=v1", "--untracked-files=all"):
        raise DistributionContractError("release tree is dirty")


def validate_distribution(
    project_root: Path,
    distribution_root: Path,
    *,
    check_git: bool = True,
    require_clean: bool = False,
) -> None:
    project_root = project_root.resolve(strict=True)
    distribution_root = distribution_root.resolve(strict=True)
    if project_root.parent != distribution_root or project_root.name != "CODEX":
        raise DistributionContractError("canonical project must be distribution_root/CODEX")
    if any((distribution_root / name).exists() for name in FORBIDDEN_LEGACY_NAMES):
        raise DistributionContractError("legacy executable tree is present")
    missing = sorted(name for name in REQUIRED_PROJECT_FILES if not (project_root / name).is_file())
    if missing:
        raise DistributionContractError(f"required project files are missing: {missing}")
    root_names = {item.name.casefold() for item in distribution_root.iterdir()}
    exposed = sorted(root_names & SENSITIVE_ROOT_NAMES)
    if exposed:
        raise DistributionContractError(f"sensitive root filenames are present: {exposed}")
    contract_path = project_root / "CANONICAL_SOLUTION.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": 1,
        "canonical_solution": ".",
        "legacy_solution_present": False,
        "credential_files_present": False,
        "vision_decision_policy": "externally-validated-f2-only",
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise DistributionContractError(f"canonical contract mismatch for {key}")

    if check_git:
        _git_evidence(project_root, require_clean=require_clean)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_project = Path(__file__).resolve().parents[2]
    parser.add_argument("--project-root", type=Path, default=default_project)
    parser.add_argument("--distribution-root", type=Path, default=default_project.parent)
    parser.add_argument("--release", action="store_true", help="also require a clean git tree")
    args = parser.parse_args(argv)
    try:
        validate_distribution(
            args.project_root,
            args.distribution_root,
            require_clean=args.release,
        )
    except (DistributionContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DISTRIBUTION_CONTRACT_FAILED type={type(exc).__name__}")
        return 1
    print("DISTRIBUTION_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
