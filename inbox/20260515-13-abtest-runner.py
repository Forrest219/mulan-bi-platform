import json
import re
import time
from pathlib import Path

import requests


BASE_URL = "http://localhost:8000"
MCP_URL = "http://localhost:3927/tableau-mcp"
CONNECTION_ID = 2
DATASOURCE_LUID = "f4290485-26d3-428f-aa8d-ccc33862a411"
OUT_JSON = Path("inbox/20260515-13-abtest-raw.json")

QUESTIONS = [
    ("Q0", "介绍数据源“订单+ (示例 - 超市)”"),
    ("Q1", "整体的销售额、利润、利润率、客户数、客单价是什么样子"),
    ("Q2", "这个指标过去几年的趋势是什么样子"),
    ("Q3", "统计一下每个子类别的销售额、利润和利润率"),
    ("Q4", "继续拆分到每个年份"),
    ("Q5", "2025 年没有销售记录的子类别有哪些？"),
    ("Q6", "Top 10 大客户是谁？请列出客户名称和销售金额及占比"),
    ("Q7", "“邓保”这个客户的合作记录是什么样？最近还有合作吗？"),
    ("Q8", "哪个子类别的利润每年都在持续增长？"),
    ("Q9", "我计划关闭一些区域，止损。哪些省份一致没挣到钱？利润是亏的"),
    ("Q10", "为什么辽宁、福建在 2024 年出现了巨亏？请看看是什么产品线和客户导致的"),
]


def parse_sse(text: str):
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


class McpSession:
    def __init__(self):
        self.s = requests.Session()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "codex-abtest", "version": "1"},
            },
        }
        r = self.s.post(MCP_URL, headers=self.headers, json=init, timeout=30)
        r.raise_for_status()
        sid = r.headers.get("mcp-session-id")
        if not sid:
            raise RuntimeError("missing mcp-session-id")
        self.headers["mcp-session-id"] = sid
        self.s.post(
            MCP_URL,
            headers=self.headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout=30,
        )
        self.next_id = 2

    def call(self, name, arguments, timeout=90):
        req = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        self.next_id += 1
        t0 = time.perf_counter()
        r = self.s.post(MCP_URL, headers=self.headers, json=req, timeout=timeout)
        elapsed = time.perf_counter() - t0
        r.raise_for_status()
        events = parse_sse(r.text)
        body = events[-1] if events else {}
        if "error" in body:
            return {"elapsed": elapsed, "error": body["error"], "raw": body}
        result = body.get("result", {})
        if result.get("isError"):
            return {"elapsed": elapsed, "error": result.get("content"), "raw": body}
        content = result.get("content") or []
        text = content[0].get("text", "{}") if content else "{}"
        data = json.loads(text)
        if isinstance(data, dict) and "data" in data and "rows" not in data:
            records = data.get("data") or []
            fields = list(records[0].keys()) if records and isinstance(records[0], dict) else []
            rows = [[rec.get(f) for f in fields] for rec in records if isinstance(rec, dict)]
            data = {**data, "fields": fields, "rows": rows}
        return {"elapsed": elapsed, "data": data, "raw": body}

    def metadata(self):
        return self.call("get-datasource-metadata", {"datasourceLuid": DATASOURCE_LUID})

    def query(self, fields, filters=None, limit=1000):
        return self.call(
            "query-datasource",
            {
                "datasourceLuid": DATASOURCE_LUID,
                "query": {"fields": fields, "filters": filters or []},
                "limit": limit,
            },
        )


def yfilter(year):
    return {
        "field": {"fieldCaption": "发货日期"},
        "filterType": "QUANTITATIVE_DATE",
        "quantitativeFilterType": "RANGE",
        "minDate": f"{year}-01-01",
        "maxDate": f"{year}-12-31",
    }


def set_filter(field, values):
    return {"field": {"fieldCaption": field}, "filterType": "SET", "values": values}


def rows(result):
    return (result.get("data") or {}).get("rows") or []


def fields(result):
    return (result.get("data") or {}).get("fields") or []


