# -*- coding: utf-8 -*-

# Copyright (C) 2024  Red Hat, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import os
import tempfile
import unittest

from productmd.location import (
    Location,
    FileEntry,
    compute_checksum,
    parse_checksum,
    CHECKSUM_RE,
    OCI_REFERENCE_RE,
)


class TestChecksumUtilities(unittest.TestCase):
    """Tests for checksum utility functions."""

    def test_compute_checksum(self):
        """Test computing checksum of a file."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"hello world\n")
            path = f.name

        try:
            checksum = compute_checksum(path)
            self.assertTrue(checksum.startswith("sha256:"))
            self.assertEqual(len(checksum), 7 + 64)  # "sha256:" + 64 hex chars
        finally:
            os.unlink(path)

    def test_compute_checksum_sha512(self):
        """Test computing checksum with different algorithm."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test data")
            path = f.name

        try:
            checksum = compute_checksum(path, "sha512")
            self.assertTrue(checksum.startswith("sha512:"))
            self.assertEqual(len(checksum), 7 + 128)  # "sha512:" + 128 hex chars
        finally:
            os.unlink(path)

    def test_parse_checksum_valid(self):
        """Test parsing valid checksum strings."""
        algo, digest = parse_checksum("sha256:" + "a" * 64)
        self.assertEqual(algo, "sha256")
        self.assertEqual(digest, "a" * 64)

        algo, digest = parse_checksum("sha512:" + "b" * 128)
        self.assertEqual(algo, "sha512")
        self.assertEqual(digest, "b" * 128)

    def test_parse_checksum_invalid(self):
        """Test parsing invalid checksum strings."""
        with self.assertRaises(ValueError):
            parse_checksum("invalid")

        with self.assertRaises(ValueError):
            parse_checksum("sha256")

        with self.assertRaises(ValueError):
            parse_checksum("sha999:abcd")

    def test_checksum_regex(self):
        """Test checksum regex pattern."""
        self.assertIsNotNone(CHECKSUM_RE.match("sha256:" + "a" * 64))
        self.assertIsNotNone(CHECKSUM_RE.match("sha512:" + "b" * 128))
        self.assertIsNotNone(CHECKSUM_RE.match("sha1:" + "c" * 40))
        self.assertIsNotNone(CHECKSUM_RE.match("md5:" + "d" * 32))
        self.assertIsNone(CHECKSUM_RE.match("sha999:abcd"))
        self.assertIsNone(CHECKSUM_RE.match("invalid"))


class TestOCIReferenceRegex(unittest.TestCase):
    """Tests for OCI reference regex pattern."""

    def test_valid_oci_references(self):
        """Test valid OCI reference patterns."""
        # Full reference with tag and digest
        url = "oci://quay.io/fedora/rpms:bash@sha256:" + "a" * 64
        match = OCI_REFERENCE_RE.match(url)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("registry"), "quay.io")
        self.assertEqual(match.group("repository"), "fedora/rpms")
        self.assertEqual(match.group("tag"), "bash")
        self.assertEqual(match.group("digest"), "sha256:" + "a" * 64)

        # Reference with only digest (no tag)
        url = "oci://registry.example.com/namespace/image@sha256:" + "b" * 64
        match = OCI_REFERENCE_RE.match(url)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("registry"), "registry.example.com")
        self.assertEqual(match.group("repository"), "namespace/image")
        self.assertIsNone(match.group("tag"))

    def test_invalid_oci_references(self):
        """Test invalid OCI reference patterns."""
        # Missing digest
        self.assertIsNone(OCI_REFERENCE_RE.match("oci://quay.io/fedora/rpms:bash"))

        # Wrong scheme
        self.assertIsNone(OCI_REFERENCE_RE.match("https://quay.io/fedora/rpms@sha256:" + "a" * 64))


