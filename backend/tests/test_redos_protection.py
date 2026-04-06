"""
ReDoS 攻击压测：验证 regex 模块原生 timeout 在高并发场景下能否在 200ms 内准确熔断

测试目标：
1. 验证恶意正则（指数级回溯）在 200ms 内被 regex 模块中断
2. 验证高并发（100 并发）下超时机制仍然有效
3. 验证正常 DDL 解析不受影响
"""

import pytest
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple


# ReDoS 深度防护：使用 regex 模块（支持原生 timeout）
try:
    import regex as re_module
    _HAS_REGEX_MODULE = True
except ImportError:
    _HAS_REGEX_MODULE = False

# 回退到标准 re 模块（无超时保护）
import re as std_re

REGEX_TIMEOUT_SEC = 0.2  # 200ms


class RegexTimeoutError(Exception):
    """正则匹配超时异常"""
    pass


def _match_with_timeout(pattern: str, text: str) -> Tuple[bool, str, float]:
    """
    带超时的正则匹配（使用 regex 模块原生 timeout）

    Returns:
        (success, result_or_error, elapsed_ms)
    """
    start = time.time()

    if _HAS_REGEX_MODULE:
        _re = re_module
    else:
        _re = std_re

    try:
        if _HAS_REGEX_MODULE:
            result = _re.search(pattern, text, timeout=REGEX_TIMEOUT_SEC)
        else:
            # 无 timeout 支持的标准 re 模块（仅用于测试环境检查）
            result = _re.search(pattern, text)
        elapsed_ms = (time.time() - start) * 1000
        return True, "matched" if result else "no_match", elapsed_ms
    except TimeoutError:
        elapsed_ms = (time.time() - start) * 1000
        return False, "timeout", elapsed_ms
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return False, f"error: {e}", elapsed_ms


# === 恶意正则模式（指数级回溯）===

EVIL_PATTERNS = [
    # 经典 ReDoS: (a+)+
    (r"(a+)+$", "aaa" * 10 + "!"),

    # 嵌套重复
    (r"(\w+\s*)+$", "word " * 20 + "!"),

    # 交替嵌套
    (r"([a-zA-Z]+[0-9]+)+$", "word123word456word789" * 5 + "!"),

    # 贪婪 + 逆向查找
    (r".*?(a|b|c)+$", "x" * 30 + "!"),

    # 复杂字符类 + 量词
    (r"([\w\d]+[\W\D]*)+$", "word123!@#" * 10 + "!"),
]


# === 正常 DDL（应正常解析）===

NORMAL_DDLS = [
    "CREATE TABLE dim_user (id BIGINT PRIMARY KEY, user_name VARCHAR(128));",
    "CREATE TABLE fact_orders (order_id BIGINT, amount DECIMAL(10,2));",
    "CREATE TABLE IF NOT EXISTS ods_source (id INT, data TEXT);",
]


