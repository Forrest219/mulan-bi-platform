---
title: P3 · Embedding 召回能力设计
aliases:
  - P3 Embedding Spec
tags:
  - project/mulan-bi
  - type/design-spec
  - phase/v1-mvp
  - owner/llm
status: ready-for-implementation
created: 2026-04-15
spec_version: v0.1
target_executor: MiniMax-M2.7 / Sonnet
related:
  - "[[Mulan - 首页问数 TODO 协作清单]]"
  - "[[Mulan - T-R1 MCP Client 重写设计]]"
---

# P3 · Embedding 召回能力设计

> [!abstract] 目标
> 让 `services/llm/nlq_service.py` 的字段召回阶段能基于向量相似度,而非全表扫描。
> 路径:**MiniMax `embo-01` embedding + pgvector HNSW + `tableau_field_semantics.embedding` 列 + 回填脚本 + 召回服务**。

> [!warning] 交付前置条件
> 1. [[Mulan - T-R1 MCP Client 重写设计]] 已落地(保证下游 query 链路通)
> 2. Tableau 同步已跑过至少一次(`tableau_field_semantics` 里有数据)
> 3. MiniMax API Key 已配置到 `ai_llm_configs.api_key_encrypted`

---

## 1. 任务分解(每个独立可验证)

### T1 · 启用 pgvector 扩展
- [ ] **T1.1** · 检查 `docker-compose.yml` 的 postgres image,若是 `postgres:16` 改为 `pgvector/pgvector:pg16`
- [ ] **T1.2** · 重启容器:`docker-compose up -d postgres`
- [ ] **T1.3** · 验证扩展:
  ```bash
  docker-compose exec postgres psql -U mulan -d mulan_bi -c "CREATE EXTENSION IF NOT EXISTS vector; \dx vector"
  # 期望输出: 有一行 vector 扩展,version >= 0.5
  ```
- [ ] **T1.4** · 若要跑生产数据库,在生产 alembic 迁移里加 `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`

**自验证**:T1.3 命令必须返回 vector 扩展行。

---

### T2 · Alembic 迁移:`tableau_field_semantics.embedding`

新建迁移 `backend/alembic/versions/add_field_semantics_embedding.py`:

```python
"""add embedding column to tableau_field_semantics
Revision ID: <autogenerate>
Revises: <last head>
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "add_field_semantics_embedding"
down_revision = "<填入当前 head,跑 alembic current 获取>"

EMBEDDING_DIM = 1024  # ⚠️ MiniMax embo-01 维度,T3.2 discovery 后若不同要同步改

def upgrade():
    # 确保扩展存在(幂等)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "tableau_field_semantics",
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.add_column(
        "tableau_field_semantics",
        sa.Column("embedding_model", sa.String(64), nullable=True),
    )
    op.add_column(
        "tableau_field_semantics",
        sa.Column("embedding_generated_at", sa.DateTime, nullable=True),
    )

    op.execute(
        "CREATE INDEX ix_tfs_embedding_hnsw ON tableau_field_semantics "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200)"
    )

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_tfs_embedding_hnsw")
    op.drop_column("tableau_field_semantics", "embedding_generated_at")
    op.drop_column("tableau_field_semantics", "embedding_model")
    op.drop_column("tableau_field_semantics", "embedding")
```

**依赖**:`pip install pgvector` 加到 `backend/requirements.txt`(确认未加才加)。

**自验证**:
```bash
cd backend && alembic upgrade head
docker-compose exec postgres psql -U mulan -d mulan_bi -c \
  "\d tableau_field_semantics" | grep -E "embedding|vector"
# 期望看到: embedding | vector(1024)
```

---

### T3 · MiniMax Embedding 接入

#### T3.1 · 文档发现(LLM 执行者自己做)

官方中文文档地址(本 spec 写作时未全解):
> https://platform.minimaxi.com/document/Embeddings

