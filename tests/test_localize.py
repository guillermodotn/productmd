"""Tests for the localization tool (localize_compose, _download_https)."""

import http.client
import io
import os
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from productmd.images import Image, Images
from productmd.localize import (
    HttpTask,
    LocalizeResult,
    OciTask,
    _SafeRedirectHandler,
    _build_auth_header,
    _deduplicate_http_tasks,
    _download_https,
    _download_single_oci,
    _get_netrc_auth_header,
    _should_skip,
    _should_skip_oci,
    _validate_credential,
    localize_compose,
)
from productmd.location import FileEntry, Location
from productmd.rpms import Rpms
from productmd.version import VERSION_1_2, VERSION_2_0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_image(parent, path, size, checksum_hex):
    img = Image(parent)
    img.path = path
    img.mtime = 1738627200
    img.size = size
    img.volume_id = "Test-1.0"
    img.type = "dvd"
    img.format = "iso"
    img.arch = "x86_64"
    img.disc_number = 1
    img.disc_count = 1
    img.checksums = {"sha256": checksum_hex}
    img.subvariant = "Server"
    return img


def _create_images_v2():
    """Create Images with explicit remote Location objects."""
    im = Images()
    im.header.version = "2.0"
    im.compose.id = "Test-1.0-20260204.0"
    im.compose.type = "production"
    im.compose.date = "20260204"
    im.compose.respin = 0
    im.output_version = VERSION_2_0

    img = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
    img.location = Location(
        url="https://cdn.example.com/Server/x86_64/iso/boot.iso",
        size=512,
        checksum="sha256:" + "a" * 64,
        local_path="Server/x86_64/iso/boot.iso",
    )
    im.add("Server", "x86_64", img)

    return im


def _create_rpms_v2():
    """Create Rpms with explicit remote Location objects."""
    rpms = Rpms()
    rpms.header.version = "2.0"
    rpms.compose.id = "Test-1.0-20260204.0"
    rpms.compose.type = "production"
    rpms.compose.date = "20260204"
    rpms.compose.respin = 0
    rpms.output_version = VERSION_2_0

    loc = Location(
        url="https://cdn.example.com/Server/x86_64/os/Packages/b/bash-5.2.26-3.fc41.x86_64.rpm",
        size=1849356,
        checksum="sha256:" + "b" * 64,
        local_path="Server/x86_64/os/Packages/b/bash-5.2.26-3.fc41.x86_64.rpm",
    )
    rpms.add(
        variant="Server",
        arch="x86_64",
        nevra="bash-0:5.2.26-3.fc41.x86_64",
        path="Server/x86_64/os/Packages/b/bash-5.2.26-3.fc41.x86_64.rpm",
        sigkey="a15b79cc",
        srpm_nevra="bash-0:5.2.26-3.fc41.src",
        category="binary",
        location=loc,
    )
    return rpms


def _create_images_v1():
    """Create Images without Location objects (v1.x data)."""
    im = Images()
    im.header.version = "1.2"
    im.compose.id = "Test-1.0-20260204.0"
    im.compose.type = "production"
    im.compose.date = "20260204"
    im.compose.respin = 0
    im.output_version = VERSION_1_2

    img = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
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
# Tests: _download_https
# ---------------------------------------------------------------------------


class TestDownloadHttps:
    """Tests for the _download_https function."""

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_creates_file(self, mock_urlopen, tmp_path):
        """Test that download creates the file at the correct path."""
        mock_urlopen.return_value = _mock_urlopen(b"hello world")
        dest = str(tmp_path / "output" / "test.txt")

        _download_https("https://example.com/test.txt", dest, retries=0)

        assert os.path.isfile(dest)
        with open(dest, "rb") as f:
            assert f.read() == b"hello world"

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_creates_parent_dirs(self, mock_urlopen, tmp_path):
        """Test that parent directories are created automatically."""
        mock_urlopen.return_value = _mock_urlopen(b"data")
        dest = str(tmp_path / "a" / "b" / "c" / "file.rpm")

        _download_https("https://example.com/file.rpm", dest, retries=0)

        assert os.path.isfile(dest)

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_atomic_rename(self, mock_urlopen, tmp_path):
        """Test that .tmp file is renamed to final name (no partial files)."""
        mock_urlopen.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "final.iso")

        _download_https("https://example.com/final.iso", dest, retries=0)

        assert os.path.isfile(dest)
        assert not os.path.exists(dest + ".tmp")

    @patch("productmd.localize.urllib.request.urlopen")
    @patch("productmd.localize.time.sleep")
    def test_download_retry_on_failure(self, mock_sleep, mock_urlopen, tmp_path):
        """Test that download retries on failure with exponential backoff."""
        from urllib.error import URLError

        mock_urlopen.side_effect = [
            URLError("connection refused"),
            URLError("timeout"),
            _mock_urlopen(b"success"),
        ]
        dest = str(tmp_path / "retried.txt")

        _download_https("https://example.com/retried.txt", dest, retries=2)

        assert os.path.isfile(dest)
        with open(dest, "rb") as f:
            assert f.read() == b"success"
        assert mock_sleep.call_count == 2

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_calls_progress_callback(self, mock_urlopen, tmp_path):
        """Test that progress callback receives correct events."""
        content = b"x" * 100
        mock_urlopen.return_value = _mock_urlopen(content)
        dest = str(tmp_path / "progress.bin")

        events = []
        _download_https(
            "https://example.com/progress.bin",
            dest,
            retries=0,
            progress_callback=events.append,
            filename="progress.bin",
        )

        event_types = [e.event_type for e in events]
        assert event_types[0] == "start"
        assert event_types[-1] == "complete"
        assert "progress" in event_types

        # Start event has total_bytes from Content-Length
        start = events[0]
        assert start.total_bytes == 100
        assert start.bytes_downloaded == 0

        # Complete event has full size
        complete = events[-1]
        assert complete.bytes_downloaded == 100

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_all_retries_exhausted(self, mock_urlopen, tmp_path):
        """Test that exception is raised when all retries are exhausted."""
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("permanent failure")
        dest = str(tmp_path / "fail.txt")

        with pytest.raises(URLError):
            _download_https("https://example.com/fail.txt", dest, retries=1)


