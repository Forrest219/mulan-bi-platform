#!/usr/bin/env python3
"""
Mulan BI — 种子数据初始化脚本
幂等执行：重复运行不报错、不重复数据

用法（从项目根目录执行）:
    cd backend && python3 ../scripts/seed_demo.py

或（设置必要的环境变量后）:
    python3 scripts/seed_demo.py
"""
import sys
from pathlib import Path

# 添加 backend 路径到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import os
from datetime import datetime, timedelta

# 确保必要环境变量已设置（从 docker-compose 或 .env 读取）
os.environ.setdefault("DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi"))
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", os.environ.get("DATASOURCE_ENCRYPTION_KEY", "dev-datasource-key-for-testing-only-32ch"))


# ============ 数据定义 ============

USERS = [
    {"username": "data_admin1", "password": "test123", "role": "data_admin", "display_name": "数据管理员-测试", "email": "data_admin1@test.local"},
    {"username": "analyst1", "password": "test123", "role": "analyst", "display_name": "分析师-测试", "email": "analyst1@test.local"},
    {"username": "user1", "password": "test123", "role": "user", "display_name": "普通用户-测试", "email": "user1@test.local"},
]

DATASOURCES = [
    {"name": "本地测试库-PostgreSQL", "db_type": "postgresql", "host": "localhost", "port": 5432, "database_name": "mulan_bi", "username": "mulan", "password_raw": "mulan", "extra_config": {"description": "本地 PostgreSQL 测试库"}},
    {"name": "演示MySQL数据源", "db_type": "mysql", "host": "127.0.0.1", "port": 3306, "database_name": "demo_warehouse", "username": "demo_user", "password_raw": "demo_password", "extra_config": {"description": "演示用 MySQL 数据源（需手动配置实际连接）"}},
]

SEMANTIC_FIELDS = [
    {"tableau_field_id": "demo_order_date", "semantic_name": "Order Date", "semantic_name_zh": "订单日期", "unit": None, "semantic_definition": "交易发生的日期"},
    {"tableau_field_id": "demo_order_amount", "semantic_name": "Order Amount", "semantic_name_zh": "订单金额", "unit": "CNY", "semantic_definition": "单笔订单的交易金额"},
    {"tableau_field_id": "demo_customer_region", "semantic_name": "Customer Region", "semantic_name_zh": "客户区域", "unit": None, "semantic_definition": "客户所在地理区域"},
    {"tableau_field_id": "demo_product_name", "semantic_name": "Product Name", "semantic_name_zh": "产品名称", "unit": None, "semantic_definition": "产品的标准名称"},
    {"tableau_field_id": "demo_quantity", "semantic_name": "Quantity", "semantic_name_zh": "销售数量", "unit": "件", "semantic_definition": "订单中的产品数量"},
    {"tableau_field_id": "demo_discount", "semantic_name": "Discount", "semantic_name_zh": "折扣率", "unit": "%", "semantic_definition": "订单适用的折扣百分比"},
    {"tableau_field_id": "demo_profit", "semantic_name": "Profit", "semantic_name_zh": "利润", "unit": "CNY", "semantic_definition": "订单的净利润"},
    {"tableau_field_id": "demo_ship_mode", "semantic_name": "Ship Mode", "semantic_name_zh": "配送方式", "unit": None, "semantic_definition": "订单的物流配送方式"},
    {"tableau_field_id": "demo_category", "semantic_name": "Category", "semantic_name_zh": "产品类别", "unit": None, "semantic_definition": "产品的一级分类"},
    {"tableau_field_id": "demo_sub_category", "semantic_name": "Sub-Category", "semantic_name_zh": "产品子类别", "unit": None, "semantic_definition": "产品的二级分类"},
]

