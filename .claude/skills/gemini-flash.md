---
name: gemini-flash
description: Route a task to Gemini Flash for fast, low-cost batch work — test generation, type annotations, boilerplate CRUD, format conversion.
user_invocable: true
---

# /gemini-flash — Gemini Flash 快速批量任务

将轻量、重复性高的任务委派给 Gemini Flash，追求速度和低成本。

## 使用场景

- 批量生成单元测试
- 批量添加 TypeScript 类型注解
- CRUD 接口脚手架代码
- 配置文件格式转换（YAML/JSON/SQL 互转）
- 字段级语义标注（大量重复模式）
- 简单代码解释和翻译

## 执行流程

1. **收集上下文** — 读取目标文件和相关类型定义
2. **调用 Gemini Flash** — 通过 `gemini_chat`，model 指定 `gemini-2.5-flash`
3. **应用结果** — 直接写入或通过 Edit 应用
4. **快速验证** — 类型检查通过即可

## 调用规范

```
gemini_chat 参数：
- model: "gemini-2.5-flash"
- session: "mulan-batch"
- change_mode: true（代码修改时）
- message: 精简 prompt，只给必要上下文
```

## Prompt 模板

```
项目：Mulan BI Platform（React 19 + FastAPI + PostgreSQL 16）

文件内容：
{file_content}

任务：{task}

要求：直接输出代码，不要解释。
```

## 注意事项

- Flash 适合模式明确的任务，不适合复杂推理
- 如果 Flash 结果质量不够，自动升级到 Pro
- 不要用 Flash 处理安全相关代码
