# Mulan Docker 一键部署迁移技术规格书

> 版本：v0.2 | 状态：草稿 | 日期：2026-05-14 | 目标：未来同事只安装 Docker 即可一键启动 Mulan

---

## 1. 概述

### 1.1 目的

将 Mulan 当前“Docker 基础设施 + 宿主机 Python/Node 运行前后端”的混合启动方式，迁移为完整 Docker Compose 编排。迁移完成后，新同事或测试环境只需要安装 Docker / Docker Compose，配置 `.env`，即可通过一个命令启动完整系统。

### 1.2 当前状态

当前项目已经部分 Docker 化：

- `docker-compose.yml` 已包含 `postgres`、`redis`、`celery`。
- `backend/Dockerfile` 已存在，但只完成 Python 依赖安装，没有标准运行入口、健康检查和迁移流程。
- 前端没有 Dockerfile。
- `start-dev.sh` 是当前唯一推荐本地启动入口，但仍依赖宿主机：
  - `backend/.venv/bin/python`
  - `backend/.venv/bin/celery`
  - `npm run dev`

当前实现缺口：

| 交付物 | 当前状态 | 迁移要求 |
|---|---|---|
| `frontend/Dockerfile` | 不存在 | 新增 multi-stage dev/build/prod |
| `frontend/nginx.conf` | 不存在 | 新增 `/api`、`/tableau-mcp` 代理 |
| `.env.docker.example` | 不存在 | 新增容器内地址模板 |
| `docker-compose.dev.yml` | 不存在 | 新增本地开发覆盖 |
| `docker-compose.deploy.yml` | 不存在 | 新增测试/部署覆盖 |
| `deploy-docker.sh` | 不存在 | 新增一键部署入口 |
| `docs/deployment/docker.md` | 不存在 | 新增面向同事的部署文档 |
| `backend/Dockerfile` | 仅基础安装 | 补齐 runtime ENV、健康检查、compose command 支持 |
| `docker-compose.yml` | 仅基础设施 + combined celery | 补齐 API、migrate、worker、beat |
| `start-dev.sh` | 仅混合模式 + stop | 增加 docker 子命令 |
| `deploy-test.sh` | 宿主机部署脚本 | 废弃并指向 `deploy-docker.sh` |

### 1.3 迁移目标

P0 目标：

- 本机只要求安装 Docker。
- 不要求安装 Python、Node、npm、backend virtualenv。
- 一个命令启动完整本地系统：

```bash
./start-dev.sh docker
```

- 一个命令停止完整本地系统：

```bash
./start-dev.sh docker stop
```

P1 目标：

- 测试环境一键部署：

```bash
./deploy-docker.sh up
```

- 前端使用生产构建 + Nginx，不依赖 Vite dev server。

P2 目标：

- CI 能验证 Docker 镜像构建、数据库迁移、健康检查和基础 smoke test。

### 1.4 范围

包含：

- 后端 Dockerfile 标准化。
- 新增前端 Dockerfile。
- 新增 Nginx 前端部署配置。
- 重构 Docker Compose 服务编排。
- 数据库迁移容器化。
- Celery worker / beat 容器化。
- 一键启动脚本改造。
- `.env.docker.example`。
- Docker 部署文档和验收标准。

不包含：

- Kubernetes / Helm。
- 云厂商专有部署。
- 数据库高可用。
- 生产级密钥管理系统。
- 对 Tableau Server / 外部 MCP 服务本身的容器化改造。

---

## 2. 目标架构

### 2.1 服务拓扑

```mermaid
flowchart LR
    U[Browser] --> FE[frontend-nginx:3000]
    FE --> API[backend-api:8000]
    API --> PG[(postgres)]
    API --> R[(redis)]
    API --> EXT[External Tableau / MCP / LLM]
    CW[celery-worker] --> PG
    CW --> R
    CW --> EXT
    CB[celery-beat] --> R
    MIG[migrate] --> PG
```

### 2.2 Compose 服务清单

