"""Guide the user through pairing and save the necessary files."""

# based on https://git.io/vxjpt
# original script by Mathieu Hofman

# `python -m venv env`
# bash: `source ./env/bin/activate`
# powershell: `./env/scripts/activate.ps1`
# `pip install cryptography==2.1.3 requests==2.18.4`
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
import re
import requests
import socket
import ssl

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from urllib.parse import urlencode

LOGIN_SERVER = "device-login.lutron.com"
APP_CLIENT_ID = ("e001a4471eb6152b7b3f35e549905fd8589dfcf57eb680b6fb37f20878c"
                 "28e5a")
APP_CLIENT_SECRET = ("b07fee362538d6df3b129dc3026a72d27e1005a3d1e5839eed5ed18"
                     "c63a89b27")
APP_OAUTH_REDIRECT_PAGE = "lutron_app_oauth_redirect"
CERT_SUBJECT = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Pennsylvania"),
    x509.NameAttribute(NameOID.LOCALITY_NAME, "Coopersburg"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME,
                       "Lutron Electronics Co., Inc."),
    x509.NameAttribute(NameOID.COMMON_NAME, "Lutron Caseta App")
])

BASE_URL = "https://%s/" % LOGIN_SERVER
REDIRECT_URI = "https://%s/%s" % (LOGIN_SERVER, APP_OAUTH_REDIRECT_PAGE)

AUTHORIZE_URL = ("%soauth/authorize?%s" % (BASE_URL,
                                           urlencode({
                                               "client_id": APP_CLIENT_ID,
                                               "redirect_uri": REDIRECT_URI,
                                               "response_type": "code"
                                           })))

try:
    with open('caseta.key', 'rb') as f:
        private_key = load_pem_private_key(f.read(), None, default_backend())
except FileNotFoundError:
    private_key = rsa.generate_private_key(public_exponent=65537,
                                           key_size=2048,
                                           backend=default_backend())
    with open('caseta.key', 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))

try:
    with open('caseta.crt', 'rb') as f:
        certificate = x509.load_pem_x509_certificate(f.read(),
                                                     default_backend())
except FileNotFoundError:
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(CERT_SUBJECT)
           .sign(private_key, hashes.SHA256(), default_backend()))

    print("Open Browser and login at %s" % AUTHORIZE_URL)

    redirected_url = input("Enter the URL (of the \"error\" page you got "
                           "redirected to (or the code in the URL): ")

    oauth_code = re.sub(r'^(.*?code=){0,1}([0-9a-f]*)\s*$', r'\2',
                        redirected_url)

    if oauth_code == '':
        raise "Invalid code"

    token = requests.post("%soauth/token" % BASE_URL, data={
        "code": oauth_code,
        "client_id": APP_CLIENT_ID,
        "client_secret": APP_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"}).json()

    if token["token_type"] != "bearer":
        raise ("Received invalid token %s. Try generating a new code "
               "(one time use).") % token

    access_token = token["access_token"]

    pairing_request_content = {
        "remote_signs_app_certificate_signing_request":
        csr.public_bytes(serialization.Encoding.PEM).decode('ASCII')
    }

    pairing_response = requests.post(
        "%sapi/v1/remotepairing/application/user" % BASE_URL,
        json=pairing_request_content,
        headers={
            "X-DeviceType": "Caseta,RA2Select",
            "Authorization": "Bearer %s" % access_token
        }
    ).json()

    app_cert = pairing_response["remote_signs_app_certificate"]
    remote_cert = pairing_response["local_signs_remote_certificate"]

    with open('caseta.crt', 'wb') as f:
        f.write(app_cert.encode('ASCII'))
        f.write(remote_cert.encode('ASCII'))

server_addr = input("Enter the address of your Caseta bridge device: ")

ssl_context = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain('caseta.crt', 'caseta.key')
ssl_context.verify_mode = ssl.CERT_NONE

with socket.create_connection((server_addr, 8081)) as raw_socket:
    with ssl_context.wrap_socket(raw_socket) as ssl_socket:
        ca_der = ssl_socket.getpeercert(True)
        ca_cert = x509.load_der_x509_certificate(ca_der, default_backend())
        with open('caseta-bridge.crt', 'wb') as f:
            f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

        ssl_socket.send(("%s\r\n" % json.dumps({
            "CommuniqueType": "ReadRequest",
            "Header": {"Url": "/server/1/status/ping"}
        })).encode('UTF-8'))

        while True:
            buffer = b''
            while not buffer.endswith(b'\r\n'):
                buffer += ssl_socket.read()

            leap_response = json.loads(buffer.decode('UTF-8'))
            if leap_response['CommuniqueType'] == 'ReadResponse':
                break

print("Successfully connected to bridge, running LEAP Server version %s" %
      leap_response['Body']['PingResponse']['LEAPVersion'])
