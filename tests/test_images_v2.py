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

"""Tests for v2.0 Image support with Location objects."""

import unittest

from productmd.images import Images, Image
from productmd.location import Location
from productmd.version import VERSION_1_2, VERSION_2_0


class TestImageLocation(unittest.TestCase):
    """Tests for Image.location property."""

    def _create_images(self):
        """Create an Images container."""
        images = Images()
        images.compose.id = "Test-1.0-20240101.0"
        images.compose.date = "20240101"
        images.compose.type = "production"
        images.compose.respin = 0
        return images

    def _create_image(self, images):
        """Create a basic Image object."""
        image = Image(images)
        image.path = "Server/x86_64/iso/test.iso"
        image.mtime = 1704067200
        image.size = 2147483648
        image.volume_id = "Test-1.0"
        image.type = "dvd"
        image.format = "iso"
        image.arch = "x86_64"
        image.disc_number = 1
        image.disc_count = 1
        image.checksums = {"sha256": "a" * 64}
        image.implant_md5 = "b" * 32
        image.bootable = True
        image.subvariant = "Server"
        return image

    def test_location_property_creates_from_v12_fields(self):
        """Test that location property creates Location from v1.2 fields."""
        images = self._create_images()
        image = self._create_image(images)

        loc = image.location
        self.assertIsInstance(loc, Location)
        self.assertEqual(loc.url, "Server/x86_64/iso/test.iso")
        self.assertEqual(loc.local_path, "Server/x86_64/iso/test.iso")
        self.assertEqual(loc.size, 2147483648)
        self.assertEqual(loc.checksum, "sha256:" + "a" * 64)

    def test_location_setter_updates_v12_fields(self):
        """Test that setting location updates v1.2 compatibility fields."""
        images = self._create_images()
        image = self._create_image(images)

        new_loc = Location(
            url="https://cdn.example.com/Server/x86_64/iso/new.iso",
            size=3000000000,
            checksum="sha256:" + "c" * 64,
            local_path="Server/x86_64/iso/new.iso",
        )
        image.location = new_loc

        self.assertEqual(image.path, "Server/x86_64/iso/new.iso")
        self.assertEqual(image.size, 3000000000)
        self.assertEqual(image.checksums, {"sha256": "c" * 64})

    def test_is_remote_property(self):
        """Test is_remote property."""
        images = self._create_images()
        image = self._create_image(images)

        # Local path - not remote
        self.assertFalse(image.is_remote)

        # Set remote location
        image.location = Location(
            url="https://cdn.example.com/test.iso",
            size=1000,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/test.iso",
        )
        self.assertTrue(image.is_remote)


class TestImageSerializationV12(unittest.TestCase):
    """Tests for Image serialization in v1.2 format."""

    def _create_images(self):
        """Create an Images container."""
        images = Images()
        images.compose.id = "Test-1.0-20240101.0"
        images.compose.date = "20240101"
        images.compose.type = "production"
        images.compose.respin = 0
        return images

    def _create_image(self, images):
        """Create a basic Image object."""
        image = Image(images)
        image.path = "Server/x86_64/iso/test.iso"
        image.mtime = 1704067200
        image.size = 2147483648
        image.volume_id = "Test-1.0"
        image.type = "dvd"
        image.format = "iso"
        image.arch = "x86_64"
        image.disc_number = 1
        image.disc_count = 1
        image.checksums = {"sha256": "a" * 64}
        image.implant_md5 = "b" * 32
        image.bootable = True
        image.subvariant = "Server"
        return image

    def test_serialize_v12_format(self):
        """Test serialization in v1.2 format (default)."""
        images = self._create_images()
        image = self._create_image(images)

        result = []
        image.serialize(result, force_version=VERSION_1_2)

        self.assertEqual(len(result), 1)
        data = result[0]
        self.assertIn("path", data)
        self.assertIn("size", data)
        self.assertIn("checksums", data)
        self.assertNotIn("location", data)
        self.assertEqual(data["path"], "Server/x86_64/iso/test.iso")

    def test_deserialize_v12_format(self):
        """Test deserialization from v1.2 format."""
        images = self._create_images()
        image = Image(images)

        data = {
            "path": "Server/x86_64/iso/test.iso",
            "mtime": 1704067200,
            "size": 2147483648,
            "volume_id": "Test-1.0",
            "type": "dvd",
            "format": "iso",
            "arch": "x86_64",
            "disc_number": 1,
            "disc_count": 1,
            "checksums": {"sha256": "a" * 64},
            "implant_md5": "b" * 32,
            "bootable": True,
            "subvariant": "Server",
        }
        image.deserialize(data)

        self.assertEqual(image.path, "Server/x86_64/iso/test.iso")
        self.assertEqual(image.size, 2147483648)
        self.assertIsNone(image._location)


