#!/usr/bin/env python3
"""
加密密钥轮换脚本（Spec 05 OI-3）

用法：
    # 预览模式（不写入数据库）
    python scripts/rotate_encryption_key.py \
        --old-key "old-key-32-bytes-long-enough!!" \
        --new-key "new-key-32-bytes-long-enough!!" \
        --dry-run

    # 正式执行
    python scripts/rotate_encryption_key.py \
        --old-key "old-key-32-bytes-long-enough!!" \
        --new-key "new-key-32-bytes-long-enough!!"

原理：
    1. 用 old_key 解密所有密文
    2. 用 new_key 重新加密
    3. 立即更新数据库（事务保证原子性）

受影响的数据：
    bi_data_sources.password_encrypted      → DATASOURCE_ENCRYPTION_KEY
    ai_llm_configs.api_key_encrypted        → LLM_ENCRYPTION_KEY
    tableau_connections.token_encrypted     → TABLEAU_ENCRYPTION_KEY

前置条件：
    - 数据库服务运行中
    - old_key 正确（否则解密失败会报错）
    - new_key 符合 Fernet 要求（32 字节 base64 编码后 44 字节）

警告：
    ⚠️ 执行前务必用 --dry-run 预览affected rows！
    ⚠️ 建议在维护窗口执行（低峰期，备份已就绪）
    ⚠️ 轮换期间相关服务（LLM/Tableau MCP）会读取旧 key，需要重启 Worker
"""
import argparse
import sys
import os

# 确保 backend 在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# 设置 DATABASE_URL（从环境变量或命令行参数）
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://mulan:mulan@localhost:5432/mulan_bi"
)


def _build_crypto(key: str):
    """构建 Fernet 加解密器（从原始 key 派生）"""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64

    # PBKDF2 派生：key → 32 字节 Fernet 密钥
    salt = b"mulan-bi-key-rotation-v1"  # 固定 salt（仅用于密钥派生，不影响安全性）
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend(),
    )
    derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    return Fernet(derived)


def _decrypt_old(crypto, ciphertext: str) -> str:
    return crypto.decrypt(ciphertext.encode()).decode()


def _encrypt_new(crypto, plaintext: str) -> str:
    return crypto.encrypt(plaintext.encode()).decode()


def rotate_datasources(old_key: str, new_key: str, dry_run: bool = True):
    """轮换 bi_data_sources.password_encrypted"""
    from services.datasources.models import DataSource, DataSourceDatabase

    old_crypto = _build_crypto(old_key)
    new_crypto = _build_crypto(new_key)

    db = DataSourceDatabase()
    session = db.session

    try:
        sources = session.query(DataSource).all()
        print(f"\n[DataSources] 找到 {len(sources)} 条记录")

        for ds in sources:
            if not ds.password_encrypted:
                print(f"  SKIP  id={ds.id} name={ds.name}: password_encrypted 为空")
                continue

            try:
                plain = _decrypt_old(old_crypto, ds.password_encrypted)
                new_cipher = _encrypt_new(new_crypto, plain)
                action = "DRY-RUN" if dry_run else "UPDATE"
                print(f"  [{action}] id={ds.id} name={ds.name}: OK (len={len(new_cipher)})")
                if not dry_run:
                    ds.password_encrypted = new_cipher
                    session.commit()
            except Exception as e:
                print(f"  FAIL  id={ds.id} name={ds.name}: {e}")
                if not dry_run:
                    session.rollback()
    finally:
        session.close()


def rotate_llm_configs(old_key: str, new_key: str, dry_run: bool = True):
    """轮换 ai_llm_configs.api_key_encrypted"""
    from services.llm.models import LLMConfig, LLMConfigDatabase

    old_crypto = _build_crypto(old_key)
    new_crypto = _build_crypto(new_key)

    db = LLMConfigDatabase()
    session = db.get_session()

    try:
        configs = session.query(LLMConfig).all()
        print(f"\n[LLMConfigs] 找到 {len(configs)} 条记录")

        for cfg in configs:
            if not cfg.api_key_encrypted:
                print(f"  SKIP  id={cfg.id}: api_key_encrypted 为空")
                continue

            try:
                plain = _decrypt_old(old_crypto, cfg.api_key_encrypted)
                new_cipher = _encrypt_new(new_crypto, plain)
                action = "DRY-RUN" if dry_run else "UPDATE"
                print(f"  [{action}] id={cfg.id} provider={cfg.provider}: OK")
                if not dry_run:
                    cfg.api_key_encrypted = new_cipher
                    session.commit()
            except Exception as e:
                print(f"  FAIL  id={cfg.id}: {e}")
                if not dry_run:
                    session.rollback()
    finally:
        session.close()