| 服务 | 镜像来源 | 端口 | 职责 | P0/P1 |
|---|---|---:|---|---|
| `postgres` | `pgvector/pgvector:pg16` | `5432` | 主数据库 + pgvector | P0 |
| `redis` | `redis:7-alpine` | `6379` | Celery broker / cache | P0 |
| `backend-api` | `backend/Dockerfile` | `8000` | FastAPI API 服务 | P0 |
| `migrate` | `backend/Dockerfile` | 无 | `alembic upgrade head` 一次性迁移 | P0 |
| `celery-worker` | `backend/Dockerfile` | 无 | 异步任务 worker | P0 |
| `celery-beat` | `backend/Dockerfile` | 无 | 定时任务调度 | P0 |
| `frontend-dev` | `frontend/Dockerfile` | `3000` | Vite dev server | P0 |
| `frontend` | `frontend/Dockerfile` multi-stage + Nginx | `3000` | 生产静态站点 | P1 |

### 2.3 网络规则

容器内服务不得使用宿主机 `localhost` 互访。

| 目标 | 容器内地址 |
|---|---|
| PostgreSQL | `postgres:5432` |
| Redis | `redis:6379` |
| Backend API | `backend-api:8000` |
| Frontend | `frontend:3000` |

如果后端需要访问宿主机上的外部服务，必须显式使用：

```text
host.docker.internal
```

并在 `.env.docker.example` 中标注。

---

## 3. 文件交付清单

### 3.1 新增文件

| 文件 | 说明 |
|---|---|
| `frontend/Dockerfile` | 前端 dev/build/nginx multi-stage 镜像 |
| `frontend/nginx.conf` | 前端静态资源服务和 `/api` 反向代理 |
| `.env.docker.example` | Docker 启动环境变量模板 |
| `docker-compose.dev.yml` | 本地开发 Compose 覆盖文件 |
| `docker-compose.deploy.yml` | 测试/部署 Compose 覆盖文件 |
| `docker-compose.debug.yml` | 可选调试覆盖文件，发布 DB/Redis 端口 |
| `deploy-docker.sh` | 测试环境一键部署入口 |
| `docs/deployment/docker.md` | 面向同事的部署说明 |

### 3.2 修改文件

| 文件 | 修改点 |
|---|---|
| `docker-compose.yml` | 抽象通用服务：postgres、redis、backend-api、migrate、celery-worker、celery-beat |
| `backend/Dockerfile` | 增加 runtime 配置、系统依赖、非交互启动约束 |
| `start-dev.sh` | 增加 `docker` 模式，保留唯一推荐本地启动入口 |
| `deploy-test.sh` | 废弃宿主机 Python/Node 流程，提示使用 `deploy-docker.sh` |
| `README.md` | 增加 Docker 一键启动入口 |

---

## 4. Compose 设计

### 4.1 基础 Compose

`docker-compose.yml` 只放跨环境通用服务和配置，默认不发布数据库和 Redis 端口到宿主机：

- `postgres`
- `redis`
- `backend-api`
- `migrate`
- `celery-worker`
- `celery-beat`
- volumes
- networks

约束：

- `postgres`、`redis` 是核心依赖，不能通过 profile 隐藏，否则部署模式下后端无法启动。
- 端口发布必须放在 dev/debug 覆盖文件中，而不是放在基础 compose。

### 4.2 本地开发覆盖

`docker-compose.dev.yml`：

- 启动 `frontend-dev`。
- 前端挂载源码目录，支持热更新。
- 后端可选挂载 `backend/`，支持 `uvicorn --reload`。
- 映射端口：
  - `3000:3000`
  - `8000:8000`
  - `5432:5432`
  - `6379:6379`

### 4.3 调试覆盖

`docker-compose.debug.yml`：

- 仅用于测试环境临时排障。
- 在部署模式下如需临时访问 DB/Redis，可额外叠加该文件发布端口。
- 不允许默认启用。

示例：