# ---------------------------------------------------------------------------
# Tests: _should_skip
# ---------------------------------------------------------------------------


class TestShouldSkip:
    """Tests for the _should_skip function."""

    def test_file_does_not_exist(self, tmp_path):
        """Test that non-existent files are not skipped."""
        assert not _should_skip(str(tmp_path / "nope"), None, True)

    def test_file_exists_no_verify(self, tmp_path):
        """Test that existing files are skipped when verify_checksums=False."""
        f = tmp_path / "exists.txt"
        f.write_text("content")
        assert _should_skip(str(f), None, False)

    def test_file_exists_with_valid_checksum(self, tmp_path):
        """Test that files with matching checksum are skipped."""
        f = tmp_path / "valid.txt"
        f.write_bytes(b"test content")

        from productmd.location import compute_checksum as cc

        checksum = cc(str(f), "sha256")
        size = os.path.getsize(str(f))

        loc = Location(url="https://x", size=size, checksum=checksum, local_path="valid.txt")
        assert _should_skip(str(f), loc, True)

    def test_file_exists_with_wrong_checksum(self, tmp_path):
        """Test that files with wrong checksum are not skipped."""
        f = tmp_path / "wrong.txt"
        f.write_bytes(b"test content")

        loc = Location(url="https://x", size=12, checksum="sha256:" + "f" * 64, local_path="wrong.txt")
        assert not _should_skip(str(f), loc, True)

    def test_file_exists_no_checksum_available(self, tmp_path):
        """Test that files without checksum fall back to existence check."""
        f = tmp_path / "no_checksum.txt"
        f.write_text("content")

        loc = Location(url="https://x", local_path="no_checksum.txt")
        assert _should_skip(str(f), loc, True)


# ---------------------------------------------------------------------------
# Tests: localize_compose
# ---------------------------------------------------------------------------