GLOSSARY_TERMS = [
    {"term": "GMV", "canonical_term": "GMV", "definition": "Gross Merchandise Volume，商品交易总额。指一定时间段内的成交总额（含未付款、退款订单）。", "category": "metric", "synonyms": ["商品交易总额", "成交总额"], "formula": "SUM(订单金额)，含取消/退款"},
    {"term": "DAU", "canonical_term": "DAU", "definition": "Daily Active Users，日活跃用户数。当日至少完成一次有效操作的去重用户数。", "category": "metric", "synonyms": ["日活", "日活跃用户"], "formula": "COUNT(DISTINCT user_id) WHERE action_date = today"},
    {"term": "留存率", "canonical_term": "留存率", "definition": "某日新增用户在第 N 日仍然活跃的比例。常见 N=1（次留）、N=7（七留）、N=30（月留）。", "category": "metric", "synonyms": ["Retention Rate", "次日留存", "七日留存"], "formula": "第N日活跃的新用户数 / 第0日新增用户数 × 100%"},
    {"term": "转化率", "canonical_term": "转化率", "definition": "完成目标行为的用户占总访问用户的比例。用于衡量漏斗各环节的转化效率。", "category": "metric", "synonyms": ["Conversion Rate", "CVR"], "formula": "完成目标行为的用户数 / 总访问用户数 × 100%"},
    {"term": "ARPU", "canonical_term": "ARPU", "definition": "Average Revenue Per User，每用户平均收入。衡量单个用户为平台贡献的平均收入。", "category": "metric", "synonyms": ["每用户平均收入", "人均收入"], "formula": "总收入 / 活跃用户数"},
]

SCAN_RECORDS = [
    {"datasource_name": "本地测试库-PostgreSQL", "db_type": "postgresql", "database_name": "mulan_bi", "status": "success", "health_score": 85.5, "total_tables": 18, "total_issues": 5, "high_count": 1, "medium_count": 2, "low_count": 2, "error_message": None, "days_ago": 3},
    {"datasource_name": "本地测试库-PostgreSQL", "db_type": "postgresql", "database_name": "mulan_bi", "status": "success", "health_score": 78.0, "total_tables": 18, "total_issues": 8, "high_count": 2, "medium_count": 3, "low_count": 3, "error_message": None, "days_ago": 7},
    {"datasource_name": "演示MySQL数据源", "db_type": "mysql", "database_name": "demo_warehouse", "status": "failed", "health_score": None, "total_tables": 0, "total_issues": 0, "high_count": 0, "medium_count": 0, "low_count": 0, "error_message": "连接超时：无法连接到 127.0.0.1:3306", "days_ago": 1},
]


# ============ Seed 函数 ============

def seed_users(auth_service):
    """创建测试用户（幂等：已存在则跳过）"""
    for user_spec in USERS:
        result = auth_service.create_user(
            username=user_spec["username"],
            password=user_spec["password"],
            role=user_spec["role"],
            display_name=user_spec["display_name"],
            email=user_spec["email"],
        )
        if result:
            print(f"  + 用户 created: {user_spec['username']} ({user_spec['role']})")
        else:
            print(f"  · 用户 already exists: {user_spec['username']}")


def seed_datasources(db, crypto):
    """创建数据源连接（幂等：通过 name 唯一性检查）"""
    from services.datasources.models import DataSourceDatabase, DataSource

    ds_db = DataSourceDatabase()

    # 先查询已存在的数据源名称
    existing_names = {ds.name for ds in db.query(DataSource).all()}

    owner_id = 1  # 默认管理员 ID

    for ds_spec in DATASOURCES:
        if ds_spec["name"] in existing_names:
            print(f"  · 数据源 already exists: {ds_spec['name']}")
            continue

        encrypted_password = crypto.encrypt(ds_spec["password_raw"])
        ds = ds_db.create(
            db=db,
            name=ds_spec["name"],
            db_type=ds_spec["db_type"],
            host=ds_spec["host"],
            port=ds_spec["port"],
            database_name=ds_spec["database_name"],
            username=ds_spec["username"],
            password_encrypted=encrypted_password,
            owner_id=owner_id,
            extra_config=ds_spec["extra_config"],
        )
        print(f"  + 数据源 created: {ds.name} (id={ds.id})")


