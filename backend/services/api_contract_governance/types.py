"""API Contract Governance - 类型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID


class FieldType(Enum):
    """字段类型枚举"""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NULL = "null"
    OBJECT = "object"
    ARRAY = "array"


class ChangeType(Enum):
    """变更类型枚举"""
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    FIELD_TYPE_CHANGED = "field_type_changed"
    ENUM_VALUE_ADDED = "enum_value_added"
    ENUM_VALUE_REMOVED = "enum_value_removed"
    NESTED_STRUCTURE_CHANGED = "nested_structure_changed"


class ChangeSeverity(Enum):
    """变更严重级别"""
    P0_BREAKING = "p0_breaking"
    P1_MAJOR = "p1_major"
    P2_MINOR = "p2_minor"
    INFO = "info"


class AuthMethod(Enum):
    """认证方式枚举"""
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"
    JWT = "jwt"


@dataclass
class FieldSchema:
    """字段结构"""
    path: str
    type: FieldType
    value_samples: list[Any] = field(default_factory=list)
    enum_values: Optional[set[str]] = None
    nested_paths: Optional[list[str]] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "type": self.type.value,
            "value_samples": self.value_samples,
            "enum_values": list(self.enum_values) if self.enum_values else None,
            "nested_paths": self.nested_paths,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FieldSchema":
        return cls(
            path=data["path"],
            type=FieldType(data["type"]),
            value_samples=data.get("value_samples", []),
            enum_values=set(data["enum_values"]) if data.get("enum_values") else None,
            nested_paths=data.get("nested_paths"),
        )


@dataclass
class ApiResponse:
    """API 响应结构"""
    status_code: int
    headers: dict[str, str]
    body: Any
    duration_ms: int
    size_bytes: int


@dataclass
class FieldChange:
    """字段变更"""
    change_type: ChangeType
    field_path: str
    from_value: Any
    to_value: Any
    severity: ChangeSeverity
    description: str

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type.value,
            "field_path": self.field_path,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "severity": self.severity.value,
            "description": self.description,
        }


@dataclass
class ComparisonResult:
    """比对结果"""
    asset_id: UUID
    from_snapshot_id: UUID
    to_snapshot_id: UUID
    changes: list[FieldChange]
    breaking_changes: list[FieldChange]
    non_breaking_changes: list[FieldChange]
    compatibility_score: float  # 0.0 - 1.0, 1.0 = 完全兼容

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "from_snapshot_id": str(self.from_snapshot_id),
            "to_snapshot_id": str(self.to_snapshot_id),
            "changes": [c.to_dict() for c in self.changes],
            "breaking_changes": [c.to_dict() for c in self.breaking_changes],
            "non_breaking_changes": [c.to_dict() for c in self.non_breaking_changes],
            "compatibility_score": self.compatibility_score,
        }