```bash
docker compose --env-file .env.docker \
  -f docker-compose.yml \
  -f docker-compose.deploy.yml \
  -f docker-compose.debug.yml \
  up -d
```

### 4.4 测试/部署覆盖

`docker-compose.deploy.yml`：

- 启动 `frontend` Nginx 生产构建。
- 后端不使用 `--reload`。
- 默认不暴露数据库和 Redis 到宿主机；如需调试，叠加 `docker-compose.debug.yml`。
- `restart: unless-stopped`。
- 健康检查必须启用。

---

## 5. 镜像设计

### 5.1 Backend 镜像

要求：

- 基础镜像固定为 Python 3.11。
- `WORKDIR /app`。
- 设置：

```dockerfile
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
```

- 安装 `backend/requirements.txt`。
- Dockerfile 可以提供 API 默认 `CMD`，但不得把 `migrate`、`celery-worker`、`celery-beat` 写死为唯一入口。
- Compose 中不同 service 必须通过 `command` 显式覆盖。
- 推荐 Dockerfile 默认命令：

```dockerfile
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- Compose service 命令必须使用：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m alembic upgrade head
python -m celery -A services.tasks worker --pool=solo --loglevel=warning
python -m celery -A services.tasks beat -S redbeat.RedBeatScheduler --loglevel=warning
```

禁止：

- 裸 `python3`。
- 裸 `uvicorn`。
- 裸 `alembic`。
- 裸 `celery`。

### 5.2 Frontend 镜像

`frontend/Dockerfile` 使用 multi-stage：

1. `deps`：安装 npm 依赖。
2. `dev`：运行 Vite dev server。
3. `build`：执行 `npm run build`，输出 `out/`。
4. `prod`：Nginx 服务静态文件。

P0 dev command：

```bash
npm run dev -- --host 0.0.0.0 --port 3000 --strictPort
```

P1 prod command：

```bash
nginx -g "daemon off;"
```

### 5.3 Nginx 代理规则

`frontend/nginx.conf`：

```nginx
location / {
  try_files $uri $uri/ /index.html;
}

location /api/ {
  proxy_pass http://backend-api:8000/api/;
}

location /tableau-mcp/ {
  proxy_pass http://backend-api:8000/tableau-mcp/;
}
```

---

## 6. 环境变量规范

### 6.1 Docker 环境文件

新增 `.env.docker.example`。

必需变量：

| 变量 | 示例 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql://mulan:mulan@postgres:5432/mulan_bi` | 容器内数据库地址 |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | Celery result backend |
| `SESSION_SECRET` | `change-me` | 会话密钥 |
| `DATASOURCE_ENCRYPTION_KEY` | `base64...` | 数据源加密密钥 |
| `LLM_ENCRYPTION_KEY` | `base64...` | LLM 配置加密密钥 |
| `TABLEAU_ENCRYPTION_KEY` | `base64...` | Tableau 配置加密密钥 |
| `TZ` | `Asia/Shanghai` | 时区 |

可选变量：

| 变量 | 说明 |
|---|---|
| `TABLEAU_SERVER_URL` | Tableau Server 地址 |
| `MCP_GATEWAY_URL` | 外部 MCP Gateway 地址 |
| `OPENAI_API_KEY` | 如使用 OpenAI |
| `LLM_PROVIDER` | LLM provider |

### 6.2 加载规则

本地 Docker 启动：

