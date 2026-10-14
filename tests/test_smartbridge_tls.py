"""Tests for the Smart Bridge's no-SNI TLS connection."""

import socket
import ssl
from unittest.mock import AsyncMock, patch, sentinel

import pytest

from pylutron_caseta import smartbridge


@pytest.fixture
def tls_context() -> ssl.SSLContext:
    """Create a real TLS context without reading paired certificate files."""
    with (
        patch.object(ssl.SSLContext, "load_verify_locations") as load_ca,
        patch.object(ssl.SSLContext, "load_cert_chain") as load_client,
    ):
        context = smartbridge.Smartbridge._create_tls_context(
            "client.key", "client.crt", "bridge.crt"
        )

    load_ca.assert_called_once_with("bridge.crt")
    load_client.assert_called_once_with("client.crt", "client.key")
    return context


def test_tls_context_verifies_certificates_without_hostname(
    tls_context: ssl.SSLContext,
) -> None:
    """Only hostname checking should be disabled for the paired bridge."""
    assert tls_context.protocol == ssl.PROTOCOL_TLS_CLIENT
    assert tls_context.check_hostname is False
    assert tls_context.verify_mode == ssl.CERT_REQUIRED
    assert tls_context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_tls_context_wraps_bio_without_server_hostname(
    tls_context: ssl.SSLContext,
) -> None:
    """Allow asyncio's no-SNI TLS setup, including on Python 3.14.8."""
    # asyncio converts server_hostname="" to None before calling wrap_bio().
    connection = tls_context.wrap_bio(
        ssl.MemoryBIO(), ssl.MemoryBIO(), server_hostname=None
    )

    assert isinstance(connection, ssl.SSLObject)


@pytest.mark.asyncio
async def test_create_tls_suppresses_sni(tls_context: ssl.SSLContext) -> None:
    """Pass an empty server hostname and the verified context to LEAP."""
    with (
        patch.object(
            smartbridge.Smartbridge, "_create_tls_context", return_value=tls_context
        ) as context_factory,
        patch.object(smartbridge, "open_connection", new_callable=AsyncMock) as connect,
    ):
        connect.return_value = sentinel.leap
        bridge = smartbridge.Smartbridge.create_tls(
            "192.0.2.1", "client.key", "client.crt", "bridge.crt"
        )

        assert await bridge._connect() is sentinel.leap

    context_factory.assert_called_once_with("client.key", "client.crt", "bridge.crt")
    connect.assert_awaited_once_with(
        "192.0.2.1",
        smartbridge.LEAP_PORT,
        server_hostname="",
        ssl=tls_context,
        family=socket.AF_INET,
    )
