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

"""
This module provides version detection and handling utilities for ProductMD metadata.

ProductMD supports multiple metadata format versions:

- **v1.x** (1.0, 1.1, 1.2): Local compose format with relative paths
- **v2.0**: Distributed compose format with Location objects

This module provides utilities to:
- Detect the version of a metadata file
- Check version compatibility
- Convert between versions

Example::

    from productmd.version import detect_version, is_v2, VERSION_1_2, VERSION_2_0

    # Detect version from file
    version = detect_version("/path/to/composeinfo.json")
    print(version)  # (2, 0) or (1, 2)

    # Check if v2.0
    if is_v2(version):
        print("This is a v2.0 distributed compose")

    # Version constants
    print(VERSION_2_0)  # (2, 0)
"""

import json
from typing import Tuple, Union, Optional, Any, Dict

__all__ = (
    "VERSION_1_0",
    "VERSION_1_1",
    "VERSION_1_2",
    "VERSION_2_0",
    "CURRENT_VERSION",
    "detect_version",
    "detect_version_from_data",
    "is_v1",
    "is_v2",
    "is_distributed",
    "has_location_objects",
    "get_version_tuple",
    "version_to_string",
    "string_to_version",
    "VersionError",
    "UnsupportedVersionError",
)


# Version constants
VERSION_1_0: Tuple[int, int] = (1, 0)
VERSION_1_1: Tuple[int, int] = (1, 1)
VERSION_1_2: Tuple[int, int] = (1, 2)
VERSION_2_0: Tuple[int, int] = (2, 0)

# Current default version for writing new files
CURRENT_VERSION: Tuple[int, int] = VERSION_1_2

# Minimum version that supports Location objects
MIN_LOCATION_VERSION: Tuple[int, int] = VERSION_2_0


class VersionError(Exception):
    """Base exception for version-related errors."""

    pass


class UnsupportedVersionError(VersionError):
    """Raised when a metadata file has an unsupported version."""

    def __init__(self, version: Tuple[int, int], supported: list = None):
        self.version = version
        self.supported = supported or [VERSION_1_0, VERSION_1_1, VERSION_1_2, VERSION_2_0]
        super().__init__(
            f"Unsupported metadata version: {version_to_string(version)}. "
            f"Supported versions: {', '.join(version_to_string(v) for v in self.supported)}"
        )


def version_to_string(version: Tuple[int, int]) -> str:
    """
    Convert a version tuple to a string.

    :param version: Version tuple (major, minor)
    :type version: tuple
    :return: Version string like "2.0"
    :rtype: str
    """
    return f"{version[0]}.{version[1]}"


def string_to_version(version_str: str) -> Tuple[int, int]:
    """
    Convert a version string to a tuple.

    :param version_str: Version string like "2.0"
    :type version_str: str
    :return: Version tuple (major, minor)
    :rtype: tuple
    :raises ValueError: If version string is invalid
    """
    try:
        parts = version_str.split(".")
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid version string: {version_str}") from e


def get_version_tuple(version: Union[str, Tuple[int, int]]) -> Tuple[int, int]:
    """
    Normalize version to a tuple.

    :param version: Version as string or tuple
    :type version: str or tuple
    :return: Version tuple (major, minor)
    :rtype: tuple
    """
    if isinstance(version, str):
        return string_to_version(version)
    return tuple(version)


def is_v1(version: Union[str, Tuple[int, int]]) -> bool:
    """
    Check if version is v1.x (1.0, 1.1, 1.2).

    :param version: Version to check
    :type version: str or tuple
    :return: True if v1.x
    :rtype: bool
    """
    v = get_version_tuple(version)
    return v[0] == 1


def is_v2(version: Union[str, Tuple[int, int]]) -> bool:
    """
    Check if version is v2.x (2.0+).

    :param version: Version to check
    :type version: str or tuple
    :return: True if v2.x
    :rtype: bool
    """
    v = get_version_tuple(version)
    return v[0] >= 2


def is_distributed(version: Union[str, Tuple[int, int]]) -> bool:
    """
    Check if version supports distributed composes (v2.0+).

    Distributed composes use Location objects with URLs instead of
    simple relative paths.

    :param version: Version to check
    :type version: str or tuple
    :return: True if distributed compose support
    :rtype: bool
    """
    return is_v2(version)


def supports_location_objects(version: Union[str, Tuple[int, int]]) -> bool:
    """
    Check if version supports Location objects.

    :param version: Version to check
    :type version: str or tuple
    :return: True if Location objects are supported
    :rtype: bool
    """
    v = get_version_tuple(version)
    return v >= MIN_LOCATION_VERSION


def detect_version(path: str) -> Tuple[int, int]:
    """
    Detect the version of a metadata file.

    :param path: Path to metadata file (JSON)
    :type path: str
    :return: Version tuple (major, minor)
    :rtype: tuple
    :raises FileNotFoundError: If file doesn't exist
    :raises ValueError: If file is not valid JSON or missing version
    """
    with open(path, "r") as f:
        data = json.load(f)
    return detect_version_from_data(data)


