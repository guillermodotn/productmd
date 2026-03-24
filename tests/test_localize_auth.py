"""Tests for HTTP authentication in the localization tool."""

import base64
import http.client
import io
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from productmd.images import Images
from productmd.localize import (
    _SafeRedirectHandler,
    _build_auth_header,
    _download_https,
    _get_netrc_auth_header,
    _validate_credential,
    localize_compose,
)
from productmd.location import Location
from productmd.version import VERSION_2_0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_images_v2():
    """Create Images with explicit remote Location objects."""
    from productmd.images import Image

    im = Images()
    im.header.version = "2.0"
    im.compose.id = "Test-1.0-20260204.0"
    im.compose.type = "production"
    im.compose.date = "20260204"
    im.compose.respin = 0
    im.output_version = VERSION_2_0

    img = Image(im)
    img.path = "Server/x86_64/iso/boot.iso"
    img.mtime = 1738627200
    img.size = 512
    img.volume_id = "Test-1.0"
    img.type = "dvd"
    img.format = "iso"
    img.arch = "x86_64"
    img.disc_number = 1
    img.disc_count = 1
    img.checksums = {"sha256": "a" * 64}
    img.subvariant = "Server"
    img.location = Location(
        url="https://cdn.example.com/Server/x86_64/iso/boot.iso",
        size=512,
        checksum="sha256:" + "a" * 64,
        local_path="Server/x86_64/iso/boot.iso",
    )
    im.add("Server", "x86_64", img)

    return im


def _mock_urlopen(content=b"fake file content", status=200, content_length=None):
    """Create a mock response for urllib.request.urlopen."""
    response = MagicMock()
    data = io.BytesIO(content)
    response.read = data.read
    if content_length is None:
        content_length = str(len(content))
    response.headers = {"Content-Length": content_length}
    response.status = status
    return response


# ---------------------------------------------------------------------------
# Tests: Netrc auth header lookup
# ---------------------------------------------------------------------------


class TestGetNetrcAuthHeader:
    """Tests for _get_netrc_auth_header."""

    def test_netrc_auth_found(self, tmp_path):
        """Test that matching netrc credentials produce a Basic auth header."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine pulp.example.com\nlogin admin\npassword secret123\n")

        result = _get_netrc_auth_header("https://pulp.example.com/repo/file.rpm", str(netrc_file))

        assert result is not None
        assert result.startswith("Basic ")
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "admin:secret123"

    def test_netrc_host_not_found(self, tmp_path):
        """Test that no match returns None."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine other.example.com\nlogin user\npassword pass\n")

        result = _get_netrc_auth_header("https://pulp.example.com/file.rpm", str(netrc_file))

        assert result is None

    def test_netrc_file_missing(self):
        """Test that a missing netrc file returns None without error."""
        result = _get_netrc_auth_header("https://pulp.example.com/file.rpm", "/nonexistent/.netrc")

        assert result is None

    def test_netrc_parse_error(self, tmp_path):
        """Test that a malformed netrc file returns None without error."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("this is not valid netrc content!!!\n~~~")

        result = _get_netrc_auth_header("https://pulp.example.com/file.rpm", str(netrc_file))

        assert result is None

    def test_netrc_custom_file(self, tmp_path):
        """Test that a custom netrc file path is used."""
        custom_netrc = tmp_path / "custom-netrc"
        custom_netrc.write_text("machine cdn.example.com\nlogin deploy\npassword s3cret\n")

        result = _get_netrc_auth_header("https://cdn.example.com/boot.iso", str(custom_netrc))

        assert result is not None
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "deploy:s3cret"

    def test_netrc_no_hostname_in_url(self):
        """Test that a URL with no hostname returns None."""
        result = _get_netrc_auth_header("file:///local/path", None)

        assert result is None

    def test_netrc_default_entry_matches(self, tmp_path):
        """Test that the netrc 'default' entry matches any hostname."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("default\nlogin fallback-user\npassword fallback-pass\n")

        result = _get_netrc_auth_header("https://any-host.example.com/file.rpm", str(netrc_file))

        assert result is not None
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "fallback-user:fallback-pass"

    def test_netrc_specific_overrides_default(self, tmp_path):
        """Test that a specific machine entry takes precedence over default."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text(
            "machine pulp.example.com\nlogin specific-user\npassword specific-pass\n\n"
            "default\nlogin fallback-user\npassword fallback-pass\n"
        )

        result = _get_netrc_auth_header("https://pulp.example.com/file.rpm", str(netrc_file))

        assert result is not None
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "specific-user:specific-pass"


# ---------------------------------------------------------------------------
# Tests: Auth header precedence
# ---------------------------------------------------------------------------


class TestBuildAuthHeader:
    """Tests for _build_auth_header precedence logic."""

    def test_explicit_basic_auth(self):
        """Test that explicit username/password produce a Basic header."""
        result = _build_auth_header("https://example.com/file", username="user", password="pass")

        assert result is not None
        assert result.startswith("Basic ")
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "user:pass"

    def test_bearer_token(self):
        """Test that a token produces a Bearer header."""
        result = _build_auth_header("https://example.com/file", token="my-jwt-token")

        assert result == "Bearer my-jwt-token"

    def test_token_overrides_basic(self):
        """Test that token takes precedence over username/password."""
        result = _build_auth_header(
            "https://example.com/file",
            username="user",
            password="pass",
            token="my-token",
        )

        assert result == "Bearer my-token"

    def test_token_overrides_netrc(self, tmp_path):
        """Test that token takes precedence over netrc credentials."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine example.com\nlogin admin\npassword secret\n")

        result = _build_auth_header(
            "https://example.com/file",
            token="my-token",
            netrc_file=str(netrc_file),
        )

        assert result == "Bearer my-token"

    def test_explicit_basic_overrides_netrc(self, tmp_path):
        """Test that explicit credentials override netrc."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine example.com\nlogin netrc-user\npassword netrc-pass\n")

        result = _build_auth_header(
            "https://example.com/file",
            username="explicit-user",
            password="explicit-pass",
            netrc_file=str(netrc_file),
        )

        assert result is not None
        assert result.startswith("Basic ")
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "explicit-user:explicit-pass"

    def test_falls_back_to_netrc(self, tmp_path):
        """Test that netrc is used when no explicit credentials are given."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine example.com\nlogin netrc-user\npassword netrc-pass\n")

        result = _build_auth_header("https://example.com/file", netrc_file=str(netrc_file))

        assert result is not None
        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "netrc-user:netrc-pass"

    def test_no_credentials_returns_none(self):
        """Test that None is returned when no auth is available."""
        result = _build_auth_header(
            "https://example.com/file",
            netrc_file="/nonexistent/.netrc",
        )

        assert result is None


