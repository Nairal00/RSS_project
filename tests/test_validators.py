"""Tests for validators: is_private_url and DNS rebinding protection."""

from unittest.mock import patch

import pytest

from validators import is_private_url


# ---------------------------------------------------------------------------
# is_private_url
# ---------------------------------------------------------------------------


class TestIsPrivateUrl:
    def test_localhost(self):
        assert is_private_url('http://localhost/feed') is True

    def test_127(self):
        assert is_private_url('http://127.0.0.1/feed') is True

    def test_10_x(self):
        assert is_private_url('http://10.0.0.1/feed') is True

    def test_172_private(self):
        assert is_private_url('http://172.16.0.1/feed') is True

    def test_192_168(self):
        assert is_private_url('http://192.168.1.1/feed') is True

    def test_link_local(self):
        assert is_private_url('http://169.254.1.1/feed') is True

    def test_ipv6_loopback(self):
        assert is_private_url('http://[::1]/feed') is True

    def test_public_ip(self):
        assert is_private_url('https://example.com/feed') is False

    def test_public_domain(self):
        assert is_private_url('https://openai.com/blog/rss.xml') is False

    def test_ipv4_mapped_ipv6_loopback(self):
        """::ffff:127.0.0.1 is an IPv4-mapped loopback — must be blocked."""
        assert is_private_url('http://[::ffff:127.0.0.1]/feed') is True

    def test_ipv4_mapped_ipv6_private(self):
        """::ffff:192.168.1.1 is an IPv4-mapped private address — must be blocked."""
        assert is_private_url('http://[::ffff:192.168.1.1]/feed') is True

    def test_ipv6_link_local(self):
        assert is_private_url('http://[fe80::1]/feed') is True

    def test_ipv6_ula(self):
        assert is_private_url('http://[fd00::1]/feed') is True

    def test_unspecified_ipv4(self):
        assert is_private_url('http://0.0.0.0/feed') is True

    def test_localhost_uppercase(self):
        assert is_private_url('http://LOCALHOST/feed') is True

    def test_172_boundary_public(self):
        """172.15.x.x is NOT in the 172.16.0.0/12 private range."""
        assert is_private_url('http://172.15.0.1/feed') is False

    def test_empty_url_treated_as_private(self):
        """Empty string has no hostname — must be treated as private."""
        assert is_private_url('') is True

    @pytest.mark.parametrize('url', [
        'http://127.0.0.1/feed',
        'http://127.255.255.255/feed',
        'http://10.0.0.1/feed',
        'http://10.255.255.255/feed',
        'http://172.16.0.1/feed',
        'http://172.31.255.255/feed',
        'http://192.168.0.1/feed',
        'http://169.254.1.1/feed',
        'http://0.0.0.0/feed',
        'http://[::1]/feed',
        'http://[fe80::1]/feed',
        'http://[fd00::1]/feed',
        'http://[::ffff:127.0.0.1]/feed',
        'http://[::ffff:10.0.0.1]/feed',
        'http://localhost/feed',
        'http://LOCALHOST/feed',
    ])
    def test_all_private_addresses_blocked(self, url):
        assert is_private_url(url) is True


# ---------------------------------------------------------------------------
# is_private_url — urlparse exception path
# ---------------------------------------------------------------------------


class TestIsPrivateUrlException:
    def test_urlparse_exception_treated_as_private(self):
        with patch('validators.urlparse', side_effect=ValueError('invalid IPv6')):
            assert is_private_url('http://[invalid::]/') is True


# ---------------------------------------------------------------------------
# is_private_url — DNS rebinding protection
# ---------------------------------------------------------------------------


class TestIsPrivateUrlDnsRebinding:
    def test_hostname_resolving_to_private_ip_is_blocked(self):
        with patch('validators._resolve_host', return_value=['192.168.1.1']):
            assert is_private_url('http://evil.example.com/feed') is True

    def test_hostname_resolving_to_loopback_is_blocked(self):
        with patch('validators._resolve_host', return_value=['127.0.0.1']):
            assert is_private_url('http://rebind.example.com/feed') is True

    def test_hostname_resolving_to_link_local_is_blocked(self):
        with patch('validators._resolve_host', return_value=['169.254.1.1']):
            assert is_private_url('http://rebind.example.com/feed') is True

    def test_hostname_resolving_to_public_ip_is_allowed(self):
        with patch('validators._resolve_host', return_value=['93.184.216.34']):
            assert is_private_url('http://example.com/feed') is False

    def test_hostname_dns_failure_fails_open(self):
        """Unresolvable hostnames are allowed (fail-open) to avoid false positives."""
        with patch('validators._resolve_host', return_value=[]):
            assert is_private_url('http://nonexistent.invalid/feed') is False

    @pytest.mark.parametrize('private_ip', [
        '10.0.0.1', '172.16.0.1', '192.168.1.1',
        '127.0.0.1', '169.254.1.1', '0.0.0.0',
    ])
    def test_all_private_resolved_ips_blocked(self, private_ip):
        with patch('validators._resolve_host', return_value=[private_ip]):
            assert is_private_url('http://attacker.example.com/feed') is True