def rowdicts(result):
    fs = fields(result)
    return [dict(zip(fs, row)) for row in rows(result)]


def num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def fmt_wan(v):
    return f"{num(v) / 10000:.2f}万"


def metric_key(name, agg="SUM"):
    return f"{agg}({name})"


def mcp_baseline():
    m = McpSession()
    out = {}

    meta = m.metadata()
    ds = ((meta.get("data") or {}).get("datasource")) or {}
    groups = (meta.get("data") or {}).get("fieldGroups") or []
    ds_fields = ds.get("fields") or [
        field
        for group in groups
        for field in (group.get("fields") or [])
    ]
    out["Q0"] = {
        "duration": meta["elapsed"],
        "row_count": len(ds_fields),
        "core": f"数据源 订单+ (示例 - 超市)，字段 {len(ds_fields)} 个：{', '.join([f.get('name', '') for f in ds_fields[:11]])}。",
        "data": meta.get("data"),
    }

    q1 = m.query([
        {"fieldCaption": "销售额", "function": "SUM"},
        {"fieldCaption": "利润", "function": "SUM"},
        {"fieldCaption": "客户名称", "function": "COUNTD"},
    ], limit=10)
    r = rowdicts(q1)[0]
    sales, profit, customers = num(r[metric_key("销售额")]), num(r[metric_key("利润")]), num(r[metric_key("客户名称", "COUNTD")])
    out["Q1"] = {
        "duration": q1["elapsed"],
        "row_count": len(rows(q1)),
        "core": f"销售额 {fmt_wan(sales)}，利润 {fmt_wan(profit)}，利润率 {profit / sales * 100:.2f}%，客户数 {customers:.0f}，客单价 {fmt_wan(sales / customers)}。",
        "data": q1.get("data"),
    }

    q2 = m.query([
        {"fieldCaption": "发货日期", "function": "YEAR"},
        {"fieldCaption": "销售额", "function": "SUM"},
        {"fieldCaption": "利润", "function": "SUM"},
        {"fieldCaption": "客户名称", "function": "COUNTD"},
    ], limit=20)
    trends = sorted(rowdicts(q2), key=lambda x: str(x.get("YEAR(发货日期)")))
    trend_txt = "；".join(
        f"{d.get('YEAR(发货日期)')} 销售额 {fmt_wan(d.get(metric_key('销售额')))}、利润率 {num(d.get(metric_key('利润'))) / max(num(d.get(metric_key('销售额'))), 1) * 100:.2f}%"
        for d in trends
    )
    out["Q2"] = {"duration": q2["elapsed"], "row_count": len(trends), "core": trend_txt, "data": q2.get("data")}

    q3 = m.query([
        {"fieldCaption": "子类别"},
        {"fieldCaption": "销售额", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1},
        {"fieldCaption": "利润", "function": "SUM"},
    ], limit=100)
    subcats = rowdicts(q3)
    top3 = subcats[:3]
    losses = [d for d in subcats if num(d.get(metric_key("利润"))) < 0]
    top3_text = ", ".join(
        f"{d.get('子类别')} {fmt_wan(d.get(metric_key('销售额')))}"
        for d in top3
    )
    losses_text = ", ".join(
        f"{d.get('子类别')} {fmt_wan(d.get(metric_key('利润')))}"
        for d in losses
    )
    out["Q3"] = {
        "duration": q3["elapsed"],
        "row_count": len(subcats),
        "core": f"返回 {len(subcats)} 个子类别；销售额 Top3 为 {top3_text}；亏损项 {losses_text}。",
        "data": q3.get("data"),
    }

    q4 = m.query([
        {"fieldCaption": "子类别"},
        {"fieldCaption": "发货日期", "function": "YEAR"},
        {"fieldCaption": "销售额", "function": "SUM"},
        {"fieldCaption": "利润", "function": "SUM"},
    ], limit=200)
    q4rows = rowdicts(q4)
    books = sorted([d for d in q4rows if d.get("子类别") == "书架"], key=lambda x: x.get("YEAR(发货日期)"))
    books_text = ", ".join(
        f"{d.get('YEAR(发货日期)')} {fmt_wan(d.get(metric_key('利润')))}"
        for d in books
        if str(d.get("YEAR(发货日期)")) in {"2021", "2022", "2023", "2024"}
    )
    out["Q4"] = {
        "duration": q4["elapsed"],
        "row_count": len(q4rows),
        "core": f"返回 {len(q4rows)} 行子类别×年份；书架 2021-2024 利润为 {books_text}。",
        "data": q4.get("data"),
    }

    qall = m.query([{"fieldCaption": "子类别"}], limit=100)
    q2025 = m.query([{"fieldCaption": "子类别"}], filters=[yfilter(2025)], limit=100)
    all_set = {d.get("子类别") for d in rowdicts(qall)}
    y2025_set = {d.get("子类别") for d in rowdicts(q2025)}
    missing = sorted(all_set - y2025_set)
    out["Q5"] = {
        "duration": qall["elapsed"] + q2025["elapsed"],
        "row_count": len(missing),
        "core": f"差集结果 {len(missing)} 个：{', '.join(missing)}。",
        "data": {"missing": missing, "all": qall.get("data"), "y2025": q2025.get("data")},
    }

    q6_total = m.query([{"fieldCaption": "销售额", "function": "SUM"}], limit=10)
    total_sales = num(rowdicts(q6_total)[0].get(metric_key("销售额")))
    q6 = m.query([
        {"fieldCaption": "客户名称"},
        {"fieldCaption": "销售额", "function": "SUM", "sortDirection": "DESC", "sortPriority": 1},
    ], limit=10)
    q6rows = rowdicts(q6)
    out["Q6"] = {
        "duration": q6_total["elapsed"] + q6["elapsed"],
        "row_count": len(q6rows),
        "core": "Top3：" + "、".join(f"{d.get('客户名称')} {fmt_wan(d.get(metric_key('销售额')))}({num(d.get(metric_key('销售额'))) / total_sales * 100:.2f}%)" for d in q6rows[:3]) + "。",
        "data": q6.get("data"),
    }

    q7 = m.query([
        {"fieldCaption": "发货日期", "function": "YEAR"},
        {"fieldCaption": "销售额", "function": "SUM"},
        {"fieldCaption": "利润", "function": "SUM"},
    ], filters=[set_filter("客户名称", ["邓保"])], limit=20)
    q7rows = sorted(rowdicts(q7), key=lambda x: str(x.get("YEAR(发货日期)")))
    out["Q7"] = {
        "duration": q7["elapsed"],
        "row_count": len(q7rows),
        "core": "邓保仅 " + "、".join(f"{d.get('YEAR(发货日期)')} 销售额 {fmt_wan(d.get(metric_key('销售额')))}、利润 {fmt_wan(d.get(metric_key('利润')))}" for d in q7rows) + f"；最近记录 {q7rows[-1].get('YEAR(发货日期)') if q7rows else '无'} 年。",
        "data": q7.get("data"),
    }

    by_sub_year = {}
    for d in q4rows:
        year = str(d.get("YEAR(发货日期)"))
        if year in {"2021", "2022", "2023", "2024"}:
            by_sub_year.setdefault(d.get("子类别"), {})[year] = num(d.get(metric_key("利润")))
    inc = sorted([
        sub for sub, vals in by_sub_year.items()
        if all(y in vals for y in ["2021", "2022", "2023", "2024"])
        and vals["2021"] < vals["2022"] < vals["2023"] < vals["2024"]
    ])
    out["Q8"] = {
        "duration": q4["elapsed"],
        "row_count": len(inc),
        "core": f"按完整 2021-2024 年口径，持续增长子类别为 {', '.join(inc)}。",
        "data": {"increasing": inc, "source": q4.get("data")},
    }

    q9 = m.query([
        {"fieldCaption": "省/自治区"},
        {"fieldCaption": "发货日期", "function": "YEAR"},
        {"fieldCaption": "利润", "function": "SUM"},
    ], limit=500)
    by_prov_year = {}
    for d in rowdicts(q9):
        year = str(d.get("YEAR(发货日期)"))
        if year in {"2021", "2022", "2023", "2024"}:
            by_prov_year.setdefault(d.get("省/自治区"), {})[year] = num(d.get(metric_key("利润")))
    losing = sorted([
        p for p, vals in by_prov_year.items()
        if all(y in vals for y in ["2021", "2022", "2023", "2024"])
        and all(vals[y] < 0 for y in ["2021", "2022", "2023", "2024"])
    ])
    out["Q9"] = {
        "duration": q9["elapsed"],
        "row_count": len(losing),
        "core": f"按完整 2021-2024 年口径，持续亏损省份为 {', '.join(losing)}。",
        "data": {"losing": losing, "source": q9.get("data")},
    }

    filters10 = [set_filter("省/自治区", ["辽宁", "福建"]), yfilter(2024)]
    q10p = m.query([
        {"fieldCaption": "省/自治区"},
        {"fieldCaption": "子类别"},
        {"fieldCaption": "利润", "function": "SUM", "sortDirection": "ASC", "sortPriority": 1},
    ], filters=filters10, limit=10)
    q10c = m.query([
        {"fieldCaption": "省/自治区"},
        {"fieldCaption": "客户名称"},
        {"fieldCaption": "利润", "function": "SUM", "sortDirection": "ASC", "sortPriority": 1},
    ], filters=filters10, limit=10)
    p_rows, c_rows = rowdicts(q10p), rowdicts(q10c)
    out["Q10"] = {
        "duration": q10p["elapsed"] + q10c["elapsed"],
        "row_count": len(p_rows) + len(c_rows),
        "core": "产品线 Top3 亏损：" + "、".join(f"{d.get('省/自治区')}-{d.get('子类别')} {fmt_wan(d.get(metric_key('利润')))}" for d in p_rows[:3]) + "；客户 Top3：" + "、".join(f"{d.get('省/自治区')}-{d.get('客户名称')} {fmt_wan(d.get(metric_key('利润')))}" for d in c_rows[:3]) + "。",
        "data": {"product": q10p.get("data"), "customer": q10c.get("data")},
    }
    return out