# ---------------------------------------------------------------------------
# Tests: Auth in _download_https
# ---------------------------------------------------------------------------


class TestDownloadHttpsAuth:
    """Tests for authentication in _download_https."""

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_sends_basic_auth_header(self, mock_urlopen_fn, tmp_path):
        """Test that explicit credentials add Authorization header to request."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "file.rpm")

        _download_https("https://pulp.example.com/file.rpm", dest, retries=0, username="admin", password="secret")

        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_sends_bearer_token_header(self, mock_urlopen_fn, tmp_path):
        """Test that a token adds a Bearer Authorization header."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "file.rpm")

        _download_https("https://pulp.example.com/file.rpm", dest, retries=0, token="jwt-token-here")

        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer jwt-token-here"

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_sends_netrc_auth_header(self, mock_urlopen_fn, tmp_path):
        """Test that netrc credentials add Authorization header."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"content")
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine pulp.example.com\nlogin admin\npassword secret\n")
        dest = str(tmp_path / "file.rpm")

        _download_https("https://pulp.example.com/file.rpm", dest, retries=0, netrc_file=str(netrc_file))

        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_no_auth_by_default(self, mock_urlopen_fn, tmp_path):
        """Test that no Authorization header is set when no auth is configured."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "file.rpm")

        _download_https("https://pulp.example.com/file.rpm", dest, retries=0, netrc_file="/nonexistent/.netrc")

        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization") is None

    @patch("productmd.localize.urllib.request.urlopen")
    def test_localize_compose_passes_auth_credentials(self, mock_urlopen_fn, tmp_path):
        """Test that localize_compose passes auth params to _download_https."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"x" * 512)
        images = _create_images_v2()

        localize_compose(
            output_dir=str(tmp_path),
            images=images,
            parallel_downloads=1,
            verify_checksums=False,
            http_username="user",
            http_password="pass",
        )

        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")

    @patch("productmd.localize.urllib.request.urlopen")
    def test_localize_compose_passes_token(self, mock_urlopen_fn, tmp_path):
        """Test that localize_compose passes token to _download_https."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"x" * 512)
        images = _create_images_v2()

        localize_compose(
            output_dir=str(tmp_path), images=images, parallel_downloads=1, verify_checksums=False, http_token="my-bearer-token"
        )

        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-bearer-token"

    @patch("productmd.localize.urllib.request.urlopen")
    def test_parallel_downloads_send_auth(self, mock_urlopen_fn, tmp_path):
        """Test that auth headers are sent when using parallel downloads."""
        mock_urlopen_fn.return_value = _mock_urlopen(b"x" * 512)
        images = _create_images_v2()

        localize_compose(
            output_dir=str(tmp_path),
            images=images,
            parallel_downloads=2,
            verify_checksums=False,
            http_username="admin",
            http_password="secret",
        )

        for call in mock_urlopen_fn.call_args_list:
            req = call[0][0]
            assert req.get_header("Authorization").startswith("Basic ")


