# MVP 外部服务配置指引

> 本文档说明 Sprint 0 验证阶段所需的外部服务配置步骤。
> 负责人：Zhang Xingchen

---

## 1. 概述

Sprint 0 验证需要以下外部服务：

| 资源 | 用途 | 配置位置 |
|------|------|----------|
| Tableau Server/Cloud 测试站点 | Tableau 资产同步 | 平台 UI（新建连接） |
| Tableau PAT | Tableau 认证 | `.env` → `TABLEAU_PAT_TOKEN` |
| LLM API Key | 首页问答、AI 摘要 | 平台 UI（系统管理 → LLM 配置） |
| 测试数据库 | DDL 扫描验证 | `.env` → `DATABASE_URL` |

---

## 2. LLM 配置指引

### 2.1 支持的 Provider

| Provider | 模型示例 | 配置难度 |
|----------|----------|----------|
| Anthropic | claude-sonnet-4-20250514 | 推荐 |
| OpenAI | gpt-4o | 中 |
| MiniMax | abab6.5s-chat | 低 |

### 2.2 Anthropic 配置步骤

**Step 1：获取 API Key**

1. 访问 [Anthropic Console](https://console.anthropic.com/)
2. 登录后进入 API Keys 页面
3. 点击 Create Key，命名如 `mulan-bi-sprint0`
4. 复制生成的 Key（格式：`sk-ant-...`）

**Step 2：在平台中配置**

1. 以 admin 身份登录平台
2. 进入 **系统管理 → LLM 配置**
3. 点击「新建配置」：
   - **Provider**：选择 `Anthropic`
   - **Display Name**：`Anthropic (Sprint0)`
   - **API Key**：粘贴从 Console 获取的 Key
   - **优先级**：数值越小优先级越高（建议设为 10）
   - **启用**：打开
4. 点击「测试」按钮验证连接
5. 保存配置

**Step 3：环境变量（非必须，仅供参考）**

```bash
# .env 中可选择性配置，用于本地开发
ANTHROPIC_API_KEY=sk-ant-...
```

### 2.3 OpenAI 配置步骤

**Step 1：获取 API Key**

1. 访问 [OpenAI Platform](https://platform.openai.com/api-keys)
2. 点击 Create new secret key
3. 命名后复制生成的 Key

**Step 2：在平台中配置**

1. 进入 **系统管理 → LLM 配置**
2. 新建配置：
   - **Provider**：选择 `OpenAI`
   - **Display Name**：`OpenAI (Sprint0)`
   - **API Key**：粘贴 Key
   - **模型**：默认 `gpt-4o`，可更改为 `gpt-4o-mini` 降低成本
   - **优先级**：建议设为 20（优先级低于 Anthropic）
   - **启用**：打开
3. 测试并保存

### 2.4 MiniMax 配置步骤

**Step 1：获取 API Key**

1. 访问 MiniMax 开放平台
2. 创建应用后获取 API Key

**Step 2：在平台中配置**

1. 进入 **系统管理 → LLM 配置**
2. 新建配置：
   - **Provider**：选择 `MiniMax`（如果下拉中有此选项）
   - **API Key**：粘贴 Key
   - **Base URL**：`https://api.minimax.chat/v1`（如需要）
   - **优先级**：根据需要设置
3. 测试并保存

### 2.5 LLM 配置加密说明

LLM API Key 在数据库中以 Fernet 对称加密存储：

- 加密密钥：`LLM_ENCRYPTION_KEY`（在 `.env` 中配置）
- 存储方式：加密后存入 `llm_configs.api_key_encrypted`
- 展示方式：列表页仅显示指纹（如 `sk-ant-••••3f2a`）

---

## 3. Tableau MCP 配置指引

### 3.1 获取 Tableau PAT

**Step 1：登录 Tableau Cloud/Server**

1. 访问你的 Tableau Cloud URL（如 `https://your-org.tableau.com`）
2. 以管理员身份登录

**Step 2：创建 Personal Access Token**

1. 点击右上角头像 → **我的账户设置**（或 **My Account Settings**）
2. 滚动到 **Personal Access Tokens** 部分
3. 点击 **Create a Personal Access Token**
4. 填写 Token 名称：如 `mulan-bi-sync`
5. 点击 **Create**
6. **立即复制 Token Secret**（只显示一次，错过需重新创建）

**Step 3：记录必要信息**

创建连接时需要以下信息：

| 字段 | 示例值 |
|------|--------|
| Server URL | `https://your-org.tableau.com` |
| Site Content URL | `default`（或你的 site 名称） |
| Token Name | `mulan-bi-sync` |
| Token Secret | `••••••••••••••••`（粘贴上一步复制的值） |

### 3.2 Tableau 连接加密说明

PAT 在数据库中以 Fernet 对称加密存储：

- 加密密钥：`TABLEAU_ENCRYPTION_KEY`（在 `.env` 中配置）
- 存储位置：`tableau_connections.token_encrypted`

### 3.3 在平台中新建 Tableau 连接

1. 以 admin 或 data_admin 身份登录平台
2. 进入 **资产管理 → Tableau 连接**
3. 点击「新建连接」
4. 填写表单：

| 字段 | 填写内容 |
|------|----------|
| 连接名称 | `Tableau Sprint0 Test` |
| Server URL | 你的 Tableau Server/Cloud URL |
| Site | Site Content URL（如 `default`） |
| 连接类型 | 选择 `MCP`（推荐）或 `TSC` |
| Token Name | 上一步创建的 PAT 名称 |
| Token Secret | 上一步创建的 PAT 值 |
| 自动同步 | 建议开启，间隔 24 小时 |
5. 点击「测试连接」，确认成功后保存

### 3.4 测试站点数据要求

验收标准要求测试站点至少包含：

| 资产类型 | 最低数量 | 说明 |
|----------|----------|------|
| 工作簿（Workbook） | 2 个 | 建议包含不同项目 |
| 视图（View） | 5 个 | 分布在上述工作簿中 |
| 数据源（Datasource） | 1 个 | 已发布到 Tableau Server |

如测试环境数据不足，可：

1. 使用 Tableau 官方示例工作簿（Sample - Superstore）发布到测试站点
2. 或联系 Zhang Xingchen 准备符合要求的测试数据

---

## 4. 测试数据库准备

### 4.1 目的

测试 DDL 扫描功能能扫出真实违规项。

### 4.2 要求

| 要求 | 说明 |
|------|------|
| 数据库类型 | MySQL 8.x 或 PostgreSQL 12+ |
| 表结构 | 包含可触发规则违规的表（如主键缺失、无注释、命名不规范等） |
| 访问权限 | 平台运行账户需有 SELECT 权限（DDL 扫描为只读） |

### 4.3 最小测试数据集

在测试数据库中执行以下 SQL 创建测试表：

```sql
-- PostgreSQL 示例
CREATE TABLE test_sales (
    id INTEGER,                    -- 违规：缺少主键
    product_name VARCHAR(100),      -- 违规：缺少 COMMENT
    sale_date DATE,                -- 合规
    amount DECIMAL(10,2)           -- 违规：命名含下划线（非 camelCase）
);

CREATE TABLE test_users (
    user_id SERIAL PRIMARY KEY,    -- 合规
    username VARCHAR(50) NOT NULL, -- 违规：缺少 COMMENT
    created_at TIMESTAMP DEFAULT NOW()  -- 合规
);

-- 添加一些数据以便扫描
INSERT INTO test_sales (id, product_name, sale_date, amount) VALUES
(1, 'Product A', '2026-01-01', 100.00),
(2, 'Product B', '2026-01-02', 200.00);

INSERT INTO test_users (username) VALUES
('user1'), ('user2');
```

```sql
-- MySQL 示例
CREATE TABLE test_sales (
    id INT,                         -- 违规：缺少主键、缺少 COMMENT
    product_name VARCHAR(100),      -- 违规：缺少 COMMENT
    sale_date DATE,                 -- 合规
    amount DECIMAL(10,2)           -- 违规：命名含下划线
);

CREATE TABLE test_users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,  -- 合规
    username VARCHAR(50) NOT NULL,           -- 违规：缺少 COMMENT
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- 合规
);
```

### 4.4 配置连接

1. 以 admin 身份登录平台
2. 进入 **系统管理 → MCP 配置**（或 **连接中心**）
3. 新建数据库连接：
   - **类型**：选择 `PostgreSQL` 或 `MySQL`
   - **Host**：测试数据库 host
   - **Port**：`5432`（PG）或 `3306`（MySQL）
   - **Database**：数据库名
   - **Username** / **Password**：连接凭证
4. 点击「测试连接」，成功后保存

### 4.5 DDL 扫描触发

1. 进入 **数据治理 → 质量检查**（或相关 DDL 扫描入口）
2. 选择已配置的数据库连接
3. 选择 `test_sales` / `test_users` 表
4. 点击「扫描」
5. 预期：扫描结果应包含主键缺失、缺少注释等违规项

---

## 5. 环境变量汇总

`.env` 中与外部服务相关的配置项：

```bash
# ──────────────────────────────────────────────
# Tableau PAT 配置
# ──────────────────────────────────────────────
TABLEAU_PAT_TOKEN=your-tableau-pat-token-here

# Tableau PAT 加密密钥（必填，正好 32 字节）
TABLEAU_ENCRYPTION_KEY=change-this-to-another-key-32b!

# ──────────────────────────────────────────────
# LLM API Key 配置
# ──────────────────────────────────────────────
# LLM_API_KEY=sk-ant-...  （通过平台 UI 配置，不在 .env 中）

# LLM 加密密钥（必填，正好 32 字节）
LLM_ENCRYPTION_KEY=change-this-to-llm-key-32bytes!

# ──────────────────────────────────────────────
# 测试数据库连接
# ──────────────────────────────────────────────
DATABASE_URL=postgresql://mulan:***@localhost:5432/mulan_bi
```

> **注意**：Tableau PAT 和 LLM API Key 主要通过平台 UI 配置（加密后存储到数据库），`.env` 中的加密密钥仅用于运行时解密。

---

## 6. 验证方法

### 6.1 验证 Tableau 连接

**验收标准：在平台中新建 Tableau 连接并同步成功**

1. 进入 **资产管理 → Tableau 连接**
2. 确认新建的连接显示在列表中
3. 点击连接右侧的「测试」按钮，预期：`success: true`
4. 点击「同步」，等待完成后：
   - 进入 **资产管理 → Tableau 资产**
   - 确认能看到工作簿、视图列表
   - 确认数据源已同步

### 6.2 验证 LLM 配置

**验收标准：在首页提问能收到 LLM 回答**

1. 进入平台首页
2. 在问答输入框输入问题，如：`介绍一下你们的数据平台`
3. 按回车提交
4. 预期：
   - 收到流式回答
   - 回答内容来自配置的 LLM（可在回答后查看 trace_id）
5. 如回答失败，检查 **系统管理 → LLM 配置** 中该配置的「运行状态」

### 6.3 验证 DDL 扫描

**验收标准：DDL 扫描能扫出真实违规项**

1. 进入 **数据治理 → DDL 扫描**（或相关入口）
2. 选择已配置的测试数据库
3. 选择 `test_sales` 或 `test_users` 表
4. 点击「扫描」
5. 预期结果包含以下违规项：
   - 主键缺失（`id` 字段）
   - 字段缺少 COMMENT 注释
6. 如无违规项，检查规则配置是否正确加载

---

## 7. 常见问题

### Q1: Tableau 连接测试失败，提示 `401 Unauthorized`

**可能原因**：
- PAT Token 已过期或被撤销
- Token Name 不匹配
- Server URL 或 Site 不正确

**排查步骤**：
1. 确认 PAT 在 Tableau Console 中处于 Active 状态
2. 确认 Token Name 与创建时完全一致（区分大小写）
3. 确认 Site Content URL 正确（注意不是 Site ID）

### Q2: LLM 测试成功但首页无回答

**可能原因**：
- LLM 配置未启用
- 优先级配置问题
- 前端网络问题

**排查步骤**：
1. 检查 **系统管理 → LLM 配置**，确认配置已启用
2. 检查浏览器控制台是否有网络错误
3. 确认至少有一个 LLM 配置的「运行状态」为成功

### Q3: DDL 扫描无违规项

**可能原因**：
- 数据库连接配置错误
- 扫描规则未正确加载
- 测试表已被修复

**排查步骤**：
1. 重新测试数据库连接
2. 检查规则配置中是否启用了主键检查、注释检查
3. 确认 `test_sales` 表结构未被修改

### Q4: API Key 展示为"未配置"但实际已配置

**说明**：这是已知的 UI 显示问题（见 `docs/PM_LLM_CONFIG_FEEDBACK.md` 反馈 3），不影响实际功能。如确认 Key 已正确保存但仍显示"未配置"，请联系开发团队。

---

## 8. 待决事项

| # | 事项 | 来源 | 负责人 | 状态 |
|---|------|------|--------|------|
| 1 | 准备符合数据要求的 Tableau 测试站点（2 工作簿、5 视图、1 数据源） | S0-6 | Zhang Xingchen | pending |
| 2 | 确认 MiniMax provider 在平台中是否可用 | S0-6 | Zhang Xingchen | pending |

---

## 9. 参考文档

| 文档 | 路径 |
|------|------|
| LLM 配置 UI 反馈分析 | `docs/PM_LLM_CONFIG_FEEDBACK.md` |
| Tableau MCP V1 技术规格 | `docs/specs/07-tableau-mcp-v1-spec.md` |
| 平台设置技术规格 | `docs/specs/37-platform-settings-spec.md` |
| 测试规范 | `docs/TESTING.md` |
| 环境变量示例 | `.env.example` |
