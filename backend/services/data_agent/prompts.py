"""Data Agent 系统提示词 — ReAct Engine 推理提示"""

from typing import List


def build_react_system_prompt(tool_descriptions: List[dict]) -> str:
    """构建 ReAct Engine 的 system prompt

    Args:
        tool_descriptions: 工具描述列表，每项包含 name, description, parameters_schema
    """
    tool_list_block = _build_tool_list_block(tool_descriptions)

    return f"""你是 Data Agent，一个智能数据分析助手。

## 你的能力

你通过 ReAct 循环（Think → Act → Observe）回答用户问题。
你可以调用内部工具来获取数据、分析信息。

## 可用工具

{tool_list_block}

## 输出格式

你必须返回 JSON 格式的决策结果：

```json
{{
  "action": "tool_call" | "final_answer",
  "tool_name": "工具名称（如 query）",
  "tool_params": {{ "参数名": "参数值" }},
  "reasoning": "你的推理过程（中文）",
  "answer": "最终回答（当 action=final_answer 时）"
}}
```

## 决策规则

1. 如果用户问题需要查询数据，使用工具。例如：销售额、指标数据、趋势分析
2. 如果用户问题是闲聊或问候，直接 final_answer
3. 如果需要多步推理，先 tool_call 收集信息，再 final_answer
4. 每次只选择一个工具调用

## 约束

- max_steps=10，超出则强制结束
- 单步超时 30s，总超时 120s
- 工具参数必须符合 parameters_schema
- 回答用中文
"""


def _build_tool_list_block(tool_descriptions: List[dict]) -> str:
    """将工具列表渲染为 markdown 格式"""
    if not tool_descriptions:
        return "（暂无注册工具）"

    lines = []
    for tool in tool_descriptions:
        lines.append(f"### {tool['name']}")
        lines.append(f"{tool['description']}")
        if tool.get("parameters_schema"):
            params = tool["parameters_schema"]
            if isinstance(params, dict) and "properties" in params:
                lines.append("参数：")
                for pname, pschema in params["properties"].items():
                    ptype = pschema.get("type", "any")
                    pdesc = pschema.get("description", "")
                    required = params.get("required", [])
                    req_mark = "（必填）" if pname in required else "（可选）"
                    lines.append(f"  - {pname}: {ptype} {req_mark} {pdesc}")
        lines.append("")

    return "\n".join(lines)


# 默认提示词（无工具时）
DEFAULT_SYSTEM_PROMPT = build_react_system_prompt([])