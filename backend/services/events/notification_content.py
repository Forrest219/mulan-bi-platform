"""通知标题/内容模板"""

from typing import Dict, Any


def build_tableau_sync_completed_content(payload: Dict[str, Any]) -> tuple:
    """tableau.sync.completed"""
    title = f"Tableau 同步完成"
    content = (
        f"连接「{payload.get('connection_name', '未知')}」同步成功，"
        f"共同步 {payload.get('workbooks_synced', 0)} 个工作簿、"
        f"{payload.get('views_synced', 0)} 个视图、"
        f"{payload.get('datasources_synced', 0)} 个数据源。"
        f"耗时 {payload.get('duration_sec', 0)} 秒。"
    )
    return title, content


def build_tableau_sync_failed_content(payload: Dict[str, Any]) -> tuple:
    """tableau.sync.failed"""
    title = f"Tableau 同步失败"
    content = (
        f"连接「{payload.get('connection_name', '未知')}」同步失败："
        f"{payload.get('error_message', '未知错误')}。"
        f"错误码：{payload.get('error_code', 'N/A')}"
    )
    return title, content


def build_tableau_connection_tested_content(payload: Dict[str, Any]) -> tuple:
    """tableau.connection.tested"""
    status = "成功" if payload.get("success") else "失败"
    title = f"Tableau 连接测试{status}"
    content = f"连接「{payload.get('connection_name', '未知')}」测试{status}。"
    return title, content


def build_semantic_submitted_content(payload: Dict[str, Any]) -> tuple:
    """semantic.submitted"""
    title = f"语义标注提交审核"
    content = (
        f"{payload.get('object_type', '对象')}「{payload.get('object_name', '未知')}」"
        f"已提交审核，请相关人员尽快处理。"
    )
    return title, content


def build_semantic_approved_content(payload: Dict[str, Any]) -> tuple:
    """semantic.approved"""
    title = f"语义标注审核通过"
    content = (
        f"您提交的 {payload.get('object_type', '对象')}「{payload.get('object_name', '未知')}」"
        f"已审核通过。审核人：{payload.get('reviewer_name', '未知')}"
    )
    return title, content


def build_semantic_rejected_content(payload: Dict[str, Any]) -> tuple:
    """semantic.rejected"""
    title = f"语义标注审核驳回"
    content = (
        f"您提交的 {payload.get('object_type', '对象')}「{payload.get('object_name', '未知')}」"
        f"已被驳回。审核人：{payload.get('reviewer_name', '未知')}。"
        f"意见：{payload.get('comment', '无')}"
    )
    return title, content


def build_semantic_published_content(payload: Dict[str, Any]) -> tuple:
    """semantic.published"""
    title = f"语义标注发布成功"
    content = (
        f"{payload.get('object_type', '对象')}「{payload.get('object_name', '未知')}」"
        f"已成功发布到 Tableau，共发布 {payload.get('fields_published', 0)} 个字段。"
    )
    return title, content


def build_semantic_publish_failed_content(payload: Dict[str, Any]) -> tuple:
    """semantic.publish_failed"""
    title = f"语义标注发布失败"
    content = f"语义标注发布失败，请检查配置和权限。"
    return title, content


def build_semantic_rollback_content(payload: Dict[str, Any]) -> tuple:
    """semantic.rollback"""
    title = f"语义版本回滚"
    content = (
        f"{payload.get('object_type', '对象')}「{payload.get('object_name', '未知')}」"
        f"已回滚至历史版本。"
    )
    return title, content


def build_semantic_ai_generated_content(payload: Dict[str, Any]) -> tuple:
    """semantic.ai_generated"""
    title = f"AI 语义生成完成"
    content = (
        f"{payload.get('object_type', '对象')}「{payload.get('object_name', '未知')}」"
        f"的 AI 语义标注已完成。"
    )
    return title, content


def build_health_scan_completed_content(payload: Dict[str, Any]) -> tuple:
    """health.scan.completed"""
    title = f"健康扫描完成"
    content = (
        f"数据源「{payload.get('datasource_name', '未知')}」扫描完成。"
        f"健康评分：{payload.get('health_score', 0)}，"
        f"共发现 {payload.get('total_issues', 0)} 个问题"
        f"（高 {payload.get('high_count', 0)} / "
        f"中 {payload.get('medium_count', 0)} / "
        f"低 {payload.get('low_count', 0)}）。"
    )
    return title, content


