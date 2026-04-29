"""单元测试：Webhook URL 校验器（SSRF 防护）"""
import pytest
from services.events.channels.url_validator import validate, _is_ip_private


class TestIsIpPrivate:
    """测试私网 IP 段判断"""

    @pytest.mark.parametrize("ip", [
        "127.0.0.1", "127.255.255.255",  # 127.0.0.0/8
        "10.0.0.1", "10.255.255.255",    # 10.0.0.0/8
        "172.16.0.1", "172.31.255.255",  # 172.16.0.0/12
        "192.168.0.1", "192.168.255.255",  # 192.168.0.0/16
        "169.254.0.1", "169.254.255.255",  # 169.254.0.0/16
        "::1",  # loopback IPv6
    ])
    def test_private_ips(self, ip):
        assert _is_ip_private(ip) is True

    @pytest.mark.parametrize("ip", [
        "8.8.8.8", "1.1.1.1", "54.240.162.1",  # public IPs
    ])
    def test_public_ips(self, ip):
        assert _is_ip_private(ip) is False


class TestUrlValidator:
    """测试 URL 安全校验"""

    def test_https_url_accepted(self):
        """合法 https URL"""
        validate("https://example.com/webhook")

    def test_http_localhost_allowed(self):
        """开发环境 http://localhost 允许"""
        validate("http://localhost/webhook")

    def test_http_non_localhost_rejected(self):
        """非 localhost 的 http URL 拒绝"""
        with pytest.raises(ValueError, match="EVT_011"):
            validate("http://example.com/webhook")

    def test_non_https_rejected(self):
        """非 https 协议拒绝"""
        with pytest.raises(ValueError, match="EVT_011"):
            validate("ftp://example.com/webhook")

    def test_localhost_rejected(self):
        """localhost hostname 拒绝"""
        with pytest.raises(ValueError, match="EVT_011"):
            validate("https://localhost/webhook")

    def test_private_ip_rejected(self):
        """私网 IP URL 拒绝"""
        with pytest.raises(ValueError, match="EVT_011"):
            validate("https://192.168.1.1/webhook")

        with pytest.raises(ValueError, match="EVT_011"):
            validate("https://10.0.0.1/webhook")

    def test_url_without_hostname_rejected(self):
        """缺少 hostname 的 URL 拒绝"""
        with pytest.raises(ValueError, match="EVT_011"):
            validate("https:///webhook")