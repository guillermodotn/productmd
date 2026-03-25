"""Tests for OCI-specific localization logic (skip, download, parallel)."""

import io
import os
from unittest.mock import MagicMock, patch

from productmd.images import Image, Images
from productmd.localize import (
    OciTask,
    _download_single_oci,
    _should_skip_oci,
    localize_compose,
)
from productmd.location import FileEntry, Location
from productmd.version import VERSION_2_0


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


def _mock_response(content=b"fake file content", status=200, content_length=None):
    """Create a mock HTTP response for _opener.open()."""
    response = MagicMock()
    data = io.BytesIO(content)
    response.read = data.read
    if content_length is None:
        content_length = str(len(content))
    response.headers = {"Content-Length": content_length}
    response.status = status
    return response


# ---------------------------------------------------------------------------
# Tests: OCI-specific skip logic
# ---------------------------------------------------------------------------


class TestShouldSkipOci:
    """Tests for the _should_skip_oci function."""

    def test_skip_oci_contents_all_exist(self, tmp_path):
        """Test skip when all content files exist with valid checksums."""
        from productmd.location import compute_checksum as cc

        dest_dir = str(tmp_path / "images")
        os.makedirs(os.path.join(dest_dir, "pxeboot"))

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

        assert _should_skip_oci(task, verify_checksums=False)

    def test_skip_oci_simple_existing_file(self, tmp_path):
        """Test skip for simple OCI (no contents) when file exists."""
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


# ---------------------------------------------------------------------------
# Tests: OCI localize integration
# ---------------------------------------------------------------------------


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
    @patch("productmd.localize._opener.open")
    def test_mixed_http_and_oci_downloads(self, mock_open, mock_get_downloader, tmp_path):
        """Test that a compose with both HTTP and OCI URLs works."""
        mock_open.return_value = _mock_response(b"http content")
        mock_downloader = MagicMock()
        mock_get_downloader.return_value = mock_downloader

        im = Images()
        im.header.version = "2.0"
        im.compose.id = "Test-1.0-20260204.0"
        im.compose.type = "production"
        im.compose.date = "20260204"
        im.compose.respin = 0
        im.output_version = VERSION_2_0

        img_http = _make_image(im, "Server/x86_64/iso/boot.iso", 512, "a" * 64)
        img_http.location = Location(
            url="https://cdn.example.com/Server/x86_64/iso/boot.iso",
            size=512,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/boot.iso",
        )
        im.add("Server", "x86_64", img_http)

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

        assert result.downloaded == 2
        assert result.failed == 0
        mock_open.assert_called_once()
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

        assert mock_get_downloader.call_count == 2