class TestLocalizeCompose:
    """Tests for the localize_compose function."""

    @patch("productmd.localize.urllib.request.urlopen")
    def test_basic_localize(self, mock_urlopen, tmp_path):
        """Test basic localization downloads files and writes v1.2 metadata."""
        mock_urlopen.return_value = _mock_urlopen(b"iso content")
        output_dir = str(tmp_path / "compose-output")

        im = _create_images_v2()
        result = localize_compose(
            output_dir=output_dir,
            images=im,
            parallel_downloads=1,
            verify_checksums=False,
            retries=0,
        )

        assert result.downloaded == 1
        assert result.failed == 0

        # Verify file was downloaded
        expected = os.path.join(output_dir, "compose", "Server", "x86_64", "iso", "boot.iso")
        assert os.path.isfile(expected)

        # Verify v1.2 metadata was written
        metadata_dir = os.path.join(output_dir, "compose", "metadata")
        assert os.path.isfile(os.path.join(metadata_dir, "images.json"))

    @patch("productmd.localize.urllib.request.urlopen")
    def test_skip_existing_with_valid_checksum(self, mock_urlopen, tmp_path):
        """Test that existing files with valid checksum are skipped."""
        output_dir = str(tmp_path / "compose-output")

        # Pre-create the file
        file_path = os.path.join(output_dir, "compose", "Server", "x86_64", "iso", "boot.iso")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(b"existing content")

        im = _create_images_v2()
        # Update location checksum to match the pre-created file
        from productmd.location import compute_checksum as cc

        checksum = cc(file_path, "sha256")
        size = os.path.getsize(file_path)
        for image in im.images["Server"]["x86_64"]:
            image.location = Location(
                url="https://cdn.example.com/Server/x86_64/iso/boot.iso",
                size=size,
                checksum=checksum,
                local_path="Server/x86_64/iso/boot.iso",
            )

        result = localize_compose(
            output_dir=output_dir,
            images=im,
            skip_existing=True,
            verify_checksums=True,
            retries=0,
        )

        assert result.skipped == 1
        assert result.downloaded == 0
        # urlopen should not have been called
        mock_urlopen.assert_not_called()

    @patch("productmd.localize.urllib.request.urlopen")
    @patch("productmd.localize._should_skip")
    def test_skip_existing_wrong_checksum_redownloads(self, mock_skip, mock_urlopen, tmp_path):
        """Test that files with wrong checksum are re-downloaded when skip returns False."""
        mock_skip.return_value = False  # Simulate checksum mismatch
        mock_urlopen.return_value = _mock_urlopen(b"correct content")

        im = _create_images_v2()
        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            skip_existing=True,
            verify_checksums=False,  # Don't verify after download
            parallel_downloads=1,
            retries=0,
        )

        assert result.downloaded == 1
        assert result.skipped == 0
        mock_skip.assert_called_once()

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_oci_simple_download(self, mock_get_downloader, tmp_path):
        """Test that simple OCI URLs (no contents) are downloaded via oras."""
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        oci_url = "oci://quay.io/fedora/server:41-x86_64@sha256:" + "a" * 64
        img = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
        img.location = Location(
            url=oci_url,
            size=512,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/boot.iso",
        )
        im.add("Server", "x86_64", img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            verify_checksums=False,
        )

        assert result.downloaded == 1
        assert result.failed == 0
        mock_downloader.download_and_extract.assert_called_once()
        call_kwargs = mock_downloader.download_and_extract.call_args[1]
        assert call_kwargs["oci_url"] == oci_url
        assert call_kwargs["contents"] is None

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_oci_with_contents_download(self, mock_get_downloader, tmp_path):
        """Test that OCI URLs with contents pass FileEntry list to downloader."""
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        contents = [
            FileEntry(file="pxeboot/vmlinuz", size=100, checksum="sha256:" + "d" * 64, layer_digest="sha256:" + "d" * 64),
            FileEntry(file="pxeboot/initrd.img", size=200, checksum="sha256:" + "e" * 64, layer_digest="sha256:" + "e" * 64),
        ]
        oci_url = "oci://quay.io/fedora/boot:41-x86_64@sha256:" + "a" * 64
        img = _make_image(im, "Server/x86_64/os/images/pxeboot/vmlinuz", 100, "d" * 64)
        img.location = Location(
            url=oci_url,
            size=300,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/images",
            contents=contents,
        )
        im.add("Server", "x86_64", img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            verify_checksums=False,
        )

        # 2 files in contents
        assert result.downloaded == 2
        assert result.failed == 0
        mock_downloader.download_and_extract.assert_called_once()
        call_kwargs = mock_downloader.download_and_extract.call_args[1]
        assert call_kwargs["contents"] == contents

    @patch("productmd.oci.HAS_ORAS", False)
    def test_oci_url_without_oras_raises_runtime_error(self, tmp_path):
        """Test that OCI URLs without oras-py installed raise RuntimeError."""
        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        img = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
        img.location = Location(
            url="oci://quay.io/fedora/server:41-x86_64@sha256:" + "a" * 64,
            size=512,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/boot.iso",
        )
        im.add("Server", "x86_64", img)

        with pytest.raises(RuntimeError, match="oras-py is required"):
            localize_compose(
                output_dir=str(tmp_path / "output"),
                images=im,
            )

    @patch("productmd.localize.urllib.request.urlopen")
    def test_fail_fast_stops_on_error(self, mock_urlopen, tmp_path):
        """Test that fail_fast=True stops on first download failure."""
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")

        im = _create_images_v2()
        rpms = _create_rpms_v2()

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            rpms=rpms,
            fail_fast=True,
            parallel_downloads=1,
            retries=0,
        )

        assert result.failed >= 1
        # Should not have attempted all downloads
        assert result.downloaded == 0

    @patch("productmd.localize.urllib.request.urlopen")
    def test_fail_fast_false_continues(self, mock_urlopen, tmp_path):
        """Test that fail_fast=False continues after errors."""
        from urllib.error import URLError

        # First call fails, second succeeds
        mock_urlopen.side_effect = [
            URLError("connection refused"),
            _mock_urlopen(b"rpm content"),
        ]

        im = _create_images_v2()
        rpms = _create_rpms_v2()

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            rpms=rpms,
            fail_fast=False,
            verify_checksums=False,
            parallel_downloads=1,
            retries=0,
        )

        assert result.failed == 1
        assert result.downloaded == 1
        assert len(result.errors) == 1

    def test_skip_non_remote_locations(self, tmp_path):
        """Test that v1.x data with no remote URLs produces no downloads."""
        im = _create_images_v1()

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=1,
        )

        assert result.downloaded == 0
        assert result.skipped == 0
        assert result.failed == 0

    @patch("productmd.localize.urllib.request.urlopen")
    def test_localize_result_counts(self, mock_urlopen, tmp_path):
        """Test that LocalizeResult has correct counts."""
        mock_urlopen.return_value = _mock_urlopen(b"data")

        im = _create_images_v2()
        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=1,
            verify_checksums=False,
            retries=0,
        )

        assert isinstance(result, LocalizeResult)
        assert result.downloaded == 1
        assert result.skipped == 0
        assert result.failed == 0
        assert result.errors == []

    @patch("productmd.localize.urllib.request.urlopen")
    def test_progress_callback_receives_events(self, mock_urlopen, tmp_path):
        """Test that progress callback receives download events."""
        mock_urlopen.return_value = _mock_urlopen(b"file data")

        im = _create_images_v2()
        events = []

        localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=1,
            verify_checksums=False,
            retries=0,
            progress_callback=events.append,
        )

        event_types = [e.event_type for e in events]
        assert "start" in event_types
        assert "complete" in event_types

    @patch("productmd.localize.urllib.request.urlopen")
    def test_metadata_downgraded_to_v12(self, mock_urlopen, tmp_path):
        """Test that output metadata is written in v1.2 format."""
        import json

        mock_urlopen.return_value = _mock_urlopen(b"content")

        im = _create_images_v2()
        output_dir = str(tmp_path / "output")

        localize_compose(
            output_dir=output_dir,
            images=im,
            parallel_downloads=1,
            verify_checksums=False,
            retries=0,
        )

        metadata_file = os.path.join(output_dir, "compose", "metadata", "images.json")
        with open(metadata_file) as f:
            data = json.load(f)

        assert data["header"]["version"] == "1.2"
        # v1.2 format should have "path", not "location"
        img = data["payload"]["images"]["Server"]["x86_64"][0]
        assert "path" in img
        assert "location" not in img


