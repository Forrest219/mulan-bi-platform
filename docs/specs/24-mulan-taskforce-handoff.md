# Spec 24 特工队接管总控台

> 状态: In Progress（已完成文档接管，待进入实现）  
> 日期: 2026-04-16

## 1) 已接管输出

1. 架构实施路线图（Architect）
- docs/tech/24-implementation-architecture-roadmap.md
- 内容：P0-P4 模块级改造、数据迁移、API 契约、风险回滚、各阶段 DoD

2. UI 落地细则（Designer）
- docs/tech/24-ui-execution-home-admin.md
- 内容：首页与连接中心组件树/状态机、交互规范、token 映射、无障碍、迭代清单

3. 6周执行手册（Orchestrator）
- docs/prd-status-spec24-rollout-plan.md
- 内容：周计划、分工、门禁、风险台账、Spec 18/21/22/24 追踪矩阵

## 2) 执行顺序（建议）

- 第一步：按 24-implementation-architecture-roadmap.md 启动 P0（基线与守护）
- 第二步：并行启动 UI Iteration A（首页状态机梳理）
- 第三步：进入 P1（Task Runtime 薄编排）+ UI Iteration B/C
- 第四步：连接中心统一壳上线（兼容旧路由）

## 3) 门禁（必须）

- 不破坏现有 5 域路由
- 不修改 /api/* 既有语义（仅增量扩展）
- 所有新增副作用流程必须可审计（trace_id + audit event）
- feature flag 控制新链路

## 4) 当前建议指令入口

可直接下发以下任一执行口令：

A. “进入 P0 实施，先做后端基线改造任务清单并开始第一批提交”
B. “先做首页 UI Iteration A/B，给我 PR 级改动”
C. “先做连接中心壳（不改后端），打通页面与旧 API 适配层”
D. “按 6 周计划全量推进，每周给我验收报告模板”
