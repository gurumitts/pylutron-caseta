"""Command line interface."""

import asyncio
import functools
import json
import logging
import socket
import ssl
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, List, Optional, TextIO
from urllib.parse import urlparse

import click
import xdg
from zeroconf import DNSQuestionType, InterfaceChoice, IPVersion, ServiceListener
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

import pylutron_caseta.leap
from pylutron_caseta.pairing import async_pair


def _cli_main(main):
    """Wrap a method to run in asyncio."""

    def wrapper(*args, **kwargs):
        logging.basicConfig()
        logging.getLogger("pylutron_caseta").setLevel(logging.WARN)

        return asyncio.run(main(*args, **kwargs))

    return functools.update_wrapper(wrapper, main)


class _CertOption(click.Option):
    """An option that accesses a certificate file for the given address."""

    def __init__(self, *args, **kwargs):
        self.suffix = kwargs.pop("suffix")
        self.host = kwargs.pop("host")
        super().__init__(*args, **kwargs)

    def get_default(self, ctx: click.Context, call: bool = True) -> Optional[Path]:
        if not call:
            return None

        config_home = xdg.xdg_config_home()
        base = config_home / "pylutron_caseta"

        config_home.mkdir(exist_ok=True)
        base.mkdir(mode=0o700, exist_ok=True)

        return base / (self.host(ctx) + self.suffix)


class _AddressCertOption(_CertOption):
    """An option that access a certificate file for a plain hostname."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, host=lambda ctx: ctx.params["address"])


class _ResourceCertOption(_CertOption):
    """An option that access a certificate file for a URL."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, **kwargs, host=lambda ctx: ctx.params["resource"].hostname
        )


class _UrlParamType(click.ParamType):
    """A parameter that is urlparsed."""

    name = "url"

    def convert(
        self, value: str, param: Optional[click.Parameter], ctx: Optional[click.Context]
    ) -> urllib.parse.ParseResult:
        if "://" not in value:
            value = f"leap://{value}"
        return urlparse(value, "leap", False)


URL = _UrlParamType()


@click.command()
@_cli_main
@click.argument("address")
@click.option(
    "--cacert",
    type=click.File("w", encoding="ascii", atomic=True),
    cls=_AddressCertOption,
    suffix="-bridge.crt",
    help="The path to the CA certificate.",
)
@click.option(
    "--cert",
    type=click.File("w", encoding="ascii", atomic=True),
    cls=_AddressCertOption,
    suffix=".crt",
    help="The path to the client certificate.",
)
@click.option(
    "--key",
    type=click.File("w", encoding="ascii", atomic=True),
    cls=_AddressCertOption,
    suffix=".key",
    help="The path to the client certificate key.",
)
async def lap_pair(address: str, cacert: TextIO, cert: TextIO, key: TextIO):
    """
    Perform LAP pairing.

    This program connects to a Lutron bridge device and initiates the LAP pairing
    process. The user will be prompted to press a physical button on the bridge, and
    certificate files will be generated on the local computer.

    By default, the certificate files will be placed in
    $XDG_CONFIG_HOME/pylutron_caseta, named after the address of the bridge device. The
    leap tool will look for certificates in the same location.
    """

    def _ready():
        click.echo(
            "Press the small black button on the back of the bridge to complete "
            "pairing."
        )

    data = await async_pair(address, _ready)
    cacert.write(data["ca"])
    cert.write(data["cert"])
    key.write(data["key"])
    click.echo(f"Successfully paired with {data['version']}")


