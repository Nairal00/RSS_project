"""Tests for validators: is_private_url, is_http_url, has_control_chars, safe_get, and DNS rebinding protection."""

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from validators import has_control_chars, is_http_url, is_private_url, safe_get


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
        # example.com is a plain IP-literal in the URL — no DNS needed
        assert is_private_url('https://93.184.216.34/feed') is False

    def test_public_domain(self):
        with patch('validators._resolve_host', return_value=['93.184.216.34']):
            assert is_private_url('https://example.com/feed') is False

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

    def test_hostname_dns_failure_fails_closed(self):
        """Unresolvable hostnames are blocked (fail-closed) to prevent SSRF via DNS failure."""
        with patch('validators._resolve_host', return_value=[]):
            assert is_private_url('http://nonexistent.invalid/feed') is True

    @pytest.mark.parametrize('private_ip', [
        '10.0.0.1', '172.16.0.1', '192.168.1.1',
        '127.0.0.1', '169.254.1.1', '0.0.0.0',
    ])
    def test_all_private_resolved_ips_blocked(self, private_ip):
        with patch('validators._resolve_host', return_value=[private_ip]):
            assert is_private_url('http://attacker.example.com/feed') is True


# ---------------------------------------------------------------------------
# is_http_url
# ---------------------------------------------------------------------------


class TestIsHttpUrl:
    def test_http_scheme_accepted(self):
        assert is_http_url('http://example.com/feed') is True

    def test_https_scheme_accepted(self):
        assert is_http_url('https://example.com/feed') is True

    def test_uppercase_http_accepted(self):
        assert is_http_url('HTTP://example.com/feed') is True

    def test_uppercase_https_accepted(self):
        assert is_http_url('HTTPS://example.com/feed') is True

    def test_ftp_rejected(self):
        assert is_http_url('ftp://example.com/file') is False

    def test_empty_string_rejected(self):
        assert is_http_url('') is False

    def test_no_scheme_rejected(self):
        assert is_http_url('example.com/feed') is False

    def test_javascript_scheme_rejected(self):
        assert is_http_url('javascript:alert(1)') is False

    def test_urlparse_raises_value_error_returns_false(self):
        with patch('validators.urlparse', side_effect=ValueError('bad url')):
            assert is_http_url('http://example.com/') is False


# ---------------------------------------------------------------------------
# has_control_chars
# ---------------------------------------------------------------------------


class TestHasControlChars:
    def test_cr_detected(self):
        assert has_control_chars('https://example.com/\rfoo') is True

    def test_lf_detected(self):
        assert has_control_chars('https://example.com/\nfoo') is True

    def test_nul_detected(self):
        assert has_control_chars('https://example.com/\x00foo') is True

    def test_clean_url_not_flagged(self):
        assert has_control_chars('https://example.com/article?id=1') is False


# ---------------------------------------------------------------------------
# is_private_url — DNS resolved IPv4-mapped and unspecified coverage
# ---------------------------------------------------------------------------


class TestIsPrivateUrlDnsEdgeCases:
    def test_dns_resolved_ipv4_mapped_ipv6_loopback_is_blocked(self):
        """DNS returns ::ffff:127.0.0.1 — must be unwrapped and blocked."""
        with patch('validators._resolve_host', return_value=['::ffff:127.0.0.1']):
            assert is_private_url('http://rebind.example.com/feed') is True

    def test_dns_resolved_unspecified_is_blocked(self):
        """DNS returns 0.0.0.0 — is_unspecified must block it."""
        with patch('validators._resolve_host', return_value=['0.0.0.0']):
            assert is_private_url('http://rebind.example.com/feed') is True

    def test_dns_invalid_ip_string_skipped(self):
        """Non-IP string from getaddrinfo is skipped without crashing."""
        with patch('validators._resolve_host', return_value=['not-an-ip', '93.184.216.34']):
            assert is_private_url('http://example.com/feed') is False


# ---------------------------------------------------------------------------
# safe_get
# ---------------------------------------------------------------------------


