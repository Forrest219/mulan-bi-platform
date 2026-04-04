"""术语服务（知识库 §3）"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from .models import KbGlossary, KbGlossaryDatabase


class GlossaryService:
    """业务术语服务 — 精确匹配 + 模糊搜索"""

    def __init__(self):
        self._db = KbGlossaryDatabase()

    def match_terms(self, db: Session, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        术语精确匹配（PRD §3.1）：
        - 优先匹配 term / canonical_term / synonyms（状态=active）
        - 按 glossary id 降序返回
        """
        results = self._db.match_by_term(db, query)
        return results[:limit]

    def search_terms(
        self, db: Session, keyword: str, category: str = None,
        page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """
        术语模糊搜索（PRD §3.2）：
        - keyword 模糊匹配 term / canonical_term / synonyms
        - category 精确筛选
        """
        return self._db.list(
            db, page=page, page_size=page_size,
            category=category, status="active", keyword=keyword
        )

    def get_term(self, db: Session, glossary_id: int) -> Optional[Dict[str, Any]]:
        """获取单个术语详情"""
        g = self._db.get(db, glossary_id)
        return g.to_dict() if g else None

    def create_term(
        self, db: Session, term: str, canonical_term: str, definition: str,
        category: str = "concept", synonyms: List[str] = None,
        formula: str = None, related_fields: List[str] = None,
        source: str = "manual", created_by: int = None
    ) -> KbGlossary:
        """创建术语"""
        return self._db.create(
            db, term=term, canonical_term=canonical_term, definition=definition,
            category=category, synonyms=synonyms, formula=formula,
            related_fields=related_fields, source=source, created_by=created_by,
        )

    def update_term(self, db: Session, glossary_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """更新术语"""
        g = self._db.update(db, glossary_id, **kwargs)
        return g.to_dict() if g else None

    def deprecate_term(self, db: Session, glossary_id: int) -> bool:
        """软删除（标记为 deprecated）"""
        return self._db.soft_delete(db, glossary_id)


glossary_service = GlossaryService()