执行以下命令验证:
```bash
# 用你配置里的 key 测一次
curl -sS https://api.minimaxi.com/v1/embeddings \
  -H "Authorization: Bearer <MINIMAX_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"embo-01","texts":["销售额","订单数量"],"type":"query"}'
```

期望响应含 `data[].embedding`(float 数组)或 `vectors[]`。**记录实际响应字段路径 + 维度数**,用于修改 T2 的 `EMBEDDING_DIM`。

> [!todo] 若 T3.1 实际维度不是 1024
> 停下来,同步修改 T2 的 `EMBEDDING_DIM` 再跑迁移。**不要**先跑迁移再改列类型。

#### T3.2 · 在 `services/llm/service.py` 新增 `generate_embedding_minimax` 方法

放在现有 `generate_embedding` 旁边(**不要删除原方法,做向后兼容**):

```python
async def generate_embedding_minimax(
    self,
    texts: list[str],
    model: str = "embo-01",
    type: str = "db",   # 入库用 "db",查询用 "query"(文档确认)
    timeout: int = 30,
) -> dict:
    """
    批量生成 embedding(MiniMax embo-01)。
    Returns: { "embeddings": List[List[float]], "model": str } or { "error": str }
    注:本方法独立于全局 provider 配置,固定走 MiniMax OpenAI 兼容 /v1/embeddings
    """
    config = self._load_config()
    if not config or not config.is_active or not config.api_key_encrypted:
        return {"error": "LLM 未配置,请联系管理员"}
    try:
        api_key = _decrypt(config.api_key_encrypted)
    except Exception as e:
        logger.error("解密失败: %s", e)
        return {"error": "LLM 认证配置错误"}

    import httpx
    url = "https://api.minimaxi.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "texts": texts, "type": type}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        # T3.1 discovery 后填入真实字段路径;以下按 OpenAI 兼容假设
        embeddings = [item["embedding"] for item in body.get("data", [])]
        if not embeddings:
            # 兜底:检查是否为 {"vectors":[...]} 格式
            embeddings = body.get("vectors", [])
        if not embeddings:
            return {"error": f"MiniMax embedding 响应异常: {body}"}
        return {"embeddings": embeddings, "model": model}
    except httpx.HTTPStatusError as e:
        logger.error("MiniMax embedding HTTP %s: %s", e.response.status_code, e.response.text)
        return {"error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error("MiniMax embedding 失败: %s", e)
        return {"error": str(e)}
```

#### T3.3 · 修复原 `generate_embedding` 的 bug

现 `service.py:467` 复用了全局 config 的 `base_url`(MiniMax Anthropic 端点),调 `/embeddings` 会 404。

**处理策略**:将其改为内部调用 `generate_embedding_minimax` 并转发单条:
```python
async def generate_embedding(self, text: str, model: str = "embo-01", timeout: int = 15) -> dict:
    """向后兼容:单条 embedding,内部转发到 MiniMax 批量接口"""
    result = await self.generate_embedding_minimax([text], model=model, type="query", timeout=timeout)
    if "error" in result:
        return result
    return {"embedding": result["embeddings"][0]}
```

#### T3.4 · 自验证

单元测试 `tests/services/llm/test_embedding.py`:
```python
async def test_minimax_embedding_shape(mock_http):
    mock_http.post("https://api.minimaxi.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data":[{"embedding":[0.1]*1024}]})
    )
    result = await llm_service.generate_embedding_minimax(["test"])
    assert "embeddings" in result
    assert len(result["embeddings"][0]) == 1024

async def test_embedding_compat_wrapper():
    # 新旧接口行为一致
    r = await llm_service.generate_embedding("销售额")
    assert "embedding" in r and len(r["embedding"]) == 1024
```

---

### T4 · 回填脚本 `scripts/build_semantic_embeddings.py`

