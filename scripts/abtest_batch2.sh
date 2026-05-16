#!/bin/bash
# Batch 2 A/B Test Runner
# Output: JSONL with each line = {"q":"Q#","mcp_duration_ms":N,"mulan_duration_ms":N,"mcp_answer":"...","mulan_answer":"...","mcp_rowcount":N,"mulan_rowcount":N,"mcp_intent":"...","mulan_intent":"...","status":"Pass|Fail"}

COOKIES="/tmp/mulan_cookies.txt"
API="http://localhost:8000/api/search/query"

mulan_query() {
  local q="$1"
  START=$(python3 -c "import time; print(int(time.time()*1000))")
  RESP=$(curl -s -b "$COOKIES" -X POST "$API" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'question':'$q'}))" 2>/dev/null || echo '{\"question\":\"error\"}')" )
  END=$(python3 -c "import time; print(int(time.time()*1000))")
  DUR=$((END - START))
  echo "$RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
intent=d.get('intent')
meta=d.get('meta')
answer=d.get('answer') or d.get('content') or ''
print(json.dumps({'intent':intent,'meta':meta,'answer':answer[:500],'duration_ms':$DUR}))
" 2>/dev/null
}

# Q0
echo "Testing Q0..."
mulan_query "介绍数据源订单+(示例-超市)"
echo "Testing Q1..."
mulan_query "整体的销售额、利润、利润率、客户数、客单价是什么样子"
echo "Testing Q2..."
mulan_query "这个指标过去几年的趋势是什么样子"
echo "Testing Q3..."
mulan_query "统计一下每个子类别的销售额、利润和利润率"
echo "Testing Q4..."
mulan_query "继续拆分到每个年份"
echo "Testing Q5..."
mulan_query "2025年没有销售记录的子类别有哪些"
echo "Testing Q6..."
mulan_query "Top10大客户是谁请列出客户名称和销售金额及占比"
echo "Testing Q7..."
mulan_query "邓保这个客户的合作记录是什么样最近还有合作吗"
echo "Testing Q8..."
mulan_query "哪个子类别的利润每年都在持续增长"
echo "Testing Q9..."
mulan_query "我计划关闭一些区域止损哪些省份一致没挣到钱利润是亏的"
echo "Testing Q10..."
mulan_query "为什么辽宁福建在2024年出现了巨亏请看看是什么产品线和客户导致的"