# ---------------------------------------------------------------------------
# Tests: Safe redirect handler
# ---------------------------------------------------------------------------


class TestSafeRedirectHandler:
    """Tests for _SafeRedirectHandler cross-origin auth stripping."""

    def _redirect(self, handler, orig_url, new_url, auth_header=None):
        """Helper to invoke redirect_request with minimal boilerplate."""
        req = urllib.request.Request(orig_url)
        if auth_header:
            req.add_header("Authorization", auth_header)
        headers = http.client.HTTPMessage()
        fp = io.BytesIO(b"")
        return handler.redirect_request(req, fp, 302, "Found", headers, new_url)

    def test_strips_auth_on_cross_origin_redirect(self):
        """Test that Authorization is removed when redirecting to a different host."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(
            handler, "https://pulp.example.com/repo/file.rpm", "https://cdn.example.com/cached-file.rpm", auth_header="Basic abc123"
        )
        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_keeps_auth_on_same_origin_redirect(self):
        """Test that Authorization is preserved when redirecting to the same origin."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(
            handler, "https://pulp.example.com/repo/file.rpm", "https://pulp.example.com/different/path.rpm", auth_header="Basic abc123"
        )
        assert new_req is not None
        assert new_req.get_header("Authorization") == "Basic abc123"

    def test_strips_auth_on_scheme_downgrade(self):
        """Test that Authorization is removed on HTTPS -> HTTP downgrade."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(
            handler, "https://pulp.example.com/file.rpm", "http://pulp.example.com/file.rpm", auth_header="Bearer my-token"
        )
        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_strips_auth_on_port_change(self):
        """Test that Authorization is removed when the port changes."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(
            handler, "https://pulp.example.com:443/file.rpm", "https://pulp.example.com:8443/file.rpm", auth_header="Basic abc123"
        )
        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_no_auth_header_no_error(self):
        """Test that redirects without Authorization header work fine."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(handler, "https://pulp.example.com/file.rpm", "https://cdn.example.com/file.rpm")
        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_keeps_auth_on_default_port_redirect(self):
        """Test that https://host -> https://host:443 is treated as same origin."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(
            handler, "https://pulp.example.com/file.rpm", "https://pulp.example.com:443/file.rpm", auth_header="Basic abc123"
        )
        assert new_req is not None
        assert new_req.get_header("Authorization") == "Basic abc123"

    def test_keeps_auth_on_default_http_port_redirect(self):
        """Test that http://host -> http://host:80 is treated as same origin."""
        handler = _SafeRedirectHandler()
        new_req = self._redirect(
            handler, "http://pulp.example.com/file.rpm", "http://pulp.example.com:80/file.rpm", auth_header="Bearer my-token"
        )
        assert new_req is not None
        assert new_req.get_header("Authorization") == "Bearer my-token"


# ---------------------------------------------------------------------------
# Tests: Credential validation
# ---------------------------------------------------------------------------


class TestValidateCredential:
    """Tests for _validate_credential header injection prevention."""

    def test_valid_credential(self):
        """Normal credential values pass through unchanged."""
        assert _validate_credential("admin", "username") == "admin"
        assert _validate_credential("secret123", "password") == "secret123"
        assert _validate_credential("eyJhbGciOiJSUzI1NiIs", "token") == "eyJhbGciOiJSUzI1NiIs"

    @pytest.mark.parametrize(
        "value",
        [
            "token\nevil",
            "token\revil",
            "token\r\nevil-header: injected",
        ],
    )
    def test_rejects_newline_characters(self, value):
        """Credentials with CR, LF, or CRLF are rejected."""
        with pytest.raises(ValueError, match="newline"):
            _validate_credential(value, "token")

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"token": "bad\ntoken"},
            {"username": "bad\nuser", "password": "pass"},
            {"username": "user", "password": "bad\npass"},
        ],
    )
    def test_build_auth_header_rejects_bad_credentials(self, kwargs):
        """_build_auth_header raises on any credential with newlines."""
        with pytest.raises(ValueError, match="newline"):
            _build_auth_header("https://example.com", **kwargs)


# ---------------------------------------------------------------------------
# Tests: Library-level auth validation
# ---------------------------------------------------------------------------


class TestLocalizeComposeAuthValidation:
    """Tests for auth parameter validation in localize_compose."""

    def test_username_without_password_raises(self):
        """localize_compose raises ValueError when username is given without password."""
        with pytest.raises(ValueError, match="must be provided together"):
            localize_compose(output_dir="/tmp/test", http_username="admin")

    def test_password_without_username_raises(self):
        """localize_compose raises ValueError when password is given without username."""
        with pytest.raises(ValueError, match="must be provided together"):
            localize_compose(output_dir="/tmp/test", http_password="secret")

    def test_token_with_username_raises(self):
        """localize_compose raises ValueError when token and username are both given."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            localize_compose(output_dir="/tmp/test", http_token="my-token", http_username="admin", http_password="secret")
