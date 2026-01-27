# ProductMD

[![CI](https://github.com/release-engineering/productmd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/release-engineering/productmd/actions/workflows/ci.yml)
[![CD](https://github.com/release-engineering/productmd/actions/workflows/cd.yml/badge.svg?branch=master)](https://github.com/release-engineering/productmd/actions/workflows/cd.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/productmd)](https://pypi.org/project/productmd)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/productmd)](https://pypi.org/project/productmd)
[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL_v2.1-blue.svg)](https://www.gnu.org/licenses/lgpl-2.1)

**ProductMD** is a Python library for parsing and creating metadata files for OS installation media and compose outputs. It provides structured access to `.treeinfo`, `.discinfo`, and compose metadata files used in Fedora, RHEL, and other RPM-based Linux distributions.

## Features

- **Compose Metadata** - Parse and manipulate compose information, RPM manifests, module metadata, and image manifests
- **TreeInfo** - Read and write `.treeinfo` files describing installable trees
- **DiscInfo** - Handle `.discinfo` files for installation media identification
- **HTTP Support** - Load metadata directly from remote URLs
- **Validation** - Built-in schema validation for metadata integrity

## Installation

```bash
pip install productmd
```

## Quick Start

### Reading Compose Metadata

```python
import productmd

# Load compose metadata from a local path or URL
compose = productmd.Compose("/path/to/compose")

# Access compose information
print(compose.info.compose.id)
print(compose.info.compose.type)
print(compose.info.compose.date)

# List all images in the compose
for variant in compose.images.images:
    for arch in compose.images.images[variant]:
        for image in compose.images.images[variant][arch]:
            print(f"{variant}/{arch}: {image.path}")

# Access RPM metadata
for variant in compose.rpms.rpms:
    for arch in compose.rpms.rpms[variant]:
        for srpm in compose.rpms.rpms[variant][arch]:
            print(f"{variant}/{arch}: {srpm}")
```

### Working with TreeInfo

```python
from productmd import TreeInfo

# Parse a .treeinfo file
ti = TreeInfo()
ti.load("/path/to/.treeinfo")

# Access release information
print(ti.release.name)
print(ti.release.version)
print(ti.tree.arch)

# List variants
for variant in ti.variants:
    print(f"{variant}: {ti.variants[variant].name}")
```

### Working with DiscInfo

```python
from productmd import DiscInfo

# Parse a .discinfo file
di = DiscInfo()
di.load("/path/to/.discinfo")

print(di.timestamp)
print(di.description)
print(di.arch)
```

## Supported Metadata Types

| Class | Description | File Format |
|-------|-------------|-------------|
| `Compose` | High-level compose access | Directory structure |
| `ComposeInfo` | Compose identification and variants | `composeinfo.json` |
| `Rpms` | RPM manifest with checksums | `rpms.json` |
| `Images` | Image manifest (ISOs, qcow2, etc.) | `images.json` |
| `Modules` | Module metadata | `modules.json` |
| `TreeInfo` | Installable tree metadata | `.treeinfo` |
| `DiscInfo` | Installation media identification | `.discinfo` |

## Documentation

Full documentation is available at [productmd.readthedocs.io](http://productmd.readthedocs.io/en/latest/).

## Development

### Prerequisites

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

### Running Tests

```bash
# Run the full test suite
uvx tox

# List available test environments
uvx tox list

# Run a specific environment
uvx tox -e py312
```

### Code Quality

```bash
# Run linter
uvx tox -e lint

# Run formatter
uvx tox -e format

# Run security scanner
uvx tox -e bandit
```

### Building

```bash
uv build
```

### Versioning

Versions are dynamically generated from git tags using [hatch-vcs](https://github.com/ofek/hatch-vcs). To release a new version, tag the commit on the `master` branch.

## License

This project is licensed under the [GNU Lesser General Public License v2.1](LICENSE).
