"""知识库服务模块（PRD §2-§6）"""
from .models import (
    KbGlossary, KbSchema, KbDocument, KbEmbedding,
    KbGlossaryDatabase, KbDocumentDatabase, KbEmbeddingDatabase,
)
from .glossary_service import glossary_service, GlossaryService
from .document_service import document_service, DocumentService
from .embedding_service import embedding_service, EmbeddingService
from .rag_service import rag_service, RAGService

__all__ = [
    # Models
    "KbGlossary", "KbSchema", "KbDocument", "KbEmbedding",
    "KbGlossaryDatabase", "KbDocumentDatabase", "KbEmbeddingDatabase",
    # Services
    "GlossaryService", "DocumentService", "EmbeddingService", "RAGService",
    "glossary_service", "document_service", "embedding_service", "rag_service",
]
