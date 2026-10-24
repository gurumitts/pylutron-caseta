"""Regression coverage for the Smart Bridge's no-SNI TLS context."""

import ssl
from unittest.mock import patch

from pylutron_caseta import smartbridge


def test_tls_context_wraps_bio_without_server_hostname() -> None:
    """Allow no-SNI TLS setup while still requiring certificate verification."""
    # Stub certificate file I/O, but use a real SSLContext and wrap_bio().
    with (
        patch.object(ssl.SSLContext, "load_verify_locations"),
        patch.object(ssl.SSLContext, "load_cert_chain"),
    ):
        context = smartbridge.Smartbridge._create_tls_context(
            "client.key", "client.crt", "bridge.crt"
        )

    # create_tls() suppresses SNI; asyncio passes None to wrap_bio().
    # This raises ValueError if hostname checking is accidentally re-enabled.
    context.wrap_bio(ssl.MemoryBIO(), ssl.MemoryBIO(), server_hostname=None)

    assert context.verify_mode == ssl.CERT_REQUIRED
