"""``productmd localize`` subcommand — download distributed v2.0 compose.

Supports both HTTPS/HTTP and OCI registry downloads.  HTTP downloads
support authentication via Bearer token, Basic credentials, or
``~/.netrc``.  OCI downloads require the ``oras-py`` package
(``pip install productmd[oci]``) and support Docker and Podman
credential stores.
"""

import os
import sys

from productmd.cli import add_input_args, load_metadata, print_error
from productmd.cli.progress import make_progress_callback
from productmd.localize import localize_compose


def register(subparsers: object) -> None:
    """Register the localize subcommand.

    :param subparsers: argparse subparsers action
    :type subparsers: object
    """
    parser = subparsers.add_parser(
        "localize",
        help="Download a distributed v2.0 compose to local storage",
        description=(
            "Download all remote artifacts from a v2.0 compose, "
            "recreating the standard v1.2 filesystem layout. "
            "Supports HTTPS/HTTP and OCI registry downloads. "
            "HTTP auth: Bearer token, Basic credentials, or ~/.netrc. "
            "OCI requires oras-py (pip install productmd[oci]). "
            "Writes v1.2 metadata after download."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Local directory to create the compose layout",
    )
    parser.add_argument(
        "--parallel-downloads",
        type=int,
        default=4,
        help="Number of concurrent downloads (default: 4)",
    )
    parser.add_argument(
        "--no-verify-checksums",
        dest="verify_checksums",
        action="store_false",
        default=True,
        help="Skip checksum verification after download (default: verify)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files that already exist with valid checksum",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retry attempts per download (default: 3)",
    )
    parser.add_argument(
        "--no-fail-fast",
        dest="fail_fast",
        action="store_false",
        default=True,
        help="Continue downloading after failures (default: stop on first)",
    )
    parser.add_argument(
        "--netrc-file",
        default=os.environ.get("PRODUCTMD_NETRC_FILE"),
        help=("Path to a netrc file for HTTP credential lookup (default: ~/.netrc). Can also be set via PRODUCTMD_NETRC_FILE env var."),
    )
    parser.add_argument(
        "--http-username",
        default=None,
        help=("Username for HTTP Basic authentication. Takes precedence over netrc credentials."),
    )
    parser.add_argument(
        "--http-password",
        default=os.environ.get("PRODUCTMD_HTTP_PASSWORD"),
        help=("Password for HTTP Basic authentication. Can also be set via PRODUCTMD_HTTP_PASSWORD env var."),
    )
    parser.add_argument(
        "--http-token",
        default=os.environ.get("PRODUCTMD_HTTP_TOKEN"),
        help=(
            "Bearer token for HTTP authentication. "
            "Takes precedence over Basic credentials and netrc. "
            "Mutually exclusive with --http-username/--http-password. "
            "Can also be set via PRODUCTMD_HTTP_TOKEN env var."
        ),
    )
    add_input_args(parser)
    parser.set_defaults(func=run)


def run(args: object) -> None:
    """Execute the localize subcommand.

    :param args: Parsed argparse namespace
    :type args: object
    """
    metadata = load_metadata(args)
    if not metadata:
        print_error(f"No metadata found at {args.input}")
        sys.exit(1)

    if args.http_token and (args.http_username or args.http_password):
        print_error("--http-token is mutually exclusive with --http-username/--http-password")
        sys.exit(2)

    if args.http_username and not args.http_password:
        print_error("--http-username requires --http-password")
        sys.exit(2)

    if args.http_password and not args.http_username:
        print_error("--http-password requires --http-username")
        sys.exit(2)

    progress_callback, cleanup = make_progress_callback(parallel=args.parallel_downloads)

    try:
        result = localize_compose(
            output_dir=args.output,
            parallel_downloads=args.parallel_downloads,
            verify_checksums=args.verify_checksums,
            skip_existing=args.skip_existing,
            retries=args.retries,
            fail_fast=args.fail_fast,
            progress_callback=progress_callback,
            netrc_file=args.netrc_file,
            http_username=args.http_username,
            http_password=args.http_password,
            http_token=args.http_token,
            **metadata,
        )
    finally:
        cleanup()

    print(f"\nDownloaded: {result.downloaded}  Skipped: {result.skipped}  Failed: {result.failed}")

    if result.errors:
        for path, error in result.errors:
            print(f"  FAILED: {path}: {error}", file=sys.stderr)
        sys.exit(1)