def build_health_scan_failed_content(payload: Dict[str, Any]) -> tuple:
    """health.scan.failed"""
    title = f"健康扫描失败"
    content = (
        f"数据源「{payload.get('datasource_name', '未知')}」扫描失败："
        f"{payload.get('error_message', '未知错误')}"
    )
    return title, content


def build_health_score_dropped_content(payload: Dict[str, Any]) -> tuple:
    """health.score.dropped"""
    title = f"健康分下降告警"
    content = (
        f"数据源「{payload.get('datasource_name', '未知')}」健康分从 "
        f"{payload.get('previous_score', 0)} 下降至 {payload.get('current_score', 0)}，"
        f"下降幅度：{payload.get('drop_amount', 0)} 分。"
    )
    return title, content


def build_auth_user_login_content(payload: Dict[str, Any]) -> tuple:
    """auth.user.login"""
    title = f"用户登录通知"
    content = f"用户「{payload.get('username', '未知')}」登录成功。"
    return title, content


def build_auth_user_created_content(payload: Dict[str, Any]) -> tuple:
    """auth.user.created"""
    title = f"新用户创建"
    content = f"新用户「{payload.get('username', '未知')}」已创建。"
    return title, content


def build_auth_user_role_changed_content(payload: Dict[str, Any]) -> tuple:
    """auth.user.role_changed"""
    title = f"用户角色变更"
    content = (
        f"用户「{payload.get('target_username', '未知')}」的角色已从 "
        f"「{payload.get('old_role', '未知')}」变更为「{payload.get('new_role', '未知')}」。"
    )
    return title, content


def build_system_maintenance_content(payload: Dict[str, Any]) -> tuple:
    """system.maintenance"""
    title = f"系统维护通知"
    content = payload.get("message", "系统即将进行维护，请提前保存工作。")
    return title, content


def build_system_error_content(payload: Dict[str, Any]) -> tuple:
    """system.error"""
    title = f"系统错误告警"
    content = f"系统发生错误：{payload.get('message', '未知错误')}"
    return title, content


def build_metric_published_content(payload: Dict[str, Any]) -> tuple:
    """metric.published"""
    title = "指标发布成功"
    content = (
        f"指标「{payload.get('name', '未知')}」已成功发布，现已激活生效。"
    )
    return title, content


def build_metric_anomaly_detected_content(payload: Dict[str, Any]) -> tuple:
    """metric.anomaly.detected"""
    title = "指标异常告警"
    content = (
        f"指标「{payload.get('metric_name', '未知')}」通过 {payload.get('detection_method', '未知')} "
        f"检测到异常，偏差分数：{payload.get('deviation_score', 0):.4f}，请及时排查。"
    )
    return title, content


def build_anomaly_detected_content(payload: Dict[str, Any]) -> tuple:
    """anomaly.detected — 异常告警邮件/站内模板（Spec 30）"""
    title = f"异常告警：{payload.get('metric_name', '未知指标')}"
    detected_at = payload.get("detected_at", "未知")
    score = payload.get("max_score") or payload.get("deviation_score") or 0.0
    link = payload.get("link") or ""
    content = (
        f"检测算法：{payload.get('algorithm', payload.get('detection_method', '未知'))}\n"
        f"异常点数量：{payload.get('anomaly_count', 1)}\n"
        f"最大偏差分数：{score:.4f}\n"
        f"检测时间：{detected_at}\n"
        f"窗口区间：{payload.get('window_start', 'N/A')} ~ {payload.get('window_end', 'N/A')}\n"
        + (f"查看详情：{link}" if link else "")
    )
    return title, content


def build_metric_consistency_failed_content(payload: Dict[str, Any]) -> tuple:
    """metric.consistency.failed"""
    title = "指标一致性校验失败"
    diff_pct = payload.get('difference_pct')
    diff_str = f"{diff_pct:.2f}%" if diff_pct is not None else "N/A"
    content = (
        f"指标「{payload.get('metric_name', '未知')}」跨数据源一致性校验失败，"
        f"差异百分比：{diff_str}，请检查数据源数据一致性。"
    )
    return title, content


