# ProductMD

[![CI](https://github.com/release-engineering/productmd/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/release-engineering/productmd/actions/workflows/ci.yml)
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
This will generate the **source** and **wheel** packages under the `dist` directory.

### Versioning

Versions are dynamically generated from git tags using [hatch-vcs](https://github.com/ofek/hatch-vcs). To release a new version, tag the commit on the `master` branch.

## License

This project is licensed under the [GNU Lesser General Public License v2.1](LICENSE).