```bash
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

测试部署启动：

```bash
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.deploy.yml up -d --build
```

### 6.3 平台兼容

Apple Silicon：

- 不默认强制 `platform: linux/amd64`，避免在 M1/M2/M3 上无谓降速。
- 如果某个镜像在 Apple Silicon 上不可用，允许在 `.env.docker` 中设置：

```bash
DOCKER_DEFAULT_PLATFORM=linux/amd64
```

或在本地 override 文件中对单个服务设置 `platform`。

Windows：

- 官方推荐通过 WSL2 + Docker Desktop 运行。
- 不保证 Windows 原生路径挂载行为。

---

## 7. 启动入口设计

### 7.1 本地开发入口

保留 `start-dev.sh` 作为唯一推荐本地入口。

新增命令：

```bash
./start-dev.sh docker
./start-dev.sh docker stop
./start-dev.sh docker logs
./start-dev.sh docker restart
```

行为：

| 命令 | 行为 |
|---|---|
| `./start-dev.sh` | 保留当前混合启动模式，作为短期兼容 |
| `./start-dev.sh docker` | 全 Docker 本地启动 |
| `./start-dev.sh docker stop` | 停止 Docker 服务 |
| `./start-dev.sh docker logs` | 查看 compose logs |
| `./start-dev.sh docker restart` | 重启 compose 服务 |

P1 后可将默认行为切到 Docker：

```bash
./start-dev.sh
```

等价于：

```bash
./start-dev.sh docker
```

### 7.2 测试部署入口

新增：

```bash
./deploy-docker.sh up
./deploy-docker.sh down
./deploy-docker.sh logs
./deploy-docker.sh status
```

`deploy-test.sh` 改为兼容提示：

```text
deploy-test.sh is deprecated. Use ./deploy-docker.sh up.
```

---

## 8. 数据库迁移与启动顺序

### 8.1 启动顺序

```mermaid
sequenceDiagram
    participant S as start-dev.sh docker
    participant PG as postgres
    participant R as redis
    participant M as migrate
    participant API as backend-api
    participant C as celery
    participant F as frontend

    S->>PG: start
    S->>R: start
    PG-->>S: healthy
    R-->>S: healthy
    S->>M: alembic upgrade head
    M-->>S: completed successfully
    S->>API: start
    S->>C: start worker/beat
    S->>F: start frontend
```

### 8.2 迁移规则

- `migrate` 是一次性 service。
- `backend-api` 必须依赖 `migrate` 成功完成。
- `migrate` 必须设置 `restart: "no"`。
- 如果使用 compose 依赖链，必须使用 Compose v2 支持的：

```yaml
depends_on:
  migrate:
    condition: service_completed_successfully
```

- 如果目标环境 Compose 版本不支持 `service_completed_successfully`，启动脚本必须显式执行：

```bash
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.deploy.yml run --rm migrate
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.deploy.yml up -d backend-api celery-worker celery-beat frontend
```

- 如果迁移失败，启动脚本必须失败并输出迁移日志。
- 不允许 API 容器启动后再静默执行迁移。

---

## 9. 持久化与文件系统

### 9.1 Volumes

| Volume | 挂载点 | 说明 |
|---|---|---|
| `pgdata` | `/var/lib/postgresql/data` | PostgreSQL 数据 |
| `redisdata` | `/data` | Redis 数据 |
| `backend_uploads` | `/app/uploads` | 用户上传文件，如项目使用 |
| `backend_exports` | `/app/exports` | 导出文件，如项目使用 |

### 9.2 日志

容器内应用日志默认输出 stdout/stderr。

本地调试使用：

```bash
docker compose logs -f backend-api
docker compose logs -f frontend
docker compose logs -f celery-worker
```

不再要求宿主机 `.dev-logs/` 才能排查 Docker 启动问题。

---

## 10. 安全与配置约束

### 10.1 密钥

- `.env.docker` 不提交 git。
- `.env.docker.example` 只提供占位符。
- 启动脚本必须检查关键密钥是否仍为默认值，部署模式下默认值直接失败。

### 10.2 端口暴露

本地开发：

- 可暴露 `5432`、`6379` 便于调试。

测试部署：

- 默认只暴露 `3000`。
- `8000` 是否暴露由部署参数决定。
- 默认不暴露 `5432`、`6379`。

### 10.3 只读前端镜像

生产前端容器不挂载源码，不运行 npm，不保存状态。

---

## 11. 迁移阶段

### Phase 0：基线确认

任务：

- 确认当前 `start-dev.sh` 可用。
- 确认当前数据库迁移可在宿主机成功执行。
- 记录当前需要的环境变量。
- 增加可重复的基线验证脚本或命令，避免只靠人工确认。

基线验证命令：

```bash
./start-dev.sh
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:3000/
./start-dev.sh stop
```

验收：

- `./start-dev.sh` 可启动。
- `http://localhost:3000` 可访问。
- `http://localhost:8000/health` 返回成功。

