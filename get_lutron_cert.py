"""Guide the user through pairing and save the necessary files."""

# `python -m venv env`
# bash: `source ./env/bin/activate`
# powershell: `./env/scripts/activate.ps1`
# `pip install pyOpenSSL==19.1.0`
# `python get_lutron_cert.py`

# your client key         -> caseta.key
# your client certificate -> caseta.crt
# your bridge certificate -> caseta-bridge.crt

# when setting up Home Assistant, use the following configuration:
# lutron_caseta:
#   host: <bridge IP>
#   keyfile: caseta.key
#   certfile: caseta.crt
#   ca_certs: caseta-bridge.crt

import json
import logging
import socket
import ssl

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from OpenSSL import SSL, crypto

logging.basicConfig(level=logging.INFO)

LOGGER = logging.getLogger("get_lutron_cert")

CERT_SUBJECT = x509.Name(
    [x509.NameAttribute(NameOID.COMMON_NAME, "get_lutron_cert.py")]
)

KEY_NAME = "caseta.key"
CERT_NAME = "caseta.crt"
CA_CERT_NAME = "caseta-bridge.crt"

LAP_CA = crypto.load_certificate(
    crypto.FILETYPE_PEM,
    """
-----BEGIN CERTIFICATE-----
MIIEsjCCA5qgAwIBAgIBATANBgkqhkiG9w0BAQ0FADCBlzELMAkGA1UEBhMCVVMx
FTATBgNVBAgTDFBlbm5zeWx2YW5pYTElMCMGA1UEChMcTHV0cm9uIEVsZWN0cm9u
aWNzIENvLiwgSW5jLjEUMBIGA1UEBxMLQ29vcGVyc2J1cmcxNDAyBgNVBAMTK0Nh
c2V0YSBMb2NhbCBBY2Nlc3MgUHJvdG9jb2wgQ2VydCBBdXRob3JpdHkwHhcNMTUx
MDMxMDAwMDAwWhcNMzUxMDMxMDAwMDAwWjCBlzELMAkGA1UEBhMCVVMxFTATBgNV
BAgTDFBlbm5zeWx2YW5pYTElMCMGA1UEChMcTHV0cm9uIEVsZWN0cm9uaWNzIENv
LiwgSW5jLjEUMBIGA1UEBxMLQ29vcGVyc2J1cmcxNDAyBgNVBAMTK0Nhc2V0YSBM
b2NhbCBBY2Nlc3MgUHJvdG9jb2wgQ2VydCBBdXRob3JpdHkwggEiMA0GCSqGSIb3
DQEBAQUAA4IBDwAwggEKAoIBAQDamUREO0dENJxvxdbsDATdDFq+nXdbe62XJ4hI
t15nrUolwv7S28M/6uPPFtRSJW9mwvk/OKDlz0G2D3jw6SdzV3I7tNzvDptvbAL2
aDy9YNp9wTub/pLF6ONDa56gfAxsPQnMBwgoZlKqNQQsjykiyBv8FX42h3Nsa+Bl
q3hjnZEdOAkdn0rvCWD605c0+VWWOWm2vv7bwyOsfgsvCPxooAyBhTDeA0JPjVE/
wHPfiDF3WqA8JzWv4Ibvkg1g33oD6lG8LulWKDS9TPBYF+cvJ40aFPMreMoAQcrX
uD15vaS7iWXKI+anVrBpqE6pRkwLhR+moFjv5GZ+9oP8eawzAgMBAAGjggEFMIIB
ATAMBgNVHRMEBTADAQH/MB0GA1UdDgQWBBSB7qznOajKywOtZypVvV7ECAsgZjCB
xAYDVR0jBIG8MIG5gBSB7qznOajKywOtZypVvV7ECAsgZqGBnaSBmjCBlzELMAkG
A1UEBhMCVVMxFTATBgNVBAgTDFBlbm5zeWx2YW5pYTElMCMGA1UEChMcTHV0cm9u
IEVsZWN0cm9uaWNzIENvLiwgSW5jLjEUMBIGA1UEBxMLQ29vcGVyc2J1cmcxNDAy
BgNVBAMTK0Nhc2V0YSBMb2NhbCBBY2Nlc3MgUHJvdG9jb2wgQ2VydCBBdXRob3Jp
dHmCAQEwCwYDVR0PBAQDAgG+MA0GCSqGSIb3DQEBDQUAA4IBAQB9UDVi2DQI7vHp
F2Lape8SCtcdGEY/7BV4a3F+Xp9WxpE4bVtwoHlb+HG4tYQk9LO7jReE3VBmzvmU
aj+Y3xa25PSb+/q6U6MuY5OscyWo6ZGwtlsrWcP5xsey950WLwW6i8mfIkqFf6uT
gPbUjLsOstB4p7PQVpFgS2rP8h50Psue+XtUKRpR+JSBrHXKX9VuU/aM4PYexSvF
WSHa2HEbjvp6ccPm53/9/EtOtzcUMNspKt3YzABAoQ5/69nebRtC5lWjFI0Ga6kv
zKyu/aZJXWqskHkMz+Mbnky8tP37NmVkMnmRLCfdCG0gHiq/C2tjWDfPQID6HY0s
zq38av5E
-----END CERTIFICATE-----
""",
)