# ---------------------------------------------------------------------------
# Tests: OCI-specific skip and download logic
# ---------------------------------------------------------------------------


class TestShouldSkipOci:
    """Tests for the _should_skip_oci function."""

    def test_skip_oci_contents_all_exist(self, tmp_path):
        """Test skip when all content files exist with valid checksums."""
        from productmd.location import compute_checksum as cc

        dest_dir = str(tmp_path / "images")
        os.makedirs(os.path.join(dest_dir, "pxeboot"))

        # Create files
        vmlinuz = os.path.join(dest_dir, "pxeboot", "vmlinuz")
        with open(vmlinuz, "wb") as f:
            f.write(b"kernel content")
        checksum = cc(vmlinuz, "sha256")

        contents = [
            FileEntry(file="pxeboot/vmlinuz", size=14, checksum=checksum, layer_digest="sha256:" + "a" * 64),
        ]
        task = OciTask(
            oci_url="oci://registry/repo@sha256:" + "b" * 64,
            dest_dir=dest_dir,
            contents=contents,
            location=Location(url="oci://registry/repo@sha256:" + "b" * 64, local_path="images"),
            rel_path="images/pxeboot/vmlinuz",
        )

        assert _should_skip_oci(task, verify_checksums=True)

    def test_no_skip_oci_contents_missing_file(self, tmp_path):
        """Test no skip when a content file is missing."""
        dest_dir = str(tmp_path / "images")
        os.makedirs(dest_dir)

        contents = [
            FileEntry(file="pxeboot/vmlinuz", size=14, checksum=None, layer_digest="sha256:" + "a" * 64),
        ]
        task = OciTask(
            oci_url="oci://registry/repo@sha256:" + "b" * 64,
            dest_dir=dest_dir,
            contents=contents,
            location=Location(url="oci://registry/repo@sha256:" + "b" * 64, local_path="images"),
            rel_path="images/pxeboot/vmlinuz",
        )

        assert not _should_skip_oci(task, verify_checksums=True)

    def test_no_skip_oci_contents_bad_checksum(self, tmp_path):
        """Test no skip when a content file has wrong checksum."""
        dest_dir = str(tmp_path / "images")
        os.makedirs(os.path.join(dest_dir, "pxeboot"))

        vmlinuz = os.path.join(dest_dir, "pxeboot", "vmlinuz")
        with open(vmlinuz, "wb") as f:
            f.write(b"kernel content")

        contents = [
            FileEntry(
                file="pxeboot/vmlinuz",
                size=14,
                checksum="sha256:" + "f" * 64,  # wrong
                layer_digest="sha256:" + "a" * 64,
            ),
        ]
        task = OciTask(
            oci_url="oci://registry/repo@sha256:" + "b" * 64,
            dest_dir=dest_dir,
            contents=contents,
            location=Location(url="oci://registry/repo@sha256:" + "b" * 64, local_path="images"),
            rel_path="images/pxeboot/vmlinuz",
        )

        assert not _should_skip_oci(task, verify_checksums=True)

    def test_skip_oci_contents_no_verify(self, tmp_path):
        """Test skip when all content files exist and verify_checksums=False."""
        dest_dir = str(tmp_path / "images")
        os.makedirs(os.path.join(dest_dir, "pxeboot"))

        vmlinuz = os.path.join(dest_dir, "pxeboot", "vmlinuz")
        with open(vmlinuz, "wb") as f:
            f.write(b"kernel content")

        contents = [
            FileEntry(
                file="pxeboot/vmlinuz",
                size=14,
                checksum="sha256:" + "f" * 64,  # wrong but not checked
                layer_digest="sha256:" + "a" * 64,
            ),
        ]
        task = OciTask(
            oci_url="oci://registry/repo@sha256:" + "b" * 64,
            dest_dir=dest_dir,
            contents=contents,
            location=Location(url="oci://registry/repo@sha256:" + "b" * 64, local_path="images"),
            rel_path="images/pxeboot/vmlinuz",
        )

        # Not verified, so existence alone is enough
        assert _should_skip_oci(task, verify_checksums=False)

    def test_skip_oci_simple_existing_file(self, tmp_path):
        """Test skip for simple OCI (no contents) when file exists."""
        # For simple OCI, dest_dir is the compose root and the file
        # is at dest_dir/local_path
        dest_dir = str(tmp_path / "compose")
        os.makedirs(dest_dir)
        file_path = os.path.join(dest_dir, "output.iso")
        with open(file_path, "wb") as f:
            f.write(b"iso content")

        task = OciTask(
            oci_url="oci://registry/repo@sha256:" + "b" * 64,
            dest_dir=dest_dir,
            contents=[],
            location=Location(url="oci://registry/repo@sha256:" + "b" * 64, local_path="output.iso"),
            rel_path="output.iso",
        )

        assert _should_skip_oci(task, verify_checksums=False)


