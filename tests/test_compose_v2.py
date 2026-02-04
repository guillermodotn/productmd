#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Tests for loading and validating v2.0 compose metadata test files.
"""

import json
import os
import unittest

# Path to v2.0 test files
V2_TEST_DIR = os.path.join(os.path.dirname(__file__), "compose-v2", "metadata")


class TestV2ComposeFiles(unittest.TestCase):
    """Test that v2.0 compose test files are valid JSON and have correct structure."""

    def test_composeinfo_v2_structure(self):
        """Test composeinfo.json v2.0 structure."""
        path = os.path.join(V2_TEST_DIR, "composeinfo.json")
        with open(path, "r") as f:
            data = json.load(f)

        # Check header
        self.assertEqual(data["header"]["version"], "2.0")
        self.assertEqual(data["header"]["type"], "productmd.composeinfo")

        # Check payload structure
        payload = data["payload"]
        self.assertIn("compose", payload)
        self.assertIn("release", payload)
        self.assertIn("variants", payload)

        # Check variant paths have Location structure
        server = payload["variants"]["Server"]
        self.assertEqual(server["id"], "Server")
        self.assertIn("paths", server)

        # Check os_tree path has Location fields
        os_tree_x86 = server["paths"]["os_tree"]["x86_64"]
        self.assertIn("url", os_tree_x86)
        self.assertIn("size", os_tree_x86)
        self.assertIn("checksum", os_tree_x86)
        self.assertIn("local_path", os_tree_x86)
        self.assertTrue(os_tree_x86["checksum"].startswith("sha256:"))

    def test_images_v2_structure(self):
        """Test images.json v2.0 structure."""
        path = os.path.join(V2_TEST_DIR, "images.json")
        with open(path, "r") as f:
            data = json.load(f)

        # Check header
        self.assertEqual(data["header"]["version"], "2.0")
        self.assertEqual(data["header"]["type"], "productmd.images")

        # Check images have location instead of path
        images = data["payload"]["images"]
        server_x86 = images["Server"]["x86_64"]
        self.assertGreater(len(server_x86), 0)

        # Check first image has Location structure
        img = server_x86[0]
        self.assertIn("location", img)
        self.assertNotIn("path", img)  # v2.0 uses location, not path
        self.assertNotIn("checksums", img)  # v2.0 uses location.checksum

        loc = img["location"]
        self.assertIn("url", loc)
        self.assertIn("size", loc)
        self.assertIn("checksum", loc)
        self.assertIn("local_path", loc)

    def test_images_oci_contents_structure(self):
        """Test images-oci-contents.json with OCI contents structure."""
        path = os.path.join(V2_TEST_DIR, "images-oci-contents.json")
        with open(path, "r") as f:
            data = json.load(f)

        # Check header
        self.assertEqual(data["header"]["version"], "2.0")

        # Find boot image with contents
        images = data["payload"]["images"]["Server"]["x86_64"]
        boot_images = [i for i in images if i.get("type") == "boot"]
        self.assertGreater(len(boot_images), 0)

        boot_img = boot_images[0]
        loc = boot_img["location"]

        # Check it's an OCI reference
        self.assertTrue(loc["url"].startswith("oci://"))

        # Check contents array
        self.assertIn("contents", loc)
        contents = loc["contents"]
        self.assertGreater(len(contents), 0)

        # Check FileEntry structure
        file_entry = contents[0]
        self.assertIn("file", file_entry)
        self.assertIn("size", file_entry)
        self.assertIn("checksum", file_entry)
        self.assertIn("layer_digest", file_entry)
        self.assertTrue(file_entry["checksum"].startswith("sha256:"))
        self.assertTrue(file_entry["layer_digest"].startswith("sha256:"))

    def test_rpms_v2_structure(self):
        """Test rpms.json v2.0 structure."""
        path = os.path.join(V2_TEST_DIR, "rpms.json")
        with open(path, "r") as f:
            data = json.load(f)

        # Check header
        self.assertEqual(data["header"]["version"], "2.0")
        self.assertEqual(data["header"]["type"], "productmd.rpms")

        # Check RPMs have location
        rpms = data["payload"]["rpms"]
        server_x86 = rpms["Server"]["x86_64"]
        self.assertGreater(len(server_x86), 0)

        # Get first SRPM and its binary RPMs
        srpm_key = list(server_x86.keys())[0]
        srpm_rpms = server_x86[srpm_key]
        rpm_key = list(srpm_rpms.keys())[0]
        rpm = srpm_rpms[rpm_key]

        # Check RPM has location
        self.assertIn("location", rpm)
        loc = rpm["location"]
        self.assertIn("url", loc)
        self.assertIn("size", loc)
        self.assertIn("checksum", loc)
        self.assertIn("local_path", loc)

    def test_extra_files_v2_structure(self):
        """Test extra_files.json v2.0 structure."""
        path = os.path.join(V2_TEST_DIR, "extra_files.json")
        with open(path, "r") as f:
            data = json.load(f)

        # Check header
        self.assertEqual(data["header"]["version"], "2.0")
        self.assertEqual(data["header"]["type"], "productmd.extra_files")

        # Check extra files have location
        extra_files = data["payload"]["extra_files"]
        server_x86 = extra_files["Server"]["x86_64"]
        self.assertGreater(len(server_x86), 0)

        # Check first file has Location structure
        file_entry = server_x86[0]
        self.assertIn("file", file_entry)
        self.assertIn("location", file_entry)

        loc = file_entry["location"]
        self.assertIn("url", loc)
        self.assertIn("size", loc)
        self.assertIn("checksum", loc)
        self.assertIn("local_path", loc)

    def test_modules_v2_structure(self):
        """Test modules.json v2.0 structure."""
        path = os.path.join(V2_TEST_DIR, "modules.json")
        with open(path, "r") as f:
            data = json.load(f)

        # Check header
        self.assertEqual(data["header"]["version"], "2.0")
        self.assertEqual(data["header"]["type"], "productmd.modules")

        # Check modules have location
        modules = data["payload"]["modules"]
        server_x86 = modules["Server"]["x86_64"]
        self.assertGreater(len(server_x86), 0)

        # Get first module
        mod_key = list(server_x86.keys())[0]
        module = server_x86[mod_key]

        # Check module structure
        self.assertIn("name", module)
        self.assertIn("stream", module)
        self.assertIn("version", module)
        self.assertIn("context", module)
        self.assertIn("arch", module)
        self.assertIn("rpms", module)
        self.assertIn("location", module)

        # Check location
        loc = module["location"]
        self.assertIn("url", loc)
        self.assertIn("checksum", loc)

    def test_all_urls_are_valid_format(self):
        """Test that all URLs in v2.0 files are valid format."""
        valid_prefixes = ("https://", "http://", "oci://")

        for filename in os.listdir(V2_TEST_DIR):
            if not filename.endswith(".json"):
                continue

            path = os.path.join(V2_TEST_DIR, filename)
            with open(path, "r") as f:
                data = json.load(f)

            # Recursively find all "url" keys
            urls = self._find_all_urls(data)
            for url in urls:
                self.assertTrue(url.startswith(valid_prefixes), f"Invalid URL format in {filename}: {url}")

    def test_all_checksums_are_sha256(self):
        """Test that all checksums use sha256: prefix."""
        for filename in os.listdir(V2_TEST_DIR):
            if not filename.endswith(".json"):
                continue

            path = os.path.join(V2_TEST_DIR, filename)
            with open(path, "r") as f:
                data = json.load(f)

            # Recursively find all "checksum" keys
            checksums = self._find_all_checksums(data)
            for checksum in checksums:
                self.assertTrue(checksum.startswith("sha256:"), f"Invalid checksum format in {filename}: {checksum}")

    def _find_all_urls(self, obj, urls=None):
        """Recursively find all 'url' values in a nested structure."""
        if urls is None:
            urls = []

        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "url" and isinstance(value, str):
                    urls.append(value)
                else:
                    self._find_all_urls(value, urls)
        elif isinstance(obj, list):
            for item in obj:
                self._find_all_urls(item, urls)

        return urls

    def _find_all_checksums(self, obj, checksums=None):
        """Recursively find all 'checksum' values in a nested structure."""
        if checksums is None:
            checksums = []

        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "checksum" and isinstance(value, str):
                    checksums.append(value)
                else:
                    self._find_all_checksums(value, checksums)
        elif isinstance(obj, list):
            for item in obj:
                self._find_all_checksums(item, checksums)

        return checksums


if __name__ == "__main__":
    unittest.main()
