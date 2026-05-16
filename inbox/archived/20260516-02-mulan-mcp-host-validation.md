# MCP Host Gate Validation Notes

Date: 2026-05-16

This is a working validation note, not a formal test report.

## Live Q1-Q4 Capture Command

Run after the backend and Tableau MCP gateway are available:

```bash
cd /Users/forrest/Projects/mulan-bi-platform
backend/.venv/bin/python - <<'PY'
import json
import re
import time
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"
CONNECTION_ID = 2
OUT = Path("inbox/20260516-02-mulan-mcp-host-q1-q4-trace.json")
QUESTIONS = [
    ("Q1", "整体的销售额、利润、利润率、客户数、客单价是什么样子"),
    ("Q2", "这个指标过去几年的趋势是什么样子"),
    ("Q3", "统计一下每个子类别的销售额、利润和利润率"),
    ("Q4", "继续拆分到每个年份"),
]

def parse_sse(text):
    events = []
    for match in re.finditer(r"^data:\s*(.+)$", text, flags=re.M):
        payload = match.group(1).strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            events.append({"type": "_decode_error", "raw": payload})
    return events

session = requests.Session()
login = session.post(
    f"{BASE_URL}/api/auth/login",
    json={"username": "admin", "password": "admin123"},
    timeout=30,
)
login.raise_for_status()

out = {"mulan": {}}
conversation_id = None
for qid, question in QUESTIONS:
    payload = {"question": question, "connection_id": CONNECTION_ID}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    started = time.perf_counter()
    response = session.post(f"{BASE_URL}/api/agent/stream", json=payload, stream=True, timeout=180)
    chunks = [chunk for chunk in response.iter_content(chunk_size=None, decode_unicode=True) if chunk]
    text = "".join(chunks)
    events = parse_sse(text)
    done = next((event for event in reversed(events) if event.get("type") == "done"), None)
    error = next((event for event in reversed(events) if event.get("type") == "error"), None)
    meta = next((event for event in events if event.get("type") == "metadata"), None)
    conversation_id = (meta or {}).get("conversation_id") or conversation_id
    out["mulan"][qid] = {
        "duration": time.perf_counter() - started,
        "status_code": response.status_code,
        "conversation_id": conversation_id,
        "done": done,
        "error": error,
        "events": events,
        "raw_text_tail": text[-2000:],
    }
    print(qid, response.status_code, "done=", bool(done), "error=", bool(error), "conversation=", conversation_id)

OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", OUT)
PY
```

## Gate Command

```bash
cd /Users/forrest/Projects/mulan-bi-platform/backend
.venv/bin/python -m services.data_agent.mcp_host.quality_gate \
  --runs ../inbox/20260516-02-mulan-mcp-host-q1-q4-trace.json \
  --baseline ../inbox/20260515-13-abtest-raw.json \
  --report ../inbox/20260516-02-mulan-mcp-host-quality-report.json
```

## Gate Rules

- Q1-Q4 must each have a live Mulan artifact.
- Baseline comparison uses `inbox/20260515-13-abtest-raw.json` and reads `mcp.<QID>.data` as the direct MCP baseline.
- Each live QID must include table-shaped `response_data` and MCP trace evidence.
- Live artifacts must not contain forbidden QuerySpec markers such as `queryspec`, `llm_queryspec`, `queryspec_fallback`, `query_plan_rejected`, `planning_skill_loader`, or `llm_mcp_args`.
- The live `response_data` table must include all direct MCP baseline fields and must match the baseline row count and row values within numeric tolerance.
- Any Q1-Q4 blocker makes the gate fail.

## 2026-05-16 Q2 Inheritance Repair Validation

Commands:

```bash
backend/.venv/bin/python -m py_compile \
  backend/services/data_agent/mcp_first_main.py \
  backend/tests/services/data_agent/test_mcp_first_main.py

backend/.venv/bin/python -m pytest backend/tests/services/data_agent/test_mcp_first_main.py -q

backend/.venv/bin/python -m pytest \
  backend/tests/services/data_agent/test_mcp_host_runtime.py \
  backend/tests/services/data_agent/test_mcp_host_planner.py \
  backend/tests/services/data_agent/test_mcp_host_quality_gate.py \
  backend/tests/services/data_agent/test_mcp_first_main.py \
  backend/tests/services/data_agent/test_mcp_proxy_main.py \
  backend/tests/services/tableau/test_mcp_client.py \
  backend/tests/services/data_agent/test_queryspec_fallback.py \
  backend/tests/services/data_agent/test_dynamic_column_engine.py \
  backend/tests/services/data_agent/test_llm_queryspec_stability.py \
  backend/tests/services/data_agent/test_mcp_args_guardrail.py -q

backend/.venv/bin/python -m services.data_agent.mcp_host.quality_gate \
  --runs inbox/20260516-02-mulan-mcp-host-q1-q4-trace.json \
  --baseline inbox/20260515-13-abtest-raw.json \
  --report inbox/20260516-02-mulan-mcp-host-quality-report.json
```

Results:

- `py_compile`: pass.
- `test_mcp_first_main.py`: 25 passed.
- Related MCP Host/Data Agent suite: 149 passed.
- Live Q1-Q4 gate: pass, 4/4 cases passed, 0 blockers.
- Q2 live fields after repair: `YEAR(发货日期)`, `利润率`, `SUM(销售额)`, `SUM(利润)`, `COUNTD(客户名称)`.
