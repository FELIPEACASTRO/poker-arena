from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_distribution import DistributionContractError, validate_distribution


def _distribution(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "distribution"
    project = root / "CODEX"
    project.mkdir(parents=True)
    for name in (
        ".gitignore",
        "CITATION.cff",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
    ):
        (project / name).write_text("present\n", encoding="utf-8")
    (project / "CANONICAL_SOLUTION.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "canonical_solution": ".",
                "legacy_solution_present": False,
                "credential_files_present": False,
                "vision_decision_policy": "externally-validated-f2-only",
            }
        ),
        encoding="utf-8",
    )
    return root, project


def test_distribution_contract_accepts_one_canonical_tree(tmp_path: Path) -> None:
    root, project = _distribution(tmp_path)

    validate_distribution(project, root, check_git=False)


@pytest.mark.parametrize("unsafe", ["CLAUDE", "kaggle.json", "CHAVE.txt"])
def test_distribution_contract_rejects_legacy_or_sensitive_root(
    tmp_path: Path, unsafe: str
) -> None:
    root, project = _distribution(tmp_path)
    target = root / unsafe
    if unsafe == "CLAUDE":
        target.mkdir()
    else:
        target.write_text("not-read", encoding="utf-8")

    with pytest.raises(DistributionContractError):
        validate_distribution(project, root, check_git=False)


def test_distribution_contract_rejects_missing_project_metadata(tmp_path: Path) -> None:
    root, project = _distribution(tmp_path)
    (project / "LICENSE").unlink()

    with pytest.raises(DistributionContractError, match="required project files"):
        validate_distribution(project, root, check_git=False)