### Phase 1：本地全 Docker 跑通

任务：

- 完善 `backend/Dockerfile`。
- 新增 `frontend/Dockerfile`。
- 新增 `docker-compose.dev.yml`。
- 增加 `migrate` service。
- 修改 `start-dev.sh docker`。

验收：

```bash
./start-dev.sh docker
```

启动后：

- `http://localhost:3000` 可访问。
- `http://localhost:8000/health` 可访问。
- 登录页可打开。
- 首页问答 API 至少能返回鉴权错误或正常业务响应，不出现 502。
- `docker compose ps` 所有核心服务 healthy 或 running。

### Phase 2：Celery 与定时任务容器化

任务：

- 拆分 `celery-worker` 和 `celery-beat`。
- 统一 `CELERY_BROKER_URL` 和 `CELERY_RESULT_BACKEND`。
- 保持 `--pool=solo` 与当前本地行为一致，避免 macOS/容器下 fork 差异。

验收：

- worker 成功连接 Redis。
- beat 正常启动。
- 任务管理页面不因 Celery 缺失报错。

### Phase 3：测试部署模式

任务：

- 新增 `frontend/nginx.conf`。
- 新增 `docker-compose.deploy.yml`。
- 新增 `deploy-docker.sh`。
- 废弃 `deploy-test.sh` 宿主机流程。

验收：

```bash
./deploy-docker.sh up
```

启动后：

- 只需 Docker，无需 Python/Node/npm。
- `http://localhost:3000` 可访问。
- 前端 `/api` 代理到后端。
- 后端健康检查通过。

### Phase 4：CI 与文档

任务：

- README 增加 Docker 一键启动。
- 新增 `docs/deployment/docker.md`。
- CI 增加 Docker 构建检查。

验收：

- 新同事按照文档，从 clean machine 到启动成功不需要安装 Python/Node。
- CI 能执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.deploy.yml config
docker compose -f docker-compose.yml -f docker-compose.deploy.yml build
```

---

## 12. 测试策略

### 12.1 P0 测试

| # | 场景 | 命令 | 预期 |
|---|---|---|---|
| 1 | Compose 配置合法 | `docker compose -f docker-compose.yml -f docker-compose.dev.yml config` | exit 0 |
| 2 | 镜像构建 | `docker compose -f docker-compose.yml -f docker-compose.dev.yml build` | exit 0 |
| 3 | 本地 Docker 启动 | `./start-dev.sh docker` | 所有核心服务启动 |
| 4 | DB 迁移 | `migrate` service | exit 0 |
| 5 | 后端健康 | `curl -fsS http://localhost:8000/health` | exit 0 |
| 6 | 前端访问 | `curl -fsS http://localhost:3000/` | exit 0 |
| 7 | 停止服务 | `./start-dev.sh docker stop` | 容器停止 |

### 12.2 P1 测试

| # | 场景 | 命令 | 预期 |
|---|---|---|---|
| 1 | 测试部署启动 | `./deploy-docker.sh up` | 生产前端 + 后端启动 |
| 2 | 前端 API 代理 | `curl -I http://localhost:3000/api/health` | 非 502 |
| 3 | 容器重启恢复 | `docker compose restart backend-api` | 后端恢复 healthy |
| 4 | 数据持久化 | 重启 compose | 数据不丢失 |

### 12.3 回归测试