class TestFileEntry(unittest.TestCase):
    """Tests for FileEntry class."""

    def test_create_file_entry(self):
        """Test creating a FileEntry."""
        entry = FileEntry(
            file="pxeboot/vmlinuz",
            size=11534336,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        self.assertEqual(entry.file, "pxeboot/vmlinuz")
        self.assertEqual(entry.size, 11534336)
        entry.validate()

    def test_file_entry_serialize(self):
        """Test FileEntry serialization."""
        entry = FileEntry(
            file="pxeboot/vmlinuz",
            size=11534336,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        data = entry.serialize()
        self.assertEqual(data["file"], "pxeboot/vmlinuz")
        self.assertEqual(data["size"], 11534336)
        self.assertEqual(data["checksum"], "sha256:" + "a" * 64)
        self.assertEqual(data["layer_digest"], "sha256:" + "b" * 64)

    def test_file_entry_deserialize(self):
        """Test FileEntry deserialization."""
        data = {
            "file": "pxeboot/initrd.img",
            "size": 89478656,
            "checksum": "sha256:" + "c" * 64,
            "layer_digest": "sha256:" + "d" * 64,
        }
        entry = FileEntry.from_dict(data)
        self.assertEqual(entry.file, "pxeboot/initrd.img")
        self.assertEqual(entry.size, 89478656)

    def test_file_entry_equality(self):
        """Test FileEntry equality comparison."""
        entry1 = FileEntry(
            file="test.txt",
            size=100,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        entry2 = FileEntry(
            file="test.txt",
            size=100,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        entry3 = FileEntry(
            file="other.txt",
            size=100,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        self.assertEqual(entry1, entry2)
        self.assertNotEqual(entry1, entry3)

    def test_file_entry_validation_absolute_path(self):
        """Test that absolute paths are rejected."""
        entry = FileEntry(
            file="/absolute/path",
            size=100,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        with self.assertRaises(ValueError):
            entry.validate()

    def test_file_entry_validation_negative_size(self):
        """Test that negative size is rejected."""
        entry = FileEntry(
            file="test.txt",
            size=-100,
            checksum="sha256:" + "a" * 64,
            layer_digest="sha256:" + "b" * 64,
        )
        with self.assertRaises(ValueError):
            entry.validate()

    def test_file_entry_validation_invalid_checksum(self):
        """Test that invalid checksum format is rejected."""
        entry = FileEntry(
            file="test.txt",
            size=100,
            checksum="invalid",
            layer_digest="sha256:" + "b" * 64,
        )
        with self.assertRaises(ValueError):
            entry.validate()


class TestLocation(unittest.TestCase):
    """Tests for Location class."""

    def test_create_https_location(self):
        """Test creating an HTTPS location."""
        loc = Location(
            url="https://cdn.example.com/Packages/bash-5.2.rpm",
            size=1849356,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/bash-5.2.rpm",
        )
        self.assertTrue(loc.is_https)
        self.assertTrue(loc.is_remote)
        self.assertFalse(loc.is_oci)
        self.assertFalse(loc.is_local)
        loc.validate()

    def test_create_oci_location(self):
        """Test creating an OCI location."""
        loc = Location(
            url="oci://quay.io/fedora/rpms:bash@sha256:" + "a" * 64,
            size=1849356,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/bash-5.2.rpm",
        )
        self.assertTrue(loc.is_oci)
        self.assertTrue(loc.is_remote)
        self.assertFalse(loc.is_https)
        self.assertFalse(loc.is_local)
        loc.validate()

    def test_create_local_location(self):
        """Test creating a local relative path location."""
        loc = Location(
            url="Server/x86_64/os/Packages/b/bash-5.2.rpm",
            size=1849356,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/bash-5.2.rpm",
        )
        self.assertTrue(loc.is_local)
        self.assertFalse(loc.is_remote)
        self.assertFalse(loc.is_https)
        self.assertFalse(loc.is_oci)
        loc.validate()

    def test_oci_properties(self):
        """Test OCI-specific properties."""
        loc = Location(
            url="oci://quay.io/fedora/boot-files:server-39-x86_64@sha256:" + "a" * 64,
            size=101376000,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/images",
        )
        self.assertEqual(loc.oci_registry, "quay.io")
        self.assertEqual(loc.oci_repository, "fedora/boot-files")
        self.assertEqual(loc.oci_tag, "server-39-x86_64")
        self.assertEqual(loc.oci_digest, "sha256:" + "a" * 64)

    def test_checksum_properties(self):
        """Test checksum-related properties."""
        loc = Location(
            url="https://example.com/file.rpm",
            size=1000,
            checksum="sha256:" + "abcd" * 16,
            local_path="path/to/file.rpm",
        )
        self.assertEqual(loc.checksum_algorithm, "sha256")
        self.assertEqual(loc.checksum_value, "abcd" * 16)

    def test_location_serialize(self):
        """Test Location serialization."""
        loc = Location(
            url="https://cdn.example.com/file.rpm",
            size=1849356,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/file.rpm",
        )
        data = loc.serialize()
        self.assertEqual(data["url"], "https://cdn.example.com/file.rpm")
        self.assertEqual(data["size"], 1849356)
        self.assertEqual(data["checksum"], "sha256:" + "a" * 64)
        self.assertEqual(data["local_path"], "Server/x86_64/os/Packages/b/file.rpm")
        self.assertNotIn("contents", data)  # No contents = not serialized

    def test_location_serialize_with_contents(self):
        """Test Location serialization with OCI contents."""
        loc = Location(
            url="oci://quay.io/fedora/boot-files:test@sha256:" + "a" * 64,
            size=101376000,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/images",
            contents=[
                FileEntry(
                    file="pxeboot/vmlinuz",
                    size=11534336,
                    checksum="sha256:" + "b" * 64,
                    layer_digest="sha256:" + "b" * 64,
                ),
                FileEntry(
                    file="pxeboot/initrd.img",
                    size=89478656,
                    checksum="sha256:" + "c" * 64,
                    layer_digest="sha256:" + "c" * 64,
                ),
            ],
        )
        data = loc.serialize()
        self.assertIn("contents", data)
        self.assertEqual(len(data["contents"]), 2)
        self.assertEqual(data["contents"][0]["file"], "pxeboot/vmlinuz")
        self.assertEqual(data["contents"][1]["file"], "pxeboot/initrd.img")

    def test_location_deserialize(self):
        """Test Location deserialization."""
        data = {
            "url": "https://cdn.example.com/file.rpm",
            "size": 1849356,
            "checksum": "sha256:" + "a" * 64,
            "local_path": "Server/x86_64/os/Packages/b/file.rpm",
        }
        loc = Location.from_dict(data)
        self.assertEqual(loc.url, "https://cdn.example.com/file.rpm")
        self.assertEqual(loc.size, 1849356)
        self.assertEqual(loc.local_path, "Server/x86_64/os/Packages/b/file.rpm")
        self.assertEqual(loc.contents, [])

    def test_location_deserialize_with_contents(self):
        """Test Location deserialization with OCI contents."""
        data = {
            "url": "oci://quay.io/fedora/boot-files:test@sha256:" + "a" * 64,
            "size": 101376000,
            "checksum": "sha256:" + "a" * 64,
            "local_path": "Server/x86_64/os/images",
            "contents": [
                {
                    "file": "pxeboot/vmlinuz",
                    "size": 11534336,
                    "checksum": "sha256:" + "b" * 64,
                    "layer_digest": "sha256:" + "b" * 64,
                },
            ],
        }
        loc = Location.from_dict(data)
        self.assertTrue(loc.has_contents)
        self.assertEqual(len(loc.contents), 1)
        self.assertEqual(loc.contents[0].file, "pxeboot/vmlinuz")

    def test_location_equality(self):
        """Test Location equality comparison."""
        loc1 = Location(
            url="https://example.com/file.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="path/to/file.rpm",
        )
        loc2 = Location(
            url="https://example.com/file.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="path/to/file.rpm",
        )
        loc3 = Location(
            url="https://example.com/other.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="path/to/other.rpm",
        )
        self.assertEqual(loc1, loc2)
        self.assertNotEqual(loc1, loc3)

    def test_location_validation_absolute_url(self):
        """Test that absolute local paths are rejected."""
        loc = Location(
            url="/absolute/path/to/file.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="path/to/file.rpm",
        )
        with self.assertRaises(ValueError):
            loc.validate()

    def test_location_validation_absolute_local_path(self):
        """Test that absolute local_path is rejected."""
        loc = Location(
            url="https://example.com/file.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="/absolute/path/to/file.rpm",
        )
        with self.assertRaises(ValueError):
            loc.validate()

    def test_location_validation_oci_without_digest(self):
        """Test that OCI URLs without digest are rejected."""
        loc = Location(
            url="oci://quay.io/fedora/rpms:bash",  # Missing @sha256:...
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="path/to/file.rpm",
        )
        with self.assertRaises(ValueError):
            loc.validate()

    def test_location_validation_contents_without_oci(self):
        """Test that contents without OCI URL is rejected."""
        loc = Location(
            url="https://example.com/file.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="path/to/file.rpm",
            contents=[
                FileEntry(
                    file="test.txt",
                    size=100,
                    checksum="sha256:" + "b" * 64,
                    layer_digest="sha256:" + "b" * 64,
                ),
            ],
        )
        with self.assertRaises(ValueError):
            loc.validate()

    def test_with_remote_url(self):
        """Test creating a remote URL from a local location."""
        loc = Location(
            url="Server/x86_64/os/Packages/b/bash.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/bash.rpm",
        )
        remote = loc.with_remote_url("https://cdn.example.com/compose")
        self.assertEqual(
            remote.url,
            "https://cdn.example.com/compose/Server/x86_64/os/Packages/b/bash.rpm",
        )
        self.assertEqual(remote.size, loc.size)
        self.assertEqual(remote.checksum, loc.checksum)
        self.assertEqual(remote.local_path, loc.local_path)

    def test_get_localized_path(self):
        """Test getting the localized filesystem path."""
        loc = Location(
            url="https://example.com/bash.rpm",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/bash.rpm",
        )
        path = loc.get_localized_path("/mnt/compose")
        self.assertEqual(path, "/mnt/compose/compose/Server/x86_64/os/Packages/b/bash.rpm")

    def test_verify_checksum_success(self):
        """Test successful checksum verification."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            path = f.name

        try:
            checksum = compute_checksum(path)
            loc = Location(
                url="https://example.com/test.txt",
                size=12,
                checksum=checksum,
                local_path="test.txt",
            )
            self.assertTrue(loc.verify_checksum(path))
        finally:
            os.unlink(path)

    def test_verify_checksum_failure(self):
        """Test checksum verification failure."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            path = f.name

        try:
            loc = Location(
                url="https://example.com/test.txt",
                size=12,
                checksum="sha256:" + "0" * 64,  # Wrong checksum
                local_path="test.txt",
            )
            with self.assertRaises(ValueError):
                loc.verify_checksum(path)
        finally:
            os.unlink(path)

    def test_verify_size_success(self):
        """Test successful size verification."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            path = f.name

        try:
            loc = Location(
                url="https://example.com/test.txt",
                size=12,
                checksum="sha256:" + "a" * 64,
                local_path="test.txt",
            )
            self.assertTrue(loc.verify_size(path))
        finally:
            os.unlink(path)

    def test_verify_size_failure(self):
        """Test size verification failure."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test content")
            path = f.name

        try:
            loc = Location(
                url="https://example.com/test.txt",
                size=999,  # Wrong size
                checksum="sha256:" + "a" * 64,
                local_path="test.txt",
            )
            with self.assertRaises(ValueError):
                loc.verify_size(path)
        finally:
            os.unlink(path)

    def test_from_local_file(self):
        """Test creating a Location from a local file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            os.makedirs(os.path.join(tmpdir, "Packages", "b"))
            filepath = os.path.join(tmpdir, "Packages", "b", "bash.rpm")
            with open(filepath, "wb") as f:
                f.write(b"fake rpm content")

            loc = Location.from_local_file("Packages/b/bash.rpm", tmpdir)
            self.assertEqual(loc.url, "Packages/b/bash.rpm")
            self.assertEqual(loc.local_path, "Packages/b/bash.rpm")
            self.assertEqual(loc.size, 16)
            self.assertTrue(loc.checksum.startswith("sha256:"))
            loc.validate()


class TestLocationRoundTrip(unittest.TestCase):
    """Test serialization/deserialization round-trips."""

    def test_simple_location_roundtrip(self):
        """Test round-trip for simple HTTPS location."""
        original = Location(
            url="https://cdn.example.com/Packages/bash.rpm",
            size=1849356,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/Packages/b/bash.rpm",
        )
        data = original.serialize()
        restored = Location.from_dict(data)
        self.assertEqual(original, restored)

    def test_oci_location_roundtrip(self):
        """Test round-trip for OCI location with contents."""
        original = Location(
            url="oci://quay.io/fedora/boot-files:test@sha256:" + "a" * 64,
            size=101376000,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/os/images",
            contents=[
                FileEntry(
                    file="pxeboot/vmlinuz",
                    size=11534336,
                    checksum="sha256:" + "b" * 64,
                    layer_digest="sha256:" + "b" * 64,
                ),
                FileEntry(
                    file="pxeboot/initrd.img",
                    size=89478656,
                    checksum="sha256:" + "c" * 64,
                    layer_digest="sha256:" + "c" * 64,
                ),
            ],
        )
        data = original.serialize()
        restored = Location.from_dict(data)
        self.assertEqual(original.url, restored.url)
        self.assertEqual(original.size, restored.size)
        self.assertEqual(original.checksum, restored.checksum)
        self.assertEqual(original.local_path, restored.local_path)
        self.assertEqual(len(original.contents), len(restored.contents))
        self.assertEqual(original.contents[0], restored.contents[0])
        self.assertEqual(original.contents[1], restored.contents[1])


if __name__ == "__main__":
    unittest.main()
