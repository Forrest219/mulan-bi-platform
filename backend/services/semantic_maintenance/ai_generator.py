"""
AI 语义生成服务（Spec 12 §5 — 独立模块）

从 service.py 抽取 AI 生成逻辑为独立模块，符合 Spec 12 §2.2 模块职责边界规范。

职责：
- pre_llm_sensitivity_check()：LLM 调用前置敏感度检查
- generate_ai_draft_field()：字段语义 AI 生成
- generate_ai_draft_datasource()：数据源语义 AI 生成
- JSON 解析 + 重试策略
- Schema 校验 + 置信度判定

不涉及：
- 直接操作数据库（由调用方保证）
- HTTP 请求/响应
- Web 框架依赖
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Tuple

from .sanitizer import BLOCKED_FOR_LLM, sanitize_fields_for_llm

logger = logging.getLogger(__name__)

# 置信度阈值（Spec 12 §6.1）
CONFIDENCE_HIGH = 0.7
CONFIDENCE_LOW = 0.3

# JSON 解析重试次数
MAX_JSON_RETRY = 1

# 字段语义输出 Schema（Spec 12 §5.2.1）
FIELD_OUTPUT_REQUIRED = [
    "semantic_name",
    "semantic_name_zh",
    "semantic_description",
    "semantic_type",
    "confidence",
]

# 数据源语义输出 Schema（Spec 12 §5.2.2）
DS_OUTPUT_REQUIRED = [
    "semantic_name_zh",
    "semantic_description",
    "confidence",
]


class AIGenerationError(Exception):
    """AI 生成错误基类"""

    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class SLIError(AIGenerationError):
    """Spec 12 错误码异常"""

    # 错误码映射
    CODES = {
        "SLI_001": "AI 服务未配置，请联系管理员",
        "SLI_002": "AI 服务调用失败：{error_detail}",
        "SLI_003": "AI 返回格式异常，无法解析为有效 JSON",
        "SLI_004": "AI 生成结果不完整，缺少：{missing_fields}",
        "SLI_005": "敏感级别为 {level} 的对象禁止 AI 处理",
        "SLI_006": "目标记录不存在（ID={id}）",
        "SLI_008": "字段元数据过多，无法在 Token 预算内组装有效上下文",
    }

    def __init__(self, code: str, message: str = None, details: dict = None):
        self.code = code
        self.message = message or self.CODES.get(code, "未知错误").format(**(details or {}))
        self.details = details or {}
        super().__init__(f"[{code}] {self.message}")


def pre_llm_sensitivity_check(
    sensitivity_level: str = None,
    is_datasource: bool = False,
) -> Optional[str]:
    """
    LLM 调用前置敏感度检查（Spec 12 §9.1 / SLI_005）。

    Args:
        sensitivity_level: 敏感级别（low/medium/high/confidential）
        is_datasource: 是否为数据源（影响错误消息）

    Returns:
        None 表示通过检查；返回错误消息字符串表示不通过。
    """
    if sensitivity_level is None:
        return None
    level = sensitivity_level.lower()
    if level in BLOCKED_FOR_LLM:
        obj_type = "数据源" if is_datasource else "字段"
        return f"SLI_005: 敏感级别为 {level} 的{obj_type}禁止 AI 处理"
    return None


def parse_json_from_response(content: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    解析 LLM 返回内容中的 JSON（Spec 12 §6.2）。

    支持 ``` 代码块包裹格式。

    Args:
        content: LLM 返回的原始文本

    Returns:
        (parsed_dict, error_message) 元组
        - 成功：parsed=字典, error=None
        - 失败：parsed=None, error=错误消息
    """
    content = content.strip()

    # 处理 ```json 代码块包裹
    if content.startswith("```"):
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", content)
        if match:
            content = match.group(1).strip()

    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败：{e}"


