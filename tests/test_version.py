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

import json
import os
import tempfile
import unittest

from productmd.version import (
    VERSION_1_0,
    VERSION_1_1,
    VERSION_1_2,
    VERSION_2_0,
    detect_version,
    detect_version_from_data,
    is_v1,
    is_v2,
    is_distributed,
    supports_location_objects,
    has_location_objects,
    version_to_string,
    string_to_version,
    get_version_tuple,
    UnsupportedVersionError,
)


class TestVersionConstants(unittest.TestCase):
    """Tests for version constants."""

    def test_version_values(self):
        """Test version constant values."""
        self.assertEqual(VERSION_1_0, (1, 0))
        self.assertEqual(VERSION_1_1, (1, 1))
        self.assertEqual(VERSION_1_2, (1, 2))
        self.assertEqual(VERSION_2_0, (2, 0))

    def test_version_ordering(self):
        """Test version comparison."""
        self.assertLess(VERSION_1_0, VERSION_1_1)
        self.assertLess(VERSION_1_1, VERSION_1_2)
        self.assertLess(VERSION_1_2, VERSION_2_0)


class TestVersionConversion(unittest.TestCase):
    """Tests for version conversion utilities."""

    def test_version_to_string(self):
        """Test converting version tuple to string."""
        self.assertEqual(version_to_string((1, 0)), "1.0")
        self.assertEqual(version_to_string((1, 2)), "1.2")
        self.assertEqual(version_to_string((2, 0)), "2.0")

    def test_string_to_version(self):
        """Test converting version string to tuple."""
        self.assertEqual(string_to_version("1.0"), (1, 0))
        self.assertEqual(string_to_version("1.2"), (1, 2))
        self.assertEqual(string_to_version("2.0"), (2, 0))

    def test_string_to_version_invalid(self):
        """Test invalid version string."""
        with self.assertRaises(ValueError):
            string_to_version("invalid")
        with self.assertRaises(ValueError):
            string_to_version("1")
        with self.assertRaises(ValueError):
            string_to_version("a.b")

    def test_get_version_tuple_from_string(self):
        """Test normalizing string to tuple."""
        self.assertEqual(get_version_tuple("2.0"), (2, 0))

    def test_get_version_tuple_from_tuple(self):
        """Test normalizing tuple (passthrough)."""
        self.assertEqual(get_version_tuple((2, 0)), (2, 0))


class TestVersionChecks(unittest.TestCase):
    """Tests for version check utilities."""

    def test_is_v1(self):
        """Test v1.x detection."""
        self.assertTrue(is_v1(VERSION_1_0))
        self.assertTrue(is_v1(VERSION_1_1))
        self.assertTrue(is_v1(VERSION_1_2))
        self.assertFalse(is_v1(VERSION_2_0))
        self.assertTrue(is_v1("1.2"))
        self.assertFalse(is_v1("2.0"))

    def test_is_v2(self):
        """Test v2.x detection."""
        self.assertFalse(is_v2(VERSION_1_0))
        self.assertFalse(is_v2(VERSION_1_1))
        self.assertFalse(is_v2(VERSION_1_2))
        self.assertTrue(is_v2(VERSION_2_0))
        self.assertFalse(is_v2("1.2"))
        self.assertTrue(is_v2("2.0"))

    def test_is_distributed(self):
        """Test distributed compose detection."""
        self.assertFalse(is_distributed(VERSION_1_2))
        self.assertTrue(is_distributed(VERSION_2_0))

    def test_supports_location_objects(self):
        """Test Location object support detection."""
        self.assertFalse(supports_location_objects(VERSION_1_2))
        self.assertTrue(supports_location_objects(VERSION_2_0))


class TestVersionDetection(unittest.TestCase):
    """Tests for version detection from metadata."""

    def test_detect_version_from_data_v12(self):
        """Test detecting v1.2 from data."""
        data = {
            "header": {"version": "1.2", "type": "productmd.images"},
            "payload": {"compose": {}, "images": {}},
        }
        self.assertEqual(detect_version_from_data(data), (1, 2))

    def test_detect_version_from_data_v20(self):
        """Test detecting v2.0 from data."""
        data = {
            "header": {"version": "2.0", "type": "productmd.images"},
            "payload": {"compose": {}, "images": {}},
        }
        self.assertEqual(detect_version_from_data(data), (2, 0))

    def test_detect_version_from_data_legacy(self):
        """Test detecting legacy (no version header) from data."""
        data = {
            "payload": {"compose": {}, "rpms": {}},
        }
        # Should default to 1.0 for legacy
        self.assertEqual(detect_version_from_data(data), (1, 0))

    def test_detect_version_from_file(self):
        """Test detecting version from a file."""
        data = {
            "header": {"version": "1.2", "type": "productmd.images"},
            "payload": {"compose": {}, "images": {}},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            self.assertEqual(detect_version(path), (1, 2))
        finally:
            os.unlink(path)

    def test_detect_version_invalid_data(self):
        """Test error on invalid data."""
        data = {"random": "data"}
        with self.assertRaises(ValueError):
            detect_version_from_data(data)


class TestHasLocationObjects(unittest.TestCase):
    """Tests for Location object detection in metadata."""

    def test_has_location_in_images(self):
        """Test detecting Location objects in images."""
        data = {
            "payload": {
                "images": {
                    "Server": {
                        "x86_64": [
                            {
                                "location": {
                                    "url": "https://example.com/image.iso",
                                    "size": 1000,
                                    "checksum": "sha256:" + "a" * 64,
                                    "local_path": "Server/x86_64/iso/image.iso",
                                },
                                "type": "dvd",
                            }
                        ]
                    }
                }
            }
        }
        self.assertTrue(has_location_objects(data))

    def test_has_location_in_rpms(self):
        """Test detecting Location objects in rpms."""
        data = {
            "payload": {
                "rpms": {
                    "Server": {
                        "x86_64": {
                            "bash-0:5.2-1.src": {
                                "bash-0:5.2-1.x86_64": {
                                    "location": {
                                        "url": "https://example.com/bash.rpm",
                                        "size": 1000,
                                        "checksum": "sha256:" + "a" * 64,
                                        "local_path": "Server/x86_64/os/Packages/b/bash.rpm",
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        self.assertTrue(has_location_objects(data))

    def test_no_location_in_v12(self):
        """Test v1.2 format without Location objects."""
        data = {
            "payload": {
                "images": {
                    "Server": {
                        "x86_64": [
                            {
                                "path": "Server/x86_64/iso/image.iso",
                                "size": 1000,
                                "checksums": {"sha256": "a" * 64},
                                "type": "dvd",
                            }
                        ]
                    }
                }
            }
        }
        self.assertFalse(has_location_objects(data))

    def test_no_payload(self):
        """Test data without payload."""
        data = {"header": {"version": "1.2"}}
        self.assertFalse(has_location_objects(data))


class TestUnsupportedVersionError(unittest.TestCase):
    """Tests for UnsupportedVersionError."""

    def test_error_message(self):
        """Test error message formatting."""
        error = UnsupportedVersionError((3, 0))
        self.assertIn("3.0", str(error))
        self.assertIn("Unsupported", str(error))

    def test_error_attributes(self):
        """Test error attributes."""
        error = UnsupportedVersionError((3, 0))
        self.assertEqual(error.version, (3, 0))
        self.assertIn((1, 2), error.supported)
        self.assertIn((2, 0), error.supported)


if __name__ == "__main__":
    unittest.main()