class TestImageSerializationV20(unittest.TestCase):
    """Tests for Image serialization in v2.0 format."""

    def _create_images(self):
        """Create an Images container."""
        images = Images()
        images.compose.id = "Test-1.0-20240101.0"
        images.compose.date = "20240101"
        images.compose.type = "production"
        images.compose.respin = 0
        return images

    def _create_image(self, images):
        """Create a basic Image object."""
        image = Image(images)
        image.path = "Server/x86_64/iso/test.iso"
        image.mtime = 1704067200
        image.size = 2147483648
        image.volume_id = "Test-1.0"
        image.type = "dvd"
        image.format = "iso"
        image.arch = "x86_64"
        image.disc_number = 1
        image.disc_count = 1
        image.checksums = {"sha256": "a" * 64}
        image.implant_md5 = "b" * 32
        image.bootable = True
        image.subvariant = "Server"
        return image

    def test_serialize_v20_format(self):
        """Test serialization in v2.0 format."""
        images = self._create_images()
        image = self._create_image(images)

        result = []
        image.serialize(result, force_version=VERSION_2_0)

        self.assertEqual(len(result), 1)
        data = result[0]
        self.assertIn("location", data)
        self.assertNotIn("path", data)
        self.assertNotIn("size", data)
        self.assertNotIn("checksums", data)

        loc = data["location"]
        self.assertEqual(loc["local_path"], "Server/x86_64/iso/test.iso")
        self.assertEqual(loc["size"], 2147483648)
        self.assertEqual(loc["checksum"], "sha256:" + "a" * 64)

    def test_serialize_v20_with_remote_url(self):
        """Test serialization in v2.0 format with remote URL."""
        images = self._create_images()
        image = self._create_image(images)

        # Set a remote location
        image.location = Location(
            url="https://cdn.example.com/Server/x86_64/iso/test.iso",
            size=2147483648,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/test.iso",
        )

        result = []
        image.serialize(result, force_version=VERSION_2_0)

        loc = result[0]["location"]
        self.assertEqual(loc["url"], "https://cdn.example.com/Server/x86_64/iso/test.iso")

    def test_deserialize_v20_format(self):
        """Test deserialization from v2.0 format."""
        images = self._create_images()
        # Set header version to 2.0 for v2.0 format detection
        images.header.version = "2.0"
        image = Image(images)

        data = {
            "location": {
                "url": "https://cdn.example.com/Server/x86_64/iso/test.iso",
                "size": 2147483648,
                "checksum": "sha256:" + "a" * 64,
                "local_path": "Server/x86_64/iso/test.iso",
            },
            "mtime": 1704067200,
            "volume_id": "Test-1.0",
            "type": "dvd",
            "format": "iso",
            "arch": "x86_64",
            "disc_number": 1,
            "disc_count": 1,
            "implant_md5": "b" * 32,
            "bootable": True,
            "subvariant": "Server",
        }
        image.deserialize(data)

        # Check v2.0 fields
        self.assertIsNotNone(image._location)
        self.assertEqual(image._location.url, "https://cdn.example.com/Server/x86_64/iso/test.iso")
        self.assertTrue(image.is_remote)

        # Check v1.2 compatibility fields
        self.assertEqual(image.path, "Server/x86_64/iso/test.iso")
        self.assertEqual(image.size, 2147483648)
        self.assertEqual(image.checksums, {"sha256": "a" * 64})


