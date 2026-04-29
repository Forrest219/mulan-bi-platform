"""Webhook URL 安全校验器（SSRF 防护）"""
import ipaddress
import socket
from typing import List

# 禁止的 IP 段（私网 / link-local / loopback）
PRIVATE_NETWORKS: List[str] = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1",
    "fc00::/7",
]


def _is_ip_private(ip_str: str) -> bool:
    """检查 IP 是否落在禁止段"""
    try:
        ip = ipaddress.ip_address(ip_str)
        for net_str in PRIVATE_NETWORKS:
            net = ipaddress.ip_network(net_str, strict=False)
            if ip in net:
                return True
    except ValueError:
        return False
    return False


def validate(url: str) -> None:
    """
    校验 Webhook URL，合法时返回 None，非法时抛 EVT_011。

    规则：
    - 协议必须为 https://（开发环境允许 http://localhost）
    - hostname DNS 解析后所有 IP 不得命中私网段
    - DNS 必须可解析
    - 不允许为内网 hostname（如 localhost）
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)

    # 协议校验
    if parsed.scheme not in ("https", "http"):
        raise ValueError("EVT_011: URL 协议必须为 https:// 或 http://localhost")

    # 开发环境允许 http://localhost，生产强制 https
    if parsed.scheme == "http" and parsed.hostname != "localhost":
        raise ValueError("EVT_011: 非 localhost URL 必须使用 https://")

    if not parsed.hostname:
        raise ValueError("EVT_011: URL 缺少 hostname")

    hostname = parsed.hostname.lower()

    # 禁止 localhost（精确匹配 + 大小写不敏感）
    if hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("EVT_011: 禁止使用 localhost 作为 Webhook 地址")

    # DNS 解析并检查 IP 段
    try:
        all_ips = set()
        # 同时解析 IPv4 和 IPv6
        try:
            infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
            for info in infos:
                all_ips.add(info[4][0])
        except socket.gaierror:
            raise ValueError("EVT_011: URL hostname DNS 不可解析")

        if not all_ips:
            raise ValueError("EVT_011: URL hostname DNS 解析无 IP")

        for ip_str in all_ips:
            if _is_ip_private(ip_str):
                raise ValueError(f"EVT_011: URL 解析 IP {ip_str} 命中私网段")
    except ValueError:
        raise
    except Exception:
        raise ValueError("EVT_011: URL hostname DNS 解析失败")