@pytest.mark.skipif(not _HAS_REGEX_MODULE, reason="regex 模块未安装")
class TestReDoSProtection:
    """ReDoS 防护测试套件（使用 regex 模块 native timeout）"""

    def test_evil_patterns_timeout(self):
        """测试恶意正则模式在 200ms 内被中断"""
        print("\n=== 测试恶意正则超时 ===")

        for pattern, text in EVIL_PATTERNS:
            success, result, elapsed_ms = _match_with_timeout(pattern, text)

            print(f"  Pattern: {pattern[:40]}...")
            print(f"  Text len: {len(text)}, Result: {result}, Time: {elapsed_ms:.1f}ms")

            assert result == "timeout", f"Pattern should timeout but got: {result}"
            assert elapsed_ms <= REGEX_TIMEOUT_SEC * 1000 + 50, f"Timeout took too long: {elapsed_ms}ms"

    def test_normal_ddl_not_affected(self):
        """测试正常 DDL 解析不受超时机制影响"""
        print("\n=== 测试正常 DDL 不受影响 ===")

        for ddl in NORMAL_DDLS:
            pattern = r"CREATE\s+TABLE\s+"
            success, result, elapsed_ms = _match_with_timeout(pattern, ddl)

            print(f"  DDL: {ddl[:50]}...")
            print(f"  Result: {result}, Time: {elapsed_ms:.1f}ms")

            assert result == "matched", f"Normal DDL should match but got: {result}"
            assert elapsed_ms < REGEX_TIMEOUT_SEC * 1000, f"Normal match took too long: {elapsed_ms}ms"

    def test_concurrent_redos_attempts(self):
        """测试高并发 ReDoS 攻击（100 并发）"""
        print("\n=== 测试高并发 ReDoS（100 并发）===")

        pattern, text = EVIL_PATTERNS[0]  # 使用第一个恶意模式

        def attack() -> Tuple[bool, str, float]:
            return _match_with_timeout(pattern, text)

        timeout_count = 0
        error_count = 0
        total_time = 0

        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = [executor.submit(attack) for _ in range(100)]

            for future in as_completed(futures):
                success, result, elapsed = future.result()
                total_time += elapsed
                if result == "timeout":
                    timeout_count += 1
                elif "error" in result:
                    error_count += 1

        avg_time = total_time / 100

        print(f"  Total attempts: 100")
        print(f"  Timeouts: {timeout_count}")
        print(f"  Errors: {error_count}")
        print(f"  Average time: {avg_time:.1f}ms")

        # 至少 95% 应该超时
        assert timeout_count >= 95, f"Expected >=95 timeouts but got {timeout_count}"
        # 不应该有错误
        assert error_count == 0, f"Too many errors: {error_count}"

    def test_rapid_fire_attacks(self):
        """测试快速连续攻击（模拟高 QPS）"""
        print("\n=== 测试快速连续攻击（200 QPS）===")

        pattern, text = EVIL_PATTERNS[0]
        results = []
        timeouts = 0

        start_total = time.time()

        for i in range(200):
            success, result, elapsed_ms = _match_with_timeout(pattern, text)
            results.append((success, result, elapsed_ms))
            if result == "timeout":
                timeouts += 1

        elapsed_total = time.time() - start_total

        print(f"  Total attempts: 200")
        print(f"  Timeouts: {timeouts}")
        print(f"  Total time: {elapsed_total:.2f}s")
        print(f"  QPS: {200/elapsed_total:.1f}")
        print(f"  Timeout rate: {timeouts/200*100:.1f}%")

        # 高 QPS 下仍然应该大部分超时
        assert timeouts >= 150, f"Expected >=150 timeouts but got {timeouts}"

    def test_mixed_normal_and_evil(self):
        """测试混合场景：正常请求与恶意请求交错"""
        print("\n=== 测试混合场景 ===")

        tasks = []
        # 10 个正常请求 + 10 个恶意请求
        for i in range(10):
            tasks.append(("normal", NORMAL_DDLS[i % len(NORMAL_DDLS)]))
            tasks.append(("evil", EVIL_PATTERNS[i % len(EVIL_PATTERNS)][1]))

        def mixed_task(task_type_and_data):
            task_type, data = task_type_and_data
            if task_type == "normal":
                pattern = r"CREATE\s+TABLE\s+\w+"
            else:
                pattern = EVIL_PATTERNS[0][0]

            success, result, elapsed_ms = _match_with_timeout(pattern, data)
            return task_type, success, result, elapsed_ms

        normal_ok = 0
        evil_timeout = 0

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(mixed_task, t) for t in tasks]

            for future in as_completed(futures):
                task_type, success, result, elapsed = future.result()
                if task_type == "normal" and result == "matched":
                    normal_ok += 1
                elif task_type == "evil" and result == "timeout":
                    evil_timeout += 1

        print(f"  Normal requests OK: {normal_ok}/10")
        print(f"  Evil requests timeout: {evil_timeout}/10")

        assert normal_ok == 10, f"Expected all normal requests to succeed but got {normal_ok}"
        assert evil_timeout >= 8, f"Expected most evil requests to timeout but got {evil_timeout}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