def login():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin123"}, timeout=30)
    r.raise_for_status()
    return s


def call_mulan(session, question, conversation_id=None):
    payload = {"question": question, "connection_id": CONNECTION_ID}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    t0 = time.perf_counter()
    r = session.post(f"{BASE_URL}/api/agent/stream", json=payload, stream=True, timeout=180)
    chunks = []
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        if chunk:
            chunks.append(chunk)
    elapsed = time.perf_counter() - t0
    text = "".join(chunks)
    events = parse_sse(text)
    done = next((e for e in reversed(events) if e.get("type") == "done"), None)
    err = next((e for e in reversed(events) if e.get("type") == "error"), None)
    meta = next((e for e in events if e.get("type") == "metadata"), None)
    table_events = [e for e in events if e.get("type") == "table_data"]
    response_data = (done or {}).get("response_data") if done else None
    if isinstance(response_data, dict) and isinstance(response_data.get("rows"), list):
        row_count = len(response_data["rows"])
    elif table_events:
        row_count = len(table_events[-1].get("rows") or [])
    elif isinstance(response_data, dict) and isinstance(response_data.get("fields"), list):
        row_count = len(response_data["fields"])
    else:
        row_count = None
    return {
        "duration": elapsed,
        "status_code": r.status_code,
        "conversation_id": (meta or {}).get("conversation_id") or conversation_id,
        "done": done,
        "error": err,
        "row_count": row_count,
        "events": events,
        "raw_text_tail": text[-2000:],
    }


def main():
    result = {"questions": QUESTIONS, "mcp": {}, "mulan": {}}
    result["mcp"] = mcp_baseline()
    s = login()
    conv = None
    for qid, question in QUESTIONS:
        r = call_mulan(s, question, conv)
        conv = r.get("conversation_id") or conv
        result["mulan"][qid] = r
        print(qid, "duration", round(r["duration"], 2), "rows", r["row_count"], "conv", conv, "error", bool(r.get("error")))
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