迁移期间每次改动后至少运行：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
docker compose -f docker-compose.yml -f docker-compose.dev.yml build backend-api frontend-dev
```

如果本地资源允许，运行：

```bash
./start-dev.sh docker
```

---

## 13. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 容器内仍使用 `localhost` 访问数据库 | 后端连接失败 | 环境变量统一改为服务名 `postgres`、`redis` |
| 前端 dev proxy 指向 `localhost:8000` | Docker dev 下 API 代理失败 | dev 容器中使用 `backend-api:8000`，宿主机访问通过 Vite |
| Alembic 未执行或失败被忽略 | API 启动后表缺失 | `migrate` service 失败即中断启动 |
| 密钥默认值进入部署环境 | 安全风险 | `deploy-docker.sh` 强校验密钥 |
| 外部 Tableau/MCP 地址在容器内不可达 | Agent 功能失败 | `.env.docker.example` 明确外部 URL；宿主机服务使用 `host.docker.internal` |
| 镜像构建慢 | 开发体验差 | Dockerfile 分层缓存：先复制依赖文件，再复制源码 |
| 本地混合模式和 Docker 模式长期并存 | 维护成本高 | P1 后默认切 Docker，混合模式仅作为兼容参数 |
| Apple Silicon 镜像兼容性 | 部分镜像可能无法拉取或运行 | 默认不强制 amd64；在 `.env.docker` 或 override 中提供 `DOCKER_DEFAULT_PLATFORM=linux/amd64` 兜底 |
| Windows Docker Desktop 路径挂载差异 | 热更新或 volume 行为异常 | 文档明确推荐 WSL2，Windows 原生路径不作为 P0 验收环境 |
| RedBeat 与 worker 混跑 | 定时任务和 worker 相互影响，排障困难 | `celery-worker` 与 `celery-beat` 必须拆分为独立服务 |

---

## 14. Coder 任务拆分

### T1：Backend Dockerfile 标准化

输出：

- 更新 `backend/Dockerfile`。
- 支持 API、migrate、celery worker、celery beat 共用镜像。

验收：

- `docker build -f backend/Dockerfile backend` 成功。

### T2：Frontend Dockerfile + Nginx

输出：

- 新增 `frontend/Dockerfile`。
- 新增 `frontend/nginx.conf`。

验收：

- dev stage 可启动 Vite。
- prod stage 可服务 `out/` 静态文件。

### T3：Compose 重构

输出：

- 更新 `docker-compose.yml`。
- 新增 `docker-compose.dev.yml`。
- 新增 `docker-compose.deploy.yml`。

验收：

- `docker compose ... config` 通过。
- `migrate` 成功后 API 启动。

### T4：启动脚本改造

输出：

- `start-dev.sh docker|docker stop|docker logs|docker restart`。
- `deploy-docker.sh up|down|logs|status`。
- `deploy-test.sh` 改为 deprecated wrapper。

验收：

- 新同事只使用 Docker 和脚本即可启动。

### T5：文档与 CI

输出：

- `.env.docker.example`。
- `docs/deployment/docker.md`。
- README 更新。
- CI Docker 校验。

验收：

- 文档命令能从空环境启动项目。

---

## 15. Tester 验收清单

- [ ] clean machine 只安装 Docker Desktop。
- [ ] clone repo 后复制 `.env.docker.example` 为 `.env.docker`。
- [ ] 填写必要密钥。
- [ ] 执行 `./start-dev.sh docker`。
- [ ] 访问 `http://localhost:3000`。
- [ ] 登录成功。
- [ ] 访问首页问答，能看到 API 响应。
- [ ] 访问技能中心，页面正常。
- [ ] 访问 Agent Monitor，页面正常。
- [ ] 执行 `./start-dev.sh docker stop` 后容器停止。
- [ ] 执行 `./deploy-docker.sh up` 后无需 Python/Node/npm。

---

## 16. 最终交付标准

本迁移完成后，部署说明应简化为：

```bash
git clone <repo>
cd mulan-bi-platform
cp .env.docker.example .env.docker
# edit .env.docker
./deploy-docker.sh up
```

访问：

```text
http://localhost:3000
```

停止：

```bash
./deploy-docker.sh down
```

除 Docker / Docker Compose 外，不要求部署者安装任何项目运行时依赖。
