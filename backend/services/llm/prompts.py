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

ONE_PASS_NL_TO_QUERY_TEMPLATE = """你是一个 Tableau 数据查询专家。请分析以下用户问题，同时完成意图分类和 VizQL JSON 生成。

数据源信息：
- datasource_luid: {datasource_luid}
- datasource_name: {datasource_name}

可用字段：
{fields_with_types}

业务术语映射：
{term_mappings}

用户问题：{question}

请以以下 JSON 格式输出（直接输出 JSON，不要包含任何解释文字）：
{{
  "intent": "<aggregate|filter|ranking|trend|comparison>",
  "confidence": <0.0-1.0>,
  "vizql_json": {{
    "fields": [...],
    "filters": [...]
  }}
}}

注意：
- intent 必须为 aggregate/filter/ranking/trend/comparison 之一
- confidence 表示你对整个解析结果的置信度（综合意图判断 + 字段映射 + 过滤条件）
- 如果用户问题无法解析为有效查询，confidence 设为 0.1
- fields 至少包含一个字段，function 可选（维度字段无需 function）
- filters 用于时间过滤、分类过滤、数值范围过滤等
"""

# === 带反馈重试的 Retry Prompt 模板 ===
ONE_PASS_RETRY_TEMPLATE = """你上次的 JSON 输出无法通过格式校验，存在以下错误：

{error_details}

请严格按照以下 JSON Schema 格式重新生成（直接输出 JSON，不要包含任何解释文字）：
{{
  "intent": "<aggregate|filter|ranking|trend|comparison>",
  "confidence": <0.0-1.0>,
  "vizql_json": {{
    "fields": [...],
    "filters": [...]
  }}
}}
"""


# === Semantic Maintenance AI 语义生成模板（Spec 12 §4.3/§4.4）===
AI_SEMANTIC_DS_TEMPLATE = """你是一个 BI 数据语义专家。请为以下数据源生成业务语义建议。

## 数据源信息
名称：{ds_name}
描述：{description}
现有语义名：{existing_semantic_name}
现有中文名：{existing_semantic_name_zh}

## 字段列表
{field_context}

请以 JSON 格式输出语义建议，包含以下字段：
- semantic_name: 英文语义名
- semantic_name_zh: 中文语义名（必填）
- semantic_description: 语义描述（必填）
- business_definition: 业务定义
- owner: 责任人建议
- sensitivity_level: 敏感级别（low/medium/high/confidential）
- tags_json: JSON 格式标签数组
- confidence: AI 置信度 0~1

只输出 JSON，不要有其他文字。"""

AI_SEMANTIC_FIELD_TEMPLATE = """你是一个 BI 字段语义专家。请为以下字段生成语义建议。

## 字段信息
字段名：{field_name}
数据类型：{data_type}
角色：{role}
公式：{formula}
现有语义名：{existing_semantic_name}
现有中文名：{existing_semantic_name_zh}
枚举值示例：
{enum_values}

请以 JSON 格式输出语义建议：
- semantic_name: 英文语义名
- semantic_name_zh: 中文语义名（必填）
- semantic_description: 语义定义（必填）
- semantic_type: 语义类型（dimension / measure / time_dimension）
- metric_definition: 指标口径（若为 measure 字段必填）
- dimension_definition: 维度解释（若为 dimension 字段必填）
- unit: 单位（如金额、百分比、人次等）
- synonyms_json: JSON 同义词数组
- sensitivity_level: 敏感级别（low/medium/high/confidential）
- is_core_field: 是否为核心字段（true/false）
- confidence: AI 置信度 0~1
- tags_json: JSON 标签数组

只输出 JSON，不要有其他文字。"""


# === 旧模板（保留兼容，如不需要可删除）===
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
