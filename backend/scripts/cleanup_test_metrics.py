#!/usr/bin/env python3
"""Clean Metrics Agent test data from a local/dev database.

Default mode is dry-run:

    cd backend
    python scripts/cleanup_test_metrics.py

Execute cleanup:

    cd backend
    python scripts/cleanup_test_metrics.py --execute

The script intentionally targets only known test/verification naming patterns
and deletes related metric records in dependency-safe order.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Sequence
from urllib.parse import urlparse

from sqlalchemy import create_engine, text


DEFAULT_DATABASE_URL = "postgresql://mulan:mulan@localhost:5432/mulan_bi"

TEST_NAME_PATTERNS = (
    "test_metric_%",
    "test_lineage_metric_%",
    "cons_metric_%",
    "svc_test_metric_%",
    "anomaly_test_metric_%",
    "dup_metric_%",
    "draft_metric_%",
    "pending_metric_%",
    "保存验证%",
    "UI内嵌保存验证%",
    "Inline保存验证%",
    "UI测试利润金额%",
    "测试利润金额%",
)

TEST_EXACT_NAMES = (
    "test_metric_type",
)

TEST_EXACT_ZH_NAMES = (
    "测试血缘指标",
)

DEPENDENT_TABLES = (
    ("bi_metric_dependencies", "metric_id = :id OR depends_on_metric_id = :id"),
    ("bi_metric_aliases", "metric_id = :id"),
    ("bi_metric_bindings", "metric_id = :id"),
    ("bi_metric_versions", "metric_id = :id"),
    ("bi_metric_lineage", "metric_id = :id"),
    ("bi_metric_anomalies", "metric_id = :id"),
    ("bi_metric_consistency_checks", "metric_id = :id"),
)


@dataclass(frozen=True)
class MetricCandidate:
    id: str
    metric_code: str | None
    name: str | None
    name_zh: str | None
    metric_type: str | None
    created_at: str | None


def _database_name(database_url: str) -> str:
    parsed = urlparse(database_url)
    return parsed.path.rsplit("/", 1)[-1] if parsed.path else ""


def _assert_safe_database_url(database_url: str, allow_non_local: bool) -> None:
    parsed = urlparse(database_url)
    db_name = _database_name(database_url)
    host = parsed.hostname or ""
    local_hosts = {"", "localhost", "127.0.0.1", "::1"}

    if db_name in {"postgres", "template0", "template1"}:
        raise RuntimeError(f"Refusing to clean system database: {database_url}")

    if not allow_non_local and host not in local_hosts:
        raise RuntimeError(
            "Refusing to clean a non-local database. "
            "Pass --allow-non-local only after confirming the target is safe."
        )


def _load_candidates(engine, tenant_id: str | None = None) -> list[MetricCandidate]:
    tenant_filter = "AND tenant_id = :tenant_id" if tenant_id else ""
    query = text(
        f"""
        SELECT id, metric_code, name, name_zh, metric_type, created_at
        FROM bi_metric_definitions
        WHERE (
               name LIKE ANY(:patterns)
            OR name_zh LIKE ANY(:patterns)
            OR name = ANY(:exact_names)
            OR name_zh = ANY(:exact_zh_names)
        )
        {tenant_filter}
        ORDER BY created_at DESC NULLS LAST, metric_code DESC NULLS LAST, id
        """
    )
    params = {
        "patterns": list(TEST_NAME_PATTERNS),
        "exact_names": list(TEST_EXACT_NAMES),
        "exact_zh_names": list(TEST_EXACT_ZH_NAMES),
    }
    if tenant_id:
        params["tenant_id"] = tenant_id
    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        MetricCandidate(
            id=str(row.id),
            metric_code=row.metric_code,
            name=row.name,
            name_zh=row.name_zh,
            metric_type=row.metric_type,
            created_at=str(row.created_at) if row.created_at else None,
        )
        for row in rows
    ]


def _delete_candidates(engine, candidates: Sequence[MetricCandidate]) -> None:
    with engine.begin() as conn:
        for candidate in candidates:
            params = {"id": candidate.id}
            for table_name, predicate in DEPENDENT_TABLES:
                conn.execute(text(f"DELETE FROM {table_name} WHERE {predicate}"), params)
            conn.execute(text("DELETE FROM bi_metric_definitions WHERE id = :id"), params)


def _print_candidates(candidates: Sequence[MetricCandidate]) -> None:
    if not candidates:
        print("No Metrics Agent test data found.")
        return
    print(f"Found {len(candidates)} Metrics Agent test metric(s):")
    for metric in candidates:
        print(
            "\t".join(
                [
                    metric.id,
                    metric.metric_code or "",
                    metric.name or "",
                    metric.name_zh or "",
                    metric.metric_type or "",
                    metric.created_at or "",
                ]
            )
        )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
        help="Target database URL. Defaults to DATABASE_URL or local mulan_bi.",
    )
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Optional tenant UUID filter.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete matched records. Omit for dry-run.",
    )
    parser.add_argument(
        "--allow-non-local",
        action="store_true",
        help="Allow cleanup against a non-local host after explicit confirmation.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    _assert_safe_database_url(args.database_url, args.allow_non_local)

    engine = create_engine(args.database_url)
    candidates = _load_candidates(engine, tenant_id=args.tenant_id)
    _print_candidates(candidates)

    if not args.execute:
        print("Dry-run only. Re-run with --execute to delete matched records.")
        return 0

    _delete_candidates(engine, candidates)
    print(f"Deleted {len(candidates)} Metrics Agent test metric(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