class TestOciLocalizeIntegration:
    """Integration-style tests for OCI localization within localize_compose."""

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_oci_download_error_fail_fast(self, mock_get_downloader, tmp_path):
        """Test that OCI download errors respect fail_fast."""
        mock_downloader = MagicMock()
        mock_downloader.download_and_extract.side_effect = RuntimeError("registry unreachable")
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        img = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
        img.location = Location(
            url="oci://quay.io/fedora/server:41-x86_64@sha256:" + "a" * 64,
            size=512,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/boot.iso",
        )
        im.add("Server", "x86_64", img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            fail_fast=True,
            verify_checksums=False,
        )

        assert result.failed == 1
        assert result.downloaded == 0
        assert len(result.errors) == 1
        assert "registry unreachable" in str(result.errors[0][1])

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_oci_progress_events(self, mock_get_downloader, tmp_path):
        """Test that OCI downloads emit progress events."""
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        img = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
        img.location = Location(
            url="oci://quay.io/fedora/server:41-x86_64@sha256:" + "a" * 64,
            size=512,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/boot.iso",
        )
        im.add("Server", "x86_64", img)

        events = []
        localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            verify_checksums=False,
            progress_callback=events.append,
        )

        event_types = [e.event_type for e in events]
        assert "start" in event_types
        assert "complete" in event_types

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    @patch("productmd.localize.urllib.request.urlopen")
    def test_mixed_http_and_oci_downloads(self, mock_urlopen, mock_get_downloader, tmp_path):
        """Test that a compose with both HTTP and OCI URLs works."""
        mock_urlopen.return_value = _mock_urlopen(b"http content")
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        # HTTP image
        img_http = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
        img_http.location = Location(
            url="https://cdn.example.com/Server/x86_64/iso/boot.iso",
            size=512,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/boot.iso",
        )
        im.add("Server", "x86_64", img_http)

        # OCI image
        img_oci = _make_image(im, "Server/aarch64/iso/boot.iso", 1024, "b" * 64)
        img_oci.arch = "aarch64"
        img_oci.location = Location(
            url="oci://quay.io/fedora/server:41-aarch64@sha256:" + "b" * 64,
            size=1024,
            checksum="sha256:" + "b" * 64,
            local_path="Server/aarch64/iso/boot.iso",
        )
        im.add("Server", "aarch64", img_oci)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=1,
            verify_checksums=False,
            retries=0,
        )

        # 1 HTTP + 1 OCI
        assert result.downloaded == 2
        assert result.failed == 0
        mock_urlopen.assert_called_once()
        mock_downloader.download_and_extract.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Parallel OCI downloads
# ---------------------------------------------------------------------------