```python
"""
回填 tableau_field_semantics.embedding

幂等:WHERE embedding IS NULL
批量:每次 32 条 texts 发一次 MiniMax
限速:默认 2 req/s(可配置)
可恢复:失败写日志,下次重跑跳过已填
"""
import asyncio
import argparse
import logging
import time
from sqlalchemy import text
from app.core.database import SessionLocal
from services.llm.service import llm_service

BATCH_SIZE = 32
RATE_LIMIT_SECONDS = 0.5  # 2 req/s


def build_text(row) -> str:
    """字段语义拼装:优先 zh > metric_definition > dimension_definition > tags"""
    parts = [
        row.semantic_name_zh or row.semantic_name or "",
        row.metric_definition or row.dimension_definition or "",
        " ".join((row.tags_json or [])) if row.tags_json else "",
    ]
    return " · ".join([p for p in parts if p])[:512]  # 截断防过长


async def run(datasource_id: int | None, dry_run: bool):
    db = SessionLocal()
    where = "embedding IS NULL"
    params = {}
    if datasource_id:
        where += " AND datasource_id = :dsid"
        params["dsid"] = datasource_id

    rows = db.execute(text(
        f"SELECT id, semantic_name, semantic_name_zh, metric_definition, "
        f"dimension_definition, tags_json FROM tableau_field_semantics WHERE {where}"
    ), params).fetchall()

    logging.info("待回填 %d 条", len(rows))
    if dry_run:
        for r in rows[:5]:
            print(r.id, build_text(r))
        return

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i+BATCH_SIZE]
        texts = [build_text(r) for r in batch]
        result = await llm_service.generate_embedding_minimax(texts, type="db")
        if "error" in result:
            logging.error("batch %d 失败: %s", i, result["error"])
            continue
        for r, emb in zip(batch, result["embeddings"]):
            db.execute(text(
                "UPDATE tableau_field_semantics SET embedding = :emb, "
                "embedding_model = 'embo-01', embedding_generated_at = NOW() WHERE id = :id"
            ), {"emb": emb, "id": r.id})
        db.commit()
        logging.info("已填 %d/%d", i+len(batch), len(rows))
        time.sleep(RATE_LIMIT_SECONDS)

    db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--datasource-id", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.datasource_id, args.dry_run))
```

**自验证**:
```bash
# 先 dry-run 看前 5 条拼装文本
cd backend && python -m scripts.build_semantic_embeddings --dry-run

# 正式跑
cd backend && python -m scripts.build_semantic_embeddings

# 核对覆盖率(期望 100% 或接近)
docker-compose exec postgres psql -U mulan -d mulan_bi -c \
  "SELECT COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS filled, COUNT(*) AS total FROM tableau_field_semantics"
```

---

### T5 · 召回服务 `services/llm/semantic_retriever.py`

```python
"""
基于 embedding 的字段召回(PRD §14 §3.1)
"""
from typing import List, Dict
from sqlalchemy import text
from app.core.database import SessionLocal
from services.llm.service import llm_service

DEFAULT_TOP_K = 10
MAX_CONTEXT_FIELDS = 10


async def recall_fields(
    question: str,
    datasource_ids: List[int] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict]:
    """
    对 question 做 embedding → cosine Top-K 召回字段语义。
    Returns: [{field_id, datasource_id, semantic_name_zh, ..., similarity}, ...]
    """
    emb_result = await llm_service.generate_embedding("query: " + question)
    if "error" in emb_result:
        raise RuntimeError(f"embedding 失败: {emb_result['error']}")
    query_vec = emb_result["embedding"]

    where_ds = ""
    params = {"query_vec": query_vec, "top_k": top_k}
    if datasource_ids:
        where_ds = "AND datasource_id = ANY(:dsids)"
        params["dsids"] = datasource_ids

    sql = f"""
      SELECT id, datasource_id, semantic_name, semantic_name_zh,
             metric_definition, dimension_definition, unit,
             1 - (embedding <=> :query_vec) AS similarity
      FROM tableau_field_semantics
      WHERE embedding IS NOT NULL {where_ds}
      ORDER BY embedding <=> :query_vec
      LIMIT :top_k
    """
    db = SessionLocal()
    try:
        rows = db.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()
```

