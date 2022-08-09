"""Guide the user through pairing and save the necessary files."""

import asyncio
import json
import logging
import socket
import ssl
import tempfile
from typing import Callable, Optional, Tuple, TypedDict
import os

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID  # type: ignore

from .assets import LAP_CA_PEM, LAP_CERT_PEM, LAP_KEY_PEM, LUTRON_ROOT_CA_PEM

LOGGER = logging.getLogger(__name__)

CERT_COMMON_NAME = "pylutron_caseta"

SOCKET_TIMEOUT = 10
BUTTON_PRESS_TIMEOUT = 180
CERT_SUBJECT = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CERT_COMMON_NAME)])

PAIR_KEY = "key"
PAIR_CERT = "cert"
PAIR_CA = "ca"
PAIR_VERSION = "version"


class PairingData(TypedDict):
    """The certificate information from a successful pairing operation."""

    key: str
    cert: str
    ca: str
    version: str


class JsonSocket:
    """A socket that reads and writes json objects."""

    def __init__(self, reader, writer):
        """Create a JsonSocket wrapping the provided socket."""
        self._writer = writer
        self._reader = reader

    async def async_read_json(self, timeout):
        """Read an object."""
        buffer = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        if buffer == b"":
            return None

        LOGGER.debug("received: %s", buffer)
        return json.loads(buffer.decode("UTF-8"))

    async def async_write_json(self, obj):
        """Write an object."""
        buffer = f"{json.dumps(obj)}\r\n".encode("ASCII")
        self._writer.write(buffer)
        LOGGER.debug("sent: %s", buffer)

    def __del__(self):
        """Cleanup when the object is deleted."""
        self._writer.close()


async def async_pair(
    server_addr: str, ready: Optional[Callable[[], None]] = None
) -> PairingData:
    """Pair with a lutron bridge."""
    loop = asyncio.get_running_loop()
    csr, key_bytes_pem, ssl_context = await loop.run_in_executor(
        None, _generate_csr_with_ssl_context
    )

    try:
        cert_pem, ca_pem = await _async_generate_certificate(
            server_addr, ssl_context, csr, ready
        )
    except ssl.SSLCertVerificationError:
        # SSL certificate verification error - might be an RA3 processor,
        # try to connect using the lutron-root certificate instead of LAP_CA
        ssl_context.load_verify_locations(cadata=LUTRON_ROOT_CA_PEM)
        cert_pem, ca_pem = await _async_generate_certificate(
            server_addr, ssl_context, csr, ready
        )
        # Generate certificates worked with RA3 lutron-root so bridge is RA3.
        # Discard the ca_pem for caseta and replace with LUTRON_ROOT_CA_PEM
        ca_pem = LUTRON_ROOT_CA_PEM

    signed_ssl_context = await loop.run_in_executor(
        None, _generate_signed_ssl_context, key_bytes_pem, cert_pem, ca_pem
    )

    leap_response = await _async_verify_certificate(server_addr, signed_ssl_context)

    version = leap_response["Body"]["PingResponse"]["LEAPVersion"]

    LOGGER.debug(
        "Successfully connected to bridge, running LEAP Server version %s", version
    )

    return {
        "key": key_bytes_pem.decode("ASCII"),
        "cert": cert_pem,
        "ca": ca_pem,
        "version": version,
    }