class TestOciParallelDownloads:
    """Tests for parallel OCI download execution."""

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_parallel_multiple_oci_tasks(self, mock_get_downloader, tmp_path):
        """Test that multiple OCI tasks are all downloaded in parallel mode."""
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        # Create 3 OCI images on different arches
        for arch, hex_char in [("x86_64", "a"), ("aarch64", "b"), ("s390x", "c")]:
            img = _make_image(im, f"Server/{arch}/iso/boot.iso", 512, hex_char * 64)
            img.arch = arch
            img.location = Location(
                url=f"oci://quay.io/fedora/server:41-{arch}@sha256:" + hex_char * 64,
                size=512,
                checksum="sha256:" + hex_char * 64,
                local_path=f"Server/{arch}/iso/boot.iso",
            )
            im.add("Server", arch, img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=3,
            verify_checksums=False,
        )

        assert result.downloaded == 3
        assert result.failed == 0
        # Each task creates its own downloader (thread-safety)
        assert mock_get_downloader.call_count == 3
        assert mock_downloader.download_and_extract.call_count == 3

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_parallel_oci_fail_fast_stops(self, mock_get_downloader, tmp_path):
        """Test that fail_fast cancels remaining parallel OCI tasks on error."""
        mock_downloader = MagicMock()
        mock_downloader.download_and_extract.side_effect = RuntimeError("pull failed")
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        for arch, hex_char in [("x86_64", "a"), ("aarch64", "b"), ("s390x", "c")]:
            img = _make_image(im, f"Server/{arch}/iso/boot.iso", 512, hex_char * 64)
            img.arch = arch
            img.location = Location(
                url=f"oci://quay.io/fedora/server:41-{arch}@sha256:" + hex_char * 64,
                size=512,
                checksum="sha256:" + hex_char * 64,
                local_path=f"Server/{arch}/iso/boot.iso",
            )
            im.add("Server", arch, img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=2,
            fail_fast=True,
            verify_checksums=False,
        )

        assert result.downloaded == 0
        assert result.failed >= 1
        assert len(result.errors) >= 1

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_parallel_oci_no_fail_fast_continues(self, mock_get_downloader, tmp_path):
        """Test that fail_fast=False continues after OCI errors in parallel mode."""
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first pull failed")
            # Subsequent calls succeed

        mock_downloader = MagicMock()
        mock_downloader.download_and_extract.side_effect = side_effect
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        for arch, hex_char in [("x86_64", "a"), ("aarch64", "b")]:
            img = _make_image(im, f"Server/{arch}/iso/boot.iso", 512, hex_char * 64)
            img.arch = arch
            img.location = Location(
                url=f"oci://quay.io/fedora/server:41-{arch}@sha256:" + hex_char * 64,
                size=512,
                checksum="sha256:" + hex_char * 64,
                local_path=f"Server/{arch}/iso/boot.iso",
            )
            im.add("Server", arch, img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=2,
            fail_fast=False,
            verify_checksums=False,
        )

        assert result.downloaded == 1
        assert result.failed == 1
        assert len(result.errors) == 1

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_sequential_oci_with_parallel_1(self, mock_get_downloader, tmp_path):
        """Test that parallel_downloads=1 uses sequential OCI path."""
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        for arch, hex_char in [("x86_64", "a"), ("aarch64", "b")]:
            img = _make_image(im, f"Server/{arch}/iso/boot.iso", 512, hex_char * 64)
            img.arch = arch
            img.location = Location(
                url=f"oci://quay.io/fedora/server:41-{arch}@sha256:" + hex_char * 64,
                size=512,
                checksum="sha256:" + hex_char * 64,
                local_path=f"Server/{arch}/iso/boot.iso",
            )
            im.add("Server", arch, img)

        result = localize_compose(
            output_dir=str(tmp_path / "output"),
            images=im,
            parallel_downloads=1,
            verify_checksums=False,
        )

        assert result.downloaded == 2
        assert result.failed == 0
        # Each task still creates its own downloader
        assert mock_get_downloader.call_count == 2

    @patch("productmd.oci.get_downloader")
    @patch("productmd.oci.HAS_ORAS", True)
    def test_download_single_oci_creates_own_downloader(self, mock_get_downloader, tmp_path):
        """Test that _download_single_oci creates a fresh downloader per call."""
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        task = OciTask(
            oci_url="oci://registry/repo@sha256:" + "a" * 64,
            dest_dir=str(tmp_path / "out"),
            contents=[],
            location=Location(
                url="oci://registry/repo@sha256:" + "a" * 64,
                size=100,
                local_path="out",
            ),
            rel_path="out/file",
        )

        _download_single_oci(task, progress_callback=None)
        _download_single_oci(task, progress_callback=None)

        # get_downloader called once per invocation (fresh downloader each time)
        assert mock_get_downloader.call_count == 2


# ---------------------------------------------------------------------------
# Tests: HTTP task deduplication
# ---------------------------------------------------------------------------


