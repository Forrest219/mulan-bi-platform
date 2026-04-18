# MCP Server 外部项目参考

记录 Mulan 平台已接入或计划接入的 MCP Server 外部项目信息。

---

## Tableau MCP

| 项目 | 链接 |
|------|------|
| GitHub | https://github.com/tableau/tableau-mcp |
| 包名 | `@tableau/mcp-server` |
| 运行时 | Node.js 22.7.5+ |

### 必填配置

| 字段 | 环境变量 | 说明 |
|------|----------|------|
| Tableau Server URL | `SERVER` | 例如 `https://online.tableau.com` |
| Site Name | `SITE_NAME` | 站点标识符，默认站点留空 |
| PAT 名称 | `PAT_NAME` | Personal Access Token 名称 |
| PAT 密钥 | `PAT_VALUE` | Personal Access Token 密钥 |
| 传输模式 | `TRANSPORT` | `stdio` 或 `http`，生产用 `http` |

### 本地运行

```bash
# HTTP 模式（推荐）
npm run start:http

# Docker
npm run start:http:docker   # 映射端口 3927
```

MCP 进程地址：`http://localhost:3927/tableau-mcp`

### npx 方式（stdio）

```json
{
  "mcpServers": {
    "tableau": {
      "command": "npx",
      "args": ["-y", "@tableau/mcp-server@latest"],
      "env": {
        "SERVER": "https://online.tableau.com",
        "SITE_NAME": "",
        "PAT_NAME": "",
        "PAT_VALUE": "",
        "TRANSPORT": "http"
      }
    }
  }
}
```

---

## StarRocks MCP

| 项目 | 链接 |
|------|------|
| GitHub | https://github.com/StarRocks/mcp-server-starrocks |
| 包名 | `mcp-server-starrocks` |
| 运行时 | Python + uv |

### 必填配置

| 字段 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| Host | `STARROCKS_HOST` | `localhost` | 数据库主机 |
| Port | `STARROCKS_PORT` | `9030` | MySQL 协议端口 |
| 用户名 | `STARROCKS_USER` | `root` | |
| 密码 | `STARROCKS_PASSWORD` | 空 | |
| 默认数据库 | `STARROCKS_DB` | 可选 | |
| 连接串 | `STARROCKS_URL` | — | 优先级高于以上字段，格式：`user:pass@host:port/db` |
| 传输模式 | `MCP_TRANSPORT_MODE` | — | `stdio` 或 `streamable-http` |

### 本地运行

```bash
uv run mcp-server-starrocks --mode streamable-http --port 8000
```

MCP 进程地址：`http://localhost:8000/mcp`

### Streamable-HTTP 客户端配置

```json
{
  "mcpServers": {
    "mcp-server-starrocks": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

---

## 快速对照表

| 类型 | GitHub | 默认端口 | MCP URL |
|------|--------|----------|---------|
| tableau | https://github.com/tableau/tableau-mcp | 3927 | `http://localhost:3927/tableau-mcp` |
| starrocks | https://github.com/StarRocks/mcp-server-starrocks | 8000 | `http://localhost:8000/mcp` |
