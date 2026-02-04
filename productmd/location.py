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
This module provides classes for representing artifact locations in ProductMD 2.0.

Location objects represent where artifacts (RPMs, images, repositories, extra files)
are stored, along with integrity information (checksums, sizes) and local path hints
for v1.2 compatiability.

"""

import hashlib
import os
import re

import productmd.common


__all__ = (
    "Location",
    "FileEntry",
    "compute_checksum",
    "CHECKSUM_ALGO",
    "CHECKSUM_RE",
)


# Default checksum algorithm for v2.0
CHECKSUM_ALGO = "sha256"

# Regex pattern for validating checksum format (algorithm:hexdigest)
CHECKSUM_RE = re.compile(r"^(?P<algorithm>sha256|sha512|sha1|md5):(?P<digest>[a-f0-9]+)$")

# Regex pattern for OCI references
OCI_REFERENCE_RE = re.compile(
    r"^oci://(?P<registry>[^/]+)/(?P<repository>[^:@]+)"
    r"(:(?P<tag>[^@]+))?(@(?P<digest>sha256:[a-f0-9]{64}))$"
)


def compute_checksum(path, algorithm=CHECKSUM_ALGO):
    """
    Compute checksum of a file.

    :param path: Path to file
    :type path: str
    :param algorithm: Hash algorithm (default: sha256)
    :type algorithm: str
    :return: Checksum in "algorithm:hexdigest" format
    :rtype: str
    """
    hasher = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)  # 1MB
            if not chunk:
                break
            hasher.update(chunk)
    return f"{algorithm}:{hasher.hexdigest().lower()}"


def parse_checksum(checksum):
    """
    Parse a checksum string in "algorithm:hexdigest" format.

    :param checksum: Checksum string
    :type checksum: str
    :return: Tuple of (algorithm, hexdigest)
    :rtype: tuple
    :raises ValueError: If checksum format is invalid
    """
    match = CHECKSUM_RE.match(checksum)
    if not match:
        raise ValueError(f"Invalid checksum format: {checksum}")
    return match.group("algorithm"), match.group("digest")


class FileEntry(productmd.common.MetadataBase):
    """
    Represents a file within an OCI image location.

    This is used when an OCI image contains multiple files as layers,
    such as boot files (kernel, initrd, efiboot.img) bundled together.

    Attributes:
        file (str): Relative path of the file within the container/image
        size (int): File size in bytes
        checksum (str): File checksum in "algorithm:hash" format
        layer_digest (str): OCI layer digest containing this file
    """

    def __init__(self, file=None, size=None, checksum=None, layer_digest=None):
        super().__init__()
        self.file = file
        self.size = size
        self.checksum = checksum
        self.layer_digest = layer_digest

    def __repr__(self):
        return f"<FileEntry:{self.file}>"

    def __eq__(self, other):
        if not isinstance(other, FileEntry):
            return False
        return (
            self.file == other.file
            and self.size == other.size
            and self.checksum == other.checksum
            and self.layer_digest == other.layer_digest
        )

    def __hash__(self):
        return hash((self.file, self.size, self.checksum, self.layer_digest))

    # Validation methods

    def _validate_file(self):
        self._assert_type("file", [str])
        self._assert_not_blank("file")
        if self.file.startswith("/"):
            raise ValueError("FileEntry: 'file' must be a relative path: %s" % self.file)

    def _validate_size(self):
        self._assert_type("size", [int])
        if self.size < 0:
            raise ValueError("FileEntry: 'size' must be non-negative: %s" % self.size)

    def _validate_checksum(self):
        self._assert_type("checksum", [str])
        self._assert_not_blank("checksum")
        if not CHECKSUM_RE.match(self.checksum):
            raise ValueError("FileEntry: 'checksum' must be in 'algorithm:hexdigest' format: %s" % self.checksum)

    def _validate_layer_digest(self):
        self._assert_type("layer_digest", [str])
        self._assert_not_blank("layer_digest")
        # Layer digest should be in sha256:... format
        if not self.layer_digest.startswith("sha256:"):
            raise ValueError("FileEntry: 'layer_digest' must start with 'sha256:': %s" % self.layer_digest)

    def serialize(self, parser=None):
        """
        Serialize FileEntry to a dictionary.

        :return: Dictionary representation
        :rtype: dict
        """
        self.validate()
        return {
            "file": self.file,
            "size": self.size,
            "checksum": self.checksum,
            "layer_digest": self.layer_digest,
        }

    def deserialize(self, data):
        """
        Deserialize FileEntry from a dictionary.

        :param data: Dictionary with file entry data
        :type data: dict
        """
        self.file = data["file"]
        self.size = int(data["size"])
        self.checksum = data["checksum"]
        self.layer_digest = data["layer_digest"]
        self.validate()

    @classmethod
    def from_dict(cls, data):
        """
        Create a FileEntry from a dictionary.

        :param data: Dictionary with file entry data
        :type data: dict
        :return: New FileEntry instance
        :rtype: FileEntry
        """
        entry = cls()
        entry.deserialize(data)
        return entry


class Location(productmd.common.MetadataBase):
    """
    Represents artifact location with integrity information.

    A Location object describes where an artifact is stored and provides
    the information needed to:
    - Download it (url)
    - Verify its integrity (checksum, size)
    - Place it in a v1.2 filesystem layout (local_path)

    Attributes:
        url (str): HTTPS URL, OCI reference, or relative path
        size (int): Size in bytes (for OCI images with contents, total image size)
        checksum (str): Checksum in "algorithm:hash" format (e.g., "sha256:abc123...")
        local_path (str): Relative path for v1.2 filesystem layout preservation
        contents (list[FileEntry], optional): For OCI images, list of files
                                              contained in the image (as layers)

    URL Schemes:
        - https:// - Direct HTTPS URL for CDN distribution
        - http:// - HTTP URL (testing only)
        - oci:// - OCI registry reference (must include @sha256:... digest)
        - Relative path - Local compose path (no scheme)
    """

    def __init__(self, url=None, size=None, checksum=None, local_path=None, contents=None):
        super().__init__()
        self.url = url
        self.size = size
        self.checksum = checksum
        self.local_path = local_path
        self.contents = contents or []

    def __repr__(self):
        if self.is_remote:
            return f"<Location:{self.url}>"
        return f"<Location:{self.local_path}>"

    def __eq__(self, other):
        if not isinstance(other, Location):
            return False
        return (
            self.url == other.url
            and self.size == other.size
            and self.checksum == other.checksum
            and self.local_path == other.local_path
            and self.contents == other.contents
        )

    def __hash__(self):
        return hash((self.url, self.size, self.checksum, self.local_path))

    # Properties for URL type detection

    @property
    def is_remote(self):
        """
        Check if the location is a remote URL (not a local relative path).

        :rtype: bool
        """
        if not self.url:
            return False
        return self.url.startswith(("https://", "http://", "oci://"))

    @property
    def is_https(self):
        """
        Check if the location is an HTTPS URL.

        :rtype: bool
        """
        if not self.url:
            return False
        return self.url.startswith("https://")

    @property
    def is_http(self):
        """
        Check if the location is an HTTP URL.

        :rtype: bool
        """
        if not self.url:
            return False
        return self.url.startswith("http://")

    @property
    def is_oci(self):
        """
        Check if the location is an OCI registry reference.

        :rtype: bool
        """
        if not self.url:
            return False
        return self.url.startswith("oci://")

    @property
    def is_local(self):
        """
        Check if the location is a local relative path.

        :rtype: bool
        """
        return not self.is_remote

    @property
    def has_contents(self):
        """
        Check if this location has OCI image contents (multiple files as layers).

        :rtype: bool
        """
        return bool(self.contents)

    @property
    def checksum_algorithm(self):
        """
        Get the checksum algorithm.

        :return: Algorithm name (e.g., "sha256")
        :rtype: str or None
        """
        if not self.checksum:
            return None
        algo, _ = parse_checksum(self.checksum)
        return algo

    @property
    def checksum_value(self):
        """
        Get the checksum hex digest value.

        :return: Hex digest string
        :rtype: str or None
        """
        if not self.checksum:
            return None
        _, digest = parse_checksum(self.checksum)
        return digest

    # OCI-specific properties

    @property
    def oci_registry(self):
        """
        Get the OCI registry hostname (for OCI URLs).

        :return: Registry hostname or None
        :rtype: str or None
        """
        if not self.is_oci:
            return None
        match = OCI_REFERENCE_RE.match(self.url)
        if match:
            return match.group("registry")
        return None

    @property
    def oci_repository(self):
        """
        Get the OCI repository name (for OCI URLs).

        :return: Repository name or None
        :rtype: str or None
        """
        if not self.is_oci:
            return None
        match = OCI_REFERENCE_RE.match(self.url)
        if match:
            return match.group("repository")
        return None

    @property
    def oci_tag(self):
        """
        Get the OCI image tag (for OCI URLs).

        :return: Tag or None
        :rtype: str or None
        """
        if not self.is_oci:
            return None
        match = OCI_REFERENCE_RE.match(self.url)
        if match:
            return match.group("tag")
        return None

    @property
    def oci_digest(self):
        """
        Get the OCI image digest (for OCI URLs).

        :return: Digest (sha256:...) or None
        :rtype: str or None
        """
        if not self.is_oci:
            return None
        match = OCI_REFERENCE_RE.match(self.url)
        if match:
            return match.group("digest")
        return None

    # Validation methods

    def _validate_url(self):
        self._assert_type("url", [str])
        self._assert_not_blank("url")

        # Check for absolute local paths (not allowed)
        if self.url.startswith("/"):
            raise ValueError("Location: 'url' must not be an absolute path: %s" % self.url)

        # Validate OCI URLs have required digest
        if self.is_oci:
            if "@sha256:" not in self.url:
                raise ValueError("Location: OCI URLs must include @sha256:... digest for immutability: %s" % self.url)

    def _validate_size(self):
        self._assert_type("size", [int])
        if self.size < 0:
            raise ValueError("Location: 'size' must be non-negative: %s" % self.size)

    def _validate_checksum(self):
        self._assert_type("checksum", [str])
        self._assert_not_blank("checksum")
        if not CHECKSUM_RE.match(self.checksum):
            raise ValueError("Location: 'checksum' must be in 'algorithm:hexdigest' format: %s" % self.checksum)

    def _validate_local_path(self):
        self._assert_type("local_path", [str])
        self._assert_not_blank("local_path")
        if self.local_path.startswith("/"):
            raise ValueError("Location: 'local_path' must be a relative path: %s" % self.local_path)

    def _validate_contents(self):
        self._assert_type("contents", [list])
        # Contents only make sense for OCI URLs
        if self.contents and not self.is_oci:
            raise ValueError("Location: 'contents' can only be used with OCI URLs: %s" % self.url)
        for entry in self.contents:
            if not isinstance(entry, FileEntry):
                raise TypeError("Location: 'contents' must contain FileEntry objects, got: %s" % type(entry))
            entry.validate()

    # Serialization

    def serialize(self, parser=None):
        """
        Serialize Location to a dictionary.

        :return: Dictionary representation
        :rtype: dict
        """
        self.validate()
        result = {
            "url": self.url,
            "size": self.size,
            "checksum": self.checksum,
            "local_path": self.local_path,
        }
        if self.contents:
            result["contents"] = [entry.serialize() for entry in self.contents]
        return result

    def deserialize(self, data):
        """
        Deserialize Location from a dictionary.

        :param data: Dictionary with location data
        :type data: dict
        """
        self.url = data["url"]
        self.size = int(data["size"])
        self.checksum = data["checksum"]
        self.local_path = data["local_path"]
        self.contents = []
        if "contents" in data:
            for entry_data in data["contents"]:
                self.contents.append(FileEntry.from_dict(entry_data))
        self.validate()

    @classmethod
    def from_dict(cls, data):
        """
        Create a Location from a dictionary.

        :param data: Dictionary with location data
        :type data: dict
        :return: New Location instance
        :rtype: Location
        """
        loc = cls()
        loc.deserialize(data)
        return loc

    @classmethod
    def from_local_file(cls, path, base_dir, compute_integrity=True):
        """
        Create a Location from a local file.

        This is useful when upgrading a v1.2 compose to v2.0 format.

        :param path: Relative path to file (will be used as url and local_path)
        :type path: str
        :param base_dir: Base directory for computing checksum
        :type base_dir: str
        :param compute_integrity: Whether to compute checksum and size
        :type compute_integrity: bool
        :return: New Location instance
        :rtype: Location
        """
        loc = cls()
        loc.url = path
        loc.local_path = path

        if compute_integrity:
            full_path = os.path.join(base_dir, path)
            loc.size = os.path.getsize(full_path)
            loc.checksum = compute_checksum(full_path)
        else:
            loc.size = 0
            loc.checksum = "sha256:" + ("0" * 64)

        return loc

    def with_remote_url(self, base_url):
        """
        Create a new Location with a remote URL based on local_path.

        This is useful when publishing a local compose to a CDN.

        :param base_url: Base URL to prepend to local_path
        :type base_url: str
        :return: New Location instance with remote URL
        :rtype: Location
        """
        base_url = base_url.rstrip("/")
        new_url = f"{base_url}/{self.local_path}"

        return Location(
            url=new_url,
            size=self.size,
            checksum=self.checksum,
            local_path=self.local_path,
            contents=self.contents.copy() if self.contents else None,
        )

    def get_localized_path(self, output_dir):
        """
        Get the full filesystem path for localizing this artifact.

        :param output_dir: Base output directory
        :type output_dir: str
        :return: Full path where artifact should be written
        :rtype: str
        """
        return os.path.join(output_dir, "compose", self.local_path)

    def verify_checksum(self, path):
        """
        Verify that a file matches this location's checksum.

        :param path: Path to file to verify
        :type path: str
        :return: True if checksum matches
        :rtype: bool
        :raises ValueError: If checksum does not match
        """
        algo = self.checksum_algorithm
        actual = compute_checksum(path, algo)
        if actual != self.checksum:
            raise ValueError(f"Checksum mismatch for {path}: expected {self.checksum}, got {actual}")
        return True

    def verify_size(self, path):
        """
        Verify that a file matches this location's size.

        :param path: Path to file to verify
        :type path: str
        :return: True if size matches
        :rtype: bool
        :raises ValueError: If size does not match
        """
        actual = os.path.getsize(path)
        if actual != self.size:
            raise ValueError(f"Size mismatch for {path}: expected {self.size}, got {actual}")
        return True

    def verify(self, path):
        """
        Verify that a file matches this location's size and checksum.

        :param path: Path to file to verify
        :type path: str
        :return: True if both size and checksum match
        :rtype: bool
        """
        self.verify_size(path)
        self.verify_checksum(path)
        return True
