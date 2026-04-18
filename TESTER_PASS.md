# TESTER_PASS — MCP 元查询场景验收报告

验收日期：2026-04-18
验收模型：claude-sonnet-4-6
验收范围：meta_datasource_list / meta_asset_count / meta_semantic_quality

---

## 总结

**4 项验证全部通过（PASS）**

---

## 验证 1：语法与导入正确性

命令：
```
cd backend && python3 -m py_compile app/api/search.py services/llm/nlq_service.py
```

结果：**py_compile exit: 0**，两个文件均无语法错误。

---

## 验证 2：classify_meta_intent 关键词匹配（静态分析 + 逻辑验证）

说明：由于 `app/core/database.py` 在模块加载时强制校验 `DATABASE_URL` 环境变量（`raise RuntimeError`），
无法在无数据库环境下执行 `python3 -c "import classify_meta_intent"`。
改用静态代码分析，对照 `META_INTENT_KEYWORDS` 字典逐条验证函数逻辑。

`classify_meta_intent` 实现（`nlq_service.py` 第 327-339 行）：
- 遍历 `META_INTENT_KEYWORDS`，每个关键词做 `kw.lower() in question.lower()` 匹配
- 命中即返回对应 intent key，否则返回 `None`

逐条测试结果：

| 输入 | 触发关键词 | 期望 | 实际 |
|------|-----------|------|------|
| 你有哪些数据源？ | "你有哪些数据源" | meta_datasource_list | PASS |
| 有哪些数据源 | "有哪些数据源" | meta_datasource_list | PASS |
| 你有几个看板？ | "你有几个看板" | meta_asset_count | PASS |
| 有多少看板 | "有多少看板" | meta_asset_count | PASS |
| 语义配置有哪些不完善 | "语义配置有哪些不完善" | meta_semantic_quality | PASS |
| 上个月销售额是多少 | 无命中 | None | PASS |
| 各区域对比 | 无命中 | None | PASS |

**7/7 通过**

---

## 验证 3：META 意图不干扰现有流水线

grep 输出（`search.py`）：
```
28:    classify_meta_intent,
231:async def handle_meta_query(meta_intent: str, connection_id: int, db: Session) -> dict:
237:        meta_intent: classify_meta_intent() 返回的意图 key
441:        # classify_meta_intent 基于规则关键词，无 LLM 调用，优先于 VizQL 意图分类
442:        meta_intent = classify_meta_intent(question)
444:            if connection_id is None:
454:            result = await handle_meta_query(meta_intent, connection_id, db)
```

确认结论：
- `classify_meta_intent(question)`（第 442 行）在 `classify_intent(question)`（VizQL 流水线入口，第 462 行）之前执行，顺序正确
- `connection_id is None` 时（第 444 行），直接返回提示文本 `"请先在左上角选择 Tableau 连接，再提问。"`，不报错、不进入数据库查询

**PASS**

---

## 验证 4：数据库字段映射正确性（静态分析）

说明：同验证 2，DATABASE_URL 强制校验阻止运行时 import，改用源码静态对比。

### `_handle_meta_datasource_list`（search.py 第 260-294 行）

| handler 使用字段 | 模型来源 | 模型实际定义 |
|-----------------|---------|------------|
| `TableauAsset.connection_id` | `tableau/models.py` L87 | Column(Integer, ForeignKey(...)) |
| `TableauAsset.asset_type` | `tableau/models.py` L88 | Column(String(32)) |
| `TableauAsset.is_deleted` | `tableau/models.py` L97 | Column(Boolean) |
| `TableauAsset.name` | `tableau/models.py` L90 | Column(String(256)) |
| `TableauConnection.id` | `tableau/models.py` L12 | Column(Integer, primary_key=True) |
| `TableauConnection.name` | `tableau/models.py` L13 | Column(String(128)) |
| `TableauConnection.site` | `tableau/models.py` L15 | Column(String(128)) |

### `_handle_meta_asset_count`（search.py 第 297-329 行）

使用字段与上表相同，全部一致。

### `_handle_meta_semantic_quality`（search.py 第 332-374 行）

| handler 使用字段 | 模型来源 | 模型实际定义 |
|-----------------|---------|------------|
| `TableauFieldSemantics.connection_id` | `semantic_maintenance/models.py` L157 | Column(Integer) |
| `TableauFieldSemantics.semantic_definition` | `semantic_maintenance/models.py` L161 | Column(Text) |
| `TableauFieldSemantics.status` | `semantic_maintenance/models.py` L171 | Column(String(32)) |
| `TableauFieldSemantics.semantic_name_zh` | `semantic_maintenance/models.py` L160 | Column(String(256)) |
| `TableauFieldSemantics.semantic_name` | `semantic_maintenance/models.py` L159 | Column(String(256)) |
| `TableauFieldSemantics.tableau_field_id` | `semantic_maintenance/models.py` L158 | Column(String(256)) |

**全部字段名与模型定义一致，无不匹配项。PASS**

---

## 注意事项

1. `database.py` 第 15-16 行在模块加载时强制 `raise RuntimeError`（无 DATABASE_URL 即抛错），
   导致所有依赖数据库模型的单元测试无法在本地无数据库环境下执行。
   建议 coder 后续将该检查改为延迟校验（在首次建立连接时校验），
   以支持测试环境 mock 和 CI 离线验证。

2. 验证 2 和验证 4 因上述原因改为静态分析，结论可信但非运行时验证，
   建议在集成测试环境中补充运行时回归用例。