async def _async_generate_certificate(
    server_addr: str,
    ssl_context: ssl.SSLContext,
    csr: x509.CertificateSigningRequest,
    ready: Optional[Callable[[], None]],
) -> Tuple[str, str]:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            server_addr,
            8083,
            server_hostname="",
            ssl=ssl_context,
            family=socket.AF_INET,
        ),
        timeout=SOCKET_TIMEOUT,
    )

    json_socket = JsonSocket(reader, writer)
    LOGGER.info("Press the small black button on the back of the Caseta bridge...")
    if ready is not None:
        ready()
    while True:
        message = await json_socket.async_read_json(BUTTON_PRESS_TIMEOUT)
        if message.get("Header", {}).get("ContentType", "").startswith(
            "status;"
        ) and "PhysicalAccess" in (
            message.get("Body", {}).get("Status", {}).get("Permissions", [])
        ):
            break

    LOGGER.debug("Getting my certificate...")
    csr_text = csr.public_bytes(serialization.Encoding.PEM).decode("ASCII")
    await json_socket.async_write_json(
        {
            "Header": {
                "RequestType": "Execute",
                "Url": "/pair",
                "ClientTag": "get-cert",
            },
            "Body": {
                "CommandType": "CSR",
                "Parameters": {
                    "CSR": csr_text,
                    "DisplayName": CERT_COMMON_NAME,
                    "DeviceUID": "000000000000",
                    "Role": "Admin",
                },
            },
        }
    )
    while True:
        message = await json_socket.async_read_json(SOCKET_TIMEOUT)
        if message.get("Header", {}).get("ClientTag") == "get-cert":
            break
    signing_result = message["Body"]["SigningResult"]
    LOGGER.debug("Got certificates")
    return signing_result["Certificate"], signing_result["RootCertificate"]


def _generate_private_key():
    LOGGER.info("Generating a new private key...")
    return rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )


def _convert_private_key_to_pem(private_key) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _generate_csr(private_key) -> x509.CertificateSigningRequest:
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(CERT_SUBJECT)
        .sign(private_key, hashes.SHA256(), default_backend())
    )


async def _async_verify_certificate(server_addr, signed_ssl_context):
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            server_addr,
            8081,
            server_hostname="",
            ssl=signed_ssl_context,
            family=socket.AF_INET,
        ),
        timeout=SOCKET_TIMEOUT,
    )
    json_socket = JsonSocket(reader, writer)

    await json_socket.async_write_json(
        {
            "CommuniqueType": "ReadRequest",
            "Header": {"Url": "/server/1/status/ping"},
        }
    )

    while True:
        leap_response = await json_socket.async_read_json(SOCKET_TIMEOUT)
        if leap_response.get("CommuniqueType") == "ReadResponse":
            return leap_response


def _generate_csr_with_ssl_context() -> Tuple[
    x509.CertificateSigningRequest, bytes, ssl.SSLContext
]:
    with tempfile.NamedTemporaryFile(delete=False) as lap_cert_temp_file:
        with tempfile.NamedTemporaryFile(delete=False) as lap_key_temp_file:
            try:
                private_key = _generate_private_key()
                key_bytes_pem = _convert_private_key_to_pem(private_key)

                csr = _generate_csr(private_key)

                lap_cert_temp_file.write(LAP_CERT_PEM.encode("ASCII"))
                lap_cert_temp_file.flush()
                lap_key_temp_file.write(LAP_KEY_PEM.encode("ASCII"))
                lap_key_temp_file.flush()

                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                ssl_context.load_verify_locations(cadata=LAP_CA_PEM)
                ssl_context.load_cert_chain(
                    lap_cert_temp_file.name, lap_key_temp_file.name
                )
                ssl_context.verify_mode = ssl.CERT_REQUIRED

                return csr, key_bytes_pem, ssl_context
            finally:
                lap_key_temp_file.close()
                lap_cert_temp_file.close()
                os.remove(lap_key_temp_file.name)
                os.remove(lap_cert_temp_file.name)


def _generate_signed_ssl_context(key_bytes_pem, cert_pem, ca_pem):
    with tempfile.NamedTemporaryFile(delete=False) as key_temp_file:
        key_temp_file.write(key_bytes_pem)
        key_temp_file.flush()

        with tempfile.NamedTemporaryFile(delete=False) as cert_temp_file:
            try:
                cert_temp_file.write(cert_pem.encode("ASCII"))
                cert_temp_file.flush()

                signed_ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                signed_ssl_context.load_verify_locations(cadata=ca_pem)
                signed_ssl_context.load_cert_chain(
                    cert_temp_file.name, key_temp_file.name
                )
                signed_ssl_context.verify_mode = ssl.CERT_REQUIRED

                return signed_ssl_context
            finally:
                key_temp_file.close()
                cert_temp_file.close()
                os.remove(key_temp_file.name)
                os.remove(cert_temp_file.name)
