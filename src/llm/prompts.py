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
类型：{asset_type}
项目：{project_name}
描述：{description}
所有者：{owner_name}

## 所属工作簿
{parent_workbook_info}

## 关联数据源
{datasources}

## 数据源字段元数据
{field_metadata}

请提供以下内容:
1. **报表概述**: 用 2~3 句话说明这个报表的核心用途
2. **关键指标**: 列出报表涉及的主要指标，并用业务语言解释其含义
3. **维度说明**: 说明报表的主要分析维度
4. **数据关注点**: 指出使用此报表时需要注意的要点
5. **适用场景**: 建议在什么场景下使用此报表

要求:
- 面向非技术业务人员
- 使用中文
- 如果字段元数据中有计算字段公式，要解释其业务含义而非技术实现"""

NL_TO_QUERY_TEMPLATE = """你是一个 Tableau 数据查询专家。请将用户的自然语言问题转换为 Tableau VizQL 查询 JSON。

## 可用数据源
数据源 LUID: {datasource_luid}
数据源名称: {datasource_name}

## 可用字段
{fields_with_types}

## 业务术语映射
{term_mappings}

## 用户问题
{question}

请生成符合以下格式的 JSON:
{{
  "fields": [
    {{"fieldCaption": "字段显示名", "function": "SUM"}},
    {{"fieldCaption": "维度字段"}}
  ],
  "filters": []
}}

规则:
- 度量字段必须指定 function (SUM/AVG/COUNT/COUNTD/MIN/MAX 等)
- 维度字段不需要 function
- 如需排序，添加 sortDirection ("ASC"/"DESC") 和 sortPriority
- 如需限制条数，使用 TOP 类型 filter
- 仅输出 JSON，不要其他内容"""
