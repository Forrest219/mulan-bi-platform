"""API Contract Governance - 比对引擎

按用户 spec 定义兼容性分级：

P0 严重不兼容：
- 字段删除
- 字段类型变化
- 关键业务字段路径变化
- 枚举含义变化
- 主键/业务唯一键变化

P1 高风险兼容变化：
- required -> optional
- optional -> required
- 数组结构变对象
- 时间格式变化
- 金额精度变化

P2 中低风险变化：
- 新增非必填字段
- 字段顺序变化
- 描述信息变化
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from .types import ChangeSeverity, ChangeType, ComparisonResult, FieldChange, FieldSchema, FieldType


class Comparator:
    """API 字段比对引擎"""

    # 破坏性变更类型（P0）
    BREAKING_CHANGE_TYPES = {
        ChangeType.FIELD_REMOVED,
        ChangeType.FIELD_TYPE_CHANGED,
        ChangeType.ENUM_VALUE_REMOVED,
    }

    # 类型兼容性映射：(from_type, to_type) -> is_breaking
    TYPE_COMPATIBILITY = {
        # 完全兼容
        (FieldType.STRING, FieldType.STRING): False,
        (FieldType.NUMBER, FieldType.NUMBER): False,
        (FieldType.BOOLEAN, FieldType.BOOLEAN): False,
        (FieldType.ARRAY, FieldType.ARRAY): False,
        (FieldType.NULL, FieldType.STRING): False,
        (FieldType.NULL, FieldType.NUMBER): False,
        (FieldType.NULL, FieldType.BOOLEAN): False,
        # 破坏性变更
        (FieldType.STRING, FieldType.NUMBER): True,
        (FieldType.STRING, FieldType.BOOLEAN): True,
        (FieldType.STRING, FieldType.ARRAY): True,
        (FieldType.STRING, FieldType.OBJECT): True,
        (FieldType.NUMBER, FieldType.STRING): True,
        (FieldType.NUMBER, FieldType.BOOLEAN): True,
        (FieldType.NUMBER, FieldType.ARRAY): True,
        (FieldType.NUMBER, FieldType.OBJECT): True,
        (FieldType.BOOLEAN, FieldType.STRING): True,
        (FieldType.BOOLEAN, FieldType.NUMBER): True,
        (FieldType.BOOLEAN, FieldType.ARRAY): True,
        (FieldType.BOOLEAN, FieldType.OBJECT): True,
        (FieldType.ARRAY, FieldType.OBJECT): True,
        (FieldType.OBJECT, FieldType.ARRAY): True,
    }

    # 关键业务字段路径模式（这些字段删除/变更都是 P0）
    KEY_FIELD_PATTERNS = [
        r".*id$",           # 主键/ID 字段
        r".*key$",          # 键字段
        r".*status$",       # 状态字段
        r".*type$",         # 类型字段
        r".*code$",         # 编码字段
        r".*name$",         # 名称字段
        r".*amount$",       # 金额字段
        r".*price$",        # 价格字段
        r".*count$",        # 数量字段
        r".*time$",         # 时间字段
        r".*date$",         # 日期字段
        r".*created.*at$",  # 创建时间
        r".*updated.*at$",  # 更新时间
    ]

    def __init__(self, key_field_patterns: Optional[list[str]] = None):
        if key_field_patterns:
            self.key_field_patterns = key_field_patterns
        else:
            self.key_field_patterns = self.KEY_FIELD_PATTERNS

    def compare(
        self,
        asset_id: UUID,
        from_snapshot: dict[str, FieldSchema],
        to_snapshot: dict[str, FieldSchema],
        from_snapshot_id: UUID,
        to_snapshot_id: UUID,
    ) -> ComparisonResult:
        """
        比对两个快照的字段差异

        Args:
            asset_id: 资产 ID
            from_snapshot: 旧快照字段映射
            to_snapshot: 新快照字段映射
            from_snapshot_id: 旧快照 ID
            to_snapshot_id: 新快照 ID

        Returns:
            ComparisonResult: 比对结果
        """
        changes: list[FieldChange] = []
        from_paths = set(from_snapshot.keys())
        to_paths = set(to_snapshot.keys())

        # 1. 检测字段新增
        added_paths = to_paths - from_paths
        for path in added_paths:
            field_schema = to_snapshot[path]
            severity = self._determine_severity_for_add(path, field_schema)
            changes.append(FieldChange(
                change_type=ChangeType.FIELD_ADDED,
                field_path=path,
                from_value=None,
                to_value=field_schema.type.value,
                severity=severity,
                description=f"字段新增: {path} ({field_schema.type.value})",
            ))

        # 2. 检测字段删除
        removed_paths = from_paths - to_paths
        for path in removed_paths:
            field_schema = from_snapshot[path]
            severity = self._determine_severity_for_remove(path, field_schema)
            changes.append(FieldChange(
                change_type=ChangeType.FIELD_REMOVED,
                field_path=path,
                from_value=field_schema.type.value,
                to_value=None,
                severity=severity,
                description=f"字段删除: {path}",
            ))

        # 3. 检测共同字段的变更
        common_paths = from_paths & to_paths
        for path in common_paths:
            from_field = from_snapshot[path]
            to_field = to_snapshot[path]

            # 类型变更
            if from_field.type != to_field.type:
                is_breaking = self.TYPE_COMPATIBILITY.get(
                    (from_field.type, to_field.type), True
                )
                severity = ChangeSeverity.P0_BREAKING if is_breaking else ChangeSeverity.P1_MAJOR
                # 关键业务字段类型变化一定是 P0
                if is_breaking and self._is_key_field(path):
                    severity = ChangeSeverity.P0_BREAKING
                changes.append(FieldChange(
                    change_type=ChangeType.FIELD_TYPE_CHANGED,
                    field_path=path,
                    from_value=from_field.type.value,
                    to_value=to_field.type.value,
                    severity=severity,
                    description=f"类型变化: {path} ({from_field.type.value} -> {to_field.type.value})",
                ))

            # 枚举值变更
            if from_field.enum_values is not None or to_field.enum_values is not None:
                enum_changes = self._compare_enum_values(path, from_field, to_field)
                changes.extend(enum_changes)

        # 4. 检测嵌套结构变更（基于 path 前缀）
        structure_changes = self._detect_structure_changes(from_snapshot, to_snapshot)
        changes.extend(structure_changes)

        # 分类破坏性和非破坏性变更
        breaking_changes = [c for c in changes if c.change_type in self.BREAKING_CHANGE_TYPES or c.severity == ChangeSeverity.P0_BREAKING]
        non_breaking_changes = [c for c in changes if c not in breaking_changes]

        # 计算兼容性评分
        compatibility_score = self._calculate_compatibility_score(
            len(from_paths),
            len(to_paths),
            len(breaking_changes),
            len(non_breaking_changes),
        )

        return ComparisonResult(
            asset_id=asset_id,
            from_snapshot_id=from_snapshot_id,
            to_snapshot_id=to_snapshot_id,
            changes=changes,
            breaking_changes=breaking_changes,
            non_breaking_changes=non_breaking_changes,
            compatibility_score=compatibility_score,
        )

    def _determine_severity_for_add(self, path: str, field_schema: FieldSchema) -> ChangeSeverity:
        """确定新增字段的严重级别"""
        # P2: 新增非必填字段
        if not self._is_key_field(path):
            return ChangeSeverity.P2_MINOR
        # 关键业务字段新增
        if self._is_key_field(path):
            return ChangeSeverity.P1_MAJOR
        return ChangeSeverity.INFO

    def _determine_severity_for_remove(self, path: str, field_schema: FieldSchema) -> ChangeSeverity:
        """确定删除字段的严重级别"""
        # 关键业务字段删除 -> P0
        if self._is_key_field(path):
            return ChangeSeverity.P0_BREAKING
        # 其他字段删除 -> P0（按 spec 所有删除都是 P0）
        return ChangeSeverity.P0_BREAKING

    def _compare_enum_values(
        self,
        path: str,
        from_field: FieldSchema,
        to_field: FieldSchema,
    ) -> list[FieldChange]:
        """比对枚举值变更"""
        changes = []
        from_enums = set(from_field.enum_values or [])
        to_enums = set(to_field.enum_values or [])

        # 新增枚举值 -> P2
        added_enums = to_enums - from_enums
        for enum_val in added_enums:
            changes.append(FieldChange(
                change_type=ChangeType.ENUM_VALUE_ADDED,
                field_path=path,
                from_value=None,
                to_value=enum_val,
                severity=ChangeSeverity.P2_MINOR,
                description=f"枚举值新增: {path} = {enum_val}",
            ))

        # 删除枚举值 -> P0
        removed_enums = from_enums - to_enums
        for enum_val in removed_enums:
            changes.append(FieldChange(
                change_type=ChangeType.ENUM_VALUE_REMOVED,
                field_path=path,
                from_value=enum_val,
                to_value=None,
                severity=ChangeSeverity.P0_BREAKING,
                description=f"枚举值删除: {path} = {enum_val}",
            ))

        return changes

    def _detect_structure_changes(
        self,
        from_snapshot: dict[str, FieldSchema],
        to_snapshot: dict[str, FieldSchema],
    ) -> list[FieldChange]:
        """检测嵌套结构变更"""
        changes = []

        # 提取顶级 path 前缀
        from_prefixes = self._extract_path_prefixes(from_snapshot.keys())
        to_prefixes = self._extract_path_prefixes(to_snapshot.keys())

        # 检测新增的顶级结构 -> P1
        for prefix in to_prefixes - from_prefixes:
            changes.append(FieldChange(
                change_type=ChangeType.NESTED_STRUCTURE_CHANGED,
                field_path=prefix,
                from_value=None,
                to_value="nested_object",
                severity=ChangeSeverity.P1_MAJOR,
                description=f"嵌套结构新增: {prefix}",
            ))

        # 检测删除的顶级结构 -> P0
        for prefix in from_prefixes - to_prefixes:
            changes.append(FieldChange(
                change_type=ChangeType.NESTED_STRUCTURE_CHANGED,
                field_path=prefix,
                from_value="nested_object",
                to_value=None,
                severity=ChangeSeverity.P0_BREAKING,
                description=f"嵌套结构删除: {prefix}",
            ))

        return changes

    def _extract_path_prefixes(self, paths: set[str]) -> set[str]:
        """提取 path 前缀（顶级结构）"""
        prefixes = set()
        for path in paths:
            clean_path = re.sub(r'\[\d+\]', '', path)
            segments = clean_path.split('.')
            if segments:
                prefixes.add(segments[0])
        return prefixes

    def _is_key_field(self, path: str) -> bool:
        """判断是否为关键业务字段"""
        for pattern in self.key_field_patterns:
            if re.search(pattern, path, re.IGNORECASE):
                return True
        return False

    def _calculate_compatibility_score(
        self,
        from_field_count: int,
        to_field_count: int,
        breaking_count: int,
        non_breaking_count: int,
    ) -> float:
        """
        计算兼容性评分（0.0 - 1.0）
        1.0 = 完全兼容
        0.0 = 完全不兼容
        """
        if from_field_count == 0 and to_field_count == 0:
            return 1.0

        total_changes = breaking_count + non_breaking_count
        if total_changes == 0:
            return 1.0

        # 破坏性变更权重更高
        breaking_weight = 1.0
        non_breaking_weight = 0.3

        base_count = max(from_field_count, to_field_count, 1)
        incompatibility_score = (
            (breaking_count * breaking_weight) +
            (non_breaking_count * non_breaking_weight)
        ) / base_count

        return max(0.0, min(1.0, 1.0 - incompatibility_score))