def _make_response(status_code: int = 200, is_redirect: bool = False,
                   location: str = '') -> MagicMock:
    """Build a minimal mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_redirect = is_redirect
    resp.headers = {'Location': location} if location else {}
    resp.close = MagicMock()
    return resp


class TestSafeGet:
    """Tests for safe_get: redirect validation and SSRF prevention."""

    def test_non_redirect_response_returned_directly(self):
        """Happy path: no redirect — response returned as-is."""
        final_resp = _make_response(200)
        with patch('validators.requests.get', return_value=final_resp) as mock_get:
            result = safe_get('https://example.com/feed', timeout=10)
        assert result is final_resp
        mock_get.assert_called_once_with('https://example.com/feed',
                                         allow_redirects=False, timeout=10)

    def test_redirect_to_public_url_followed(self):
        """A redirect to a public URL should be followed and final response returned."""
        redirect_resp = _make_response(301, is_redirect=True,
                                       location='https://example.com/new')
        final_resp = _make_response(200)
        with (
            patch('validators.requests.get', side_effect=[redirect_resp, final_resp]),
            patch('validators.is_private_url', return_value=False),
        ):
            result = safe_get('https://example.com/old', timeout=5)
        assert result is final_resp
        redirect_resp.close.assert_called_once()

    def test_redirect_to_private_url_raises_value_error(self):
        """Redirect to a private address must raise ValueError and not follow."""
        redirect_resp = _make_response(301, is_redirect=True,
                                       location='http://192.168.1.1/internal')
        with (
            patch('validators.requests.get', return_value=redirect_resp),
            patch('validators.is_private_url', return_value=True),
        ):
            with pytest.raises(ValueError, match='Redirect to private/reserved URL blocked'):
                safe_get('https://example.com/', timeout=5)
        redirect_resp.close.assert_called_once()

    def test_too_many_redirects_raises(self):
        """Exceeding max_redirects raises TooManyRedirects."""
        redirect_resp = _make_response(301, is_redirect=True,
                                       location='https://example.com/loop')
        with (
            patch('validators.requests.get', return_value=redirect_resp),
            patch('validators.is_private_url', return_value=False),
        ):
            with pytest.raises(requests.exceptions.TooManyRedirects):
                safe_get('https://example.com/start', max_redirects=2, timeout=5)

    def test_allow_redirects_forced_false(self):
        """safe_get must always pass allow_redirects=False to requests.get."""
        final_resp = _make_response(200)
        with patch('validators.requests.get', return_value=final_resp) as mock_get:
            safe_get('https://example.com/', timeout=5)
        _, kwargs = mock_get.call_args
        assert kwargs.get('allow_redirects') is False

    def test_request_exception_propagates(self):
        """Network errors from requests.get propagate unchanged."""
        with patch('validators.requests.get',
                   side_effect=requests.ConnectionError('timeout')):
            with pytest.raises(requests.ConnectionError):
                safe_get('https://example.com/', timeout=5)

    def test_relative_location_header_resolved_against_base(self):
        """A relative Location header is resolved to an absolute URL before SSRF check."""
        redirect_resp = _make_response(302, is_redirect=True, location='/new-path')
        final_resp = _make_response(200)
        captured_urls: list[str] = []

        def fake_is_private(url: str) -> bool:
            captured_urls.append(url)
            return False

        with (
            patch('validators.requests.get', side_effect=[redirect_resp, final_resp]),
            patch('validators.is_private_url', side_effect=fake_is_private),
        ):
            safe_get('https://example.com/old', timeout=5)

        assert captured_urls[0] == 'https://example.com/new-path'

    @pytest.mark.parametrize('private_location', [
        'http://127.0.0.1/secret',
        'http://10.0.0.1/internal',
        'http://192.168.1.1/admin',
        'http://169.254.169.254/metadata',
    ])
    def test_all_private_redirect_targets_blocked(self, private_location):
        """All classes of private redirect targets are blocked."""
        redirect_resp = _make_response(301, is_redirect=True,
                                       location=private_location)
        with patch('validators.requests.get', return_value=redirect_resp):
            with pytest.raises(ValueError):
                safe_get('https://example.com/', timeout=5)

