#!/bin/bash
# 后端启动脚本 — 自动从项目根目录 .env 加载环境变量
cd /Users/zhangxingchen/Documents/Claude\ code\ projects/mulan-bi-platform
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
# 修正 DATABASE_URL 密码（docker-compose 用 admin123）
DATABASE_URL="postgresql://mulan:mulan@localhost:5432/mulan_bi"
JWT_SECRET="${JWT_SECRET:-test-jwt-secret-for-service-auth-32ch}"
SERVICE_JWT_SECRET="${SERVICE_JWT_SECRET:-test-jwt-secret-for-service-auth-32ch}"
SESSION_SECRET="${SESSION_SECRET:-change-me-in-production-32chars!!}"
export DATABASE_URL JWT_SECRET SERVICE_JWT_SECRET SESSION_SECRET
cd /Users/zhangxingchen/Documents/Claude\ code\ projects/mulan-bi-platform/backend
source .venv/bin/activate
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
