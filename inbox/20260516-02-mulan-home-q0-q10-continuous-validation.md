# Mulan Home Q0-Q10 Continuous Accuracy Validation

Date: 2026-05-16

## Scope

- Test target: Mulan home continuous Q&A flow via `/api/agent/stream`.
- Baseline: `inbox/20260515-13-abtest-raw.json`.
- Direct MCP baseline was reused from the baseline artifact and was not rerun.
- Live trace: `inbox/20260516-02-mulan-home-q0-q10-continuous-trace.json`.
- Accuracy report: `inbox/20260516-02-mulan-home-q0-q10-accuracy-report.json`.
- Mechanical Q1-Q4 gate report: `inbox/20260516-02-mulan-home-q1-q4-quality-report.json`.

## Method

Run Q0 through Q10 in one conversation, carrying `conversation_id` forward for each question.

Datasource context:

- `connection_id`: 2
- `datasource_luid`: `f4290485-26d3-428f-aa8d-ccc33862a411`
- `datasource_name`: `订单+ (示例 - 超市)`

The accuracy comparator reuses previous direct MCP results and checks content equivalence:

- Q0: datasource field inventory.
- Q1-Q4 and Q6: baseline table fields and rows.
- Q5: expected set difference result.
- Q7: yearly customer summary, with `period` treated as `YEAR(发货日期)`.
- Q8: increasing subcategory set.
- Q9: all-period losing province set.
- Q10: root-cause product/customer contributors.

## Live Summary

- Q0: done, no error.
- Q1: done, 1 row.
- Q2: done, 5 rows.
- Q3: done, 17 rows.
- Q4: done, 80 rows.
- Q5: done, 5 rows.
- Q6: done, 10 rows.
- Q7: done, 2 rows.
- Q8: done, 5 rows.
- Q9: done, 1 row.
- Q10: done, 20 rows.

## Accuracy Result

- Overall status: block.
- Passed: 10/11.
- Blocked: Q10.

Case status:

- Q0: pass.
- Q1: pass.
- Q2: pass.
- Q3: pass.
- Q4: pass.
- Q5: pass.
- Q6: pass.
- Q7: pass.
- Q8: pass.
- Q9: pass.
- Q10: block.

## Q10 Blocker

Baseline separates product and customer contributors by province:

- Product baseline top 3: `辽宁-装订机`, `福建-设备`, `辽宁-设备`.
- Customer baseline top 3: `福建-殷丽雪`, `辽宁-黄涛`, `辽宁-柯巧`.

Live Mulan returns combined contributors without province:

- Product live top 3: `设备`, `装订机`, `桌子`.
- Customer live top 3: `殷丽雪`, `黄涛`, `柯巧`.

This loses the province dimension required by the baseline, so Q10 is not equivalent even though the query returned data.

## Route Note

The strict MCP Host Q1-Q4 mechanical gate blocks on QuerySpec fallback markers in this continuous home run, although the Q1-Q4 table values match the direct MCP baseline. This validation is therefore an answer-accuracy check for the home flow, not a strict MCP Host route compliance gate.