**自验证**:
```python
# tests/services/llm/test_retriever.py
async def test_recall_returns_top_k(seeded_db):
    results = await recall_fields("销售额", top_k=5)
    assert 0 < len(results) <= 5
    assert all(0 <= r["similarity"] <= 1 for r in results)
    # 第 1 个必须是"销售额"相关的字段
    assert "销售" in results[0]["semantic_name_zh"]
```

---

### T6 · 集成到 NLQ 编排

**不改 `nlq_service.py` 的对外接口**。改内部:找到现有拼装 field context 的位置,把"全表拉字段"换成"调 `recall_fields`"。

具体需要执行者先读 `services/llm/nlq_service.py` 里 `resolve_fields` / `_build_fields_with_types` 相关段落,确定替换点。**若发现改动会污染超过 30 行代码,停下来上报**——可能需要 Forrest 另外给 refactor spec。

**自验证**:现有 `search.py` E2E 调 `/api/search/query` 成功返回结果,且 Prompt 里字段数 ≤ 10。

---

## 2. 总体 DoD(MiniMax 自查清单)

- [ ] `docker-compose exec postgres psql -c "SELECT 1 FROM pg_extension WHERE extname='vector'"` 返回 1 行
- [ ] `alembic current` 指向 `add_field_semantics_embedding`
- [ ] `tableau_field_semantics.embedding` 列类型为 `vector(N)`,N 与 MiniMax 实测维度一致
- [ ] `scripts/build_semantic_embeddings.py --dry-run` 输出前 5 条拼装文本(人工肉眼检查合理)
- [ ] 正式回填后 `embedding IS NOT NULL` 的行数 ≥ 总行数 × 95%
- [ ] `pytest tests/services/llm/test_embedding.py tests/services/llm/test_retriever.py` 全绿
- [ ] `/api/search/query` 打一条真实问题(如 "Q1 销售额"),Prompt 里的字段数 ≤ 10 条,能看到相似度 > 0.6 的字段
- [ ] `ruff check backend/services/llm/ backend/scripts/build_semantic_embeddings.py` 零告警
- [ ] 不引入 OpenAI SDK 依赖

---

## 3. 碰到下列情况停下来先问 Forrest

| 情况 | 为什么要停 |
|---|---|
| MiniMax embo-01 实际维度 ≠ 1024 | 迁移列类型要调整 |
| MiniMax 响应格式不符合 OpenAI `data[].embedding` 约定 | 解析逻辑要重写 |
| 回填命中 MiniMax 限流(429 频繁) | 需调整 `RATE_LIMIT_SECONDS` 或批量大小 |
| `tableau_field_semantics` 没有 `tags_json` / `metric_definition` 等字段 | 表结构与 spec 假设不符 |
| `nlq_service.py` 现有字段组装超过 30 行需要改 | 可能破坏上游契约 |
| pgvector 扩展在生产环境无法启用 | 需要备用方案(如 ivfflat 或外部向量库) |

---

## 4. 成本与性能预估

| 项 | 预估 |
|---|---|
| MiniMax embo-01 单价 | ~¥0.0005 / 1K tokens(以实际计费为准) |
| MVP 字段总数 | 假设 < 2000 |
| 回填总 tokens | ~100K(每字段 ~50 tokens) |
| 回填总成本 | < ¥0.5 |
| 回填耗时 | ~10 分钟(限速 2 req/s) |
| HNSW Top-10 召回延迟 | < 20ms(2000 行规模) |

---

> [!success] 交付完成的标志
> Forrest 在前端 AskBar 输入"Q1 销售额是多少",后端日志里能看到:
> 1. Embedding 调用成功(单次,<300ms)
> 2. 召回返回 Top-10 字段(与"销售"/"金额"强相关)
> 3. 下游 LLM 收到 ≤ 3000 tokens 的字段上下文
> 4. `/api/search/query` 200 OK,返回数值卡片
