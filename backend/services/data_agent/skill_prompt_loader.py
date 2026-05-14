"""File-backed prompt contract loader for controlled Data Agent QA."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SkillPromptKind = Literal["planning", "rendering"]

SKILL_PROMPT_VERSION_FALLBACK = "prompt.v1"
DEFAULT_SKILL_PROMPT_ROOT = Path(__file__).resolve().parents[3] / "skills"
_SKILL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class SkillPromptLoadResult:
    """Structured result for a prompt markdown load attempt."""

    ok: bool
    skill_key: str
    kind: SkillPromptKind
    content: str | None = None
    checksum: str | None = None
    version: str | None = None
    source_path: str | None = None
    metadata: dict[str, str] | None = None
    error: dict[str, str] | None = None


class SkillPromptLoader:
    """Load planning/rendering prompt contracts from markdown files."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_SKILL_PROMPT_ROOT

    def load_planning(self, skill_key: str) -> SkillPromptLoadResult:
        return self.load("planning", skill_key)

    def load_rendering(self, skill_key: str) -> SkillPromptLoadResult:
        return self.load("rendering", skill_key)

    def load(self, kind: SkillPromptKind, skill_key: str) -> SkillPromptLoadResult:
        normalized_key = str(skill_key or "").strip()
        source_path = self._source_path(kind, normalized_key)

        if not _SKILL_KEY_RE.fullmatch(normalized_key):
            return self._error(
                kind=kind,
                skill_key=normalized_key,
                source_path=source_path,
                code="invalid_skill_key",
                message="skill key must use lowercase letters, digits, and underscores",
            )

        try:
            raw_content = source_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._error(
                kind=kind,
                skill_key=normalized_key,
                source_path=source_path,
                code="skill_prompt_not_found",
                message="skill prompt markdown file does not exist",
            )
        except OSError as exc:
            return self._error(
                kind=kind,
                skill_key=normalized_key,
                source_path=source_path,
                code="skill_prompt_read_error",
                message=str(exc),
            )

        content = raw_content.strip()
        if not content:
            return self._error(
                kind=kind,
                skill_key=normalized_key,
                source_path=source_path,
                code="skill_prompt_empty",
                message="skill prompt markdown file is empty",
            )

        metadata = _extract_frontmatter(content)
        kind_error = _validate_skill_type(kind, metadata)
        if kind_error:
            return self._error(
                kind=kind,
                skill_key=normalized_key,
                source_path=source_path,
                code="skill_prompt_kind_mismatch",
                message=kind_error,
            )

        return SkillPromptLoadResult(
            ok=True,
            skill_key=normalized_key,
            kind=kind,
            content=content,
            checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            version=metadata.get("version") or _extract_version(content),
            source_path=str(source_path),
            metadata=metadata,
            error=None,
        )

    def _source_path(self, kind: SkillPromptKind, skill_key: str) -> Path:
        return self.root / kind / f"{skill_key}.md"

    @staticmethod
    def _error(
        *,
        kind: SkillPromptKind,
        skill_key: str,
        source_path: Path,
        code: str,
        message: str,
    ) -> SkillPromptLoadResult:
        return SkillPromptLoadResult(
            ok=False,
            skill_key=skill_key,
            kind=kind,
            source_path=str(source_path),
            error={
                "code": code,
                "message": message,
                "skill_key": skill_key,
                "kind": kind,
                "source_path": str(source_path),
            },
        )


def _extract_version(content: str) -> str:
    for line in content.splitlines()[:20]:
        stripped = line.strip()
        if stripped.startswith("version:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'") or SKILL_PROMPT_VERSION_FALLBACK
    return SKILL_PROMPT_VERSION_FALLBACK


def _extract_frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:40]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def _validate_skill_type(kind: SkillPromptKind, metadata: dict[str, str]) -> str | None:
    skill_type = metadata.get("skill_type")
    if not skill_type:
        return None

    expected = "planning_prompt" if kind == "planning" else "rendering_prompt"
    if skill_type != expected:
        return f"skill_type must be {expected}, got {skill_type}"
    return None
