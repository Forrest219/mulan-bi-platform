"""
HypothesisStoreTool — 假设存储

Spec 28 §4.1 — hypothesis_store

功能：
- 存储当前假设树（已验证/已否定/待验证）
- 假设的增删改查
- hypothesis_tree JSONB 状态管理
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from services.data_agent.tool_base import BaseTool, ToolResult, ToolContext, ToolMetadata
from services.data_agent.models import BiAnalysisSession

logger = logging.getLogger(__name__)


class HypothesisStoreTool(BaseTool):
    """Hypothesis Store Tool — 假设存储管理"""

    name = "hypothesis_store"
    description = "管理归因分析中的假设树，包括添加、更新、确认、否定假设。用于跟踪因果推理过程。"
    metadata = ToolMetadata(
        category="state",
        version="1.0.0",
        dependencies=[],
        tags=["hypothesis", "causation", "reasoning_tree"],
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "分析会话 ID",
            },
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["add", "update", "confirm", "reject", "get"],
            },
            "hypothesis": {
                "type": "object",
                "description": "假设对象",
                "properties": {
                    "id": {"type": "string", "description": "假设 ID"},
                    "description": {"type": "string", "description": "假设描述"},
                    "confidence": {"type": "number", "description": "置信度 0-1"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "confirmed", "rejected", "inconclusive"],
                        "description": "假设状态",
                    },
                    "parent_id": {"type": "string", "description": "父假设 ID"},
                    "children": {"type": "array", "description": "子假设 ID 列表"},
                    "validation_method": {"type": "string", "description": "验证方法"},
                    "expected_evidence": {"type": "string", "description": "预期证据"},
                    "evidence_for": {"type": "array", "description": "支持证据"},
                    "evidence_against": {"type": "array", "description": "反对证据"},
                },
            },
        },
        "required": ["session_id", "action"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        start_time = time.time()
        session_id = params.get("session_id", "")
        action = params.get("action", "")
        hypothesis = params.get("hypothesis", {})

        if not session_id:
            return ToolResult(
                success=False,
                data=None,
                error="session_id 是必填参数",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            logger.info(
                "HypothesisStoreTool: session_id=%s, action=%s",
                session_id,
                action,
            )

            db = SessionLocal()
            try:
                session = db.query(BiAnalysisSession).filter(
                    BiAnalysisSession.id == session_id,
                    BiAnalysisSession.created_by == context.user_id,
                ).first()

                if not session:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"会话不存在: {session_id}",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                # 获取或初始化 hypothesis_tree
                tree = session.hypothesis_tree or {"nodes": [], "root": None}
                nodes = tree.get("nodes", [])
                nodes_dict = {n["id"]: n for n in nodes}

                if action == "get":
                    return ToolResult(
                        success=True,
                        data={
                            "hypothesis_tree": tree,
                            "node_count": len(nodes),
                        },
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                if action == "add":
                    hyp_id = hypothesis.get("id")
                    if not hyp_id:
                        import uuid
                        hyp_id = f"hyp_{uuid.uuid4().hex[:8]}"

                    new_node = {
                        "id": hyp_id,
                        "description": hypothesis.get("description", ""),
                        "confidence": hypothesis.get("confidence", 0.5),
                        "status": hypothesis.get("status", "pending"),
                        "parent_id": hypothesis.get("parent_id"),
                        "children": hypothesis.get("children", []),
                        "validation_method": hypothesis.get("validation_method", ""),
                        "expected_evidence": hypothesis.get("expected_evidence", ""),
                        "evidence_for": hypothesis.get("evidence_for", []),
                        "evidence_against": hypothesis.get("evidence_against", []),
                    }
                    nodes.append(new_node)
                    nodes_dict[hyp_id] = new_node

                    # 更新父节点的 children
                    parent_id = hypothesis.get("parent_id")
                    if parent_id and parent_id in nodes_dict:
                        parent = nodes_dict[parent_id]
                        if hyp_id not in parent.get("children", []):
                            parent["children"] = parent.get("children", []) + [hyp_id]

                    # 设置根节点
                    if not tree.get("root"):
                        tree["root"] = hyp_id

                    result_data = {
                        "hypothesis_id": hyp_id,
                        "action": "added",
                        "hypothesis_tree": tree,
                    }

                elif action == "update":
                    hyp_id = hypothesis.get("id")
                    if hyp_id not in nodes_dict:
                        return ToolResult(
                            success=False,
                            data=None,
                            error=f"假设不存在: {hyp_id}",
                            execution_time_ms=int((time.time() - start_time) * 1000),
                        )

                    node = nodes_dict[hyp_id]
                    node.update({
                        k: v for k, v in hypothesis.items()
                        if k != "id"  # 不允许修改 ID
                    })

                    result_data = {
                        "hypothesis_id": hyp_id,
                        "action": "updated",
                        "hypothesis_tree": tree,
                    }

                elif action == "confirm":
                    hyp_id = hypothesis.get("id")
                    if hyp_id in nodes_dict:
                        nodes_dict[hyp_id]["status"] = "confirmed"
                        nodes_dict[hyp_id]["confidence"] = hypothesis.get("confidence", nodes_dict[hyp_id].get("confidence", 0.8))
                        nodes_dict[hyp_id]["evidence_for"] = hypothesis.get("evidence_for", nodes_dict[hyp_id].get("evidence_for", []))

                    # 更新 confirmed_path
                    tree["confirmed_path"] = tree.get("confirmed_path", [])
                    if hyp_id not in tree["confirmed_path"]:
                        tree["confirmed_path"].append(hyp_id)

                    result_data = {
                        "hypothesis_id": hyp_id,
                        "action": "confirmed",
                        "hypothesis_tree": tree,
                    }

                elif action == "reject":
                    hyp_id = hypothesis.get("id")
                    if hyp_id in nodes_dict:
                        nodes_dict[hyp_id]["status"] = "rejected"
                        nodes_dict[hyp_id]["evidence_against"] = hypothesis.get("evidence_against", [])

                    # 更新 rejected_paths
                    tree["rejected_paths"] = tree.get("rejected_paths", [])
                    tree["rejected_paths"].append([hyp_id])

                    result_data = {
                        "hypothesis_id": hyp_id,
                        "action": "rejected",
                        "hypothesis_tree": tree,
                    }

                else:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"不支持的操作: {action}",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                # 更新会话的 hypothesis_tree
                tree["nodes"] = list(nodes_dict.values())
                session.hypothesis_tree = tree
                db.commit()

                return ToolResult(
                    success=True,
                    data=result_data,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            finally:
                db.close()

        except Exception as e:
            logger.exception("HypothesisStoreTool error: %s", e)
            return ToolResult(
                success=False,
                data=None,
                error=f"假设存储失败: {str(e)}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )