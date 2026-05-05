"""任务拆分器 - 将大批次表拆分为小批次"""
from typing import List, Dict


class TaskSplitter:
    """将大批次表拆分为小批次，支持多种策略"""

    def split(self, table_names: List[str], batch_size: int = 50) -> List[List[str]]:
        """
        固定大小分批

        Args:
            table_names: 表名列表
            batch_size: 每批大小，默认 50

        Returns:
            分批后的表名列表
        """
        return [table_names[i:i + batch_size] for i in range(0, len(table_names), batch_size)]

    def split_by_prefix(self, table_names: List[str], prefix_groups: Dict[str, List[str]] = None) -> List[List[str]]:
        """
        按表名前缀分组（ODS/DWD/DIM等）

        Args:
            table_names: 表名列表
            prefix_groups: 前缀分组映射，{前缀: [表名列表]}
                           若为 None，使用默认规则：
                           - ODS_: 原始层
                           - DWD_: 明细层
                           - DIM_: 维度层
                           - DWS_: 汇总层
                           - ADS_: 应用层

        Returns:
            分组后的表名列表（每组为同一前缀的表）
        """
        if prefix_groups is None:
            prefix_groups = {
                "ODS_": [],
                "DWD_": [],
                "DIM_": [],
                "DWS_": [],
                "ADS_": [],
            }
            # 按前缀分类
            for table_name in table_names:
                assigned = False
                for prefix in prefix_groups:
                    if table_name.startswith(prefix):
                        prefix_groups[prefix].append(table_name)
                        assigned = True
                        break
                if not assigned:
                    # 未分类的表归入 "OTHER_"
                    if "OTHER_" not in prefix_groups:
                        prefix_groups["OTHER_"] = []
                    prefix_groups["OTHER_"].append(table_name)

        # 返回非空组
        return [tables for tables in prefix_groups.values() if tables]