LAP_CERT = crypto.load_certificate(
    crypto.FILETYPE_PEM,
    """
-----BEGIN CERTIFICATE-----
MIIECjCCAvKgAwIBAgIBAzANBgkqhkiG9w0BAQ0FADCBlzELMAkGA1UEBhMCVVMx
FTATBgNVBAgTDFBlbm5zeWx2YW5pYTElMCMGA1UEChMcTHV0cm9uIEVsZWN0cm9u
aWNzIENvLiwgSW5jLjEUMBIGA1UEBxMLQ29vcGVyc2J1cmcxNDAyBgNVBAMTK0Nh
c2V0YSBMb2NhbCBBY2Nlc3MgUHJvdG9jb2wgQ2VydCBBdXRob3JpdHkwHhcNMTUx
MDMxMDAwMDAwWhcNMzUxMDMxMDAwMDAwWjB+MQswCQYDVQQGEwJVUzEVMBMGA1UE
CBMMUGVubnN5bHZhbmlhMSUwIwYDVQQKExxMdXRyb24gRWxlY3Ryb25pY3MgQ28u
LCBJbmMuMRQwEgYDVQQHEwtDb29wZXJzYnVyZzEbMBkGA1UEAxMSQ2FzZXRhIEFw
cGxpY2F0aW9uMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyAOELqTw
WNkF8ofSYJ9QkOHAYMmkVSRjVvZU2AqFfaZYCfWLoors7EBeQrsuGyojqxCbtRUd
l2NQrkPrGVw9cp4qsK54H8ntVadNsYi7KAfDW8bHQNf3hzfcpe8ycXcdVPZram6W
pM9P7oS36jV2DLU59A/OGkcO5AkC0v5ESqzab3qaV3ZvELP6qSt5K4MaJmm8lZT2
6deHU7Nw3kR8fv41qAFe/B0NV7IT+hN+cn6uJBxG5IdAimr4Kl+vTW9tb+/Hh+f+
pQ8EzzyWyEELRp2C72MsmONarnomei0W7dVYbsgxUNFXLZiXBdtNjPCMv1u6Znhm
QMIu9Fhjtz18LwIDAQABo3kwdzAJBgNVHRMEAjAAMB0GA1UdDgQWBBTiN03yqw/B
WK/jgf6FNCZ8D+SgwDAfBgNVHSMEGDAWgBSB7qznOajKywOtZypVvV7ECAsgZjAL
BgNVHQ8EBAMCBaAwHQYDVR0lBBYwFAYIKwYBBQUHAwEGCCsGAQUFBwMCMA0GCSqG
SIb3DQEBDQUAA4IBAQABdgPkGvuSBCwWVGO/uzFEIyRius/BF/EOZ7hMuZluaF05
/FT5PYPWg+UFPORUevB6EHyfezv+XLLpcHkj37sxhXdDKB4rrQPNDY8wzS9DAqF4
WQtGMdY8W9z0gDzajrXRbXkYLDEXnouUWA8+AblROl1Jr2GlUsVujI6NE6Yz5JcJ
zDLVYx7pNZkhYcmEnKZ30+ICq6+0GNKMW+irogm1WkyFp4NHiMCQ6D2UMAIMfeI4
xsamcaGquzVMxmb+Py8gmgtjbpnO8ZAHV6x3BG04zcaHRDOqyA4g+Xhhbxp291c8
B31ZKg0R+JaGyy6ZpE5UPLVyUtLlN93V2V8n66kR
-----END CERTIFICATE-----
""",
)

