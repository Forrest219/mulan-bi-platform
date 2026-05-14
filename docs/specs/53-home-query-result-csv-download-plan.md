# 首页问答结果 CSV 下载开发计划

> 版本：v0.1 | 状态：Ready for Coder | 日期：2026-05-14 | 范围：首页问答表格结果

---

## 1. 目标

在首页问答结果表格上增加“下载 CSV”按钮，导出当前前端已拿到的表格数据。

P0 不新增后端接口，不重新执行查询，不改变 Data Agent 查询链路。

---

## 2. 最低成本方案

采用前端本地导出：

- 数据来源：`QueryResultTable` 组件接收到的 `data.fields` 与 `data.rows`。
- 导出格式：CSV。
- 下载方式：浏览器 `Blob` + 临时 `a[download]`。
- 适用范围：
  - 当前 SSE 流式回答产生的表格。
  - URL `conv=` 恢复的历史表格。

---

## 3. 修改范围

### 3.1 必改文件

| 文件 | 修改内容 |
|---|---|
| `frontend/src/components/chat/QueryResultTable.tsx` | 增加 CSV 转换与下载按钮 |

### 3.2 不修改

- 后端 API。
- 数据库。
- Data Agent 查询逻辑。
- 会话恢复逻辑。
- `MessageActions` props 链路。

---

## 4. 实现要求

### 4.1 CSV 生成规则

- 第一行为表头：优先使用表格当前展示列名，未配置展示列名时使用 `fields`。
- 后续为数据行：`rows`。
- `null` / `undefined` 导出为空字符串。
- 包含逗号、双引号、换行时，用双引号包裹。
- 双引号转义为 `""`。
- 文件内容前加 UTF-8 BOM，避免 Excel 打开中文乱码。

### 4.2 下载范围

- 导出全部 `data.rows`。
- 不只导出当前分页 `pageRows`。
- P0 默认导出原始返回顺序，不跟随 UI 排序状态。

### 4.3 UI 规则

- 有表格数据时显示“下载 CSV”按钮。
- 按钮建议放在表格底部统计栏右侧，与分页控件同一行。
- icon 使用 `ri-download-2-line`。
- `rows.length === 0` 时不显示按钮。
- 不影响现有排序、分页、数字格式和负数样式。

---

## 5. Coder Tasks

1. 在 `QueryResultTable.tsx` 新增 `escapeCsvCell`。
2. 新增 `tableDataToCsv(fields, rows)`。
3. 新增 `downloadCsv(filename, csv)`。
4. 在 `QueryResultTable` 中新增 `handleDownloadCsv`。
5. 在底部操作栏展示下载按钮。
6. 确认下载行数等于 `data.rows.length`。

---

## 6. Tester Tasks

1. 打开首页历史会话：

```text
http://localhost:3000/?conv=3d107067-2af0-4599-b58d-0519e069aa6d&connection=2
```

2. 找到表格回答。
3. 点击“下载 CSV”。
4. 用 Numbers / Excel / 文本编辑器打开。
5. 验证：
   - 中文不乱码。
   - 表头正确。
   - 行数等于当前已返回行数。
   - 分页状态下仍导出全部已返回数据。

---

## 7. 验收标准

- [ ] 有表格结果时显示“下载 CSV”。
- [ ] 点击后下载 `.csv` 文件。
- [ ] 中文列名和中文内容不乱码。
- [ ] 导出的行数等于 `data.rows.length`。
- [ ] 分页时导出全部已返回数据。
- [ ] 纯文本回答不出现下载按钮。
- [ ] 现有表格排序和分页不被破坏。
- [ ] `npm run type-check` 通过。

---

## 8. 已知限制

- 如果后端只返回截断后的数据，CSV 只能导出截断后的数据。
- P0 不支持 `.xlsx`。
- P0 不做下载审计。
- P0 不重新查询数据库以获取完整数据。
