"""DDL 生成数据模型"""
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class ColumnDefinition:
    """列定义"""
    name: str
    data_type: str
    length: Optional[int] = None
    decimal_length: Optional[int] = None
    nullable: bool = False
    default: Optional[str] = None
    comment: str = ""
    is_primary_key: bool = False
    is_auto_increment: bool = False

    def to_sql(self, db_type: str = "mysql") -> str:
        """生成列 SQL 定义"""
        parts = []

        # 列名
        parts.append(f"`{self.name}`")

        # 数据类型
        if self.data_type.upper() in ("DECIMAL", "NUMERIC"):
            if self.length and self.decimal_length:
                parts.append(f"{self.data_type}({self.length},{self.decimal_length})")
            elif self.length:
                parts.append(f"{self.data_type}({self.length})")
            else:
                parts.append(f"{self.data_type}(10,2)")
        elif self.length and self.data_type.upper() in ("VARCHAR", "CHAR"):
            parts.append(f"{self.data_type}({self.length})")
        else:
            parts.append(self.data_type)

        # 自增
        if self.is_auto_increment and db_type == "mysql":
            parts.append("AUTO_INCREMENT")

        # 非空
        if not self.nullable:
            parts.append("NOT NULL")

        # 默认值
        if self.default:
            parts.append(f"DEFAULT {self.default}")

        # 注释
        if self.comment:
            parts.append(f"COMMENT '{self.comment}'")

        return " ".join(parts)


@dataclass
class IndexDefinition:
    """索引定义"""
    name: str
    columns: List[str]
    is_unique: bool = False
    is_primary: bool = False
    comment: str = ""

    def to_sql(self, db_type: str = "mysql") -> str:
        """生成索引 SQL 定义"""
        col_list = ", ".join([f"`{col}`" for col in self.columns])

        if self.is_primary:
            return f"PRIMARY KEY ({col_list})"
        elif self.is_unique:
            return f"UNIQUE INDEX `{self.name}` ({col_list})"
        else:
            return f"INDEX `{self.name}` ({col_list})"


@dataclass
class TableDefinition:
    """表定义"""
    table_name: str
    columns: List[ColumnDefinition] = field(default_factory=list)
    indexes: List[IndexDefinition] = field(default_factory=list)
    comment: str = ""
    database: str = ""

    def add_column(self, column: ColumnDefinition):
        """添加列"""
        self.columns.append(column)

    def add_index(self, index: IndexDefinition):
        """添加索引"""
        self.indexes.append(index)

    def get_primary_key_columns(self) -> List[str]:
        """获取主键列名"""
        return [idx.columns[0] for idx in self.indexes if idx.is_primary]

    def auto_add_timestamps(self):
        """自动添加时间戳字段"""
        has_create_time = any(col.name == "create_time" for col in self.columns)
        has_update_time = any(col.name == "update_time" for col in self.columns)

        if not has_create_time:
            self.columns.insert(0, ColumnDefinition(
                name="create_time",
                data_type="DATETIME",
                nullable=False,
                default="CURRENT_TIMESTAMP",
                comment="创建时间"
            ))

        if not has_update_time:
            # 找到 create_time 的位置，在其后插入
            idx = 1 if has_create_time else 0
            self.columns.insert(idx, ColumnDefinition(
                name="update_time",
                data_type="DATETIME",
                nullable=False,
                default="CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
                comment="更新时间"
            ))

    def auto_add_soft_delete(self):
        """自动添加软删除字段"""
        has_is_deleted = any(col.name == "is_deleted" for col in self.columns)

        if not has_is_deleted:
            self.columns.append(ColumnDefinition(
                name="is_deleted",
                data_type="TINYINT",
                length=1,
                nullable=False,
                default="0",
                comment="是否删除，0-未删除，1-已删除"
            ))

    def auto_add_primary_key(self):
        """自动添加主键（如果没有）"""
        has_pk = any(idx.is_primary for idx in self.indexes)

        if not has_pk and self.columns:
            # 创建一个 id 列作为主键
            has_id = any(col.name == "id" for col in self.columns)
            if not has_id:
                self.columns.insert(0, ColumnDefinition(
                    name="id",
                    data_type="BIGINT",
                    nullable=False,
                    is_auto_increment=True,
                    is_primary_key=True,
                    comment="主键ID"
                ))
            else:
                # 将现有的 id 列设为主键
                for col in self.columns:
                    if col.name == "id":
                        col.is_primary_key = True
                        col.nullable = False
                        col.is_auto_increment = True
                        break
                # 添加主键索引
                self.indexes.insert(0, IndexDefinition(
                    name=f"pk_{self.table_name}",
                    columns=["id"],
                    is_primary=True
                ))
