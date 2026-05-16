# TESTER_FAIL

**测试时间**：2026-05-17 00:27  
**测试者**：Tester Agent  
**测试对象**：初始化配置验收（用户 / 用户组 / LLM / Tableau MCP / MySQL / StarRocks）  
**执行账号**：admin / admin123  
**环境**：Docker Compose（backend:8000 / frontend:3000）

---

## 总体结论：FAIL

共 6 项配置，4 项通过，2 项失败。

---

## 逐项结果

### ✅ 1. 用户（PASS）

| 用户名 | 角色 | 邮箱 | 状态 |
|--------|------|------|------|
| zhangxingchen | admin | zhangxingchen1@kingsoft.com | ✅ 创建成功 |
| zhaoying | data_admin | zhangying@test.com | ✅ 创建成功 |
| xuchao | data_admin | xuchao@test.com | ✅ 创建成功 |
| xieyue | user | xieyue@test.com | ✅ 创建成功 |
| linxinru | user | linxinru@test.com | ✅ 创建成功 |
| liyi | user | liyi@test.com | ✅ 创建成功 |
| yanglijing | user | yanglijing@test.com | ✅ 创建成功 |

系统现有用户：共 8 人（含 admin）。

---

### ✅ 2. 用户组（PASS）

| 用户组 | 成员 | 状态 |
|--------|------|------|
| 管理员（id=39） | admin、zhangxingchen | ✅ 成功 |
| 数据管理员（id=40） | zhaoying、xuchao | ✅ 成功 |
| 财数中心（id=41） | liyi、yanglijing | ✅ 成功 |
| 参谋部-信息技术部（id=42） | xieyue、linxinru | ✅ 成功 |

---

### ✅ 3. LLM（PASS）

配置已存在（id=34），与配置文件完全匹配：

| 字段 | 值 |
|------|-----|
| display_name | MiniMax-M2.7 |
| provider | anthropic |
| base_url | https://api.minimaxi.com/anthropic |
| model | MiniMax-M2.7 |
| is_active | true |
| has_api_key | true |

---

### ❌ 4. Tableau-online MCP（FAIL）

**实际表现**：配置写入成功（id=31），凭证字段正确，但连通性测试失败。

**预期表现**：`POST /api/mcp-configs/31/test` 返回 `success: true`。

**实际返回**：
```json
{"status": "online", "latency_ms": 6, "http_status": 404}
```
连接测试：`{"success": false, "message": "REST API 认证失败 (HTTP 404): {\"detail\":\"Not Found\"}"}`

**根本原因（两个独立 bug）**：

1. **Tableau MCP 容器启动错误**：
   ```
   ModuleNotFoundError: No module named 'app'
   ```
   容器 `mulan-bi-tableau-mcp` 在启动时尝试 `from app.core.database import SessionLocal`，但运行在独立容器内无法访问主后端模块，导致以 **degraded mode** 运行，无法从 DB 加载任何配置。

2. **连接测试路由错误**：
   后端将 Tableau REST API 认证请求（`POST /api/3.21/auth/signin`）发送至本地 MCP 容器（`172.18.0.7:3928`），而非 `online.tableau.com`，导致 404。

**复现步骤**：
```bash
curl -s -b cookies.txt -X POST http://localhost:8000/api/mcp-configs/31/test
# → {"status": "online", "latency_ms": 6, "http_status": 404}

docker logs mulan-bi-tableau-mcp 2>&1 | grep "POST /api/3.21/auth"
# → "POST /api/3.21/auth/signin HTTP/1.1" 404 Not Found
```

---

### ✅ 5. MySQL 数据库连接（PASS）

配置已存在（id=7），连通性测试通过：

| 字段 | 值 |
|------|-----|
| name | 阿里云 MySQL |
| host | rm-bp1t0ie3sj4g7561hpo.mysql.rds.aliyuncs.com |
| port | 3306 |
| database | openclaw_db |
| 连通性测试 | ✅ 连接成功 |

---

### ❌ 6. StarRocks 数据库连接（FAIL）

**实际表现**：配置写入成功（id=8），但连通性测试失败。

**预期表现**：`POST /api/datasources/8/test` 返回 `success: true`。

**实际返回**：`{"success": false, "message": "连接失败"}`

**根本原因**：后端拼接 SQLAlchemy 连接串时未对密码做 URL encode。密码 `bistar365@forai` 中的 `@` 被解析为主机分隔符，导致 host 变成 `forai@10.69.65.62`，实际连接字符串为：

```
mysql://admin:bistar365@forai@10.69.65.62:9030/ai
#                        ↑ 错误截断点
```

后端日志：
```
Can't connect to MySQL server on 'forai@10.69.65.62' ([Errno -2] Name or service not known)
```

**确认信息**：`10.69.65.62:9030` 从 Docker 容器内网络可达（TCP 连接测试通过），是纯粹的后端 URL encode 缺陷。

**复现步骤**：
```bash
# 1. 创建含 @ 字符密码的数据源
# 2. POST /api/datasources/8/test
# 3. docker logs mulan-bi-backend 查看：
#    Can't connect to MySQL server on 'forai@10.69.65.62'
```

---

## 缺陷汇总

| # | 缺陷 | 严重程度 | 影响范围 |
|---|------|---------|---------|
| BUG-1 | `tableau-mcp` 容器 `ModuleNotFoundError: No module named 'app'`，启动后 degraded mode | 高 | Tableau MCP 全部功能 |
| BUG-2 | Tableau 连接测试将 REST API 请求发至本地 MCP 容器而非 tableau.com | 高 | Tableau 连接测试 |
| BUG-3 | 数据源密码含 `@` 时 SQLAlchemy URL 未做 URL encode，连接失败 | 中 | 含特殊字符密码的所有数据库连接 |

---

## 下一步

移交 Fixer 处理 BUG-1、BUG-2、BUG-3，修复后 Tester 重新验收 Tableau MCP 和 StarRocks 两项。
