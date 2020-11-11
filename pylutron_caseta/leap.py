"""LEAP protocol layer."""

import asyncio
import json
import logging
import re
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from . import BridgeDisconnectedError
from .messages import Response

_LOG = logging.getLogger(__name__)
_DEFAULT_LIMIT = 2 ** 16


def _make_tag() -> str:
    return str(uuid.uuid4())


class LeapProtocol:
    """A wrapper for making LEAP calls."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Wrap a reader and writer with a LEAP request and response protocol."""
        self._reader = reader
        self._writer = writer
        self._in_flight_requests: Dict[str, "asyncio.Future[Response]"] = {}
        self._tagged_subscriptions: Dict[str, Callable[[Response], None]] = {}
        self._unsolicited_subs: List[Callable[[Response], None]] = []

    async def request(
        self,
        communique_type: str,
        url: str,
        body: Optional[dict] = None,
        tag: Optional[str] = None,
    ) -> Response:
        """Make a request to the bridge and return the response."""
        if tag is None:
            tag = _make_tag()

        future: asyncio.Future = asyncio.get_running_loop().create_future()

        cmd = {
            "CommuniqueType": communique_type,
            "Header": {"ClientTag": tag, "Url": url},
        }

        if body is not None:
            cmd["Body"] = body

        self._in_flight_requests[tag] = future

        # remove cancelled tasks
        def clean_up(future):
            if future.cancelled():
                self._in_flight_requests.pop(tag, None)

        future.add_done_callback(clean_up)

        try:
            text = json.dumps(cmd).encode("UTF-8")
            _LOG.debug("sending %s", text)
            self._writer.write(text + b"\r\n")

            return await future
        finally:
            self._in_flight_requests.pop(tag, None)

    async def run(self):
        """Event monitoring loop."""
        while not self._reader.at_eof():
            received = await self._reader.readline()

            if received == b"":
                break

            resp_json = json.loads(received.decode("UTF-8"))

            if isinstance(resp_json, dict):
                tag = resp_json.get("Header", {}).pop("ClientTag", None)
                if tag is not None:
                    in_flight = self._in_flight_requests.pop(tag, None)
                    if in_flight is not None and not in_flight.done():
                        _LOG.debug("received: %s", resp_json)
                        in_flight.set_result(Response.from_json(resp_json))
                    else:
                        subscription = self._tagged_subscriptions.get(tag, None)
                        if subscription is not None:
                            _LOG.debug(
                                "received for subscription %s: %s", tag, resp_json
                            )
                            subscription(Response.from_json(resp_json))
                        else:
                            _LOG.error(
                                "Was not expecting message with tag %s: %s",
                                tag,
                                resp_json,
                            )
                else:
                    _LOG.debug("Received message with no tag: %s", resp_json)
                    obj = Response.from_json(resp_json)
                    for handler in self._unsolicited_subs:
                        try:
                            handler(obj)
                        except Exception:  # pylint: disable=broad-except
                            _LOG.exception(
                                "Got exception from unsolicited message handler"
                            )

    async def subscribe(
        self,
        url: str,
        callback: Callable[[Response], None],
        body: Optional[dict] = None,
        communique_type: str = "SubscribeRequest",
        tag: Optional[str] = None,
    ) -> Tuple[Response, str]:
        """
        Subscribe to events from the bridge.

        This is similar to a normal request, except that the bridge is expected to send
        additional responses with the same tag value at a later time. These additional
        responses will be handled by the provided callback.

        This returns both the response message and a string that will be required for
        unsubscribing (not implemented).
        """
        if not callable(callback):
            raise TypeError("callback must be callable")

        if tag is None:
            tag = _make_tag()

        response = await self.request(communique_type, url, body, tag=tag)

        status = response.Header.StatusCode
        if status is not None and status.is_successful():
            self._tagged_subscriptions[tag] = callback
            _LOG.debug("Subscribed to %s as %s", url, tag)

        return (response, tag)

    def subscribe_unsolicited(self, callback: Callable[[Response], None]):
        """
        Subscribe to notifications of unsolicited events.

        The provided callback will be executed when the bridge sends an untagged
        response message.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._unsolicited_subs.append(callback)

    def unsubscribe_unsolicited(self, callback: Callable[[Response], None]):
        """Unsubscribe from notifications of unsolicited events."""
        self._unsolicited_subs.remove(callback)

    def close(self):
        """Disconnect."""
        self._writer.close()

        for request in self._in_flight_requests.values():
            request.set_exception(BridgeDisconnectedError())
        self._in_flight_requests.clear()
        self._tagged_subscriptions.clear()


async def open_connection(
    host: str, port: int, *, limit: int = _DEFAULT_LIMIT, **kwds
) -> LeapProtocol:
    """Open a stream and wrap it with LEAP."""
    reader, writer = await asyncio.open_connection(host, port, limit=limit, **kwds)
    return LeapProtocol(reader, writer)


_HREFRE = re.compile(r"/(?:\D+)/(\d+)(?:\/\D+)?")


def id_from_href(href: str) -> str:
    """Get an id from any kind of href.

    Raises ValueError if id cannot be determined from the format
    """
    match = _HREFRE.match(href)

    if match is None:
        raise ValueError(f"Cannot find ID from href {href!r}")

    return match.group(1)
