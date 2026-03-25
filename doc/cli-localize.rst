productmd-localize
==================

Synopsis
--------

**productmd localize** **--output** *DIR* [**--parallel-downloads** *N*] [**--no-verify-checksums**] [**--skip-existing**] [**--retries** *N*] [**--no-fail-fast**] [**--http-username** *USER*] [**--netrc-file** *PATH*] *input*

Description
-----------

Download all remote artifacts from a v2.0 compose to local storage,
recreating the standard v1.2 filesystem layout.  After downloading,
writes v1.2 metadata files to the output directory.

Supports both HTTPS/HTTP and OCI registry downloads.  HTTP downloads
run in parallel using a thread pool.  OCI downloads also run in parallel,
with each thread using its own registry connection for thread safety.

After all downloads complete, v1.2 metadata files are written to
``<output>/compose/metadata/``.

Options
-------

**--output** *DIR*
    Local directory to create the compose layout.  Required.
    The compose tree is created under ``<DIR>/compose/``.

**--parallel-downloads** *N*
    Number of concurrent download threads.  Default: 4.
    Applies to both HTTP and OCI downloads.  Set to 1 for sequential
    downloads.

**--no-verify-checksums**
    Skip SHA-256 checksum verification after each download.
    By default, checksums are verified and mismatches cause an error.

**--skip-existing**
    Skip files that already exist on disk.  When combined with
    checksum verification (the default), only skips files whose
    checksums match the metadata.  Useful for resuming interrupted
    downloads.

**--retries** *N*
    Number of retry attempts per HTTP download.  Default: 3.
    Uses exponential backoff between retries (1s, 2s, 4s, ...).
    Does not apply to OCI downloads (oras-py handles its own retries).

**--no-fail-fast**
    Continue downloading after failures instead of stopping on the
    first error.  By default, the tool stops immediately when any
    download fails.  With this flag, all errors are collected and
    reported at the end.

*input*
    Path to a v2.0 metadata file or compose directory.  Auto-detected.

HTTP Authentication
-------------------

HTTP downloads support authentication for accessing protected content
servers (e.g. Pulp).  Three mechanisms are available, resolved in the
following precedence order (highest first):

1. **Bearer token** — ``$PRODUCTMD_HTTP_TOKEN``
2. **Basic credentials** — ``--http-username`` + ``$PRODUCTMD_HTTP_PASSWORD``
3. **Netrc** — automatic lookup from ``~/.netrc`` (or ``--netrc-file``)

Only one of Bearer token or Basic credentials may be specified.
Setting ``$PRODUCTMD_HTTP_TOKEN`` together with
``--http-username``/``$PRODUCTMD_HTTP_PASSWORD`` is an error.

.. note::

   Sensitive credentials (password and token) are provided exclusively
   via environment variables to avoid leaking them in shell history or
   process listings.

.. note::

   When using ``$PRODUCTMD_HTTP_TOKEN`` or
   ``--http-username``/``$PRODUCTMD_HTTP_PASSWORD``, the credentials
   are sent to **all** HTTP download hosts referenced in the compose
   metadata.  If your compose references multiple hosts, use
   ``~/.netrc`` instead — it resolves credentials per hostname
   automatically.

When no explicit credentials are given, the tool automatically checks
``~/.netrc`` for entries matching the download URL hostname.  This is
transparent and requires no CLI flags.

**--http-username** *USER*
    Username for HTTP Basic authentication.  Password must be set via
    the ``PRODUCTMD_HTTP_PASSWORD`` environment variable.  Takes
    precedence over netrc credentials.  For Bearer token auth, set
    ``PRODUCTMD_HTTP_TOKEN`` instead.

**--netrc-file** *PATH*
    Path to a netrc file for credential lookup.  Default: ``~/.netrc``.
    Can also be set via the ``PRODUCTMD_NETRC_FILE`` environment variable.
    Useful in CI/automation or containerized environments where
    ``~/.netrc`` is not available.

The netrc file uses the standard format::

    machine pulp.example.com
    login admin
    password secret123

Credentials are matched by hostname.  Different hosts can have
different credentials in the same netrc file.

.. note::

   Authorization headers are automatically stripped when an HTTP
   redirect points to a different origin (scheme, host, or port),
   preventing credential leakage to third-party servers such as CDNs
   or S3 presigned URLs.  This matches curl's default behavior.

OCI Support
-----------

Artifacts stored in OCI registries (URLs starting with ``oci://``)
require the **oras-py** package::

    pip install productmd[oci]

Authentication uses standard Docker and Podman credential stores.
Run ``docker login`` or ``podman login`` before using **productmd
localize** with OCI registry URLs.  Credentials are discovered from
the following locations in order:

1. ``$REGISTRY_AUTH_FILE`` (Podman/Skopeo)
2. ``$XDG_RUNTIME_DIR/containers/auth.json`` (Podman runtime)
3. ``$XDG_CONFIG_HOME/containers/auth.json`` (Podman persistent)
4. ``$DOCKER_CONFIG/config.json`` (Docker env override)
5. ``~/.docker/config.json`` (Docker default)

If OCI URLs are present in the metadata but oras-py is not installed,
the tool exits with an error message.

Examples
--------

Download a distributed compose::

    productmd localize \
        --output /mnt/local \
        --parallel-downloads 8 \
        images.json

Resume an interrupted download::

    productmd localize \
        --output /mnt/local \
        --skip-existing \
        images.json

Download without checksum verification::

    productmd localize \
        --output /mnt/local \
        --no-verify-checksums \
        images.json

Continue after failures::

    productmd localize \
        --output /mnt/local \
        --no-fail-fast \
        images.json

Download with a Bearer token::

    export PRODUCTMD_HTTP_TOKEN=eyJhbGciOiJSUzI1NiIs...
    productmd localize \
        --output /mnt/local \
        images.json

Download with Basic auth (password via env var)::

    export PRODUCTMD_HTTP_PASSWORD=secret123
    productmd localize \
        --output /mnt/local \
        --http-username admin \
        images.json

Download using a custom netrc file::

    productmd localize \
        --output /mnt/local \
        --netrc-file /run/secrets/netrc \
        images.json

See Also
--------

**productmd**\(1),
**productmd-upgrade**\(1),
**productmd-verify**\(1)
