#!/bin/bash
cd /Users/zhangxingchen/Documents/Claude\ code\ projects/mulan-bi-platform/backend
source .env
exec uvicorn app.main:app --reload --port 8000