@click.command()
@_cli_main
@click.option(
    "-i",
    "--interface",
    multiple=True,
    help=(
        "Limit scanned network interfaces. "
        "This option may be specified multiple times."
    ),
)
@click.option(
    "-t",
    "--timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="The amount of time (in seconds) to wait for replies.",
)
async def leap_scan(interface: List[str], timeout: float):
    """
    Scan for LEAP devices on the local network.

    This program uses MDNS to locate LEAP devices on networks connected to the local
    computer.
    """

    async def _async_add_service(zeroconf, type_, name):
        info = AsyncServiceInfo(type_, name)
        await info.async_request(zeroconf, 3000, question_type=DNSQuestionType.QU)

        addresses = [f"{info.server}:{info.port}"]

        for address in info.addresses_by_version(IPVersion.V4Only):
            addresses.append(f"{socket.inet_ntop(socket.AF_INET, address)}:{info.port}")

        for address in info.addresses_by_version(IPVersion.V6Only):
            addresses.append(
                f"[{socket.inet_ntop(socket.AF_INET6, address)}]:{info.port}"
            )

        click.echo(" ".join(addresses))

    class _Listener(ServiceListener):
        def remove_service(self, *args):
            pass

        def add_service(self, zc, type_, name):
            asyncio.ensure_future(_async_add_service(zc, type_, name))

        def update_service(self, *args):
            pass

    interfaces: Any = InterfaceChoice.All
    if len(interface) > 0:
        interfaces = interface

    async with AsyncZeroconf(interfaces) as azc:
        await azc.zeroconf.async_wait_for_start()
        browser = AsyncServiceBrowser(azc.zeroconf, "_leap._tcp.local.", _Listener())
        await asyncio.sleep(timeout)
        await browser.async_cancel()


@asynccontextmanager
async def _connect(
    resource: urllib.parse.ParseResult, cacert: str, cert: str, key: str
) -> AsyncIterator[pylutron_caseta.leap.LeapProtocol]:
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_context.load_verify_locations(cacert)
    ssl_context.load_cert_chain(cert, key)

    if resource.hostname is None:
        raise ValueError("Hostname must be specified")

    protocol = await pylutron_caseta.leap.open_connection(
        resource.hostname,
        resource.port or 8081,
        server_hostname="",
        ssl=ssl_context,
        family=socket.AF_INET,
    )
    run = asyncio.ensure_future(protocol.run())

    try:
        yield protocol
    finally:
        run.cancel()
        try:
            await run
        except asyncio.CancelledError:
            pass
        protocol.close()
        try:
            await protocol.wait_closed()
        except ssl.SSLError:
            pass


@click.command()
@_cli_main
@click.pass_context
@click.option(
    "-X",
    "--request",
    default="ReadRequest",
    help="The CommuniqueType to send.",
    show_default=True,
)
@click.option(
    "--cacert",
    type=click.Path(True, dir_okay=False),
    cls=_ResourceCertOption,
    suffix="-bridge.crt",
    help="The path to the CA certificate.",
)
@click.option(
    "-E",
    "--cert",
    type=click.Path(True, dir_okay=False),
    cls=_ResourceCertOption,
    suffix=".crt",
    help="The path to the client certificate.",
)
@click.option(
    "--key",
    type=click.Path(True, dir_okay=False),
    cls=_ResourceCertOption,
    suffix=".key",
    help="The path to the client certificate key.",
)
@click.option("-d", "--data", help="The JSON data to send with the request.")
@click.option(
    "-f",
    "--fail",
    is_flag=True,
    help="Exit when the status code does not indicate success.",
)
@click.option(
    "-o",
    "--output",
    type=click.File("w", encoding="utf8"),
    default="-",
    help="Save the response into a file.",
)
@click.option(
    "-v", "--verbose", is_flag=True, help="Output the response headers as well."
)
@click.argument("resource", type=URL)
async def leap(
    ctx: click.Context,
    request: str,
    resource: urllib.parse.ParseResult,
    cacert: str,
    cert: str,
    key: str,
    data: Optional[str],
    fail: bool,
    output: TextIO,
    verbose: bool,
):
    """
    Make a single LEAP request.

    LEAP is similar to JSON over HTTP, and this tool is similar to Curl.
    """
    async with _connect(resource, cacert, cert, key) as connection:
        if data is None:
            body = None
        else:
            body = json.loads(data)

        res = resource.path
        if resource.query is not None and len(resource.query) > 0:
            res += f"?{resource.query}"

        response = await connection.request(request, res, body)

    if (
        fail
        and response.Header.StatusCode is not None
        and not response.Header.StatusCode.is_successful()
    ):
        ctx.exit(1)

    if verbose:
        # LeapProtocol discards the original JSON so reconstruct it here.
        output.write(
            json.dumps(
                {
                    "Header": {
                        "StatusCode": str(response.Header.StatusCode),
                        "Url": response.Header.Url,
                        "MessageBodyType": response.Header.MessageBodyType,
                    },
                    "CommuniqueType": response.CommuniqueType,
                    "Body": response.Body,
                }
            )
        )
    else:
        output.write(json.dumps(response.Body))

    output.write("\n")