class TestDeduplicateHttpTasks:
    """Tests for _deduplicate_http_tasks conflict detection."""

    def test_same_url_same_dest_deduplicates(self):
        """Test that identical tasks are deduplicated silently."""
        task = HttpTask(
            url="https://cdn.example.com/boot.iso",
            dest_path="/tmp/compose/Server/x86_64/iso/boot.iso",
            location=None,
            rel_path="Server/x86_64/iso/boot.iso",
        )
        result = _deduplicate_http_tasks([task, task])
        assert len(result) == 1
        assert result[0] is task

    def test_different_url_same_dest_raises(self):
        """Test that conflicting URLs for the same dest_path raise ValueError."""
        task1 = HttpTask(
            url="https://cdn-a.example.com/boot.iso",
            dest_path="/tmp/compose/Server/x86_64/iso/boot.iso",
            location=None,
            rel_path="Server/x86_64/iso/boot.iso",
        )
        task2 = HttpTask(
            url="https://cdn-b.example.com/boot.iso",
            dest_path="/tmp/compose/Server/x86_64/iso/boot.iso",
            location=None,
            rel_path="Server/x86_64/iso/boot.iso",
        )
        with pytest.raises(ValueError, match="Conflicting URLs"):
            _deduplicate_http_tasks([task1, task2])

    def test_same_url_different_dest_keeps_both(self):
        """Test that same URL targeting different paths keeps both."""
        task1 = HttpTask(
            url="https://cdn.example.com/boot.iso",
            dest_path="/tmp/compose/Server/x86_64/iso/boot.iso",
            location=None,
            rel_path="Server/x86_64/iso/boot.iso",
        )
        task2 = HttpTask(
            url="https://cdn.example.com/boot.iso",
            dest_path="/tmp/compose/Workstation/x86_64/iso/boot.iso",
            location=None,
            rel_path="Workstation/x86_64/iso/boot.iso",
        )
        result = _deduplicate_http_tasks([task1, task2])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests: HTTP Authentication
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
        import base64

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
        import base64

        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "deploy:s3cret"

    def test_netrc_no_hostname_in_url(self):
        """Test that a URL with no hostname returns None."""
        result = _get_netrc_auth_header("file:///local/path", None)

        assert result is None