def validate_field_output(parsed: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    校验字段语义输出 Schema（Spec 12 §5.2.1）。

    Args:
        parsed: 解析后的字典

    Returns:
        (is_valid, missing_fields) 元组
    """
    missing = []
    for field in FIELD_OUTPUT_REQUIRED:
        if field not in parsed:
            missing.append(field)

    # 校验 semantic_type
    if "semantic_type" in parsed:
        valid_types = {"dimension", "measure", "time_dimension"}
        if parsed["semantic_type"] not in valid_types:
            missing.append(f"semantic_type（必须为 {valid_types} 之一）")

    # 校验 confidence 范围
    if "confidence" in parsed:
        conf = parsed["confidence"]
        if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
            missing.append("confidence（必须在 0.0~1.0 之间）")

    return len(missing) == 0, missing


def validate_datasource_output(parsed: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    校验数据源语义输出 Schema（Spec 12 §5.2.2）。

    Args:
        parsed: 解析后的字典

    Returns:
        (is_valid, missing_fields) 元组
    """
    missing = []
    for field in DS_OUTPUT_REQUIRED:
        if field not in parsed:
            missing.append(field)

    # 校验 confidence 范围
    if "confidence" in parsed:
        conf = parsed["confidence"]
        if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
            missing.append("confidence（必须在 0.0~1.0 之间）")

    return len(missing) == 0, missing


def determine_confidence_level(confidence: float) -> str:
    """
    判断置信度等级（Spec 12 §6.1）。

    Args:
        confidence: 置信度值（0.0~1.0）

    Returns:
        "high": 高置信度（>= 0.7）
        "medium": 中置信度（0.3 <= x < 0.7）
        "low": 低置信度（< 0.3）
    """
    if confidence >= CONFIDENCE_HIGH:
        return "high"
    elif confidence >= CONFIDENCE_LOW:
        return "medium"
    else:
        return "low"


def build_json_retry_prompt(
    original_prompt: str,
    error_message: str,
) -> str:
    """
    构建 JSON 重试 Prompt（Spec 12 §6.2）。

    Args:
        original_prompt: 原始 Prompt
        error_message: JSON 解析错误消息

    Returns:
        重试 Prompt 字符串
    """
    return (
        f"{original_prompt}\n\n"
        f"[修正要求] 你上次生成的格式有误，JSON 解析报错信息为：{error_message}。"
        f"请严格按照 JSON 规范重新生成，不要包含任何 Markdown 标记（如 ```json），只输出纯 JSON。"
    )


class AIGenerator:
    """
    AI 语义生成器。

    封装 LLM 调用、JSON 解析、Schema 校验、置信度判定等逻辑。

    使用方式：
        generator = AIGenerator(llm_service=llm_service)
        result = generator.generate_field_semantic(...)
    """

    def __init__(self, llm_service=None):
        """
        Args:
            llm_service: LLM 服务实例（必须提供 complete_for_semantic 方法）
                       如果为 None，则 generate_* 方法会返回错误
        """
        self.llm_service = llm_service

    def _check_llm_available(self) -> Optional[str]:
        """检查 LLM 服务是否可用"""
        if self.llm_service is None:
            return "LLM 服务未配置"
        return None

    async def generate_field_semantic(
        self,
        field_metadata: Dict[str, Any],
        user_id: int = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        AI 生成字段语义草稿（Spec 12 §5）。

        Args:
            field_metadata: 字段元数据，包含：
                - field_id: 字段记录 ID
                - field_name: 字段名
                - data_type: 数据类型
                - role: 角色（dimension/measure）
                - formula: 公式
                - enum_values: 枚举值列表
                - sensitivity_level: 敏感级别
                - existing_semantic_name: 现有英文语义名
                - existing_semantic_name_zh: 现有中文语义名

        Returns:
            (success, result_or_error) 元组
            - 成功：success=True, result=包含生成结果的字典
            - 失败：success=False, result=错误消息字符串
        """
        # 检查 LLM 可用性
        err = self._check_llm_available()
        if err:
            return False, err

        # 敏感度检查
        sensitivity_err = pre_llm_sensitivity_check(
            field_metadata.get("sensitivity_level"),
            is_datasource=False,
        )
        if sensitivity_err:
            return False, sensitivity_err

        # 构建 Prompt
        from services.llm.prompts import AI_SEMANTIC_FIELD_TEMPLATE

        field_name = field_metadata.get("field_name", "")
        data_type = field_metadata.get("data_type", "未知")
        role = field_metadata.get("role", "未知")
        formula = field_metadata.get("formula") or "无"
        existing_semantic_name = field_metadata.get("existing_semantic_name") or "无"
        existing_semantic_name_zh = field_metadata.get("existing_semantic_name_zh") or "无"

        # 枚举值截断
        enum_values = field_metadata.get("enum_values") or []
        enum_text = "\n".join([f"- {v}" for v in enum_values[:20]]) or "无"

        prompt = AI_SEMANTIC_FIELD_TEMPLATE.format(
            field_name=field_name,
            data_type=data_type,
            role=role,
            formula=formula,
            existing_semantic_name=existing_semantic_name,
            existing_semantic_name_zh=existing_semantic_name_zh,
            enum_values=enum_text,
        )
        system = "你是一个专业的 BI 字段语义专家。"

        # 调用 LLM
        try:
            result = await self.llm_service.complete_for_semantic(
                prompt, system=system, timeout=30
            )
        except Exception as e:
            return False, f"LLM 调用失败: {e}"

        if "error" in result:
            return False, result["error"]

        # JSON 解析 + 重试
        content = result["content"].strip()
        parsed, parse_err = parse_json_from_response(content)

        if parse_err and MAX_JSON_RETRY > 0:
            # 重试一次
            retry_prompt = build_json_retry_prompt(prompt, parse_err)
            try:
                result_retry = await self.llm_service.complete_for_semantic(
                    retry_prompt, system=system, timeout=30
                )
            except Exception as e:
                return False, f"LLM 重试失败: {e}"

            if "error" in result_retry:
                return False, result_retry["error"]

            parsed, parse_err = parse_json_from_response(result_retry["content"].strip())
            if parse_err:
                return False, "AI 返回格式异常（重试后仍非有效 JSON）"

        elif parse_err:
            return False, f"AI 返回格式异常: {parse_err}"

        # Schema 校验
        is_valid, missing = validate_field_output(parsed)
        if not is_valid:
            return False, f"AI 生成结果不完整，缺少：{', '.join(missing)}"

        # 置信度判定
        confidence = parsed.get("confidence", 0.0)
        confidence_level = determine_confidence_level(confidence)

        # 构建结果
        result_dict = {
            "semantic_name": parsed.get("semantic_name"),
            "semantic_name_zh": parsed.get("semantic_name_zh"),
            "semantic_definition": parsed.get("semantic_description"),
            "metric_definition": parsed.get("metric_definition"),
            "dimension_definition": parsed.get("dimension_definition"),
            "unit": parsed.get("unit"),
            "synonyms_json": parsed.get("synonyms_json"),
            "tags_json": parsed.get("tags_json"),
            "sensitivity_level": parsed.get("sensitivity_level"),
            "is_core_field": parsed.get("is_core_field", False),
            "ai_confidence": confidence,
            "confidence_level": confidence_level,
            "change_reason": "ai_generated",
        }

        return True, result_dict

    async def generate_datasource_semantic(
        self,
        ds_metadata: Dict[str, Any],
        field_context: List[Dict[str, Any]] = None,
        user_id: int = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        AI 生成数据源语义草稿（Spec 12 §5）。

        Args:
            ds_metadata: 数据源元数据，包含：
                - ds_id: 数据源记录 ID
                - ds_name: 数据源名称
                - description: 描述
                - existing_semantic_name: 现有英文语义名
                - existing_semantic_name_zh: 现有中文语义名
                - sensitivity_level: 敏感级别
            field_context: 字段上下文列表（可选）

        Returns:
            (success, result_or_error) 元组
        """
        # 检查 LLM 可用性
        err = self._check_llm_available()
        if err:
            return False, err

        # 敏感度检查
        sensitivity_err = pre_llm_sensitivity_check(
            ds_metadata.get("sensitivity_level"),
            is_datasource=True,
        )
        if sensitivity_err:
            return False, sensitivity_err

        # 构建 Prompt
        from services.llm.prompts import AI_SEMANTIC_DS_TEMPLATE
        from .context_assembler import ContextAssembler

        assembler = ContextAssembler()

        # 净化字段上下文
        sanitized_fields = assembler.sanitize_fields(field_context or [])
        field_context_text = assembler.build_field_context(sanitized_fields)

        ds_name = ds_metadata.get("ds_name", "")
        description = ds_metadata.get("description") or "无"
        existing_semantic_name = ds_metadata.get("existing_semantic_name") or "无"
        existing_semantic_name_zh = ds_metadata.get("existing_semantic_name_zh") or "无"

        prompt = AI_SEMANTIC_DS_TEMPLATE.format(
            ds_name=ds_name,
            description=description,
            existing_semantic_name=existing_semantic_name,
            existing_semantic_name_zh=existing_semantic_name_zh,
            field_context=field_context_text,
        )
        system = "你是一个专业的 BI 数据语义专家。"

        # 调用 LLM
        try:
            result = await self.llm_service.complete_for_semantic(
                prompt, system=system, timeout=30
            )
        except Exception as e:
            return False, f"LLM 调用失败: {e}"

        if "error" in result:
            return False, result["error"]

        # JSON 解析 + 重试
        content = result["content"].strip()
        parsed, parse_err = parse_json_from_response(content)

        if parse_err and MAX_JSON_RETRY > 0:
            retry_prompt = build_json_retry_prompt(prompt, parse_err)
            try:
                result_retry = await self.llm_service.complete_for_semantic(
                    retry_prompt, system=system, timeout=30
                )
            except Exception as e:
                return False, f"LLM 重试失败: {e}"

            if "error" in result_retry:
                return False, result_retry["error"]

            parsed, parse_err = parse_json_from_response(result_retry["content"].strip())
            if parse_err:
                return False, "AI 返回格式异常（重试后仍非有效 JSON）"

        elif parse_err:
            return False, f"AI 返回格式异常: {parse_err}"

        # Schema 校验
        is_valid, missing = validate_datasource_output(parsed)
        if not is_valid:
            return False, f"AI 生成结果不完整，缺少：{', '.join(missing)}"

        # 构建结果
        result_dict = {
            "semantic_name": parsed.get("semantic_name"),
            "semantic_name_zh": parsed.get("semantic_name_zh"),
            "semantic_description": parsed.get("semantic_description"),
            "business_definition": parsed.get("business_definition"),
            "owner": parsed.get("owner"),
            "sensitivity_level": parsed.get("sensitivity_level"),
            "tags_json": parsed.get("tags_json"),
            "ai_confidence": parsed.get("confidence", 0.0),
            "change_reason": "ai_generated",
        }

        return True, result_dict


# 同步封装函数（供 service.py 调用）
def generate_ai_draft_field_sync(
    field_metadata: Dict[str, Any],
    llm_service,
    user_id: int = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    generate_field_semantic 的同步封装。

    用于 service.py 中通过 asyncio.run() 调用异步方法。
    """
    generator = AIGenerator(llm_service=llm_service)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的 loop，同步调用
        return asyncio.run(generator.generate_field_semantic(field_metadata, user_id))

    # 有运行中的 loop，在线程池中执行
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            asyncio.run,
            generator.generate_field_semantic(field_metadata, user_id),
        )
        return future.result()


def generate_ai_draft_datasource_sync(
    ds_metadata: Dict[str, Any],
    llm_service,
    field_context: List[Dict[str, Any]] = None,
    user_id: int = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    generate_datasource_semantic 的同步封装。
    """
    generator = AIGenerator(llm_service=llm_service)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            generator.generate_datasource_semantic(ds_metadata, field_context, user_id)
        )

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            asyncio.run,
            generator.generate_datasource_semantic(ds_metadata, field_context, user_id),
        )
        return future.result()
