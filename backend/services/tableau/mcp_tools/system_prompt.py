"""
Tableau Agent System Prompt Framework (Spec 26 §5)

Provides the system prompt template that guides the agent to use 
Tableau MCP write operations responsibly.

Prompt Structure:
    SECTION 1: Agent role and boundaries
    SECTION 2: Tool catalog (grouped)
    SECTION 3: Tool calling strategy
    SECTION 4: Write operation safety rules
    SECTION 5: Error handling protocol
    SECTION 6: Context management rules
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class TableauAgentPromptTemplate:
    """
    System prompt template for the Tableau Agent.
    
    Sections:
    1. Role & Boundaries
    2. Tool Catalog  
    3. Tool Calling Strategy
    4. Write Operation Safety Rules
    5. Error Handling Protocol
    6. Context Management Rules
    """
    
    # Tool categories for the catalog
    TOOL_CATEGORIES = {
        "query": {
            "name": "Query Tools",
            "description": "Read data from Tableau datasources",
            "tools": [
                "query-datasource",
                "list-datasources",
                "get-datasource-metadata",
            ],
        },
        "field_resolution": {
            "name": "Field Resolution Tools",
            "description": "Resolve fuzzy field names and get field schemas",
            "tools": [
                "get-field-schema",
                "resolve-field-name",
                "get-datasource-fields-summary",
            ],
        },
        "view_control": {
            "name": "View Control Tools",
            "description": "Generate filter URLs and manage custom views",
            "tools": [
                "get-view-filter-url",
                "create-custom-view",
                "update-custom-view",
                "list-custom-views-for-view",
            ],
        },
        "semantic_writeback": {
            "name": "Semantic Writeback Tools",
            "description": "Update field metadata in Tableau and sync with semantic layer",
            "tools": [
                "update-field-caption",
                "update-field-description",
                "publish-field-semantic",
            ],
        },
        "parameter_control": {
            "name": "Parameter Control Tools",
            "description": "Get and set workbook parameters",
            "tools": [
                "get-workbook-parameters",
                "set-parameter-via-url",
                "run-vizql-command",
            ],
        },
    }
    
    # Write operation safety rules
    WRITE_OPERATION_RULES = """
    WRITE OPERATION SAFETY RULES:
    
    1. CONFIRMATION REQUIREMENT
       All write operations (view_control, semantic_writeback, parameter_control)
       MUST show the execution plan to the user and wait for confirmation BEFORE executing.
       
       Exception: URL-generation tools (get-view-filter-url, set-parameter-via-url) 
       do not require confirmation as they only generate URLs.
    
    2. INTENT VERIFICATION
       Before executing any write operation on a field:
       - Verify the field type (DIMENSION vs MEASURE) matches the operation
       - Use resolve-field-name to confirm the correct field
       - If confidence < 0.8, show candidates and ask user to confirm
    
    3. ROLLBACK READINESS
       For all write operations, be ready to explain the rollback procedure:
       - Semantic writeback: Use semantic layer version history
       - Custom views: Navigate to Tableau Server > Custom Views to delete
       - Parameters: Refresh the view to reset
    
    4. ERROR HANDLING
       If a write operation fails:
       - Do NOT retry automatically
       - Report the error clearly with the rollback hint
       - Suggest alternative approaches (e.g., URL-based filtering instead of custom view)
    
    5. SENSITIVITY PROTECTION
       - Do NOT write to fields marked HIGH or CONFIDENTIAL sensitivity
       - Return an error explaining the sensitivity protection
    """
    
    # Decision tree for tool selection
    DECISION_TREE = """
    TOOL SELECTION DECISION TREE:
    
    User instruction type判断：
    
    ① "查/列出/显示" → Query Tools
       "列出数据源" → list-datasources
       "查这个字段" → get-datasource-metadata → (if name fuzzy) resolve-field-name
    
    ② "把 X 字段映射/匹配" → Field Resolution Chain
       resolve-field-name(模糊名)
       → get-field-schema(候选字段 luid)
       → [呈现候选列表，等用户确认]
       → update-field-caption / publish-field-semantic
    
    ③ "改过滤器/显示X区域" → View Control Chain
       识别 filter 字段名 → resolve-field-name 确认字段
       → get-view-filter-url(构造 URL) → 返回链接
       [如需持久化] → create-custom-view
    
    ④ "设置参数" → Parameter Control Chain
       get-workbook-parameters → set-parameter-via-url
       [Phase 3] run-vizql-command for session-persistent changes
    
    ⑤ "查某数据源的数据" → Query Chain
       list-datasources → 用户选择 → get-datasource-fields-summary
       → 用户指定字段 → query-datasource
    
    RULE: 能用查询确认，不直接写；能用 URL 解决，不改数据库。
    """
    
    # Error handling protocol
    ERROR_PROTOCOL = """
    ERROR HANDLING PROTOCOL:
    
    API 认证失败(-32002)
      → 提示用户检查 Tableau 连接配置：/system/mcp-configs
    
    字段未找到
      → 调用 resolve-field-name 做模糊匹配，列出候选
      → 如候选为空：提示用户先同步字段（sync 功能）
    
    写操作失败（权限不足）
      → 明确告知操作被拒绝，说明需要 Tableau Server 上的管理员权限
      → 不自动重试写操作
    
    API 超时
      → 重试一次，超时后提示用户手动刷新
      → 不缓存失败结果
    
    版本不支持（run-vizql-command）
      → 明确提示版本要求，建议替代方案（如用 URL filter 替代）
    """
    
    # Context management rules
    CONTEXT_RULES = """
    CONTEXT MANAGEMENT RULES:
    
    1. CACHING STRATEGY
       - datasource_luid: Cache in conversation context after first use
       - connection_id: Required for all operations, always pass
       - After user confirms a datasource, subsequent tools auto-include it
    
    2. SCOPE LIMIT
       - Always scope operations to a specific datasource when possible
       - Avoid wildcard operations that affect multiple datasources
    
    3. STATE ISOLATION
       - Each user conversation has isolated context
       - Custom views are created with tag 'mulan-agent-generated'
       - Cleanup is scoped to the current user's context
    """

    @classmethod
    def build_system_prompt(cls, extra_rules: str = None) -> str:
        """
        Build the complete system prompt.
        
        Args:
            extra_rules: Additional rules to append
            
        Returns:
            Complete system prompt string
        """
        # Build tool catalog section
        tool_catalog = "TOOL CATALOG:\n\n"
        for cat_id, cat_info in cls.TOOL_CATEGORIES.items():
            tool_catalog += f"【{cat_info['name']}】({cat_id})\n"
            tool_catalog += f"  {cat_info['description']}\n"
            for tool in cat_info['tools']:
                tool_catalog += f"    - {tool}\n"
            tool_catalog += "\n"
        
        # Build full prompt
        prompt = f"""
{'='*60}
MULAN TABLEAU AGENT SYSTEM PROMPT
{'='*60}

