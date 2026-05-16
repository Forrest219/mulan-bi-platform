# MCP Host Q5-Q10 Live Validation

Date: 2026-05-16

## Scope

- Baseline: `inbox/20260515-13-abtest-raw.json`
- Live trace: `inbox/20260516-02-mulan-mcp-host-q5-q10-trace.json`
- Gate report: `inbox/20260516-02-mulan-mcp-host-q5-q10-quality-report.json`
- Q10 retry trace: `inbox/20260516-02-mulan-mcp-host-q10-retry-trace.json`

## Commands

```bash
backend/.venv/bin/python -m services.data_agent.mcp_host.quality_gate \
  --runs inbox/20260516-02-mulan-mcp-host-q5-q10-trace.json \
  --baseline inbox/20260515-13-abtest-raw.json \
  --report inbox/20260516-02-mulan-mcp-host-q5-q10-quality-report.json \
  --qid Q5 --qid Q6 --qid Q7 --qid Q8 --qid Q9 --qid Q10
```

## Live Capture Summary

- Q5: done, 12 rows, fields `子类别`.
- Q6: done, 10 rows, fields `客户名称`, `SUM(销售额)`.
- Q7: done, 13 rows, fields `客户名称`, `YEAR(发货日期)`, `MONTH(发货日期)`, `SUM(销售额)`, `SUM(利润)`, `子类别`.
- Q8: done, 80 rows, fields `YEAR(发货日期)`, `子类别`, `SUM(利润)`, `SUM(销售额)`.
- Q9: done, 31 rows, fields `省/自治区`, `SUM(利润)`.
- Q10: error, `MCP_HOST_PLANNER_UNAVAILABLE`.

## Gate Result

- Mechanical gate status: block.
- Passed: Q6.
- Blocked: Q5, Q7, Q8, Q9, Q10.

Notes:

- The current gate is table-oriented. Q5, Q8, Q9, and Q10 direct MCP baselines contain derived or multi-table structures, so the gate is useful for blocker detection but not sufficient as the only semantic comparator for these cases.
- Q7 is a direct table comparison failure: live output is lower-level month/subcategory detail, while baseline is year-level customer summary.

## Semantic Findings

- Q5 fails semantically. Baseline missing subcategories are `信封`, `复印机`, `桌子`, `设备`, `配件`; live output returned the 12 subcategories that do have 2025 sales.
- Q6 passes. Live rows match baseline Top 10 customers by `SUM(销售额)`.
- Q7 has correct underlying values after regrouping by year, but response_data is not baseline-shaped. Baseline has 2 year rows; live has 13 detail rows.
- Q8 has sufficient source rows to derive the baseline increasing subcategories: `器具`, `复印机`, `用具`, `系固件`, `纸张`. Live response does not return that derived answer directly.
- Q9 fails semantically. Baseline asks for provinces losing money every full year 2021-2024 and expects `重庆`; live returns total profit by province across years.
- Q10 first sequence run fails with planner unavailable. A fresh single-question retry returns 244 detail rows. Those rows can derive the baseline product/customer Top 10 exactly, but live response_data is not baseline-shaped and the user-facing answer is only a generic row-count message.
