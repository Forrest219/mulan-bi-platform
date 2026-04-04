"""知识库错误码（PRD §8）"""
from enum import Enum


class KBErrorCode(Enum):
    TERM_NOT_FOUND = "KB_001"
    TERM_DUPLICATE = "KB_002"
    TERM_MISSING_FIELD = "KB_003"
    DOC_NOT_FOUND = "KB_004"
    DOC_EMPTY_CONTENT = "KB_005"
    DOC_UNSUPPORTED_FORMAT = "KB_006"
    EMBEDDING_FAILED = "KB_007"
    VECTOR_SEARCH_UNAVAILABLE = "KB_008"
    SEARCH_QUERY_EMPTY = "KB_009"
    UNSUPPORTED_SOURCE_TYPE = "KB_010"


KB_ERROR_MESSAGES = {
    KBErrorCode.TERM_NOT_FOUND: "术语不存在",
    KBErrorCode.TERM_DUPLICATE: "标准术语已存在",
    KBErrorCode.TERM_MISSING_FIELD: "术语定义不能为空",
    KBErrorCode.DOC_NOT_FOUND: "文档不存在",
    KBErrorCode.DOC_EMPTY_CONTENT: "文档内容不能为空",
    KBErrorCode.DOC_UNSUPPORTED_FORMAT: "不支持的文档格式: {format}",
    KBErrorCode.EMBEDDING_FAILED: "Embedding 生成失败",
    KBErrorCode.VECTOR_SEARCH_UNAVAILABLE: "向量检索服务不可用",
    KBErrorCode.SEARCH_QUERY_EMPTY: "搜索内容不能为空",
    KBErrorCode.UNSUPPORTED_SOURCE_TYPE: "不支持的知识来源类型: {type}",
}


def kb_error_response(code: KBErrorCode, status_code: int, **kwargs) -> dict:
    """构造知识库错误响应"""
    message = KB_ERROR_MESSAGES[code].format(**kwargs)
    return {
        "error_code": code.value,
        "message": message,
    }
