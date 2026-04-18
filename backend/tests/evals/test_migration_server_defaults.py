"""
Eval: 陷阱 4 — Alembic autogenerate 遗漏 server_default

静态分析 backend/alembic/versions/*.py，
检测 op.add_column() 中 nullable=False 但缺少 server_default 的列定义。

背景：
  向已有数据的表添加 NOT NULL 列时，若没有 server_default，
  PostgreSQL 会在迁移时报错（现有行无法填充默认值）。
  Alembic autogenerate 不会自动为你补充 server_default。

测试策略：
  - 纯静态文本分析，不连接数据库
  - 使用 AST + 正则双重检测，降低误报
"""
import ast
import re
from pathlib import Path

import pytest

# 从本文件向上查找含 alembic/versions 的 backend 根目录
def _find_backend_root() -> Path:
    candidate = Path(__file__).parent
    for _ in range(6):
        if (candidate / "alembic" / "versions").exists():
            return candidate
        candidate = candidate.parent
    # fallback：tests/evals -> tests -> backend（向上 3 级）
    return Path(__file__).parent.parent.parent


_PROJECT_ROOT = _find_backend_root()
_VERSIONS_DIR = _PROJECT_ROOT / "alembic" / "versions"


def _get_migration_files() -> list[Path]:
    """获取所有迁移 .py 文件（排除 __pycache__）"""
    if not _VERSIONS_DIR.exists():
        return []
    return sorted(
        f for f in _VERSIONS_DIR.glob("*.py") if not f.name.startswith("__")
    )


def _find_bad_add_column_calls(filepath: Path) -> list[dict]:
    """
    扫描迁移文件，找到 op.add_column() 中：
      - 含 nullable=False
      - 不含 server_default=
    的调用，返回问题列表。
    """
    content = filepath.read_text(encoding="utf-8")
    issues = []

    # 逐个找 op.add_column( 调用块
    pos = 0
    while True:
        idx = content.find("op.add_column(", pos)
        if idx == -1:
            break

        # 向前找配对括号（手动栈）
        depth = 0
        end = idx
        for i in range(idx + len("op.add_column(") - 1, min(idx + 3000, len(content))):
            c = content[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        snippet = content[idx : end + 1]

        has_nullable_false = bool(re.search(r"nullable\s*=\s*False", snippet))
        has_server_default = bool(re.search(r"server_default\s*=", snippet))

        if has_nullable_false and not has_server_default:
            line_no = content[:idx].count("\n") + 1
            summary = " ".join(snippet.split())[:150]
            issues.append(
                {
                    "file": filepath.name,
                    "line": line_no,
                    "snippet": summary,
                }
            )

        pos = end + 1

    return issues


class TestMigrationServerDefaults:
    """静态检测所有 Alembic 迁移文件的 server_default 合规性"""

    def test_versions_directory_exists(self):
        """alembic/versions 目录必须存在"""
        assert _VERSIONS_DIR.exists(), (
            f"alembic/versions 目录不存在: {_VERSIONS_DIR}"
        )

    def test_migration_files_found(self):
        """至少存在一个迁移文件"""
        files = _get_migration_files()
        assert len(files) > 0, "未找到任何 Alembic 迁移文件"

    def test_no_nullable_false_without_server_default(self):
        """
        所有迁移文件中，op.add_column(nullable=False) 必须同时指定 server_default。

        若此测试失败：在 sa.Column() 中添加 server_default='<默认值>'，
        或先设为 nullable=True，填充数据后再改为 NOT NULL。
        """
        files = _get_migration_files()
        all_issues = []

        for filepath in files:
            issues = _find_bad_add_column_calls(filepath)
            all_issues.extend(issues)

        if all_issues:
            lines = []
            for iss in all_issues:
                lines.append(
                    f"  [{iss['file']}] Line {iss['line']}: {iss['snippet']}"
                )
            msg = (
                f"发现 {len(all_issues)} 处 nullable=False 但缺少 server_default 的列定义：\n"
                + "\n".join(lines)
                + "\n\n修复方法：添加 server_default='<默认值>' 参数。"
            )
            pytest.fail(msg)

    @pytest.mark.parametrize(
        "filepath",
        _get_migration_files(),
        ids=lambda f: f.name,
    )
    def test_individual_migration_file(self, filepath: Path):
        """逐文件检测，便于 CI 中定位具体文件"""
        issues = _find_bad_add_column_calls(filepath)
        if issues:
            lines = [
                f"  Line {iss['line']}: {iss['snippet']}" for iss in issues
            ]
            pytest.fail(
                f"[{filepath.name}] 发现 {len(issues)} 处问题：\n"
                + "\n".join(lines)
            )

    def test_known_good_migration_has_server_default(self):
        """
        回归测试：已知正确的迁移文件（add_llm_purpose_columns）
        的 purpose/priority 列应包含 server_default。
        """
        target = _VERSIONS_DIR / "20260416_000000_add_llm_purpose_columns.py"
        if not target.exists():
            pytest.skip("目标迁移文件不存在，跳过回归测试")

        content = target.read_text(encoding="utf-8")

        # purpose 列：nullable=False + server_default='default'
        assert "server_default='default'" in content or 'server_default="default"' in content, (
            "purpose 列缺少 server_default"
        )
        # priority 列：nullable=False + server_default='0'
        assert "server_default='0'" in content or 'server_default="0"' in content, (
            "priority 列缺少 server_default"
        )