class TestImagesContainerVersioning(unittest.TestCase):
    """Tests for Images container version handling."""

    def _create_images_with_image(self):
        """Create an Images container with one image."""
        images = Images()
        images.compose.id = "Test-1.0-20240101.0"
        images.compose.date = "20240101"
        images.compose.type = "production"
        images.compose.respin = 0

        image = Image(images)
        image.path = "Server/x86_64/iso/test.iso"
        image.mtime = 1704067200
        image.size = 2147483648
        image.volume_id = "Test-1.0"
        image.type = "dvd"
        image.format = "iso"
        image.arch = "x86_64"
        image.disc_number = 1
        image.disc_count = 1
        image.checksums = {"sha256": "a" * 64}
        image.implant_md5 = "b" * 32
        image.bootable = True
        image.subvariant = "Server"

        images.add("Server", "x86_64", image)
        return images

    def test_output_version_property(self):
        """Test output_version property."""
        images = Images()
        # Default should be productmd.common.VERSION
        self.assertIsNotNone(images.output_version)

        # Set via tuple
        images.output_version = (2, 0)
        self.assertEqual(images.output_version, (2, 0))

        # Set via string
        images.output_version = "1.2"
        self.assertEqual(images.output_version, (1, 2))

    def test_serialize_v12_container(self):
        """Test Images container serialization in v1.2 format."""
        images = self._create_images_with_image()

        data = {}
        images.serialize(data, force_version=VERSION_1_2)

        self.assertIn("header", data)
        self.assertIn("payload", data)
        self.assertIn("images", data["payload"])

        image_data = data["payload"]["images"]["Server"]["x86_64"][0]
        self.assertIn("path", image_data)
        self.assertNotIn("location", image_data)

    def test_serialize_v20_container(self):
        """Test Images container serialization in v2.0 format."""
        images = self._create_images_with_image()

        data = {}
        images.serialize(data, force_version=VERSION_2_0)

        self.assertIn("header", data)
        self.assertEqual(data["header"]["version"], "2.0")

        image_data = data["payload"]["images"]["Server"]["x86_64"][0]
        self.assertIn("location", image_data)
        self.assertNotIn("path", image_data)


class TestRoundTrip(unittest.TestCase):
    """Tests for round-trip serialization/deserialization."""

    def test_v12_roundtrip(self):
        """Test v1.2 format round-trip."""
        images = Images()
        images.compose.id = "Test-1.0-20240101.0"
        images.compose.date = "20240101"
        images.compose.type = "production"
        images.compose.respin = 0

        image = Image(images)
        image.path = "Server/x86_64/iso/test.iso"
        image.mtime = 1704067200
        image.size = 2147483648
        image.volume_id = "Test-1.0"
        image.type = "dvd"
        image.format = "iso"
        image.arch = "x86_64"
        image.disc_number = 1
        image.disc_count = 1
        image.checksums = {"sha256": "a" * 64}
        image.implant_md5 = "b" * 32
        image.bootable = True
        image.subvariant = "Server"
        images.add("Server", "x86_64", image)

        # Serialize
        data = {}
        images.serialize(data, force_version=VERSION_1_2)

        # Deserialize into new object
        images2 = Images()
        images2.deserialize(data)

        # Check
        image2 = list(images2.images["Server"]["x86_64"])[0]
        self.assertEqual(image2.path, image.path)
        self.assertEqual(image2.size, image.size)
        self.assertEqual(image2.checksums, image.checksums)

    def test_v20_roundtrip(self):
        """Test v2.0 format round-trip."""
        images = Images()
        images.compose.id = "Test-1.0-20240101.0"
        images.compose.date = "20240101"
        images.compose.type = "production"
        images.compose.respin = 0

        image = Image(images)
        image.path = "Server/x86_64/iso/test.iso"
        image.mtime = 1704067200
        image.size = 2147483648
        image.volume_id = "Test-1.0"
        image.type = "dvd"
        image.format = "iso"
        image.arch = "x86_64"
        image.disc_number = 1
        image.disc_count = 1
        image.checksums = {"sha256": "a" * 64}
        image.implant_md5 = "b" * 32
        image.bootable = True
        image.subvariant = "Server"

        # Set remote location
        image.location = Location(
            url="https://cdn.example.com/Server/x86_64/iso/test.iso",
            size=2147483648,
            checksum="sha256:" + "a" * 64,
            local_path="Server/x86_64/iso/test.iso",
        )
        images.add("Server", "x86_64", image)

        # Serialize as v2.0
        data = {}
        images.serialize(data, force_version=VERSION_2_0)

        # Verify header version is 2.0
        self.assertEqual(data["header"]["version"], "2.0")

        # Deserialize into new object
        images2 = Images()
        images2.deserialize(data)

        # Verify header version was read correctly
        self.assertEqual(images2.header.version_tuple, (2, 0))

        # Check
        image2 = list(images2.images["Server"]["x86_64"])[0]
        self.assertEqual(image2.path, "Server/x86_64/iso/test.iso")
        self.assertEqual(image2.size, 2147483648)
        self.assertTrue(image2.is_remote)
        self.assertEqual(image2._location.url, "https://cdn.example.com/Server/x86_64/iso/test.iso")


if __name__ == "__main__":
    unittest.main()