class TestBuildAuthHeader:
    """Tests for _build_auth_header precedence logic."""

    def test_explicit_basic_auth(self):
        """Test that explicit username/password produce a Basic header."""
        result = _build_auth_header("https://example.com/file", username="user", password="pass")

        assert result is not None
        assert result.startswith("Basic ")
        import base64

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
        import base64

        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "explicit-user:explicit-pass"

    def test_falls_back_to_netrc(self, tmp_path):
        """Test that netrc is used when no explicit credentials are given."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine example.com\nlogin netrc-user\npassword netrc-pass\n")

        result = _build_auth_header("https://example.com/file", netrc_file=str(netrc_file))

        assert result is not None
        import base64

        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "netrc-user:netrc-pass"

    def test_no_credentials_returns_none(self):
        """Test that None is returned when no auth is available."""
        result = _build_auth_header(
            "https://example.com/file",
            netrc_file="/nonexistent/.netrc",
        )

        assert result is None


class TestDownloadHttpsAuth:
    """Tests for authentication in _download_https."""

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_sends_basic_auth_header(self, mock_urlopen, tmp_path):
        """Test that explicit credentials add Authorization header to request."""
        mock_urlopen.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "file.rpm")

        _download_https(
            "https://pulp.example.com/file.rpm",
            dest,
            retries=0,
            username="admin",
            password="secret",
        )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_sends_bearer_token_header(self, mock_urlopen, tmp_path):
        """Test that a token adds a Bearer Authorization header."""
        mock_urlopen.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "file.rpm")

        _download_https(
            "https://pulp.example.com/file.rpm",
            dest,
            retries=0,
            token="jwt-token-here",
        )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer jwt-token-here"

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_sends_netrc_auth_header(self, mock_urlopen, tmp_path):
        """Test that netrc credentials add Authorization header."""
        mock_urlopen.return_value = _mock_urlopen(b"content")
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("machine pulp.example.com\nlogin admin\npassword secret\n")
        dest = str(tmp_path / "file.rpm")

        _download_https(
            "https://pulp.example.com/file.rpm",
            dest,
            retries=0,
            netrc_file=str(netrc_file),
        )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")

    @patch("productmd.localize.urllib.request.urlopen")
    def test_download_no_auth_by_default(self, mock_urlopen, tmp_path):
        """Test that no Authorization header is set when no auth is configured."""
        mock_urlopen.return_value = _mock_urlopen(b"content")
        dest = str(tmp_path / "file.rpm")

        _download_https(
            "https://pulp.example.com/file.rpm",
            dest,
            retries=0,
            netrc_file="/nonexistent/.netrc",
        )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") is None

    @patch("productmd.localize.urllib.request.urlopen")
    def test_localize_compose_passes_auth_credentials(self, mock_urlopen, tmp_path):
        """Test that localize_compose passes auth params to _download_https."""
        mock_urlopen.return_value = _mock_urlopen(b"x" * 512)
        images = _create_images_v2()

        localize_compose(
            output_dir=str(tmp_path),
            images=images,
            parallel_downloads=1,
            verify_checksums=False,
            http_username="user",
            http_password="pass",
        )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")

    @patch("productmd.localize.urllib.request.urlopen")
    def test_localize_compose_passes_token(self, mock_urlopen, tmp_path):
        """Test that localize_compose passes token to _download_https."""
        mock_urlopen.return_value = _mock_urlopen(b"x" * 512)
        images = _create_images_v2()

        localize_compose(
            output_dir=str(tmp_path),
            images=images,
            parallel_downloads=1,
            verify_checksums=False,
            http_token="my-bearer-token",
        )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-bearer-token"


# ---------------------------------------------------------------------------
# Tests: Safe Redirect Handler
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
            handler,
            "https://pulp.example.com/repo/file.rpm",
            "https://cdn.example.com/cached-file.rpm",
            auth_header="Basic abc123",
        )

        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_keeps_auth_on_same_origin_redirect(self):
        """Test that Authorization is preserved when redirecting to the same origin."""
        handler = _SafeRedirectHandler()

        new_req = self._redirect(
            handler,
            "https://pulp.example.com/repo/file.rpm",
            "https://pulp.example.com/different/path.rpm",
            auth_header="Basic abc123",
        )

        assert new_req is not None
        assert new_req.get_header("Authorization") == "Basic abc123"

    def test_strips_auth_on_scheme_downgrade(self):
        """Test that Authorization is removed on HTTPS -> HTTP downgrade."""
        handler = _SafeRedirectHandler()

        new_req = self._redirect(
            handler,
            "https://pulp.example.com/file.rpm",
            "http://pulp.example.com/file.rpm",
            auth_header="Bearer my-token",
        )

        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_strips_auth_on_port_change(self):
        """Test that Authorization is removed when the port changes."""
        handler = _SafeRedirectHandler()

        new_req = self._redirect(
            handler,
            "https://pulp.example.com:443/file.rpm",
            "https://pulp.example.com:8443/file.rpm",
            auth_header="Basic abc123",
        )

        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_no_auth_header_no_error(self):
        """Test that redirects without Authorization header work fine."""
        handler = _SafeRedirectHandler()

        new_req = self._redirect(
            handler,
            "https://pulp.example.com/file.rpm",
            "https://cdn.example.com/file.rpm",
        )

        assert new_req is not None
        assert new_req.get_header("Authorization") is None

    def test_keeps_auth_on_default_port_redirect(self):
        """Test that https://host → https://host:443 is treated as same origin."""
        handler = _SafeRedirectHandler()

        new_req = self._redirect(
            handler,
            "https://pulp.example.com/file.rpm",
            "https://pulp.example.com:443/file.rpm",
            auth_header="Basic abc123",
        )

        assert new_req is not None
        assert new_req.get_header("Authorization") == "Basic abc123"

    def test_keeps_auth_on_default_http_port_redirect(self):
        """Test that http://host → http://host:80 is treated as same origin."""
        handler = _SafeRedirectHandler()

        new_req = self._redirect(
            handler,
            "http://pulp.example.com/file.rpm",
            "http://pulp.example.com:80/file.rpm",
            auth_header="Bearer my-token",
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
            localize_compose(
                output_dir="/tmp/test",
                http_username="admin",
            )

    def test_password_without_username_raises(self):
        """localize_compose raises ValueError when password is given without username."""
        with pytest.raises(ValueError, match="must be provided together"):
            localize_compose(
                output_dir="/tmp/test",
                http_password="secret",
            )

    def test_token_with_username_raises(self):
        """localize_compose raises ValueError when token and username are both given."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            localize_compose(
                output_dir="/tmp/test",
                http_token="my-token",
                http_username="admin",
                http_password="secret",
            )


# ---------------------------------------------------------------------------
# Tests: Netrc default entry
# ---------------------------------------------------------------------------


class TestNetrcDefaultEntry:
    """Tests for netrc 'default' machine entry."""

    def test_netrc_default_entry_matches(self, tmp_path):
        """Test that the netrc 'default' entry matches any hostname."""
        netrc_file = tmp_path / ".netrc"
        netrc_file.write_text("default\nlogin fallback-user\npassword fallback-pass\n")

        result = _get_netrc_auth_header("https://any-host.example.com/file.rpm", str(netrc_file))

        assert result is not None
        import base64

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
        import base64

        decoded = base64.b64decode(result.split(" ", 1)[1]).decode()
        assert decoded == "specific-user:specific-pass"


# ---------------------------------------------------------------------------
# Tests: Parallel downloads with auth
# ---------------------------------------------------------------------------


class TestParallelDownloadsAuth:
    """Tests for auth in parallel download path."""

    @patch("productmd.localize.urllib.request.urlopen")
    def test_parallel_downloads_send_auth(self, mock_urlopen, tmp_path):
        """Test that auth headers are sent when using parallel downloads."""
        mock_urlopen.return_value = _mock_urlopen(b"x" * 512)
        images = _create_images_v2()

        localize_compose(
            output_dir=str(tmp_path),
            images=images,
            parallel_downloads=2,
            verify_checksums=False,
            http_username="admin",
            http_password="secret",
        )

        # All calls should have the auth header
        for call in mock_urlopen.call_args_list:
            req = call[0][0]
            assert req.get_header("Authorization").startswith("Basic ")
