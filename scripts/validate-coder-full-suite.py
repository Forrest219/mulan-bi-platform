#!/usr/bin/env python3
"""Validate execution of inbox/20260516-16-tasks-coder-full-suite.md.

This script is intended to run after the coder finishes the handoff tasks.
It verifies the same command sequence and records a durable report under
inbox/validation-reports/. It does not stage, commit, or modify source files
except removing backend/.coverage before the full suite, matching the task doc.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
TASK_DOC = REPO / "inbox" / "20260516-16-tasks-coder-full-suite.md"
REPORT_DIR = REPO / "inbox" / "validation-reports"
PYCACHE_PREFIX = "/private/tmp/mulan-pycache"


@dataclass
class StepResult:
    name: str
    command: str
    cwd: Path
    exit_code: int
    log_path: Path

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def _now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = PYCACHE_PREFIX
    return env


def _run(
    *,
    name: str,
    cmd: list[str],
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> StepResult:
    command = " ".join(cmd)
    header = [
        f"# {name}",
        f"cwd: {cwd}",
        f"command: {command}",
        "",
    ]
    log_path.write_text("\n".join(header), encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            text=True,
        )
        fh.write(f"\n\nexit_code: {proc.returncode}\n")
    return StepResult(name, command, cwd, proc.returncode, log_path)


def _check_expected_files() -> list[str]:
    expected = [
        TASK_DOC,
        BACKEND / "tests" / "test_data_agent_e2e.py",
        BACKEND / "app" / "api" / "rules.py",
        BACKEND / "app" / "core" / "database.py",
        BACKEND / "services" / "data_agent" / "skill_loader.py",
        BACKEND / "services" / "data_agent" / "data_qa_drift.py",
        BACKEND / "services" / "data_agent" / "virtual_metrics_registry.py",
        BACKEND / "tests" / "services" / "data_agent" / "test_data_qa_drift.py",
        BACKEND / "tests" / "services" / "data_agent" / "test_virtual_metrics_registry.py",
        REPO / ".github" / "workflows" / "data-agent-nightly.yml",
        REPO / "scripts" / "data-agent-schema-drift-alert.py",
    ]
    return [str(path.relative_to(REPO)) for path in expected if not path.exists()]


def _git_lines(args: Iterable[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.stdout.splitlines()


def _status_boundary() -> tuple[list[str], list[str]]:
    status_lines = _git_lines(["status", "--short"])
    staged_paths = _git_lines(["diff", "--cached", "--name-only"])
    risky_staged = [
        path
        for path in staged_paths
        if path.startswith("inbox/archived/")
        or path.startswith(".obsidian/")
        or path == "inbox/archived"
    ]
    return status_lines, risky_staged


def _write_report(
    *,
    report_path: Path,
    missing_files: list[str],
    results: list[StepResult],
    status_lines: list[str],
    risky_staged: list[str],
) -> None:
    all_passed = not missing_files and all(r.passed for r in results) and not risky_staged
    lines: list[str] = [
        "# Coder Full Suite Validation Report",
        "",
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"Task doc: `{TASK_DOC.relative_to(REPO)}`",
        f"Overall: {'PASS' if all_passed else 'FAIL'}",
        "",
        "## Expected File Check",
        "",
    ]
    if missing_files:
        lines.append("Missing expected files:")
        lines.extend(f"- `{path}`" for path in missing_files)
    else:
        lines.append("All expected files exist.")

    lines.extend(["", "## Command Results", ""])
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.extend(
            [
                f"### {result.name}: {status}",
                "",
                f"- cwd: `{result.cwd}`",
                f"- command: `{result.command}`",
                f"- exit_code: `{result.exit_code}`",
                f"- log: `{result.log_path.relative_to(REPO)}`",
                "",
            ]
        )

    lines.extend(["## Git Boundary Check", ""])
    if status_lines:
        lines.append("`git status --short`:")
        lines.append("")
        lines.append("```text")
        lines.extend(status_lines)
        lines.append("```")
    else:
        lines.append("`git status --short` is clean.")

    lines.append("")
    if risky_staged:
        lines.append("Risky staged paths detected. Do not commit until reviewed:")
        lines.extend(f"- `{path}`" for path in risky_staged)
    else:
        lines.append("No staged `inbox/archived` or `.obsidian` paths detected.")

    lines.extend(
        [
            "",
            "## Acceptance Rule",
            "",
            "This report is PASS only when:",
            "",
            "- `tests/test_data_agent_e2e.py -q` passes.",
            "- `tests/ -x -q` runs to completion with exit code 0.",
            "- Data QA drift and Virtual Metrics Registry focused tests pass.",
            "- No risky staged user-local/archive files are present.",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate coder execution of backend full suite continuation tasks."
    )
    parser.add_argument(
        "--skip-full-suite",
        action="store_true",
        help="Skip TASK 2 full backend suite. Use only for smoke-checking the script itself.",
    )
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = REPORT_DIR / f"coder-full-suite-{_now_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)

    missing_files = _check_expected_files()
    results: list[StepResult] = []

    python = str(BACKEND / ".venv" / "bin" / "python")
    pytest_cmd = [python, "-m", "pytest"]

    results.append(
        _run(
            name="TASK 1 - Data Agent E2E focused",
            cmd=[*pytest_cmd, "tests/test_data_agent_e2e.py", "-q"],
            cwd=BACKEND,
            log_path=run_dir / "task1-data-agent-e2e.log",
            env=_env(),
        )
    )

    if not args.skip_full_suite:
        coverage = BACKEND / ".coverage"
        if coverage.exists():
            coverage.unlink()
        results.append(
            _run(
                name="TASK 2 - Full backend suite",
                cmd=[*pytest_cmd, "tests/", "-x", "-q"],
                cwd=BACKEND,
                log_path=run_dir / "task2-full-backend-suite.log",
                env=_env(),
            )
        )

    results.append(
        _run(
            name="TASK 3 - P1 quality governance focused",
            cmd=[
                *pytest_cmd,
                "tests/services/data_agent/test_data_qa_drift.py",
                "tests/services/data_agent/test_virtual_metrics_registry.py",
                "-q",
            ],
            cwd=BACKEND,
            log_path=run_dir / "task3-p1-quality-governance.log",
            env=_env(),
        )
    )

    status_lines, risky_staged = _status_boundary()
    report_path = run_dir / "validation-report.md"
    _write_report(
        report_path=report_path,
        missing_files=missing_files,
        results=results,
        status_lines=status_lines,
        risky_staged=risky_staged,
    )

    print(f"Validation report: {report_path}")
    all_passed = not missing_files and all(r.passed for r in results) and not risky_staged
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
