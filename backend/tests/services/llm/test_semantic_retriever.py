"""
单元测试：services/llm/semantic_retriever.py（P3 T5）

覆盖：
- recall_fields 返回 top_k 条记录
- similarity 在 [0, 1] 范围内
- 无 embedding 时优雅降级（抛异常）
"""
from unittest import mock

import pytest


class MockRow:
    """Mock SQLAlchemy Row with _mapping support."""
    def __init__(self, data):
        object.__setattr__(self, "_mapping", data)

    def __getitem__(self, key):
        return self._mapping[key]


class TestSemanticRetriever:
    """test_recall_returns_top_k"""

    @pytest.mark.asyncio
    async def test_recall_returns_top_k(self):
        """recall_fields 返回相似度排序的 top_k 字段"""
        from services.llm.semantic_retriever import recall_fields

        async def mock_generate_embedding(question):
            return {"embedding": [0.1] * 1024}

        mock_rows = [
            MockRow({"id": 1, "datasource_id": 1, "semantic_name": "sales", "semantic_name_zh": "销售额",
             "metric_definition": None, "dimension_definition": None, "unit": "元", "similarity": 0.95}),
            MockRow({"id": 2, "datasource_id": 1, "semantic_name": "orders", "semantic_name_zh": "订单数",
             "metric_definition": None, "dimension_definition": None, "unit": "个", "similarity": 0.88}),
        ]

        with mock.patch(
            "services.llm.semantic_retriever.llm_service.generate_embedding",
            side_effect=mock_generate_embedding,
        ):
            with mock.patch(
                "services.llm.semantic_retriever.SessionLocal"
            ) as MockSessionLocal:
                mock_db = mock.Mock()
                mock_db.execute.return_value.fetchall.return_value = mock_rows
                mock_db.close = mock.Mock()
                MockSessionLocal.return_value = mock_db

                results = await recall_fields("销售额是多少", top_k=5)

        assert len(results) == 2
        assert results[0]["similarity"] == 0.95
        assert results[1]["similarity"] == 0.88
        assert all(0 <= r["similarity"] <= 1 for r in results)

    @pytest.mark.asyncio
    async def test_recall_embedding_failure_raises(self):
        """embedding 失败时抛出 RuntimeError"""
        from services.llm.semantic_retriever import recall_fields

        async def mock_generate_embedding(question):
            return {"error": "API unavailable"}

        with mock.patch(
            "services.llm.semantic_retriever.llm_service.generate_embedding",
            side_effect=mock_generate_embedding,
        ):
            with pytest.raises(RuntimeError, match="embedding 失败"):
                await recall_fields("销售额")

    @pytest.mark.asyncio
    async def test_recall_with_datasource_ids_filter(self):
        """recall_fields 支持 datasource_ids 过滤"""
        from services.llm.semantic_retriever import recall_fields

        async def mock_generate_embedding(question):
            return {"embedding": [0.1] * 1024}

        with mock.patch(
            "services.llm.semantic_retriever.llm_service.generate_embedding",
            side_effect=mock_generate_embedding,
        ):
            with mock.patch(
                "services.llm.semantic_retriever.SessionLocal"
            ) as MockSessionLocal:
                mock_db = mock.Mock()
                mock_db.execute.return_value.fetchall.return_value = []
                mock_db.close = mock.Mock()
                MockSessionLocal.return_value = mock_db

                await recall_fields("test", datasource_ids=[1, 2], top_k=10)

                # Verify SQL contains datasource filter
                call_args = mock_db.execute.call_args
                params = call_args[0][1]
                assert "dsids" in params
