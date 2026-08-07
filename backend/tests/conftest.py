from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MANUAL_RUN_PREFIX = "poker-arena-pytest-"
_MANUAL_RUN_PARENT = Path(tempfile.gettempdir()).resolve()
_ORIGINAL_LOG_DIR = os.environ.get("POKER_LOG_DIR")
_RUN_ROOT: Path | None = None
_MANAGED_LOG_DIR = False


def _is_reparse(path: Path) -> bool:
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(
        getattr(file_stat, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _ensure_run_root() -> Path:
    global _RUN_ROOT

    if _RUN_ROOT is None:
        candidate = Path(tempfile.mkdtemp(prefix=_MANUAL_RUN_PREFIX))
        if _is_reparse(candidate):
            raise RuntimeError("manual pytest run root cannot be a reparse point")
        candidate = candidate.resolve(strict=True)
        if candidate.parent != _MANUAL_RUN_PARENT or not candidate.name.startswith(
            _MANUAL_RUN_PREFIX
        ):
            raise RuntimeError("manual pytest run root resolved outside the OS temp directory")
        _RUN_ROOT = candidate
    return _RUN_ROOT


def _qa_harness_log_dir() -> Path | None:
    """Accept only the dedicated log directory issued by the aggregate QA harness."""

    raw = os.environ.get("POKER_TEST_LOG_DIR", "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise RuntimeError("POKER_TEST_LOG_DIR must be absolute")
    resolved = candidate.resolve(strict=False)
    run_root = resolved.parent
    if run_root.parent != _PROJECT_ROOT or not run_root.name.startswith(".qa-run-"):
        raise RuntimeError("POKER_TEST_LOG_DIR is outside an isolated QA run")
    if _is_reparse(candidate) or _is_reparse(run_root) or _is_reparse(resolved):
        raise RuntimeError("POKER_TEST_LOG_DIR cannot use symbolic links")
    return resolved


def pytest_configure(config: pytest.Config) -> None:
    """Isolate manual test runs without overriding the authoritative QA harness."""

    global _MANAGED_LOG_DIR

    harness_log_dir = _qa_harness_log_dir()
    if harness_log_dir is None:
        run_root = _ensure_run_root()
        # Pytest's shared ``pytest-of-<user>`` directory can retain hostile or stale
        # ACLs from an interrupted run.  Give every manual invocation an owned,
        # unpredictable base instead; an explicit QA-harness --basetemp still wins.
        if config.option.basetemp is None:
            config.option.basetemp = run_root / "tmp"
        log_dir = run_root / "logs"
    else:
        log_dir = harness_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    os.environ["POKER_LOG_DIR"] = str(log_dir)
    _MANAGED_LOG_DIR = True


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the caller and clean after pytest has released test-runtime handles."""

    del config
    if _MANAGED_LOG_DIR:
        if _ORIGINAL_LOG_DIR is None:
            os.environ.pop("POKER_LOG_DIR", None)
        else:
            os.environ["POKER_LOG_DIR"] = _ORIGINAL_LOG_DIR

    if _RUN_ROOT is None or not _RUN_ROOT.exists():
        return

    resolved = _RUN_ROOT.resolve(strict=True)
    if resolved.parent != _MANUAL_RUN_PARENT or not resolved.name.startswith(_MANUAL_RUN_PREFIX):
        raise RuntimeError("refusing to clean an unexpected pytest run root")
    if _is_reparse(_RUN_ROOT) or any(_is_reparse(path) for path in _RUN_ROOT.rglob("*")):
        raise RuntimeError("refusing to clean a pytest run containing symbolic links")
    shutil.rmtree(resolved)