LAP_KEY = crypto.load_privatekey(
    crypto.FILETYPE_PEM,
    """
-----BEGIN RSA PRIVATE KEY-----
MIIEpQIBAAKCAQEAyAOELqTwWNkF8ofSYJ9QkOHAYMmkVSRjVvZU2AqFfaZYCfWL
oors7EBeQrsuGyojqxCbtRUdl2NQrkPrGVw9cp4qsK54H8ntVadNsYi7KAfDW8bH
QNf3hzfcpe8ycXcdVPZram6WpM9P7oS36jV2DLU59A/OGkcO5AkC0v5ESqzab3qa
V3ZvELP6qSt5K4MaJmm8lZT26deHU7Nw3kR8fv41qAFe/B0NV7IT+hN+cn6uJBxG
5IdAimr4Kl+vTW9tb+/Hh+f+pQ8EzzyWyEELRp2C72MsmONarnomei0W7dVYbsgx
UNFXLZiXBdtNjPCMv1u6ZnhmQMIu9Fhjtz18LwIDAQABAoIBAQCXDtDNyZQcBgwP
17RzdN8MDPOWJbQO+aRtES2S3J9k/jSPkPscj3/QDe0iyOtRaMn3cFuor4HhzAgr
FPCB/sAJyJrFRX9DwuWUQv7SjkmLOhG5Rq9FsdYoMXBbggO+3g8xE8qcX1k2r7vW
kDW2lRnLDzPtt+IYxoHgh02yvIYnPn1VLuryM0+7eUrTVmdHQ1IGS5RRAGvtoFjf
4QhkkwLzZzCBly/iUDtNiincwRx7wUG60c4ZYu/uBbdJKT+8NcDLnh6lZyJIpGns
jjZvvYA9kgCB2QgQ0sdvm0rA31cbc72Y2lNdtE30DJHCQz/K3X7T0PlfR191NMiX
E7h2I/oBAoGBAPor1TqsQK0tT5CftdN6j49gtHcPXVoJQNhPyQldKXADIy8PVGnn
upG3y6wrKEb0w8BwaZgLAtqOO/TGPuLLFQ7Ln00nEVsCfWYs13IzXjCCR0daOvcF
3FCb0IT/HHym3ebtk9gvFY8Y9AcV/GMH5WkAufWxAbB7J82M//afSghPAoGBAMys
g9D0FYO/BDimcBbUBpGh7ec+XLPaB2cPM6PtXzMDmkqy858sTNBLLEDLl+B9yINi
FYcxpR7viNDAWtilVGKwkU3hM514k+xrEr7jJraLzd0j5mjp55dnmH0MH0APjEV0
qum+mIJmWXlkfKKIiIDgr6+FwIiF5ttSbX1NwnYhAoGAMRvjqrXfqF8prEk9xzra
7ZldM7YHbEI+wXfADh+En+FtybInrvZ3UF2VFMIQEQXBW4h1ogwfTkn3iRBVje2x
v4rHRbzykjwF48XPsTJWPg2E8oPK6Wz0F7rOjx0JOYsEKm3exORRRhru5Gkzdzk4
lok29/z8SOmUIayZHo+cV88CgYEAgPsmhoOLG19A9cJNWNV83kHBfryaBu0bRSMb
U+6+05MtpG1pgaGVNp5o4NxsdZhOyB0DnBL5D6m7+nF9zpFBwH+s0ftdX5sg/Rfs
1Eapmtg3f2ikRvFAdPVf7024U9J4fzyqiGsICQUe1ZUxxetsumrdzCrpzh80AHrN
bO2X4oECgYEAxoVXNMdFH5vaTo3X/mOaCi0/j7tOgThvGh0bWcRVIm/6ho1HXk+o
+kY8ld0vCa7VvqT+iwPt+7x96qesVPyWQN3+uLz9oL3hMOaXCpo+5w8U2Qxjinod
uHnNjMTXCVxNy4tkARwLRwI+1aV5PMzFSi+HyuWmBaWOe19uz3SFbYs=
-----END RSA PRIVATE KEY-----
""",
    None,
)