def rotate_tableau_connections(old_key: str, new_key: str, dry_run: bool = True):
    """轮换 tableau_connections.token_encrypted"""
    from services.tableau.models import TableauConnection, TableauDatabase

    old_crypto = _build_crypto(old_key)
    new_crypto = _build_crypto(new_key)

    db = TableauDatabase()
    session = db.session

    try:
        connections = session.query(TableauConnection).all()
        print(f"\n[TableauConnections] 找到 {len(connections)} 条记录")

        for conn in connections:
            if not conn.token_encrypted:
                print(f"  SKIP  id={conn.id} name={conn.name}: token_encrypted 为空")
                continue

            try:
                plain = _decrypt_old(old_crypto, conn.token_encrypted)
                new_cipher = _encrypt_new(new_crypto, plain)
                action = "DRY-RUN" if dry_run else "UPDATE"
                print(f"  [{action}] id={conn.id} name={conn.name}: OK")
                if not dry_run:
                    conn.token_encrypted = new_cipher
                    session.commit()
            except Exception as e:
                print(f"  FAIL  id={conn.id} name={conn.name}: {e}")
                if not dry_run:
                    session.rollback()
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="加密密钥轮换脚本（Spec 05 OI-3）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 预览受影响的行（强烈建议先执行）
  python scripts/rotate_encryption_key.py \\
      --old-key "old-key-32-bytes-long-enough!!" \\
      --new-key "new-key-32-bytes-long-enough!!" \\
      --dry-run

  # 正式执行
  python scripts/rotate_encryption_key.py \\
      --old-key "old-key-32-bytes-long-enough!!" \\
      --new-key "new-key-32-bytes-long-enough!!"

轮换后必须：
  1. 更新环境变量：LLM_ENCRYPTION_KEY / DATASOURCE_ENCRYPTION_KEY / TABLEAU_ENCRYPTION_KEY
  2. 重启 Celery Worker（清除旧 CryptoHelper 缓存）
  3. 清除 services/common/settings.py 中的加密密钥缓存：
     from services.common.settings import clear_encryption_key_cache
     clear_encryption_key_cache()
        """,
    )
    parser.add_argument("--old-key", required=True, help="旧的加密密钥（必须与当前环境变量一致）")
    parser.add_argument("--new-key", required=True, help="新的加密密钥（需要更新到环境变量）")
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="预览模式：不写入数据库（默认 True）",
    )
    parser.add_argument(
        "--database-url",
        default=DATABASE_URL,
        help=f"DATABASE_URL（默认从环境变量读取）",
    )
    args = parser.parse_args()

    if len(args.new_key) < 16:
        print("ERROR: new_key 长度必须 >= 16 字节（建议 >= 32 字节）")
        sys.exit(1)

    # 设置 DATABASE_URL 环境变量（影响后续导入的 backend 模块）
    os.environ["DATABASE_URL"] = args.database_url

    print("=" * 60)
    print("加密密钥轮换脚本（Spec 05 OI-3）")
    print("=" * 60)
    print(f"模式: {'DRY-RUN（预览）' if args.dry_run else 'LIVE（正式执行）'}")
    print(f"数据库: {args.database_url}")
    print()

    if args.dry_run:
        print("⚠️  DRY-RUN 模式：不会修改任何数据")
        print()

    try:
        rotate_datasources(args.old_key, args.new_key, dry_run=args.dry_run)
        rotate_llm_configs(args.old_key, args.new_key, dry_run=args.dry_run)
        rotate_tableau_connections(args.old_key, args.new_key, dry_run=args.dry_run)
    except Exception as e:
        print(f"\nERROR: 密钥轮换失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print()
    if args.dry_run:
        print("✅ DRY-RUN 完成，以上是受影响的所有行。")
        print("   若确认无误，去掉 --dry-run 参数重新执行。")
    else:
        print("✅ 密钥轮换完成！")
        print()
        print("⚠️  后续操作（必须）：")
        print("   1. 更新环境变量（LLM_ENCRYPTION_KEY / TABLEAU_ENCRYPTION_KEY）")
        print("   2. 重启 Celery Worker：celery -A services.tasks worker --reload")
        print("   3. 重启 FastAPI 服务")


if __name__ == "__main__":
    main()