def build_dqc_cycle_completed_content(payload: Dict[str, Any]) -> tuple:
    """dqc.cycle.completed"""
    title = "DQC 巡检完成"
    p0 = payload.get("p0_count", 0)
    p1 = payload.get("p1_count", 0)
    duration = payload.get("duration_sec", 0)
    count = payload.get("assets_processed", 0)
    scope = payload.get("scope", "full")
    content = f"DQC {scope} 巡检完成，处理 {count} 张表，P0={p0}，P1={p1}，耗时 {duration} 秒。"
    return title, content


def build_dqc_asset_signal_changed_content(payload: Dict[str, Any]) -> tuple:
    """dqc.asset.signal_changed"""
    asset_name = payload.get("display_name") or f"{payload.get('schema_name', '')}.{payload.get('table_name', '')}"
    title = f"资产信号变化：{asset_name}"
    content = f"信号从 {payload.get('prev_signal')} → {payload.get('current_signal')}，置信度 {payload.get('prev_confidence_score')} → {payload.get('current_confidence_score')}"
    return title, content


def build_dqc_asset_p0_triggered_content(payload: Dict[str, Any]) -> tuple:
    """dqc.asset.p0_triggered"""
    asset_name = payload.get("display_name") or f"{payload.get('schema_name', '')}.{payload.get('table_name', '')}"
    title = f"[P0] DQC 告警：{asset_name}"
    cs = payload.get("current_confidence_score", 0)
    content = f"资产置信度降至 {cs}，触发 P0 告警。请立即处理。"
    return title, content


def build_dqc_asset_p1_triggered_content(payload: Dict[str, Any]) -> tuple:
    """dqc.asset.p1_triggered"""
    asset_name = payload.get("display_name") or f"{payload.get('schema_name', '')}.{payload.get('table_name', '')}"
    title = f"[P1] DQC 告警：{asset_name}"
    cs = payload.get("current_confidence_score", 0)
    content = f"资产置信度降至 {cs}，触发 P1 告警。"
    return title, content


def build_dqc_asset_recovered_content(payload: Dict[str, Any]) -> tuple:
    """dqc.asset.recovered"""
    asset_name = payload.get("display_name") or f"{payload.get('schema_name', '')}.{payload.get('table_name', '')}"
    title = f"资产恢复：{asset_name}"
    cs = payload.get("current_confidence_score", 0)
    content = f"资产置信度恢复至 {cs}，信号已变为 GREEN。"
    return title, content


# 通知内容构建函数注册表
CONTENT_BUILDERS = {
    "tableau.sync.completed": build_tableau_sync_completed_content,
    "tableau.sync.failed": build_tableau_sync_failed_content,
    "tableau.connection.tested": build_tableau_connection_tested_content,
    "semantic.submitted": build_semantic_submitted_content,
    "semantic.approved": build_semantic_approved_content,
    "semantic.rejected": build_semantic_rejected_content,
    "semantic.published": build_semantic_published_content,
    "semantic.publish_failed": build_semantic_publish_failed_content,
    "semantic.rollback": build_semantic_rollback_content,
    "semantic.ai_generated": build_semantic_ai_generated_content,
    "health.scan.completed": build_health_scan_completed_content,
    "health.scan.failed": build_health_scan_failed_content,
    "health.score.dropped": build_health_score_dropped_content,
    "auth.user.login": build_auth_user_login_content,
    "auth.user.created": build_auth_user_created_content,
    "auth.user.role_changed": build_auth_user_role_changed_content,
    "system.maintenance": build_system_maintenance_content,
    "system.error": build_system_error_content,
    "metric.published": build_metric_published_content,
    "metric.anomaly.detected": build_metric_anomaly_detected_content,
    "metric.consistency.failed": build_metric_consistency_failed_content,
    "anomaly.detected": build_anomaly_detected_content,
    "dqc.cycle.completed": build_dqc_cycle_completed_content,
    "dqc.asset.signal_changed": build_dqc_asset_signal_changed_content,
    "dqc.asset.p0_triggered": build_dqc_asset_p0_triggered_content,
    "dqc.asset.p1_triggered": build_dqc_asset_p1_triggered_content,
    "dqc.asset.recovered": build_dqc_asset_recovered_content,
}


def build_notification_content(event_type: str, payload: Dict[str, Any], default_level: str = "info") -> tuple:
    """
    根据事件类型构建通知标题和内容。

    Returns:
        (title, content)
    """
    builder = CONTENT_BUILDERS.get(event_type)
    if builder:
        return builder(payload)

    # 默认兜底
    title = f"系统通知"
    content = f"收到事件：{event_type}"
    return title, content
