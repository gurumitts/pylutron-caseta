"""LEAP protocol layer."""

import asyncio
import json
import logging
import re

_LOG = logging.getLogger(__name__)
_DEFAULT_LIMIT = 2 ** 16


async def open_connection(host=None, port=None, *,
                          limit=_DEFAULT_LIMIT, **kwds):
    """Open a stream and wrap it with LEAP."""
    connection = await asyncio.open_connection(host, port,
                                               limit=limit, **kwds)
    return LeapReader(connection[0]), LeapWriter(connection[1])


class LeapReader:
    """A wrapper for reading the LEAP protocol."""

    def __init__(self, reader):
        """Initialize the reader."""
        self._reader = reader

    def exception(self):
        """Get the exception."""
        return self._reader.exception()

    async def read(self):
        """
        Read a single object.

        If EOF is received, return `None`.

        If invaid data is received, raise ValueError.
        """
        received = await self._reader.readline()

        if received == b'':
            return None
        _LOG.debug('received %s', received)

        try:
            return json.loads(received.decode('UTF-8'))
        except ValueError as err:
            _LOG.error("Invalid LEAP response: %s", received)
            self._reader.set_exception(err)
            raise err

    def at_eof(self):
        """Return `True` if the underlying stream is at EOF."""
        return self._reader.at_eof()


class LeapWriter:
    """A wrapper for writing the LEAP protocol."""

    def __init__(self, writer):
        """Initialize the writer."""
        self._writer = writer

    def abort(self):
        """Abort the underlying stream."""
        self._writer.transport.abort()

    async def drain(self):
        """Let the underlying stream drain its buffer."""
        await self._writer.drain()

    def write(self, obj):
        """Write a single object."""
        text = json.dumps(obj).encode('UTF-8')
        _LOG.debug('sending %s', text)
        self._writer.write(text + b'\r\n')

    def write_eof(self):
        """Write EOF to the underlying stream."""
        self._writer.write_eof()


_HREFRE = re.compile(r'/(?:\D+)/(\d+)(?:\/\D+)?')


def id_from_href(href):
    """Get an id from any kind of href.

    Raises ValueError if id cannot be determined from the format
    """
    try:
        return _HREFRE.match(href).group(1)
    except IndexError:
        raise ValueError("Cannot find ID from href {}".format(href))
