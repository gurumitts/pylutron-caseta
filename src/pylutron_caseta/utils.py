"""Utilities for pylutron_caseta."""

import asyncio
import ssl
import sys

if sys.version_info[:2] < (3, 11):
    from async_timeout import timeout as asyncio_timeout
else:
    from asyncio import timeout as asyncio_timeout


def _make_tls_context(keyfile: str, certfile: str, ca_certs: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(ca_certs)
    context.load_cert_chain(certfile, keyfile)
    context.check_hostname = False
    return context


"""Create a TLS context for the Smart Bridge."""


async def make_tls_context(
    keyfile: str, certfile: str, ca_certs: str
) -> ssl.SSLContext:
    return await asyncio.get_running_loop().run_in_executor(
        None, _make_tls_context, keyfile, certfile, ca_certs
    )


__all__ = ["asyncio_timeout", "make_tls_context"]