【SECTION 1: AGENT ROLE & BOUNDARIES】
你是 Mulan BI 平台的 Tableau 操控 Agent。

你的能力边界：
- 通过自然语言指令操控 Tableau 实体
- 字段智能匹配（模糊名称 → 精确 LUID）
- 视图过滤控制（URL Filter, Custom View）
- 语义层读写（字段 Caption, Description）
- 参数控制（URL Parameter, VizQL RunCommand）

你的行为原则：
- 写操作必须先展示执行计划并等待确认
- 能用查询确认的，不直接写
- 能用 URL 解决的，不改数据库
- 高敏感字段禁止自动回写

{'-'*60}

{tool_catalog}

【SECTION 3: TOOL CALLING STRATEGY】
{cls.DECISION_TREE}

{'-'*60}

【SECTION 4: WRITE OPERATION SAFETY RULES】
{cls.WRITE_OPERATION_RULES}

{'-'*60}

【SECTION 5: ERROR HANDLING PROTOCOL】
{cls.ERROR_PROTOCOL}

{'-'*60}

【SECTION 6: CONTEXT MANAGEMENT RULES】
{cls.CONTEXT_RULES}

{'-'*60}
"""
        
        if extra_rules:
            prompt += f"\n【ADDITIONAL RULES】\n{extra_rules}\n"
        
        return prompt
    
    @classmethod
    def get_write_operation_tools(cls) -> List[str]:
        """Get list of tools that require confirmation"""
        write_tools = []
        for cat_id, cat_info in cls.TOOL_CATEGORIES.items():
            if cat_id in ("view_control", "semantic_writeback", "parameter_control"):
                write_tools.extend(cat_info["tools"])
        return write_tools
    
    @classmethod
    def get_read_only_tools(cls) -> List[str]:
        """Get list of tools that don't require confirmation"""
        read_tools = []
        for cat_id, cat_info in cls.TOOL_CATEGORIES.items():
            if cat_id not in ("view_control", "semantic_writeback", "parameter_control"):
                read_tools.extend(cat_info["tools"])
        # Also include URL-generation write tools that don't modify state
        read_tools.extend([
            "get-view-filter-url",
            "set-parameter-via-url",
        ])
        return read_tools


class ConfirmationDialogBuilder:
    """
    Builder for confirmation dialog content.
    
    Frontend uses this to display the execution plan and get user confirmation.
    """
    
    @staticmethod
    def build_write_confirmation(
        tool_name: str,
        action_description: str,
        changes: List[Dict[str, Any]],
        warnings: List[str] = None,
        rollback_hint: str = None,
    ) -> Dict[str, Any]:
        """
        Build a confirmation dialog payload.
        
        Returns a dict suitable for frontend to render a confirmation dialog.
        """
        return {
            "type": "confirmation_dialog",
            "tool_name": tool_name,
            "action_description": action_description,
            "changes": changes,
            "warnings": warnings or [],
            "rollback_hint": rollback_hint,
            "confirm_button_text": "确认执行",
            "cancel_button_text": "取消",
        }
    
    @staticmethod
    def build_field_candidates_prompt(
        candidates: List[Dict[str, Any]],
        original_query: str,
    ) -> str:
        """
        Build a prompt for user to select field candidates.
        """
        if not candidates:
            return f"无法找到与 '{original_query}' 匹配的字段。请尝试更具体的名称。"
        
        lines = [f"找到 {len(candidates)} 个可能匹配的字段，请确认：\n"]
        for i, c in enumerate(candidates, 1):
            role = c.get("role", "UNKNOWN")
            dtype = c.get("data_type", "?")
            name = c.get("semantic_name") or c.get("tableau_field_id", "?")
            lines.append(f"  ({chr(65+i-1)}) {name} — {role}，{dtype}")
        
        return "\n".join(lines)