try:
    with open(KEY_NAME, "rb") as f:
        private_key = load_pem_private_key(f.read(), None, default_backend())
except FileNotFoundError:
    LOGGER.info("Generating a new private key...")
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    with open(KEY_NAME, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

server_addr = input("Enter the address of your Caseta bridge device: ")

csr = (
    x509.CertificateSigningRequestBuilder()
    .subject_name(CERT_SUBJECT)
    .sign(private_key, hashes.SHA256(), default_backend())
)

ssl_context = SSL.Context(SSL.TLSv1_2_METHOD)
ssl_context.get_cert_store().add_cert(LAP_CA)
ssl_context.use_certificate(LAP_CERT)
ssl_context.use_privatekey(LAP_KEY)


class JsonSocket:
    """A socket that reads and writes json objects."""

    def __init__(self, socket):
        """Create a JsonSocket wrapping the provided socket."""
        self._socket = socket

    def read_json(self):
        """Read an object."""
        buffer = b""
        while not buffer.endswith(b"\r\n"):
            buffer += self._socket.read(1024)

        LOGGER.debug("received: %s", buffer)
        return json.loads(buffer.decode("UTF-8"))

    def write_json(self, obj):
        """Write an object."""
        buffer = ("%s\r\n" % json.dumps(obj)).encode("ASCII")
        self._socket.write(buffer)
        LOGGER.debug("sent: %s", buffer)


with socket.create_connection((server_addr, 8083)) as raw_socket:
    tls_socket = SSL.Connection(ssl_context, raw_socket)
    tls_socket.set_connect_state()

    sock = JsonSocket(tls_socket)

    LOGGER.info("Connected to bridge.")
    print(
        "Press and release the small black button on the back of the Caseta"
        + "bridge..."
    )
    while True:
        message = sock.read_json()
        if message.get("Header", {}).get("ContentType", "").startswith(
            "status;"
        ) and "PhysicalAccess" in (
            message.get("Body", {}).get("Status", {}).get("Permissions", [])
        ):
            break

    LOGGER.info("Getting my certificate...")
    csr_text = csr.public_bytes(serialization.Encoding.PEM).decode("ASCII")
    sock.write_json(
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
                    "DisplayName": "get_lutron_cert.py",
                    "DeviceUID": "000000000000",
                    "Role": "Admin",
                },
            },
        }
    )
    while True:
        message = sock.read_json()
        if message.get("Header", {}).get("ClientTag") == "get-cert":
            break
    cert_text = message["Body"]["SigningResult"]["Certificate"]
    with open(CERT_NAME, "wb") as f:
        f.write(cert_text.encode("ASCII"))
    root_text = message["Body"]["SigningResult"]["RootCertificate"]
    with open(CA_CERT_NAME, "wb") as f:
        f.write(root_text.encode("ASCII"))
    LOGGER.info("Got certificates")
    tls_socket.shutdown()

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
ssl_context.load_verify_locations(CA_CERT_NAME)
ssl_context.load_cert_chain(CERT_NAME, KEY_NAME)
ssl_context.verify_mode = ssl.CERT_REQUIRED

with socket.create_connection((server_addr, 8081)) as raw_socket:
    with ssl_context.wrap_socket(raw_socket) as tls_socket:
        socket = JsonSocket(tls_socket)
        socket.write_json(
            {
                "CommuniqueType": "ReadRequest",
                "Header": {"Url": "/server/1/status/ping"},
            }
        )

        while True:
            leap_response = socket.read_json()
            if leap_response.get("CommuniqueType") == "ReadResponse":
                break

LOGGER.info(
    "Successfully connected to bridge, running LEAP Server version %s"
    % leap_response["Body"]["PingResponse"]["LEAPVersion"]
)
