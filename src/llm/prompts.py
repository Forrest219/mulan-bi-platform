"""Prompt 模板"""

ASSET_SUMMARY_TEMPLATE = """你是一个数据分析助手。请根据以下 Tableau 资产信息，生成一段简洁的中文摘要（100字以内）。

资产类型：{asset_type}
名称：{name}
项目：{project_name}
描述：{description}
所有者：{owner_name}

请直接输出摘要内容，无需额外说明。"""

ASSET_EXPLAIN_TEMPLATE = """你是一个 BI 报表解读专家。请根据以下报表信息，用通俗易懂的语言向业务用户解释这个报表。

## 报表基本信息
名称：{name}
项目：{project_name}
描述：{description}

## 关联数据源
{datasources}

请用 2~3 句话解释这个报表的用途和关键指标，要求：
1. 面向非技术业务人员
2. 说明主要指标含义
3. 指出可能的数据关注点"""