def detect_version_from_data(data: Dict[str, Any]) -> Tuple[int, int]:
    """
    Detect the version from parsed metadata.

    :param data: Parsed JSON data
    :type data: dict
    :return: Version tuple (major, minor)
    :rtype: tuple
    :raises ValueError: If version cannot be determined
    """
    # Check for header.version (standard location)
    if "header" in data and "version" in data["header"]:
        return string_to_version(data["header"]["version"])

    # Legacy format without explicit version
    # Try to infer from structure
    if "payload" in data:
        payload = data["payload"]

        # Check for v2.0 indicators (Location objects)
        if _has_location_in_payload(payload):
            return VERSION_2_0

        # Check for v1.x indicators
        if "rpms" in payload or "images" in payload or "compose" in payload:
            # Default to 1.0 for legacy files without version
            return VERSION_1_0

    raise ValueError("Cannot determine metadata version from data")


def has_location_objects(data: Dict[str, Any]) -> bool:
    """
    Check if metadata contains Location objects (v2.0 format).

    This is useful for detecting v2.0 format even when version
    header hasn't been updated yet.

    :param data: Parsed JSON data
    :type data: dict
    :return: True if Location objects are present
    :rtype: bool
    """
    if "payload" not in data:
        return False
    return _has_location_in_payload(data["payload"])


def _has_location_in_payload(payload: Dict[str, Any]) -> bool:
    """
    Check if payload contains Location objects.

    Location objects are identified by having 'url', 'size', 'checksum',
    and 'local_path' keys together.

    :param payload: Payload section of metadata
    :type payload: dict
    :return: True if Location objects found
    :rtype: bool
    """
    # Check rpms
    if "rpms" in payload:
        for variant in payload["rpms"].values():
            if isinstance(variant, dict):
                for arch in variant.values():
                    if isinstance(arch, dict):
                        for srpm in arch.values():
                            if isinstance(srpm, dict):
                                for rpm in srpm.values():
                                    if isinstance(rpm, dict) and "location" in rpm:
                                        return True

    # Check images
    if "images" in payload:
        for variant in payload["images"].values():
            if isinstance(variant, dict):
                for arch in variant.values():
                    if isinstance(arch, list):
                        for image in arch:
                            if isinstance(image, dict) and "location" in image:
                                return True

    # Check extra_files
    if "extra_files" in payload:
        for variant in payload["extra_files"].values():
            if isinstance(variant, dict):
                for arch in variant.values():
                    if isinstance(arch, list):
                        for item in arch:
                            if isinstance(item, dict) and "location" in item:
                                return True

    # Check variant paths (in composeinfo)
    if "variants" in payload:
        for variant in payload["variants"].values():
            if isinstance(variant, dict) and "paths" in variant:
                paths = variant["paths"]
                for path_type in paths.values():
                    if isinstance(path_type, dict):
                        for arch_path in path_type.values():
                            if isinstance(arch_path, dict) and "url" in arch_path:
                                return True

    return False


def _is_location_object(obj: Any) -> bool:
    """
    Check if an object looks like a Location object.

    :param obj: Object to check
    :type obj: any
    :return: True if it has Location object structure
    :rtype: bool
    """
    if not isinstance(obj, dict):
        return False
    required_keys = {"url", "size", "checksum", "local_path"}
    return required_keys.issubset(obj.keys())


class VersionedMetadataMixin:
    """
    Mixin class providing version-aware serialization/deserialization.

    This mixin can be added to metadata classes to provide automatic
    version detection and handling.

    Usage::

        class MyMetadata(MetadataBase, VersionedMetadataMixin):
            def deserialize(self, data):
                version = self.detect_data_version(data)
                if is_v2(version):
                    self.deserialize_2_0(data)
                else:
                    self.deserialize_1_x(data)
    """

    # Default output version (can be overridden per-class or per-instance)
    _output_version: Optional[Tuple[int, int]] = None

    @property
    def output_version(self) -> Tuple[int, int]:
        """
        Get the version to use when serializing.

        :return: Version tuple
        :rtype: tuple
        """
        if self._output_version is not None:
            return self._output_version
        return CURRENT_VERSION

    @output_version.setter
    def output_version(self, version: Union[str, Tuple[int, int]]):
        """
        Set the version to use when serializing.

        :param version: Version to use
        :type version: str or tuple
        """
        self._output_version = get_version_tuple(version)

    def detect_data_version(self, data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Detect version from parsed data.

        :param data: Parsed metadata
        :type data: dict
        :return: Version tuple
        :rtype: tuple
        """
        return detect_version_from_data(data)

    def should_use_locations(self) -> bool:
        """
        Check if Location objects should be used for output.

        :return: True if using v2.0 format
        :rtype: bool
        """
        return supports_location_objects(self.output_version)