def seed_semantic_fields(db):
    """创建语义字段（幂等：基于 tableau_field_id 唯一性）"""
    from services.semantic_maintenance.models import TableauFieldSemantics

    existing_ids = {f.tableau_field_id for f in db.query(TableauFieldSemantics).all()}

    for field_spec in SEMANTIC_FIELDS:
        if field_spec["tableau_field_id"] in existing_ids:
            print(f"  · 语义字段 already exists: {field_spec['tableau_field_id']}")
            continue

        field = TableauFieldSemantics(
            field_registry_id=None,
            connection_id=0,  # demo 固定为 0
            tableau_field_id=field_spec["tableau_field_id"],
            semantic_name=field_spec["semantic_name"],
            semantic_name_zh=field_spec["semantic_name_zh"],
            semantic_definition=field_spec["semantic_definition"],
            unit=field_spec["unit"],
            source="manual",
            status="draft",
            version=1,
        )
        db.add(field)
        db.commit()
        print(f"  + 语义字段 created: {field_spec['tableau_field_id']}")


def seed_glossary(db):
    """创建知识库术语（幂等：基于 canonical_term 唯一性）"""
    from services.knowledge_base.models import KbGlossaryDatabase

    glossary_db = KbGlossaryDatabase()

    # 查询已存在的 canonical_term
    existing_terms = {g.canonical_term for g in db.query(KbGlossary).all()}

    for term_spec in GLOSSARY_TERMS:
        if term_spec["canonical_term"] in existing_terms:
            print(f"  · 术语 already exists: {term_spec['canonical_term']}")
            continue

        glossary_db.create(
            db=db,
            term=term_spec["term"],
            canonical_term=term_spec["canonical_term"],
            definition=term_spec["definition"],
            category=term_spec["category"],
            synonyms=term_spec["synonyms"],
            formula=term_spec.get("formula"),
            source="manual",
        )
        print(f"  + 术语 created: {term_spec['canonical_term']}")


def seed_scan_records(db):
    """创建扫描日志（幂等：检查表记录数 >= 3 则跳过）"""
    from services.health_scan.models import HealthScanRecord

    # 幂等检查：已有 >= 3 条记录则跳过
    count = db.query(HealthScanRecord).count()
    if count >= 3:
        print(f"  · 扫描日志 already seeded ({count} records), skipping")
        return

    for scan_spec in SCAN_RECORDS:
        record = HealthScanRecord(
            datasource_id=0,  # demo 固定为 0
            datasource_name=scan_spec["datasource_name"],
            db_type=scan_spec["db_type"],
            database_name=scan_spec["database_name"],
            status=scan_spec["status"],
            health_score=scan_spec["health_score"],
            total_tables=scan_spec["total_tables"],
            total_issues=scan_spec["total_issues"],
            high_count=scan_spec["high_count"],
            medium_count=scan_spec["medium_count"],
            low_count=scan_spec["low_count"],
            error_message=scan_spec["error_message"],
            created_at=datetime.now() - timedelta(days=scan_spec["days_ago"]),
        )
        db.add(record)
    db.commit()
    print(f"  + 扫描日志 seeded ({len(SCAN_RECORDS)} records)")


# ============ Main ============

def main():
    print("=" * 50)
    print("Mulan BI — 种子数据初始化")
    print("=" * 50)

    from app.core.database import get_db_context
    from app.core.crypto import get_datasource_crypto
    from services.auth.service import AuthService

    crypto = get_datasource_crypto()
    auth_service = AuthService()

    with get_db_context() as db:
        print("\n[1/5] 创建测试用户...")
        seed_users(auth_service)

        print("\n[2/5] 创建数据源连接...")
        seed_datasources(db, crypto)

        print("\n[3/5] 创建语义字段...")
        seed_semantic_fields(db)

        print("\n[4/5] 创建知识库术语...")
        seed_glossary(db)

        print("\n[5/5] 创建扫描日志...")
        seed_scan_records(db)

    print("\n" + "=" * 50)
    print("✅ 种子数据初始化完成")
    print("=" * 50)
    print("\n测试账号（密码均为 test123）:")
    print("  - data_admin1  (数据管理员)")
    print("  - analyst1     (分析师)")
    print("  - user1        (普通用户)")
    print("\n注意：admin 账号由后端启动时自动创建")


if __name__ == "__main__":
    main()