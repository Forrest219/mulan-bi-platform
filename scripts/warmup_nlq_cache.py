#!/usr/bin/env python3
"""
NLQ 缓存预热脚本 — 防止冷启动 N+1 查询风暴

Spec 14 v1.1 §7.1 问题：
BI 平台重启后，若高并发查询瞬间涌入，
Redis 缓存为空 → 所有请求穿透到 PG 做 N+1 跨表查询 → DB 打满。

本脚本在服务启动时（或 CI 部署流水线的最后一步）预填充 Redis 缓存：
    1. 遍历所有 Tableau 数据源
    2. 查询其字段列表（field_caption / field_name）
    3. 写入 Redis（TTL 1小时）

用法：
    # 常规部署
    python scripts/warmup_nlq_cache.py

    # 验证模式（不写入）
    python scripts/warmup_nlq_cache.py --dry-run

    # 仅预热指定 datasource_luid
    python scripts/warmup_nlq_cache.py --luid "ABC123XYZ"

CI 集成（.github/workflows/ci.yml 或部署脚本末尾）：
    python scripts/warmup_nlq_cache.py
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://mulan:mulan@localhost:5432/mulan_bi",
)
os.environ["DATABASE_URL"] = DATABASE_URL


def warmup_all(specific_luid: str = None, dry_run: bool = True) -> dict:
    """
    预热所有 NLQ 字段缓存。

    Returns:
        {
            "total": int,
            "cached": int,
            "skipped": int,
            "errors": int,
            "duration_seconds": float,
            "details": [(datasource_name, asset_id, field_count | error), ...]
        }
    """
    from services.tableau.models import TableauDatabase, TableauAsset, TableauDatasourceField
    from services.common.redis_cache import cache_datasource_fields, get_redis_client

    start = time.time()
    results = {
        "total": 0,
        "cached": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    redis_client = get_redis_client()
    if redis_client is None and not dry_run:
        print("ERROR: Redis 不可用，请检查 CELERY_BROKER_URL 环境变量")
        results["errors"] += 1
        return results

    db = TableauDatabase()
    session = db.session

    try:
        query = session.query(TableauAsset).filter(
            TableauAsset.is_deleted == False,
            TableauAsset.asset_type == "datasource",
        )
        if specific_luid:
            query = query.filter(TableauAsset.datasource_luid == specific_luid)

        assets = query.all()
        results["total"] = len(assets)
        print(f"找到 {len(assets)} 个数据源资产")

        for asset in assets:
            try:
                fields = session.query(TableauDatasourceField).filter(
                    TableauDatasourceField.asset_id == asset.id
                ).all()

                field_captions = [
                    f.field_caption or f.field_name
                    for f in fields
                    if f.field_caption or f.field_name
                ]

                if not field_captions:
                    results["skipped"] += 1
                    results["details"].append((asset.name, asset.id, "SKIP: 无字段"))
                    continue

                if dry_run:
                    results["details"].append((asset.name, asset.id, f"DRY: {len(field_captions)} 字段"))
                else:
                    ok = cache_datasource_fields(asset.id, field_captions)
                    status = "OK" if ok else "REDIS_FAIL"
                    results["details"].append((asset.name, asset.id, f"{status}: {len(field_captions)} 字段"))
                    if ok:
                        results["cached"] += 1
                    else:
                        results["errors"] += 1

            except Exception as e:
                results["errors"] += 1
                results["details"].append((asset.name, asset.id, f"ERROR: {e}"))

    finally:
        session.close()

    results["duration_seconds"] = round(time.time() - start, 2)
    return results


def main():
    parser = argparse.ArgumentParser(description="NLQ 缓存预热脚本")
    parser.add_argument("--luid", help="仅预热指定 datasource_luid")
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="验证模式（默认 True，不写入 Redis）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("NLQ 缓存预热脚本")
    print("=" * 60)
    print(f"模式: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"数据库: {DATABASE_URL}")
    print()

    results = warmup_all(specific_luid=args.luid, dry_run=args.dry_run)

    print(f"\n汇总:")
    print(f"  总数据源:   {results['total']}")
    print(f"  预热成功:   {results['cached']}")
    print(f"  跳过（空）: {results['skipped']}")
    print(f"  错误:       {results['errors']}")
    print(f"  耗时:       {results['duration_seconds']}s")

    print(f"\n详情:")
    for name, asset_id, status in results["details"]:
        print(f"  [{status}] asset_id={asset_id} name={name}")

    if args.dry_run:
        print("\n✅ DRY-RUN 完成，以上是预判结果。")
        print("   若确认无误，去掉 --dry-run 参数重新执行。")
    else:
        if results["errors"] == 0:
            print(f"\n✅ 预热完成，{results['cached']} 个数据源缓存已就绪。")
        else:
            print(f"\n⚠️ 预热完成，但有 {results['errors']} 个错误，请检查 Redis 连接。")
            sys.exit(1)


if __name__ == "__main__":
    main()
