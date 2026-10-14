"""Regression coverage for the Smart Bridge's no-SNI TLS context."""

import ssl
from unittest.mock import patch

from pylutron_caseta import smartbridge


def test_tls_context_wraps_bio_without_server_hostname() -> None:
    """Allow no-SNI TLS setup while retaining paired certificate verification."""
    with (
        patch.object(ssl.SSLContext, "load_verify_locations") as load_ca,
        patch.object(ssl.SSLContext, "load_cert_chain") as load_client,
    ):
        context = smartbridge.Smartbridge._create_tls_context(
            "client.key", "client.crt", "bridge.crt"
        )

    load_ca.assert_called_once_with("bridge.crt")
    load_client.assert_called_once_with("client.crt", "client.key")

    # asyncio converts server_hostname="" to None before calling wrap_bio().
    connection = context.wrap_bio(
        ssl.MemoryBIO(), ssl.MemoryBIO(), server_hostname=None
    )

    assert isinstance(connection, ssl.SSLObject)
    assert context.protocol == ssl.PROTOCOL_TLS_CLIENT
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
