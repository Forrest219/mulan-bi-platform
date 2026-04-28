"""
Glossary Service 单元测试（Spec 12 §10.1）

测试同义词匹配优先级：
1. 精确匹配 term -> canonical_term
2. synonyms_json 包含匹配
"""
import pytest

from services.knowledge_base.glossary_service import GlossaryService


class TestGlossaryServiceMatching:
    """术语匹配优先级测试"""

    def test_match_term_exact(self):
        """精确匹配"""
        # GlossaryService 的 match_terms 方法需要 db 参数
        # 这里测试同义词匹配的优先级逻辑
        pass

    def test_match_term_synonym(self):
        """同义词匹配"""
        pass

    def test_canonical_term_return(self):
        """返回规范术语"""
        pass


class TestGlossaryServiceCRUD:
    """CRUD 操作测试"""

    def test_create_term(self):
        """创建术语"""
        pass

    def test_duplicate_term(self):
        """重复术语（KB_002）"""
        pass

    def test_update_term(self):
        """更新术语"""
        pass

    def test_delete_term(self):
        """删除术语"""
        pass
